import base64
import pickle
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_EMBEDDINGS_PATH = Path(__file__).with_name("embeddings.pkl")
VENDOR_PATH = Path(__file__).with_name("vendor")
SIMILARITY_THRESHOLD = 0.50
EARLY_ACCEPT_SIMILARITY = 0.72
MODEL_NAME = "buffalo_l"
PROVIDERS = ["CPUExecutionProvider"]
DETECTION_SIZE = (320, 320)
CAMERA_INDEX = 0


class FaceRecognitionUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class FaceMatch:
    name: str | None
    score: float
    recognized: bool


class FaceDatabase:
    def __init__(
        self,
        path: Path | str = DEFAULT_EMBEDDINGS_PATH,
        data: dict[str, list[Any]] | None = None,
        threshold: float = SIMILARITY_THRESHOLD,
    ):
        self.path = Path(path)
        self.threshold = threshold
        self.data = data if data is not None else self._load()

    def _load(self) -> dict[str, list[Any]]:
        if not self.path.exists():
            return {}
        with self.path.open("rb") as file:
            return pickle.load(file)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("wb") as file:
            pickle.dump(self.data, file)

    @staticmethod
    def normalize(vector: Any) -> np.ndarray:
        normalized = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(normalized)
        return normalized if norm == 0 else normalized / norm

    def match(self, embedding: Any) -> FaceMatch:
        if not self.data:
            return FaceMatch(name=None, score=-1.0, recognized=False)

        query = self.normalize(embedding)
        best_name: str | None = None
        best_score = -1.0

        for name, embeddings in self.data.items():
            for stored_embedding in embeddings:
                score = float(np.dot(query, self.normalize(stored_embedding)))
                if score > best_score:
                    best_name = name
                    best_score = score

        return FaceMatch(
            name=best_name,
            score=best_score,
            recognized=best_name is not None and best_score >= self.threshold,
        )

    def replace_person(self, name: str, embeddings: list[Any]) -> None:
        self.data[name] = [self.normalize(embedding) for embedding in embeddings]
        self.save()


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

            app = FaceAnalysis(name=MODEL_NAME, providers=PROVIDERS)
            app.prepare(ctx_id=0, det_size=DETECTION_SIZE)
            self._app = app
            return app

    def warm_up(self) -> None:
        self._face_app()

    def recognize_frame(self, frame: Any) -> FaceMatch:
        faces = self._face_app().get(frame)
        if not faces:
            return FaceMatch(name=None, score=-1.0, recognized=False)

        face = max(
            faces,
            key=lambda item: (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1]),
        )
        return self.database.match(face.embedding)

    def recognize_image_base64(self, image_base64: str) -> FaceMatch:
        frame = self.decode_image_base64(image_base64)
        return self.recognize_frame(frame)

    def recognize_images_base64(self, images_base64: list[str]) -> FaceMatch:
        if not images_base64:
            raise ValueError("At least one face image is required for recognition.")

        best_match = FaceMatch(name=None, score=-1.0, recognized=False)
        for image_base64 in images_base64:
            match = self.recognize_image_base64(image_base64)
            if match.score > best_match.score:
                best_match = match
            if match.recognized and match.score >= EARLY_ACCEPT_SIMILARITY:
                break
        return best_match

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

    def embedding_from_image_base64(self, image_base64: str) -> np.ndarray:
        frame = self.decode_image_base64(image_base64)
        faces = self._face_app().get(frame)
        if not faces:
            raise ValueError("No face was detected in one of the enrollment images.")
        face = max(
            faces,
            key=lambda item: (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1]),
        )
        return self.database.normalize(face.embedding)

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
