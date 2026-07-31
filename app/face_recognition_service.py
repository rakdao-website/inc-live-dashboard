import base64
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue


VENDOR_PATH = Path(__file__).with_name("vendor")

# Similarity thresholds
HIGH_CONFIDENCE_THRESHOLD = 0.70   # >= this: recognized automatically
LOW_CONFIDENCE_THRESHOLD = 0.50    # 0.50-0.69: show as suggestions
# < 0.50: not registered, ask to register

MODEL_NAME = "buffalo_l"
PROVIDERS = ["CPUExecutionProvider"]
DETECTION_SIZE = (320, 320)
CAMERA_INDEX = 0

QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
QDRANT_COLLECTION = "face_embeddings"
EMBEDDING_SIZE = 512


class FaceRecognitionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class FaceMatch:
    name: str | None
    score: float
    recognized: bool


@dataclass(frozen=True)
class FaceRecognitionResult:
    status: str  # "recognized" | "suggestions" | "not_registered" | "no_face"
    best_match: FaceMatch | None
    suggestions: list[FaceMatch]
    message: str


class FaceDatabase:
    def __init__(
        self,
        host: str = QDRANT_HOST,
        port: int = QDRANT_PORT,
    ):
        self.client = QdrantClient(host=host, port=port)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        collections = [c.name for c in self.client.get_collections().collections]
        if QDRANT_COLLECTION not in collections:
            self.client.create_collection(
                collection_name=QDRANT_COLLECTION,
                vectors_config=VectorParams(size=EMBEDDING_SIZE, distance=Distance.COSINE),
            )

    @staticmethod
    def normalize(vector: Any) -> np.ndarray:
        normalized = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(normalized)
        return normalized if norm == 0 else normalized / norm

    def match(self, embedding: Any, top_k: int = 3) -> list[FaceMatch]:
        query = self.normalize(embedding)
        results = self.client.query_points(
            collection_name=QDRANT_COLLECTION,
            query=query.tolist(),
            limit=top_k,
        ).points

        return [
            FaceMatch(
                name=result.payload.get("name"),
                score=float(result.score),
                recognized=float(result.score) >= HIGH_CONFIDENCE_THRESHOLD,
            )
            for result in results
        ]

    def replace_person(self, name: str, embeddings: list[Any]) -> None:
        self.client.delete(
            collection_name=QDRANT_COLLECTION,
            points_selector=Filter(
                must=[FieldCondition(key="name", match=MatchValue(value=name))]
            ),
        )
        points = [
            PointStruct(
                id=abs(hash(f"{name}_{i}")) % (2**63),
                vector=self.normalize(embedding).tolist(),
                payload={"name": name},
            )
            for i, embedding in enumerate(embeddings)
        ]
        self.client.upsert(collection_name=QDRANT_COLLECTION, points=points)


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
        """Returns the normalized embedding for the largest face, or None if no face found."""
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
        Recognizes a person from up to several photos taken at once (higher accuracy
        via averaging embeddings). Applies three-tier confidence:
          - score >= 0.70            -> recognized automatically
          - 0.50 <= score < 0.70     -> return top matches as suggestions
          - score < 0.50             -> not_registered
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
        matches = self.database.match(average_embedding, top_k=3)
        best = matches[0] if matches else None

        if best is not None and best.score >= HIGH_CONFIDENCE_THRESHOLD:
            return FaceRecognitionResult(
                status="recognized",
                best_match=best,
                suggestions=[],
                message=f"Welcome back, {best.name}!",
            )

        candidates = [match for match in matches if match.score >= LOW_CONFIDENCE_THRESHOLD]
        if candidates:
            return FaceRecognitionResult(
                status="suggestions",
                best_match=None,
                suggestions=candidates,
                message="We found some possible matches. Please confirm which one is you.",
            )

        return FaceRecognitionResult(
            status="not_registered",
            best_match=None,
            suggestions=[],
            message="We don't recognize you yet. Please register.",
        )

    def enroll_images(self, name: str, images_base64: list[str]) -> int:
        embeddings = [
            self.embedding_from_image_base64(image_base64)
            for image_base64 in images_base64
        ]
        if not embeddings:
            raise ValueError("At least one face image is required for enrollment.")
        self.database.replace_person(name, embeddings)
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