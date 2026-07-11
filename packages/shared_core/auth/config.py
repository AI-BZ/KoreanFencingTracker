"""
공유 인증 설정

JWT + OAuth 설정. Gemini/Verification은 data 서비스에 잔류.
"""
import os
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


# 안전하지 않은 예전 기본값 — 실수로라도 사용되면 즉시 거부
_INSECURE_JWT_DEFAULTS = {"your-secret-key-change-in-production"}


class SharedAuthSettings(BaseSettings):
    """공유 인증 설정 (JWT + OAuth)"""

    # Supabase
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

    # JWT — 안전한 기본값 없음. 환경변수(JWT_SECRET_KEY)가 반드시 주입돼야 하며
    # 누락/공백/예전 기본값이면 기동 시점에 예외로 실패한다(fail-fast).
    JWT_SECRET_KEY: str
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

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def _require_secure_jwt_secret(cls, v: str) -> str:
        if v is None or not v.strip():
            raise ValueError(
                "JWT_SECRET_KEY environment variable must be set (empty/missing value is not allowed)"
            )
        if v in _INSECURE_JWT_DEFAULTS:
            raise ValueError(
                "JWT_SECRET_KEY must not use the insecure placeholder value; set a real secret"
            )
        return v

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_shared_auth_settings() -> SharedAuthSettings:
    return SharedAuthSettings()
