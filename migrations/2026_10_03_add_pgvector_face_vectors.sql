-- Move live face matching from Qdrant to PostgreSQL (pgvector).
-- Additive only. The legacy face_embeddings table (JSON text) is untouched;
-- scripts/migrate_face_embeddings_to_pgvector.py copies its rows over.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS face_vectors (
  face_vector_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  face_identifier VARCHAR(160) NOT NULL,          -- "visitor:<visitor_id>"
  visitor_id BIGINT REFERENCES visitors(visitor_id),
  embedding vector(512) NOT NULL,                 -- L2-normalised, ArcFace / buffalo_l
  photo_base64 TEXT,                              -- thumbnail shown in suggestions
  model_name VARCHAR(40) NOT NULL DEFAULT 'buffalo_l',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_face_vectors_identifier ON face_vectors(face_identifier);
CREATE INDEX IF NOT EXISTS idx_face_vectors_visitor ON face_vectors(visitor_id);

-- Approximate nearest-neighbour index, cosine distance (matches Qdrant's metric).
CREATE INDEX IF NOT EXISTS idx_face_vectors_embedding_hnsw
  ON face_vectors USING hnsw (embedding vector_cosine_ops);
