import csv
import io
from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.admin_panel import audit_chain
from app.admin_panel.audit import record_audit
from app.admin_panel.deps import AdminPrincipal, admin_gate
from app.admin_panel.models import AdminAuditLog
from app.admin_panel.responses import success
from app.database import get_db

router = APIRouter(prefix="/admin/audit-log", tags=["Admin audit"], dependencies=[Depends(admin_gate)])

EXPORT_LIMIT = 5000


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
        "category": row.category or audit_chain.category_for(row.action),
        "chained": row.row_hash is not None,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
    }


def _filtered(db: Session, q, action, username, entity_type, category, date_from, date_to):
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
    if category:
        query = query.filter(AdminAuditLog.category == category)
    if date_from:
        query = query.filter(AdminAuditLog.occurred_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(AdminAuditLog.occurred_at < datetime.combine(date_to + timedelta(days=1), time.min))
    return query


@router.get("")
def list_audit_log(
    q: Optional[str] = Query(default=None, max_length=80),
    action: Optional[str] = Query(default=None, max_length=80),
    username: Optional[str] = Query(default=None, max_length=80),
    entity_type: Optional[str] = Query(default=None, max_length=40),
    category: Optional[str] = Query(default=None, pattern="^(auth|data_access|change|privacy|system)$"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = _filtered(db, q, action, username, entity_type, category, date_from, date_to)
    total = query.count()
    rows = query.order_by(AdminAuditLog.occurred_at.desc(), AdminAuditLog.audit_id.desc()).offset(offset).limit(limit).all()
    return success("Audit log retrieved", {"items": [audit_payload(r) for r in rows], "total": total, "limit": limit, "offset": offset})


@router.get("/verify")
def verify_audit_log(request: Request, principal: AdminPrincipal = Depends(admin_gate), db: Session = Depends(get_db)):
    """Check that no audit row was changed or removed since it was written."""
    result = audit_chain.verify(db)
    record_audit(db, principal, "audit.verify", "audit", None, {"ok": result["ok"], "checked": result["checked"]}, request=request)
    db.commit()
    return success("Audit log checked", result)


@router.get("/export")
def export_audit_log(
    request: Request,
    q: Optional[str] = Query(default=None, max_length=80),
    action: Optional[str] = Query(default=None, max_length=80),
    username: Optional[str] = Query(default=None, max_length=80),
    entity_type: Optional[str] = Query(default=None, max_length=40),
    category: Optional[str] = Query(default=None, pattern="^(auth|data_access|change|privacy|system)$"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    principal: AdminPrincipal = Depends(admin_gate),
    db: Session = Depends(get_db),
):
    """CSV of the filtered log (newest first, up to 5000 rows). The export is itself recorded."""
    rows = _filtered(db, q, action, username, entity_type, category, date_from, date_to).order_by(
        AdminAuditLog.occurred_at.desc(), AdminAuditLog.audit_id.desc()
    ).limit(EXPORT_LIMIT).all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["audit_id", "occurred_at", "category", "username", "role", "action", "entity_type", "entity_id", "detail", "ip_address"])
    for r in rows:
        p = audit_payload(r)
        # A leading = + - @ would be run as a formula by a spreadsheet, so prefix it.
        cells = [p["audit_id"], p["occurred_at"], p["category"], p["username"], p["role"], p["action"], p["entity_type"], p["entity_id"], p["detail"], p["ip_address"]]
        writer.writerow([("'" + c) if isinstance(c, str) and c[:1] in "=+-@" else c for c in cells])
    record_audit(db, principal, "audit.export", "audit", None, {"rows": len(rows), "category": category, "q": q}, request=request)
    db.commit()
    return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'})
