import numpy as np
import pytest
from sqlalchemy import text

from app.face_recognition_service import (
    EMBEDDING_SIZE,
    FaceDatabase,
    FaceRecognitionService,
    MATCH_THRESHOLD,
    PgVectorStore,
    vector_literal,
)


class InMemoryStore:
    """Stand-in for PgVectorStore: same interface, cosine similarity in numpy."""

    def __init__(self):
        self.rows: list[dict] = []

    def search(self, vector, limit):
        scored = [
            {"name": r["name"], "photo": r["photo"], "score": float(np.dot(vector, r["vector"]))}
            for r in self.rows
        ]
        return sorted(scored, key=lambda r: r["score"], reverse=True)[:limit]

    def replace(self, name, vectors, photo_base64):
        self.rows = [r for r in self.rows if r["name"] != name]
        self.rows += [{"name": name, "vector": v, "photo": photo_base64} for v in vectors]


def _make_database(seed: dict | None = None) -> FaceDatabase:
    db = FaceDatabase(store=InMemoryStore())
    for name, embeddings in (seed or {}).items():
        db.replace_person(name, embeddings)
    return db


def test_vector_literal_is_pgvector_text():
    assert vector_literal([1.0, 0.5]) == "[1.00000000,0.50000000]"


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

def test_oversized_thumbnail_is_dropped():
    db = _make_database()
    db.replace_person("visitor:1", [np.array([1.0, 0.0])], photo_base64="x" * 300_000)
    assert db.match(np.array([1.0, 0.0]))[0].photo_base64 is None


@pytest.fixture
def live_store():
    """Real pgvector round trip; skipped when Postgres or the extension is missing."""
    from app.database import SessionLocal

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT '[1]'::vector"))
            db.execute(text("SELECT 1 FROM face_vectors LIMIT 1"))
    except Exception:
        pytest.skip("Postgres with pgvector and the face_vectors table is not available")
    store = PgVectorStore()
    yield store
    with SessionLocal() as db:
        db.execute(text("DELETE FROM face_vectors WHERE face_identifier LIKE 'pytest:%'"))
        db.commit()


def test_pgvector_round_trip_ranks_by_cosine_similarity(live_store):
    def unit(i):
        v = np.zeros(EMBEDDING_SIZE, dtype=np.float32)
        v[i] = 1.0
        return v

    database = FaceDatabase(store=live_store)
    database.replace_person("pytest:a", [unit(0)], photo_base64="thumb-a")
    database.replace_person("pytest:b", [unit(1)])

    close = database.normalize(unit(0) + 0.1 * unit(2))
    best = database.match(close, top_k=1)[0]
    assert best.name == "pytest:a"
    assert best.photo_base64 == "thumb-a"
    assert best.score >= MATCH_THRESHOLD

    database.replace_person("pytest:a", [unit(5)])  # replaces, does not append
    assert database.match(unit(0), top_k=1)[0].score < MATCH_THRESHOLD


def _service_with_faces(monkeypatch, per_frame_faces):
    """A service whose camera frames contain the given faces: [(width, embedding), ...] per frame."""
    class Face:
        def __init__(self, width, embedding):
            self.bbox = np.array([0, 0, width, width])
            self.embedding = embedding

    class App:
        calls = 0
        lock = __import__("threading").Lock()

        def get(self, _frame):
            with self.lock:  # frames are analysed in parallel: hand out each face set exactly once
                faces = per_frame_faces[min(self.calls, len(per_frame_faces) - 1)]
                self.calls += 1
            return [Face(w, e) for w, e in faces]

    class Cv2:
        IMREAD_COLOR = 1

        @staticmethod
        def imdecode(_a, _m):
            return np.zeros((80, 80, 3), dtype=np.uint8)

    monkeypatch.setitem(__import__("sys").modules, "cv2", Cv2)
    db = _make_database({"visitor:7": [np.array([1.0, 0.0])]})
    service = FaceRecognitionService(database=db)
    service._app = App()
    return service


def test_two_similar_sized_faces_are_not_guessed(monkeypatch):
    service = _service_with_faces(monkeypatch, [[(100, np.array([1.0, 0.0])), (90, np.array([0.0, 1.0]))]])
    result = service.recognize_images_base64(["AAAA"])
    assert result.status == "multiple_faces" and result.best_match is None


def test_a_small_background_face_is_ignored(monkeypatch):
    # 28 px vs 100 px is about 8% of the area: someone far behind, not at the kiosk.
    service = _service_with_faces(monkeypatch, [[(100, np.array([1.0, 0.0])), (28, np.array([0.0, 1.0]))]])
    result = service.recognize_images_base64(["AAAA"])
    assert result.status == "recognized" and result.best_match.name == "visitor:7"


def test_a_crowded_frame_among_three_blocks_recognition(monkeypatch):
    clear = [(100, np.array([1.0, 0.0]))]
    crowded = [(100, np.array([1.0, 0.0])), (95, np.array([0.0, 1.0]))]
    service = _service_with_faces(monkeypatch, [clear, crowded, clear])
    assert service.recognize_images_base64(["AAAA", "AAAA", "AAAA"]).status == "multiple_faces"


def test_presence_reports_faces_and_the_largest_width(monkeypatch):
    class Det:
        def detect(self, frame, max_num=0, metric="default"):
            return np.array([[10, 10, 50, 60, 0.9], [100, 20, 200, 130, 0.95]]), None  # widths 40 and 100

    class App:
        det_model = Det()

    class Cv2:
        IMREAD_COLOR = 1

        @staticmethod
        def imdecode(_a, _m):
            return np.zeros((240, 320, 3), dtype=np.uint8)  # 320 px wide

    monkeypatch.setitem(__import__("sys").modules, "cv2", Cv2)
    service = FaceRecognitionService(database=_make_database())
    service._app = App()

    faces, ratio = service.detect_presence("AAAA")

    assert faces == 2 and abs(ratio - 100 / 320) < 1e-6


def test_presence_with_no_face(monkeypatch):
    class Det:
        def detect(self, frame, max_num=0, metric="default"):
            return np.zeros((0, 5)), None

    class App:
        det_model = Det()

    class Cv2:
        IMREAD_COLOR = 1

        @staticmethod
        def imdecode(_a, _m):
            return np.zeros((240, 320, 3), dtype=np.uint8)

    monkeypatch.setitem(__import__("sys").modules, "cv2", Cv2)
    service = FaceRecognitionService(database=_make_database())
    service._app = App()
    assert service.detect_presence("AAAA") == (0, 0.0)
