"""Bulk-enroll existing users' faces into the database gallery.

Point this at a folder with one sub-folder per person. Each sub-folder holds
one or more clear, front-facing photos of that person:

    dataset/
      +971501234567/          <- phone number  (matches Visitor.visitor_phone)
        1.jpg
        2.jpg
      12/                     <- numeric        (matches Visitor.visitor_id)
        a.png
      Aisha Khan/             <- name           (matches Visitor.visitor_name)
        photo.jpg

For every folder we resolve the visitor, compute a face embedding per image
with InsightFace, and store them in the `face_embeddings` table under the
identifier `visitor:{visitor_id}`. Recognition (/api/face/detect) then matches
live faces against these rows.

Usage (from the inc-live-dashboard folder, with the venv active):

    python scripts/import_existing_faces.py --dataset ./dataset
    python scripts/import_existing_faces.py --dataset ./dataset --create-missing
    python scripts/import_existing_faces.py --dataset ./dataset --dry-run
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

# Allow running as a plain script: add the project root (parent of app/) to sys.path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import face_gallery  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.face_recognition_service import (  # noqa: E402
    FaceRecognitionUnavailable,
    get_face_recognition_service,
)
from app.kiosk_flow_services import normalize_name, normalize_phone  # noqa: E402
from app.models import Visitor  # noqa: E402

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def resolve_visitor(db, folder_name: str, *, create_missing: bool) -> Visitor | None:
    label = folder_name.strip()

    if label.isdigit():
        visitor = db.get(Visitor, int(label))
        if visitor is None:
            print(f"  ! no visitor with id={label}")
        return visitor

    looks_like_phone = label.startswith("+") or label.replace(" ", "").isdigit()
    if looks_like_phone:
        phone = normalize_phone(label)
        visitor = next(
            (v for v in db.query(Visitor).all() if normalize_phone(v.visitor_phone) == phone),
            None,
        )
        if visitor is None and create_missing:
            visitor = Visitor(
                visitor_name=f"Imported {phone}",
                visitor_phone=phone,
                visitor_type="visitor",
                lead_source="face_import",
            )
            db.add(visitor)
            db.flush()
            print(f"  + created visitor id={visitor.visitor_id} phone={phone}")
        elif visitor is None:
            print(f"  ! no visitor with phone={phone} (use --create-missing to add)")
        return visitor

    wanted = normalize_name(label)
    visitor = next(
        (v for v in db.query(Visitor).all() if normalize_name(v.visitor_name) == wanted),
        None,
    )
    if visitor is None:
        print(f"  ! no visitor named '{label}' (name folders can't be auto-created; use phone or id)")
    return visitor


def embedding_for_image(service, image_path: Path):
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return service.embedding_from_image_base64(image_b64)


def import_dataset(dataset_dir: Path, *, create_missing: bool, dry_run: bool) -> None:
    people = sorted(p for p in dataset_dir.iterdir() if p.is_dir())
    if not people:
        print(f"No person sub-folders found in {dataset_dir}")
        return

    service = get_face_recognition_service()
    total_people = 0
    total_embeddings = 0

    with SessionLocal() as db:
        for person_dir in people:
            print(f"[{person_dir.name}]")
            images = [p for p in sorted(person_dir.iterdir()) if p.suffix.lower() in IMAGE_SUFFIXES]
            if not images:
                print("  ! no images, skipping")
                continue

            visitor = resolve_visitor(db, person_dir.name, create_missing=create_missing)
            if visitor is None:
                continue

            embeddings = []
            sources = []
            for image_path in images:
                try:
                    embeddings.append(embedding_for_image(service, image_path))
                    sources.append(str(image_path))
                    print(f"  - embedded {image_path.name}")
                except ValueError as exc:
                    print(f"  ! skipped {image_path.name}: {exc}")

            if not embeddings:
                print("  ! no usable faces, skipping")
                continue

            identifier = f"visitor:{visitor.visitor_id}"
            if dry_run:
                print(f"  = would store {len(embeddings)} embedding(s) as {identifier}")
            else:
                face_gallery.replace_embeddings(
                    db,
                    face_identifier=identifier,
                    embeddings=embeddings,
                    visitor_id=visitor.visitor_id,
                    source_images=sources,
                )
                visitor.face_reference_id = identifier
                print(f"  = stored {len(embeddings)} embedding(s) as {identifier}")

            total_people += 1
            total_embeddings += len(embeddings)

        if dry_run:
            db.rollback()
        else:
            db.commit()

    print(
        f"\nDone. {'(dry run) ' if dry_run else ''}"
        f"{total_people} visitor(s), {total_embeddings} embedding(s)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import existing users' faces into the DB gallery.")
    parser.add_argument("--dataset", required=True, help="Folder with one sub-folder per person.")
    parser.add_argument(
        "--create-missing",
        action="store_true",
        help="Create a visitor for phone-named folders that don't exist yet.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute embeddings and report, but do not write to the database.",
    )
    parser.add_argument(
        "--create-tables",
        action="store_true",
        help="Create any missing tables before importing (handy for a fresh POC DB).",
    )
    args = parser.parse_args()

    dataset_dir = Path(args.dataset).expanduser().resolve()
    if not dataset_dir.is_dir():
        parser.error(f"Dataset folder not found: {dataset_dir}")

    if args.create_tables:
        Base.metadata.create_all(bind=engine)

    try:
        import_dataset(dataset_dir, create_missing=args.create_missing, dry_run=args.dry_run)
    except FaceRecognitionUnavailable as exc:
        print(f"Face recognition unavailable: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
