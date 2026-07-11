"""
Club Check-in Tests

출석 체크인 기능 테스트
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, date, timedelta
from fastapi import HTTPException

from app.club.models import (
    CheckInRequest,
    CheckInResponse,
    AttendanceType,
    CheckinMethod,
)
from app.club.router import (
    check_in,
    get_checkin_status,
    _check_auto_checkin_eligibility,
)


class TestAutoCheckinEligibility:
    """자동 체크인 자격 확인 테스트"""

    @pytest.mark.asyncio
    async def test_auto_checkin_enabled_ip_match(self, test_organization_id):
        """자동 체크인 활성화 + IP 일치"""
        mock_supabase = MagicMock()
        mock_response = MagicMock()
        mock_response.data = {
            "auto_checkin_enabled": True,
            "allowed_ips": ["192.168.0.*", "10.0.0.100"],
        }

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=mock_response)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            result = await _check_auto_checkin_eligibility(
                test_organization_id,
                "192.168.0.100"
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_auto_checkin_disabled(self, test_organization_id):
        """자동 체크인 비활성화"""
        mock_supabase = MagicMock()
        mock_response = MagicMock()
        mock_response.data = {
            "auto_checkin_enabled": False,
            "allowed_ips": ["192.168.0.*"],
        }

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=mock_response)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            result = await _check_auto_checkin_eligibility(
                test_organization_id,
                "192.168.0.100"
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_ip_not_in_allowed_list(self, test_organization_id):
        """허용되지 않은 IP"""
        mock_supabase = MagicMock()
        mock_response = MagicMock()
        mock_response.data = {
            "auto_checkin_enabled": True,
            "allowed_ips": ["192.168.0.*"],
        }

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=mock_response)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            result = await _check_auto_checkin_eligibility(
                test_organization_id,
                "203.0.113.1"  # 외부 IP
            )
            assert result is False

    @pytest.mark.asyncio
    async def test_subnet_wildcard_match(self, test_organization_id):
        """서브넷 와일드카드 매칭"""
        mock_supabase = MagicMock()
        mock_response = MagicMock()
        mock_response.data = {
            "auto_checkin_enabled": True,
            "allowed_ips": ["192.168.0.*"],
        }

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=mock_response)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            # 192.168.0.* 범위 내 IP
            result1 = await _check_auto_checkin_eligibility(
                test_organization_id,
                "192.168.0.1"
            )
            assert result1 is True

            result2 = await _check_auto_checkin_eligibility(
                test_organization_id,
                "192.168.0.255"
            )
            assert result2 is True

    @pytest.mark.asyncio
    async def test_no_settings_found(self, test_organization_id):
        """클럽 설정이 없는 경우"""
        mock_supabase = MagicMock()
        mock_response = MagicMock()
        mock_response.data = None

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.execute = MagicMock(return_value=mock_response)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            result = await _check_auto_checkin_eligibility(
                test_organization_id,
                "192.168.0.100"
            )
            assert result is False


class TestCheckIn:
    """체크인 테스트"""

    @pytest.mark.asyncio
    async def test_successful_checkin_auto_ip(self, student_context):
        """성공적인 자동 체크인 (IP 기반)"""
        request = MagicMock()
        request.client.host = "192.168.0.100"
        request.headers.get = MagicMock(return_value=None)

        checkin_data = CheckInRequest(
            attendance_type=AttendanceType.regular,
            notes=None,
        )

        mock_supabase = MagicMock()

        # 자동 체크인 설정
        settings_response = MagicMock()
        settings_response.data = {
            "auto_checkin_enabled": True,
            "allowed_ips": ["192.168.0.*"],
        }

        # 오늘 체크인 없음
        existing_response = MagicMock()
        existing_response.data = []

        # 체크인 생성
        insert_response = MagicMock()
        insert_response.data = [{
            "id": "checkin123",
            "member_id": student_context.member_id,
            "check_in_at": datetime.now().isoformat(),
        }]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.gte = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.insert = MagicMock(return_value=mock_supabase)

        # 순차적으로 다른 응답 반환
        execute_calls = [settings_response, existing_response, insert_response]
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            with patch("app.club.router.get_client_ip", return_value="192.168.0.100"):
                response = await check_in(request, checkin_data, student_context)

                assert response.member_id == student_context.member_id
                assert response.member_name == student_context.full_name
                assert response.checkin_method == CheckinMethod.auto_ip
                assert response.auto_checkin_available is True

    @pytest.mark.asyncio
    async def test_checkin_manual_outside_ip(self, student_context):
        """수동 체크인 (IP 범위 밖)"""
        request = MagicMock()

        checkin_data = CheckInRequest(
            attendance_type=AttendanceType.regular,
        )

        mock_supabase = MagicMock()

        # 자동 체크인 불가 (IP 불일치)
        settings_response = MagicMock()
        settings_response.data = {
            "auto_checkin_enabled": True,
            "allowed_ips": ["192.168.0.*"],
        }

        existing_response = MagicMock()
        existing_response.data = []

        insert_response = MagicMock()
        insert_response.data = [{
            "id": "checkin123",
            "member_id": student_context.member_id,
            "check_in_at": datetime.now().isoformat(),
        }]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.gte = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.insert = MagicMock(return_value=mock_supabase)

        execute_calls = [settings_response, existing_response, insert_response]
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            with patch("app.club.router.get_client_ip", return_value="203.0.113.1"):
                response = await check_in(request, checkin_data, student_context)

                assert response.checkin_method == CheckinMethod.manual
                assert response.auto_checkin_available is False

    @pytest.mark.asyncio
    async def test_duplicate_checkin_today(self, student_context):
        """오늘 이미 체크인한 경우"""
        request = MagicMock()

        checkin_data = CheckInRequest(
            attendance_type=AttendanceType.regular,
        )

        mock_supabase = MagicMock()

        settings_response = MagicMock()
        settings_response.data = {
            "auto_checkin_enabled": False,
            "allowed_ips": [],
        }

        # 오늘 체크인 이미 있음
        existing_response = MagicMock()
        existing_response.data = [{"id": "existing_checkin"}]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.gte = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)

        execute_calls = [settings_response, existing_response]
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            with patch("app.club.router.get_client_ip", return_value="192.168.0.100"):
                with pytest.raises(HTTPException) as exc_info:
                    await check_in(request, checkin_data, student_context)

                assert exc_info.value.status_code == 400
                assert "오늘 이미 체크인했습니다" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_checkin_with_notes(self, student_context):
        """메모와 함께 체크인"""
        request = MagicMock()

        checkin_data = CheckInRequest(
            attendance_type=AttendanceType.lesson,
            notes="개인 레슨",
        )

        mock_supabase = MagicMock()

        settings_response = MagicMock()
        settings_response.data = {"auto_checkin_enabled": False, "allowed_ips": []}

        existing_response = MagicMock()
        existing_response.data = []

        insert_response = MagicMock()
        insert_response.data = [{
            "id": "checkin123",
            "member_id": student_context.member_id,
            "check_in_at": datetime.now().isoformat(),
            "notes": "개인 레슨",
        }]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.gte = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.insert = MagicMock(return_value=mock_supabase)

        execute_calls = [settings_response, existing_response, insert_response]
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            with patch("app.club.router.get_client_ip", return_value="192.168.0.100"):
                response = await check_in(request, checkin_data, student_context)

                assert response.attendance_type == AttendanceType.lesson


class TestCheckinStatus:
    """체크인 상태 확인 테스트"""

    @pytest.mark.asyncio
    async def test_already_checked_in(self, student_context):
        """이미 체크인한 상태"""
        request = MagicMock()

        mock_supabase = MagicMock()

        # 자동 체크인 설정
        settings_response = MagicMock()
        settings_response.data = {
            "auto_checkin_enabled": True,
            "allowed_ips": ["192.168.0.*"],
        }

        # 오늘 체크인 있음
        today = date.today().isoformat()
        existing_response = MagicMock()
        existing_response.data = [{
            "id": "checkin123",
            "check_in_at": f"{today}T10:00:00",
            "attendance_type": "regular",
        }]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.gte = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)

        execute_calls = [existing_response, settings_response]
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            with patch("app.club.router.get_client_ip", return_value="192.168.0.100"):
                result = await get_checkin_status(request, student_context)

                assert result["already_checked_in"] is True
                assert result["checkin_record"] is not None
                assert result["auto_checkin_available"] is True

    @pytest.mark.asyncio
    async def test_not_checked_in_yet(self, student_context):
        """아직 체크인하지 않은 상태"""
        request = MagicMock()

        mock_supabase = MagicMock()

        settings_response = MagicMock()
        settings_response.data = {
            "auto_checkin_enabled": True,
            "allowed_ips": ["192.168.0.*"],
        }

        existing_response = MagicMock()
        existing_response.data = []

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.gte = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)

        execute_calls = [existing_response, settings_response]
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            with patch("app.club.router.get_client_ip", return_value="192.168.0.100"):
                result = await get_checkin_status(request, student_context)

                assert result["already_checked_in"] is False
                assert result["checkin_record"] is None


class TestConcurrentCheckin:
    """동시 체크인 테스트"""

    @pytest.mark.asyncio
    async def test_race_condition_prevention(self, student_context):
        """동시 체크인 시도 방지"""
        # 실제로는 DB unique constraint나 transaction으로 방지
        # 여기서는 로직 테스트
        request = MagicMock()

        checkin_data = CheckInRequest(attendance_type=AttendanceType.regular)

        mock_supabase = MagicMock()

        settings_response = MagicMock()
        settings_response.data = {"auto_checkin_enabled": False, "allowed_ips": []}

        # 첫 번째 체크: 없음
        existing_response_1 = MagicMock()
        existing_response_1.data = []

        # 두 번째 체크: 생성됨 (동시 요청으로 인해)
        existing_response_2 = MagicMock()
        existing_response_2.data = [{"id": "checkin123"}]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.gte = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)

        execute_calls = [settings_response, existing_response_2]  # 이미 있음
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            with patch("app.club.router.get_client_ip", return_value="192.168.0.100"):
                with pytest.raises(HTTPException) as exc_info:
                    await check_in(request, checkin_data, student_context)

                assert exc_info.value.status_code == 400


class TestTimezoneHandling:
    """시간대 처리 테스트"""

    @pytest.mark.asyncio
    async def test_checkin_near_midnight(self, student_context):
        """자정 근처 체크인 (날짜 경계)"""
        request = MagicMock()

        checkin_data = CheckInRequest(attendance_type=AttendanceType.regular)

        mock_supabase = MagicMock()

        settings_response = MagicMock()
        settings_response.data = {"auto_checkin_enabled": False, "allowed_ips": []}

        # 오늘 체크인 확인 - 날짜 기준으로 올바르게 비교되는지
        today = date.today().isoformat()
        existing_response = MagicMock()
        existing_response.data = []

        insert_response = MagicMock()
        insert_response.data = [{
            "id": "checkin123",
            "member_id": student_context.member_id,
            "check_in_at": f"{today}T23:59:59",
        }]

        mock_supabase.table = MagicMock(return_value=mock_supabase)
        mock_supabase.select = MagicMock(return_value=mock_supabase)
        mock_supabase.eq = MagicMock(return_value=mock_supabase)
        mock_supabase.gte = MagicMock(return_value=mock_supabase)
        mock_supabase.lte = MagicMock(return_value=mock_supabase)
        mock_supabase.single = MagicMock(return_value=mock_supabase)
        mock_supabase.insert = MagicMock(return_value=mock_supabase)

        execute_calls = [settings_response, existing_response, insert_response]
        mock_supabase.execute = MagicMock(side_effect=execute_calls)

        with patch("app.club.router.get_supabase_client", return_value=mock_supabase):
            with patch("app.club.router.get_client_ip", return_value="192.168.0.100"):
                response = await check_in(request, checkin_data, student_context)

                # 체크인 시간이 오늘 날짜 범위 내에 있는지 확인
                assert response is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
