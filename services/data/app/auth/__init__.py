"""
Auth Module - 회원 인증 시스템

핵심 로직은 shared_core에서 import, 서비스 특화 기능은 이 모듈에 잔류.
"""
from .router import router as auth_router

# shared_core에서 re-export (기존 호환성)
from shared_core.auth.jwt import create_access_token, get_current_member
from shared_core.types.member import (
    MemberType,
    VerificationType,
    VerificationStatus,
)
from shared_core.auth.models import (
    MemberCreate,
    MemberResponse,
    VerificationUpload,
    VerificationResponse,
    PrivacySettings,
    GuardianLink,
)
from shared_core.privacy.masking import mask_korean_name
from shared_core.privacy.anonymize import anonymize_team

# data 서비스 전용
from .verification import GeminiVerifier

__all__ = [
    "auth_router",
    "create_access_token",
    "get_current_member",
    "MemberType",
    "VerificationType",
    "VerificationStatus",
    "MemberCreate",
    "MemberResponse",
    "VerificationUpload",
    "VerificationResponse",
    "PrivacySettings",
    "GuardianLink",
    "mask_korean_name",
    "anonymize_team",
    "GeminiVerifier",
]
