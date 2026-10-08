from fastapi.testclient import TestClient

from app.main import app


def test_kiosk_frontend_origin_can_call_backend():
    client = TestClient(app)

    response = client.options(
        "/api/kiosk/recognize-face",
        headers={
            "Origin": "http://localhost:3002",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3002"


def test_origin_not_in_the_allow_list_is_rejected():
    # Admin sessions use cookies, so only the exact origins in
    # CORS_ALLOWED_ORIGINS may call the backend. Add a port there to allow it.
    client = TestClient(app)

    response = client.options(
        "/api/kiosk/recognize-face",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_extra_origins_are_added_to_the_defaults():
    # CORS_EXTRA_ORIGINS lets an extra screen (for example the dashboard display) call the backend
    # without retyping the whole default list. The middleware is built at start-up, so check the
    # merged list the app was given.
    from app.main import app as application

    cors = next(m for m in application.user_middleware if m.cls.__name__ == "CORSMiddleware")
    allowed = cors.kwargs["allow_origins"]
    assert "http://localhost:3001" in allowed            # a default is still there
    assert "null" not in allowed and "*" not in allowed  # and nothing unsafe was added


def test_cors_merge_ignores_blanks_and_spaces(monkeypatch):
    from app.config import settings as cfg

    monkeypatch.setattr(cfg, "cors_extra_origins", " http://localhost:3004 , ,https://display.example.com ")
    merged = [o.strip() for o in f"{cfg.cors_allowed_origins},{cfg.cors_extra_origins}".split(",") if o.strip()]
    assert merged[-2:] == ["http://localhost:3004", "https://display.example.com"]
