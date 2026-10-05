import base64
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import text


VENDOR_PATH = Path(__file__).with_name("vendor")

# Single confidence cutoff:
#   score >= MATCH_THRESHOLD -> "recognized" (automatic "Welcome back")
#   score <  MATCH_THRESHOLD -> "not_registered" (including an empty
#                                 gallery) -> the kiosk goes straight to
#                                 FaceCheckID's top 3 web results instead of
#                                 comparing this face against other enrolled
#                                 visitors.
MATCH_THRESHOLD = 0.60

MODEL_NAME = "buffalo_l"
PROVIDERS = ["CPUExecutionProvider"]
DETECTION_SIZE = (320, 320)
CAMERA_INDEX = 0

EMBEDDING_SIZE = 512

THUMBNAIL_MAX_CHARS = 200_000  # keep payload reasonable


class FaceRecognitionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class FaceMatch:
    name: str | None
    score: float
    recognized: bool
    photo_base64: str | None = None


@dataclass(frozen=True)
class FaceRecognitionResult:
    status: str  # "recognized" | "not_registered" | "no_face"
    best_match: FaceMatch | None
    suggestions: list[FaceMatch]  # always empty; kept for structural compatibility
    message: str


def vector_literal(vector: Any) -> str:
    """pgvector text form, e.g. '[0.1,0.2,...]' (cast with ::vector in SQL)."""
    return "[" + ",".join(f"{float(x):.8f}" for x in vector) + "]"


class PgVectorStore:
    """Face vectors in PostgreSQL (pgvector, cosine distance, HNSW index)."""

    def __init__(self, session_factory=None):
        if session_factory is None:
            from app.database import SessionLocal

            session_factory = SessionLocal
        self._session_factory = session_factory

    def search(self, vector: np.ndarray, limit: int) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows = db.execute(
                text(
                    "SELECT face_identifier, photo_base64, "
                    "1 - (embedding <=> CAST(:q AS vector)) AS score "
                    "FROM face_vectors "
                    "ORDER BY embedding <=> CAST(:q AS vector) "
                    "LIMIT :k"
                ),
                {"q": vector_literal(vector), "k": limit},
            ).all()
        return [
            {"name": row.face_identifier, "photo": row.photo_base64, "score": float(row.score)}
            for row in rows
        ]

    def replace(self, name: str, vectors: list[np.ndarray], photo_base64: str | None) -> None:
        visitor_id = _visitor_id_from_identifier(name)
        with self._session_factory() as db:
            db.execute(text("DELETE FROM face_vectors WHERE face_identifier = :n"), {"n": name})
            for vector in vectors:
                db.execute(
                    text(
                        "INSERT INTO face_vectors "
                        "(face_identifier, visitor_id, embedding, photo_base64, model_name) "
                        "VALUES (:n, (SELECT visitor_id FROM visitors WHERE visitor_id = :v), "
                        "CAST(:e AS vector), :p, :m)"
                    ),
                    {"n": name, "v": visitor_id, "e": vector_literal(vector), "p": photo_base64, "m": MODEL_NAME},
                )
            db.commit()


def ensure_pgvector_schema(engine) -> None:
    """Create the vector extension and face_vectors table if missing (idempotent).

    Used with AUTO_CREATE_TABLES so a fresh database works without running the
    SQL migration by hand. The extension must be installed on the server.
    """
    statements = [
        "CREATE EXTENSION IF NOT EXISTS vector",
        """CREATE TABLE IF NOT EXISTS face_vectors (
            face_vector_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            face_identifier VARCHAR(160) NOT NULL,
            visitor_id BIGINT REFERENCES visitors(visitor_id),
            embedding vector(512) NOT NULL,
            photo_base64 TEXT,
            model_name VARCHAR(40) NOT NULL DEFAULT 'buffalo_l',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_face_vectors_identifier ON face_vectors(face_identifier)",
        "CREATE INDEX IF NOT EXISTS idx_face_vectors_visitor ON face_vectors(visitor_id)",
        "CREATE INDEX IF NOT EXISTS idx_face_vectors_embedding_hnsw ON face_vectors USING hnsw (embedding vector_cosine_ops)",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _visitor_id_from_identifier(name: str) -> int | None:
    prefix, _, rest = name.partition(":")
    return int(rest) if prefix == "visitor" and rest.isdigit() else None


class FaceDatabase:
    """Matching and enrolment on top of a vector store (pgvector by default)."""

    def __init__(self, store: PgVectorStore | None = None):
        self.store = store or PgVectorStore()

    @staticmethod
    def normalize(vector: Any) -> np.ndarray:
        normalized = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(normalized)
        return normalized if norm == 0 else normalized / norm

    def match(self, embedding: Any, top_k: int = 3) -> list[FaceMatch]:
        query = self.normalize(embedding)
        return [
            FaceMatch(
                name=row["name"],
                score=row["score"],
                recognized=row["score"] >= MATCH_THRESHOLD,
                photo_base64=row["photo"],
            )
            for row in self.store.search(query, top_k)
        ]

    def replace_person(
        self,
        name: str,
        embeddings: list[Any],
        photo_base64: str | None = None,
    ) -> None:
        if photo_base64 and len(photo_base64) > THUMBNAIL_MAX_CHARS:
            photo_base64 = None
        self.store.replace(name, [self.normalize(e) for e in embeddings], photo_base64)


class FaceRecognitionService:
    def __init__(self, database: FaceDatabase | None = None):
        self.database = database or FaceDatabase()
        self._app = None
        self._app_lock = threading.Lock()

    def _face_app(self):
        if self._app is not None:
            return self._app
        with self._app_lock:
            if self._app is not None:
                return self._app
            try:
                if VENDOR_PATH.exists() and str(VENDOR_PATH) not in sys.path:
                    sys.path.insert(0, str(VENDOR_PATH))
                from insightface.app import FaceAnalysis
            except ImportError as exc:
                raise FaceRecognitionUnavailable(
                    "Face recognition dependencies are not installed. Run pip install -r requirements.txt in the backend environment."
                ) from exc

            app = FaceAnalysis(
                name=MODEL_NAME,
                providers=PROVIDERS,
                allowed_modules=["detection", "recognition"],
            )
            app.prepare(ctx_id=0, det_size=DETECTION_SIZE)
            self._app = app
            return app

    def warm_up(self) -> None:
        self._face_app()

    @staticmethod
    def decode_image_base64(image_base64: str):
        try:
            import cv2
        except ImportError as exc:
            raise FaceRecognitionUnavailable(
                "OpenCV is not installed. Run pip install -r requirements.txt in the backend environment."
            ) from exc

        payload = image_base64.split(",", 1)[-1]
        image_bytes = base64.b64decode(payload)
        image_array = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Could not decode face image.")
        return frame

    def _embedding_from_image_safe(self, image_base64: str) -> np.ndarray | None:
        try:
            frame = self.decode_image_base64(image_base64)
            faces = self._face_app().get(frame)
            if not faces:
                return None
            face = max(
                faces,
                key=lambda item: (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1]),
            )
            return self.database.normalize(face.embedding)
        except Exception:
            return None

    def embedding_from_image_base64(self, image_base64: str) -> np.ndarray:
        embedding = self._embedding_from_image_safe(image_base64)
        if embedding is None:
            raise ValueError("No face was detected in one of the enrollment images.")
        return embedding

    def recognize_frame(self, frame: Any) -> FaceMatch:
        faces = self._face_app().get(frame)
        if not faces:
            return FaceMatch(name=None, score=-1.0, recognized=False)
        face = max(
            faces,
            key=lambda item: (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1]),
        )
        matches = self.database.match(face.embedding, top_k=1)
        return matches[0] if matches else FaceMatch(name=None, score=-1.0, recognized=False)

    def recognize_image_base64(self, image_base64: str) -> FaceMatch:
        frame = self.decode_image_base64(image_base64)
        return self.recognize_frame(frame)

    def recognize_images_base64(self, images_base64: list[str]) -> FaceRecognitionResult:
        """
        Two outcomes:
          - score >= MATCH_THRESHOLD -> "recognized" (automatic "Welcome back")
          - anything else (including an empty gallery) -> "not_registered",
            which sends the kiosk straight to FaceCheckID's top 3 web results
            instead of comparing this face against other enrolled visitors.
        """
        if not images_base64:
            raise ValueError("At least one face image is required for recognition.")

        embeddings: list[np.ndarray] = []
        with ThreadPoolExecutor(max_workers=min(len(images_base64), 4)) as executor:
            futures = [executor.submit(self._embedding_from_image_safe, img) for img in images_base64]
            for future in as_completed(futures):
                embedding = future.result()
                if embedding is not None:
                    embeddings.append(embedding)

        if not embeddings:
            return FaceRecognitionResult(
                status="no_face",
                best_match=None,
                suggestions=[],
                message="No face was detected in any of the provided images.",
            )

        average_embedding = self.database.normalize(np.mean(embeddings, axis=0))
        matches = self.database.match(average_embedding, top_k=1)
        best = matches[0] if matches else None

        if best is not None and best.score >= MATCH_THRESHOLD:
            return FaceRecognitionResult(
                status="recognized",
                best_match=best,
                suggestions=[],
                message=f"Welcome back, {best.name}!",
            )

        return FaceRecognitionResult(
            status="not_registered",
            best_match=None,
            suggestions=[],
            message="We don't recognize you yet. Let's check for a web match.",
        )

    def enroll_images(self, name: str, images_base64: list[str]) -> int:
        embeddings = [
            self.embedding_from_image_base64(image_base64)
            for image_base64 in images_base64
        ]
        if not embeddings:
            raise ValueError("At least one face image is required for enrollment.")
        # Use the first enrollment photo as the thumbnail shown in future suggestions.
        thumbnail = images_base64[0] if images_base64 else None
        self.database.replace_person(name, embeddings, photo_base64=thumbnail)
        return len(embeddings)

    def recognize_from_camera(self, camera_index: int = CAMERA_INDEX) -> FaceMatch:
        try:
            import cv2
        except ImportError as exc:
            raise FaceRecognitionUnavailable(
                "OpenCV is not installed. Run pip install -r requirements.txt in the backend environment."
            ) from exc

        capture = cv2.VideoCapture(camera_index)
        try:
            if not capture.isOpened():
                raise FaceRecognitionUnavailable("Could not open the camera for face recognition.")
            ok, frame = capture.read()
            if not ok:
                raise FaceRecognitionUnavailable("Could not read a frame from the camera.")
            return self.recognize_frame(frame)
        finally:
            capture.release()


_service: FaceRecognitionService | None = None


def get_face_recognition_service() -> FaceRecognitionService:
    global _service
    if _service is None:
        _service = FaceRecognitionService()
    return _service