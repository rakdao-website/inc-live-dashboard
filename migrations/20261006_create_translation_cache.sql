-- Automatic Arabic translations of changing kiosk text (event names,
-- backend messages), saved so each text is only sent to the AI once.
-- Only needed when AUTO_CREATE_TABLES=false; otherwise the API creates this
-- table from the TranslationCache model on startup.
CREATE TABLE IF NOT EXISTS translation_cache (
    translation_id   BIGSERIAL PRIMARY KEY,
    source_hash      VARCHAR(64) NOT NULL,
    source_text      TEXT        NOT NULL,
    target_lang      VARCHAR(10) NOT NULL,
    translated_text  TEXT        NOT NULL,
    created_at       TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_hash, target_lang)
);

CREATE INDEX IF NOT EXISTS ix_translation_cache_source_hash ON translation_cache (source_hash);
