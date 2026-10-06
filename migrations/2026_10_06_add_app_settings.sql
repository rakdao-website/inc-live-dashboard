-- Settings changed from the admin panel (voice agent, face recognition, kiosk scan,
-- Spacebring sync, opening hours). A missing row means "use the .env default". Additive only.
CREATE TABLE IF NOT EXISTS app_settings (
  setting_key VARCHAR(80) PRIMARY KEY,
  setting_value TEXT NOT NULL,
  updated_by_user_id BIGINT,
  updated_by_username VARCHAR(80),
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
