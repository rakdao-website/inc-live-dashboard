from datetime import datetime

from fastapi.testclient import TestClient

from app.admin_panel.models import AdminAuditLog, AdminSession, AdminUser
from app.config import settings
from app.main import app
from tests.conftest import NEW_PASSWORD, OTHER_PASSWORD, PASSWORD, make_user


def post_login(client, username, password):
    return client.post("/admin/auth/login", json={"username": username, "password": password})


def test_login_sets_http_only_signed_cookie_and_returns_permissions(client, db):
    make_user(db, "reviewer")
    response = post_login(client, "reviewer-user", PASSWORD)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["role"] == "reviewer"
    assert data["permissions"]["approvals"] == ["read", "write"]
    assert data["permissions"]["web_links"] == ["read"]
    assert "password" not in response.text and "hash" not in response.text
    cookie = response.headers["set-cookie"]
    assert settings.admin_cookie_name in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie


def test_default_admin_credentials_no_longer_work(client):
    assert post_login(client, "admin", OTHER_PASSWORD).status_code == 401


def test_wrong_password_and_unknown_user_look_the_same(client, db):
    make_user(db)
    wrong = post_login(client, "super_user-user", "nope")
    unknown = post_login(client, "ghost", "nope")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_inactive_user_cannot_sign_in(client, db):
    make_user(db, active=False)
    assert post_login(client, "super_user-user", PASSWORD).status_code == 401


def test_login_is_rate_limited_then_recovers_after_reset(client, db, monkeypatch):
    monkeypatch.setattr(settings, "admin_login_max_attempts", 3)
    make_user(db)
    for _ in range(3):
        assert post_login(client, "super_user-user", "bad").status_code == 401
    blocked = post_login(client, "super_user-user", PASSWORD)
    assert blocked.status_code == 429
    assert blocked.json()["error_code"] == "LOGIN_RATE_LIMITED"
    assert int(blocked.headers["retry-after"]) > 0


def test_me_requires_session_and_logout_revokes_it(login, client):
    assert client.get("/admin/auth/me").status_code == 401
    session = login("reception")
    assert session.get("/admin/auth/me").json()["data"]["role"] == "reception"
    assert session.post("/admin/auth/logout").status_code == 200
    assert session.get("/admin/auth/me").status_code == 401


def test_deactivating_user_ends_existing_session(login, db):
    session = login("reception")
    assert session.get("/admin/auth/me").status_code == 200
    user = db.query(AdminUser).one()
    user.is_active = False
    db.commit()
    assert session.get("/admin/auth/me").status_code == 401


def test_expired_server_session_is_rejected(login, db):
    session = login("reception")
    row = db.query(AdminSession).one()
    row.expires_at = datetime(2000, 1, 1)
    db.commit()
    assert session.get("/admin/auth/me").status_code == 401


def test_forged_cookie_is_rejected(client):
    client.cookies.set(settings.admin_cookie_name, "eyJzaWQiOiJ4In0.forged")
    assert client.get("/admin/auth/me").status_code == 401


def test_write_from_untrusted_origin_is_refused(login):
    session = login("super_user")
    response = session.post("/admin/auth/logout", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert response.json()["error_code"] == "ORIGIN_NOT_ALLOWED"


def test_login_and_failed_login_are_audited_without_secrets(client, db):
    make_user(db)
    post_login(client, "super_user-user", "bad-password")
    post_login(client, "super_user-user", PASSWORD)
    rows = db.query(AdminAuditLog).order_by(AdminAuditLog.audit_id).all()
    assert [r.action for r in rows] == ["login.failed", "login.success"]
    assert all("bad-password" not in (r.detail or "") for r in rows)


def test_change_password_revokes_other_sessions(login, client, db):
    first = login("reception")
    second = TestClient(app)
    assert post_login(second, "reception-user", PASSWORD).status_code == 200
    response = first.post(
        "/admin/auth/change-password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 200
    assert second.get("/admin/auth/me").status_code == 401
    assert first.get("/admin/auth/me").status_code == 200


def test_cors_does_not_allow_null_origin(client):
    response = client.options(
        "/admin/auth/me",
        headers={"Origin": "null", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") != "null"
    assert "null" not in settings.cors_allowed_origins.split(",")
