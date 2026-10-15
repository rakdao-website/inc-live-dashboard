-- Spacebring events mirrored into the events table (shown on the kiosk). Additive only.
ALTER TABLE events ADD COLUMN IF NOT EXISTS spacebring_event_id VARCHAR(40);
CREATE UNIQUE INDEX IF NOT EXISTS uq_events_spacebring_event_id ON events(spacebring_event_id) WHERE spacebring_event_id IS NOT NULL;
