from datetime import date, time

import app.routers.kiosk_flow as kiosk_flow
import app.spacebring_booking_service as svc
from app.kiosk_flow_schemas import KioskBookingCreate
from app.spacebring_client import SpacebringError
from tests.test_kiosk_flow_api import FakeSession, FakeVisitor


class MappedZone:
    zone_id = "TTS_2"
    zone_name = "TikTok Beauty Room"
    zone_type = "studio"
    is_bookable = True
    is_closed = False
    spacebring_resource_id = "res-2"


class FakeClient:
    def __init__(self, available=True):
        self.available = available
        self.created = []
        self.cancelled = []

    def check_availability(self, resource_id, start, end):
        return {"available": self.available, "reason": {"message": "taken"}}

    def create_booking(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "sb-1"}

    def cancel_booking(self, booking_id):
        self.cancelled.append(booking_id)


class Session(FakeSession):
    def __init__(self, zone):
        super().__init__(rows=[])
        self.zone = zone
        self.visitor = FakeVisitor()

    def refresh(self, row):
        if row.__class__.__name__ == "Booking":
            row.booking_id = 1

    def get(self, model, _id):
        return {"Zone": self.zone, "Visitor": self.visitor}.get(model.__name__)


def payload(**overrides):
    values = dict(
        visitor_id=7, service_type="tiktok_studio", zone_id="TTS_2",
        booking_date=date(2026, 11, 15), booking_time_start=time(10, 0), duration_minutes=30,
    )
    values.update(overrides)
    return KioskBookingCreate(**values)


def enable(monkeypatch, client):
    monkeypatch.setattr(svc, "spacebring_enabled", lambda: True)
    monkeypatch.setattr(svc, "get_spacebring_client", lambda: client)
    monkeypatch.setattr(kiosk_flow, "is_within_operating_hours", lambda *_: True)


def test_booking_goes_to_spacebring_and_is_mirrored(monkeypatch):
    client = FakeClient()
    enable(monkeypatch, client)
    db = Session(MappedZone())

    response = kiosk_flow.create_kiosk_booking(payload(), db)

    assert response["success"] is True
    assert client.created[0]["resource_id"] == "res-2"
    assert client.created[0]["owner_customer_id"] is None  # anonymous for now
    mirrored = [row for row in db.added if row.__class__.__name__ == "Booking"][0]
    assert mirrored.spacebring_booking_id == "sb-1"
    assert db.committed


def test_taken_slot_returns_409_and_creates_nothing(monkeypatch):
    client = FakeClient(available=False)
    enable(monkeypatch, client)
    db = Session(MappedZone())

    response = kiosk_flow.create_kiosk_booking(payload(), db)

    assert response.status_code == 409
    assert client.created == []
    assert not db.committed


def test_spacebring_outage_returns_502(monkeypatch):
    class Down(FakeClient):
        def check_availability(self, *a, **k):
            raise SpacebringError("down")

    enable(monkeypatch, Down())
    response = kiosk_flow.create_kiosk_booking(payload(), Session(MappedZone()))
    assert response.status_code == 502


def test_customer_owner_only_when_enabled(monkeypatch):
    client = FakeClient()
    enable(monkeypatch, client)
    visitor = FakeVisitor()
    visitor.spacebring_customer_id = "cust-9"

    assert svc.owner_customer_id(visitor) is None
    monkeypatch.setattr(svc.settings, "spacebring_use_customer_owner", True)
    assert svc.owner_customer_id(visitor) == "cust-9"


def test_unmapped_zone_keeps_local_path(monkeypatch):
    zone = MappedZone()
    zone.spacebring_resource_id = None
    client = FakeClient()
    enable(monkeypatch, client)

    kiosk_flow.create_kiosk_booking(payload(service_type="tiktok_studio"), Session(zone))
    assert client.created == []


def test_rejects_non_tiktok_zone_for_tiktok_service(monkeypatch):
    enable(monkeypatch, FakeClient())
    response = kiosk_flow.create_kiosk_booking(payload(zone_id="POD_1"), Session(MappedZone()))
    assert response.status_code == 400


def test_availability_endpoint_uses_spacebring(monkeypatch):
    client = FakeClient(available=False)
    enable(monkeypatch, client)
    monkeypatch.setattr(kiosk_flow, "ensure_free", svc.ensure_free)

    response = kiosk_flow.check_room_availability(
        zone_id="TTS_2", booking_date=date(2026, 11, 15), booking_time_start=time(10, 0),
        duration_minutes=30, db=Session(MappedZone()),
    )

    assert response["data"]["available"] is False
    assert response["data"]["room_name"] == "TikTok Beauty Room"
    assert client.created == []  # checking never books


def test_rooms_endpoint_lists_zones_by_service_with_spacebring_photos(monkeypatch):
    class Z:
        def __init__(self, zone_id, name, zone_type, resource=None, closed=False, bookable=True):
            self.zone_id, self.zone_name, self.zone_type = zone_id, name, zone_type
            self.spacebring_resource_id, self.is_closed, self.is_bookable = resource, closed, bookable

    zones = [
        Z("MR_1", "Meeting Room 1", "meeting_room"),
        Z("TTS_2", "TikTok Beauty Room", "studio", "res-2"),
        Z("TTS_3", "TikTok Music Room", "studio", "res-3", closed=True),
        Z("POD_1", "Podcast Studio", "studio", "res-p"),
        Z("EVT_1", "Event Area", "event_space"),
    ]

    class Q:
        def filter(self, *_): return self
        def order_by(self, *_): return self
        def all(self): return zones

    class Db:
        def query(self, _model): return Q()

    monkeypatch.setattr(kiosk_flow, "get_room_cover_urls", lambda: {"res-2": "https://cdn.test/beauty.jpg"})

    everything = kiosk_flow.list_bookable_rooms(service_type=None, db=Db())["data"]
    assert [r["zone_id"] for r in everything] == ["MR_1", "TTS_2", "TTS_3", "POD_1"]  # event area excluded
    tiktok = kiosk_flow.list_bookable_rooms(service_type="tiktok_studio", db=Db())["data"]
    assert [r["zone_id"] for r in tiktok] == ["TTS_2", "TTS_3"]
    beauty, music = tiktok
    assert beauty["image_url"] == "https://cdn.test/beauty.jpg" and beauty["source"] == "spacebring"
    assert music["image_url"] is None and music["is_closed"] is True
    meeting = kiosk_flow.list_bookable_rooms(service_type="meeting_room", db=Db())["data"][0]
    assert meeting["source"] == "internal" and meeting["image_url"] is None


def test_cover_urls_are_cached_and_survive_an_outage(monkeypatch):
    import app.spacebring_room_images as images

    calls = {"n": 0}

    class Client:
        def list_rooms(self):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("down")
            return [{"id": "r1", "media": [{"key": "k", "url": "https://cdn.test/1.jpg"}]}, {"id": "r2", "media": []}]

    monkeypatch.setattr(images, "spacebring_enabled", lambda: True)
    monkeypatch.setattr(images, "get_spacebring_client", lambda: Client())
    images._cache, images._loaded_at = {}, 0.0

    assert images.get_room_cover_urls(now=100.0) == {"r1": "https://cdn.test/1.jpg"}
    images.get_room_cover_urls(now=200.0)             # within 5 minutes: cached
    assert calls["n"] == 1
    images.get_room_cover_urls(now=500.0)             # refresh
    assert calls["n"] == 2
    assert images.get_room_cover_urls(now=900.0) == {"r1": "https://cdn.test/1.jpg"}  # outage: last good answer kept
