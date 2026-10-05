"""Seed clients and employees from a CSV and enrol their faces (dry run by default).

Usage (from inc-live-dashboard):
    .venv/bin/python -m scripts.seed_people                       # dry run, seed/private/people.csv
    .venv/bin/python -m scripts.seed_people --file seed/people.sample.csv
    .venv/bin/python -m scripts.seed_people --execute             # write to the database
    .venv/bin/python -m scripts.seed_people --execute --link-spacebring

Local photos are looked up under --photos-root (default seed/photos, or
seed/private/photos when the private CSV is used). See app/people_seed.py.
"""
import argparse
from pathlib import Path

from app.database import SessionLocal
from app.face_recognition_service import get_face_recognition_service
from app.people_seed import parse_people_csv, seed_people

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_CSV = ROOT / "seed" / "private" / "people.csv"
SAMPLE_CSV = ROOT / "seed" / "people.sample.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, help="people CSV (default: seed/private/people.csv, else the sample)")
    parser.add_argument("--photos-root", type=Path, help="base folder for relative photo_paths")
    parser.add_argument("--execute", action="store_true", help="write to the database (default is a dry run)")
    parser.add_argument("--link-spacebring", action="store_true", help="look up each person's Spacebring customer")
    args = parser.parse_args()

    csv_path = args.file or (PRIVATE_CSV if PRIVATE_CSV.exists() else SAMPLE_CSV)
    photos_root = args.photos_root or (
        ROOT / "seed" / "private" / "photos" if csv_path.parent.name == "private" else ROOT / "seed" / "photos"
    )
    print(f"People file: {csv_path}\nPhotos root: {photos_root}\nMode: {'EXECUTE' if args.execute else 'dry run'}\n")

    spacebring = None
    if args.link_spacebring:
        from app.spacebring_client import get_spacebring_client
        spacebring = get_spacebring_client()

    rows = parse_people_csv(csv_path)
    with SessionLocal() as db:
        results = seed_people(
            db, rows, photos_root=photos_root, face_service=get_face_recognition_service(),
            spacebring_client=spacebring, apply=args.execute,
        )
    for result in results:
        print(result.line_text())
    people = sum(1 for r in results if r.action != "skipped")
    faces = sum(r.faces_enrolled for r in results)
    skipped = sum(1 for r in results if r.action == "skipped")
    print(f"\n{people} people, {faces} face vector(s), {skipped} row(s) skipped."
          + ("" if args.execute else " Dry run: re-run with --execute to apply."))


if __name__ == "__main__":
    main()
