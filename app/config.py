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
    # Server-side text-to-speech. Off by default; the frontend falls back to
    # the browser's built-in speech synthesis automatically when this is
    # disabled or the call fails for any reason.

    openai_api_key: str = ""
    openai_realtime_model: str = "gpt-realtime-2.1"
    openai_realtime_voice: str = "marin"



    # Reverse face web search for unknown visitors. Off by default; when a
    # detected face doesn't match anyone in our gallery and this is enabled,
    # we query the provider for the top public-web candidates for a human to
    # review. Disabled or unconfigured just returns "no web matches".
    face_web_search_enabled: bool = False
    face_web_search_provider: str = "facecheck"
    facecheck_api_token: str = ""
    # Testing mode returns inaccurate results but does not consume credits.
    face_web_search_testing_mode: bool = False
    face_web_search_max_images: int = 3  # confirmed: multiple photos of the same person don't cost extra FaceCheck.ID credits
    
    # Spacebring REST API (Basic auth). Sandbox credentials first, prod later.
    spacebring_base_url: str = "https://api.spacebring.com"
    spacebring_client_id: str = ""
    spacebring_client_secret: str = ""
    spacebring_network_id: str = ""
    spacebring_location_id: str = ""
    # Kiosk times are local wall-clock times; Spacebring wants UTC instants.
    spacebring_timezone: str = "Asia/Dubai"
    # "none" or "all". Unowned (anonymous) bookings have nobody to email.
    spacebring_send_updates: str = "none"
    # Off until the team decides how a visitor maps to a Spacebring customer.
    # When on, visitors with a spacebring_customer_id own their booking and
    # pay with their Spacebring credits.
    spacebring_use_customer_owner: bool = False
    # How often the API pulls Spacebring bookings into Postgres. 0 turns the
    # background sync off (the script scripts/sync_spacebring_bookings.py still works).
    spacebring_sync_interval_seconds: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )



@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


