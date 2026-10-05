"""Spacebring -> Postgres booking sync.

Spacebring is the system of record. The kiosk writes through Spacebring and
mirrors the row itself; this sync catches everything that changes in
Spacebring without us: bookings made in the Spacebring app, moved or cancelled
there, or left behind when a mirror write failed.

It reconciles upcoming bookings only (from the start of today, local time):
  * in Spacebring, not in Postgres      -> insert a mirror row
  * in both, times differ               -> update the mirror
  * in Postgres, cancelled/gone in SB   -> delete the mirror
It never touches rows without a spacebring_booking_id (meeting rooms, legacy).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.models import ActivityFeed, Booking, VisitorCheckIn, Zone
from app.spacebring_client import SpacebringClient, SpacebringError

logger = logging.getLogger("spacebring.sync")

# A booking this young may still be mid-flight in the kiosk (Spacebring row
# created, Postgres mirror not yet committed). Leave it to the kiosk.
RECENT_BOOKING_GRACE = timedelta(seconds=60)

BOOKING_TYPE_BY_ZONE_TYPE = {"studio": "studio", "meeting_room": "meeting", "office": "office"}


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"created={self.created} updated={self.updated} deleted={self.deleted} "
            f"skipped={len(self.skipped)}"
        )


def delete_mirror_booking(db: Session, booking: Booking) -> None:
    """Remove a mirror row; other tables keep their rows, minus the reference."""
    db.query(VisitorCheckIn).filter(VisitorCheckIn.booking_id == booking.booking_id).update(
        {VisitorCheckIn.booking_id: None}
    )
    db.query(ActivityFeed).filter(ActivityFeed.booking_id == booking.booking_id).update(
        {ActivityFeed.booking_id: None}
    )
    db.delete(booking)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _customer_name(sb_booking: dict) -> str | None:
    user = (sb_booking.get("customer") or {}).get("user") or sb_booking.get("userOwner") or {}
    name = " ".join(part for part in (user.get("name"), user.get("surname")) if part)
    return name or None


def sync_bookings(db: Session, client: SpacebringClient, now: datetime | None = None) -> SyncResult:
    tz = ZoneInfo(settings.spacebring_timezone)
    now = now or datetime.now(timezone.utc)
    window_start_local = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = window_start_local.astimezone(timezone.utc)

    # Fetch everything first: if either call fails nothing below runs, so a
    # Spacebring outage can never look like "all bookings were cancelled".
    active = client.list_bookings(starts_from=window_start, status="confirmed,tentative")
    canceled = client.list_bookings(starts_from=window_start, status="canceled")
    active_ids = {b["id"] for b in active}
    canceled_ids = {b["id"] for b in canceled}

    zones = {
        z.spacebring_resource_id: z
        for z in db.query(Zone).filter(Zone.spacebring_resource_id.isnot(None)).all()
    }
    mirrors = {
        b.spacebring_booking_id: b
        for b in db.query(Booking)
        .filter(Booking.spacebring_booking_id.isnot(None), Booking.booking_date >= window_start_local.date())
        .all()
    }
    result = SyncResult()

    for sb in active:
        zone = zones.get(sb.get("resourceRef"))
        if zone is None:
            continue  # a room we do not track
        start = _parse_utc(sb["startDate"]).astimezone(tz)
        end = _parse_utc(sb["endDate"]).astimezone(tz)
        mirror = mirrors.get(sb["id"])

        if mirror is None:
            created = _parse_utc(sb["createDate"]) if sb.get("createDate") else None
            if created and now - created < RECENT_BOOKING_GRACE:
                continue
            booking_type = BOOKING_TYPE_BY_ZONE_TYPE.get(zone.zone_type)
            if booking_type is None or end.date() != start.date() or end.time() <= start.time():
                result.skipped.append(f"{sb['id']} (multi-day or unsupported room type)")
                continue
            db.add(
                Booking(
                    zone_id=zone.zone_id,
                    booking_type=booking_type,
                    booking_name=zone.zone_name,
                    visitor_name=_customer_name(sb) or sb.get("title"),
                    booking_start_date=start.date(),
                    booking_end_date=start.date(),
                    booking_date=start.date(),
                    booking_time_start=start.time().replace(microsecond=0),
                    booking_time_end=end.time().replace(microsecond=0),
                    spacebring_booking_id=sb["id"],
                )
            )
            result.created += 1
            continue

        new_start, new_end = start.time().replace(microsecond=0), end.time().replace(microsecond=0)
        if end.date() != start.date() or new_end <= new_start:
            result.skipped.append(f"{sb['id']} (multi-day)")
            continue
        if (mirror.booking_date, mirror.booking_time_start, mirror.booking_time_end) != (start.date(), new_start, new_end):
            mirror.booking_start_date = mirror.booking_end_date = mirror.booking_date = start.date()
            mirror.booking_time_start, mirror.booking_time_end = new_start, new_end
            result.updated += 1

    for spacebring_id, mirror in mirrors.items():
        if spacebring_id in active_ids:
            continue
        if spacebring_id not in canceled_ids and not _is_gone(client, spacebring_id):
            continue
        delete_mirror_booking(db, mirror)
        result.deleted += 1

    db.commit()
    return result


def _is_gone(client: SpacebringClient, spacebring_id: str) -> bool:
    """A mirror in neither list: confirm with Spacebring before deleting it."""
    try:
        booking = client.get_booking(spacebring_id)
    except SpacebringError as exc:
        return exc.status_code == 404
    return booking.get("status") == "canceled"
