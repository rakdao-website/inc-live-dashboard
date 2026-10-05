"""Sync tests run against the real local Postgres inside a rolled-back transaction."""
from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy.orm import Session

from app.database import engine
from app.models import Booking, Visitor, VisitorCheckIn, Zone
from app.spacebring_sync import sync_bookings

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, active=None, canceled=None, single=None):
        self.active, self.canceled = active or [], canceled or []
        self.single = single or {}
        self.fail = False

    def list_bookings(self, *, starts_from=None, status=None, **_):
        if self.fail:
            from app.spacebring_client import SpacebringError

            raise SpacebringError("down")
        return self.canceled if status == "canceled" else self.active

    def get_booking(self, booking_id):
        from app.spacebring_client import SpacebringError

        if booking_id not in self.single:
            raise SpacebringError("gone", status_code=404)
        return self.single[booking_id]


def sb(id, start="2026-11-15T06:00:00.000Z", end="2026-11-15T06:30:00.000Z", resource="res-t", **extra):
    return {"id": id, "resourceRef": resource, "startDate": start, "endDate": end, "title": "From Spacebring",
            "status": "confirmed", "createDate": "2026-11-01T00:00:00.000Z", **extra}


@pytest.fixture
def db():
    try:
        connection = engine.connect()
    except Exception:
        pytest.skip("Postgres is not available")
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        if not session.query(Booking).filter(Booking.spacebring_booking_id.isnot(None)).count() == 0:
            pytest.skip("database already holds Spacebring bookings; not a clean test database")
        zone = session.get(Zone, "TTS_9") or Zone(zone_id="TTS_9", zone_name="Sync Test Room", zone_type="studio", is_bookable=True)
        zone.spacebring_resource_id = "res-t"
        session.add(zone)
        session.flush()
    except Exception:
        session.close(); outer.rollback(); connection.close()
        pytest.skip("database schema is not migrated for Spacebring")
    yield session
    session.close()
    outer.rollback()
    connection.close()


def mirror_of(db, sb_id):
    return db.query(Booking).filter(Booking.spacebring_booking_id == sb_id).first()


def test_new_spacebring_booking_is_mirrored_in_local_time(db):
    result = sync_bookings(db, FakeClient(active=[sb("sb-new")]), now=NOW)

    row = mirror_of(db, "sb-new")
    assert result.created == 1
    assert (row.zone_id, row.booking_date) == ("TTS_9", date(2026, 11, 15))
    assert (row.booking_time_start, row.booking_time_end) == (time(10, 0), time(10, 30))  # Dubai = UTC+4
    assert row.booking_type == "studio"


def test_moved_booking_updates_mirror_and_second_run_is_a_noop(db):
    sync_bookings(db, FakeClient(active=[sb("sb-1")]), now=NOW)
    moved = FakeClient(active=[sb("sb-1", start="2026-11-15T08:00:00.000Z", end="2026-11-15T09:00:00.000Z")])

    assert sync_bookings(db, moved, now=NOW).updated == 1
    assert mirror_of(db, "sb-1").booking_time_start == time(12, 0)
    assert str(sync_bookings(db, moved, now=NOW)) == "created=0 updated=0 deleted=0 skipped=0"


def test_cancelled_in_spacebring_removes_mirror_and_keeps_check_in(db):
    sync_bookings(db, FakeClient(active=[sb("sb-2")]), now=NOW)
    row = mirror_of(db, "sb-2")
    visitor = Visitor(visitor_name="T", visitor_phone="+971500000999")
    db.add(visitor); db.flush()
    check_in = VisitorCheckIn(visitor_id=visitor.visitor_id, booking_id=row.booking_id,
                              check_in_status="booking_found", match_method="phone")
    db.add(check_in); db.flush()

    result = sync_bookings(db, FakeClient(canceled=[sb("sb-2", status="canceled")]), now=NOW)

    assert result.deleted == 1 and mirror_of(db, "sb-2") is None
    db.refresh(check_in)
    assert check_in.booking_id is None  # history kept, reference dropped


def test_booking_missing_from_both_lists_is_deleted_only_if_spacebring_says_gone(db):
    sync_bookings(db, FakeClient(active=[sb("sb-3"), sb("sb-4", start="2026-11-16T06:00:00.000Z", end="2026-11-16T06:30:00.000Z")]), now=NOW)

    result = sync_bookings(db, FakeClient(single={"sb-4": sb("sb-4")}), now=NOW)  # sb-3 -> 404, sb-4 still alive

    assert result.deleted == 1
    assert mirror_of(db, "sb-3") is None and mirror_of(db, "sb-4") is not None


def test_spacebring_outage_deletes_nothing(db):
    sync_bookings(db, FakeClient(active=[sb("sb-5")]), now=NOW)
    down = FakeClient(); down.fail = True

    with pytest.raises(Exception):
        sync_bookings(db, down, now=NOW)

    assert mirror_of(db, "sb-5") is not None


def test_booking_created_seconds_ago_is_left_to_the_kiosk(db):
    fresh = sb("sb-6", createDate="2026-11-14T11:59:40.000Z")
    assert sync_bookings(db, FakeClient(active=[fresh]), now=NOW).created == 0


def test_untracked_rooms_and_multi_day_bookings_are_skipped(db):
    other_room = sb("sb-7", resource="res-unknown")
    multi_day = sb("sb-8", end="2026-11-16T06:30:00.000Z")

    result = sync_bookings(db, FakeClient(active=[other_room, multi_day]), now=NOW)

    assert result.created == 0 and len(result.skipped) == 1
