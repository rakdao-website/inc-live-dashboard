from datetime import time

from app.kiosk_flow_schemas import CreateProfileRequest
from app.kiosk_flow_services import calculate_end_time, service_to_booking_defaults


def test_client_profile_accepts_license_and_company_fields():
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
    assert payload.license_number == "LIC-123"
    assert payload.company_name == "Innovation Demo"


def test_visitor_profile_clears_license_number():
    payload = CreateProfileRequest(
        full_name="Omar Hassan",
        mobile_number="+971551112233",
        email="omar@example.com",
        visitor_type="visitor",
        license_number="SHOULD-NOT-STAY",
    )

    assert payload.visitor_type == "visitor"
    assert payload.license_number is None


def test_calculate_end_time_adds_duration():
    assert calculate_end_time(time(10, 30), 90) == time(12, 0)


def test_service_to_booking_defaults_maps_studios_to_zones():
    assert service_to_booking_defaults("podcast_studio") == ("studio", "POD_1", "Podcast Studio")
    assert service_to_booking_defaults("tiktok_studio") == ("studio", "TTS_1", "TikTok Studio")
