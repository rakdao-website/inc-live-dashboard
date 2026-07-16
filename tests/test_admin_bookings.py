from datetime import date, datetime, time

from app.admin import admin_booking_payload


class FakeLiveBooking:
    booking_id = 10
    visitor_id = None
    zone_id = "OFF_01"
    booking_type = "office"
    booking_name = "Office 1 Booking"
    visitor_name = "Noor Deiab"
    visitor_phone = "+971501234567"
    visitor_email = "noor@example.com"
    visitor_is_client = True
    booking_start_date = date(2026, 1, 1)
    booking_end_date = date(2026, 12, 31)
    booking_date = date(2026, 1, 1)
    booking_time_start = time(9, 0)
    booking_time_end = time(17, 0)
    booking_status = "upcoming"


def test_admin_booking_payload_computes_office_status_from_date_range():
    payload = admin_booking_payload(
        FakeLiveBooking(),
        now=datetime(2026, 7, 15, 14, 30),
    )

    assert payload["booking_status"] == "live"
