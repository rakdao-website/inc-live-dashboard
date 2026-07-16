from datetime import date, time

import pytest
from pydantic import ValidationError

from app.schemas import BookingCreate


def test_booking_create_defaults_booking_date_to_start_date():
    booking = BookingCreate(
        zone_id="MR_1",
        booking_type="meeting",
        booking_name="Visitor Meeting",
        visitor_name="Maya Ahmed",
        visitor_phone="+971501234567",
        visitor_email="maya@example.com",
        booking_start_date=date(2026, 7, 1),
        booking_end_date=date(2026, 7, 1),
        booking_time_start=time(10, 0),
        booking_time_end=time(11, 0),
    )

    assert booking.booking_date == date(2026, 7, 1)
    assert booking.visitor_name == "Maya Ahmed"
    assert booking.visitor_phone == "+971501234567"
    assert booking.visitor_email == "maya@example.com"


def test_booking_create_rejects_end_date_before_start_date():
    with pytest.raises(ValidationError, match="booking_end_date"):
        BookingCreate(
            zone_id="OFF_1",
            booking_type="office",
            booking_name="Yearly Office Booking",
            booking_start_date=date(2026, 7, 1),
            booking_end_date=date(2026, 6, 30),
            booking_time_start=time(9, 0),
            booking_time_end=time(10, 0),
        )


def test_booking_create_rejects_end_time_before_start_time():
    with pytest.raises(ValidationError, match="booking_time_end"):
        BookingCreate(
            zone_id="MR_1",
            booking_type="meeting",
            booking_name="Invalid Meeting",
            booking_start_date=date(2026, 7, 1),
            booking_end_date=date(2026, 7, 1),
            booking_time_start=time(11, 0),
            booking_time_end=time(10, 0),
        )


def test_booking_create_rejects_times_outside_operating_hours():
    with pytest.raises(ValidationError, match="between 9:00 AM and 5:00 PM"):
        BookingCreate(
            zone_id="MR_1",
            booking_type="meeting",
            booking_name="Early Meeting",
            booking_start_date=date(2026, 7, 1),
            booking_end_date=date(2026, 7, 1),
            booking_time_start=time(8, 30),
            booking_time_end=time(9, 30),
        )

    with pytest.raises(ValidationError, match="between 9:00 AM and 5:00 PM"):
        BookingCreate(
            zone_id="MR_1",
            booking_type="meeting",
            booking_name="Late Meeting",
            booking_start_date=date(2026, 7, 1),
            booking_end_date=date(2026, 7, 1),
            booking_time_start=time(16, 30),
            booking_time_end=time(17, 30),
        )
