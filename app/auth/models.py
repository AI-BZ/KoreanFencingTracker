"""
Auth Models - Pydantic 모델 정의
"""
from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class MemberType(str, Enum):
    """회원 유형"""
    PLAYER = "player"                # 선수회원
    PLAYER_PARENT = "player_parent"  # 선수 부모회원
    CLUB_COACH = "club_coach"        # 클럽 코치
    SCHOOL_COACH = "school_coach"    # 학교 코치
    GENERAL = "general"              # 일반 회원


class VerificationType(str, Enum):
    """인증 유형"""
    ASSOCIATION_CARD = "association_card"  # 협회 등록증
    MASK_PHOTO = "mask_photo"              # 마스크 + 이름 + 날짜 종이
    UNIFORM_PHOTO = "uniform_photo"        # 도복 + 이름 + 날짜 종이


class VerificationStatus(str, Enum):
    """인증 상태"""
    PENDING = "pending"        # 처리 대기
    PROCESSING = "processing"  # 처리 중
    APPROVED = "approved"      # 승인
    REJECTED = "rejected"      # 거부
    ERROR = "error"            # 오류


class MemberVerificationStatus(str, Enum):
    """회원 인증 상태"""
    PENDING = "pending"      # 인증 대기
    SUBMITTED = "submitted"  # 인증 제출됨
    VERIFIED = "verified"    # 인증 완료
    REJECTED = "rejected"    # 인증 거부
    EXPIRED = "expired"      # 인증 만료


class OAuthProvider(str, Enum):
    """OAuth 제공자"""
    KAKAO = "kakao"
    GOOGLE = "google"
    X = "x"


# =============================================
# Request Models
# =============================================

class MemberCreate(BaseModel):
    """회원가입 요청"""
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: Optional[str] = None
    birth_date: Optional[date] = None
    member_type: MemberType
    organization_id: Optional[int] = None
    marketing_consent: bool = False
    promotional_consent: bool = False

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
    display_name: Optional[str]
    email: str
    phone: Optional[str]
    birth_date: Optional[date]
    member_type: MemberType
    player_id: Optional[int]
    organization_id: Optional[int]
    verification_status: MemberVerificationStatus
    verified_at: Optional[datetime]
    privacy_public: bool
    marketing_consent: bool
    promotional_consent: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MemberPublicResponse(BaseModel):
    """회원 공개 정보 응답 (마스킹 적용)"""
    id: UUID
    display_name: str  # 마스킹된 이름 (H.G.D.)
    display_team: str  # 익명화된 소속 (서울(클럽))
    member_type: MemberType
    verification_status: MemberVerificationStatus

    class Config:
        from_attributes = True


class VerificationResponse(BaseModel):
    """인증 결과 응답"""
    id: UUID
    verification_type: VerificationType
    status: VerificationStatus
    gemini_confidence: Optional[float]
    extracted_name: Optional[str]
    rejection_reason: Optional[str]
    created_at: datetime
    processed_at: Optional[datetime]

    class Config:
        from_attributes = True


class OAuthConnectionResponse(BaseModel):
    """OAuth 연결 정보"""
    id: UUID
    provider: OAuthProvider
    provider_email: Optional[str]
    provider_name: Optional[str]
    is_primary: bool
    for_promotional: bool
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================
# Gemini API Response Models
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
