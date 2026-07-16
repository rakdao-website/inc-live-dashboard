from datetime import time

from app.kiosk_flow_schemas import CreateProfileRequest
from app.kiosk_flow_services import (
    booking_overlaps,
    calculate_end_time,
    normalize_phone,
    service_to_booking_defaults,
)


def test_kiosk_profile_ignores_license_and_keeps_company_fields():
    payload = CreateProfileRequest(
        full_name="Aisha Khan",
        mobile_number="+971501234567",
        email="aisha@example.com",
        visitor_type="client",
        license_number="LIC-123",
        company_name="Innovation Demo",
        company_number="CO-001",
    )

    assert payload.visitor_type == "client"
    assert payload.license_number is None
    assert payload.company_name == "Innovation Demo"


def test_visitor_profile_ignores_license_number():
    payload = CreateProfileRequest(
        full_name="Omar Hassan",
        mobile_number="+971551112233",
        email="omar@example.com",
        visitor_type="visitor",
        license_number="SHOULD-NOT-STAY",
    )

    assert payload.visitor_type == "visitor"
    assert payload.license_number is None


def test_normalize_phone_accepts_common_uae_formats():
    assert normalize_phone("+971 50 123 4567") == "+971501234567"
    assert normalize_phone("050 123 4567") == "+971501234567"
    assert normalize_phone("50 123 4567") == "+971501234567"
    assert normalize_phone("00971 50 123 4567") == "+971501234567"


def test_calculate_end_time_adds_duration():
    assert calculate_end_time(time(10, 30), 90) == time(12, 0)


def test_service_to_booking_defaults_maps_studios_to_zones():
    assert service_to_booking_defaults("meeting_room") == ("meeting", "MR_1", "Meeting Room 1")
    assert service_to_booking_defaults("podcast_studio") == ("studio", "POD_1", "Podcast Studio")
    assert service_to_booking_defaults("tiktok_studio") == ("studio", "TTS_1", "TikTok Studio")


def test_booking_overlaps_detects_partial_overlap():
    assert booking_overlaps(
        existing_start=time(10, 0),
        existing_end=time(11, 0),
        requested_start=time(10, 30),
        requested_end=time(11, 30),
    )


def test_booking_overlaps_allows_adjacent_slots():
    assert not booking_overlaps(
        existing_start=time(10, 0),
        existing_end=time(11, 0),
        requested_start=time(11, 0),
        requested_end=time(12, 0),
    )
