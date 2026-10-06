"""Audit trail. Never put images, tokens, passwords or web-match links in `detail`."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.admin_panel.models import AdminAuditLog

logger = logging.getLogger("admin.audit")

_FORBIDDEN_KEYS = {"password", "token", "image", "image_base64", "thumbnail_base64", "embedding", "source_url"}

# Session factory used by the middleware; tests replace it.
session_factory: Callable[[], Session] | None = None


def _clean(detail: dict[str, Any] | None) -> str | None:
    if not detail:
        return None
    safe = {k: v for k, v in detail.items() if k.lower() not in _FORBIDDEN_KEYS}
    return json.dumps(safe, default=str, separators=(",", ":"))[:2000]


def record_audit(
    db: Session,
    principal,
    action: str,
    entity_type: str | None = None,
    entity_id: Any = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
    *,
    request=None,
    username: str | None = None,
) -> AdminAuditLog:
    """Add an audit row to `db`. The caller commits it with its own change."""
    if request is not None:
        request.state.audit_recorded = True
        ip_address = ip_address or client_ip(request)
    row = AdminAuditLog(
        user_id=getattr(principal, "user_id", None),
        username=getattr(principal, "username", None) or username,
        role=getattr(principal, "role", None),
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        detail=_clean(detail),
        ip_address=ip_address,
    )
    db.add(row)
    return row


def client_ip(request) -> str | None:
    return request.client.host if request.client else None


class AdminAuditMiddleware:
    """Records every successful write to /admin or /api/face that handlers did not audit themselves.

    The gate stores the signed-in user on the request; handlers that call
    `record_audit(..., request=request)` mark the request as already audited.
    """

    UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in self.UNSAFE:
            await self.app(scope, receive, send)
            return

        status_holder = {"status": 500}

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        await self.app(scope, receive, wrapped_send)

        state = scope.get("state") or {}
        principal = state.get("admin_user")
        if principal is None or state.get("audit_recorded") or not 200 <= status_holder["status"] < 300:
            return
        try:
            from starlette.concurrency import run_in_threadpool

            await run_in_threadpool(self._write, scope, principal)
        except Exception:  # an audit failure must not turn a finished request into an error
            logger.exception("Could not write the audit row for %s", scope.get("path"))

    @staticmethod
    def _write(scope, principal) -> None:
        from app.database import SessionLocal

        route = scope.get("route")
        template = getattr(route, "path", scope["path"])
        params = scope.get("path_params") or {}
        entity_id = next(iter(params.values()), None)
        segments = template.strip("/").split("/")
        index = 1 if segments[0] == "admin" else 2
        entity_type = segments[index] if len(segments) > index else None
        factory = session_factory or SessionLocal
        with factory() as db:
            record_audit(
                db,
                principal,
                action=f"{scope['method']} {template}",
                entity_type=entity_type,
                entity_id=entity_id,
                ip_address=(scope.get("client") or [None])[0],
            )
            db.commit()
