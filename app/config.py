from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Innovation City Live Dashboard API"
    environment: str = "development"
    debug: bool = True

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/INC_live_dashboard"
    auto_create_tables: bool = False
    seed_sample_data: bool = False
    admin_username: str = "admin"
    admin_password: str = "admin123"
    admin_role: str = "super_user"

    # Room Q&A brain. "scripted" needs no key and is the default; set to
    # "gemini" or "grok" and supply the matching key via .env to enable it.
    # Falls back to the scripted matcher automatically if the call fails.
    room_question_provider: str = "scripted"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    # Server-side text-to-speech. Off by default; the frontend falls back to
    # the browser's built-in speech synthesis automatically when this is
    # disabled or the call fails for any reason.
    xai_api_key: str = ""
    xai_model: str = "grok-4"
    xai_tts_codec: str = "mp3"
    xai_tts_language: str = "en-US"

    conversation_provider: str = "xai"



    tts_enabled: bool = False
    tts_provider: str = "xai"  # "xai" | "gemini"
    openrouter_tts_model: str = ""
    openrouter_tts_voice: str = ""
    xai_tts_model: str = ""
    xai_tts_voice: str = ""

    openrouter_api_key: str  = ""
    openrouter_stt_model: str = "openai/whisper-1"
    openrouter_model: str = "google/gemini-2.5-flash"
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


