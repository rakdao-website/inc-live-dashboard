BEGIN;

CREATE TABLE IF NOT EXISTS visitors (
  visitor_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  visitor_name VARCHAR(150) NOT NULL,
  visitor_phone VARCHAR(40) NOT NULL UNIQUE,
  visitor_email VARCHAR(150),
  is_existing_client BOOLEAN NOT NULL DEFAULT FALSE,
  face_reference_id VARCHAR(120),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO visitors
  (visitor_name, visitor_phone, visitor_email, is_existing_client)
SELECT DISTINCT ON (visitor_phone)
  COALESCE(visitor_name, 'Visitor') AS visitor_name,
  visitor_phone,
  visitor_email,
  COALESCE(visitor_is_client, FALSE) AS is_existing_client
FROM bookings
WHERE visitor_phone IS NOT NULL
  AND visitor_phone <> ''
ON CONFLICT (visitor_phone) DO UPDATE
SET
  visitor_name = EXCLUDED.visitor_name,
  visitor_email = COALESCE(visitors.visitor_email, EXCLUDED.visitor_email),
  is_existing_client = visitors.is_existing_client OR EXCLUDED.is_existing_client,
  updated_at = CURRENT_TIMESTAMP;

COMMIT;

