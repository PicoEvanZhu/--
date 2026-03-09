from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Stock Assistant API"
    app_env: str = "dev"
    debug: bool = True
    api_prefix: str = "/api/v1"
    database_url: str = "mysql+pymysql://stockapp:change-me@127.0.0.1:3306/gupiao?charset=utf8mb4"
    auth_secret: str = "change-this-secret-in-production"
    auth_token_expire_minutes: int = 1440
    password_reset_code_expire_minutes: int = 15
    bootstrap_admin_username: str = "tianyuyezi"
    bootstrap_admin_password: str = "88888888"
    bootstrap_admin_email: str = "tianyuyezi@stock-assistant.local"
    qa_enable_web_search: bool = True
    qa_web_search_timeout_seconds: float = 10.0
    qa_web_search_max_results: int = 5

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized.startswith("mysql+pymysql://"):
            raise ValueError("仅支持 mysql+pymysql:// 连接串")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
