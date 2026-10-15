"""Event sync tests run against the real local Postgres inside a rolled-back transaction."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.database import engine
from app.models import Event, Zone
from app.spacebring_client import SpacebringError
from app.spacebring_sync import SyncResult, sync_events

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)  # 16:00 in Dubai


class FakeClient:
    def __init__(self, events=None, gone=()):
        self.events, self.gone, self.fail = events or [], set(gone), False

    def list_events(self, **_):
        if self.fail:
            raise SpacebringError("down")
        return self.events

    def _request(self, method, path, **_):
        event_id = path.rsplit("/", 1)[-1]
        if event_id in self.gone:
            raise SpacebringError("gone", status_code=404)
        return {"event": {"id": event_id}}


def sb(id="ev-1", start="2026-11-15T12:00:00.000Z", end="2026-11-15T14:00:00.000Z", **extra):
    return {"id": id, "title": "Free Meetup", "startDate": start, "endDate": end, "venue": "Innovation City", "attendees": 0, **extra}


@pytest.fixture
def db():
    try:
        connection = engine.connect()
    except Exception:
        pytest.skip("Postgres is not available")
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        session.query(Event).filter(Event.spacebring_event_id.isnot(None)).count()
        if session.query(Zone).filter(Zone.zone_type == "event_space").count() == 0:
            session.add(Zone(zone_id="EVT_T", zone_name="Event Area", zone_type="event_space", is_bookable=False))
            session.flush()
    except Exception:
        session.close(); outer.rollback(); connection.close()
        pytest.skip("database schema is not migrated for Spacebring events")
    yield session
    session.close()
    outer.rollback()


def test_new_event_is_mirrored_in_dubai_time(db):
    result = sync_events(db, FakeClient([sb(attendees=3)]), now=NOW)
    event = db.query(Event).filter_by(spacebring_event_id="ev-1").one()
    assert result.events_created == 1
    assert (event.event_name, event.event_date, str(event.event_time_start), str(event.event_time_end)) == ("Free Meetup", date(2026, 11, 15), "16:00:00", "18:00:00")
    assert event.event_attendee_count == 3 and event.event_status == "upcoming" and event.event_location == "Innovation City"


def test_changes_update_the_mirror_and_attendees_never_go_down(db):
    sync_events(db, FakeClient([sb(attendees=2)]), now=NOW)
    event = db.query(Event).filter_by(spacebring_event_id="ev-1").one()
    event.event_attendee_count = 5  # five people chose it at the kiosk
    db.flush()
    result = sync_events(db, FakeClient([sb(title="Renamed", start="2026-11-15T13:00:00.000Z", attendees=2)]), now=NOW)
    db.refresh(event)
    assert result.events_updated == 1 and event.event_name == "Renamed" and str(event.event_time_start) == "17:00:00"
    assert event.event_attendee_count == 5
    assert sync_events(db, FakeClient([sb(title="Renamed", start="2026-11-15T13:00:00.000Z", attendees=2)]), now=NOW).events_updated == 0


def test_status_follows_the_clock(db):
    sync_events(db, FakeClient([sb("live", "2026-11-14T11:00:00.000Z", "2026-11-14T13:00:00.000Z"), sb("done", "2026-11-14T06:00:00.000Z", "2026-11-14T08:00:00.000Z")]), now=NOW)
    status = {e.spacebring_event_id: e.event_status for e in db.query(Event).filter(Event.spacebring_event_id.in_(["live", "done"]))}
    assert status == {"live": "live", "done": "ended"}


def test_deleted_event_is_removed_but_an_outage_removes_nothing(db):
    sync_events(db, FakeClient([sb()]), now=NOW)
    down = FakeClient([])
    down.fail = True
    with pytest.raises(SpacebringError):
        sync_events(db, down, now=NOW)
    assert db.query(Event).filter_by(spacebring_event_id="ev-1").count() == 1
    assert sync_events(db, FakeClient([]), now=NOW).events_deleted == 0  # missing from the list but not proven gone
    assert sync_events(db, FakeClient([], gone=["ev-1"]), now=NOW).events_deleted == 1
    assert db.query(Event).filter_by(spacebring_event_id="ev-1").count() == 0


def test_multi_day_events_are_skipped_and_local_events_untouched(db):
    local = Event(zone_id=db.query(Zone).filter(Zone.zone_type == "event_space").first().zone_id, event_name="Local", event_date=date(2026, 11, 15),
                  event_time_start=datetime(2026, 1, 1, 9).time(), event_time_end=datetime(2026, 1, 1, 10).time(), event_organizer="Staff")
    db.add(local)
    db.flush()
    result = sync_events(db, FakeClient([sb("long", "2026-11-15T12:00:00.000Z", "2026-11-17T12:00:00.000Z")]), now=NOW)
    assert result.events_created == 0 and any("multi-day" in s for s in result.skipped)
    assert db.get(Event, local.event_id) is not None
