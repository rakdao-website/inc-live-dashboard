from app.schemas import VisitorCreate, VisitorUpdate


class FakeQuery:
    def __init__(self, result=None, scalar=None):
        self.result = result
        self.scalar_result = scalar

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.result

    def scalar(self):
        return self.scalar_result


class FakeSession:
    def __init__(self, visitor=None):
        self.visitor = visitor
        self.added = []

    def query(self, model):
        from app.models import Visitor

        if model is Visitor:
            return FakeQuery(result=self.visitor)
        return FakeQuery(scalar="2026-07-07 12:00:00")

    def add(self, item):
        self.added.append(item)


def test_visitor_create_accepts_core_lead_fields_without_source():
    visitor = VisitorCreate(
        visitor_name="Maya Ahmed",
        visitor_phone="+971501234567",
        visitor_email="maya@example.com",
        is_existing_client=True,
    )

    assert visitor.visitor_name == "Maya Ahmed"
    assert visitor.visitor_phone == "+971501234567"
    assert visitor.visitor_email == "maya@example.com"
    assert visitor.is_existing_client is True
    assert not hasattr(visitor, "source")


def test_visitor_update_allows_partial_phone_link_update():
    visitor = VisitorUpdate(visitor_phone="+971551112233")

    assert visitor.visitor_phone == "+971551112233"
    assert visitor.visitor_name is None


def test_booking_with_phone_creates_visitor_lead():
    from app.admin import upsert_visitor_from_booking
    from app.models import Booking, Visitor

    booking = Booking(
        zone_id="MR_1",
        booking_type="meeting",
        booking_name="Strategy Meeting",
        visitor_name="Maya Ahmed",
        visitor_phone="+971501234567",
        visitor_email=None,
        visitor_is_client=True,
    )
    session = FakeSession()

    upsert_visitor_from_booking(booking, session)

    assert len(session.added) == 1
    assert isinstance(session.added[0], Visitor)
    assert session.added[0].visitor_name == "Maya Ahmed"
    assert session.added[0].visitor_phone == "+971501234567"
    assert session.added[0].is_existing_client is True
