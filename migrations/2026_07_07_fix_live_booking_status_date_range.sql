BEGIN;

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

