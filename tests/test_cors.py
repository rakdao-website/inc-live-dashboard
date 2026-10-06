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
