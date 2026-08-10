from datetime import datetime, time, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Booking, Event, VisitSession, Visitor, VisitorActivity


SERVICE_DEFAULTS = {
    "meeting_room": ("meeting", "MR_1", "Meeting Room 1"),
    "podcast_studio": ("studio", "POD_1", "Podcast Studio"),
    "tiktok_studio": ("studio", "TTS_1", "TikTok Studio")
}


def normalize_phone(value: str) -> str:
    raw_value = str(value or "").strip()
    digits = "".join(char for char in raw_value if char.isdigit())

    if not digits:
        return ""

    if digits.startswith("00"):
        digits = digits[2:]

    if digits.startswith("971"):
        return f"+{digits}"

    if digits.startswith("0") and len(digits) == 10:
        return f"+971{digits[1:]}"

    if digits.startswith("5") and len(digits) == 9:
        return f"+971{digits}"

    if raw_value.startswith("+"):
        return f"+{digits}"

    return digits


def normalize_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def split_first_name(full_name: str) -> str:
    return str(full_name or "").strip().split(" ", 1)[0]


def calculate_end_time(start_time: time, duration_minutes: int) -> time:
    anchor = datetime.combine(datetime.today(), start_time)
    return (anchor + timedelta(minutes=duration_minutes)).time().replace(second=0, microsecond=0)


def service_to_booking_defaults(service_type: str) -> tuple[str, str, str]:
    return SERVICE_DEFAULTS[service_type]


def booking_overlaps(
    *,
    existing_start: time,
    existing_end: time,
    requested_start: time,
    requested_end: time,
) -> bool:
    return requested_start < existing_end and requested_end > existing_start


def schedule_has_conflict(
    db: Session,
    *,
    zone_id: str,
    schedule_date,
    start_time: time,
    end_time: time,
    exclude_booking_id: int | None = None,
    exclude_event_id: int | None = None,
) -> bool:
    bookings = (
        db.query(Booking)
        .filter(
            Booking.zone_id == zone_id,
            Booking.booking_date == schedule_date,
        )
        .all()
    )
    for booking in bookings:
        if exclude_booking_id is not None and booking.booking_id == exclude_booking_id:
            continue
        if booking_overlaps(
            existing_start=booking.booking_time_start,
            existing_end=booking.booking_time_end,
            requested_start=start_time,
            requested_end=end_time,
        ):
            return True

    events = (
        db.query(Event)
        .filter(
            Event.zone_id == zone_id,
            Event.event_date == schedule_date,
        )
        .all()
    )
    for event in events:
        if exclude_event_id is not None and event.event_id == exclude_event_id:
            continue
        if booking_overlaps(
            existing_start=event.event_time_start,
            existing_end=event.event_time_end,
            requested_start=start_time,
            requested_end=end_time,
        ):
            return True

    return False


def find_previous_visit(db: Session, visitor_id: int) -> VisitSession | None:
    return (
        db.query(VisitSession)
        .filter(VisitSession.visitor_id == visitor_id)
        .order_by(VisitSession.check_in_time.desc(), VisitSession.visit_session_id.desc())
        .first()
    )


def create_visit_session(
    db: Session,
    *,
    visitor: Visitor,
    recognition_method: str,
    current_selected_service: str | None = None,
    visit_purpose: str | None = None,
    notes: str | None = None,
) -> VisitSession:
    previous_visit = find_previous_visit(db, visitor.visitor_id)
    session = VisitSession(
        visitor_id=visitor.visitor_id,
        recognition_method=recognition_method,
        is_returning_visitor=previous_visit is not None,
        previous_visit_id=previous_visit.visit_session_id if previous_visit else None,
        current_selected_service=current_selected_service,
        visit_purpose=visit_purpose,
        notes=notes,
    )
    db.add(session)
    if hasattr(db, "flush"):
        db.flush()
    visitor.last_visit_at = func.current_timestamp()
    return session


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