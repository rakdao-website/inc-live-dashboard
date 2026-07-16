import json
from datetime import date, time

from app.kiosk_schemas import ScreenBookingCreate
from app.models import Booking, Event, VisitSession, Visitor, VisitorActivity
from app.routers.kiosk import create_screen_booking


class FakeQuery:
    def __init__(self, rows=None):
        self.rows = rows or []

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.added = []
        self.committed = False
        self.rolled_back = False

    def get(self, model, row_id):
        for row in self.rows:
            if row.__class__.__name__.removeprefix("Fake") == model.__name__:
                if getattr(row, "zone_id", None) == row_id:
                    return row
                if getattr(row, "visitor_id", None) == row_id:
                    return row
        return None

    def query(self, model):
        rows = [
            row
            for row in [*self.rows, *self.added]
            if row.__class__ is model or row.__class__.__name__.removeprefix("Fake") == model.__name__
        ]
        return FakeQuery(rows)

    def add(self, row):
        self.added.append(row)

    def flush(self):
        for row in self.added:
            if isinstance(row, Visitor) and getattr(row, "visitor_id", None) is None:
                row.visitor_id = 12
            if isinstance(row, Booking) and getattr(row, "booking_id", None) is None:
                row.booking_id = 99
            if isinstance(row, VisitSession) and getattr(row, "visit_session_id", None) is None:
                row.visit_session_id = 33

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, row):
        self.flush()


class FakeZone:
    zone_id = "MR_1"
    zone_name = "Meeting Room 1"
    zone_type = "meeting_room"
    is_bookable = True
    is_closed = False


class FakeBooking:
    booking_id = 7
    zone_id = "MR_1"
    booking_date = date(2026, 7, 16)
    booking_time_start = time(10, 0)
    booking_time_end = time(11, 0)


class FakeEvent:
    event_id = 4
    zone_id = "MR_1"
    event_date = date(2026, 7, 16)
    event_time_start = time(11, 15)
    event_time_end = time(12, 0)


class FakeVisitSession:
    visit_session_id = 20
    visitor_id = 12
    check_in_time = "previous"


def screen_booking_payload(**overrides):
    payload = {
        "zone_id": "MR_1",
        "visitor_name": "Noor Deiab",
        "visitor_phone": "0501234567",
        "visitor_email": "noor@example.com",
        "visitor_is_client": True,
        "booking_date": date(2026, 7, 16),
        "booking_time_start": time(11, 0),
        "booking_time_end": time(11, 30),
    }
    payload.update(overrides)
    return ScreenBookingCreate(**payload)


def test_screen_booking_creates_database_booking_and_map_source_activity():
    session = FakeSession([FakeZone()])

    response = create_screen_booking(screen_booking_payload(), session)

    bookings = [row for row in session.added if isinstance(row, Booking)]
    visitors = [row for row in session.added if isinstance(row, Visitor)]
    activities = [row for row in session.added if isinstance(row, VisitorActivity)]
    visit_sessions = [row for row in session.added if isinstance(row, VisitSession)]

    assert response["booking_id"] == 99
    assert response["zone_id"] == "MR_1"
    assert response["status"] == "upcoming"
    assert session.committed is True
    assert bookings[0].booking_type == "meeting"
    assert bookings[0].booking_name == "Meeting Room 1 Booking"
    assert bookings[0].visitor_phone == "+971501234567"
    assert bookings[0].visitor_id == 12
    assert visitors[0].lead_source == "map_screen"
    assert visitors[0].visitor_type == "client"
    assert visit_sessions[0].recognition_method == "manual"
    assert visit_sessions[0].is_returning_visitor is False
    assert activities[0].visit_session_id == 33
    assert activities[0].selected_service == "screen_booking"
    assert activities[0].visit_purpose == "Booked Meeting Room 1"


def test_screen_booking_rejects_overlapping_slot():
    session = FakeSession([FakeZone(), FakeBooking()])

    response = create_screen_booking(
        screen_booking_payload(booking_time_start=time(10, 30), booking_time_end=time(11, 30)),
        session,
    )
    payload = json.loads(response.body)

    assert response.status_code == 409
    assert payload["success"] is False
    assert payload["error_code"] == "BOOKING_OVERLAP"
    assert session.committed is False


def test_screen_booking_counts_existing_visitor_as_returning_from_any_prior_visit():
    visitor = Visitor(
        visitor_id=12,
        visitor_name="Noor Deiab",
        visitor_phone="+971501234567",
        visitor_email="old@example.com",
        visitor_type="visitor",
        is_existing_client=False,
        lead_source="screen_2_check_in",
    )
    session = FakeSession([FakeZone(), visitor, FakeVisitSession()])

    response = create_screen_booking(screen_booking_payload(visitor_is_client=False), session)

    visit_sessions = [row for row in session.added if isinstance(row, VisitSession)]

    assert response["booking_id"] == 99
    assert visit_sessions[0].is_returning_visitor is True
    assert visit_sessions[0].previous_visit_id == 20


def test_screen_booking_rejects_event_conflict_in_same_zone():
    session = FakeSession([FakeZone(), FakeEvent()])

    response = create_screen_booking(
        screen_booking_payload(booking_time_start=time(11, 30), booking_time_end=time(12, 30)),
        session,
    )
    payload = json.loads(response.body)

    assert response.status_code == 409
    assert payload["success"] is False
    assert payload["error_code"] == "BOOKING_OVERLAP"
    assert session.committed is False
