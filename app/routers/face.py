"""Face endpoints: detect -> match gallery -> (if unknown) reverse web search.

Flow for POST /api/face/detect:
  1. Detect the largest face in the image and compute its embedding.
  2. Match against the DB face gallery (face_embeddings table).
  3. If it matches a known visitor -> return that visitor.
  4. If not -> save the crop, create an unknown_face_captures row, and run a
     reverse web search returning the top candidate matches for a human to review.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app import face_gallery, face_web_search
from app.database import get_db
from app.face_recognition_service import (
    FaceRecognitionUnavailable,
    get_face_recognition_service,
)
from app.face_schemas import (
    CaptureRead,
    DetectFaceRequest,
    DetectFaceResponse,
    LinkCaptureRequest,
)
from app.face_web_search import WebFaceSearchUnavailable
from app.kiosk_flow_services import normalize_name, normalize_phone
from app.models import FaceWebMatch, UnknownFaceCapture, Visitor

router = APIRouter(prefix="/api/face", tags=["Face"])

UNKNOWN_FACE_DIR = Path(__file__).resolve().parents[2] / "data" / "unknown_faces"


def _success(message: str, data=None) -> dict:
    return {"success": True, "message": message, "data": {} if data is None else data}


def _error(message: str, error_code: str) -> dict:
    return {"success": False, "message": message, "error_code": error_code}


def _not_found(message: str, error_code: str) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=_error(message, error_code))


def _bad_request(message: str, error_code: str) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=_error(message, error_code))


def _decode_base64(image_base64: str) -> bytes:
    payload = image_base64.split(",", 1)[-1]
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Could not decode the face image.") from exc


def _save_capture_image(image_bytes: bytes) -> Path:
    UNKNOWN_FACE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = UNKNOWN_FACE_DIR / f"unknown_{stamp}.jpg"
    path.write_bytes(image_bytes)
    return path


def _resolve_visitor(db: Session, match: face_gallery.GalleryMatch) -> Visitor | None:
    if match.visitor_id is not None:
        return db.get(Visitor, match.visitor_id)
    identifier = str(match.face_identifier or "").strip()
    if not identifier:
        return None
    for visitor in db.query(Visitor).all():
        if str(getattr(visitor, "face_reference_id", "") or "").strip() == identifier:
            return visitor
    return None


def _run_web_search(db: Session, capture: UnknownFaceCapture, image_bytes: bytes) -> None:
    """Populate capture.web_matches from the reverse web search provider.

    Any provider failure is stored on web_search_status and swallowed, so the
    kiosk never breaks just because the external search is down or unset.
    """
    db.query(FaceWebMatch).filter(FaceWebMatch.capture_id == capture.capture_id).delete(
        synchronize_session=False
    )
    try:
        matches = face_web_search.search_web_faces(image_bytes, limit=3)
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


def _capture_payload(db: Session, capture: UnknownFaceCapture) -> dict:
    db.refresh(capture)
    return CaptureRead.model_validate(capture).model_dump(mode="json")


@router.post("/detect")
def detect_face(payload: DetectFaceRequest, db: Session = Depends(get_db)):
    images = payload.images_base64 or ([payload.image_base64] if payload.image_base64 else [])
    if not images:
        return _bad_request(
            "A camera image is required for face detection.", "FACE_IMAGE_REQUIRED"
        )

    try:
        service = get_face_recognition_service()
        best_embedding = None
        best_bytes = None
        best_score = -1.0
        best_match = None
        for image_base64 in images:
            image_bytes = _decode_base64(image_base64)
            embedding = service.embedding_from_image_base64(image_base64)
            match = face_gallery.match_embedding(db, embedding)
            if match.score > best_score:
                best_score = match.score
                best_embedding = embedding
                best_bytes = image_bytes
                best_match = match
    except FaceRecognitionUnavailable as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_error(str(exc), "FACE_RECOGNITION_UNAVAILABLE"),
        )
    except ValueError as exc:
        return _bad_request(str(exc), "FACE_IMAGE_INVALID")

    if best_match is not None and best_match.recognized:
        visitor = _resolve_visitor(db, best_match)
        return _success(
            "Face recognized",
            DetectFaceResponse(
                recognized=True,
                visitor_id=visitor.visitor_id if visitor else None,
                matched_name=visitor.visitor_name if visitor else None,
                face_identifier=best_match.face_identifier,
                confidence=best_match.score,
            ).model_dump(mode="json"),
        )

    image_path = _save_capture_image(best_bytes)
    capture = UnknownFaceCapture(
        image_path=str(image_path),
        embedding=face_gallery.serialize_embedding(best_embedding),
        best_gallery_score=best_score if best_score >= 0 else None,
        status="pending",
    )
    db.add(capture)
    db.flush()

    if payload.run_web_search:
        _run_web_search(db, capture, best_bytes)

    db.commit()

    return _success(
        "Face not recognized; captured for review",
        DetectFaceResponse(
            recognized=False,
            confidence=best_score if best_score >= 0 else None,
            capture=CaptureRead.model_validate(capture),
        ).model_dump(mode="json"),
    )


@router.get("/captures")
def list_captures(status_filter: str | None = None, limit: int = 50, db: Session = Depends(get_db)):
    query = db.query(UnknownFaceCapture)
    if status_filter:
        query = query.filter(UnknownFaceCapture.status == status_filter)
    captures = (
        query.order_by(UnknownFaceCapture.last_seen_at.desc()).limit(limit).all()
    )
    return _success(
        "Captures retrieved",
        [CaptureRead.model_validate(capture).model_dump(mode="json") for capture in captures],
    )


@router.get("/captures/{capture_id}")
def get_capture(capture_id: int, db: Session = Depends(get_db)):
    capture = db.get(UnknownFaceCapture, capture_id)
    if capture is None:
        return _not_found("Capture not found", "CAPTURE_NOT_FOUND")
    return _success("Capture retrieved", CaptureRead.model_validate(capture).model_dump(mode="json"))


@router.get("/captures/{capture_id}/image")
def get_capture_image(capture_id: int, db: Session = Depends(get_db)):
    capture = db.get(UnknownFaceCapture, capture_id)
    if capture is None:
        return _not_found("Capture not found", "CAPTURE_NOT_FOUND")
    path = Path(capture.image_path)
    if not path.exists():
        return _not_found("Capture image file missing", "CAPTURE_IMAGE_MISSING")
    return FileResponse(str(path), media_type="image/jpeg")


@router.post("/captures/{capture_id}/web-search")
def rerun_web_search(capture_id: int, db: Session = Depends(get_db)):
    capture = db.get(UnknownFaceCapture, capture_id)
    if capture is None:
        return _not_found("Capture not found", "CAPTURE_NOT_FOUND")

    path = Path(capture.image_path)
    if not path.exists():
        return _not_found("Capture image file missing", "CAPTURE_IMAGE_MISSING")

    _run_web_search(db, capture, path.read_bytes())
    db.commit()
    return _success("Web search completed", _capture_payload(db, capture))


@router.post("/captures/{capture_id}/link", status_code=status.HTTP_201_CREATED)
def link_capture(capture_id: int, payload: LinkCaptureRequest, db: Session = Depends(get_db)):
    capture = db.get(UnknownFaceCapture, capture_id)
    if capture is None:
        return _not_found("Capture not found", "CAPTURE_NOT_FOUND")

    if payload.visitor_id is not None:
        visitor = db.get(Visitor, payload.visitor_id)
        if visitor is None:
            return _not_found("Visitor not found", "VISITOR_NOT_FOUND")
    else:
        if not payload.full_name or not payload.mobile_number:
            return _bad_request(
                "Provide visitor_id, or full_name and mobile_number to create a visitor.",
                "VISITOR_DETAILS_REQUIRED",
            )
        phone = normalize_phone(payload.mobile_number)
        visitor = next(
            (v for v in db.query(Visitor).all() if normalize_phone(v.visitor_phone) == phone),
            None,
        )
        if visitor is None:
            visitor = Visitor(
                visitor_name=payload.full_name,
                visitor_phone=phone,
                visitor_email=payload.email,
                visitor_type=payload.visitor_type,
                is_existing_client=payload.visitor_type == "client",
                lead_source="face_web_review",
            )
            db.add(visitor)
            db.flush()

    identifier = f"visitor:{visitor.visitor_id}"
    if payload.enroll_face and capture.embedding:
        face_gallery.replace_embeddings(
            db,
            face_identifier=identifier,
            embeddings=[face_gallery.deserialize_embedding(capture.embedding)],
            visitor_id=visitor.visitor_id,
            source_images=[capture.image_path],
        )
        visitor.face_reference_id = identifier

    capture.status = "linked"
    capture.linked_visitor_id = visitor.visitor_id
    db.commit()

    return _success(
        "Capture linked to visitor",
        {
            "capture_id": capture.capture_id,
            "visitor_id": visitor.visitor_id,
            "face_identifier": identifier if payload.enroll_face else None,
            "enrolled": bool(payload.enroll_face and capture.embedding),
        },
    )


@router.post("/captures/{capture_id}/dismiss")
def dismiss_capture(capture_id: int, db: Session = Depends(get_db)):
    capture = db.get(UnknownFaceCapture, capture_id)
    if capture is None:
        return _not_found("Capture not found", "CAPTURE_NOT_FOUND")
    capture.status = "dismissed"
    db.commit()
    return _success("Capture dismissed", {"capture_id": capture_id, "status": "dismissed"})
