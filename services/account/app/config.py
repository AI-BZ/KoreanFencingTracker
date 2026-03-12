"""
Account Config - account 서비스 인증/인증 설정

SharedAuthSettings를 상속하여 Gemini/Verification 전용 설정 추가.
"""
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from shared_core.auth.config import SharedAuthSettings


class AccountSettings(SharedAuthSettings):
    """
    account 서비스 설정

    SharedAuthSettings를 상속하여 Gemini/Verification 전용 설정 추가.
    """

    # Gemini API
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = "gemini-2.0-flash-exp"

    # IP Geolocation (선택사항)
    IP_GEOLOCATION_API_KEY: str = os.getenv("IP_GEOLOCATION_API_KEY", "")

    # Stripe
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY: str = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    # PortOne (한국 결제)
    PORTONE_API_KEY: str = os.getenv("PORTONE_API_KEY", "")
    PORTONE_API_SECRET: str = os.getenv("PORTONE_API_SECRET", "")
    PORTONE_WEBHOOK_SECRET: str = os.getenv("PORTONE_WEBHOOK_SECRET", "")

    # 인증 설정 (Gemini 자동 승인/거부 임계값)
    VERIFICATION_AUTO_APPROVE_THRESHOLD: float = 0.85
    VERIFICATION_AUTO_REJECT_THRESHOLD: float = 0.60

    # Email (Resend)
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = 24

    # Account deletion
    ACCOUNT_DELETION_GRACE_DAYS: int = 30

    # NTS (국세청) API for BRN verification
    NTS_API_KEY: str = os.getenv("NTS_API_KEY", "")

    # Player Claim thresholds
    CLAIM_AUTO_APPROVE_THRESHOLD: float = 0.85
    CLAIM_MANUAL_REVIEW_THRESHOLD: float = 0.50

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache()
def get_account_settings() -> AccountSettings:
    return AccountSettings()


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
""",

    "business_registration": """
이 이미지는 한국 사업자등록증입니다.
다음 항목을 정확하게 추출하고 JSON으로 응답하세요:

1. 사업자등록번호 (business_registration_number: string, "XXX-XX-XXXXX" 형식)
2. 상호 또는 법인명 (business_name: string or null)
3. 대표자 성명 (representative_name: string or null)
4. 개업년월일 (opening_date: string or null, "YYYYMMDD" 형식)
5. 사업장 소재지 (address: string or null)
6. 업태 (business_type: string or null)
7. 종목 (business_item: string or null)
8. 전체 신뢰도 (confidence: 0.0 ~ 1.0)
9. 인증 가능 여부 (is_valid: boolean)
10. 거부 사유 (rejection_reason: string or null)

형식: { "business_registration_number": "...", "business_name": "...", ... }
추출할 수 없는 항목은 null로 표시하세요.
중요: 반드시 유효한 JSON 형식으로만 응답하세요. 마크다운이나 설명 없이 JSON만 반환하세요.
"""
}
