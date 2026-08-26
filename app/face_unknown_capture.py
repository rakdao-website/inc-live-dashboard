from __future__ import annotations

import base64
import binascii
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app import face_gallery, face_web_search
from app.config import settings
from app.face_recognition_service import get_face_recognition_service
from app.face_web_search import WebFaceSearchUnavailable
from app.models import FaceWebMatch, UnknownFaceCapture

UNKNOWN_FACE_DIR = Path(__file__).resolve().parents[1] / "data" / "unknown_faces"


def decode_base64_image(image_base64: str) -> bytes:
    payload = image_base64.split(",", 1)[-1]
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Could not decode the face image.") from exc


def save_capture_image(image_bytes: bytes) -> Path:
    UNKNOWN_FACE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = UNKNOWN_FACE_DIR / f"unknown_{stamp}.jpg"
    path.write_bytes(image_bytes)
    return path


def usable_frames(images_base64: list[str]):
    """Across all provided frames, return:
      - embedding, image_bytes, gallery_score for the single "best" frame
        (used for the capture's saved image + stored embedding + enrollment)
      - all_image_bytes: every frame that had a detectable face, in order
        (used for the FaceCheckID search, since searching with multiple
        photos of the same person tends to be more accurate than one)

    Any of the "best" values may be None if no face was found anywhere.
    """
    service = get_face_recognition_service()
    best_embedding = None
    best_bytes = None
    best_score = None
    all_image_bytes: list[bytes] = []

    for image_base64 in images_base64:
        try:
            image_bytes = decode_base64_image(image_base64)
        except ValueError:
            continue

        embedding = service._embedding_from_image_safe(image_base64)
        if embedding is None:
            continue

        all_image_bytes.append(image_bytes)

        matches = service.database.match(embedding, top_k=1)
        score = matches[0].score if matches else -1.0
        if best_score is None or score > best_score:
            best_score = score
            best_embedding = embedding
            best_bytes = image_bytes

    return best_embedding, best_bytes, best_score, all_image_bytes


def best_embedding_and_bytes(images_base64: list[str]):
    """Backwards-compatible wrapper: returns just (embedding, image_bytes,
    gallery_score) for the single best frame. Prefer usable_frames() for new
    code that also needs every frame (e.g. for the FaceCheckID search)."""
    best_embedding, best_bytes, best_score, _ = usable_frames(images_base64)
    return best_embedding, best_bytes, best_score


def run_web_face_search(
    db: Session,
    capture: UnknownFaceCapture,
    images_bytes: bytes | list[bytes],
) -> None:
    db.query(FaceWebMatch).filter(FaceWebMatch.capture_id == capture.capture_id).delete(
        synchronize_session=False
    )
    try:
        matches = face_web_search.search_web_faces(images_bytes, limit=3)
    except WebFaceSearchUnavailable as exc:
        capture.web_search_status = f"unavailable: {exc}"
        return
    except Exception as exc:  # noqa: BLE001 - external call, never fatal to kiosk
        capture.web_search_status = f"error: {exc}"
        return

    for match in matches:
        db.add(
            FaceWebMatch(
                capture_id=capture.capture_id,
                rank=match.rank,
                source_url=match.source_url,
                score=match.score,
                thumbnail_base64=match.thumbnail_base64,
                provider=match.provider,
            )
        )
    capture.web_search_status = f"found {len(matches)}" if matches else "no matches"
    capture.status = "web_searched"


def create_capture_with_web_search(
    db: Session,
    images_base64: list[str],
    *,
    run_web_search: bool = True,
) -> UnknownFaceCapture | None:
    """Create an UnknownFaceCapture row for this face and (if enabled) run
    the FaceCheckID reverse search using every usable frame, populating
    face_web_matches.

    Returns None if no usable face was found in any of the images.
    """
    embedding, image_bytes, gallery_score, all_image_bytes = usable_frames(images_base64)
    if embedding is None or image_bytes is None:
        return None

    image_path = save_capture_image(image_bytes)
    capture = UnknownFaceCapture(
        image_path=str(image_path),
        embedding=face_gallery.serialize_embedding(embedding),
        best_gallery_score=gallery_score if gallery_score is not None and gallery_score >= 0 else None,
        status="pending",
    )
    db.add(capture)
    db.flush()

    if run_web_search:
        # Search with up to settings.face_web_search_max_images usable frames
        # (not just the single "best" one) so FaceCheckID has multiple photos
        # of the same person to match against -- set to 1 in .env if multiple
        # images turn out to cost extra credits per search.
        max_images = max(1, getattr(settings, "face_web_search_max_images", 1))
        frames_to_send = (all_image_bytes or [image_bytes])[:max_images]
        run_facecheck_search(db, capture, frames_to_send)

    db.commit()
    db.refresh(capture)
    return capture