from datetime import timedelta

import pytest

from app import runtime_settings, session_log
from app.admin_panel import audit_chain
from app.admin_panel.models import AdminAuditLog
from app.models import Visitor
from app.privacy_mask import mask_email, mask_phone, mask_text


def test_masks_hide_the_real_value():
    assert mask_email("mohamad@example.com") == "m*****@e*****.com"
    assert mask_phone("+971 50 123 4567") == "+971*****67"
    assert mask_phone("0501234567") == "050*****67"
    assert mask_email("not-an-email") is None and mask_phone("12") is None and mask_phone(None) is None
    text = mask_text("Mail me at mohamad@example.com or call +971 50 123 4567, room 4B at 3pm")
    assert "mohamad" not in text and "123 4567" not in text
    assert "room 4B at 3pm" in text


def make_visitor(db, name="Aisha Khan", phone="+971501234567", email="aisha@example.com", kind="customer"):
    visitor = Visitor(visitor_name=name, visitor_phone=phone, visitor_email=email, visitor_type=kind)
    db.add(visitor)
    db.commit()
    return visitor


def test_visitor_masked_columns_follow_the_real_ones(db):
    visitor = make_visitor(db)
    assert visitor.email_masked == "a*****@e*****.com" and visitor.phone_masked == "+971*****67"
    visitor.visitor_email = "zed@corp.io"
    db.commit()
    assert visitor.email_masked == "z*****@c*****.io"


def test_kiosk_session_is_stored_masked_and_resends_are_harmless(client, db):
    visitor = make_visitor(db)
    started = client.post("/api/kiosk/sessions", json={"visitor_id": visitor.visitor_id}).json()["data"]
    sid = started["session_id"]
    assert started["logging"] is True
    assert client.post(f"/api/kiosk/sessions/{sid}/messages", json={"role": "visitor", "text": "my email is aisha@example.com", "item_id": "i1"}).status_code == 200
    client.post(f"/api/kiosk/sessions/{sid}/messages", json={"role": "visitor", "text": "my number is +971 50 123 4567", "item_id": "i1"})  # same item, final text
    client.post(f"/api/kiosk/sessions/{sid}/messages", json={"role": "assistant", "text": "Done", "item_id": "i2"})
    stored = db.query(session_log.KioskSessionMessage).order_by(session_log.KioskSessionMessage.message_id).all()
    assert [m.role for m in stored] == ["visitor", "assistant"]
    assert "123 4567" not in stored[0].content and "aisha" not in stored[0].content
    row = db.get(session_log.KioskSession, sid)
    assert row.visitor_label == "Aisha Khan" and row.message_count == 2

    assert client.post(f"/api/kiosk/sessions/{sid}/end", json={"outcome": "booked"}).status_code == 200
    assert client.post(f"/api/kiosk/sessions/{sid}/messages", json={"role": "visitor", "text": "late"}).status_code == 404
    assert client.post("/api/kiosk/sessions/nope/messages", json={"role": "visitor", "text": "x"}).status_code == 404


def test_the_visitors_name_comes_from_the_database_not_the_browser(client, db):
    sid = client.post("/api/kiosk/sessions", json={"visitor_id": 999999, "visitor_label": "Fake Name"}).json()["data"]["session_id"]
    assert db.get(session_log.KioskSession, sid).visitor_label is None


def test_a_visitor_identified_during_the_conversation_is_linked_at_the_end(client, db):
    visitor = make_visitor(db)
    sid = client.post("/api/kiosk/sessions", json={}).json()["data"]["session_id"]
    client.post(f"/api/kiosk/sessions/{sid}/end", json={"outcome": "completed", "visitor_id": visitor.visitor_id})
    row = db.get(session_log.KioskSession, sid)
    assert row.visitor_id == visitor.visitor_id and row.visitor_label == "Aisha Khan" and row.outcome == "completed"


def test_logging_can_be_switched_off_and_old_logs_expire(client, db, login):
    admin = login("super_user")
    old = client.post("/api/kiosk/sessions", json={}).json()["data"]["session_id"]
    row = db.get(session_log.KioskSession, old)
    row.started_at = row.started_at - timedelta(days=200)
    db.commit()
    client.post("/api/kiosk/sessions", json={})  # starting a session clears expired ones
    db.expire_all()
    assert db.get(session_log.KioskSession, old) is None

    assert admin.put("/admin/settings/sessions.store_transcripts", json={"value": False}).status_code == 200
    off = client.post("/api/kiosk/sessions", json={}).json()["data"]
    assert off == {"session_id": None, "logging": False}


def test_admin_views_are_role_limited_audited_and_masked(client, db, login):
    visitor = make_visitor(db)
    sid = client.post("/api/kiosk/sessions", json={"visitor_id": visitor.visitor_id}).json()["data"]["session_id"]
    client.post(f"/api/kiosk/sessions/{sid}/messages", json={"role": "visitor", "text": "hello", "item_id": "a"})

    assert login("reception").get("/admin/sessions").status_code == 403
    assert login("read_only").get(f"/admin/sessions/{sid}").status_code == 403

    reviewer = login("reviewer")
    detail = reviewer.get(f"/admin/sessions/{sid}")
    assert detail.status_code == 200 and detail.json()["data"]["messages"][0]["content"] == "hello"
    assert reviewer.get("/admin/sessions").json()["data"]["total"] == 1
    actions = [r.action for r in db.query(AdminAuditLog).all()]
    assert "sessions.view" in actions and "sessions.list" in actions
    assert reviewer.get("/admin/sessions/unknown").status_code == 404


@pytest.mark.parametrize("role", ["super_user", "reception", "reviewer", "read_only"])
def test_customer_list_shows_only_masked_contact_details(login, db, role):
    make_visitor(db)
    response = login(role).get("/admin/customers")
    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["email_masked"] == "a*****@e*****.com" and item["phone_masked"] == "+971*****67"
    assert "aisha@example.com" not in response.text and "501234567" not in response.text
    assert "visitor_email" not in item and "visitor_phone" not in item


def test_customer_search_filter_and_session_count(client, login, db):
    a = make_visitor(db)
    make_visitor(db, name="Omar Hassan", phone="+971551112233", email="omar@example.com", kind="employee")
    client.post("/api/kiosk/sessions", json={"visitor_id": a.visitor_id})
    admin = login("reception")
    data = admin.get("/admin/customers", params={"q": "aisha"}).json()["data"]
    assert data["total"] == 1 and data["items"][0]["sessions"] == 1
    assert admin.get("/admin/customers", params={"visitor_type": "employee"}).json()["data"]["items"][0]["name"] == "Omar Hassan"
    assert admin.get("/admin/customers/999999").status_code == 404
    assert admin.get(f"/admin/customers/{a.visitor_id}").json()["data"]["phone_masked"] == "+971*****67"


def test_audit_chain_verifies_and_detects_tampering(login, db):
    admin = login("super_user")
    admin.put("/admin/settings/scan.duration_ms", json={"value": 2000})
    admin.put("/admin/settings/scan.duration_ms", json={"value": 2500})
    ok = admin.get("/admin/audit-log/verify").json()["data"]
    assert ok["ok"] is True and ok["checked"] >= 3

    rows = db.query(AdminAuditLog).filter(AdminAuditLog.row_hash.isnot(None)).order_by(AdminAuditLog.audit_id).all()
    assert rows[0].prev_hash is None and rows[1].prev_hash == rows[0].row_hash
    rows[1].detail = '{"changed":"later"}'
    db.commit()
    broken = admin.get("/admin/audit-log/verify").json()["data"]
    assert broken["ok"] is False and broken["broken_at"] == rows[1].audit_id

    assert audit_chain.verify(db)["ok"] is False


def test_deleting_an_audit_row_is_detected(login, db):
    admin = login("super_user")
    for value in (2000, 2100, 2200):
        admin.put("/admin/settings/scan.duration_ms", json={"value": value})
    middle = db.query(AdminAuditLog).filter(AdminAuditLog.row_hash.isnot(None)).order_by(AdminAuditLog.audit_id).all()[2]
    db.delete(middle)
    db.commit()
    assert audit_chain.verify(db)["ok"] is False


def test_audit_categories_filter_and_csv_export_is_safe_and_audited(login, db):
    admin = login("super_user")
    admin.put("/admin/settings/scan.duration_ms", json={"value": 2000})
    admin.get("/admin/customers")
    cats = {i["action"]: i["category"] for i in admin.get("/admin/audit-log").json()["data"]["items"]}
    assert cats["settings.update"] == "change" and cats["customers.list"] == "data_access" and cats["login.success"] == "auth"
    only = admin.get("/admin/audit-log", params={"category": "data_access"}).json()["data"]["items"]
    assert only and all(i["category"] == "data_access" for i in only)
    assert admin.get("/admin/audit-log", params={"category": "bogus"}).status_code == 422

    db.add(AdminAuditLog(username="x", action="=HYPERLINK(1)", detail="d"))
    db.commit()
    export = admin.get("/admin/audit-log/export")
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv")
    assert "'=HYPERLINK(1)" in export.text and ",=HYPERLINK" not in export.text
    assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "audit.export").count() == 1


def test_only_super_user_reads_the_audit_log(login):
    for role in ("reception", "reviewer", "read_only"):
        s = login(role)
        assert s.get("/admin/audit-log/verify").status_code == 403
        assert s.get("/admin/audit-log/export").status_code == 403


def test_one_customer_many_visits_are_kept_together(client, login, db):
    from datetime import datetime, timedelta
    from app.models import VisitorCheckIn

    a = make_visitor(db)
    b = make_visitor(db, name="Omar Hassan", phone="+971551112233", email="omar@example.com")
    now = datetime.utcnow()
    for days in (3, 2, 1):
        db.add(VisitorCheckIn(visitor_id=a.visitor_id, check_in_time=now - timedelta(days=days), check_in_status="booking_found", match_method="face"))
    db.add(VisitorCheckIn(visitor_id=b.visitor_id, check_in_status="no_booking_found", match_method="phone"))
    db.commit()
    first = client.post("/api/kiosk/sessions", json={"visitor_id": a.visitor_id}).json()["data"]["session_id"]
    client.post("/api/kiosk/sessions", json={"visitor_id": a.visitor_id})

    admin = login("reviewer")
    items = {i["name"]: i for i in admin.get("/admin/customers", params={"sort": "visits"}).json()["data"]["items"]}
    assert items["Aisha Khan"]["visits"] == 3 and items["Aisha Khan"]["sessions"] == 2 and items["Omar Hassan"]["visits"] == 1
    assert [i["name"] for i in admin.get("/admin/customers", params={"sort": "visits"}).json()["data"]["items"]][0] == "Aisha Khan"

    detail = admin.get(f"/admin/customers/{a.visitor_id}").json()["data"]
    assert [v["status"] for v in detail["recent_visits"]] == ["booking_found"] * 3
    assert detail["recent_visits"][0]["at"] > detail["recent_visits"][1]["at"]  # newest first
    assert {s["session_id"] for s in detail["recent_sessions"]} >= {first}
    assert "aisha@example.com" not in str(detail)
    only_a = admin.get("/admin/sessions", params={"visitor_id": a.visitor_id}).json()["data"]
    assert only_a["total"] == 2
    assert admin.get("/admin/customers", params={"sort": "bogus"}).status_code == 422
