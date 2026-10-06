"""See who is enrolled and who a photo matches (read-only).

Usage (from inc-live-dashboard):
    .venv/bin/python -m scripts.face_debug --list
    .venv/bin/python -m scripts.face_debug --image path/to/photo.jpg
"""
import argparse
import base64
from pathlib import Path

from sqlalchemy import text

from app.database import SessionLocal
from app.face_recognition_service import MATCH_THRESHOLD, get_face_recognition_service
from app.models import Visitor


def visitor_label(db, identifier: str | None) -> str:
    if identifier and identifier.startswith("visitor:") and identifier[8:].isdigit():
        visitor = db.get(Visitor, int(identifier[8:]))
        if visitor:
            return f"{visitor.visitor_name} (id {visitor.visitor_id}, {visitor.visitor_type})"
    return f"{identifier} (no matching visitor record)"


def list_enrolled() -> None:
    with SessionLocal() as db:
        rows = db.execute(text(
            "SELECT face_identifier, count(*) AS n FROM face_vectors GROUP BY 1 ORDER BY 1"
        )).all()
        print(f"People with face vectors: {len(rows)}")
        for identifier, count in rows:
            print(f"  {visitor_label(db, identifier)}: {count} vector(s)")
        consented = db.query(Visitor).filter(Visitor.face_consent_given.is_(True)).count()
        total = db.query(Visitor).count()
        print(f"Visitors: {total}, with face consent: {consented}")
        enrolled_ids = {r[0] for r in rows}
        missing = [v for v in db.query(Visitor).filter(Visitor.face_reference_id.isnot(None)).all()
                   if v.face_reference_id not in enrolled_ids]
        for v in missing:
            print(f"  ! {v.visitor_name} has face_reference_id {v.face_reference_id} but NO vectors: cannot be recognised")
        if not rows:
            print("\nNobody is enrolled, so no face can be recognised. Enrol faces first "
                  "(kiosk registration, scripts.seed_people with photos, or import_existing_faces).")


def match_image(path: Path) -> None:
    service = get_face_recognition_service()
    image = "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    try:
        embedding = service.embedding_from_image_base64(image)
    except ValueError:
        print("No face detected in this photo. Use a clear, front-facing, well-lit photo.")
        return
    matches = service.database.match(embedding, top_k=3)
    print(f"Threshold: {MATCH_THRESHOLD} (score at or above = recognised)\n")
    if not matches:
        print("The face store is empty: nobody to match against.")
        return
    with SessionLocal() as db:
        for rank, m in enumerate(matches, start=1):
            verdict = "RECOGNISED" if m.score >= MATCH_THRESHOLD else "below threshold"
            print(f"{rank}. score {m.score:.3f}  {verdict:<16} {visitor_label(db, m.name)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="show who has face vectors")
    parser.add_argument("--image", type=Path, help="photo to test against the gallery")
    args = parser.parse_args()
    if args.image:
        match_image(args.image)
    else:
        list_enrolled()


if __name__ == "__main__":
    main()
