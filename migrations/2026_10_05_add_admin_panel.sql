-- Admin panel: users, sessions, audit log and the visitor approval queue.
-- Additive only. Create the first super_user with scripts/create_admin_user.py.

CREATE TABLE IF NOT EXISTS admin_users (
  user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username VARCHAR(80) NOT NULL UNIQUE,
  display_name VARCHAR(120) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(20) NOT NULL CHECK (role IN ('super_user', 'reception', 'reviewer', 'read_only')),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  last_login_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS admin_sessions (
  session_pk BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  session_hash VARCHAR(64) NOT NULL UNIQUE,
  user_id BIGINT NOT NULL REFERENCES admin_users(user_id),
  created_at TIMESTAMP NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  revoked_at TIMESTAMP,
  ip_address VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_user ON admin_sessions(user_id);

CREATE TABLE IF NOT EXISTS admin_audit_log (
  audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id BIGINT,
  username VARCHAR(80),
  role VARCHAR(20),
  action VARCHAR(80) NOT NULL,
  entity_type VARCHAR(40),
  entity_id VARCHAR(80),
  detail TEXT,
  ip_address VARCHAR(64),
  occurred_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_occurred ON admin_audit_log(occurred_at);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_action ON admin_audit_log(action);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_entity ON admin_audit_log(entity_type);
CREATE INDEX IF NOT EXISTS idx_admin_audit_log_user ON admin_audit_log(user_id);

-- Existing visitors stay approved; only new kiosk entries start as pending.
ALTER TABLE visitors
  ADD COLUMN IF NOT EXISTS approval_status VARCHAR(20) NOT NULL DEFAULT 'approved';
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'visitors_approval_status_check') THEN
    ALTER TABLE visitors ADD CONSTRAINT visitors_approval_status_check
      CHECK (approval_status IN ('pending', 'approved', 'rejected'));
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_visitors_approval_status ON visitors(approval_status);

CREATE TABLE IF NOT EXISTS visitor_approvals (
  approval_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  visitor_id BIGINT NOT NULL REFERENCES visitors(visitor_id),
  status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
  source VARCHAR(20) NOT NULL CHECK (source IN ('new_entry', 'web_suggestion')),
  capture_id BIGINT,
  chosen_web_match_id BIGINT,
  best_gallery_score DOUBLE PRECISION,
  entered_details TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  decided_by_user_id BIGINT,
  decided_by_username VARCHAR(80),
  decided_at TIMESTAMP,
  decision_reason VARCHAR(500)
);
CREATE INDEX IF NOT EXISTS idx_visitor_approvals_status ON visitor_approvals(status);
CREATE INDEX IF NOT EXISTS idx_visitor_approvals_visitor ON visitor_approvals(visitor_id);
