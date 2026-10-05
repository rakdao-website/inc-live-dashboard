import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

import app.spacebring_client as sb
from app.spacebring_client import SpacebringClient, SpacebringError, to_spacebring_datetime

DUBAI = ZoneInfo("Asia/Dubai")


def make_client(handler):
    return SpacebringClient(
        base_url="https://api.test",
        client_id="id",
        client_secret="secret",
        network_id="net-1",
        location_id="loc-1",
        transport=httpx.MockTransport(handler),
    )


def test_dubai_time_is_sent_as_utc():
    assert to_spacebring_datetime(datetime(2026, 11, 15, 10, 0, tzinfo=DUBAI)) == "2026-11-15T06:00:00.000Z"


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        to_spacebring_datetime(datetime(2026, 11, 15, 10, 0))


def test_requests_use_basic_auth_and_network_header():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["network"] = request.headers["spacebring-network-id"]
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={"resources": [{"id": "r1", "title": "A"}]})

    rooms = make_client(handler).list_rooms()
    assert rooms == [{"id": "r1", "title": "A"}]
    assert seen["auth"].startswith("Basic ")
    assert seen["network"] == "net-1"
    assert seen["query"]["locationRef"] == "loc-1"


def test_list_rooms_follows_pagination():
    pages = [
        {"resources": [{"id": "r1"}], "nextPageToken": "t2"},
        {"resources": [{"id": "r2"}]},
    ]

    def handler(request):
        return httpx.Response(200, json=pages.pop(0))

    assert [r["id"] for r in make_client(handler).list_rooms()] == ["r1", "r2"]


def test_create_booking_payload_is_anonymous_unless_owner_given():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"booking": {"id": "b1"}})

    client = make_client(handler)
    start, end = datetime(2026, 11, 15, 10, 0, tzinfo=DUBAI), datetime(2026, 11, 15, 10, 30, tzinfo=DUBAI)
    client.create_booking(resource_id="r1", start=start, end=end, title="T")
    client.create_booking(resource_id="r1", start=start, end=end, title="T", owner_customer_id="c9")

    assert "membershipRefOwner" not in bodies[0]["booking"]
    assert bodies[0]["booking"]["sendUpdates"] == "none"
    assert bodies[1]["booking"]["membershipRefOwner"] == "c9"


def test_availability_returns_reason():
    def handler(request):
        return httpx.Response(200, json={"available": False, "reason": {"code": "bookingConflict"}})

    result = make_client(handler).check_availability(
        "r1", datetime(2026, 11, 15, 10, 0, tzinfo=DUBAI), datetime(2026, 11, 15, 10, 30, tzinfo=DUBAI)
    )
    assert result["available"] is False


def test_cancel_accepts_204():
    client = make_client(lambda request: httpx.Response(204))
    assert client.cancel_booking("b1") is None


def test_api_errors_carry_status_and_code():
    def handler(request):
        return httpx.Response(400, json={"code": "invalidParams", "message": "locationRef is required"})

    with pytest.raises(SpacebringError) as info:
        make_client(handler).list_bookings()
    assert info.value.status_code == 400
    assert info.value.code == "invalidParams"


def test_429_is_retried(monkeypatch):
    monkeypatch.setattr(sb.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"message": "slow down"})
        return httpx.Response(200, json={"booking": {"id": "b1"}})

    assert make_client(handler).get_booking("b1") == {"id": "b1"}
    assert calls["n"] == 3


def test_network_failure_becomes_spacebring_error():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(SpacebringError):
        make_client(handler).get_booking("b1")


def test_missing_credentials_raise():
    with pytest.raises(SpacebringError):
        SpacebringClient(base_url="https://x", client_id="", client_secret="")
