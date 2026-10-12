"""Staff view of the kiosk conversation log. Opening the list or a transcript is itself audited."""

from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.admin_panel.audit import record_audit
from app.admin_panel.deps import AdminPrincipal, admin_gate
from app.admin_panel.responses import failure, success
from app.database import get_db
from app.session_log import KioskSession

router = APIRouter(prefix="/admin/sessions", tags=["Admin sessions"], dependencies=[Depends(admin_gate)])


def _summary(row: KioskSession) -> dict:
    seconds = int((row.ended_at - row.started_at).total_seconds()) if row.ended_at and row.started_at else None
    return {
        "session_id": row.session_id,
        "visitor_id": row.visitor_id,
        "visitor_label": row.visitor_label,
        "visitor_type": row.visitor_type,
        "channel": row.channel,
        "outcome": row.outcome,
        "message_count": row.message_count,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "duration_seconds": seconds,
    }


@router.get("")
def list_sessions(
    request: Request,
    q: Optional[str] = Query(default=None, max_length=80),
    visitor_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AdminPrincipal = Depends(admin_gate),
    db: Session = Depends(get_db),
):
    query = db.query(KioskSession)
    if q:
        query = query.filter(KioskSession.visitor_label.ilike(f"%{q}%"))
    if visitor_id:
        query = query.filter(KioskSession.visitor_id == visitor_id)
    if date_from:
        query = query.filter(KioskSession.started_at >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.filter(KioskSession.started_at < datetime.combine(date_to + timedelta(days=1), time.min))
    total = query.count()
    rows = query.order_by(KioskSession.started_at.desc()).offset(offset).limit(limit).all()
    record_audit(db, principal, "sessions.list", "session", None, {"q": q, "visitor_id": visitor_id, "returned": len(rows)}, request=request)
    db.commit()
    return success("Sessions retrieved", {"items": [_summary(r) for r in rows], "total": total, "limit": limit, "offset": offset})


@router.get("/{session_id}")
def get_session(session_id: str, request: Request, principal: AdminPrincipal = Depends(admin_gate), db: Session = Depends(get_db)):
    row = db.get(KioskSession, session_id)
    if row is None:
        return failure(404, "Session not found", "SESSION_NOT_FOUND")
    record_audit(db, principal, "sessions.view", "session", session_id, {"visitor_id": row.visitor_id, "messages": row.message_count}, request=request)
    db.commit()
    messages = [
        {"message_id": m.message_id, "role": m.role, "content": m.content, "occurred_at": m.occurred_at.isoformat() if m.occurred_at else None}
        for m in row.messages
    ]
    return success("Session retrieved", {**_summary(row), "messages": messages})
