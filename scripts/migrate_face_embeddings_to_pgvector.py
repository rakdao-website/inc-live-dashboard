"""One-off: copy face embeddings from the legacy Postgres face_embeddings
table (JSON text) into the pgvector face_vectors table, so everyone enrolled
under the old flow is recognised by the live matcher.

Run once, after migrations/2026_10_03_add_pgvector_face_vectors.sql:
    .venv/bin/python -m scripts.migrate_face_embeddings_to_pgvector
"""
from collections import defaultdict

from app.database import SessionLocal
from app.face_gallery import deserialize_embedding
from app.face_recognition_service import FaceDatabase
from app.models import FaceEmbedding


def main() -> None:
    grouped: dict[str, list] = defaultdict(list)
    with SessionLocal() as db:
        for row in db.query(FaceEmbedding).all():
            grouped[row.face_identifier].append(deserialize_embedding(row.embedding))

    if not grouped:
        print("No legacy face embeddings found. Nothing to migrate.")
        return

    database = FaceDatabase()
    for identifier, embeddings in grouped.items():
        database.replace_person(identifier, embeddings)
        print(f"Migrated '{identifier}': {len(embeddings)} embedding(s)")
    print("Done.")


if __name__ == "__main__":
    main()
