"""
Pytest configuration and fixtures for Korean Fencing Tracker tests
"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def base_url():
    """Base URL for E2E tests"""
    return "http://localhost:7171"


@pytest.fixture(scope="session")
def sample_competition_id():
    """Known competition ID for testing"""
    return "COMPM00668"


@pytest.fixture(scope="session")
def sample_event_id():
    """Known event ID for testing"""
    return "COMPS000000000003802"


@pytest.fixture(scope="function")
def sample_de_bracket_data():
    """Sample DE bracket data for unit testing"""
    return {
        "seeding": [
            {"seed": 1, "name": "김철수", "team": "서울중학교", "score": "5-0"},
            {"seed": 2, "name": "이영희", "team": "부산중학교", "score": "4-1"},
            {"seed": 3, "name": "박민수", "team": "대전중학교", "score": "3-2"},
            {"seed": 4, "name": "최지영", "team": "인천중학교", "score": "3-2"},
            {"seed": 5, "name": "정동훈", "team": "광주중학교", "score": "2-3"},
            {"seed": 6, "name": "한미경", "team": "대구중학교", "score": "2-3"},
            {"seed": 7, "name": "오승현", "team": "울산중학교", "score": "1-4"},
            {"seed": 8, "name": "장서윤", "team": "수원중학교", "score": "0-5"},
        ],
        "results_by_round": {
            "8강전": [
                {"seed": 1, "name": "김철수", "score": {"winner_score": 15, "loser_score": 10}},
                {"seed": 2, "name": "이영희", "score": {"winner_score": 15, "loser_score": 12}},
                {"seed": 3, "name": "박민수", "score": {"winner_score": 15, "loser_score": 8}},
                {"seed": 4, "name": "최지영", "score": {"winner_score": 15, "loser_score": 11}},
            ],
            "준결승": [
                {"seed": 1, "name": "김철수", "score": {"winner_score": 15, "loser_score": 13}},
                {"seed": 3, "name": "박민수", "score": {"winner_score": 15, "loser_score": 14}},
            ],
            "결승": [
                {"seed": 1, "name": "김철수", "score": {"winner_score": 15, "loser_score": 12}},
            ],
        }
    }


@pytest.fixture(scope="function")
def sample_event_data(sample_de_bracket_data):
    """Sample event data with DE bracket"""
    return {
        "name": "남자 플러레 중등부 개인",
        "sub_event_cd": "COMPS000000000003802",
        "weapon": "플러레",
        "gender": "남",
        "age_group": "중등부",
        "event_type": "개인전",
        "participant_count": 65,
        "de_bracket": sample_de_bracket_data,
        "final_rankings": [
            {"rank": 1, "name": "김철수", "team": "서울중학교"},
            {"rank": 2, "name": "박민수", "team": "대전중학교"},
            {"rank": 3, "name": "이영희", "team": "부산중학교"},
            {"rank": 3, "name": "최지영", "team": "인천중학교"},
        ],
        "pool_rounds": [
            {
                "pool_number": 1,
                "results": [
                    {"name": "김철수", "team": "서울중학교", "rank": 1, "v": 5, "d": 0, "ts": 25, "tr": 10},
                    {"name": "정동훈", "team": "광주중학교", "rank": 2, "v": 4, "d": 1, "ts": 23, "tr": 15},
                ]
            }
        ]
    }


@pytest.fixture(scope="function")
def sample_competition_data():
    """Sample competition data"""
    return {
        "event_cd": "COMPM00668",
        "comp_name": "2024년 전국중고등학교펜싱선수권대회",
        "start_date": "2024-07-01",
        "end_date": "2024-07-05",
        "location": "충주",
        "events": []
    }
