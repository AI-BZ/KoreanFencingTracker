"""
Club Management Dependencies - Shim (호환성 유지)

실제 구현은 shared_core.auth.dependencies에 위치.
기존 import 경로를 유지하기 위한 re-export 파일.
"""

# shared_core에서 통합 Dependencies re-export
from shared_core.auth.dependencies import (
    ServiceMemberContext,
    get_client_ip,
    get_current_club_member,
    require_coach,
    require_admin,
    require_staff,
    require_roles,
    TEST_MODE_ENV,
    TEST_CLUB_CONFIG,
)

# 기존 호환성: ClubMemberContext = ServiceMemberContext
ClubMemberContext = ServiceMemberContext

__all__ = [
    "ClubMemberContext",
    "ServiceMemberContext",
    "get_client_ip",
    "get_current_club_member",
    "require_coach",
    "require_admin",
    "require_staff",
    "require_roles",
    "TEST_MODE_ENV",
    "TEST_CLUB_CONFIG",
]
