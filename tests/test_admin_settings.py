from datetime import time

import pytest

from app import face_web_search, runtime_settings
from app.admin_panel import sync_status
from app.admin_panel.models import AdminAuditLog
from app.admin_panel.routers import settings as settings_router
from app.config import settings
from app.face_recognition_service import match_threshold
from app.operating_hours import is_within_operating_hours, operating_hours_message
from app.spacebring_client import SpacebringError
from app.spacebring_sync import SyncResult


def put(session, key, value):
    return session.put(f"/admin/settings/{key}", json={"value": value})


def test_only_super_user_can_open_or_change_settings(login):
    for role in ("reception", "reviewer", "read_only"):
        session = login(role)
        assert session.get("/admin/settings").status_code == 403
        assert put(session, "face.match_threshold", 0.7).status_code == 403
        assert session.post("/admin/settings/spacebring/sync-now").status_code == 403


def test_listing_shows_groups_defaults_and_the_current_voice_model(login, monkeypatch):
    monkeypatch.setattr(settings, "openai_realtime_model", "gpt-realtime-2.1")
    data = login("super_user").get("/admin/settings").json()["data"]
    assert [g["id"] for g in data["groups"]] == ["voice", "face", "scan", "spacebring", "bookings"]
    by_key = {s["key"]: s for g in data["groups"] for s in g["settings"]}
    assert by_key["voice.realtime_model"]["value"] == "gpt-realtime-2.1"
    assert "gpt-realtime-2.1" in by_key["voice.realtime_model"]["choices"]
    assert by_key["face.match_threshold"]["value"] == 0.6 and by_key["face.match_threshold"]["source"] == "default"
    assert by_key["bookings.open_time"]["value"] == "09:00"


def test_listing_never_contains_secrets(login, monkeypatch):
    monkeypatch.setattr(settings, "facecheck_api_token", "FC-SECRET-TOKEN")
    monkeypatch.setattr(settings, "openai_api_key", "sk-SECRET-KEY")
    monkeypatch.setattr(settings, "spacebring_client_secret", "SB-SECRET")
    response = login("super_user").get("/admin/settings")
    for secret in ("FC-SECRET-TOKEN", "sk-SECRET-KEY", "SB-SECRET"):
        assert secret not in response.text
    status = response.json()["data"]["status"]
    assert status["facecheck_token_configured"] is True and status["openai_key_configured"] is True


def test_change_takes_effect_at_once_and_is_audited_with_old_and_new(login, db):
    admin = login("super_user")
    assert put(admin, "face.match_threshold", 0.7).status_code == 200
    assert match_threshold() == 0.7
    row = db.query(AdminAuditLog).filter(AdminAuditLog.action == "settings.update").one()
    assert row.entity_id == "face.match_threshold" and '"from":0.6' in row.detail and '"to":0.7' in row.detail
    assert row.username == "super_user-user"
    listed = {s["key"]: s for g in admin.get("/admin/settings").json()["data"]["groups"] for s in g["settings"]}
    assert listed["face.match_threshold"]["source"] == "database" and listed["face.match_threshold"]["updated_by"] == "super_user-user"


def test_reset_returns_to_the_default(login, db):
    admin = login("super_user")
    put(admin, "scan.duration_ms", 3000)
    assert runtime_settings.get("scan.duration_ms") == 3000
    assert admin.delete("/admin/settings/scan.duration_ms").status_code == 200
    assert runtime_settings.get("scan.duration_ms") == 1800
    assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "settings.reset").count() == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("face.match_threshold", 0.1),
        ("face.match_threshold", 0.99),
        ("face.match_threshold", "high"),
        ("face.web_search_max_images", 2.5),
        ("face.web_search_max_images", 9),
        ("face.web_search_demo_mode", "yes"),
        ("face.web_search_demo_mode", 1),
        ("voice.realtime_model", "not-a-model"),
        ("voice.voice", "robot"),
        ("scan.duration_ms", 10),
        ("scan.enrolment_photos", 0),
        ("spacebring.sync_interval_seconds", 5),
        ("bookings.open_time", "25:00"),
        ("bookings.open_time", "nine"),
    ],
)
def test_invalid_values_are_refused_and_nothing_changes(login, db, key, value):
    response = put(login("super_user"), key, value)
    assert response.status_code == 422 and response.json()["error_code"] == "INVALID_SETTING"
    assert db.query(runtime_settings.AppSetting).count() == 0


def test_unknown_setting_is_404(login):
    admin = login("super_user")
    assert put(admin, "face.secret_thing", 1).status_code == 404
    assert admin.delete("/admin/settings/nope").status_code == 404


def test_opening_hours_apply_to_booking_checks_and_the_message(login):
    admin = login("super_user")
    assert is_within_operating_hours(time(8, 0), time(9, 0)) is False
    assert put(admin, "bookings.open_time", "08:00").status_code == 200
    assert put(admin, "bookings.close_time", "18:30").status_code == 200
    assert is_within_operating_hours(time(8, 0), time(9, 0)) is True
    assert is_within_operating_hours(time(17, 0), time(18, 30)) is True
    assert operating_hours_message() == "Bookings and events must be scheduled between 8:00 AM and 6:30 PM."


def test_opening_must_be_before_closing(login):
    admin = login("super_user")
    response = put(admin, "bookings.open_time", "17:00")  # closing is 17:00 by default
    assert response.status_code == 422 and "earlier" in response.json()["message"]
    assert runtime_settings.get("bookings.open_time") == "09:00"


def test_facecheck_switch_needs_a_server_token_and_drives_the_search(login, monkeypatch):
    admin = login("super_user")
    monkeypatch.setattr(settings, "facecheck_api_token", "")
    refused = put(admin, "face.web_search_enabled", True)
    assert refused.status_code == 409 and refused.json()["error_code"] == "FACECHECK_TOKEN_MISSING"
    assert face_web_search.is_enabled() is False

    monkeypatch.setattr(settings, "facecheck_api_token", "tok")
    monkeypatch.setattr(settings, "face_web_search_provider", "facecheck")
    assert put(admin, "face.web_search_enabled", True).status_code == 200
    assert face_web_search.is_enabled() is True
    assert put(admin, "face.web_search_enabled", False).status_code == 200
    assert face_web_search.is_enabled() is False


def test_demo_mode_setting_reaches_the_quota_report(login, monkeypatch):
    monkeypatch.setattr(settings, "face_web_search_testing_mode", False)
    assert face_web_search.get_account_info()["demo_mode"] is False
    put(login("super_user"), "face.web_search_demo_mode", True)
    assert face_web_search.get_account_info()["demo_mode"] is True


def test_text_provider_needs_a_key(login, monkeypatch):
    admin = login("super_user")
    refused = put(admin, "voice.text_provider", "gemini")
    assert refused.status_code == 409 and refused.json()["error_code"] == "PROVIDER_KEY_MISSING"
    assert put(admin, "voice.text_provider", "scripted").status_code == 200


def test_voice_model_and_voice_are_used_by_the_realtime_session(login):
    admin = login("super_user")
    choices = {s["key"]: s["choices"] for g in admin.get("/admin/settings").json()["data"]["groups"] for s in g["settings"]}
    other = next(m for m in choices["voice.realtime_model"] if m != runtime_settings.get("voice.realtime_model"))
    assert put(admin, "voice.realtime_model", other).status_code == 200
    assert put(admin, "voice.voice", "cedar").status_code == 200
    assert runtime_settings.get("voice.realtime_model") == other and runtime_settings.get("voice.voice") == "cedar"


def test_kiosk_config_is_public_and_follows_the_settings(client, login):
    before = client.get("/api/kiosk/config")
    assert before.status_code == 200
    assert before.json()["data"]["face_scan"] == {"duration_ms": 1800, "recognition_photos": 3, "enrolment_photos": 3}
    admin = login("super_user")
    put(admin, "scan.duration_ms", 2500)
    put(admin, "scan.enrolment_photos", 4)
    put(admin, "bookings.open_time", "08:30")
    after = client.get("/api/kiosk/config").json()["data"]
    assert after["face_scan"]["duration_ms"] == 2500 and after["face_scan"]["enrolment_photos"] == 4
    assert after["operating_hours"] == {"open": "08:30", "close": "17:00"}


def test_spacebring_sync_setting_and_sync_now(login, db, monkeypatch):
    admin = login("super_user")
    monkeypatch.setattr(settings_router, "spacebring_enabled", lambda: False)
    assert admin.post("/admin/settings/spacebring/sync-now").status_code == 409

    monkeypatch.setattr(settings_router, "spacebring_enabled", lambda: True)
    monkeypatch.setattr(sync_status, "run_spacebring_sync", lambda _db: SyncResult(created=2, updated=1, deleted=0, skipped=["x"]))
    ok = admin.post("/admin/settings/spacebring/sync-now")
    assert ok.status_code == 200 and ok.json()["data"] == {"created": 2, "updated": 1, "deleted": 0, "skipped": 1}
    assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "spacebring.sync_now").count() == 1

    def down(_db):
        raise SpacebringError("boom")

    monkeypatch.setattr(sync_status, "run_spacebring_sync", down)
    failed = admin.post("/admin/settings/spacebring/sync-now")
    assert failed.status_code == 502 and failed.json()["error_code"] == "SPACEBRING_UNAVAILABLE"

    assert put(admin, "spacebring.sync_enabled", False).status_code == 200
    assert runtime_settings.get("spacebring.sync_enabled") is False
    assert put(admin, "spacebring.sync_interval_seconds", 120).status_code == 200


def test_unreadable_settings_table_falls_back_to_defaults(monkeypatch):
    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(runtime_settings, "loader", broken)
    runtime_settings.invalidate()
    assert runtime_settings.get("face.match_threshold") == 0.6
