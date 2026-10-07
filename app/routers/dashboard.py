"""The numbers for the live dashboard display (the TV screen): one endpoint, counts only.

Read-only and public like the other display endpoints, but it returns **only counts**: no names,
no phone numbers, no emails, not even room names. Everything is calculated live from the zones,
bookings, events and visit tables (bookings include the copies of Spacebring bookings), in Dubai
time, so no database view is needed.

Poll every 10 to 30 seconds. `as_of` says when the numbers were calculated.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Booking, Event, VisitSession, Zone
from app.routers.kiosk import latest_ecosystem_payload
from app.services import booking_is_active, now_dubai, schedule_status

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard display"])


class TypeCount(BaseModel):
    total: int
    occupied: int


class Ecosystem(BaseModel):
    snapshot_date: date
    active_companies: int
    active_licenses: int


class DashboardMetrics(BaseModel):
    as_of: datetime
    timezone: str = "Asia/Dubai"
    meetings_active: int          # meeting rooms in use right now
    rooms_occupied: int           # bookable rooms in use right now (a booking or an event)
    rooms_total: int              # bookable rooms that are open (not switched off)
    rooms_closed: int             # bookable rooms switched off by staff
    events_today: int
    events_live: int              # events happening right now
    bookings_today: int
    visitors_today: int           # different people who checked in at the kiosk today
    rooms_by_type: dict[str, TypeCount]
    ecosystem: Optional[Ecosystem] = None   # latest company and licence counts, if recorded


def _room_state(zone: Zone, now: datetime) -> str:
    """"closed", "occupied" or "available" for one bookable room."""
    if zone.is_closed:
        return "closed"
    live_event = any(
        e.event_date == now.date() and schedule_status(e.event_date, e.event_time_start, e.event_time_end, now) == "live"
        for e in zone.events
    )
    live_booking = any(booking_is_active(b, now) for b in zone.bookings)
    return "occupied" if live_event or live_booking else "available"


def build_metrics(db: Session, now: datetime | None = None) -> DashboardMetrics:
    now = now or now_dubai()
    zones = db.scalars(
        select(Zone).options(joinedload(Zone.events), joinedload(Zone.bookings)).where(Zone.is_bookable.is_(True))
    ).unique().all()
    states = [(zone, _room_state(zone, now)) for zone in zones]
    open_rooms = [(zone, state) for zone, state in states if state != "closed"]

    by_type: dict[str, TypeCount] = {}
    for zone, state in open_rooms:
        counts = by_type.setdefault(zone.zone_type, TypeCount(total=0, occupied=0))
        counts.total += 1
        counts.occupied += 1 if state == "occupied" else 0

    day_start = datetime.combine(now.date(), time.min)
    visitors = db.scalar(
        select(func.count(func.distinct(VisitSession.visitor_id))).where(
            VisitSession.visitor_id.is_not(None),
            VisitSession.check_in_time >= day_start,
            VisitSession.check_in_time < day_start + timedelta(days=1),
        )
    ) or 0
    events = db.scalars(select(Event).where(Event.event_date == now.date())).all()
    bookings_today = db.scalar(select(func.count(Booking.booking_id)).where(Booking.booking_date == now.date())) or 0
    ecosystem = latest_ecosystem_payload(db)

    return DashboardMetrics(
        as_of=now,
        meetings_active=sum(1 for z, s in open_rooms if z.zone_type == "meeting_room" and s == "occupied"),
        rooms_occupied=sum(1 for _, s in open_rooms if s == "occupied"),
        rooms_total=len(open_rooms),
        rooms_closed=sum(1 for _, s in states if s == "closed"),
        events_today=len(events),
        events_live=sum(1 for e in events if schedule_status(e.event_date, e.event_time_start, e.event_time_end, now) == "live"),
        bookings_today=int(bookings_today),
        visitors_today=int(visitors),
        rooms_by_type=by_type,
        ecosystem=Ecosystem(**ecosystem) if ecosystem else None,
    )


@router.get("/metrics", response_model=DashboardMetrics)
def dashboard_metrics(response: Response, db: Session = Depends(get_db)) -> DashboardMetrics:
    """Every number the dashboard tiles need, in one call. Counts only, no personal data."""
    response.headers["Cache-Control"] = "no-store"
    return build_metrics(db)
