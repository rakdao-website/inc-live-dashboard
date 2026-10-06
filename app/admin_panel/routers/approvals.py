"""Approval queue: kiosk-created visitors stay Pending until a reviewer decides."""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.admin_panel import permissions
from app.admin_panel.clock import utcnow
from app.admin_panel.audit import record_audit
from app.admin_panel.capture_files import delete_capture_image, resolve_capture_image
from app.admin_panel.deps import AdminPrincipal, current_admin, admin_gate
from app.admin_panel.models import VisitorApproval
from app.admin_panel.responses import failure, success
from app.database import get_db
from app.face_gallery import deserialize_embedding
from app.face_recognition_service import get_face_recognition_service
from app.models import FaceWebMatch, UnknownFaceCapture, Visitor

logger = logging.getLogger("admin.approvals")
router = APIRouter(prefix="/admin/approvals", tags=["Admin approvals"], dependencies=[Depends(admin_gate)])


class ApproveRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)
    enroll_face: bool = True
    consent_confirmed: bool = False  # approver attests the person agreed to face recognition


class RejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


def _iso(value):
    return value.isoformat() if value else None


def approval_payload(db: Session, approval: VisitorApproval, role: str) -> dict:
    visitor = db.get(Visitor, approval.visitor_id)
    capture = db.get(UnknownFaceCapture, approval.capture_id) if approval.capture_id else None
    chosen = db.get(FaceWebMatch, approval.chosen_web_match_id) if approval.chosen_web_match_id else None
    can_see_links = permissions.can_see_web_links(role)

    chosen_payload = None
    if chosen is not None:
        chosen_payload = {
            "rank": chosen.rank,
            "score": chosen.score,
            "provider": chosen.provider,
            "source_url": chosen.source_url if can_see_links else None,
            "thumbnail_base64": chosen.thumbnail_base64 if can_see_links else None,
        }
    try:
        entered = json.loads(approval.entered_details) if approval.entered_details else {}
    except ValueError:
        entered = {}

    return {
        "approval_id": approval.approval_id,
        "status": approval.status,
        "source": approval.source,
        "created_at": _iso(approval.created_at),
        "visitor": None
        if visitor is None
        else {
            "visitor_id": visitor.visitor_id,
            "visitor_name": visitor.visitor_name,
            "visitor_phone": visitor.visitor_phone,
            "visitor_email": visitor.visitor_email,
            "visitor_type": visitor.visitor_type,
            "company_name": visitor.company_name,
            "face_consent_given": visitor.face_consent_given,
        },
        "entered_details": entered,
        "match": {
            "method": "web_suggestion" if approval.source == "web_suggestion" else "manual_entry",
            "best_gallery_score": approval.best_gallery_score,
            "web_search_status": capture.web_search_status if capture else None,
        },
        "chosen_suggestion": chosen_payload,
        "capture_id": approval.capture_id,
        "has_image": bool(capture and resolve_capture_image(capture.image_path)),
        "has_face_data": bool(capture and capture.embedding),
        "decided_by": approval.decided_by_username,
        "decided_at": _iso(approval.decided_at),
        "decision_reason": approval.decision_reason,
    }


@router.get("")
def list_approvals(
    request: Request,
    status: str = Query(default="pending", pattern="^(pending|approved|rejected|all)$"),
    q: Optional[str] = Query(default=None, max_length=80),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AdminPrincipal = Depends(current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(VisitorApproval)
    if status != "all":
        query = query.filter(VisitorApproval.status == status)
    if q:
        like = f"%{q}%"
        query = query.join(Visitor, Visitor.visitor_id == VisitorApproval.visitor_id).filter(
            Visitor.visitor_name.ilike(like) | Visitor.visitor_phone.ilike(like)
        )
    total = query.count()
    rows = query.order_by(VisitorApproval.created_at.desc(), VisitorApproval.approval_id.desc()).offset(offset).limit(limit).all()
    return success(
        "Approvals retrieved",
        {"items": [approval_payload(db, r, principal.role) for r in rows], "total": total, "limit": limit, "offset": offset},
    )


@router.get("/{approval_id}")
def get_approval(approval_id: int, principal: AdminPrincipal = Depends(current_admin), db: Session = Depends(get_db)):
    approval = db.get(VisitorApproval, approval_id)
    if approval is None:
        return failure(404, "Approval not found", "APPROVAL_NOT_FOUND")
    return success("Approval retrieved", approval_payload(db, approval, principal.role))


@router.get("/{approval_id}/image")
def get_approval_image(approval_id: int, db: Session = Depends(get_db)):
    approval = db.get(VisitorApproval, approval_id)
    capture = db.get(UnknownFaceCapture, approval.capture_id) if approval and approval.capture_id else None
    path = resolve_capture_image(capture.image_path) if capture else None
    if path is None:
        return failure(404, "No face image for this approval", "APPROVAL_IMAGE_MISSING")
    return FileResponse(str(path), media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


def _identifiers(visitor: Visitor) -> set[str]:
    names = {f"visitor:{visitor.visitor_id}"}
    if visitor.face_reference_id:
        names.add(visitor.face_reference_id)
    return names


@router.post("/{approval_id}/approve")
def approve(
    approval_id: int,
    payload: ApproveRequest,
    request: Request,
    principal: AdminPrincipal = Depends(current_admin),
    db: Session = Depends(get_db),
):
    approval = db.get(VisitorApproval, approval_id)
    if approval is None:
        return failure(404, "Approval not found", "APPROVAL_NOT_FOUND")
    if approval.status != "pending":
        return failure(409, f"This request was already {approval.status}.", "APPROVAL_ALREADY_DECIDED")
    visitor = db.get(Visitor, approval.visitor_id)
    if visitor is None:
        return failure(404, "The visitor no longer exists.", "VISITOR_NOT_FOUND")
    capture = db.get(UnknownFaceCapture, approval.capture_id) if approval.capture_id else None

    enrol = bool(payload.enroll_face and capture is not None and capture.embedding)
    if enrol and not visitor.face_consent_given:
        if not payload.consent_confirmed:
            return failure(
                422,
                "Face consent is not recorded. Confirm the person consented, or approve without the face.",
                "CONSENT_REQUIRED",
            )
        visitor.face_consent_given = True
        visitor.face_consent_at = utcnow()

    now = utcnow()
    visitor.approval_status = "approved"
    visitor.updated_at = now
    approval.status = "approved"
    approval.decided_by_user_id = principal.user_id
    approval.decided_by_username = principal.username
    approval.decided_at = now
    approval.decision_reason = payload.reason

    identifier = f"visitor:{visitor.visitor_id}"
    if enrol:
        try:
            get_face_recognition_service().database.replace_person(identifier, [deserialize_embedding(capture.embedding)])
        except Exception:
            db.rollback()
            logger.exception("Face enrolment failed while approving %s", approval_id)
            return failure(503, "Could not store the face. Nothing was approved; try again.", "FACE_ENROLL_FAILED")
        visitor.face_reference_id = identifier
    if capture is not None:
        capture.status = "linked"
        capture.linked_visitor_id = visitor.visitor_id

    record_audit(
        db, principal, "approval.approve", "visitor", visitor.visitor_id,
        {"approval_id": approval_id, "face_enrolled": enrol, "consent_attested": bool(payload.consent_confirmed), "reason": payload.reason},
        request=request,
    )
    db.commit()
    return success("Visitor approved", {"approval_id": approval_id, "visitor_id": visitor.visitor_id, "face_enrolled": enrol})


@router.post("/{approval_id}/reject")
def reject(
    approval_id: int,
    payload: RejectRequest,
    request: Request,
    principal: AdminPrincipal = Depends(current_admin),
    db: Session = Depends(get_db),
):
    approval = db.get(VisitorApproval, approval_id)
    if approval is None:
        return failure(404, "Approval not found", "APPROVAL_NOT_FOUND")
    if approval.status != "pending":
        return failure(409, f"This request was already {approval.status}.", "APPROVAL_ALREADY_DECIDED")
    visitor = db.get(Visitor, approval.visitor_id)
    capture = db.get(UnknownFaceCapture, approval.capture_id) if approval.capture_id else None

    removed_vectors = 0
    if visitor is not None:
        database = get_face_recognition_service().database
        try:
            for name in _identifiers(visitor):
                removed_vectors += database.delete_person(name)
        except Exception:
            logger.exception("Could not remove face vectors while rejecting %s", approval_id)
            return failure(503, "Could not remove the face data. Nothing was changed; try again.", "FACE_DELETE_FAILED")
        visitor.approval_status = "rejected"
        visitor.face_reference_id = None
        visitor.updated_at = utcnow()

    image_deleted = False
    if capture is not None:
        capture.embedding = None
        capture.status = "dismissed"
        image_deleted = delete_capture_image(capture.image_path)

    approval.status = "rejected"
    approval.decided_by_user_id = principal.user_id
    approval.decided_by_username = principal.username
    approval.decided_at = utcnow()
    approval.decision_reason = payload.reason
    record_audit(
        db, principal, "approval.reject", "visitor", approval.visitor_id,
        {"approval_id": approval_id, "vectors_removed": removed_vectors, "image_deleted": image_deleted, "reason": payload.reason},
        request=request,
    )
    db.commit()
    return success("Visitor rejected", {"approval_id": approval_id, "vectors_removed": removed_vectors})
