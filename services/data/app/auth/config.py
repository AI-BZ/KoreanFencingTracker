"""
Auth Config - data 서비스 인증 설정

공유 설정은 shared_core에서 re-export.
Gemini/Verification 설정은 data 서비스 전용으로 잔류.
"""
import os
from pydantic_settings import SettingsConfigDict
from functools import lru_cache

# === 공유 설정 re-export ===
from shared_core.auth.config import SharedAuthSettings, get_shared_auth_settings
from shared_core.auth.oauth.providers import (
    OAUTH_PROVIDERS,
    get_available_providers,
    get_promotional_providers,
)


class AuthSettings(SharedAuthSettings):
    """
    data 서비스 인증 설정

    SharedAuthSettings를 상속하여 Gemini/Verification 전용 설정 추가.
    """

    # Gemini API (data 서비스 전용)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = "gemini-2.0-flash-exp"

    # IP Geolocation (선택사항)
    IP_GEOLOCATION_API_KEY: str = os.getenv("IP_GEOLOCATION_API_KEY", "")

    # 인증 설정 (Gemini 자동 승인/거부 임계값)
    VERIFICATION_AUTO_APPROVE_THRESHOLD: float = 0.85
    VERIFICATION_AUTO_REJECT_THRESHOLD: float = 0.60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_auth_settings() -> AuthSettings:
    return AuthSettings()


# Gemini API 프롬프트 (data 서비스 전용)
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
