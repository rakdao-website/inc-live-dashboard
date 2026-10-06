from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app import face_web_search
from app.admin_panel import sync_status
from app.admin_panel.models import VisitorApproval
from app.admin_panel.deps import admin_gate
from app.admin_panel.responses import success
from app.config import settings
from app.database import get_db
from app.face_recognition_service import get_face_recognition_service
from app.models import Booking, UnknownFaceCapture, VisitorCheckIn
from app.services import now_dubai
from app.spacebring_client import spacebring_enabled

router = APIRouter(prefix="/admin/dashboard", tags=["Admin dashboard"], dependencies=[Depends(admin_gate)])


def _database_ok(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    today = now_dubai().date()
    start_of_day = datetime.combine(today, datetime.min.time())

    arrivals = db.query(func.count(VisitorCheckIn.check_in_id)).filter(VisitorCheckIn.check_in_time >= start_of_day).scalar() or 0
    bookings = db.query(func.count(Booking.booking_id)).filter(Booking.booking_date == today).scalar() or 0
    pending_approvals = db.query(func.count(VisitorApproval.approval_id)).filter(VisitorApproval.status == "pending").scalar() or 0
    unknown_captures = (
        db.query(func.count(UnknownFaceCapture.capture_id))
        .filter(UnknownFaceCapture.status.in_(("pending", "web_searched")))
        .scalar()
        or 0
    )

    facecheck = face_web_search.get_account_info() if face_web_search.is_enabled() else {
        "enabled": False,
        "demo_mode": bool(settings.face_web_search_testing_mode),
        "credit_cost": settings.face_web_search_credit_cost,
        "credits_remaining": None,
        "online": None,
        "error": None,
    }

    return success(
        "Dashboard summary",
        {
            "today": today.isoformat(),
            "arrivals_today": arrivals,
            "bookings_today": bookings,
            "pending_approvals": pending_approvals,
            "unknown_captures_waiting": unknown_captures,
            "spacebring": {
                "enabled": spacebring_enabled(),
                "environment": settings.spacebring_environment.upper(),
                "sync": sync_status.snapshot(),
            },
            "facecheck": facecheck,
            "face_model_ready": get_face_recognition_service().is_ready,
            "database_ok": _database_ok(db),
        },
    )
