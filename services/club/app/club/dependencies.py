"""
Club Management Dependencies - shared_core 래퍼

shared_core 통합 인증 모듈을 재수출합니다.
JWT + Supabase Auth 이중 인증 자동 지원.

기존 import 호환성 유지:
  from .dependencies import ClubMemberContext, get_current_club_member, ...
"""
from typing import Optional

from fastapi import HTTPException, Request

from shared_core.auth.dependencies import (
    ServiceMemberContext as ClubMemberContext,
    get_current_club_member,
    require_coach,
    require_admin,
    require_staff,
    require_roles,
)
from shared_core.types.member import ClubRole


async def try_get_current_club_member(request: Request) -> Optional[ClubMemberContext]:
    """
    인증 실패 시 None 반환 (비인증 접근 허용 페이지용)

    get_current_club_member()와 동일하지만 HTTPException 대신 None 반환.
    랜딩 페이지, 역할별 라우팅 등에서 사용.
    """
    try:
        return await get_current_club_member(request)
    except HTTPException:
        return None


async def get_client_ip(request: Request) -> str:
    """클라이언트 IP 추출"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    if request.client:
        return request.client.host

    return "unknown"


__all__ = [
    "ClubMemberContext",
    "ClubRole",
    "get_current_club_member",
    "try_get_current_club_member",
    "require_coach",
    "require_admin",
    "require_staff",
    "require_roles",
    "get_client_ip",
]
