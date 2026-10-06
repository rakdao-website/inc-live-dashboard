"""Create a Pending visitor from the kiosk. Nothing here counts as confirmed until a reviewer approves."""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from app.admin_panel.models import VisitorApproval
from app.models import FaceWebMatch, UnknownFaceCapture, Visitor


def create_pending_visitor(
    db: Session,
    *,
    full_name: str,
    phone: str,
    email: Optional[str],
    visitor_type: str,
    company_name: Optional[str] = None,
    company_number: Optional[str] = None,
    lead_source: str = "screen_2_check_in",
    capture: UnknownFaceCapture | None = None,
    chosen_rank: int | None = None,
) -> tuple[Visitor, VisitorApproval]:
    """Add the visitor and its approval record to the session (the caller commits)."""
    visitor = Visitor(
        visitor_name=full_name,
        visitor_phone=phone,
        visitor_email=email,
        visitor_type=visitor_type,
        company_name=company_name,
        company_number=company_number,
        is_existing_client=visitor_type == "client",
        lead_source=lead_source,
        approval_status="pending",
    )
    db.add(visitor)
    db.flush()

    chosen_match_id = None
    if capture is not None and chosen_rank is not None:
        match = next((m for m in capture.web_matches if m.rank == chosen_rank), None)
        chosen_match_id = match.web_match_id if match else None

    approval = VisitorApproval(
        visitor_id=visitor.visitor_id,
        status="pending",
        source="web_suggestion" if chosen_match_id is not None else "new_entry",
        capture_id=capture.capture_id if capture is not None else None,
        chosen_web_match_id=chosen_match_id,
        best_gallery_score=capture.best_gallery_score if capture is not None else None,
        entered_details=json.dumps(
            {
                "full_name": full_name,
                "mobile_number": phone,
                "email": email,
                "visitor_type": visitor_type,
                "company_name": company_name,
                "company_number": company_number,
            }
        ),
    )
    db.add(approval)
    db.flush()
    return visitor, approval
