"""The live dashboard numbers: correct counts, and no personal data in any response."""
import json
from datetime import datetime, time

import pytest
from sqlalchemy.orm import Session

from app.database import engine
from app.models import Booking, Event, VisitSession, Visitor, Zone
from app.routers.dashboard import build_metrics
from app.services import now_dubai

SECRET_NAME, SECRET_PHONE, SECRET_EMAIL = "Zed Secretname", "+971509998877", "zed.secret@example.test"


@pytest.fixture
def db():
    try:
        connection = engine.connect()
        outer = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        session.query(Visitor.manager_email).first()
    except Exception:
        pytest.skip("Postgres with the current schema is not available")
    yield session
    session.close()
    outer.rollback()
    connection.close()


def test_metrics_counts(db):
    today = now_dubai().date()
    noon = datetime.combine(today, time(12, 0))
    base = build_metrics(db, noon)

    meeting = Zone(zone_id="DSH_M", zone_name="Dash Meeting", zone_type="meeting_room", is_bookable=True)
    studio = Zone(zone_id="DSH_S", zone_name="Dash Studio", zone_type="studio", is_bookable=True)
    closed = Zone(zone_id="DSH_C", zone_name="Dash Closed", zone_type="meeting_room", is_bookable=True, is_closed=True)
    visitor = Visitor(visitor_name=SECRET_NAME, visitor_phone=SECRET_PHONE, visitor_email=SECRET_EMAIL)
    db.add_all([meeting, studio, closed, visitor])
    db.flush()

    def booking(zone, start, end):
        db.add(Booking(zone_id=zone, booking_type="studio" if zone == "DSH_S" else "meeting", booking_name="x",
                       visitor_id=visitor.visitor_id, visitor_name=SECRET_NAME, visitor_phone=SECRET_PHONE, visitor_email=SECRET_EMAIL,
                       booking_start_date=today, booking_end_date=today, booking_date=today,
                       booking_time_start=start, booking_time_end=end))

    booking("DSH_S", time(11, 30), time(12, 30))     # live at noon
    booking("DSH_M", time(15, 0), time(16, 0))       # later today
    db.add(Event(zone_id="DSH_M", event_name="Founders Meetup", event_date=today, event_time_start=time(11, 0),
                 event_time_end=time(13, 0), event_location="Dash Meeting", event_organizer="Org", event_attendee_count=40))
    db.add(VisitSession(visitor_id=visitor.visitor_id, recognition_method="face", is_returning_visitor=False,
                        check_in_time=datetime.combine(today, time(9, 0))))
    db.flush()

    now = build_metrics(db, noon)
    assert now.rooms_total - base.rooms_total == 2           # open meeting + studio; the closed room is not counted
    assert now.rooms_closed - base.rooms_closed == 1
    assert now.rooms_occupied - base.rooms_occupied == 2     # studio booking + meeting-room event, both live
    assert now.meetings_active - base.meetings_active == 1   # the meeting room is in use by the event
    assert now.events_today - base.events_today == 1 and now.events_live - base.events_live == 1
    assert now.bookings_today - base.bookings_today == 2
    assert now.rooms_by_type["studio"].occupied - (base.rooms_by_type.get("studio").occupied if "studio" in base.rooms_by_type else 0) == 1

    later = build_metrics(db, datetime.combine(today, time(17, 0)))
    assert later.rooms_occupied - base.rooms_occupied == 0   # everything has finished by 17:00

    # No personal data anywhere in what the display receives.
    everything = json.dumps(now.model_dump(mode="json"))
    assert set(now.model_dump()) >= {"meetings_active", "rooms_occupied", "rooms_total", "events_today"}
    for secret in (SECRET_NAME, SECRET_PHONE, SECRET_EMAIL, "Secretname", "Dash Meeting", "Dash Studio", "Founders Meetup"):  # not even room or event names
        assert secret not in everything


def test_single_metrics_endpoint_counts_only():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    response = client.get("/api/dashboard/metrics")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert isinstance(body["rooms_occupied"], int) and isinstance(body["rooms_total"], int)
    # The old list endpoints are gone: only the counts are public.
    for path in ("summary", "rooms", "schedule/today", "events/today"):
        assert client.get(f"/api/dashboard/{path}").status_code == 404, path
