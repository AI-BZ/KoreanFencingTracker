"""
공유 인증 설정

JWT + OAuth 설정. Gemini/Verification은 data 서비스에 잔류.
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class SharedAuthSettings(BaseSettings):
    """공유 인증 설정 (JWT + OAuth)"""

    # Supabase
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

    # JWT
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24시간

    # Kakao OAuth
    KAKAO_CLIENT_ID: str = os.getenv("KAKAO_CLIENT_ID", "")
    KAKAO_CLIENT_SECRET: str = os.getenv("KAKAO_CLIENT_SECRET", "")
    KAKAO_REDIRECT_URI: str = os.getenv("KAKAO_REDIRECT_URI", "http://localhost:9070/auth/callback/kakao")

    # Google OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:9070/auth/callback/google")

    # X (Twitter) OAuth
    X_CLIENT_ID: str = os.getenv("X_CLIENT_ID", "")
    X_CLIENT_SECRET: str = os.getenv("X_CLIENT_SECRET", "")
    X_REDIRECT_URI: str = os.getenv("X_REDIRECT_URI", "http://localhost:9070/auth/callback/x")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_shared_auth_settings() -> SharedAuthSettings:
    return SharedAuthSettings()
