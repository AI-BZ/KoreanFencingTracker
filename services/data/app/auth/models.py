"""
Auth Models - Shim (호환성 유지)

실제 모델은 shared_core.auth.models 및 shared_core.types.member에 정의.
기존 import 경로를 유지하기 위한 re-export 파일.
"""

# === Types (Enums) ===
from shared_core.types.member import (
    MemberType,
    VerificationType,
    VerificationStatus,
    MemberVerificationStatus,
    OAuthProvider,
)

# === Request/Response Models ===
from shared_core.auth.models import (
    MemberCreate,
    MemberUpdate,
    PrivacySettings,
    GuardianLink,
    VerificationUpload,
    MemberResponse,
    MemberPublicResponse,
    VerificationResponse,
    OAuthConnectionResponse,
    GeminiVerificationResult,
    TokenData,
    TokenResponse,
    MemberServiceCreate,
    MemberServiceResponse,
)

__all__ = [
    # Enums
    "MemberType",
    "VerificationType",
    "VerificationStatus",
    "MemberVerificationStatus",
    "OAuthProvider",
    # Request Models
    "MemberCreate",
    "MemberUpdate",
    "PrivacySettings",
    "GuardianLink",
    "VerificationUpload",
    # Response Models
    "MemberResponse",
    "MemberPublicResponse",
    "VerificationResponse",
    "OAuthConnectionResponse",
    "GeminiVerificationResult",
    # Token Models
    "TokenData",
    "TokenResponse",
    # Member Services
    "MemberServiceCreate",
    "MemberServiceResponse",
]
