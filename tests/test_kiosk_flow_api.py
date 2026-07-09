from datetime import date, time

from app.kiosk_flow_schemas import ProfileLookupRequest, RecognizeFaceRequest
from app.routers.kiosk_flow import list_today_events, profile_lookup, recognize_face


class FakeQuery:
    def __init__(self, rows=None):
        self.rows = rows or []

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []

    def query(self, _model):
        return FakeQuery(self.rows)


class FakeEvent:
    event_id = 1
    event_name = "AI Founders Meetup"
    event_date = date(2026, 7, 9)
    event_time_start = time(11, 0)
    event_time_end = time(12, 30)
    event_location = "Event Area"


def test_recognize_face_placeholder_returns_success_envelope():
    response = recognize_face(RecognizeFaceRequest(), FakeSession())

    assert response["success"] is True
    assert response["data"]["recognized"] is False


def test_profile_lookup_returns_not_found_for_unknown_profile():
    response = profile_lookup(
        ProfileLookupRequest(full_name="Unknown Person", mobile_number="+971000000000"),
        FakeSession(),
    )

    assert response.status_code == 404


def test_today_events_endpoint_returns_success_envelope():
    response = list_today_events(FakeSession([FakeEvent()]))

    assert response["success"] is True
    assert response["data"][0]["event_name"] == "AI Founders Meetup"
    assert response["data"][0]["short_description"] == "Hosted by Innovation City"
