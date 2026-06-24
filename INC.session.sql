-- Innovation City Live Dashboard - PostgreSQL MVP
-- Ground Floor only. Fields marked "Later" are excluded.
-- This resets ONLY the dashboard tables created by the previous scripts.

BEGIN;
SET TIME ZONE 'Asia/Dubai';

DROP VIEW IF EXISTS live_activity_feed;
DROP VIEW IF EXISTS live_activity_metrics;
DROP VIEW IF EXISTS admin_zones;
DROP VIEW IF EXISTS live_ground_floor_map;
DROP VIEW IF EXISTS live_events;
DROP VIEW IF EXISTS live_bookings;
DROP FUNCTION IF EXISTS prevent_schedule_overlap() CASCADE;
DROP TABLE IF EXISTS activity_feed;
DROP TABLE IF EXISTS bookings;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS sector_metrics;
DROP TABLE IF EXISTS sectors;
DROP TABLE IF EXISTS ecosystem_metrics;
DROP TABLE IF EXISTS daily_activity_metrics;
DROP TABLE IF EXISTS zones;

-- Ground Floor Interactive Map
CREATE TABLE zones (
  zone_id VARCHAR(30) PRIMARY KEY,
  zone_name VARCHAR(120) NOT NULL UNIQUE,
  zone_type VARCHAR(40) NOT NULL,
  is_bookable BOOLEAN NOT NULL DEFAULT FALSE,
  is_closed BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Business Ecosystem Snapshot
-- ecosystem_id is only this table's own primary key; it does not link to activity metrics.
CREATE TABLE ecosystem_metrics (
  ecosystem_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  snapshot_date DATE NOT NULL UNIQUE,
  active_companies INTEGER NOT NULL CHECK (active_companies >= 0),
  active_licenses INTEGER NOT NULL CHECK (active_licenses >= 0),
  top_sector VARCHAR(100) NOT NULL,
  recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Sector Overview: one table is enough for the dashboard chart.
CREATE TABLE sectors (
  sector_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sector_name VARCHAR(100) NOT NULL UNIQUE,
  company_count INTEGER NOT NULL CHECK (company_count >= 0),
  source_name VARCHAR(200) NOT NULL,
  display_order SMALLINT NOT NULL UNIQUE CHECK (display_order > 0)
);

-- Events Panel. Each event must be assigned to a map zone.
CREATE TABLE events (
  event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  zone_id VARCHAR(30) NOT NULL REFERENCES zones(zone_id),
  event_name VARCHAR(200) NOT NULL,
  event_date DATE NOT NULL,
  event_time_start TIME NOT NULL,
  event_time_end TIME NOT NULL,
  event_location VARCHAR(120) NOT NULL DEFAULT 'Event Area',
  event_status VARCHAR(10) NOT NULL DEFAULT 'upcoming'
    CHECK (event_status IN ('upcoming', 'live', 'ended')),
  event_organizer VARCHAR(150) NOT NULL,
  event_attendee_count INTEGER CHECK (event_attendee_count >= 0),
  CHECK (event_time_end > event_time_start)
);

-- Meeting and studio reservations. Each booking must be assigned to a map zone.
CREATE TABLE bookings (
  booking_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  zone_id VARCHAR(30) NOT NULL REFERENCES zones(zone_id),
  booking_type VARCHAR(10) NOT NULL CHECK (booking_type IN ('meeting', 'studio', 'office')),
  booking_name VARCHAR(200) NOT NULL,
  booking_date DATE NOT NULL,
  booking_time_start TIME NOT NULL,
  booking_time_end TIME NOT NULL,
  CHECK (booking_time_end > booking_time_start)
);

-- Live Activity Feed.
-- An update can point directly to a zone, or indirectly through an event/booking.
-- The view below resolves the correct zone, so an event/booking cannot show the wrong zone.
CREATE TABLE activity_feed (
  feed_id VARCHAR(40) PRIMARY KEY,
  zone_id VARCHAR(30) REFERENCES zones(zone_id),
  event_id BIGINT REFERENCES events(event_id),
  booking_id BIGINT REFERENCES bookings(booking_id),
  activity_action VARCHAR(30) NOT NULL CHECK (activity_action IN (
    'occupied', 'available', 'starts_in_30', 'starts_in_15',
    'starts_now', 'license_application_submitted'
  )),
  category VARCHAR(10) NOT NULL CHECK (category IN ('room', 'event', 'company', 'studio')),
  occurred_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CHECK (NOT (event_id IS NOT NULL AND booking_id IS NOT NULL)),
  CHECK (
    (category = 'event' AND event_id IS NOT NULL)
    OR (category IN ('room', 'studio') AND (zone_id IS NOT NULL OR booking_id IS NOT NULL))
    OR (category = 'company' AND activity_action = 'license_application_submitted'
        AND zone_id IS NULL AND event_id IS NULL AND booking_id IS NULL)
  )
);

-- Reject a schedule that clashes with an event OR booking in the same map zone.
-- End times are exclusive, so a booking ending at 12:00 and another starting at 12:00 is allowed.
CREATE FUNCTION prevent_schedule_overlap()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  -- Only bookable, unlocked zones can receive events or bookings.
  IF EXISTS (SELECT 1 FROM zones WHERE zone_id = NEW.zone_id AND is_bookable = FALSE) THEN
    RAISE EXCEPTION 'Zone % is not bookable.', NEW.zone_id;
  END IF;

  IF EXISTS (SELECT 1 FROM zones WHERE zone_id = NEW.zone_id AND is_closed = TRUE) THEN
    RAISE EXCEPTION 'Zone % is closed. Unlock it before adding an event or booking.', NEW.zone_id;
  END IF;

  IF TG_TABLE_NAME = 'events' THEN
    IF EXISTS (
      SELECT 1 FROM events e
      WHERE e.zone_id = NEW.zone_id
        AND e.event_date = NEW.event_date
        AND e.event_id <> COALESCE(NEW.event_id, -1)
        AND NEW.event_time_start < e.event_time_end
        AND NEW.event_time_end > e.event_time_start
    ) OR EXISTS (
      SELECT 1 FROM bookings b
      WHERE b.zone_id = NEW.zone_id
        AND b.booking_date = NEW.event_date
        AND NEW.event_time_start < b.booking_time_end
        AND NEW.event_time_end > b.booking_time_start
    ) THEN
      RAISE EXCEPTION 'This event overlaps another event or booking in zone %', NEW.zone_id;
    END IF;
  ELSE
    IF EXISTS (
      SELECT 1 FROM bookings b
      WHERE b.zone_id = NEW.zone_id
        AND b.booking_date = NEW.booking_date
        AND b.booking_id <> COALESCE(NEW.booking_id, -1)
        AND NEW.booking_time_start < b.booking_time_end
        AND NEW.booking_time_end > b.booking_time_start
    ) OR EXISTS (
      SELECT 1 FROM events e
      WHERE e.zone_id = NEW.zone_id
        AND e.event_date = NEW.booking_date
        AND NEW.booking_time_start < e.event_time_end
        AND NEW.booking_time_end > e.event_time_start
    ) THEN
      RAISE EXCEPTION 'This booking overlaps another booking or event in zone %', NEW.zone_id;
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER prevent_event_overlap
BEFORE INSERT OR UPDATE OF zone_id, event_date, event_time_start, event_time_end ON events
FOR EACH ROW EXECUTE FUNCTION prevent_schedule_overlap();

CREATE TRIGGER prevent_booking_overlap
BEFORE INSERT OR UPDATE OF zone_id, booking_date, booking_time_start, booking_time_end ON bookings
FOR EACH ROW EXECUTE FUNCTION prevent_schedule_overlap();

CREATE INDEX idx_events_zone_date ON events (zone_id, event_date);
CREATE INDEX idx_bookings_zone_date ON bookings (zone_id, booking_date);
CREATE INDEX idx_activity_feed_time ON activity_feed (occurred_at DESC);

-- Live Activity Cards. These figures are calculated from bookings, events, and zones.
-- There is no separate activity-metrics table for an admin to maintain.
CREATE VIEW live_activity_metrics AS
SELECT
  CURRENT_DATE AS snapshot_date,
  (
    SELECT COUNT(*)
    FROM zones z
    WHERE z.zone_type = 'meeting_room'
      AND z.is_bookable = TRUE
      AND z.is_closed = FALSE
      AND (
        EXISTS (
          SELECT 1 FROM events e
          WHERE e.zone_id = z.zone_id
            AND e.event_date = CURRENT_DATE
            AND e.event_time_start <= LOCALTIME
            AND e.event_time_end > LOCALTIME
        )
        OR EXISTS (
          SELECT 1 FROM bookings b
          WHERE b.zone_id = z.zone_id
            AND b.booking_date = CURRENT_DATE
            AND b.booking_time_start <= LOCALTIME
            AND b.booking_time_end > LOCALTIME
        )
      )
  ) AS meetings_active,
  (
    SELECT COUNT(*)
    FROM zones z
    WHERE z.is_bookable = TRUE
      AND z.is_closed = FALSE
      AND (
        EXISTS (
          SELECT 1 FROM events e
          WHERE e.zone_id = z.zone_id
            AND e.event_date = CURRENT_DATE
            AND e.event_time_start <= LOCALTIME
            AND e.event_time_end > LOCALTIME
        )
        OR EXISTS (
          SELECT 1 FROM bookings b
          WHERE b.zone_id = z.zone_id
            AND b.booking_date = CURRENT_DATE
            AND b.booking_time_start <= LOCALTIME
            AND b.booking_time_end > LOCALTIME
        )
      )
  ) AS zones_occupied,
  (
    SELECT COUNT(*) FROM zones WHERE is_bookable = TRUE
  ) AS zones_total,
  (
    SELECT COUNT(*) FROM events WHERE event_date = CURRENT_DATE
  ) AS events_today_count;

-- Event status is calculated automatically from today's date and time.
CREATE VIEW live_events AS
SELECT
  e.event_id, e.zone_id, e.event_name, e.event_date, e.event_time_start,
  e.event_time_end, e.event_location, e.event_organizer, e.event_attendee_count,
  CASE
    WHEN e.event_date < CURRENT_DATE
      OR (e.event_date = CURRENT_DATE AND e.event_time_end <= LOCALTIME) THEN 'ended'
    WHEN e.event_date = CURRENT_DATE
      AND e.event_time_start <= LOCALTIME
      AND e.event_time_end > LOCALTIME THEN 'live'
    ELSE 'upcoming'
  END AS event_status
FROM events e;

-- Booking status is calculated automatically from today's date and time.
CREATE VIEW live_bookings AS
SELECT
  b.booking_id, b.zone_id, b.booking_type, b.booking_name, b.booking_date,
  b.booking_time_start, b.booking_time_end,
  CASE
    WHEN b.booking_date < CURRENT_DATE
      OR (b.booking_date = CURRENT_DATE AND b.booking_time_end <= LOCALTIME) THEN 'ended'
    WHEN b.booking_date = CURRENT_DATE
      AND b.booking_time_start <= LOCALTIME
      AND b.booking_time_end > LOCALTIME THEN 'live'
    ELSE 'upcoming'
  END AS booking_status
FROM bookings b;

-- Ground Floor map status is calculated automatically from active events/bookings.
-- A zone with is_closed = TRUE always remains closed.
CREATE VIEW live_ground_floor_map AS
SELECT
  z.zone_id,
  z.zone_name,
  z.zone_type,
  effective_status.zone_status,
  (effective_status.zone_status = 'available') AS zone_pulse,
  CASE effective_status.zone_status
    WHEN 'available' THEN '#00C6AE'
    WHEN 'occupied' THEN '#FF4D6D'
    ELSE '#7B8794'
  END AS zone_highlight_color,
  active_schedule.start_time AS zone_start_time,
  active_schedule.end_time AS zone_end_time,
  z.updated_at
FROM zones z
LEFT JOIN LATERAL (
  SELECT schedule.zone_id, schedule.start_time, schedule.end_time
  FROM (
    SELECT e.zone_id, e.event_time_start AS start_time, e.event_time_end AS end_time
    FROM events e
    WHERE e.zone_id = z.zone_id
      AND e.event_date = CURRENT_DATE
      AND e.event_time_start <= LOCALTIME
      AND e.event_time_end > LOCALTIME
    UNION ALL
    SELECT b.zone_id, b.booking_time_start, b.booking_time_end
    FROM bookings b
    WHERE b.zone_id = z.zone_id
      AND b.booking_date = CURRENT_DATE
      AND b.booking_time_start <= LOCALTIME
      AND b.booking_time_end > LOCALTIME
  ) schedule
  LIMIT 1
) active_schedule ON TRUE
CROSS JOIN LATERAL (
  SELECT CASE
    WHEN z.is_closed THEN 'closed'
    WHEN active_schedule.zone_id IS NOT NULL THEN 'occupied'
    ELSE 'available'
  END AS zone_status
) effective_status;

-- Read this in the admin dashboard to list zones and their closed toggle.
-- Update the underlying zones.is_closed value when the admin changes the toggle.
CREATE VIEW admin_zones AS
SELECT
  z.zone_id, z.zone_name, z.zone_type, z.is_bookable, z.is_closed,
  m.zone_status AS current_map_status,
  m.zone_start_time, m.zone_end_time,
  active_booking.booking_id AS active_booking_id,
  active_booking.booking_name AS active_booking_name,
  active_booking.booking_type AS active_booking_type,
  m.zone_pulse, m.zone_highlight_color, z.updated_at
FROM zones z
JOIN live_ground_floor_map m ON m.zone_id = z.zone_id
LEFT JOIN LATERAL (
  SELECT b.booking_id, b.booking_name, b.booking_type
  FROM bookings b
  WHERE b.zone_id = z.zone_id
    AND b.booking_date = CURRENT_DATE
    AND b.booking_time_start <= LOCALTIME
    AND b.booking_time_end > LOCALTIME
  LIMIT 1
) active_booking ON TRUE;

-- Dashboard live feed. Event/booking updates inherit their zone details automatically.
CREATE VIEW live_activity_feed AS
SELECT
  af.feed_id,
  af.occurred_at,
  af.category,
  af.activity_action,
  z.zone_id,
  z.zone_name,
  z.zone_status,
  e.event_id,
  e.event_name,
  b.booking_id,
  b.booking_name,
  CASE af.activity_action
    WHEN 'occupied' THEN z.zone_name || ' is now occupied'
    WHEN 'available' THEN z.zone_name || ' is now available'
    WHEN 'starts_in_30' THEN COALESCE(e.event_name, b.booking_name) || ' starts in 30 minutes - ' || z.zone_name
    WHEN 'starts_in_15' THEN COALESCE(e.event_name, b.booking_name) || ' starts in 15 minutes - ' || z.zone_name
    WHEN 'starts_now' THEN COALESCE(e.event_name, b.booking_name) || ' starts now - ' || z.zone_name
    WHEN 'license_application_submitted' THEN 'New license application submitted'
  END AS display_message
FROM activity_feed af
LEFT JOIN events e ON e.event_id = af.event_id
LEFT JOIN bookings b ON b.booking_id = af.booking_id
LEFT JOIN live_ground_floor_map z ON z.zone_id = COALESCE(e.zone_id, b.zone_id, af.zone_id);

-- Sample data
INSERT INTO zones
  (zone_id, zone_name, zone_type, is_bookable, is_closed)
VALUES
  ('REC_1', 'Reception', 'reception', FALSE, FALSE),
  ('EVT_1', 'Event Area', 'event_space', TRUE, FALSE),
  ('TTS_1', 'TikTok Studio', 'studio', TRUE, FALSE),
  ('POD_1', 'Podcast Studio', 'studio', TRUE, FALSE),
  ('MR_1', 'Meeting Room 1', 'meeting_room', TRUE, FALSE),
  ('MR_2', 'Meeting Room 2', 'meeting_room', TRUE, FALSE),
  ('PAN_1', 'Pantry', 'amenity', FALSE, FALSE),
  ('ENT_1', 'Entrance Area', 'entrance', FALSE, FALSE),
  ('BAT_1', 'Bathroom', 'amenity', FALSE, TRUE);

INSERT INTO zones (zone_id, zone_name, zone_type, is_bookable, is_closed)
SELECT
  'OFF_' || LPAD(office_number::TEXT, 2, '0'),
  'Office ' || office_number,
  'office',
  TRUE,
  FALSE
FROM generate_series(1, 19) AS office_number;

INSERT INTO ecosystem_metrics
  (snapshot_date, active_companies, active_licenses, top_sector)
VALUES (CURRENT_DATE, 2001, 1202, 'Manufacturing');

INSERT INTO sectors (sector_name, company_count, source_name, display_order) VALUES
  ('Web3', 179, 'Official - Innovation City Documents', 1),
  ('Artificial Intelligence', 99, 'Official - Innovation City Documents', 2),
  ('Gaming', 75, 'Official - Innovation City Documents', 3),
  ('Manufacturing', 483, 'Official - Innovation City Documents', 4),
  ('Trading', 261, 'Official - Innovation City Documents', 5),
  ('Media', 457, 'Official - Innovation City Documents', 6),
  ('Software', 199, 'Official - Innovation City Documents', 7),
  ('E-commerce', 20, 'Official - Innovation City Documents', 8),
  ('Consulting', 171, 'Official - Innovation City Documents', 9),
  ('Other', 57, 'Official - Innovation City Documents', 10);

INSERT INTO events
  (zone_id, event_name, event_date, event_time_start, event_time_end, event_location, event_status, event_organizer, event_attendee_count)
VALUES
  ('EVT_1', 'AI Founders Meetup', CURRENT_DATE, '11:00', '12:30', 'Event Area', 'live', 'Innovation City', 42),
  ('EVT_1', 'Web3 Community Hour', CURRENT_DATE, '15:00', '16:00', 'Event Area', 'upcoming', 'Innovation City', NULL);

INSERT INTO bookings
  (zone_id, booking_type, booking_name, booking_date, booking_time_start, booking_time_end)
VALUES
  ('MR_1', 'meeting', 'Investor Strategy Meeting', CURRENT_DATE, '11:00', '12:00'),
  ('POD_1', 'studio', 'Founder Stories Podcast', CURRENT_DATE, '10:30', '12:30');

-- Current office occupancy: all 19 bookable offices are booked today.
INSERT INTO bookings
  (zone_id, booking_type, booking_name, booking_date, booking_time_start, booking_time_end)
SELECT
  'OFF_' || LPAD(office_number::TEXT, 2, '0'),
  'office',
  'Office ' || office_number || ' Booking',
  CURRENT_DATE,
  '00:00'::TIME,
  '23:59'::TIME
FROM generate_series(1, 19) AS office_number;

INSERT INTO activity_feed
  (feed_id, zone_id, event_id, booking_id, activity_action, category, occurred_at)
VALUES
  ('feed_001', NULL, NULL, 1, 'occupied', 'room', CURRENT_TIMESTAMP - INTERVAL '12 minutes'),
  ('feed_002', NULL, 1, NULL, 'starts_now', 'event', CURRENT_TIMESTAMP - INTERVAL '5 minutes'),
  ('feed_003', NULL, NULL, 2, 'occupied', 'studio', CURRENT_TIMESTAMP - INTERVAL '2 minutes'),
  ('feed_004', NULL, NULL, NULL, 'license_application_submitted', 'company', CURRENT_TIMESTAMP - INTERVAL '1 minute');

COMMIT;

-- Dashboard queries
SELECT * FROM live_activity_metrics;
SELECT * FROM live_activity_feed ORDER BY occurred_at DESC;
SELECT * FROM live_ground_floor_map ORDER BY zone_name;
SELECT * FROM admin_zones ORDER BY zone_name;

-- ADMIN EXAMPLES (run only when needed)
-- Close a zone:   UPDATE zones SET is_closed = TRUE,  updated_at = CURRENT_TIMESTAMP WHERE zone_id = 'MR_1';
-- Unlock a zone:  UPDATE zones SET is_closed = FALSE, updated_at = CURRENT_TIMESTAMP WHERE zone_id = 'MR_1';
-- Edit ecosystem: UPDATE ecosystem_metrics SET active_companies = 2010, active_licenses = 1210,
--                 top_sector = 'Manufacturing', recorded_at = CURRENT_TIMESTAMP WHERE snapshot_date = CURRENT_DATE;
