"""The unknown-face path: save the capture, run the web search, keep up to 3 matches.

This path used to crash on a misspelt function name (F-1), which the kiosk swallowed, so unknown
visitors never got their "Is this you?" suggestions and the capture was never saved."""
import base64
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app import face_unknown_capture, face_web_search
from app.database import engine
from app.face_web_search import WebFaceMatch, WebFaceSearchUnavailable
from app.models import FaceWebMatch, UnknownFaceCapture, Visitor

DEMO_FACE = Path(__file__).resolve().parents[1] / "app/vendor/insightface/data/images/Tom_Hanks_54745.png"  # a public sample photo shipped with the face library


@pytest.fixture
def db(tmp_path, monkeypatch):
    try:
        connection = engine.connect()
        outer = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        session.query(Visitor.manager_email).first()
    except Exception:
        pytest.skip("Postgres with the current schema is not available")
    monkeypatch.setattr(face_unknown_capture, "save_capture_image", lambda data: tmp_path / "unknown.jpg")  # no files in data/
    yield session
    session.close()
    outer.rollback()
    connection.close()


def image_base64() -> list[str]:
    return ["data:image/png;base64," + base64.b64encode(DEMO_FACE.read_bytes()).decode()]


def fake_matches(*_args, **_kwargs):
    return [WebFaceMatch(rank=i, source_url=f"https://example.test/page/{i}", score=0.9 - i / 10, thumbnail_base64="data:image/png;base64,AAAA", provider="facecheck") for i in (1, 2, 3)]


def test_the_capture_is_saved_with_its_top_three_web_matches(db, monkeypatch):
    monkeypatch.setattr(face_web_search, "search_web_faces", fake_matches)

    capture = face_unknown_capture.create_capture_with_web_search(db, image_base64())

    assert capture is not None and capture.status == "web_searched" and capture.web_search_status == "found 3"
    ranks = [m.rank for m in db.query(FaceWebMatch).filter(FaceWebMatch.capture_id == capture.capture_id).order_by(FaceWebMatch.rank)]
    assert ranks == [1, 2, 3]


def test_a_failing_search_never_loses_the_capture(db, monkeypatch):
    def unavailable(*_a, **_k):
        raise WebFaceSearchUnavailable("Upload failed: Invalid API token! (EXCEPTION)")

    monkeypatch.setattr(face_web_search, "search_web_faces", unavailable)

    capture = face_unknown_capture.create_capture_with_web_search(db, image_base64())

    assert capture is not None and capture.status == "pending"          # saved, waiting for a person to review
    assert capture.web_search_status.startswith("unavailable: Upload failed")
    assert len(capture.web_search_status) <= 40  # the column is 40 characters; a longer value used to fail the save
    assert db.query(FaceWebMatch).filter(FaceWebMatch.capture_id == capture.capture_id).count() == 0
    assert db.get(UnknownFaceCapture, capture.capture_id) is not None


def test_an_unexpected_error_is_recorded_not_raised(db, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("network down")

    monkeypatch.setattr(face_web_search, "search_web_faces", broken)
    capture = face_unknown_capture.create_capture_with_web_search(db, image_base64())
    assert capture is not None and capture.web_search_status == "error: network down"


def test_no_search_is_made_when_not_asked_to(db, monkeypatch):
    monkeypatch.setattr(face_web_search, "search_web_faces", lambda *a, **k: pytest.fail("searched"))
    capture = face_unknown_capture.create_capture_with_web_search(db, image_base64(), run_web_search=False)
    assert capture is not None and capture.web_search_status is None


def test_an_image_without_a_face_makes_no_capture(db):
    blank = "data:image/png;base64," + base64.b64encode(
        __import__("cv2").imencode(".png", __import__("numpy").full((120, 120, 3), 90, "uint8"))[1].tobytes()
    ).decode()
    assert face_unknown_capture.create_capture_with_web_search(db, [blank]) is None
