-- Conversation logs, masked contact columns and the tamper-evident audit chain. Additive only.

-- 1. Masked copies of the visitor's email and phone (for the customer list).
ALTER TABLE visitors ADD COLUMN IF NOT EXISTS email_masked VARCHAR(160);
ALTER TABLE visitors ADD COLUMN IF NOT EXISTS phone_masked VARCHAR(60);
-- Backfill (the application keeps them current from now on): m*****@e*****.com and +971*****67.
UPDATE visitors SET email_masked = left(visitor_email, 1) || '*****@' ||
  left(split_part(visitor_email, '@', 2), 1) || '*****.' ||
  regexp_replace(split_part(visitor_email, '@', 2), '^.*\.', '')
WHERE visitor_email LIKE '%_@_%.__%' AND email_masked IS NULL;
UPDATE visitors SET phone_masked =
  CASE WHEN visitor_phone LIKE '+%' THEN '+' ELSE '' END ||
  left(regexp_replace(visitor_phone, '\D', '', 'g'), 3) || '*****' ||
  right(regexp_replace(visitor_phone, '\D', '', 'g'), 2)
WHERE length(regexp_replace(visitor_phone, '\D', '', 'g')) >= 6 AND phone_masked IS NULL;

-- 2. Conversation logs.
CREATE TABLE IF NOT EXISTS kiosk_sessions (
  session_id VARCHAR(36) PRIMARY KEY,
  visitor_id BIGINT REFERENCES visitors(visitor_id) ON DELETE SET NULL,
  visitor_label VARCHAR(150),
  visitor_type VARCHAR(20),
  channel VARCHAR(20) NOT NULL DEFAULT 'voice',
  outcome VARCHAR(40),
  message_count INTEGER NOT NULL DEFAULT 0,
  started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ended_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_kiosk_sessions_visitor ON kiosk_sessions(visitor_id);
CREATE INDEX IF NOT EXISTS idx_kiosk_sessions_started ON kiosk_sessions(started_at);

CREATE TABLE IF NOT EXISTS kiosk_session_messages (
  message_id BIGSERIAL PRIMARY KEY,
  session_id VARCHAR(36) NOT NULL REFERENCES kiosk_sessions(session_id) ON DELETE CASCADE,
  item_id VARCHAR(80),
  role VARCHAR(12) NOT NULL,
  content TEXT NOT NULL,
  occurred_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_session_item UNIQUE (session_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_kiosk_session_messages_session ON kiosk_session_messages(session_id);

-- 3. Audit log: hash chain, category, and append-only.
ALTER TABLE admin_audit_log ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64);
ALTER TABLE admin_audit_log ADD COLUMN IF NOT EXISTS row_hash VARCHAR(64);
ALTER TABLE admin_audit_log ADD COLUMN IF NOT EXISTS category VARCHAR(20);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_category ON admin_audit_log(category);

CREATE OR REPLACE FUNCTION admin_audit_log_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'admin_audit_log is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_admin_audit_log_append_only ON admin_audit_log;
CREATE TRIGGER trg_admin_audit_log_append_only
  BEFORE UPDATE OR DELETE ON admin_audit_log
  FOR EACH ROW EXECUTE FUNCTION admin_audit_log_append_only();
