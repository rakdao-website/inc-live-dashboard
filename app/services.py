from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import ActivityFeed, Booking, EcosystemMetric, Event, Zone

DUBAI = ZoneInfo("Asia/Dubai")


def now_dubai() -> datetime:
    return datetime.now(DUBAI).replace(tzinfo=None)


def schedule_status(schedule_date: date, start: time, end: time, now: datetime | None = None) -> str:
    now = now or now_dubai()
    if schedule_date < now.date() or (schedule_date == now.date() and end <= now.time()):
        return "ended"
    if schedule_date == now.date() and start <= now.time() < end:
        return "live"
    return "upcoming"


def booking_is_active(booking: Booking, now: datetime | None = None) -> bool:
    now = now or now_dubai()
    if booking.booking_type == "office":
        return booking.booking_start_date <= now.date() <= booking.booking_end_date
    return schedule_status(booking.booking_date, booking.booking_time_start, booking.booking_time_end, now) == "live"


def booking_status(booking: Booking, now: datetime | None = None) -> str:
    now = now or now_dubai()
    if booking.booking_type == "office":
        if booking.booking_end_date < now.date():
            return "ended"
        if booking.booking_start_date <= now.date() <= booking.booking_end_date:
            return "live"
        return "upcoming"
    return schedule_status(booking.booking_date, booking.booking_time_start, booking.booking_time_end, now)


def zone_status(zone: Zone, now: datetime | None = None) -> str:
    if zone.is_closed:
        return "closed"
    now = now or now_dubai()
    active_event = any(schedule_status(e.event_date, e.event_time_start, e.event_time_end, now) == "live" for e in zone.events)
    active_booking = any(booking_is_active(b, now) for b in zone.bookings)
    return "occupied" if active_event or active_booking else "available"


def zones_with_status(db: Session) -> list[dict]:
    now = now_dubai()
    zones = db.scalars(select(Zone).options(joinedload(Zone.events), joinedload(Zone.bookings)).order_by(Zone.zone_name)).unique().all()
    return [
        {"zone_id": z.zone_id, "zone_name": z.zone_name, "zone_type": z.zone_type, "is_bookable": z.is_bookable,
         "is_closed": z.is_closed, "status": zone_status(z, now), "pulse": zone_status(z, now) == "available"}
        for z in zones
    ]


def activity_message(item: ActivityFeed) -> str:
    zone_name = item.event.zone.zone_name if item.event else item.booking.zone.zone_name if item.booking else item.zone.zone_name if item.zone else None
    name = item.event.event_name if item.event else item.booking.booking_name if item.booking else None
    if item.activity_action == "license_application_submitted":
        return "New license application submitted"
    messages = {
        "occupied": f"{zone_name} is now occupied",
        "available": f"{zone_name} is now available",
        "starts_in_30": f"{name} starts in 30 minutes - {zone_name}",
        "starts_in_15": f"{name} starts in 15 minutes - {zone_name}",
        "starts_now": f"{name} starts now - {zone_name}",
    }
    return messages[item.activity_action]

