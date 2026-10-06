import numpy as np
import pytest

from app import face_gallery, face_web_search
from app.admin_panel import capture_files
from app.admin_panel.models import AdminAuditLog, AdminUser
from app.models import UnknownFaceCapture, Visitor, Zone
from app.routers import face as face_module
from tests.conftest import NEW_PASSWORD
from tests.test_admin_approvals import FakeService


@pytest.fixture()
def service(monkeypatch):
    fake = FakeService()
    monkeypatch.setattr(face_module, "get_face_recognition_service", lambda: fake)
    return fake


@pytest.fixture()
def capture(db, tmp_path, monkeypatch):
    monkeypatch.setattr(capture_files, "UNKNOWN_FACE_DIR", tmp_path)
    image = tmp_path / "c.jpg"
    image.write_bytes(b"jpeg")
    row = UnknownFaceCapture(
        image_path=str(image),
        embedding=face_gallery.serialize_embedding(np.ones(512, dtype=np.float32)),
        status="pending",
    )
    db.add(row)
    db.commit()
    return row


def quota(**overrides):
    base = {"enabled": True, "demo_mode": False, "credit_cost": 3, "credits_remaining": 10, "online": True, "error": None}
    return {**base, **overrides}


# --- link / dismiss ------------------------------------------------------

def test_link_to_existing_visitor_needs_consent_then_enrols_and_audits(login, db, capture, service):
    visitor = Visitor(visitor_name="Known", visitor_phone="+971500000001", visitor_type="client")
    db.add(visitor)
    db.commit()
    staff = login("reception")
    url = f"/api/face/captures/{capture.capture_id}/link"

    refused = staff.post(url, json={"visitor_id": visitor.visitor_id})
    assert refused.status_code == 422 and refused.json()["error_code"] == "CONSENT_REQUIRED"
    assert service.database.enrolled == {}

    ok = staff.post(url, json={"visitor_id": visitor.visitor_id, "consent_confirmed": True})
    assert ok.status_code == 201 and ok.json()["data"]["enrolled"] is True
    db.expire_all()
    assert db.query(UnknownFaceCapture).one().status == "linked"
    assert db.query(Visitor).one().face_consent_given is True
    audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "capture.link").one()
    assert audit.username == "reception-user" and audit.entity_id == str(capture.capture_id)
    assert staff.post(url, json={"visitor_id": visitor.visitor_id, "consent_confirmed": True}).status_code == 409


def test_staff_cannot_link_a_pending_visitor_around_the_queue(login, db, capture, service):
    visitor = Visitor(visitor_name="P", visitor_phone="+971500000002", visitor_type="visitor", approval_status="pending")
    db.add(visitor)
    db.commit()
    response = login("reception").post(
        f"/api/face/captures/{capture.capture_id}/link", json={"visitor_id": visitor.visitor_id, "consent_confirmed": True}
    )
    assert response.status_code == 409 and response.json()["error_code"] == "VISITOR_NOT_APPROVED"
    assert service.database.enrolled == {}


def test_link_can_create_a_new_visitor_without_face(login, db, capture, service):
    response = login("super_user").post(
        f"/api/face/captures/{capture.capture_id}/link",
        json={"full_name": "New Person", "mobile_number": "+971500000003", "enroll_face": False},
    )
    assert response.status_code == 201
    assert db.query(Visitor).one().visitor_name == "New Person"


def test_dismiss_is_audited(login, db, capture):
    assert login("reviewer").post(f"/api/face/captures/{capture.capture_id}/dismiss").status_code == 200
    db.expire_all()
    assert db.query(UnknownFaceCapture).one().status == "dismissed"
    assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "capture.dismiss").count() == 1


def test_list_filters_by_status(login, db, capture):
    staff = login("reviewer")
    assert len(staff.get("/api/face/captures?status_filter=pending").json()["data"]) == 1
    assert staff.get("/api/face/captures?status_filter=dismissed").json()["data"] == []


# --- re-run web search and its credit cost -------------------------------

def test_quota_endpoint_reports_cost_and_balance(login, monkeypatch):
    monkeypatch.setattr(face_web_search, "get_account_info", lambda: quota())
    data = login("reviewer").get("/api/face/web-search/quota").json()["data"]
    assert data["credit_cost"] == 3 and data["credits_remaining"] == 10
    assert "token" not in str(data).lower()


def test_rerun_requires_cost_confirmation(login, db, capture, monkeypatch):
    monkeypatch.setattr(face_web_search, "get_account_info", lambda: quota())
    response = login("reviewer").post(f"/api/face/captures/{capture.capture_id}/web-search", json={})
    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "CREDIT_COST_NOT_CONFIRMED" and body["details"]["credit_cost"] == 3


def test_rerun_refused_when_credits_are_too_low(login, capture, monkeypatch):
    monkeypatch.setattr(face_web_search, "get_account_info", lambda: quota(credits_remaining=2))
    response = login("reviewer").post(
        f"/api/face/captures/{capture.capture_id}/web-search", json={"confirm_credit_cost": True}
    )
    assert response.status_code == 409 and response.json()["error_code"] == "INSUFFICIENT_CREDITS"


def test_rerun_runs_search_records_status_and_audits(login, db, capture, monkeypatch):
    monkeypatch.setattr(face_web_search, "get_account_info", lambda: quota())

    def disabled(*_a, **_k):
        raise face_web_search.WebFaceSearchUnavailable("Web face search is disabled or FACECHECK_API_TOKEN is not set.")

    monkeypatch.setattr(face_web_search, "search_web_faces", disabled)
    response = login("super_user").post(
        f"/api/face/captures/{capture.capture_id}/web-search", json={"confirm_credit_cost": True}
    )
    assert response.status_code == 200
    status_text = response.json()["data"]["web_search_status"]
    assert status_text.startswith("unavailable") and len(status_text) <= 40
    audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "capture.web_search").one()
    assert '"credit_cost":3' in audit.detail


def test_account_info_never_returns_the_token(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "face_web_search_enabled", False)
    monkeypatch.setattr(settings, "facecheck_api_token", "SECRET-TOKEN-VALUE")
    info = face_web_search.get_account_info()
    assert "SECRET-TOKEN-VALUE" not in str(info) and info["enabled"] is False


# --- legacy routes are audited by the middleware -------------------------

def test_legacy_write_is_audited_automatically(login, db):
    db.add(Zone(zone_id="Z1", zone_name="Zone One", zone_type="studio", is_bookable=True))
    db.commit()
    response = login("reception").patch("/admin/zones/Z1/close")
    assert response.status_code == 200, response.text
    row = db.query(AdminAuditLog).filter(AdminAuditLog.action == "PATCH /admin/zones/{zone_id}/close").one()
    assert row.username == "reception-user" and row.entity_id == "Z1" and row.entity_type == "zones"


def test_failed_or_denied_writes_are_not_audited_as_done(login, db):
    login("read_only").patch("/admin/zones/Z1/close")
    login("reception").patch("/admin/zones/MISSING/close")
    assert db.query(AdminAuditLog).filter(AdminAuditLog.action.like("PATCH%")).count() == 0


# --- users ---------------------------------------------------------------

def test_super_user_manages_users_and_last_super_user_is_protected(login, db):
    admin = login("super_user")
    created = admin.post(
        "/admin/users",
        json={"username": "New.Reviewer", "display_name": "New", "role": "reviewer", "password": NEW_PASSWORD},
    )
    assert created.status_code == 201 and created.json()["data"]["username"] == "new.reviewer"
    assert "password" not in created.text
    assert admin.post("/admin/users", json={"username": "new.reviewer", "display_name": "x", "role": "reviewer", "password": NEW_PASSWORD}).status_code == 409
    assert admin.post("/admin/users", json={"username": "weak", "display_name": "x", "role": "reviewer", "password": "short"}).status_code == 422

    me = db.query(AdminUser).filter(AdminUser.role == "super_user").one()
    blocked = admin.patch(f"/admin/users/{me.user_id}", json={"role": "reception"})
    assert blocked.status_code == 409 and blocked.json()["error_code"] == "LAST_SUPER_USER"
    assert admin.patch(f"/admin/users/{me.user_id}", json={"is_active": False}).status_code == 409


def test_role_change_ends_that_users_sessions(login, db):
    admin = login("super_user")
    reception = login("reception")
    target = db.query(AdminUser).filter(AdminUser.role == "reception").one()
    assert admin.patch(f"/admin/users/{target.user_id}", json={"role": "read_only"}).status_code == 200
    assert reception.get("/admin/auth/me").status_code == 401


# --- audit log + dashboard -----------------------------------------------

def test_audit_log_is_listed_and_filtered_for_super_user(login, db):
    admin = login("super_user")
    data = admin.get("/admin/audit-log?action=login.success").json()["data"]
    assert data["total"] == 1 and data["items"][0]["username"] == "super_user-user"
    assert admin.get("/admin/audit-log?username=nobody").json()["data"]["total"] == 0
    assert admin.get("/admin/audit-log?date_from=2999-01-01").json()["data"]["total"] == 0


def test_dashboard_summary_shape_and_no_secrets(login, db, capture, monkeypatch):
    monkeypatch.setattr(face_web_search, "is_enabled", lambda: False)
    data = login("read_only").get("/admin/dashboard/summary").json()["data"]
    assert data["unknown_captures_waiting"] == 1
    assert data["pending_approvals"] == 0
    assert data["spacebring"]["environment"] in {"SANDBOX", "LIVE"}
    assert set(data["spacebring"]["sync"]) >= {"last_run_at", "ok", "created", "updated", "deleted", "error"}
    assert data["database_ok"] is True and data["facecheck"]["credit_cost"] == 3
    text = str(data).lower()
    assert "secret" not in text and "token" not in text and "password" not in text


def test_visitor_search_is_minimal_masked_and_approved_only(login, db):
    db.add_all(
        [
            Visitor(visitor_name="Amal Hassan", visitor_phone="+971501234567", visitor_email="a@x.com", visitor_type="client"),
            Visitor(visitor_name="Amal Pending", visitor_phone="+971509999999", visitor_type="visitor", approval_status="pending"),
        ]
    )
    db.commit()
    reviewer = login("reviewer")  # reviewers cannot open the people list, but may search to link
    rows = reviewer.get("/api/face/visitor-search?q=amal").json()["data"]
    assert [r["visitor_name"] for r in rows] == ["Amal Hassan"]
    assert rows[0]["phone_hint"] == "…4567"
    assert "visitor_phone" not in rows[0] and "visitor_email" not in rows[0]
    assert reviewer.get("/api/face/visitor-search?q=a").status_code == 400
    assert reviewer.get("/admin/visitors").status_code == 403
