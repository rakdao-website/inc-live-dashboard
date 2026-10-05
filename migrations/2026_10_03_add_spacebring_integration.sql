-- Spacebring integration: Spacebring is the system of record for room
-- bookings; Postgres keeps a mirror. Additive only.

ALTER TABLE zones
  ADD COLUMN IF NOT EXISTS spacebring_resource_id VARCHAR(40);
CREATE UNIQUE INDEX IF NOT EXISTS uq_zones_spacebring_resource_id
  ON zones(spacebring_resource_id) WHERE spacebring_resource_id IS NOT NULL;

ALTER TABLE bookings
  ADD COLUMN IF NOT EXISTS spacebring_booking_id VARCHAR(40);
CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_spacebring_booking_id
  ON bookings(spacebring_booking_id) WHERE spacebring_booking_id IS NOT NULL;

-- Nullable until the team decides how a visitor maps to a Spacebring customer.
ALTER TABLE visitors
  ADD COLUMN IF NOT EXISTS spacebring_customer_id VARCHAR(40);

-- Three person types: client (customer), employee, visitor (anonymous).
ALTER TABLE visitors DROP CONSTRAINT IF EXISTS visitors_visitor_type_check;
ALTER TABLE visitors ADD CONSTRAINT visitors_visitor_type_check
  CHECK (visitor_type IN ('client', 'employee', 'visitor'));

-- Every Spacebring room has a zone (resource ids are filled by
-- scripts/sync_spacebring_zones.py, which matches rooms by title).
INSERT INTO zones (zone_id, zone_name, zone_type, is_bookable, is_closed) VALUES
  ('TTS_2', 'TikTok Beauty Room',   'studio', TRUE, FALSE),
  ('TTS_3', 'TikTok Music Room',    'studio', TRUE, FALSE),
  ('TTS_4', 'TikTok Battle Room 1', 'studio', TRUE, FALSE),
  ('TTS_5', 'TikTok Battle Room 2', 'studio', TRUE, FALSE)
ON CONFLICT (zone_id) DO NOTHING;
