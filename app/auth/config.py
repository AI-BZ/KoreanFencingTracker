"""
Auth Config - OAuth 및 인증 설정
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache


class AuthSettings(BaseSettings):
    """인증 관련 설정"""

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
    KAKAO_REDIRECT_URI: str = os.getenv("KAKAO_REDIRECT_URI", "http://localhost:71/auth/callback/kakao")

    # Google OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:71/auth/callback/google")

    # X (Twitter) OAuth
    X_CLIENT_ID: str = os.getenv("X_CLIENT_ID", "")
    X_CLIENT_SECRET: str = os.getenv("X_CLIENT_SECRET", "")
    X_REDIRECT_URI: str = os.getenv("X_REDIRECT_URI", "http://localhost:71/auth/callback/x")

    # Gemini API
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = "gemini-2.0-flash-exp"  # 최신 모델

    # IP Geolocation (선택사항)
    IP_GEOLOCATION_API_KEY: str = os.getenv("IP_GEOLOCATION_API_KEY", "")

    # 인증 설정
    VERIFICATION_AUTO_APPROVE_THRESHOLD: float = 0.85  # 자동 승인 신뢰도
    VERIFICATION_AUTO_REJECT_THRESHOLD: float = 0.60   # 자동 거부 신뢰도

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_auth_settings() -> AuthSettings:
    return AuthSettings()


# OAuth Provider 설정
OAUTH_PROVIDERS = {
    "kakao": {
        "enabled": True,
        "region_restriction": "KR",  # 한국만
        "authorize_url": "https://kauth.kakao.com/oauth/authorize",
        "token_url": "https://kauth.kakao.com/oauth/token",
        "userinfo_url": "https://kapi.kakao.com/v2/user/me",
        "scopes": ["profile_nickname"],  # account_email은 카카오 앱에서 동의항목 설정 필요
    },
    "google": {
        "enabled": True,
        "region_restriction": None,  # 전세계
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "scopes": ["openid", "email", "profile"],
    },
    "x": {
        "enabled": True,
        "region_restriction": None,
        "promotional_only": True,  # 홍보용만
        "authorize_url": "https://twitter.com/i/oauth2/authorize",
        "token_url": "https://api.twitter.com/2/oauth2/token",
        "userinfo_url": "https://api.twitter.com/2/users/me",
        "scopes": ["tweet.read", "users.read"],
    },
}


def get_available_providers(country_code: Optional[str] = None) -> list[str]:
    """
    국가 코드에 따라 사용 가능한 OAuth 제공자 목록 반환

    Args:
        country_code: ISO 2글자 국가 코드 (예: KR, US, JP)

    Returns:
        사용 가능한 provider 목록
    """
    providers = []

    for provider, config in OAUTH_PROVIDERS.items():
        if not config.get("enabled", False):
            continue

        # 홍보용만인 경우 제외 (로그인용 목록에서)
        if config.get("promotional_only", False):
            continue

        # 지역 제한 확인
        region = config.get("region_restriction")
        if region and country_code and country_code != region:
            continue

        providers.append(provider)

    # 한국은 카카오 우선
    if country_code == "KR" and "kakao" in providers:
        providers.remove("kakao")
        providers.insert(0, "kakao")

    return providers


def get_promotional_providers() -> list[str]:
    """
    홍보용 연동 가능한 OAuth 제공자 목록 반환

    Returns:
        홍보용 provider 목록 (예: x)
    """
    return [
        provider for provider, config in OAUTH_PROVIDERS.items()
        if config.get("enabled", False) and config.get("promotional_only", False)
    ]


# Gemini API 프롬프트
VERIFICATION_PROMPTS = {
    "mask_photo": """
이 이미지는 펜싱 마스크와 함께 찍은 본인 인증 사진입니다.
다음 항목을 확인하고 JSON으로 응답하세요:

1. 펜싱 마스크가 보이는가? (is_mask_visible: boolean)
2. 이름이 적힌 종이가 보이는가? (is_name_paper_visible: boolean)
3. 날짜가 적힌 종이가 보이는가? (is_date_paper_visible: boolean)
4. 종이에 적힌 이름 (extracted_name: string or null)
5. 종이에 적힌 날짜 (extracted_date: string or null, YYYY-MM-DD 형식)
6. 마스크에 이름이 있다면 (mask_name: string or null)
7. 전체 신뢰도 (confidence: 0.0 ~ 1.0)
8. 인증 가능 여부 (is_valid: boolean)
9. 거부 사유 (rejection_reason: string or null)

중요: 반드시 유효한 JSON 형식으로만 응답하세요. 마크다운이나 설명 없이 JSON만 반환하세요.
""",

    "uniform_photo": """
이 이미지는 펜싱 도복과 함께 찍은 본인 인증 사진입니다.
다음 항목을 확인하고 JSON으로 응답하세요:

1. 펜싱 도복이 보이는가? (is_uniform_visible: boolean)
2. 도복에 이름이 있는가? (uniform_name: string or null)
3. 이름이 적힌 종이가 보이는가? (is_name_paper_visible: boolean)
4. 날짜가 적힌 종이가 보이는가? (is_date_paper_visible: boolean)
5. 종이에 적힌 이름 (extracted_name: string or null)
6. 종이에 적힌 날짜 (extracted_date: string or null, YYYY-MM-DD 형식)
7. 전체 신뢰도 (confidence: 0.0 ~ 1.0)
8. 인증 가능 여부 (is_valid: boolean)
9. 거부 사유 (rejection_reason: string or null)

중요: 반드시 유효한 JSON 형식으로만 응답하세요. 마크다운이나 설명 없이 JSON만 반환하세요.
""",

    "association_card": """
이 이미지는 대한펜싱협회 등록증입니다.
다음 항목을 확인하고 JSON으로 응답하세요:

1. 대한펜싱협회 로고/명칭이 보이는가? (is_association_logo: boolean)
2. 회원증/등록증 형태인가? (is_membership_card: boolean)
3. 이름 (extracted_name: string or null)
4. 등록번호 (registration_number: string or null)
5. 소속 (organization: string or null)
6. 유효기간 (valid_until: string or null)
7. 전체 신뢰도 (confidence: 0.0 ~ 1.0)
8. 인증 가능 여부 (is_valid: boolean)
9. 거부 사유 (rejection_reason: string or null)

중요: 반드시 유효한 JSON 형식으로만 응답하세요. 마크다운이나 설명 없이 JSON만 반환하세요.
"""
}
