"""
통합 인증 Dependencies

모든 서브도메인에서 공유하는 인증/권한 체크 FastAPI 의존성.
기존 ClubMemberContext를 일반화한 ServiceMemberContext 제공.
"""
import os
from typing import Optional, List

from fastapi import Depends, HTTPException, status, Request

from shared_core.types.member import ClubRole
from shared_core.auth.jwt import decode_token, extract_token
from shared_core.db.client import get_supabase_client


# 테스트 모드 설정
TEST_MODE_ENV = os.getenv("CLUB_TEST_MODE", "0") == "1"

# 테스트용 기본 클럽 설정 (최병철펜싱클럽)
TEST_CLUB_CONFIG = {
    "organization_id": 401,
    "organization_name": "최병철펜싱클럽",
    "member_id": "00000000-0000-0000-0000-000000000001",
    "full_name": "최병철",
    "club_role": ClubRole.owner,
    "player_id": None,
}


class ServiceMemberContext:
    """
    서비스 회원 컨텍스트

    기존 ClubMemberContext를 일반화하여 모든 서브도메인에서 사용 가능.
    """

    def __init__(
        self,
        member_id: str,
        organization_id: Optional[int] = None,
        club_role: Optional[ClubRole] = None,
        full_name: str = "",
        player_id: Optional[int] = None,
        guardian_member_id: Optional[str] = None,
        email: Optional[str] = None,
        member_type: Optional[str] = None,
    ):
        self.member_id = member_id
        self.organization_id = organization_id
        self.club_role = club_role
        self.full_name = full_name
        self.player_id = player_id
        self.guardian_member_id = guardian_member_id
        self.email = email
        self.member_type = member_type

    def is_coach(self) -> bool:
        """코치 이상 권한인지"""
        return self.club_role in [
            ClubRole.owner,
            ClubRole.head_coach,
            ClubRole.coach,
        ]

    def is_admin(self) -> bool:
        """관리자 권한인지 (owner/head_coach)"""
        return self.club_role in [
            ClubRole.owner,
            ClubRole.head_coach,
        ]

    def is_staff(self) -> bool:
        """스태프 이상 권한인지"""
        return self.club_role in [
            ClubRole.owner,
            ClubRole.head_coach,
            ClubRole.coach,
            ClubRole.staff,
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


async def get_current_club_member(request: Request) -> ServiceMemberContext:
    """
    현재 로그인한 클럽 회원 정보 조회

    통합 JWT 토큰 기반 인증 + Supabase Auth 폴백.

    테스트 모드:
    - 환경변수 CLUB_TEST_MODE=1
    - 또는 쿼리 파라미터 ?test=1
    """
    # 테스트 모드 체크
    test_param = request.query_params.get("test", "0")
    is_test_mode = TEST_MODE_ENV or test_param == "1"

    if is_test_mode:
        return ServiceMemberContext(
            member_id=TEST_CLUB_CONFIG["member_id"],
            organization_id=TEST_CLUB_CONFIG["organization_id"],
            club_role=TEST_CLUB_CONFIG["club_role"],
            full_name=TEST_CLUB_CONFIG["full_name"],
            player_id=TEST_CLUB_CONFIG["player_id"],
        )

    # 1. 통합 JWT 토큰 시도
    token = extract_token(request)
    if token:
        payload = decode_token(token)
        if payload and payload.get("member_id"):
            try:
                supabase = get_supabase_client()
                member_response = supabase.table("members").select(
                    "id, organization_id, club_role, full_name, player_id, "
                    "guardian_member_id, email, member_type"
                ).eq("id", payload["member_id"]).single().execute()

                if member_response.data:
                    member = member_response.data
                    if not member.get("organization_id"):
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="소속 클럽이 없습니다",
                        )
                    if not member.get("club_role"):
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="클럽 역할이 지정되지 않았습니다",
                        )
                    return ServiceMemberContext(
                        member_id=member["id"],
                        organization_id=member["organization_id"],
                        club_role=ClubRole(member["club_role"]),
                        full_name=member["full_name"],
                        player_id=member.get("player_id"),
                        guardian_member_id=member.get("guardian_member_id"),
                        email=member.get("email"),
                        member_type=member.get("member_type"),
                    )
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"인증 오류: {str(e)}",
                )

    # 2. Supabase Auth 토큰 폴백 (기존 호환성)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        sb_token = auth_header.split(" ")[1]
        try:
            supabase = get_supabase_client()
            user_response = supabase.auth.get_user(sb_token)
            if not user_response or not user_response.user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="유효하지 않은 토큰입니다",
                )

            user_id = user_response.user.id
            member_response = supabase.table("members").select(
                "id, organization_id, club_role, full_name, player_id, "
                "guardian_member_id, email, member_type"
            ).eq("supabase_auth_id", user_id).single().execute()

            if not member_response.data:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="클럽 회원 등록이 필요합니다",
                )

            member = member_response.data
            if not member.get("organization_id"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="소속 클럽이 없습니다",
                )
            if not member.get("club_role"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="클럽 역할이 지정되지 않았습니다",
                )

            return ServiceMemberContext(
                member_id=member["id"],
                organization_id=member["organization_id"],
                club_role=ClubRole(member["club_role"]),
                full_name=member["full_name"],
                player_id=member.get("player_id"),
                guardian_member_id=member.get("guardian_member_id"),
                email=member.get("email"),
                member_type=member.get("member_type"),
            )

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"인증 오류: {str(e)}",
            )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증이 필요합니다",
    )


def require_coach(
    member: ServiceMemberContext = Depends(get_current_club_member),
) -> ServiceMemberContext:
    """코치 이상 권한 필요"""
    if not member.is_coach():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="코치 이상 권한이 필요합니다",
        )
    return member


def require_admin(
    member: ServiceMemberContext = Depends(get_current_club_member),
) -> ServiceMemberContext:
    """관리자 권한 필요 (owner/head_coach)"""
    if not member.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다",
        )
    return member


def require_staff(
    member: ServiceMemberContext = Depends(get_current_club_member),
) -> ServiceMemberContext:
    """스태프 이상 권한 필요"""
    if not member.is_staff():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="스태프 이상 권한이 필요합니다",
        )
    return member


def require_roles(allowed_roles: List[ClubRole]):
    """특정 역할 필요"""
    def _check(
        member: ServiceMemberContext = Depends(get_current_club_member),
    ) -> ServiceMemberContext:
        if member.club_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"허용된 역할: {', '.join([r.value for r in allowed_roles])}",
            )
        return member
    return _check
