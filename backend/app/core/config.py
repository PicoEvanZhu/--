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
    openai_base_url: str = "https://api.openai.com"
    openai_api_key: str = ""
    openai_model: str = "gpt5.4"
    main_force_accumulation_score_min: int = 65
    main_force_accumulation_vol_squeeze_max: float = 0.75
    main_force_accumulation_range_squeeze_max: float = 0.75
    main_force_markup_close_slope_min: float = 0.02
    main_force_markup_up_volume_ratio_min: float = 0.6
    main_force_distribution_close_slope_max: float = -0.02
    main_force_distribution_obv_slope_max: float = -0.0
    main_force_pullback_close_slope_max: float = 0.0
    main_force_pullback_obv_slope_min: float = 0.0
    main_force_signal_high_score_min: int = 70
    main_force_signal_medium_score_min: int = 62
    main_force_signal_high_vol_squeeze_max: float = 0.7
    main_force_signal_medium_vol_squeeze_max: float = 0.85
    main_force_signal_high_range_squeeze_max: float = 0.7
    main_force_signal_medium_range_squeeze_max: float = 0.85
    main_force_signal_high_obv_slope_min: float = 0.0
    main_force_signal_medium_obv_slope_min: float = 0.0
    main_force_sentiment_high: int = 70
    main_force_sentiment_low: int = 35
    main_force_sentiment_boost_step: int = 10
    main_force_sentiment_boost_weight: int = 1
    main_force_scan_limit: int = 200
    main_force_scan_top_n: int = 30
    main_force_scan_with_llm: bool = True
    main_force_scan_llm_top_n: int = 10
    main_force_scan_with_web: bool = True
    main_force_scan_sentiment_top_n: int = 30

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
