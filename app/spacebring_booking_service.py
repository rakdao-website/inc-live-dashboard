"""Booking flow against Spacebring (system of record) for the kiosk.

Postgres keeps a mirror row per booking. Zones without a
spacebring_resource_id (for example the meeting rooms, which do not exist in
Spacebring yet) keep using the local booking path.
"""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.config import settings
from app.models import Visitor, Zone
from app.spacebring_client import (
    SpacebringClient,
    SpacebringError,
    get_spacebring_client,
    spacebring_enabled,
)


class SlotUnavailable(Exception):
    """Spacebring says the room is not free for the requested window."""


def uses_spacebring(zone: Zone) -> bool:
    return bool(getattr(zone, "spacebring_resource_id", None)) and spacebring_enabled()


def local_to_aware(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=ZoneInfo(settings.spacebring_timezone))


def booking_title(visitor: Visitor, room_name: str) -> str:
    return f"{visitor.visitor_name} - {room_name} (kiosk)"


def owner_customer_id(visitor: Visitor) -> str | None:
    """Anonymous by default; owned only once the team enables customer ownership."""
    if settings.spacebring_use_customer_owner and visitor.spacebring_customer_id:
        return visitor.spacebring_customer_id
    return None


def ensure_free(
    zone: Zone,
    day: date,
    start: time,
    end: time,
    client: SpacebringClient | None = None,
) -> None:
    client = client or get_spacebring_client()
    result = client.check_availability(
        zone.spacebring_resource_id, local_to_aware(day, start), local_to_aware(day, end)
    )
    if not result.get("available", False):
        raise SlotUnavailable(result.get("reason", {}).get("message", "Room is not available"))


def create_in_spacebring(
    zone: Zone,
    visitor: Visitor,
    room_name: str,
    day: date,
    start: time,
    end: time,
    client: SpacebringClient | None = None,
) -> str:
    """Check availability, then create. Returns the Spacebring booking id."""
    client = client or get_spacebring_client()
    ensure_free(zone, day, start, end, client)
    created = client.create_booking(
        resource_id=zone.spacebring_resource_id,
        start=local_to_aware(day, start),
        end=local_to_aware(day, end),
        title=booking_title(visitor, room_name),
        owner_customer_id=owner_customer_id(visitor),
        send_updates=settings.spacebring_send_updates,
    )
    return created["id"]


def cancel_quietly(booking_id: str, client: SpacebringClient | None = None) -> None:
    """Best-effort rollback of a Spacebring booking after a mirror failure."""
    try:
        (client or get_spacebring_client()).cancel_booking(booking_id)
    except SpacebringError:
        pass
