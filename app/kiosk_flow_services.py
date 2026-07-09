from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from app.models import VisitSession, VisitorActivity


SERVICE_DEFAULTS = {
    "meeting_room": ("meeting", "MR_1", "Meeting Room"),
    "podcast_studio": ("studio", "POD_1", "Podcast Studio"),
    "tiktok_studio": ("studio", "TTS_1", "TikTok Studio"),
}


def normalize_phone(value: str) -> str:
    return "".join(str(value or "").split())


def normalize_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def split_first_name(full_name: str) -> str:
    return str(full_name or "").strip().split(" ", 1)[0]


def calculate_end_time(start_time: time, duration_minutes: int) -> time:
    anchor = datetime.combine(datetime.today(), start_time)
    return (anchor + timedelta(minutes=duration_minutes)).time().replace(second=0, microsecond=0)


def service_to_booking_defaults(service_type: str) -> tuple[str, str, str]:
    return SERVICE_DEFAULTS[service_type]


def find_previous_visit(db: Session, visitor_id: int) -> VisitSession | None:
    return (
        db.query(VisitSession)
        .filter(VisitSession.visitor_id == visitor_id)
        .order_by(VisitSession.check_in_time.desc(), VisitSession.visit_session_id.desc())
        .first()
    )


def create_activity(
    db: Session,
    *,
    visitor_id: int,
    visit_session_id: int | None,
    selected_service: str | None,
    visit_purpose: str | None,
    notes: str | None,
) -> VisitorActivity:
    previous = (
        db.query(VisitorActivity)
        .filter(VisitorActivity.visitor_id == visitor_id)
        .order_by(VisitorActivity.created_at.desc(), VisitorActivity.visitor_activity_id.desc())
        .first()
    )
    activity = VisitorActivity(
        visitor_id=visitor_id,
        visit_session_id=visit_session_id,
        selected_service=selected_service,
        visit_purpose=visit_purpose,
        previous_selected_service=previous.selected_service if previous else None,
        notes=notes,
    )
    db.add(activity)
    return activity
