from fastapi import APIRouter, Depends
from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.kiosk_schemas import (
    ActivityItem,
    ActivityMetricsRead,
    BookingRead,
    EcosystemMetricRead,
    EventRead,
    HeaderResponse,
    ScreenBookingCreate,
    ZoneRead,
)
from app.kiosk_flow_services import (
    create_activity,
    create_visit_session as create_visit_session_record,
    normalize_phone,
    schedule_has_conflict,
)
from app.models import ActivityFeed, Booking, EcosystemMetric, Event, Visitor, Zone
from app.services import activity_message, booking_status, now_dubai, schedule_status, zones_with_status


router = APIRouter(prefix="/api", tags=["kiosk"])


def error_response(message: str, error_code: str, details=None) -> dict:
    return {
        "success": False,
        "message": message,
        "error_code": error_code,
        "details": details,
    }


def screen_booking_type(zone_type: str) -> str:
    if zone_type == "meeting_room":
        return "meeting"
    if zone_type == "studio":
        return "studio"
    return "office"


def booking_payload(booking: Booking, zone_name: str, now=None) -> dict:
    now = now or now_dubai()
    return {
        "booking_id": booking.booking_id,
        "booking_type": booking.booking_type,
        "name": booking.booking_name,
        "visitor_name": booking.visitor_name,
        "visitor_phone": booking.visitor_phone,
        "visitor_email": booking.visitor_email,
        "visitor_is_client": booking.visitor_is_client,
        "date": booking.booking_date,
        "start": booking.booking_time_start,
        "end": booking.booking_time_end,
        "zone_id": booking.zone_id,
        "zone_name": zone_name,
        "status": booking_status(booking, now),
    }


def find_or_create_screen_visitor(payload: ScreenBookingCreate, db: Session) -> Visitor:
    normalized_phone = normalize_phone(payload.visitor_phone)
    visitor = None
    for row in db.query(Visitor).all():
        if normalize_phone(row.visitor_phone) == normalized_phone:
            visitor = row
            break

    if visitor is None:
        visitor = Visitor(
            visitor_name=payload.visitor_name,
            visitor_phone=normalized_phone,
            visitor_email=payload.visitor_email,
            visitor_type="client" if payload.visitor_is_client else "visitor",
            is_existing_client=payload.visitor_is_client,
            lead_source="map_screen",
        )
        db.add(visitor)
        if hasattr(db, "flush"):
            db.flush()
        return visitor

    visitor.visitor_name = payload.visitor_name
    if payload.visitor_email:
        visitor.visitor_email = payload.visitor_email
    visitor.is_existing_client = visitor.is_existing_client or payload.visitor_is_client
    visitor.lead_source = visitor.lead_source or "map_screen"
    return visitor


def header_payload() -> dict:
    now = now_dubai()
    return {
        "title": "Innovation City Live Dashboard",
        "subtitle": "Ground Floor Live Overview",
        "screen": "Digital Kiosk",
        "date": now.date(),
        "day": now.strftime("%A"),
        "display_date": now.strftime("%A, %d %B %Y"),
        "time": now.strftime("%H:%M"),
        "timezone": "Asia/Dubai",
        "status": "Live",
        "last_updated": now,
    }


def activity_metrics_payload(db: Session, now=None) -> dict:
    now = now or now_dubai()
    zone_data = zones_with_status(db)
    occupied = sum(z["status"] == "occupied" for z in zone_data)
    active_meetings = sum(z["status"] == "occupied" and z["zone_type"] == "meeting_room" for z in zone_data)
    events_today_count = len(db.scalars(select(Event.event_id).where(Event.event_date == now.date())).all())
    event_visitors = db.scalar(
        select(func.coalesce(func.sum(Event.event_attendee_count), 0))
        .where(Event.event_date == now.date())
    ) or 0
    booking_visitors = db.scalar(
        select(func.count(Booking.booking_id))
        .where(
            Booking.booking_date == now.date(),
            Booking.visitor_name.is_not(None),
        )
    ) or 0
    return {
        "zones_occupied": occupied,
        "zones_total": sum(z["is_bookable"] for z in zone_data),
        "meetings_active": active_meetings,
        "visitors_count": int(event_visitors) + int(booking_visitors),
        "events_today_count": events_today_count,
    }


def latest_ecosystem_payload(db: Session) -> dict | None:
    metric = db.scalar(select(EcosystemMetric).order_by(EcosystemMetric.snapshot_date.desc()))
    if metric is None:
        return None
    return {
        "snapshot_date": metric.snapshot_date,
        "active_companies": metric.active_companies,
        "active_licenses": metric.active_licenses,
    }


@router.get("/header", response_model=HeaderResponse)
def header() -> dict:
    return header_payload()


@router.get("/zones", response_model=list[ZoneRead])
def list_zones(db: Session = Depends(get_db)) -> list[dict]:
    return zones_with_status(db)


@router.get("/activity-metrics", response_model=ActivityMetricsRead)
def activity_metrics(db: Session = Depends(get_db)) -> dict:
    return activity_metrics_payload(db)


@router.get("/ecosystem-metrics", response_model=EcosystemMetricRead | None)
def ecosystem_metrics(db: Session = Depends(get_db)) -> dict | None:
    return latest_ecosystem_payload(db)


@router.get("/events", response_model=list[EventRead])
def list_events(db: Session = Depends(get_db)) -> list[dict]:
    now = now_dubai()
    events = db.scalars(
        select(Event)
        .options(joinedload(Event.zone))
        .order_by(Event.event_date, Event.event_time_start)
    ).all()
    return [
        {
            "event_id": event.event_id,
            "name": event.event_name,
            "date": event.event_date,
            "start": event.event_time_start,
            "end": event.event_time_end,
            "location": event.event_location,
            "organizer": event.event_organizer,
            "attendee_count": event.event_attendee_count,
            "zone_id": event.zone_id,
            "zone_name": event.zone.zone_name,
            "status": schedule_status(event.event_date, event.event_time_start, event.event_time_end, now),
        }
        for event in events
    ]


@router.get("/bookings", response_model=list[BookingRead])
def list_bookings(db: Session = Depends(get_db)) -> list[dict]:
    now = now_dubai()
    bookings = db.scalars(
        select(Booking)
        .options(joinedload(Booking.zone))
        .order_by(Booking.booking_date, Booking.booking_time_start)
    ).all()
    return [
        {
            "booking_id": booking.booking_id,
            "booking_type": booking.booking_type,
            "name": booking.booking_name,
            "visitor_name": booking.visitor_name,
            "visitor_phone": booking.visitor_phone,
            "visitor_email": booking.visitor_email,
            "visitor_is_client": booking.visitor_is_client,
            "date": booking.booking_date,
            "start": booking.booking_time_start,
            "end": booking.booking_time_end,
            "zone_id": booking.zone_id,
            "zone_name": booking.zone.zone_name,
            "status": booking_status(booking, now),
        }
        for booking in bookings
    ]


@router.post("/screen/bookings", response_model=BookingRead, status_code=status.HTTP_201_CREATED)
def create_screen_booking(payload: ScreenBookingCreate, db: Session = Depends(get_db)) -> dict | JSONResponse:
    zone = db.get(Zone, payload.zone_id)
    if zone is None:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=error_response("Zone not found", "ZONE_NOT_FOUND"),
        )
    if not zone.is_bookable:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=error_response("Zone is not bookable", "ZONE_NOT_BOOKABLE"),
        )
    if zone.is_closed:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=error_response("Zone is closed", "ZONE_CLOSED"),
        )

    if schedule_has_conflict(
        db,
        zone_id=payload.zone_id,
        schedule_date=payload.booking_date,
        start_time=payload.booking_time_start,
        end_time=payload.booking_time_end,
    ):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=error_response(
                "This booking overlaps another booking or event in the selected zone",
                "BOOKING_OVERLAP",
            ),
        )

    visitor = find_or_create_screen_visitor(payload, db)
    visit_session = create_visit_session_record(
        db,
        visitor=visitor,
        recognition_method="manual",
        current_selected_service="screen_booking",
        visit_purpose=f"Booked {zone.zone_name}",
        notes="Created from map screen",
    )
    booking = Booking(
        visitor_id=getattr(visitor, "visitor_id", None),
        zone_id=zone.zone_id,
        booking_type=screen_booking_type(zone.zone_type),
        booking_name=f"{zone.zone_name} Booking",
        visitor_name=payload.visitor_name,
        visitor_phone=normalize_phone(payload.visitor_phone),
        visitor_email=payload.visitor_email,
        visitor_is_client=payload.visitor_is_client,
        booking_start_date=payload.booking_date,
        booking_end_date=payload.booking_date,
        booking_date=payload.booking_date,
        booking_time_start=payload.booking_time_start,
        booking_time_end=payload.booking_time_end,
    )
    db.add(booking)

    visitor_id = getattr(visitor, "visitor_id", None)
    if visitor_id is not None:
        create_activity(
            db,
            visitor_id=visitor_id,
            visit_session_id=visit_session.visit_session_id,
            selected_service="screen_booking",
            visit_purpose=f"Booked {zone.zone_name}",
            notes=f"Created from map screen for {payload.booking_time_start.strftime('%H:%M')} to {payload.booking_time_end.strftime('%H:%M')}",
        )

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

    db.refresh(booking)
    return booking_payload(booking, zone.zone_name)


@router.get("/activity-feed", response_model=list[ActivityItem])
def list_activity_feed(db: Session = Depends(get_db)) -> list[dict]:
    feed = db.scalars(
        select(ActivityFeed)
        .options(
            joinedload(ActivityFeed.zone),
            joinedload(ActivityFeed.event).joinedload(Event.zone),
            joinedload(ActivityFeed.booking).joinedload(Booking.zone),
        )
        .order_by(ActivityFeed.occurred_at.desc())
        .limit(20)
    ).all()
    return [
        {
            "feed_id": item.feed_id,
            "occurred_at": item.occurred_at,
            "category": item.category,
            "action": item.activity_action,
            "message": activity_message(item),
        }
        for item in feed
    ]
