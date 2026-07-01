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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
