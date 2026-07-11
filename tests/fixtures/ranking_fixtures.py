"""
Test fixtures for ranking calculator tests
"""
import pytest
from datetime import date, timedelta
from ranking.calculator import PlayerResult


@pytest.fixture
def sample_player_result():
    """Basic player result fixture"""
    return PlayerResult(
        player_name="박소윤",
        team="최병철펜싱클럽",
        event_name="여자 초등부(5-6학년) 플러레 개인전",
        competition_name="2024 회장배 전국펜싱선수권대회",
        competition_date=date(2024, 7, 15),
        final_rank=1,
        total_participants=64,
        weapon="플러레",
        gender="여",
        age_group="E3",
        tier="S",
        category="PRO",
        points=0.0
    )


@pytest.fixture
def large_competition_result():
    """Large competition (128+ participants) result"""
    return PlayerResult(
        player_name="김철수",
        team="서울펜싱클럽",
        event_name="남자 일반부 에뻬 개인전",
        competition_name="전국체전 펜싱",
        competition_date=date(2024, 10, 1),
        final_rank=1,
        total_participants=150,
        weapon="에뻬",
        gender="남",
        age_group="SR",
        tier="S",
        category="PRO",
        points=0.0
    )


@pytest.fixture
def small_competition_result():
    """Small competition (< 8 participants) result"""
    return PlayerResult(
        player_name="이영희",
        team="부산펜싱클럽",
        event_name="여자 초등부(1-2학년) 사브르 개인전",
        competition_name="지역 클럽 대회",
        competition_date=date(2024, 5, 10),
        final_rank=2,
        total_participants=6,
        weapon="사브르",
        gender="여",
        age_group="E1",
        tier="C",
        category="CLUB",
        points=0.0
    )


@pytest.fixture
def u17_result():
    """U17 age group result (special case)"""
    return PlayerResult(
        player_name="최민수",
        team="대전펜싱클럽",
        event_name="남자 U17 플러레 개인전",
        competition_name="익산 국제펜싱대회",
        competition_date=date(2024, 8, 20),
        final_rank=5,
        total_participants=48,
        weapon="플러레",
        gender="남",
        age_group="U17",
        tier="D",
        category="PRO",
        points=0.0
    )


@pytest.fixture
def club_competition_result():
    """Club competition result (amateur category)"""
    return PlayerResult(
        player_name="정지영",
        team="인천동호인펜싱클럽",
        event_name="남자 일반부 에뻬 개인전",
        competition_name="클럽 친선 펜싱대회",
        competition_date=date(2024, 6, 5),
        final_rank=3,
        total_participants=24,
        weapon="에뻬",
        gender="남",
        age_group="SR",
        tier="C",
        category="CLUB",
        points=0.0
    )


@pytest.fixture
def player_results_multiple():
    """Multiple results for same player for ranking calculation"""
    base_date = date(2024, 1, 1)
    return [
        PlayerResult(
            player_name="박소윤",
            team="최병철펜싱클럽",
            event_name="여자 초등부(5-6학년) 플러레 개인전",
            competition_name=f"대회 {i+1}",
            competition_date=base_date + timedelta(days=30 * i),
            final_rank=rank,
            total_participants=64,
            weapon="플러레",
            gender="여",
            age_group="E3",
            tier="A",
            category="PRO",
            points=0.0
        )
        for i, rank in enumerate([1, 2, 1, 3, 5, 1, 8])
    ]


@pytest.fixture
def player_results_different_weapons():
    """Results with different weapons for same player"""
    return [
        PlayerResult(
            player_name="홍길동",
            team="서울펜싱클럽",
            event_name="남자 고등부 플러레 개인전",
            competition_name="플러레 대회",
            competition_date=date(2024, 3, 1),
            final_rank=1,
            total_participants=32,
            weapon="플러레",
            gender="남",
            age_group="HS",
            tier="A",
            category="PRO",
            points=0.0
        ),
        PlayerResult(
            player_name="홍길동",
            team="서울펜싱클럽",
            event_name="남자 고등부 에뻬 개인전",
            competition_name="에뻬 대회",
            competition_date=date(2024, 4, 1),
            final_rank=2,
            total_participants=32,
            weapon="에뻬",
            gender="남",
            age_group="HS",
            tier="A",
            category="PRO",
            points=0.0
        ),
    ]


@pytest.fixture
def national_team_results():
    """National team selection competition results"""
    return [
        PlayerResult(
            player_name="강태희",
            team="국가대표",
            event_name="남자 일반부 사브르 개인전",
            competition_name="국가대표 선발전",
            competition_date=date(2024, 2, 15),
            final_rank=1,
            total_participants=20,
            weapon="사브르",
            gender="남",
            age_group="SR",
            tier="S",
            category="PRO",
            points=0.0
        ),
        PlayerResult(
            player_name="강태희",
            team="서울시청",
            event_name="남자 일반부 사브르 개인전",
            competition_name="일반 대회",
            competition_date=date(2024, 3, 15),
            final_rank=1,
            total_participants=40,
            weapon="사브르",
            gender="남",
            age_group="SR",
            tier="A",
            category="PRO",
            points=0.0
        ),
    ]


@pytest.fixture
def old_results():
    """Results older than rolling window (> 12 months)"""
    old_date = date.today() - timedelta(days=400)
    return [
        PlayerResult(
            player_name="김오래",
            team="역사펜싱클럽",
            event_name="남자 일반부 플러레 개인전",
            competition_name="2년전 대회",
            competition_date=old_date,
            final_rank=1,
            total_participants=64,
            weapon="플러레",
            gender="남",
            age_group="SR",
            tier="A",
            category="PRO",
            points=0.0
        )
    ]


@pytest.fixture
def recent_results():
    """Results within rolling window (< 12 months)"""
    recent_date = date.today() - timedelta(days=30)
    return [
        PlayerResult(
            player_name="김최근",
            team="현재펜싱클럽",
            event_name="여자 일반부 에뻬 개인전",
            competition_name="최근 대회",
            competition_date=recent_date,
            final_rank=1,
            total_participants=64,
            weapon="에뻬",
            gender="여",
            age_group="SR",
            tier="A",
            category="PRO",
            points=0.0
        )
    ]


@pytest.fixture
def mock_competition_data():
    """Mock full competition data structure (for load_from_data)"""
    return {
        "competitions": [
            {
                "competition": {
                    "name": "2024 회장배",
                    "start_date": "2024-07-15",
                },
                "events": [
                    {
                        "name": "여자 초등부(5-6학년) 플러레 개인전",
                        "weapon": "플러레",
                        "gender": "여",
                        "age_group": "E3",
                        "total_participants": 64,
                        "final_rankings": [
                            {"rank": 1, "name": "박소윤", "team": "최병철펜싱클럽"},
                            {"rank": 2, "name": "김서연", "team": "서울펜싱클럽"},
                            {"rank": 3, "name": "이지은", "team": "부산펜싱클럽"},
                        ],
                    }
                ],
            }
        ],
        "meta": {"total_competitions": 1},
    }


@pytest.fixture
def incomplete_event_data():
    """Event data with missing fields (edge case)"""
    return {
        "competition": {
            "name": "불완전 대회",
            "start_date": "2024-01-01",
        },
        "events": [
            {
                "name": "종목 이름만 있음",
                "final_rankings": [
                    {"rank": 1, "name": "선수A", "team": ""},
                    {"rank": 0, "name": "", "team": "팀B"},  # Invalid rank
                ],
            }
        ],
    }
