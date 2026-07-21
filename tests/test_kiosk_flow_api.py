import json
from datetime import date, time

import pytest

import app.routers.kiosk_flow as kiosk_flow
from app.face_recognition_service import FaceMatch
from app.kiosk_flow_schemas import CreateFaceProfileRequest, KioskBookingCreate, LicenseLookupRequest, ProfileLookupRequest, RecognizeFaceRequest
from app.routers.kiosk_flow import (
    create_face_profile,
    create_kiosk_booking,
    event_selection_matches_activity,
    get_current_booking,
    get_current_bookings,
    license_lookup,
    list_today_events,
    profile_lookup,
    recognize_face,
    select_event,
)
from app.kiosk_flow_schemas import EventSelectionCreate


class FakeQuery:
    def __init__(self, rows=None, scalar_value=date(2026, 7, 9)):
        self.rows = rows or []
        self.scalar_value = scalar_value

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def scalar(self):
        return self.scalar_value


class FakeSession:
    def __init__(self, rows=None, scalar_values=None):
        self.rows = rows or []
        self.scalar_values = list(scalar_values or [date(2026, 7, 9), time(10, 0)])
        self.added = []
        self.committed = False

    def query(self, model):
        model_name = getattr(model, "__name__", None)
        if model_name is None:
            scalar_value = self.scalar_values.pop(0) if self.scalar_values else date(2026, 7, 9)
            return FakeQuery(scalar_value=scalar_value)

        rows = [
            row
            for row in self.rows
            if row.__class__.__name__.removeprefix("Fake") == model_name
        ]
        return FakeQuery(rows)

    def get(self, model, _id):
        for row in self.rows:
            row_name = row.__class__.__name__.removeprefix("Fake")
            if row_name == model.__name__:
                return row
        return None

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.committed = True

    def refresh(self, row):
        if row.__class__.__name__ == "FaceProfile" and getattr(row, "face_profile_id", None) is None:
            row.face_profile_id = 99


class FakeEvent:
    event_id = 1
    event_name = "AI Founders Meetup"
    event_date = date(2026, 7, 9)
    event_time_start = time(11, 0)
    event_time_end = time(12, 30)
    event_location = "Event Area"
    event_attendee_count = 2


class FakeVisitor:
    visitor_id = 7
    visitor_name = "John Smith"
    visitor_phone = "+971501234567"
    visitor_email = "john@company.com"
    visitor_type = "client"
    company_name = "INC Demo"
    company_number = "CO-7"
    license_number = "LN-889-221"
    face_consent_given = True
    face_reference_id = "visitor:7"
    last_visit_at = None


class FakeZone:
    zone_name = "Meeting Room 1"
    zone_id = "MR_1"
    zone_type = "meeting_room"
    is_bookable = True
    is_closed = False


class FakeBooking:
    booking_id = 3
    booking_type = "meeting"
    booking_name = "Investor Strategy Meeting"
    booking_date = date(2026, 7, 9)
    booking_time_start = time(10, 30)
    booking_time_end = time(11, 30)
    zone_id = "MR_1"
    zone = FakeZone()


class FakeEndedBooking(FakeBooking):
    booking_time_start = time(8, 30)
    booking_time_end = time(9, 30)


class FakeVisitSession:
    visit_session_id = 4


class FakeVisitorActivity:
    visitor_activity_id = 99
    visitor_id = 7
    visit_session_id = 4
    selected_service = "event"
    visit_purpose = "AI Founders Meetup"
    previous_selected_service = None
    notes = "Selected event #1"
    created_at = None
    current_selected_service = None


def test_recognize_face_placeholder_returns_success_envelope():
    response = recognize_face(
        RecognizeFaceRequest(simulate_mobile_number="+971000000000"),
        FakeSession(),
    )

    assert response["success"] is True
    assert response["data"]["recognized"] is False


def test_recognize_face_matches_model_name_to_visitor(monkeypatch: pytest.MonkeyPatch):
    class FakeRecognizer:
        def recognize_image_base64(self, image):
            assert image == "good-frame"
            return FaceMatch(name="John Smith", score=0.91, recognized=True)

    monkeypatch.setattr(kiosk_flow, "get_face_recognition_service", lambda: FakeRecognizer())

    response = recognize_face(RecognizeFaceRequest(image_base64="good-frame"), FakeSession([FakeVisitor()]))

    assert response["success"] is True
    assert response["data"]["recognized"] is True
    assert response["data"]["visitor_id"] == 7
    assert response["data"]["matched_name"] == "John Smith"


def test_recognize_face_matches_enrolled_visitor_identifier(monkeypatch: pytest.MonkeyPatch):
    class FakeRecognizer:
        def recognize_images_base64(self, images):
            assert images == ["weak-frame", "good-frame"]
            return FaceMatch(name="visitor:7", score=0.88, recognized=True)

    monkeypatch.setattr(kiosk_flow, "get_face_recognition_service", lambda: FakeRecognizer())

    response = recognize_face(
        RecognizeFaceRequest(images_base64=["weak-frame", "good-frame"]),
        FakeSession([FakeVisitor()]),
    )

    assert response["success"] is True
    assert response["data"]["recognized"] is True
    assert response["data"]["visitor_id"] == 7
    assert response["data"]["matched_name"] == "visitor:7"


def test_recognize_face_returns_json_error_for_unexpected_model_failure(monkeypatch: pytest.MonkeyPatch):
    class BrokenRecognizer:
        def recognize_image_base64(self, image):
            assert image == "bad-frame"
            raise RuntimeError("model crashed")

    monkeypatch.setattr(kiosk_flow, "get_face_recognition_service", lambda: BrokenRecognizer())

    response = recognize_face(RecognizeFaceRequest(image_base64="bad-frame"), FakeSession())
    payload = json.loads(response.body)

    assert response.status_code == 500
    assert payload["success"] is False
    assert payload["error_code"] == "FACE_RECOGNITION_FAILED"
    assert "try again" in payload["message"].lower()


def test_recognize_face_requires_browser_image_payload():
    response = recognize_face(RecognizeFaceRequest(), FakeSession())
    payload = json.loads(response.body)

    assert response.status_code == 400
    assert payload["success"] is False
    assert payload["error_code"] == "FACE_IMAGE_REQUIRED"
    assert "camera image" in payload["message"].lower()


def test_create_face_profile_enrolls_visitor_images(monkeypatch: pytest.MonkeyPatch):
    class FakeRecognizer:
        def enroll_images(self, name, images_base64):
            assert name == "visitor:7"
            assert images_base64 == ["img1", "img2", "img3"]
            return 3

    monkeypatch.setattr(kiosk_flow, "get_face_recognition_service", lambda: FakeRecognizer())
    visitor = FakeVisitor()
    response = create_face_profile(
        CreateFaceProfileRequest(visitor_id=7, images_base64=["img1", "img2", "img3"]),
        FakeSession([visitor]),
    )

    assert response["success"] is True
    assert response["data"]["face_identifier"] == "visitor:7"
    assert response["data"]["sample_count"] == 3
    assert visitor.face_reference_id == "visitor:7"


def test_create_face_profile_returns_json_error_for_unexpected_model_failure(monkeypatch: pytest.MonkeyPatch):
    class BrokenRecognizer:
        def enroll_images(self, name, images_base64):
            assert name == "visitor:7"
            assert images_base64 == ["img1"]
            raise RuntimeError("model crashed")

    monkeypatch.setattr(kiosk_flow, "get_face_recognition_service", lambda: BrokenRecognizer())
    visitor = FakeVisitor()

    response = create_face_profile(
        CreateFaceProfileRequest(visitor_id=7, images_base64=["img1"]),
        FakeSession([visitor]),
    )
    payload = json.loads(response.body)

    assert response.status_code == 500
    assert payload["success"] is False
    assert payload["error_code"] == "FACE_ENROLLMENT_FAILED"


def test_profile_lookup_returns_not_found_for_unknown_profile():
    response = profile_lookup(
        ProfileLookupRequest(full_name="Unknown Person", mobile_number="+971000000000"),
        FakeSession(),
    )

    assert response.status_code == 404


def test_license_lookup_returns_matching_client_profile():
    response = license_lookup(
        LicenseLookupRequest(license_number="LN-889-221"),
        FakeSession([FakeVisitor()]),
    )

    assert response["success"] is True
    assert response["data"]["visitor_name"] == "John Smith"


def test_today_events_endpoint_returns_success_envelope():
    response = list_today_events(FakeSession([FakeEvent()]))

    assert response["success"] is True
    assert response["data"][0]["event_name"] == "AI Founders Meetup"
    assert response["data"][0]["short_description"] == "Hosted by Innovation City"


def test_current_booking_uses_map_room_name_not_booking_title():
    response = get_current_booking(visitor_id=7, mobile_number=None, db=FakeSession([FakeBooking()]))

    assert response["success"] is True
    assert response["data"]["room_name"] == "Meeting Room 1"
    assert response["data"]["booking_name"] == "Investor Strategy Meeting"


def test_current_bookings_returns_all_remaining_bookings_for_today():
    second_booking = FakeBooking()
    second_booking.booking_id = 4
    second_booking.booking_name = "Podcast Recording"
    second_booking.booking_type = "studio"
    second_booking.booking_time_start = time(12, 0)
    second_booking.booking_time_end = time(13, 0)
    second_booking.zone_id = "POD_1"
    second_booking.zone = type("FakeZone", (), {"zone_name": "Podcast Studio"})()

    response = get_current_bookings(visitor_id=7, mobile_number=None, db=FakeSession([FakeBooking(), second_booking]))

    assert response["success"] is True
    assert [booking["room_name"] for booking in response["data"]] == ["Meeting Room 1", "Podcast Studio"]
    assert [booking["booking_time_start"] for booking in response["data"]] == ["10:30:00", "12:00:00"]


def test_current_booking_hides_booking_after_it_ends():
    response = get_current_booking(visitor_id=7, mobile_number=None, db=FakeSession([FakeEndedBooking()]))

    assert response.status_code == 404


def test_booking_that_crosses_midnight_returns_validation_error():
    response = create_kiosk_booking(
        KioskBookingCreate(
            visitor_id=7,
            visit_session_id=None,
            service_type="meeting_room",
            zone_id="MR_1",
            booking_date=date(2026, 7, 14),
            booking_time_start=time(23, 30),
            duration_minutes=30,
        ),
        FakeSession([FakeVisitor(), FakeZone()]),
    )

    assert response.status_code == 400


def test_kiosk_booking_after_operating_hours_returns_validation_error():
    response = create_kiosk_booking(
        KioskBookingCreate(
            visitor_id=7,
            visit_session_id=None,
            service_type="meeting_room",
            zone_id="MR_1",
            booking_date=date(2026, 7, 14),
            booking_time_start=time(16, 30),
            duration_minutes=60,
        ),
        FakeSession([FakeVisitor(), FakeZone()]),
    )

    assert response.status_code == 400


def test_event_selection_increments_event_attendee_count():
    event = FakeEvent()
    event.event_attendee_count = 2
    response = select_event(
        EventSelectionCreate(visitor_id=7, visit_session_id=4, event_id=1),
        FakeSession([FakeVisitor(), event, FakeVisitSession()]),
    )

    assert response["success"] is True
    assert event.event_attendee_count == 3


def test_event_selection_is_idempotent_for_same_visitor_and_event():
    event = FakeEvent()
    event.event_attendee_count = 2
    session = FakeSession([FakeVisitor(), event, FakeVisitSession(), FakeVisitorActivity()])

    response = select_event(
        EventSelectionCreate(visitor_id=7, visit_session_id=4, event_id=1),
        session,
    )

    assert response["success"] is True
    assert event.event_attendee_count == 2
    assert session.added == []


def test_event_selection_match_is_scoped_to_same_visit_session():
    historical_activity = FakeVisitorActivity()
    historical_activity.visit_session_id = 99

    assert event_selection_matches_activity(
        historical_activity,
        visitor_id=7,
        visit_session_id=4,
        event_name="AI Founders Meetup",
    ) is False

    historical_activity.visit_session_id = 4
    assert event_selection_matches_activity(
        historical_activity,
        visitor_id=7,
        visit_session_id=4,
        event_name="AI Founders Meetup",
    ) is True
