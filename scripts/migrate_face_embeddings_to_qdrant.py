"""One-off: copy any face embeddings sitting in the old Postgres
face_embeddings table into Qdrant, so everyone registered via either
flow (kiosk enrollment or the /api/face review flow) is recognized by
the same live matcher.

Run once:
    uv run --python 3.12 python scripts/migrate_face_embeddings_to_qdrant.py
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.face_gallery import deserialize_embedding
from app.face_recognition_service import get_face_recognition_service
from app.models import FaceEmbedding


def main():
    db = SessionLocal()
    service = get_face_recognition_service()

    grouped: dict[str, list] = defaultdict(list)
    for row in db.query(FaceEmbedding).all():
        grouped[row.face_identifier].append(deserialize_embedding(row.embedding))

    if not grouped:
        print("No Postgres face embeddings found. Nothing to migrate.")
        return

    for identifier, embeddings in grouped.items():
        service.database.replace_person(identifier, embeddings)
        print(f"Migrated '{identifier}': {len(embeddings)} embedding(s)")

    db.close()
    print("Done.")


if __name__ == "__main__":
    main()