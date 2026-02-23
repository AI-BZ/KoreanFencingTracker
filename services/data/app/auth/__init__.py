"""
Auth Module - 기존 호환성 shim

인증 엔드포인트는 account 서비스(account.fencingmind.ai:70)로 이동되었습니다.
이 모듈은 기존 코드의 import 호환성을 위해 shared_core를 re-export합니다.

신규 코드에서는 shared_core에서 직접 import하세요:
    from shared_core.auth.jwt import create_access_token, get_current_member
    from shared_core.types.member import MemberType
"""

# auth_router export (redirect shim)
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
]
