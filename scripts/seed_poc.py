"""Seed the POC database (zones, visitors, bookings) and prepare the face dataset folders.

Usage (from inc-live-dashboard, with venv active):

    python scripts/seed_poc.py
    python scripts/seed_poc.py --create-tables
    python scripts/seed_poc.py --with-faces   # also run import if photos exist
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.seed import SEED_VISITORS, seed_sample_data  # noqa: E402

DATASET_DIR = PROJECT_ROOT / "dataset"


def ensure_dataset_folders() -> list[Path]:
    """Create one folder per seed visitor, named by phone for the import script."""
    created: list[Path] = []
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    for row in SEED_VISITORS:
        folder = DATASET_DIR / row["visitor_phone"]
        folder.mkdir(parents=True, exist_ok=True)
        readme = folder / "PUT_FACE_PHOTOS_HERE.txt"
        if not readme.exists():
            readme.write_text(
                f"Drop clear front-facing photos of {row['visitor_name']} here.\n"
                f"Supported: .jpg .jpeg .png .bmp .webp\n"
                f"Then run:\n"
                f"  python scripts/import_existing_faces.py --dataset ./dataset\n",
                encoding="utf-8",
            )
        created.append(folder)
    return created


def print_seed_summary(db) -> None:
    from sqlalchemy import func, select

    from app.models import FaceEmbedding, Visitor, Zone

    zones = db.scalar(select(func.count()).select_from(Zone)) or 0
    visitors = db.scalar(select(func.count()).select_from(Visitor)) or 0
    embeddings = db.scalar(select(func.count()).select_from(FaceEmbedding)) or 0
    print(f"Zones: {zones}")
    print(f"Visitors: {visitors}")
    print(f"Face embeddings: {embeddings}")
    print()
    print("Seed visitors (use these phones for profile-lookup / face import):")
    for row in SEED_VISITORS:
        print(
            f"  - {row['visitor_name']:20} {row['visitor_phone']}  "
            f"consent={row['face_consent_given']}  type={row['visitor_type']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed POC data for Innovation City dashboard.")
    parser.add_argument(
        "--create-tables",
        action="store_true",
        help="Create any missing SQLAlchemy tables before seeding.",
    )
    parser.add_argument(
        "--with-faces",
        action="store_true",
        help="After seeding visitors, import face photos from ./dataset if present.",
    )
    args = parser.parse_args()

    if args.create_tables:
        print("Creating tables...")
        Base.metadata.create_all(bind=engine)

    folders = ensure_dataset_folders()
    print(f"Dataset folders ready under {DATASET_DIR} ({len(folders)} people)")

    with SessionLocal() as db:
        print("Seeding sample data...")
        seed_sample_data(db)
        print_seed_summary(db)

    if args.with_faces:
        image_count = sum(
            1
            for folder in folders
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        )
        if image_count == 0:
            print(
                "\n--with-faces: no photos found in dataset/*/.\n"
                "Add .jpg/.png files into the phone-named folders, then re-run:\n"
                "  python scripts/import_existing_faces.py --dataset ./dataset"
            )
            return

        print(f"\nImporting {image_count} face photo(s)...")
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "import_existing_faces.py"), "--dataset", str(DATASET_DIR)],
            cwd=str(PROJECT_ROOT),
            check=False,
        )
        if result.returncode != 0:
            sys.exit(result.returncode)

    print("\nDone. Next:")
    print("  1. Put face photos in dataset/+9715.../")
    print("  2. python scripts/import_existing_faces.py --dataset ./dataset")
    print("  3. POST /api/face/detect with a matching photo")


if __name__ == "__main__":
    main()
