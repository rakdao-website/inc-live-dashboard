"""Bookings & rooms for staff.

Two routers, protected by `admin_gate` like every admin route:
  * /admin/bookings-overview -> resource "bookings" (permissions.py)
  * /admin/rooms-overview    -> resource "rooms"
Own prefixes on purpose: older /admin/bookings and /admin/zones routes exist
(app/admin) and are registered first, so these must not reuse those paths.

Bookings come from Postgres, which mirrors Spacebring (system of record for
the rooms linked to it) and holds the local-only rooms (meeting rooms) itself.
Booking dates and times are local wall-clock times (settings.spacebring_timezone).
Phone numbers are only ever returned masked, whatever the role.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.admin_panel.audit import record_audit
from app.admin_panel.deps import AdminPrincipal, admin_gate
from app.admin_panel.responses import failure, success
from app.config import settings
from app.database import get_db
from app.models import Booking, Zone
from app.privacy_mask import mask_phone
from app.spacebring_client import SpacebringError, get_spacebring_client, spacebring_enabled
from app.spacebring_zones import sync_zone_resource_ids

bookings_router = APIRouter(prefix="/admin/bookings-overview", tags=["Admin bookings"], dependencies=[Depends(admin_gate)])
rooms_router = APIRouter(prefix="/admin/rooms-overview", tags=["Admin rooms"], dependencies=[Depends(admin_gate)])


def _now_local() -> datetime:
    return datetime.now(ZoneInfo(settings.spacebring_timezone)).replace(tzinfo=None)


def _hhmm(value: time) -> str:
    return value.strftime("%H:%M")


def _status(b: Booking, now: datetime) -> str:
    start = datetime.combine(b.booking_date, b.booking_time_start)
    end = datetime.combine(b.booking_date, b.booking_time_end)
    if end <= now:
        return "past"
    if start <= now:
        return "in_progress"
    return "upcoming"


def _booking_payload(b: Booking, now: datetime) -> dict:
    zone = b.zone
    visitor = b.visitor
    phone = b.visitor_phone or (visitor.visitor_phone if visitor else None)
    return {
        "booking_id": b.booking_id,
        "date": b.booking_date.isoformat(),
        "start": _hhmm(b.booking_time_start),
        "end": _hhmm(b.booking_time_end),
        "zone_id": b.zone_id,
        "room_name": zone.zone_name if zone else b.booking_name,
        "room_type": zone.zone_type if zone else None,
        "booking_type": b.booking_type,
        "visitor_id": b.visitor_id,
        "visitor_name": b.visitor_name or (visitor.visitor_name if visitor else None),
        "phone_masked": (visitor.phone_masked if visitor and visitor.phone_masked else None) or mask_phone(phone),
        "is_client": bool(b.visitor_is_client),
        "source": "spacebring" if b.spacebring_booking_id else "local",
        "spacebring_booking_id": b.spacebring_booking_id,
        "status": _status(b, now),
    }


@bookings_router.get("")
def list_bookings(
    request: Request,
    when: str = Query(default="upcoming", pattern="^(upcoming|today|past|all)$"),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    zone_id: Optional[str] = Query(default=None, max_length=30),
    source: str = Query(default="all", pattern="^(all|spacebring|local)$"),
    q: Optional[str] = Query(default=None, max_length=80),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AdminPrincipal = Depends(admin_gate),
    db: Session = Depends(get_db),
):
    now = _now_local()
    today = now.date()
    query = db.query(Booking).options(joinedload(Booking.zone), joinedload(Booking.visitor))

    if when == "today":
        query = query.filter(Booking.booking_date == today)
    elif when == "upcoming":
        # Today's bookings that have not ended yet, then every later day.
        query = query.filter(
            or_(
                Booking.booking_date > today,
                (Booking.booking_date == today) & (Booking.booking_time_end > now.time()),
            )
        )
    elif when == "past":
        query = query.filter(
            or_(
                Booking.booking_date < today,
                (Booking.booking_date == today) & (Booking.booking_time_end <= now.time()),
            )
        )
    if date_from:
        query = query.filter(Booking.booking_date >= date_from)
    if date_to:
        query = query.filter(Booking.booking_date <= date_to)
    if zone_id:
        query = query.filter(Booking.zone_id == zone_id)
    if source == "spacebring":
        query = query.filter(Booking.spacebring_booking_id.isnot(None))
    elif source == "local":
        query = query.filter(Booking.spacebring_booking_id.is_(None))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Booking.visitor_name.ilike(like), Booking.booking_name.ilike(like)))

    total = query.count()
    if when == "past":
        query = query.order_by(Booking.booking_date.desc(), Booking.booking_time_start.desc())
    else:
        query = query.order_by(Booking.booking_date, Booking.booking_time_start)
    rows = query.offset(offset).limit(limit).all()

    record_audit(
        db, principal, "bookings.list", "booking", None,
        {"when": when, "zone_id": zone_id, "source": source, "q": q, "returned": len(rows)},
        request=request,
    )
    db.commit()
    return success(
        "Bookings retrieved",
        {"items": [_booking_payload(b, now) for b in rows], "total": total, "limit": limit, "offset": offset},
    )


@rooms_router.get("")
def list_rooms(
    request: Request,
    principal: AdminPrincipal = Depends(admin_gate),
    db: Session = Depends(get_db),
):
    """Every bookable (or Spacebring-linked) room with its status right now."""
    now = _now_local()
    zones = (
        db.query(Zone)
        .filter(or_(Zone.is_bookable.is_(True), Zone.spacebring_resource_id.isnot(None)))
        .order_by(Zone.zone_type, Zone.zone_name)
        .all()
    )
    todays = (
        db.query(Booking)
        .filter(Booking.booking_date == now.date(), Booking.zone_id.in_([z.zone_id for z in zones]))
        .order_by(Booking.booking_time_start)
        .all()
    )
    by_zone: dict[str, list[Booking]] = {}
    for b in todays:
        by_zone.setdefault(b.zone_id, []).append(b)

    # Each room's next booking on any day (looking 60 days ahead), so a room
    # with nothing more today still shows e.g. tomorrow's booking.
    upcoming_rows = (
        db.query(Booking)
        .filter(
            Booking.zone_id.in_([z.zone_id for z in zones]),
            Booking.booking_date >= now.date(),
            Booking.booking_date <= now.date() + timedelta(days=60),
        )
        .order_by(Booking.booking_date, Booking.booking_time_start)
        .all()
    )
    next_by_zone: dict[str, Booking] = {}
    for b in upcoming_rows:
        if b.booking_date == now.date() and b.booking_time_start <= now.time():
            continue  # already started or over
        next_by_zone.setdefault(b.zone_id, b)

    rooms = []
    for z in zones:
        bookings = by_zone.get(z.zone_id, [])
        current = next((b for b in bookings if b.booking_time_start <= now.time() < b.booking_time_end), None)
        upcoming = next_by_zone.get(z.zone_id)

        busy_until = None
        if current is not None:
            # Back-to-back bookings: keep extending "busy until".
            busy_until = current.booking_time_end
            for b in bookings:
                if b.booking_time_start <= busy_until < b.booking_time_end:
                    busy_until = b.booking_time_end

        rooms.append(
            {
                "zone_id": z.zone_id,
                "zone_name": z.zone_name,
                "zone_type": z.zone_type,
                "is_bookable": bool(z.is_bookable),
                "is_closed": bool(z.is_closed),
                "spacebring_resource_id": z.spacebring_resource_id,
                "linked": bool(z.spacebring_resource_id),
                "status_now": "closed" if z.is_closed else ("busy" if current else "available"),
                "busy_until": _hhmm(busy_until) if busy_until else None,
                "bookings_today": len(bookings),
                # Every booking today, for the day timeline on the room card.
                "today": [
                    {"start": _hhmm(b.booking_time_start), "end": _hhmm(b.booking_time_end), "visitor_name": b.visitor_name}
                    for b in bookings
                ],
                "next_booking": (
                    {
                        "date": upcoming.booking_date.isoformat(),
                        "start": _hhmm(upcoming.booking_time_start),
                        "end": _hhmm(upcoming.booking_time_end),
                        "visitor_name": upcoming.visitor_name,
                    }
                    if upcoming
                    else None
                ),
            }
        )

    record_audit(db, principal, "rooms.list", "room", None, {"returned": len(rooms)}, request=request)
    db.commit()
    return success(
        "Rooms retrieved",
        {"spacebring_enabled": spacebring_enabled(), "today": now.date().isoformat(), "now": _hhmm(now.time()), "rooms": rooms},
    )


@rooms_router.post("/spacebring-match")
def match_rooms_with_spacebring(
    request: Request,
    principal: AdminPrincipal = Depends(admin_gate),
    db: Session = Depends(get_db),
):
    """Link our rooms to Spacebring rooms by title (app/spacebring_zones.py)."""
    if not spacebring_enabled():
        return failure(409, "Spacebring is not configured on this server.", "SPACEBRING_NOT_CONFIGURED")
    try:
        spacebring_rooms = get_spacebring_client().list_rooms()
    except SpacebringError as exc:
        return failure(502, f"Could not reach Spacebring: {exc}", "SPACEBRING_UNAVAILABLE")
    result = sync_zone_resource_ids(db, spacebring_rooms)
    record_audit(
        db, principal, "rooms.spacebring_match", "room", None,
        {"mapped": len(result["mapped"]), "missing_room": result["missing_room"]},
        request=request,
    )
    db.commit()
    return success("Rooms matched with Spacebring", result)