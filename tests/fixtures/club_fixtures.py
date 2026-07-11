"""
Club Management Test Fixtures

공통 테스트 데이터 및 Mocks
"""

import pytest
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4

from app.club.models import (
    ClubRole,
    MemberStatus,
    AttendanceType,
    CheckinMethod,
    LessonType,
    LessonStatus,
    ParticipantStatus,
)
from app.club.dependencies import ClubMemberContext


# =============================================
# Organization & Member Fixtures
# =============================================

@pytest.fixture
def test_organization_id():
    """테스트용 조직 ID (최병철펜싱클럽)"""
    return 401


@pytest.fixture
def test_organization_name():
    """테스트용 조직 이름"""
    return "최병철펜싱클럽"


@pytest.fixture
def owner_member_id():
    """Owner 회원 ID"""
    return str(uuid4())


@pytest.fixture
def coach_member_id():
    """Coach 회원 ID"""
    return str(uuid4())


@pytest.fixture
def student_member_id():
    """Student 회원 ID"""
    return str(uuid4())


@pytest.fixture
def parent_member_id():
    """Parent 회원 ID"""
    return str(uuid4())


@pytest.fixture
def owner_context(owner_member_id, test_organization_id):
    """Owner ClubMemberContext"""
    return ClubMemberContext(
        member_id=owner_member_id,
        organization_id=test_organization_id,
        club_role=ClubRole.owner,
        full_name="최병철",
        player_id=None,
    )


@pytest.fixture
def coach_context(coach_member_id, test_organization_id):
    """Coach ClubMemberContext"""
    return ClubMemberContext(
        member_id=coach_member_id,
        organization_id=test_organization_id,
        club_role=ClubRole.coach,
        full_name="김코치",
        player_id=None,
    )


@pytest.fixture
def student_context(student_member_id, test_organization_id):
    """Student ClubMemberContext"""
    return ClubMemberContext(
        member_id=student_member_id,
        organization_id=test_organization_id,
        club_role=ClubRole.student,
        full_name="박소윤",
        player_id=1,
    )


@pytest.fixture
def parent_context(parent_member_id, student_member_id, test_organization_id):
    """Parent ClubMemberContext"""
    return ClubMemberContext(
        member_id=parent_member_id,
        organization_id=test_organization_id,
        club_role=ClubRole.parent,
        full_name="박학부모",
        player_id=None,
        guardian_member_id=student_member_id,
    )


# =============================================
# Supabase Mock Fixtures
# =============================================

@pytest.fixture
def mock_supabase():
    """Mocked Supabase client"""
    mock = MagicMock()
    mock.table = MagicMock(return_value=mock)
    mock.select = MagicMock(return_value=mock)
    mock.insert = MagicMock(return_value=mock)
    mock.update = MagicMock(return_value=mock)
    mock.delete = MagicMock(return_value=mock)
    mock.eq = MagicMock(return_value=mock)
    mock.gte = MagicMock(return_value=mock)
    mock.lte = MagicMock(return_value=mock)
    mock.in_ = MagicMock(return_value=mock)
    mock.or_ = MagicMock(return_value=mock)
    mock.order = MagicMock(return_value=mock)
    mock.limit = MagicMock(return_value=mock)
    mock.single = MagicMock(return_value=mock)

    # Execute returns data
    execute_mock = MagicMock()
    execute_mock.data = []
    execute_mock.count = 0
    mock.execute = MagicMock(return_value=execute_mock)

    return mock


@pytest.fixture
def mock_supabase_with_data(mock_supabase):
    """Supabase mock with sample data"""
    def set_data(data, count=None):
        execute_mock = MagicMock()
        execute_mock.data = data
        execute_mock.count = count if count is not None else len(data) if data else 0
        mock_supabase.execute = MagicMock(return_value=execute_mock)

    mock_supabase.set_data = set_data
    return mock_supabase


# =============================================
# Club Settings Fixtures
# =============================================

@pytest.fixture
def club_settings_data(test_organization_id):
    """클럽 설정 데이터"""
    return {
        "organization_id": test_organization_id,
        "auto_checkin_enabled": True,
        "allowed_ips": ["192.168.0.*", "10.0.0.100"],
        "default_lesson_duration": 60,
        "default_lesson_fee": 50000,
    }


# =============================================
# Attendance Fixtures
# =============================================

@pytest.fixture
def today_checkins_data():
    """오늘 체크인 데이터"""
    today = datetime.now()
    return [
        {
            "id": str(uuid4()),
            "member_id": str(uuid4()),
            "members": {"full_name": "박소윤"},
            "check_in_at": (today - timedelta(hours=2)).isoformat(),
            "attendance_type": "regular",
            "checkin_method": "auto_ip",
        },
        {
            "id": str(uuid4()),
            "member_id": str(uuid4()),
            "members": {"full_name": "김학생"},
            "check_in_at": (today - timedelta(hours=1)).isoformat(),
            "attendance_type": "regular",
            "checkin_method": "manual",
        },
    ]


@pytest.fixture
def attendance_record():
    """단일 출석 기록"""
    return {
        "id": str(uuid4()),
        "member_id": str(uuid4()),
        "organization_id": 401,
        "check_in_at": datetime.now().isoformat(),
        "check_out_at": None,
        "attendance_type": "regular",
        "checkin_method": "auto_ip",
        "client_ip": "192.168.0.100",
        "notes": None,
    }


# =============================================
# Member Fixtures
# =============================================

@pytest.fixture
def members_data(test_organization_id):
    """회원 데이터 목록"""
    return [
        {
            "id": str(uuid4()),
            "full_name": "박소윤",
            "email": "soyoon@test.com",
            "phone": "010-1234-5678",
            "club_role": "student",
            "member_status": "active",
            "organization_id": test_organization_id,
            "player_id": 1,
            "created_at": datetime.now().isoformat(),
        },
        {
            "id": str(uuid4()),
            "full_name": "김학생",
            "email": "student@test.com",
            "phone": "010-2345-6789",
            "club_role": "student",
            "member_status": "active",
            "organization_id": test_organization_id,
            "player_id": None,
            "created_at": datetime.now().isoformat(),
        },
        {
            "id": str(uuid4()),
            "full_name": "김코치",
            "email": "coach@test.com",
            "phone": "010-3456-7890",
            "club_role": "coach",
            "member_status": "active",
            "organization_id": test_organization_id,
            "player_id": None,
            "created_at": datetime.now().isoformat(),
        },
    ]


# =============================================
# Lesson Fixtures
# =============================================

@pytest.fixture
def lesson_data(test_organization_id, coach_member_id):
    """레슨 데이터"""
    return {
        "id": str(uuid4()),
        "organization_id": test_organization_id,
        "lesson_type": "individual",
        "title": "개인 레슨",
        "description": "1:1 개인 레슨",
        "scheduled_at": (datetime.now() + timedelta(days=1)).isoformat(),
        "duration_minutes": 60,
        "coach_id": coach_member_id,
        "max_students": 1,
        "fee_per_session": 50000,
        "status": "scheduled",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }


@pytest.fixture
def lesson_participant_data(lesson_data, student_member_id):
    """레슨 참가자 데이터"""
    return {
        "id": str(uuid4()),
        "lesson_id": lesson_data["id"],
        "member_id": student_member_id,
        "members": {"full_name": "박소윤"},
        "attendance_status": "registered",
        "attended_at": None,
    }


# =============================================
# Fee Fixtures
# =============================================

@pytest.fixture
def fees_data(test_organization_id):
    """비용 데이터 목록"""
    return [
        {
            "id": str(uuid4()),
            "member_id": str(uuid4()),
            "organization_id": test_organization_id,
            "fee_type": "membership",
            "amount": 100000,
            "status": "pending",
            "due_date": date.today().isoformat(),
            "members": {"full_name": "박소윤"},
        },
        {
            "id": str(uuid4()),
            "member_id": str(uuid4()),
            "organization_id": test_organization_id,
            "fee_type": "membership",
            "amount": 100000,
            "status": "overdue",
            "due_date": (date.today() - timedelta(days=10)).isoformat(),
            "members": {"full_name": "김학생"},
        },
        {
            "id": str(uuid4()),
            "member_id": str(uuid4()),
            "organization_id": test_organization_id,
            "fee_type": "membership",
            "amount": 100000,
            "status": "paid",
            "paid_at": datetime.now().isoformat(),
            "members": {"full_name": "이학생"},
        },
    ]


# =============================================
# Player Data Fixtures
# =============================================

@pytest.fixture
def player_search_results():
    """선수 검색 결과"""
    return [
        {
            "player_id": 1,
            "name": "박소윤",
            "team": "최병철펜싱클럽",
            "weapon": "foil",
            "birth_year": 2010,
            "competition_count": 15,
            "is_linked": False,
        },
        {
            "player_id": 2,
            "name": "김학생",
            "team": "최병철펜싱클럽",
            "weapon": "epee",
            "birth_year": 2011,
            "competition_count": 8,
            "is_linked": False,
        },
    ]


@pytest.fixture
def player_profile_data():
    """선수 프로필 데이터"""
    return {
        "player_id": 1,
        "name": "박소윤",
        "team": "최병철펜싱클럽",
        "weapon": "foil",
        "birth_year": 2010,
        "nationality": "KOR",
        "total_competitions": 15,
        "total_events": 20,
        "gold_medals": 3,
        "silver_medals": 5,
        "bronze_medals": 7,
        "current_rankings": [
            {
                "weapon": "foil",
                "gender": "female",
                "age_group": "중등부",
                "rank": 5,
                "points": 120.5,
                "year": 2025,
            }
        ],
    }


@pytest.fixture
def player_stats_data():
    """선수 통계 데이터"""
    return {
        "player_id": 1,
        "player_name": "박소윤",
        "pool_total_bouts": 100,
        "pool_wins": 75,
        "pool_losses": 25,
        "pool_win_rate": 75.0,
        "pool_touches_scored": 450,
        "pool_touches_received": 300,
        "pool_indicator": 150,
        "de_total_events": 15,
        "de_advancement_rate": 0.8,
        "de_avg_rounds_won": 2.5,
        "medal_count": 15,
        "avg_final_rank": 5.3,
    }


# =============================================
# FastAPI Test Client Fixtures
# =============================================

@pytest.fixture
def client():
    """FastAPI TestClient"""
    from fastapi.testclient import TestClient
    from app.server import app

    return TestClient(app)


@pytest.fixture
def auth_headers(owner_context):
    """인증 헤더 (owner)"""
    from app.auth.router import create_access_token

    token = create_access_token({
        "member_id": owner_context.member_id,
        "email": "owner@test.com",
        "member_type": "club_coach",
    })

    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def coach_auth_headers(coach_context):
    """인증 헤더 (coach)"""
    from app.auth.router import create_access_token

    token = create_access_token({
        "member_id": coach_context.member_id,
        "email": "coach@test.com",
        "member_type": "club_coach",
    })

    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def student_auth_headers(student_context):
    """인증 헤더 (student)"""
    from app.auth.router import create_access_token

    token = create_access_token({
        "member_id": student_context.member_id,
        "email": "student@test.com",
        "member_type": "player",
    })

    return {"Authorization": f"Bearer {token}"}
