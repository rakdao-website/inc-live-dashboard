from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.admin_panel.models import AdminAuditLog
from app.admin_panel.deps import admin_gate
from app.admin_panel.responses import success
from app.database import get_db

router = APIRouter(prefix="/admin/audit-log", tags=["Admin audit"], dependencies=[Depends(admin_gate)])


def audit_payload(row: AdminAuditLog) -> dict:
    return {
        "audit_id": row.audit_id,
        "user_id": row.user_id,
        "username": row.username,
        "role": row.role,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "detail": row.detail,
        "ip_address": row.ip_address,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
    }


@router.get("")
def list_audit_log(
    q: Optional[str] = Query(default=None, max_length=80),
    action: Optional[str] = Query(default=None, max_length=80),
    username: Optional[str] = Query(default=None, max_length=80),
    entity_type: Optional[str] = Query(default=None, max_length=40),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = db.query(AdminAuditLog)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(AdminAuditLog.action.ilike(like), AdminAuditLog.username.ilike(like), AdminAuditLog.entity_id == q)
        )
    if action:
        query = query.filter(AdminAuditLog.action == action)
    if username:
        query = query.filter(AdminAuditLog.username == username.lower())
    if entity_type:
        query = query.filter(AdminAuditLog.entity_type == entity_type)
    if date_from:
        query = query.filter(AdminAuditLog.occurred_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(AdminAuditLog.occurred_at < datetime.combine(date_to + timedelta(days=1), time.min))
    total = query.count()
    rows = query.order_by(AdminAuditLog.occurred_at.desc(), AdminAuditLog.audit_id.desc()).offset(offset).limit(limit).all()
    return success("Audit log retrieved", {"items": [audit_payload(r) for r in rows], "total": total, "limit": limit, "offset": offset})
