import numpy as np
import pytest

from app import face_recognition_service as frs
from app.face_recognition_service import (
    FaceDatabase,
    FaceRecognitionService,
    HIGH_CONFIDENCE_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
)


class FakePoint:
    def __init__(self, score, payload):
        self.score = score
        self.payload = payload


class FakeQueryResult:
    def __init__(self, points):
        self.points = points


class FakeCollectionInfo:
    def __init__(self, name):
        self.name = name


class FakeCollectionsResponse:
    def __init__(self, names):
        self.collections = [FakeCollectionInfo(n) for n in names]


class FakeQdrantClient:
    """In-memory stand-in for qdrant_client.QdrantClient, used only in tests."""

    def __init__(self, host=None, port=None):
        self._collections = set()
        self._points: dict[str, list[dict]] = {}

    def get_collections(self):
        return FakeCollectionsResponse(list(self._collections))

    def create_collection(self, collection_name, vectors_config=None):
        self._collections.add(collection_name)
        self._points.setdefault(collection_name, [])

    def query_points(self, collection_name, query, limit=3):
        query_vec = np.asarray(query, dtype=np.float32)
        rows = self._points.get(collection_name, [])
        scored = [
            (float(np.dot(query_vec, row["vector"])), row["payload"])
            for row in rows
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        points = [FakePoint(score, payload) for score, payload in scored[:limit]]
        return FakeQueryResult(points)

    def delete(self, collection_name, points_selector=None):
        name_to_remove = None
        try:
            name_to_remove = points_selector.must[0].match.value
        except Exception:
            pass
        if name_to_remove is not None:
            self._points[collection_name] = [
                row
                for row in self._points.get(collection_name, [])
                if row["payload"].get("name") != name_to_remove
            ]

    def upsert(self, collection_name, points):
        rows = self._points.setdefault(collection_name, [])
        for point in points:
            rows.append(
                {
                    "id": point.id,
                    "vector": np.asarray(point.vector, dtype=np.float32),
                    "payload": point.payload,
                }
            )


@pytest.fixture(autouse=True)
def fake_qdrant(monkeypatch):
    """Every test uses an in-memory fake instead of a real Qdrant server."""
    monkeypatch.setattr(frs, "QdrantClient", FakeQdrantClient)


def _make_database(seed: dict | None = None) -> FaceDatabase:
    db = FaceDatabase()
    for name, embeddings in (seed or {}).items():
        db.replace_person(name, embeddings)
    return db


def test_face_database_matches_normalized_embedding():
    db = _make_database({"person_a": [np.array([1.0, 0.0])]})

    matches = db.match(np.array([0.9, 0.1]))

    assert matches[0].name == "person_a"
    assert matches[0].recognized is True


def test_face_database_replaces_person_embeddings():
    db = _make_database({"visitor:7": [np.array([1.0, 0.0])]})

    db.replace_person("visitor:7", [np.array([0.0, 2.0]), np.array([0.0, 3.0])])

    matches = db.match(np.array([0.0, 1.0]), top_k=2)
    assert {match.name for match in matches} == {"visitor:7"}
    assert len(matches) == 2


def test_face_service_recognizes_with_multiple_login_images(monkeypatch):
    class FakeFace:
        def __init__(self, embedding):
            self.bbox = np.array([0, 0, 80, 80])
            self.embedding = embedding

    class FakeApp:
        calls = 0

        def get(self, _frame):
            self.calls += 1
            if self.calls == 1:
                return [FakeFace(np.array([0.2, 0.8]))]
            return [FakeFace(np.array([1.0, 0.0]))]

    class FakeCv2:
        IMREAD_COLOR = 1

        @staticmethod
        def imdecode(_image_array, _mode):
            return np.zeros((80, 80, 3), dtype=np.uint8)

    monkeypatch.setitem(__import__("sys").modules, "cv2", FakeCv2)

    db = _make_database({"visitor:7": [np.array([1.0, 0.0])]})
    service = FaceRecognitionService(database=db)
    service._app = FakeApp()

    result = service.recognize_images_base64(["AAAA", "AAAA"])

    assert result.status == "recognized"
    assert result.best_match.name == "visitor:7"
    assert result.best_match.recognized is True


def test_face_service_returns_suggestions_for_medium_confidence(monkeypatch):
    class FakeFace:
        def __init__(self, embedding):
            self.bbox = np.array([0, 0, 80, 80])
            self.embedding = embedding

    class FakeApp:
        def get(self, _frame):
            return [FakeFace(np.array([0.6, 0.8]))]

    class FakeCv2:
        IMREAD_COLOR = 1

        @staticmethod
        def imdecode(_image_array, _mode):
            return np.zeros((80, 80, 3), dtype=np.uint8)

    monkeypatch.setitem(__import__("sys").modules, "cv2", FakeCv2)

    db = _make_database({"visitor:7": [np.array([1.0, 0.0])]})
    service = FaceRecognitionService(database=db)
    service._app = FakeApp()

    result = service.recognize_images_base64(["AAAA"])

    assert result.status == "suggestions"
    assert result.suggestions
    assert LOW_CONFIDENCE_THRESHOLD <= result.suggestions[0].score < HIGH_CONFIDENCE_THRESHOLD


def test_face_service_reports_not_registered_for_low_confidence(monkeypatch):
    class FakeFace:
        def __init__(self, embedding):
            self.bbox = np.array([0, 0, 80, 80])
            self.embedding = embedding

    class FakeApp:
        def get(self, _frame):
            return [FakeFace(np.array([0.0, 1.0]))]

    class FakeCv2:
        IMREAD_COLOR = 1

        @staticmethod
        def imdecode(_image_array, _mode):
            return np.zeros((80, 80, 3), dtype=np.uint8)

    monkeypatch.setitem(__import__("sys").modules, "cv2", FakeCv2)

    db = _make_database({"visitor:7": [np.array([1.0, 0.0])]})
    service = FaceRecognitionService(database=db)
    service._app = FakeApp()

    result = service.recognize_images_base64(["AAAA"])

    assert result.status == "not_registered"


def test_face_service_enrolls_multiple_base64_images(monkeypatch):
    class FakeFace:
        def __init__(self, value):
            self.bbox = np.array([0, 0, 80, 80])
            self.embedding = np.array([float(value), 0.0])

    class FakeApp:
        calls = 0

        def get(self, _frame):
            self.calls += 1
            return [FakeFace(self.calls)]

    class FakeCv2:
        IMREAD_COLOR = 1

        @staticmethod
        def imdecode(_image_array, _mode):
            return np.zeros((80, 80, 3), dtype=np.uint8)

    monkeypatch.setitem(__import__("sys").modules, "cv2", FakeCv2)

    db = _make_database()
    service = FaceRecognitionService(database=db)
    service._app = FakeApp()

    count = service.enroll_images("visitor:7", ["data:image/jpeg;base64,AAAA", "AAAA", "AAAA"])

    assert count == 3
    matches = db.match(np.array([1.0, 0.0]), top_k=3)
    assert len(matches) == 3
    assert all(match.name == "visitor:7" for match in matches)