BEGIN;

ALTER TABLE bookings
  ADD COLUMN IF NOT EXISTS visitor_email VARCHAR(150);

ALTER TABLE bookings
  ADD COLUMN IF NOT EXISTS booking_start_date DATE,
  ADD COLUMN IF NOT EXISTS booking_end_date DATE;

UPDATE bookings
SET
  booking_start_date = COALESCE(booking_start_date, booking_date),
  booking_end_date = COALESCE(booking_end_date, booking_date)
WHERE booking_start_date IS NULL
   OR booking_end_date IS NULL;

ALTER TABLE bookings
  ALTER COLUMN booking_start_date SET NOT NULL,
  ALTER COLUMN booking_end_date SET NOT NULL;

DROP VIEW IF EXISTS live_bookings;

CREATE VIEW live_bookings AS
SELECT
  b.booking_id, b.zone_id, b.booking_type, b.booking_name,
  b.booking_start_date, b.booking_end_date, b.booking_date,
  b.visitor_name, b.visitor_phone, b.visitor_email, b.visitor_is_client,
  b.booking_time_start, b.booking_time_end,
  CASE
    WHEN b.booking_end_date < CURRENT_DATE
      OR (b.booking_end_date = CURRENT_DATE AND b.booking_time_end <= LOCALTIME) THEN 'ended'
    WHEN b.booking_start_date <= CURRENT_DATE
      AND b.booking_end_date >= CURRENT_DATE
      AND b.booking_time_start <= LOCALTIME
      AND b.booking_time_end > LOCALTIME THEN 'live'
    ELSE 'upcoming'
  END AS booking_status
FROM bookings b;

COMMIT;
