"""Runtime settings: voice agent, face recognition, kiosk face scan, Spacebring sync, opening hours."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import runtime_settings as rs
from app.admin_panel import sync_status
from app.admin_panel.audit import record_audit
from app.admin_panel.clock import utcnow
from app.admin_panel.deps import AdminPrincipal, admin_gate, current_admin
from app.admin_panel.responses import failure, success
from app.config import settings
from app.database import get_db
from app.spacebring_client import SpacebringError, spacebring_enabled

router = APIRouter(prefix="/admin/settings", tags=["Admin settings"], dependencies=[Depends(admin_gate)])


class SettingValue(BaseModel):
    value: Any


def _definition_payload(definition: rs.Definition, overrides: dict[str, Any], rows: dict[str, Any]) -> dict:
    row = rows.get(definition.key)
    return {
        "key": definition.key,
        "label": definition.label,
        "description": definition.description,
        "kind": definition.kind,
        "choices": list(definition.choices),
        "minimum": definition.minimum,
        "maximum": definition.maximum,
        "unit": definition.unit,
        "confirm": definition.confirm,
        "effect": definition.effect,
        "value": rs.get(definition.key),
        "default": definition.default(),
        "source": "database" if definition.key in overrides else "default",
        "updated_by": getattr(row, "updated_by_username", None),
        "updated_at": row.updated_at.isoformat() if row is not None and row.updated_at else None,
    }


def _status() -> dict:
    """Facts shown next to the switches. Only yes/no and labels, never keys or tokens."""
    return {
        "facecheck_token_configured": bool(settings.facecheck_api_token),
        "openai_key_configured": bool(settings.openai_api_key),
        "gemini_key_configured": bool(getattr(settings, "gemini_api_key", "")),
        "grok_key_configured": bool(getattr(settings, "xai_api_key", "")),
        "spacebring": {
            "configured": spacebring_enabled(),
            "environment": settings.spacebring_environment.upper(),
            "location_configured": bool(settings.spacebring_location_id),
            "sync": sync_status.snapshot(),
        },
    }


@router.get("")
def list_settings(db: Session = Depends(get_db)):
    rs.invalidate()
    overrides = rs.overrides()
    rows = {row.setting_key: row for row in db.query(rs.AppSetting).all()}
    groups = []
    for group_id, title in rs.GROUP_TITLES.items():
        members = sorted((d for d in rs.DEFINITIONS if d.group == group_id), key=lambda d: d.order)
        groups.append({"id": group_id, "title": title, "settings": [_definition_payload(d, overrides, rows) for d in members]})
    return success("Settings retrieved", {"groups": groups, "status": _status()})


def _precondition_problem(key: str, value: Any) -> tuple[str, str] | None:
    if key == "face.web_search_enabled" and value is True and not settings.facecheck_api_token:
        return "FACECHECK_API_TOKEN is not set on the server, so web search cannot be switched on.", "FACECHECK_TOKEN_MISSING"
    if key == "voice.text_provider":
        if value == "gemini" and not getattr(settings, "gemini_api_key", ""):
            return "No Gemini key is configured on the server.", "PROVIDER_KEY_MISSING"
        if value == "grok" and not getattr(settings, "xai_api_key", ""):
            return "No Grok key is configured on the server.", "PROVIDER_KEY_MISSING"
    return None


@router.put("/{key}")
def update_setting(
    key: str,
    payload: SettingValue,
    request: Request,
    principal: AdminPrincipal = Depends(current_admin),
    db: Session = Depends(get_db),
):
    definition = rs.BY_KEY.get(key)
    if definition is None:
        return failure(404, "Unknown setting", "SETTING_NOT_FOUND")
    try:
        value = rs.validate(definition, payload.value)
        rs.invalidate()
        effective = {d.key: rs.get(d.key) for d in rs.DEFINITIONS}
        effective[key] = value
        rs.validate_combination(effective)
    except rs.SettingError as exc:
        return failure(422, str(exc), "INVALID_SETTING", {"key": key})
    problem = _precondition_problem(key, value)
    if problem:
        return failure(409, problem[0], problem[1])

    previous = rs.get(key)
    row = db.get(rs.AppSetting, key)
    if row is None:
        row = rs.AppSetting(setting_key=key, setting_value=json.dumps(value), updated_at=utcnow())
        db.add(row)
    row.setting_value = json.dumps(value)
    row.updated_by_user_id = principal.user_id
    row.updated_by_username = principal.username
    row.updated_at = utcnow()
    record_audit(db, principal, "settings.update", "setting", key, {"from": previous, "to": value}, request=request)
    db.commit()
    rs.invalidate()
    return success("Setting saved", {"key": key, "value": value, "previous": previous})


@router.delete("/{key}")
def reset_setting(
    key: str,
    request: Request,
    principal: AdminPrincipal = Depends(current_admin),
    db: Session = Depends(get_db),
):
    definition = rs.BY_KEY.get(key)
    if definition is None:
        return failure(404, "Unknown setting", "SETTING_NOT_FOUND")
    previous = rs.get(key)
    row = db.get(rs.AppSetting, key)
    if row is not None:
        db.delete(row)
    record_audit(db, principal, "settings.reset", "setting", key, {"from": previous, "to": definition.default()}, request=request)
    db.commit()
    rs.invalidate()
    return success("Setting reset to its default", {"key": key, "value": definition.default()})


@router.post("/spacebring/sync-now")
def sync_now(request: Request, principal: AdminPrincipal = Depends(current_admin), db: Session = Depends(get_db)):
    if not spacebring_enabled():
        return failure(409, "Spacebring is not configured on the server.", "SPACEBRING_NOT_CONFIGURED")
    try:
        result = sync_status.run_spacebring_sync(db)
    except SpacebringError as exc:
        record_audit(db, principal, "spacebring.sync_now.failed", "spacebring", None, {"error": str(exc)[:200]}, request=request)
        db.commit()
        return failure(502, "Spacebring is unavailable. Nothing was changed.", "SPACEBRING_UNAVAILABLE")
    counts = {"created": result.created, "updated": result.updated, "deleted": result.deleted, "skipped": len(result.skipped)}
    record_audit(db, principal, "spacebring.sync_now", "spacebring", None, counts, request=request)
    db.commit()
    return success("Spacebring sync finished", counts)
