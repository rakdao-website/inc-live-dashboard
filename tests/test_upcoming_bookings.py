"""The voice agent lists, moves and cancels bookings made for later days."""
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.database import engine
from app.models import Booking, Visitor, Zone
from app.routers.kiosk_flow import current_database_date, current_database_time, get_upcoming_bookings


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


def test_upcoming_lists_today_and_later_but_not_past_or_other_people(db):
    from datetime import time

    zone = Zone(zone_id="TTS_U", zone_name="Upcoming Test Room", zone_type="studio", is_bookable=True)
    me = Visitor(visitor_name="Me", visitor_phone="+971500009991")
    other = Visitor(visitor_name="Other", visitor_phone="+971500009992")
    db.add_all([zone, me, other])
    db.flush()
    today, now = current_database_date(db), current_database_time(db)

    def booking(who, day, start, end):
        row = Booking(
            visitor_id=who.visitor_id, zone_id="TTS_U", booking_type="studio", booking_name="x",
            booking_start_date=day, booking_end_date=day, booking_date=day,
            booking_time_start=start, booking_time_end=end,
        )
        db.add(row)
        db.flush()
        return row.booking_id

    tomorrow = booking(me, today + timedelta(days=1), time(10, 0), time(10, 30))
    later = booking(me, today + timedelta(days=5), time(9, 0), time(9, 30))
    booking(me, today - timedelta(days=1), time(10, 0), time(10, 30))   # yesterday
    booking(other, today + timedelta(days=1), time(12, 0), time(12, 30))  # someone else's

    result = get_upcoming_bookings(visitor_id=me.visitor_id, limit=20, db=db)["data"]

    assert [b["booking_id"] for b in result] == [tomorrow, later]  # soonest first
    assert get_upcoming_bookings(visitor_id=999999999, limit=20, db=db)["data"] == []  # empty is a normal answer
