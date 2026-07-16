from datetime import date, time

from app.services import booking_status, schedule_status, zone_status


class FakeZone:
    is_closed = False

    def __init__(self, events=None, bookings=None):
        self.events = events or []
        self.bookings = bookings or []


class FakeBooking:
    def __init__(
        self,
        *,
        booking_type="meeting",
        booking_start_date=date(2026, 7, 1),
        booking_end_date=date(2026, 7, 1),
        booking_date=date(2026, 7, 1),
        booking_time_start=time(10, 0),
        booking_time_end=time(11, 0),
    ):
        self.booking_type = booking_type
        self.booking_start_date = booking_start_date
        self.booking_end_date = booking_end_date
        self.booking_date = booking_date
        self.booking_time_start = booking_time_start
        self.booking_time_end = booking_time_end


class FakeNow:
    def __init__(self, current_date, current_time):
        self._date = current_date
        self._time = current_time

    def date(self):
        return self._date

    def time(self):
        return self._time


def test_office_booking_occupies_zone_for_entire_active_date_range():
    zone = FakeZone(
        bookings=[
            FakeBooking(
                booking_type="office",
                booking_start_date=date(2026, 1, 1),
                booking_end_date=date(2026, 12, 31),
                booking_date=date(2026, 1, 1),
                booking_time_start=time(9, 0),
                booking_time_end=time(17, 0),
            )
        ]
    )

    assert zone_status(zone, FakeNow(date(2026, 7, 14), time(22, 30))) == "occupied"


def test_meeting_booking_still_uses_time_window_for_occupancy():
    zone = FakeZone(bookings=[FakeBooking()])

    assert zone_status(zone, FakeNow(date(2026, 7, 1), time(12, 0))) == "available"


def test_schedule_status_still_uses_time_window_for_non_office_items():
    assert schedule_status(date(2026, 7, 1), time(10, 0), time(11, 0), FakeNow(date(2026, 7, 1), time(10, 30))) == "live"


def test_office_booking_status_uses_date_range():
    booking = FakeBooking(
        booking_type="office",
        booking_start_date=date(2026, 1, 1),
        booking_end_date=date(2026, 12, 31),
        booking_date=date(2026, 1, 1),
    )

    assert booking_status(booking, FakeNow(date(2026, 7, 14), time(22, 30))) == "live"
