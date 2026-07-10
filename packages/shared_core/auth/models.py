"""
인증 관련 Pydantic 모델

회원 생성/수정/응답 모델, 토큰 모델 등
"""
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import ConfigDict, BaseModel, EmailStr, Field, field_validator

from shared_core.types.member import (
    MemberType,
    MemberVerificationStatus,
    VerificationType,
    VerificationStatus,
    OAuthProvider,
)
from shared_core.types.service import ServiceType, SubscriptionTier


# =============================================
# Request Models
# =============================================

class MemberCreate(BaseModel):
    """회원가입 요청"""
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: Optional[str] = None
    phone_country_code: str = "+82"
    birth_date: Optional[date] = None
    member_type: MemberType
    organization_id: Optional[int] = None
    marketing_consent: bool = False
    promotional_consent: bool = False
    email_verified: bool = False
    terms_agreed_at: Optional[datetime] = None
    privacy_agreed_at: Optional[datetime] = None
    consent_version: str = "1.0"

    @field_validator('birth_date')
    @classmethod
    def validate_birth_date(cls, v):
        if v and v > date.today():
            raise ValueError('생년월일은 오늘 이전이어야 합니다')
        return v


class MemberUpdate(BaseModel):
    """회원정보 수정 요청"""
    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    phone: Optional[str] = None
    organization_id: Optional[int] = None


class PrivacySettings(BaseModel):
    """개인정보 설정"""
    privacy_public: bool = Field(..., description="대중 공개 여부")
    marketing_consent: Optional[bool] = None
    promotional_consent: Optional[bool] = None


class GuardianLink(BaseModel):
    """보호자-미성년자 연결 요청"""
    minor_member_id: UUID
    relationship: str = Field(..., description="관계 (부, 모, 법정대리인 등)")


class VerificationUpload(BaseModel):
    """인증 이미지 업로드 메타데이터"""
    verification_type: VerificationType


# =============================================
# Response Models
# =============================================

class MemberResponse(BaseModel):
    """회원 정보 응답"""
    id: UUID
    full_name: str
    display_name: Optional[str] = None
    email: str
    phone: Optional[str] = None
    phone_country_code: str = "+82"
    birth_date: Optional[date] = None
    member_type: MemberType
    player_id: Optional[int] = None
    organization_id: Optional[int] = None
    verification_status: MemberVerificationStatus
    verified_at: Optional[datetime] = None
    email_verified: bool = False
    privacy_public: bool
    marketing_consent: bool
    promotional_consent: bool
    terms_agreed_at: Optional[datetime] = None
    privacy_agreed_at: Optional[datetime] = None
    consent_version: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class MemberPublicResponse(BaseModel):
    """회원 공개 정보 응답 (마스킹 적용)"""
    id: UUID
    display_name: str  # 마스킹된 이름 (H.G.D.)
    display_team: str  # 익명화된 소속 (서울(클럽))
    member_type: MemberType
    verification_status: MemberVerificationStatus
    model_config = ConfigDict(from_attributes=True)


class VerificationResponse(BaseModel):
    """인증 결과 응답"""
    id: UUID
    verification_type: VerificationType
    status: VerificationStatus
    gemini_confidence: Optional[float] = None
    extracted_name: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class OAuthConnectionResponse(BaseModel):
    """OAuth 연결 정보"""
    id: UUID
    provider: OAuthProvider
    provider_email: Optional[str] = None
    provider_name: Optional[str] = None
    is_primary: bool
    for_promotional: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# =============================================
# Gemini API Response Models (data 서비스에서도 사용)
# =============================================

class GeminiVerificationResult(BaseModel):
    """Gemini API 인증 결과"""
    is_valid: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    extracted_name: Optional[str] = None
    extracted_date: Optional[str] = None
    extracted_organization: Optional[str] = None
    rejection_reason: Optional[str] = None

    # 마스크/도복 사진용
    is_mask_visible: Optional[bool] = None
    is_uniform_visible: Optional[bool] = None
    is_name_paper_visible: Optional[bool] = None
    is_date_paper_visible: Optional[bool] = None
    mask_name: Optional[str] = None
    uniform_name: Optional[str] = None

    # 협회 등록증용
    is_association_logo: Optional[bool] = None
    is_membership_card: Optional[bool] = None
    registration_number: Optional[str] = None
    valid_until: Optional[str] = None


# =============================================
# Token Models
# =============================================

class TokenData(BaseModel):
    """JWT 토큰 데이터"""
    member_id: UUID
    email: str
    member_type: MemberType
    verification_status: MemberVerificationStatus
    exp: datetime


class TokenResponse(BaseModel):
    """토큰 응답"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    member: MemberResponse


# =============================================
# Member Services Models
# =============================================

class MemberServiceCreate(BaseModel):
    """서비스 구독 생성"""
    service_id: ServiceType
    tier: SubscriptionTier = SubscriptionTier.FREE


class MemberServiceResponse(BaseModel):
    """서비스 구독 응답"""
    id: UUID
    member_id: UUID
    service_id: str
    tier: str
    status: str
    settings: Optional[dict] = None
    started_at: datetime
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
