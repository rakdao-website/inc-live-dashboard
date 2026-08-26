-- Face gallery in the database + unknown-face captures with web search matches.
-- Additive only: do not reset or drop existing data.

CREATE TABLE IF NOT EXISTS face_embeddings (
  face_embedding_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  visitor_id BIGINT REFERENCES visitors(visitor_id),
  face_identifier VARCHAR(160) NOT NULL,
  embedding TEXT NOT NULL,
  source_image VARCHAR(255),
  model_name VARCHAR(40) NOT NULL DEFAULT 'buffalo_l',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_face_embeddings_identifier
  ON face_embeddings(face_identifier);
CREATE INDEX IF NOT EXISTS idx_face_embeddings_visitor
  ON face_embeddings(visitor_id);

CREATE TABLE IF NOT EXISTS unknown_face_captures (
  capture_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  image_path VARCHAR(255) NOT NULL,
  embedding TEXT,
  best_gallery_score DOUBLE PRECISION,
  status VARCHAR(20) NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'web_searched', 'linked', 'dismissed')),
  web_search_status VARCHAR(40),
  linked_visitor_id BIGINT REFERENCES visitors(visitor_id),
  first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS face_web_matches (
  web_match_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  capture_id BIGINT NOT NULL REFERENCES unknown_face_captures(capture_id),
  rank INTEGER NOT NULL,
  source_url TEXT NOT NULL,
  score DOUBLE PRECISION,
  thumbnail_base64 TEXT,
  provider VARCHAR(40) NOT NULL DEFAULT 'facecheck',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_face_web_matches_capture
  ON face_web_matches(capture_id);
