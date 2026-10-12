"""Customer list for staff. Only masked email and phone are ever returned, whatever the role."""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.admin_panel.audit import record_audit
from app.admin_panel.deps import AdminPrincipal, admin_gate
from app.admin_panel.responses import failure, success
from app.database import get_db
from app.models import Visitor, VisitorCheckIn
from app.privacy_mask import mask_email, mask_phone
from app.session_log import KioskSession

router = APIRouter(prefix="/admin/customers", tags=["Admin customers"], dependencies=[Depends(admin_gate)])

TYPES = ("customer", "employee", "visitor")


def _payload(v: Visitor, sessions: int, visits: int = 0) -> dict:
    return {
        "visitor_id": v.visitor_id,
        "name": v.visitor_name,
        "visitor_type": v.visitor_type,
        "company_name": v.company_name,
        "email_masked": v.email_masked or mask_email(v.visitor_email),
        "phone_masked": v.phone_masked or mask_phone(v.visitor_phone),
        "approval_status": v.approval_status,
        "is_existing_client": v.is_existing_client,
        "face_consent_given": v.face_consent_given,
        "last_visit_at": v.last_visit_at.isoformat() if v.last_visit_at else None,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "sessions": sessions,
        "visits": visits,
    }


def _session_counts(db: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = db.query(KioskSession.visitor_id, func.count()).filter(KioskSession.visitor_id.in_(ids)).group_by(KioskSession.visitor_id).all()
    return {vid: n for vid, n in rows}


def _visit_counts(db: Session, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = db.query(VisitorCheckIn.visitor_id, func.count()).filter(VisitorCheckIn.visitor_id.in_(ids)).group_by(VisitorCheckIn.visitor_id).all()
    return {vid: n for vid, n in rows}


@router.get("")
def list_customers(
    request: Request,
    q: Optional[str] = Query(default=None, max_length=80),
    visitor_type: Optional[str] = Query(default=None, max_length=20),
    sort: str = Query(default="name", pattern="^(name|recent|visits)$"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AdminPrincipal = Depends(admin_gate),
    db: Session = Depends(get_db),
):
    query = db.query(Visitor)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Visitor.visitor_name.ilike(like), Visitor.company_name.ilike(like)))
    if visitor_type:
        query = query.filter(Visitor.visitor_type == visitor_type)
    total = query.count()
    if sort == "recent":
        query = query.order_by(Visitor.last_visit_at.desc().nullslast(), Visitor.visitor_name)
    elif sort == "visits":
        visit_total = db.query(VisitorCheckIn.visitor_id.label("vid"), func.count().label("n")).group_by(VisitorCheckIn.visitor_id).subquery()
        query = query.outerjoin(visit_total, visit_total.c.vid == Visitor.visitor_id).order_by(func.coalesce(visit_total.c.n, 0).desc(), Visitor.visitor_name)
    else:
        query = query.order_by(Visitor.visitor_name)
    rows = query.offset(offset).limit(limit).all()
    ids = [r.visitor_id for r in rows]
    counts = _session_counts(db, ids)
    visits = _visit_counts(db, ids)
    record_audit(db, principal, "customers.list", "customer", None, {"q": q, "type": visitor_type, "returned": len(rows)}, request=request)
    db.commit()
    return success("Customers retrieved", {"items": [_payload(r, counts.get(r.visitor_id, 0), visits.get(r.visitor_id, 0)) for r in rows], "total": total, "limit": limit, "offset": offset})


@router.get("/{visitor_id}")
def get_customer(visitor_id: int, request: Request, principal: AdminPrincipal = Depends(admin_gate), db: Session = Depends(get_db)):
    visitor = db.get(Visitor, visitor_id)
    if visitor is None:
        return failure(404, "Customer not found", "CUSTOMER_NOT_FOUND")
    record_audit(db, principal, "customers.view", "customer", visitor_id, request=request)
    db.commit()
    recent_visits = (
        db.query(VisitorCheckIn).filter(VisitorCheckIn.visitor_id == visitor_id)
        .order_by(VisitorCheckIn.check_in_time.desc()).limit(50).all()
    )
    sessions = (
        db.query(KioskSession).filter(KioskSession.visitor_id == visitor_id)
        .order_by(KioskSession.started_at.desc()).limit(50).all()
    )
    data = _payload(visitor, len(sessions) if len(sessions) < 50 else _session_counts(db, [visitor_id]).get(visitor_id, 0), _visit_counts(db, [visitor_id]).get(visitor_id, 0))
    data["recent_visits"] = [
        {"check_in_id": v.check_in_id, "at": v.check_in_time.isoformat() if v.check_in_time else None,
         "status": v.check_in_status, "method": v.match_method, "service": v.selected_service}
        for v in recent_visits
    ]
    data["recent_sessions"] = [
        {"session_id": x.session_id, "started_at": x.started_at.isoformat() if x.started_at else None,
         "message_count": x.message_count, "outcome": x.outcome}
        for x in sessions
    ]
    return success("Customer retrieved", data)
