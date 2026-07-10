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

    # Email verification code (login via email)
    EMAIL_CODE_EXPIRE_MINUTES: int = 10
    EMAIL_CODE_MAX_ATTEMPTS: int = 5

    # Account deletion
    ACCOUNT_DELETION_GRACE_DAYS: int = 30

    # NTS (국세청) API for BRN verification
    NTS_API_KEY: str = os.getenv("NTS_API_KEY", "")

    # Player Claim thresholds
    CLAIM_AUTO_APPROVE_THRESHOLD: float = 0.85
    CLAIM_MANUAL_REVIEW_THRESHOLD: float = 0.50

    # Parent Claim (학부모 인증은 자동 승인 없음, AI는 판단 보조만)
    PARENT_CLAIM_HIGH_CONFIDENCE: float = 0.80  # AI 리포트에서 "recommend approve" 기준
    PARENT_CLAIM_LOW_CONFIDENCE: float = 0.40   # AI 리포트에서 "recommend reject" 기준

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
""",

    "parent_claim": """
학부모-선수 관계 인증 요청을 분석하세요. 개인정보 서류 없이 데이터 교차검증만으로 판단합니다.

## 입력 데이터
- 부모 정보: {parent_info}
- 자녀(선수) 후보: {child_candidates}
- 사전 분석 신호: {signals}

## 평가 기준
1. 성씨 일치: 부모 성과 선수 성이 같은지 (한국 가족 동일 성씨 문화)
2. 나이 차이: 부모-자녀 간 나이 차이가 합리적인지 (20~50세 정상, 25~40세 최적)
3. 소속팀 일치: 부모가 속한 조직과 선수의 소속팀이 일치하는지
4. 선수 존재: players 테이블에서 이름+생년으로 매칭되는 선수가 있는지
5. 중복 여부: 같은 선수에 대한 기존 승인된 학부모 claim이 있는지

## 출력 형식 (JSON)
{
    "confidence": 0.0~1.0,
    "recommendation": "approve" | "reject" | "manual_review",
    "reasoning": "한국어 요약 3줄 이내",
    "flags": [{"type": "warning|info|danger", "message": "설명"}]
}

## 제약사항
- 개인 서류(가족관계증명서, 주민등록등본 등) 요청을 절대 권장하지 마세요.
- 미성년자 안전 문제로 자동 승인은 불가능하며, 관리자 최종 판단이 필요합니다.
- confidence가 높더라도 recommendation은 "manual_review" 이상으로만 설정하세요.

중요: 반드시 유효한 JSON 형식으로만 응답하세요.
"""
}
