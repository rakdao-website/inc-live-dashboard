from datetime import date, datetime

from app.admin import delete_visitor, visitor_activity_payload, visitor_read_payload, visitor_visit_count
from app.models import Booking, FaceProfile, OtherAssistanceRequest, VisitSession, VisitorActivity, VisitorCheckIn


class FakeDeleteQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model

    def filter(self, *_args, **_kwargs):
        return self

    def delete(self, synchronize_session=False):
        self.session.deleted_models.append((self.model.__name__, synchronize_session))
        return 1

    def update(self, values, synchronize_session=False):
        self.session.updated_models.append((self.model.__name__, values, synchronize_session))
        return 1

    def scalar(self):
        return self.session.scalar_counts.pop(0)

    def all(self):
        return self.session.date_rows.pop(0) if self.session.date_rows else []


class FakeSession:
    def __init__(self, visitor=None, scalar_counts=None, date_rows=None):
        self.visitor = visitor
        self.scalar_counts = list(scalar_counts or [])
        self.date_rows = list(date_rows or [])
        self.committed = False
        self.deleted = []
        self.deleted_models = []
        self.updated_models = []
        self.queries = []

    def get(self, model, _id):
        if model.__name__ == "Visitor":
            return self.visitor
        return None

    def query(self, model):
        self.queries.append(getattr(model, "__name__", str(model)))
        return FakeDeleteQuery(self, model)

    def delete(self, row):
        self.deleted.append(row)

    def commit(self):
        self.committed = True


class FakeVisitor:
    visitor_id = 7
    visitor_name = "Aisha Khan"
    visitor_phone = "+971501234567"
    visitor_email = "aisha@example.com"
    license_number = None
    is_existing_client = False
    face_reference_id = None
    face_consent_given = False
    face_consent_at = None
    lead_source = "screen_2_check_in"
    last_visit_at = None
    created_at = datetime(2026, 7, 9, 10, 15)
    updated_at = datetime(2026, 7, 9, 10, 15)


class FakeActivity:
    visitor_activity_id = 9
    visitor_id = 7
    visit_session_id = 4
    selected_service = "other"
    visit_purpose = "start_company"
    previous_selected_service = "meeting_room"
    notes = "Need CX follow-up"
    created_at = datetime(2026, 7, 9, 10, 20)


class FakeVisitSession:
    visit_session_id = 4
    check_in_time = datetime(2026, 7, 9, 10, 15)
    is_returning_visitor = False
    current_selected_service = "other"
    recognition_method = "phone"


class FakeMapLeadVisitor(FakeVisitor):
    lead_source = "map_screen"


def test_delete_visitor_detaches_dependent_records_before_delete():
    visitor = FakeVisitor()
    session = FakeSession(visitor=visitor)

    response = delete_visitor(visitor_id=7, db=session)

    assert response["success"] is True
    assert session.committed is True
    assert session.deleted == [visitor]
    assert ("FaceProfile", False) in session.deleted_models
    assert any(row[0] == Booking.__name__ for row in session.updated_models)
    assert any(row[0] == VisitSession.__name__ for row in session.updated_models)
    assert any(row[0] == VisitorActivity.__name__ for row in session.updated_models)
    assert any(row[0] == VisitorCheckIn.__name__ for row in session.updated_models)
    assert any(row[0] == OtherAssistanceRequest.__name__ for row in session.updated_models)


def test_visitor_activity_payload_includes_source_and_service():
    payload = visitor_activity_payload(
        activity=FakeActivity(),
        visitor=None,
        visit_session=FakeVisitSession(),
        previous_visit_purpose="Booked Meeting Room 1",
    )

    assert payload["source"] == "check_in_kiosk"
    assert payload["previous_visit_purpose"] == "Booked Meeting Room 1"


def test_visitor_activity_source_uses_current_session_not_original_lead_source():
    payload = visitor_activity_payload(
        activity=FakeActivity(),
        visitor=FakeMapLeadVisitor(),
        visit_session=FakeVisitSession(),
    )

    assert payload["source"] == "check_in_kiosk"


def test_visitor_read_payload_includes_visit_count():
    payload = visitor_read_payload(FakeVisitor(), visit_count=3)

    assert payload["visitor_id"] == 7
    assert payload["visit_count"] == 3


def test_visitor_visit_count_counts_one_visit_per_calendar_day():
    session = FakeSession(
        date_rows=[
            [(date(2026, 7, 15),), (date(2026, 7, 15),)],
            [(date(2026, 7, 15),), (date(2026, 7, 16),)],
            [(datetime(2026, 7, 16, 14, 30),), (datetime(2026, 7, 17, 9, 0),)],
        ]
    )

    assert visitor_visit_count(session, visitor_id=7) == 3


def test_visitor_visit_count_uses_activity_days_when_no_session_exists():
    session = FakeSession(
        date_rows=[
            [],
            [],
            [(date(2026, 7, 15),), (date(2026, 7, 15),), (date(2026, 7, 16),)],
        ]
    )

    assert visitor_visit_count(session, visitor_id=7) == 2
