-- Kiosk visitor flow support.
-- Additive only: do not reset or drop existing dashboard data.

ALTER TABLE visitors
  ADD COLUMN IF NOT EXISTS visitor_type VARCHAR(20) NOT NULL DEFAULT 'visitor',
  ADD COLUMN IF NOT EXISTS company_name VARCHAR(160),
  ADD COLUMN IF NOT EXISTS company_number VARCHAR(80);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'visitors_visitor_type_check'
  ) THEN
    ALTER TABLE visitors ADD CONSTRAINT visitors_visitor_type_check
      CHECK (visitor_type IN ('client', 'visitor'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS face_profiles (
  face_profile_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  visitor_id BIGINT NOT NULL REFERENCES visitors(visitor_id),
  face_identifier VARCHAR(160) NOT NULL UNIQUE,
  consent_given BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS visit_sessions (
  visit_session_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  visitor_id BIGINT REFERENCES visitors(visitor_id),
  check_in_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  recognition_method VARCHAR(20) NOT NULL CHECK (recognition_method IN ('face', 'lookup', 'manual')),
  is_returning_visitor BOOLEAN NOT NULL DEFAULT FALSE,
  previous_visit_id BIGINT REFERENCES visit_sessions(visit_session_id),
  current_selected_service VARCHAR(40),
  visit_purpose VARCHAR(160),
  notes TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS visitor_activity (
  visitor_activity_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  visitor_id BIGINT REFERENCES visitors(visitor_id),
  visit_session_id BIGINT REFERENCES visit_sessions(visit_session_id),
  selected_service VARCHAR(40),
  visit_purpose VARCHAR(160),
  previous_selected_service VARCHAR(40),
  notes TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS packages (
  package_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  package_name VARCHAR(160) NOT NULL UNIQUE,
  package_description TEXT NOT NULL,
  price_label VARCHAR(80),
  features TEXT NOT NULL DEFAULT '',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS other_assistance_requests (
  other_assistance_request_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  visitor_id BIGINT REFERENCES visitors(visitor_id),
  visit_session_id BIGINT REFERENCES visit_sessions(visit_session_id),
  reason VARCHAR(120) NOT NULL,
  notes TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_face_profiles_visitor_id ON face_profiles(visitor_id);
CREATE INDEX IF NOT EXISTS ix_visit_sessions_visitor_id ON visit_sessions(visitor_id);
CREATE INDEX IF NOT EXISTS ix_visitor_activity_visitor_id ON visitor_activity(visitor_id);
CREATE INDEX IF NOT EXISTS ix_visitor_activity_visit_session_id ON visitor_activity(visit_session_id);
CREATE INDEX IF NOT EXISTS ix_other_assistance_requests_visitor_id ON other_assistance_requests(visitor_id);

INSERT INTO packages (package_name, package_description, price_label, features, is_active)
VALUES
  (
    'Idea',
    'Idea plan includes',
    'AED 6,600',
    '0 visa;Multiple shareholders allowed;10 standard or custom activities included;Shared desk included;Unlimited refreshments in Innovation HQ;Access to Innovation HQ event space and content creator studio',
    TRUE
  ),
  (
    'Seed',
    'Seed plan includes',
    'AED 13,200',
    '1 visa included (capped at 1);1 shareholder;1 custom or premium activity allowed (over 200 technology and innovation-related options);Shared desk included;Unlimited refreshments in Innovation HQ;Access to Innovation HQ event space and content creator studio',
    TRUE
  ),
  (
    'Startup',
    'Startup plan includes',
    'AED 15,400',
    '1 visa included (capped at 4);Multiple shareholders allowed;10 standard or custom activities included;Shared desk included;Unlimited refreshments in Innovation HQ;Unlimited access to Innovation HQ event space and content creator studio',
    TRUE
  ),
  (
    'Growth',
    'Growth plan includes',
    'AED 22,550',
    '1 visa included (capped at 4);Multiple shareholders allowed;10 standard or custom activities included;Dedicated desk included;Unlimited refreshments in Innovation HQ;Unlimited access to Innovation HQ event space and content creator studio',
    TRUE
  )
ON CONFLICT (package_name) DO NOTHING;
