from starlette.responses import JSONResponse

from app.admin import admin_login
from app.config import settings
from app.schemas import AdminLoginRequest


def test_admin_login_accepts_configured_credentials(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "StrongPassword123!")
    monkeypatch.setattr(settings, "admin_role", "super_user")

    response = admin_login(
        AdminLoginRequest(username="admin", password="StrongPassword123!")
    )

    assert response["success"] is True
    assert response["data"] == {
        "username": "admin",
        "role": "super_user",
    }


def test_admin_login_rejects_wrong_password(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "StrongPassword123!")

    response = admin_login(AdminLoginRequest(username="admin", password="wrong"))

    assert isinstance(response, JSONResponse)
    assert response.status_code == 401
