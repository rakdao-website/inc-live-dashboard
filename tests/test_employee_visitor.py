"""Staff (employee) visitors are seeded, so every read path must accept them."""
import pytest
from pydantic import ValidationError

from app.kiosk_flow_schemas import CreateProfileRequest, KioskVisitorRead


class StoredEmployee:
    visitor_id = 50
    visitor_name = "Mujtaba"
    visitor_phone = "+971500000103"
    visitor_email = "mujtaba@example.test"
    visitor_type = "employee"
    company_name = "Innovation City"
    company_number = None
    license_number = None
    face_consent_given = True
    last_visit_at = None


def test_kiosk_reads_an_employee_visitor():
    data = KioskVisitorRead.model_validate(StoredEmployee()).model_dump(mode="json")
    assert data["visitor_type"] == "employee"


def test_kiosk_registration_cannot_create_an_employee():
    with pytest.raises(ValidationError):
        CreateProfileRequest(
            full_name="X", mobile_number="0500000000", email="x@example.test", visitor_type="employee"
        )
