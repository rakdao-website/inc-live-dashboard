-- Optional SQL seed for visitors (run after migrations).
-- Prefer: python scripts/seed_poc.py --create-tables

INSERT INTO visitors (
  visitor_name, visitor_phone, visitor_email, license_number,
  visitor_type, company_name, company_number, is_existing_client,
  face_consent_given, lead_source
)
VALUES
  ('Aisha Khan', '+971501234567', 'aisha.khan@example.com', 'LIC-1001',
   'client', 'Aisha Ventures', 'CN-1001', TRUE, TRUE, 'seed'),
  ('Omar Hassan', '+971551112233', 'omar.hassan@example.com', 'LIC-1002',
   'visitor', NULL, NULL, FALSE, TRUE, 'seed'),
  ('Sara Al Maktoum', '+971529998877', 'sara.almaktoum@example.com', 'LIC-1003',
   'client', 'Desert Labs', 'CN-1003', TRUE, TRUE, 'seed'),
  ('James Chen', '+971504445566', 'james.chen@example.com', NULL,
   'visitor', 'Chen Soft', NULL, FALSE, TRUE, 'seed'),
  ('Fatima Noor', '+971567778899', 'fatima.noor@example.com', 'LIC-1005',
   'client', 'Noor Media', 'CN-1005', TRUE, FALSE, 'seed')
ON CONFLICT (visitor_phone) DO NOTHING;

-- Link face_reference_id + face_profiles for consent=true visitors
UPDATE visitors
SET face_reference_id = 'visitor:' || visitor_id::text,
    face_consent_at = CURRENT_TIMESTAMP
WHERE face_consent_given = TRUE
  AND (face_reference_id IS NULL OR face_reference_id = '');

INSERT INTO face_profiles (visitor_id, face_identifier, consent_given)
SELECT visitor_id, 'visitor:' || visitor_id::text, TRUE
FROM visitors
WHERE face_consent_given = TRUE
  AND NOT EXISTS (
    SELECT 1 FROM face_profiles fp WHERE fp.visitor_id = visitors.visitor_id
  );
