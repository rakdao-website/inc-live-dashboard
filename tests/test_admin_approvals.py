"""Pending -> approve / reject, the kiosk side of it, and who may see web-match links."""

import numpy as np
import pytest

from app import face_gallery
from app.admin_panel import capture_files
from app.admin_panel.models import AdminAuditLog, VisitorApproval
from app.admin_panel.routers import approvals as approvals_module
from app.models import FaceWebMatch, UnknownFaceCapture, Visitor
from app.routers import face as face_module


class FakeFaceDatabase:
    def __init__(self):
        self.enrolled = {}
        self.deleted = []

    def replace_person(self, name, embeddings, photo_base64=None):
        self.enrolled[name] = embeddings

    def delete_person(self, name):
        self.deleted.append(name)
        return 1 if self.enrolled.pop(name, None) is not None else 0


class FakeService:
    def __init__(self):
        self.database = FakeFaceDatabase()
        self.is_ready = True


@pytest.fixture()
def face_service(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(approvals_module, "get_face_recognition_service", lambda: service)
    monkeypatch.setattr(face_module, "get_face_recognition_service", lambda: service)
    return service


@pytest.fixture()
def capture(db, tmp_path, monkeypatch):
    monkeypatch.setattr(capture_files, "UNKNOWN_FACE_DIR", tmp_path)
    image = tmp_path / "unknown_1.jpg"
    image.write_bytes(b"\xff\xd8fakejpeg")
    row = UnknownFaceCapture(
        image_path=str(image),
        embedding=face_gallery.serialize_embedding(np.ones(512, dtype=np.float32)),
        best_gallery_score=0.31,
        status="web_searched",
        web_search_status="found 2",
    )
    db.add(row)
    db.flush()
    db.add_all(
        [
            FaceWebMatch(capture_id=row.capture_id, rank=1, source_url="https://example.com/p/1", score=0.91, thumbnail_base64="data:image/jpeg;base64,AAA"),
            FaceWebMatch(capture_id=row.capture_id, rank=2, source_url="https://example.com/p/2", score=0.62),
        ]
    )
    db.commit()
    return row


def kiosk_register(client, capture_id, rank=1, phone="+971501110001"):
    return client.post(
        f"/api/kiosk/captures/{capture_id}/link",
        json={"full_name": "Sara Ali", "mobile_number": phone, "email": "sara@example.com", "visitor_type": "visitor", "chosen_rank": rank},
    )


def test_kiosk_registration_creates_pending_visitor_and_never_enrols_the_face(client, db, capture, face_service):
    response = kiosk_register(client, capture.capture_id)
    assert response.status_code == 201
    assert response.json()["data"]["pending"] is True
    visitor = db.query(Visitor).one()
    assert visitor.approval_status == "pending"
    assert visitor.face_reference_id is None
    assert face_service.database.enrolled == {}
    approval = db.query(VisitorApproval).one()
    assert approval.status == "pending" and approval.source == "web_suggestion"
    assert approval.chosen_web_match_id is not None
    assert "sara@example.com" in approval.entered_details
    assert "example.com/p" not in response.text  # the kiosk never receives web-match links


def test_kiosk_registration_without_suggestion_is_a_new_entry(client, db, capture):
    kiosk_register(client, capture.capture_id, rank=None)
    assert db.query(VisitorApproval).one().source == "new_entry"


def test_kiosk_profile_without_face_is_also_pending(client, db):
    response = client.post(
        "/api/kiosk/profiles",
        json={"full_name": "Omar K", "mobile_number": "+971502220002", "email": "o@example.com", "visitor_type": "client"},
    )
    assert response.status_code == 201
    assert db.query(Visitor).one().approval_status == "pending"
    assert db.query(VisitorApproval).one().source == "new_entry"


def test_pending_visitor_is_not_a_confirmed_visitor(client, db, capture):
    kiosk_register(client, capture.capture_id)
    lookup = client.post("/api/kiosk/profile-lookup", json={"full_name": "Sara Ali", "mobile_number": "+971501110001"})
    assert lookup.status_code == 404
    again = client.post(
        "/api/kiosk/profiles",
        json={"full_name": "Sara Ali", "mobile_number": "+971501110001", "email": "s@example.com", "visitor_type": "visitor"},
    )
    assert again.status_code == 409
    assert again.json()["error_code"] == "VISITOR_PENDING_APPROVAL"


def test_kiosk_cannot_attach_a_face_to_an_existing_person_by_phone(client, db, capture):
    db.add(Visitor(visitor_name="Existing", visitor_phone="+971503330003", visitor_type="client"))
    db.commit()
    response = kiosk_register(client, capture.capture_id, phone="+971503330003")
    assert response.status_code == 409
    assert response.json()["error_code"] == "VISITOR_PHONE_EXISTS"
    assert db.query(VisitorApproval).count() == 0


def test_approve_enrols_face_only_with_consent_and_is_audited(client, login, db, capture, face_service):
    kiosk_register(client, capture.capture_id)
    reviewer = login("reviewer")
    approval_id = db.query(VisitorApproval).one().approval_id

    blocked = reviewer.post(f"/admin/approvals/{approval_id}/approve", json={})
    assert blocked.status_code == 422 and blocked.json()["error_code"] == "CONSENT_REQUIRED"
    assert db.query(Visitor).one().approval_status == "pending"

    ok = reviewer.post(f"/admin/approvals/{approval_id}/approve", json={"consent_confirmed": True, "reason": "ID checked"})
    assert ok.status_code == 200 and ok.json()["data"]["face_enrolled"] is True
    db.expire_all()
    visitor = db.query(Visitor).one()
    assert visitor.approval_status == "approved" and visitor.face_consent_given and visitor.face_consent_at
    assert visitor.face_reference_id == f"visitor:{visitor.visitor_id}"
    assert f"visitor:{visitor.visitor_id}" in face_service.database.enrolled
    approval = db.query(VisitorApproval).one()
    assert approval.status == "approved" and approval.decided_by_username == "reviewer-user" and approval.decided_at
    audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "approval.approve").one()
    assert audit.username == "reviewer-user" and audit.entity_id == str(visitor.visitor_id)
    # now a confirmed visitor on the kiosk
    assert client.post("/api/kiosk/profile-lookup", json={"full_name": "Sara Ali", "mobile_number": "+971501110001"}).status_code == 200


def test_approve_without_face_needs_no_consent(client, login, db, capture, face_service):
    kiosk_register(client, capture.capture_id)
    approval_id = db.query(VisitorApproval).one().approval_id
    response = login("super_user").post(f"/admin/approvals/{approval_id}/approve", json={"enroll_face": False})
    assert response.status_code == 200 and response.json()["data"]["face_enrolled"] is False
    assert face_service.database.enrolled == {}


def test_reject_removes_vectors_image_and_records_who_and_why(client, login, db, capture, face_service, tmp_path):
    kiosk_register(client, capture.capture_id)
    visitor = db.query(Visitor).one()
    face_service.database.enrolled[f"visitor:{visitor.visitor_id}"] = [1]  # a stray vector for this person
    approval_id = db.query(VisitorApproval).one().approval_id

    response = login("reviewer").post(f"/admin/approvals/{approval_id}/reject", json={"reason": "Not a client"})
    assert response.status_code == 200 and response.json()["data"]["vectors_removed"] == 1
    db.expire_all()
    assert db.query(Visitor).one().approval_status == "rejected"
    row = db.query(VisitorApproval).one()
    assert (row.status, row.decision_reason, row.decided_by_username) == ("rejected", "Not a client", "reviewer-user")
    cap = db.query(UnknownFaceCapture).one()
    assert cap.embedding is None and cap.status == "dismissed"
    assert not (tmp_path / "unknown_1.jpg").exists()
    audit = db.query(AdminAuditLog).filter(AdminAuditLog.action == "approval.reject").one()
    assert "Not a client" in audit.detail


def test_decided_approval_cannot_be_decided_twice(client, login, db, capture, face_service):
    kiosk_register(client, capture.capture_id)
    approval_id = db.query(VisitorApproval).one().approval_id
    reviewer = login("reviewer")
    reviewer.post(f"/admin/approvals/{approval_id}/reject", json={})
    again = reviewer.post(f"/admin/approvals/{approval_id}/approve", json={"consent_confirmed": True})
    assert again.status_code == 409 and again.json()["error_code"] == "APPROVAL_ALREADY_DECIDED"


def test_queue_lists_pending_with_details_match_and_suggestion(client, login, db, capture):
    kiosk_register(client, capture.capture_id)
    item = login("reviewer").get("/admin/approvals?status=pending").json()["data"]["items"][0]
    assert item["visitor"]["visitor_name"] == "Sara Ali"
    assert item["entered_details"]["email"] == "sara@example.com"
    assert item["match"] == {"method": "web_suggestion", "best_gallery_score": 0.31, "web_search_status": "found 2"}
    assert item["chosen_suggestion"]["rank"] == 1 and item["has_image"] is True


def test_approval_image_needs_login_and_is_not_cached(client, login, db, capture):
    kiosk_register(client, capture.capture_id)
    approval_id = db.query(VisitorApproval).one().approval_id
    assert client.get(f"/admin/approvals/{approval_id}/image").status_code == 401
    ok = login("reviewer").get(f"/admin/approvals/{approval_id}/image")
    assert ok.status_code == 200 and ok.headers["cache-control"] == "private, no-store"


def test_only_reviewer_and_super_user_see_web_links_in_captures(client, login, capture):
    for role, sees in (("reviewer", True), ("super_user", True), ("reception", False)):
        data = login(role).get(f"/api/face/captures/{capture.capture_id}").json()["data"]
        assert "image_path" not in data
        first = data["web_matches"][0]
        assert (first["source_url"] is not None) is sees, role
        assert (first["thumbnail_base64"] is not None) is sees, role
        assert first["score"] == 0.91  # the score stays visible
