from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.kiosk_schemas import (
    ActivityItem,
    ActivityMetricsRead,
    BookingRead,
    EcosystemMetricRead,
    EventRead,
    HeaderResponse,
    SectorRead,
    ZoneRead,
)
from app.models import ActivityFeed, Booking, EcosystemMetric, Event, Sector
from app.services import activity_message, now_dubai, schedule_status, zones_with_status


router = APIRouter(prefix="/api", tags=["kiosk"])


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
        "top_sector": metric.top_sector,
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


@router.get("/sectors", response_model=list[SectorRead])
def list_sectors(db: Session = Depends(get_db)) -> list[Sector]:
    return db.scalars(select(Sector).order_by(Sector.display_order)).all()


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
            "visitor_is_client": booking.visitor_is_client,
            "date": booking.booking_date,
            "start": booking.booking_time_start,
            "end": booking.booking_time_end,
            "zone_id": booking.zone_id,
            "zone_name": booking.zone.zone_name,
            "status": schedule_status(booking.booking_date, booking.booking_time_start, booking.booking_time_end, now),
        }
        for booking in bookings
    ]


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
