"""
데이터베이스 설정

Supabase 연결 설정 (scraper 모델 의존성 없음)
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class SharedDBConfig(BaseSettings):
    """공유 DB 설정 - scraper 의존성 제거된 독립 설정"""

    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_db_config() -> SharedDBConfig:
    return SharedDBConfig()
