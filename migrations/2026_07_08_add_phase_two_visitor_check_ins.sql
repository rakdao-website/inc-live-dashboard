-- Phase 2 kiosk check-in support.
-- Adds visitor identity metadata, an internal booking->visitor link,
-- and a check-in history table. The phone number remains the practical
-- matching field for visitor/booking workflows.

ALTER TABLE visitors
  ADD COLUMN IF NOT EXISTS license_number VARCHAR(80),
  ADD COLUMN IF NOT EXISTS face_consent_given BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS face_consent_at TIMESTAMP,
  ADD COLUMN IF NOT EXISTS lead_source VARCHAR(40),
  ADD COLUMN IF NOT EXISTS last_visit_at TIMESTAMP;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'visitors_license_number_key'
  ) THEN
    ALTER TABLE visitors ADD CONSTRAINT visitors_license_number_key UNIQUE (license_number);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'visitors_lead_source_check'
  ) THEN
    ALTER TABLE visitors ADD CONSTRAINT visitors_lead_source_check CHECK (
      lead_source IS NULL OR lead_source IN (
        'admin_visitors_tab',
        'admin_booking_tab',
        'screen_1_booking',
        'screen_2_booking',
        'screen_2_check_in'
      )
    );
  END IF;
END $$;

ALTER TABLE bookings
  ADD COLUMN IF NOT EXISTS visitor_id BIGINT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'bookings_visitor_id_fkey'
  ) THEN
    ALTER TABLE bookings
      ADD CONSTRAINT bookings_visitor_id_fkey
      FOREIGN KEY (visitor_id) REFERENCES visitors(visitor_id);
  END IF;
END $$;

UPDATE bookings AS b
SET visitor_id = v.visitor_id
FROM visitors AS v
WHERE b.visitor_id IS NULL
  AND b.visitor_phone IS NOT NULL
  AND b.visitor_phone = v.visitor_phone;

CREATE TABLE IF NOT EXISTS visitor_check_ins (
  check_in_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  visitor_id BIGINT REFERENCES visitors(visitor_id),
  visitor_phone VARCHAR(40),
  booking_id BIGINT REFERENCES bookings(booking_id),
  event_id BIGINT REFERENCES events(event_id),
  check_in_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  check_in_status VARCHAR(40) NOT NULL CHECK (
    check_in_status IN (
      'booking_found',
      'no_booking_found',
      'new_visitor_registered',
      'service_requested',
      'event_selected'
    )
  ),
  match_method VARCHAR(30) NOT NULL CHECK (match_method IN ('phone', 'license_number', 'face')),
  selected_service VARCHAR(40) CHECK (
    selected_service IS NULL OR selected_service IN (
      'meeting_room',
      'podcast_studio',
      'tiktok_studio',
      'event',
      'business_center',
      'other'
    )
  ),
  face_enrollment_status VARCHAR(30) CHECK (
    face_enrollment_status IS NULL OR face_enrollment_status IN (
      'not_enrolled',
      'enrolled',
      'failed'
    )
  )
);

CREATE INDEX IF NOT EXISTS ix_visitors_license_number ON visitors(license_number);
CREATE INDEX IF NOT EXISTS ix_bookings_visitor_id ON bookings(visitor_id);
CREATE INDEX IF NOT EXISTS ix_visitor_check_ins_visitor_id ON visitor_check_ins(visitor_id);
CREATE INDEX IF NOT EXISTS ix_visitor_check_ins_visitor_phone ON visitor_check_ins(visitor_phone);
CREATE INDEX IF NOT EXISTS ix_visitor_check_ins_booking_id ON visitor_check_ins(booking_id);
CREATE INDEX IF NOT EXISTS ix_visitor_check_ins_event_id ON visitor_check_ins(event_id);
