from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Stock Assistant API"
    app_env: str = "dev"
    debug: bool = True
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./stock_assistant.db"
    auth_secret: str = "change-this-secret-in-production"
    auth_token_expire_minutes: int = 1440
    password_reset_code_expire_minutes: int = 15
    bootstrap_admin_username: str = "tianyuyezi"
    bootstrap_admin_password: str = "88888888"
    bootstrap_admin_email: str = "tianyuyezi@stock-assistant.local"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
