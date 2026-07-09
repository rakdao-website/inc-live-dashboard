from datetime import datetime

from app.admin import list_visitor_activity


class FakeQuery:
    def __init__(self, rows=None):
        self.rows = rows or []

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, activities=None, visitor=None, visit_session=None):
        self.activities = activities or []
        self.visitor = visitor
        self.visit_session = visit_session

    def query(self, _model):
        return FakeQuery(self.activities)

    def get(self, model, _id):
        if model.__name__ == "Visitor":
            return self.visitor
        if model.__name__ == "VisitSession":
            return self.visit_session
        return None


class FakeVisitor:
    visitor_id = 1
    visitor_name = "Aisha Khan"
    visitor_phone = "+971501234567"
    visitor_email = "aisha@example.com"
    visitor_type = "client"
    company_name = "Innovation Demo"
    company_number = "CO-001"


class FakeVisitSession:
    visit_session_id = 4
    check_in_time = datetime(2026, 7, 9, 10, 15)
    is_returning_visitor = True


class FakeActivity:
    visitor_activity_id = 9
    visitor_id = 1
    visit_session_id = 4
    selected_service = "meeting_room"
    visit_purpose = "Meeting Room"
    previous_selected_service = "event"
    notes = "Created from kiosk"
    created_at = datetime(2026, 7, 9, 10, 20)


def test_admin_visitor_activity_returns_activity_rows():
    response = list_visitor_activity(
        search=None,
        limit=100,
        db=FakeSession(
            activities=[FakeActivity()],
            visitor=FakeVisitor(),
            visit_session=FakeVisitSession(),
        )
    )

    assert response["success"] is True
    assert response["data"][0]["visitor_name"] == "Aisha Khan"
    assert response["data"][0]["previous_selected_service"] == "event"
