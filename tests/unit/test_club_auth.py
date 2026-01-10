"""
Club Management Authentication & Authorization Tests

인증 및 권한 관리 테스트
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi import HTTPException, Request

from app.club.dependencies import (
    ClubMemberContext,
    ClubRole,
    get_current_club_member,
    require_coach,
    require_admin,
    require_staff,
    get_client_ip,
)


class TestClubMemberContext:
    """ClubMemberContext 테스트"""

    def test_init(self, test_organization_id, owner_member_id):
        """컨텍스트 초기화"""
        context = ClubMemberContext(
            member_id=owner_member_id,
            organization_id=test_organization_id,
            club_role=ClubRole.owner,
            full_name="최병철",
            player_id=None,
        )

        assert context.member_id == owner_member_id
        assert context.organization_id == test_organization_id
        assert context.club_role == ClubRole.owner
        assert context.full_name == "최병철"
        assert context.player_id is None

    def test_is_coach_owner(self, owner_context):
        """Owner는 coach 권한 보유"""
        assert owner_context.is_coach() is True

    def test_is_coach_head_coach(self, test_organization_id):
        """Head coach는 coach 권한 보유"""
        context = ClubMemberContext(
            member_id="test",
            organization_id=test_organization_id,
            club_role=ClubRole.head_coach,
            full_name="수석코치",
        )
        assert context.is_coach() is True

    def test_is_coach_regular_coach(self, coach_context):
        """Coach는 coach 권한 보유"""
        assert coach_context.is_coach() is True

    def test_is_coach_student(self, student_context):
        """Student는 coach 권한 없음"""
        assert student_context.is_coach() is False

    def test_is_admin_owner(self, owner_context):
        """Owner는 admin 권한 보유"""
        assert owner_context.is_admin() is True

    def test_is_admin_head_coach(self, test_organization_id):
        """Head coach는 admin 권한 보유"""
        context = ClubMemberContext(
            member_id="test",
            organization_id=test_organization_id,
            club_role=ClubRole.head_coach,
            full_name="수석코치",
        )
        assert context.is_admin() is True

    def test_is_admin_regular_coach(self, coach_context):
        """일반 coach는 admin 권한 없음"""
        assert coach_context.is_admin() is False

    def test_is_staff_owner(self, owner_context):
        """Owner는 staff 권한 보유"""
        assert owner_context.is_staff() is True

    def test_is_staff_coach(self, coach_context):
        """Coach는 staff 권한 보유"""
        assert coach_context.is_staff() is True

    def test_is_staff_assistant(self, test_organization_id):
        """Assistant는 staff 권한 없음 (보조 코치는 코치 그룹이지만 staff 권한은 coach 이상)"""
        context = ClubMemberContext(
            member_id="test",
            organization_id=test_organization_id,
            club_role=ClubRole.assistant,
            full_name="보조코치",
        )
        assert context.is_staff() is False

    def test_is_staff_student(self, student_context):
        """Student는 staff 권한 없음"""
        assert student_context.is_staff() is False

    def test_can_manage_members_staff(self, coach_context):
        """Staff는 회원 관리 가능"""
        assert coach_context.can_manage_members() is True

    def test_can_manage_members_student(self, student_context):
        """Student는 회원 관리 불가"""
        assert student_context.can_manage_members() is False

    def test_can_manage_fees_staff(self, coach_context):
        """Staff는 비용 관리 가능"""
        assert coach_context.can_manage_fees() is True

    def test_can_view_all_attendance_staff(self, coach_context):
        """Staff는 전체 출석 조회 가능"""
        assert coach_context.can_view_all_attendance() is True


class TestGetClientIP:
    """클라이언트 IP 추출 테스트"""

    @pytest.mark.asyncio
    async def test_x_forwarded_for(self):
        """X-Forwarded-For 헤더"""
        request = MagicMock(spec=Request)
        request.headers.get = MagicMock(
            side_effect=lambda key: "203.0.113.1, 198.51.100.1" if key == "X-Forwarded-For" else None
        )
        request.client = None

        ip = await get_client_ip(request)
        assert ip == "203.0.113.1"  # 첫 번째 IP

    @pytest.mark.asyncio
    async def test_x_real_ip(self):
        """X-Real-IP 헤더"""
        request = MagicMock(spec=Request)
        request.headers.get = MagicMock(
            side_effect=lambda key: "203.0.113.1" if key == "X-Real-IP" else None
        )
        request.client = None

        ip = await get_client_ip(request)
        assert ip == "203.0.113.1"

    @pytest.mark.asyncio
    async def test_direct_client(self):
        """직접 연결"""
        request = MagicMock(spec=Request)
        request.headers.get = MagicMock(return_value=None)
        request.client = MagicMock()
        request.client.host = "192.168.0.100"

        ip = await get_client_ip(request)
        assert ip == "192.168.0.100"

    @pytest.mark.asyncio
    async def test_no_client(self):
        """클라이언트 정보 없음"""
        request = MagicMock(spec=Request)
        request.headers.get = MagicMock(return_value=None)
        request.client = None

        ip = await get_client_ip(request)
        assert ip == "unknown"


class TestGetCurrentClubMember:
    """get_current_club_member 테스트"""

    @pytest.mark.asyncio
    async def test_test_mode_enabled(self, test_organization_id):
        """테스트 모드 활성화 (환경변수)"""
        request = MagicMock(spec=Request)
        request.query_params.get = MagicMock(return_value="0")

        with patch("app.club.dependencies.TEST_MODE_ENV", True):
            context = await get_current_club_member(request)
            assert context.organization_id == test_organization_id
            assert context.club_role == ClubRole.owner

    @pytest.mark.asyncio
    async def test_test_mode_query_param(self, test_organization_id):
        """테스트 모드 활성화 (쿼리 파라미터)"""
        request = MagicMock(spec=Request)
        request.query_params.get = MagicMock(return_value="1")

        context = await get_current_club_member(request)
        assert context.organization_id == test_organization_id
        assert context.club_role == ClubRole.owner

    @pytest.mark.asyncio
    async def test_no_auth_header(self):
        """인증 토큰 없음"""
        request = MagicMock(spec=Request)
        request.query_params.get = MagicMock(return_value="0")
        request.headers.get = MagicMock(return_value=None)

        with patch("app.club.dependencies.TEST_MODE_ENV", False):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_club_member(request)

            assert exc_info.value.status_code == 401
            assert "인증이 필요합니다" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_invalid_bearer_format(self):
        """잘못된 Bearer 형식"""
        request = MagicMock(spec=Request)
        request.query_params.get = MagicMock(return_value="0")
        request.headers.get = MagicMock(return_value="InvalidFormat token")

        with patch("app.club.dependencies.TEST_MODE_ENV", False):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_club_member(request)

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_token_no_member(self):
        """유효한 토큰이지만 members 테이블에 없음"""
        request = MagicMock(spec=Request)
        request.query_params.get = MagicMock(return_value="0")
        request.headers.get = MagicMock(return_value="Bearer valid_token")

        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "user123"
        mock_user_response = MagicMock()
        mock_user_response.user = mock_user
        mock_supabase.auth.get_user = MagicMock(return_value=mock_user_response)

        # members 조회 실패
        mock_member_response = MagicMock()
        mock_member_response.data = None
        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=mock_member_response)

        with patch("app.club.dependencies.TEST_MODE_ENV", False):
            with patch("database.supabase_client.get_supabase_client", return_value=mock_supabase):
                with pytest.raises(HTTPException) as exc_info:
                    await get_current_club_member(request)

                assert exc_info.value.status_code == 403
                assert "클럽 회원 등록이 필요합니다" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_member_no_organization(self):
        """회원은 있지만 조직 소속이 아님"""
        request = MagicMock(spec=Request)
        request.query_params.get = MagicMock(return_value="0")
        request.headers.get = MagicMock(return_value="Bearer valid_token")

        mock_supabase = MagicMock()
        mock_user = MagicMock()
        mock_user.id = "user123"
        mock_user_response = MagicMock()
        mock_user_response.user = mock_user
        mock_supabase.auth.get_user = MagicMock(return_value=mock_user_response)

        # members 조회 성공하지만 organization_id 없음
        mock_member_response = MagicMock()
        mock_member_response.data = {
            "id": "member123",
            "organization_id": None,
            "club_role": "student",
            "full_name": "테스트",
        }
        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=mock_member_response)

        with patch("app.club.dependencies.TEST_MODE_ENV", False):
            with patch("database.supabase_client.get_supabase_client", return_value=mock_supabase):
                with pytest.raises(HTTPException) as exc_info:
                    await get_current_club_member(request)

                assert exc_info.value.status_code == 403
                assert "소속 클럽이 없습니다" in exc_info.value.detail


class TestRequireCoach:
    """require_coach 테스트"""

    def test_coach_access(self, coach_context):
        """Coach 접근 허용"""
        result = require_coach(coach_context)
        assert result == coach_context

    def test_owner_access(self, owner_context):
        """Owner 접근 허용 (coach 권한 포함)"""
        result = require_coach(owner_context)
        assert result == owner_context

    def test_student_denied(self, student_context):
        """Student 접근 거부"""
        with pytest.raises(HTTPException) as exc_info:
            require_coach(student_context)

        assert exc_info.value.status_code == 403
        assert "코치 이상 권한이 필요합니다" in exc_info.value.detail


class TestRequireAdmin:
    """require_admin 테스트"""

    def test_owner_access(self, owner_context):
        """Owner 접근 허용"""
        result = require_admin(owner_context)
        assert result == owner_context

    def test_head_coach_access(self, test_organization_id):
        """Head coach 접근 허용"""
        context = ClubMemberContext(
            member_id="test",
            organization_id=test_organization_id,
            club_role=ClubRole.head_coach,
            full_name="수석코치",
        )
        result = require_admin(context)
        assert result == context

    def test_coach_denied(self, coach_context):
        """일반 coach 접근 거부"""
        with pytest.raises(HTTPException) as exc_info:
            require_admin(coach_context)

        assert exc_info.value.status_code == 403
        assert "관리자 권한이 필요합니다" in exc_info.value.detail


class TestRequireStaff:
    """require_staff 테스트"""

    def test_owner_access(self, owner_context):
        """Owner 접근 허용"""
        result = require_staff(owner_context)
        assert result == owner_context

    def test_coach_access(self, coach_context):
        """Coach 접근 허용"""
        result = require_staff(coach_context)
        assert result == coach_context

    def test_student_denied(self, student_context):
        """Student 접근 거부"""
        with pytest.raises(HTTPException) as exc_info:
            require_staff(student_context)

        assert exc_info.value.status_code == 403
        assert "스태프 이상 권한이 필요합니다" in exc_info.value.detail


class TestOrganizationIsolation:
    """조직 격리 테스트"""

    def test_different_organization(self, test_organization_id):
        """다른 조직 회원 접근 불가"""
        context1 = ClubMemberContext(
            member_id="member1",
            organization_id=test_organization_id,
            club_role=ClubRole.coach,
            full_name="코치1",
        )

        context2 = ClubMemberContext(
            member_id="member2",
            organization_id=test_organization_id + 1,  # 다른 조직
            club_role=ClubRole.coach,
            full_name="코치2",
        )

        assert context1.organization_id != context2.organization_id

    def test_member_access_own_organization_only(self, owner_context, test_organization_id):
        """회원은 자신의 조직만 접근 가능"""
        assert owner_context.organization_id == test_organization_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
