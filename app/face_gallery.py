"""Database-backed face gallery.

The gallery is the set of known face embeddings stored in the `face_embeddings`
table. Recognition loads every row and picks the highest cosine similarity,
which replaces the old single-file `embeddings.pkl` as the source of truth.

Embeddings are stored as JSON arrays of floats so the same schema works on
PostgreSQL and SQLite without a vector extension. This is fine for a POC-sized
gallery (hundreds to low thousands of faces); swap to a vector store later if
it needs to scale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from app.models import FaceEmbedding

SIMILARITY_THRESHOLD = 0.50


@dataclass(frozen=True)
class GalleryMatch:
    visitor_id: int | None
    face_identifier: str | None
    score: float
    recognized: bool


def _normalize(vector) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32)
    norm = np.linalg.norm(array)
    return array if norm == 0 else array / norm


def serialize_embedding(vector) -> str:
    return json.dumps(_normalize(vector).tolist())


def deserialize_embedding(payload: str) -> np.ndarray:
    return np.asarray(json.loads(payload), dtype=np.float32)


def add_embedding(
    db: Session,
    *,
    face_identifier: str,
    embedding,
    visitor_id: int | None = None,
    source_image: str | None = None,
    model_name: str = "buffalo_l",
) -> FaceEmbedding:
    row = FaceEmbedding(
        visitor_id=visitor_id,
        face_identifier=face_identifier,
        embedding=serialize_embedding(embedding),
        source_image=source_image,
        model_name=model_name,
    )
    db.add(row)
    return row


def replace_embeddings(
    db: Session,
    *,
    face_identifier: str,
    embeddings: list,
    visitor_id: int | None = None,
    source_images: list[str] | None = None,
    model_name: str = "buffalo_l",
) -> int:
    """Delete any existing rows for this identifier and insert fresh ones."""
    db.query(FaceEmbedding).filter(
        FaceEmbedding.face_identifier == face_identifier
    ).delete(synchronize_session=False)

    images = source_images or [None] * len(embeddings)
    for embedding, source_image in zip(embeddings, images):
        add_embedding(
            db,
            face_identifier=face_identifier,
            embedding=embedding,
            visitor_id=visitor_id,
            source_image=source_image,
            model_name=model_name,
        )
    return len(embeddings)


def match_embedding(
    db: Session,
    embedding,
    *,
    threshold: float = SIMILARITY_THRESHOLD,
) -> GalleryMatch:
    query = _normalize(embedding)
    rows = db.query(FaceEmbedding).all()

    best: FaceEmbedding | None = None
    best_score = -1.0
    for row in rows:
        score = float(np.dot(query, _normalize(deserialize_embedding(row.embedding))))
        if score > best_score:
            best_score = score
            best = row

    if best is None:
        return GalleryMatch(visitor_id=None, face_identifier=None, score=-1.0, recognized=False)

    return GalleryMatch(
        visitor_id=best.visitor_id,
        face_identifier=best.face_identifier,
        score=best_score,
        recognized=best_score >= threshold,
    )
