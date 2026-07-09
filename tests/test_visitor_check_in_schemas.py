from datetime import datetime

from app.schemas import VisitorCheckInCreate, VisitorCreate


def test_visitor_create_accepts_phase_two_identity_fields_without_face_status():
    visitor = VisitorCreate(
        visitor_name="Maya Ahmed",
        visitor_phone="+971501234567",
        visitor_email="maya@example.com",
        is_existing_client=True,
        license_number="LIC-2026-001",
        face_consent_given=True,
        face_consent_at=datetime(2026, 7, 8, 10, 30),
        lead_source="screen_2_check_in",
    )

    assert visitor.license_number == "LIC-2026-001"
    assert visitor.face_consent_given is True
    assert visitor.lead_source == "screen_2_check_in"
    assert not hasattr(visitor, "face_enrollment_status")


def test_visitor_check_in_tracks_face_status_on_the_check_in_record():
    check_in = VisitorCheckInCreate(
        visitor_id=1,
        visitor_phone="+971501234567",
        booking_id=7,
        check_in_status="booking_found",
        match_method="face",
        selected_service="meeting_room",
        face_enrollment_status="enrolled",
    )

    assert check_in.face_enrollment_status == "enrolled"
    assert check_in.match_method == "face"
    assert check_in.check_in_status == "booking_found"
