"""
Club Management Dependencies

인증 및 권한 체크 의존성
- 자체 JWT (카카오/구글 OAuth 로그인) + Supabase Auth 이중 지원
"""

import os
from typing import Optional, List
from fastapi import Depends, HTTPException, status, Request, Query
from jose import jwt, JWTError
from loguru import logger
from .models import ClubRole

# 테스트 모드 설정
# 환경변수 CLUB_TEST_MODE=1 또는 쿼리 파라미터 ?test=1 로 활성화
TEST_MODE_ENV = os.getenv("CLUB_TEST_MODE", "0") == "1"

# 테스트용 기본 클럽 설정 (최병철펜싱클럽)
TEST_CLUB_CONFIG = {
    "organization_id": 401,  # 최병철펜싱클럽
    "organization_name": "최병철펜싱클럽",
    "member_id": "00000000-0000-0000-0000-000000000001",  # 최병철 감독 UUID
    "full_name": "최병철",
    "club_role": ClubRole.owner,  # owner로 테스트 (모든 기능 접근 가능)
    "player_id": None
}


async def get_client_ip(request: Request) -> str:
    """클라이언트 IP 추출"""
    # X-Forwarded-For 헤더 확인 (프록시/로드밸런서 뒤에서)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # 첫 번째 IP가 실제 클라이언트
        return forwarded.split(",")[0].strip()

    # X-Real-IP 헤더 확인
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # 직접 연결된 클라이언트
    if request.client:
        return request.client.host

    return "unknown"


class ClubMemberContext:
    """클럽 회원 컨텍스트"""

    def __init__(
        self,
        member_id: str,
        organization_id: int,
        club_role: ClubRole,
        full_name: str,
        player_id: Optional[int] = None,
        guardian_member_id: Optional[str] = None
    ):
        self.member_id = member_id
        self.organization_id = organization_id
        self.club_role = club_role
        self.full_name = full_name
        self.player_id = player_id
        self.guardian_member_id = guardian_member_id

    def is_coach(self) -> bool:
        """코치 이상 권한인지"""
        return self.club_role in [
            ClubRole.owner,
            ClubRole.head_coach,
            ClubRole.coach
        ]

    def is_admin(self) -> bool:
        """관리자 권한인지 (owner/head_coach)"""
        return self.club_role in [
            ClubRole.owner,
            ClubRole.head_coach
        ]

    def is_staff(self) -> bool:
        """스태프 이상 권한인지"""
        return self.club_role in [
            ClubRole.owner,
            ClubRole.head_coach,
            ClubRole.coach,
            ClubRole.staff
        ]

    def can_manage_members(self) -> bool:
        """회원 관리 권한"""
        return self.is_staff()

    def can_manage_fees(self) -> bool:
        """비용 관리 권한"""
        return self.is_staff()

    def can_view_all_attendance(self) -> bool:
        """전체 출석 조회 권한"""
        return self.is_staff()


async def get_current_club_member(request: Request) -> ClubMemberContext:
    """
    현재 로그인한 클럽 회원 정보 조회

    인증 방식 (우선순위):
    1. 테스트 모드 (CLUB_TEST_MODE=1 또는 ?test=1)
    2. 자체 JWT (카카오/구글 OAuth → 쿠키 또는 Bearer)
    3. Supabase Auth (Bearer 토큰)
    """
    from .players.service import get_supabase_client

    # 테스트 모드 체크 (환경변수 또는 쿼리 파라미터)
    test_param = request.query_params.get("test", "0")
    is_test_mode = TEST_MODE_ENV or test_param == "1"

    if is_test_mode:
        return ClubMemberContext(
            member_id=TEST_CLUB_CONFIG["member_id"],
            organization_id=TEST_CLUB_CONFIG["organization_id"],
            club_role=TEST_CLUB_CONFIG["club_role"],
            full_name=TEST_CLUB_CONFIG["full_name"],
            player_id=TEST_CLUB_CONFIG["player_id"]
        )

    # 토큰 추출: Bearer 헤더 또는 쿠키
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    else:
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다"
        )

    # 방법 1: 자체 JWT 토큰 (카카오/구글 OAuth 로그인)
    member = await _try_app_jwt_auth(token)

    # 방법 2: Supabase Auth 토큰
    if not member:
        member = await _try_supabase_auth(token)

    if not member:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다"
        )

    if not member.get("organization_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="소속 클럽이 없습니다"
        )

    if not member.get("club_role"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="클럽 역할이 지정되지 않았습니다"
        )

    return ClubMemberContext(
        member_id=member["id"],
        organization_id=member["organization_id"],
        club_role=ClubRole(member["club_role"]),
        full_name=member["full_name"],
        player_id=member.get("player_id"),
        guardian_member_id=member.get("guardian_member_id")
    )


async def _try_app_jwt_auth(token: str) -> Optional[dict]:
    """자체 JWT 토큰으로 회원 조회 (카카오/구글 OAuth 로그인)"""
    try:
        from app.auth.config import get_auth_settings
        settings = get_auth_settings()

        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        member_id = payload.get("member_id")
        if not member_id:
            return None

        from .players.service import get_supabase_client
        supabase = get_supabase_client()
        result = supabase.table("members").select(
            "id, organization_id, club_role, full_name, player_id, guardian_member_id"
        ).eq("id", member_id).single().execute()

        return result.data
    except JWTError:
        return None
    except Exception as e:
        logger.debug(f"자체 JWT 인증 실패 (Supabase Auth로 폴백): {e}")
        return None


async def _try_supabase_auth(token: str) -> Optional[dict]:
    """Supabase Auth 토큰으로 회원 조회"""
    try:
        from .players.service import get_supabase_client
        supabase = get_supabase_client()
        user_response = supabase.auth.get_user(token)

        if not user_response or not user_response.user:
            return None

        user_id = user_response.user.id
        result = supabase.table("members").select(
            "id, organization_id, club_role, full_name, player_id, guardian_member_id"
        ).eq("supabase_auth_id", user_id).single().execute()

        return result.data
    except Exception as e:
        logger.debug(f"Supabase Auth 인증 실패: {e}")
        return None


def require_coach(member: ClubMemberContext = Depends(get_current_club_member)) -> ClubMemberContext:
    """코치 이상 권한 필요"""
    if not member.is_coach():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="코치 이상 권한이 필요합니다"
        )
    return member


def require_admin(member: ClubMemberContext = Depends(get_current_club_member)) -> ClubMemberContext:
    """관리자 권한 필요 (owner/head_coach)"""
    if not member.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다"
        )
    return member


def require_staff(member: ClubMemberContext = Depends(get_current_club_member)) -> ClubMemberContext:
    """스태프 이상 권한 필요"""
    if not member.is_staff():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="스태프 이상 권한이 필요합니다"
        )
    return member


def require_roles(allowed_roles: List[ClubRole]):
    """특정 역할 필요"""
    def _check(member: ClubMemberContext = Depends(get_current_club_member)) -> ClubMemberContext:
        if member.club_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"허용된 역할: {', '.join([r.value for r in allowed_roles])}"
            )
        return member
    return _check
