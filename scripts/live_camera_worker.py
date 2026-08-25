"""Continuous camera worker: watches a webcam and logs a recognition event
whenever a visitor stands in front of it long enough for a stable face.

Note: this script only detects and logs to the database. It has no UI, so it
cannot show suggestion choices or collect new-visitor details -- that part of
the flow already exists in the kiosk frontend (http://localhost:3002), which
calls the same recognition service through /api/kiosk/recognize-face.

Run with:
    uv run --python 3.12 python scripts/live_camera_worker.py
"""

from __future__ import annotations

import argparse
import base64
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2

from app.database import SessionLocal
from app.face_recognition_service import get_face_recognition_service
from app.models import RecognitionEvent


def _frame_to_base64(frame) -> str:
    ok, buffer = cv2.imencode(".jpg", frame)
    if not ok:
        raise RuntimeError("Could not encode frame to JPEG.")
    return "data:image/jpeg;base64," + base64.b64encode(buffer).decode("ascii")


def _has_face(service, frame) -> bool:
    faces = service._face_app().get(frame)
    return bool(faces)


def _log_event(camera_id: str, result) -> None:
    """Log one RecognitionEvent per candidate considered (up to 3), so all
    suggestions are recorded, not just the top one."""
    db = SessionLocal()
    try:
        candidates = (
            [result.best_match] if result.best_match
            else result.suggestions if result.suggestions
            else [None]
        )
        for rank, candidate in enumerate(candidates, start=1):
            db.add(
                RecognitionEvent(
                    matched_name=candidate.name if candidate else None,
                    camera_id=camera_id,
                    confidence=candidate.score if candidate else None,
                    recognized=result.status == "recognized" and rank == 1,
                )
            )
        db.commit()
    finally:
        db.close()


def run(camera_index: int, camera_id: str, poll_interval: float) -> None:
    service = get_face_recognition_service()
    print("Warming up face model...")
    service.warm_up()
    print(f"Watching camera {camera_index} as '{camera_id}'. Ctrl+C to stop.")

    capture = cv2.VideoCapture(camera_index)
    if not capture.isOpened():
        raise RuntimeError(f"Could not open camera index {camera_index}.")

    state = "watching"
    consecutive_face_frames = 0
    consecutive_empty_frames = 0

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                time.sleep(poll_interval)
                continue

            face_present = _has_face(service, frame)

            if state == "watching":
                consecutive_face_frames = consecutive_face_frames + 1 if face_present else 0

                if consecutive_face_frames >= 2:
                    print("Person detected. Capturing 3 quick shots...")
                    images = []
                    for _ in range(3):
                        ok, shot = capture.read()
                        if ok:
                            images.append(_frame_to_base64(shot))
                        time.sleep(0.1)

                    if images:
                        result = service.recognize_images_base64(images)
                        print(f"  -> status={result.status}")
                        if result.status == "recognized" and result.best_match:
                            print(f"     match: {result.best_match.name} (score={result.best_match.score:.3f})")
                        elif result.status == "suggestions":
                            print("     top candidates:")
                            for i, candidate in enumerate(result.suggestions, start=1):
                                print(f"       {i}. {candidate.name} (score={candidate.score:.3f})")
                        elif result.status == "not_registered":
                            print("     no close match -> this visitor would be prompted to register")
                        _log_event(camera_id, result)

                    consecutive_face_frames = 0
                    consecutive_empty_frames = 0
                    state = "clearing"
                    print("Waiting for this person to step away...")
                else:
                    time.sleep(poll_interval)

            else:  # state == "clearing"
                consecutive_empty_frames = consecutive_empty_frames + 1 if not face_present else 0
                if consecutive_empty_frames >= 3:
                    state = "watching"
                    print("Ready for the next visitor.")
                time.sleep(poll_interval)
    finally:
        capture.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--camera-id", default="front_door")
    parser.add_argument("--interval", type=float, default=0.3, help="Seconds between polls.")
    args = parser.parse_args()

    run(args.camera_index, args.camera_id, args.interval)