"""
Test fixtures for scraper unit tests
"""
import pytest
from datetime import date
from typing import Dict, Any


# ============================================
# HTML Fixtures (Competition List)
# ============================================

@pytest.fixture
def competition_list_html():
    """대회 목록 HTML (정상 케이스)"""
    return """
    <table class="list">
        <tr><th>번호</th><th>대회명</th><th>기간</th></tr>
        <tr>
            <td>1</td>
            <td><a onclick="funcView('COMP001')">2024 회장배 펜싱대회</a></td>
            <td>2024.01.15 ~ 2024.01.17</td>
        </tr>
        <tr>
            <td>2</td>
            <td><a onclick="funcView('COMP002')">2024 전국체전</a></td>
            <td>2024.03.20 ~ 2024.03.22</td>
        </tr>
    </table>
    <ul class="pagination">
        <a href="#" onclick="funcPage(1)">1</a>
        <a href="#" onclick="funcPage(2)">2</a>
        <a href="#" onclick="funcPage(3)">3</a>
        <a href="#" class="last" onclick="funcPage(5)">마지막</a>
    </ul>
    """


@pytest.fixture
def competition_list_empty_html():
    """빈 대회 목록 HTML"""
    return """
    <table class="list">
        <tr><th>번호</th><th>대회명</th><th>기간</th></tr>
    </table>
    """


@pytest.fixture
def competition_list_malformed_html():
    """잘못된 형식의 대회 목록 HTML"""
    return """
    <table class="list">
        <tr><th>번호</th><th>대회명</th><th>기간</th></tr>
        <tr>
            <td>1</td>
            <td><a>대회명 없음</a></td>
            <!-- 날짜 컬럼 누락 -->
        </tr>
    </table>
    """


@pytest.fixture
def competition_single_date_html():
    """단일 날짜 대회 HTML"""
    return """
    <table class="list">
        <tr><th>번호</th><th>대회명</th><th>기간</th></tr>
        <tr>
            <td>1</td>
            <td><a onclick="funcView('COMP003')">원데이 대회</a></td>
            <td>2024.05.10</td>
        </tr>
    </table>
    """


# ============================================
# JSON Fixtures (API Responses)
# ============================================

@pytest.fixture
def events_json_response():
    """종목 목록 JSON 응답"""
    return [
        {
            "subEventCd": "EVT001",
            "subEventNm": "남자 플뢰레 개인전",
            "weapon": "플뢰레",
            "gender": "남자"
        },
        {
            "subEventCd": "EVT002",
            "subEventNm": "여자 에페 개인전",
            "weapon": "에페",
            "gender": "여자"
        }
    ]


@pytest.fixture
def players_json_response():
    """선수 목록 JSON 응답"""
    return [
        {
            "plyNm": "박소윤",
            "teamNm": "최병철펜싱클럽",
            "birthYear": 2010
        },
        {
            "plyNm": "김철수",
            "teamNm": "서울펜싱클럽",
            "birthYear": 2008
        },
        {
            "plyNm": "이영희",
            "teamNm": None,
            "birthYear": None
        }
    ]


@pytest.fixture
def matches_json_response():
    """경기 결과 JSON 응답"""
    return {
        "matchInfoList": [
            {
                "roundNm": "8강",
                "upPlyNm": "박소윤",
                "upScore": "15",
                "downPlyNm": "김철수",
                "downScore": "12",
                "winGbn": "V"
            },
            {
                "roundNm": "준결승",
                "upPlyNm": "이영희",
                "upScore": "10",
                "downPlyNm": "박소윤",
                "downScore": "15",
                "winGbn": "V"
            },
            {
                "roundNm": "결승",
                "upPlyNm": "박소윤",
                "upScore": None,
                "downPlyNm": "최강자",
                "downScore": None,
                "winGbn": "A"  # 기권
            }
        ]
    }


@pytest.fixture
def rankings_json_response():
    """최종 순위 JSON 응답"""
    return [
        {
            "rankNo": "1",
            "plyNm": "박소윤",
            "teamNm": "최병철펜싱클럽",
            "matchCnt": "5",
            "winCnt": "5",
            "lossCnt": "0"
        },
        {
            "rankNo": "2",
            "plyNm": "최강자",
            "teamNm": "인천펜싱클럽",
            "matchCnt": "4",
            "winCnt": "3",
            "lossCnt": "1"
        },
        {
            "rankNo": None,  # 순위 없음
            "plyNm": "탈락자",
            "teamNm": "서울펜싱클럽",
            "matchCnt": "1",
            "winCnt": "0",
            "lossCnt": "1"
        }
    ]


@pytest.fixture
def malformed_json_response():
    """잘못된 JSON 문자열"""
    return "{invalid json: missing quotes"


# ============================================
# Seeding Fixtures (DE Bracket)
# ============================================

@pytest.fixture
def seeding_14_players():
    """14명의 시딩 데이터"""
    return [
        {'seed': 1, 'name': '1번 시드', 'team': 'A팀', 'is_bye': False},
        {'seed': 2, 'name': '2번 시드', 'team': 'B팀', 'is_bye': False},
        {'seed': 3, 'name': '3번 시드', 'team': 'C팀', 'is_bye': False},
        {'seed': 4, 'name': '4번 시드', 'team': 'D팀', 'is_bye': False},
        {'seed': 5, 'name': '5번 시드', 'team': 'E팀', 'is_bye': False},
        {'seed': 6, 'name': '6번 시드', 'team': 'F팀', 'is_bye': False},
        {'seed': 7, 'name': '7번 시드', 'team': 'G팀', 'is_bye': False},
        {'seed': 8, 'name': '8번 시드', 'team': 'H팀', 'is_bye': False},
        {'seed': 9, 'name': '9번 시드', 'team': 'I팀', 'is_bye': False},
        {'seed': 10, 'name': '10번 시드', 'team': 'J팀', 'is_bye': False},
        {'seed': 11, 'name': '11번 시드', 'team': 'K팀', 'is_bye': False},
        {'seed': 12, 'name': '12번 시드', 'team': 'L팀', 'is_bye': False},
        {'seed': 13, 'name': '13번 시드', 'team': 'M팀', 'is_bye': False},
        {'seed': 14, 'name': '14번 시드', 'team': 'N팀', 'is_bye': False},
    ]


@pytest.fixture
def seeding_with_gaps():
    """시드 번호에 빈 구멍이 있는 데이터"""
    return [
        {'seed': 1, 'name': '1번 시드', 'team': 'A팀'},
        {'seed': 3, 'name': '3번 시드', 'team': 'C팀'},
        {'seed': 5, 'name': '5번 시드', 'team': 'E팀'},
        {'seed': 8, 'name': '8번 시드', 'team': 'H팀'},
    ]


@pytest.fixture
def existing_bouts_8():
    """기존 8강 경기 데이터"""
    return [
        {
            'bout_id': '8강_01',
            'round_name': '8강',
            'match_number': 1,
            'player1_seed': 1,
            'player1_name': '1번 시드',
            'player1_score': 15,
            'player2_seed': 8,
            'player2_name': '8번 시드',
            'player2_score': 10,
            'winner_seed': 1,
            'is_completed': True
        },
        {
            'bout_id': '8강_02',
            'round_name': '8강',
            'match_number': 2,
            'player1_seed': 4,
            'player1_name': '4번 시드',
            'player1_score': 15,
            'player2_seed': 5,
            'player2_name': '5번 시드',
            'player2_score': 12,
            'winner_seed': 4,
            'is_completed': True
        }
    ]


# ============================================
# Test Data: Date Ranges
# ============================================

@pytest.fixture
def date_range_test_cases():
    """날짜 범위 파싱 테스트 케이스"""
    return [
        # (input, expected_start, expected_end)
        ("2024.01.15 ~ 2024.01.17", date(2024, 1, 15), date(2024, 1, 17)),
        ("2024.03.01~2024.03.03", date(2024, 3, 1), date(2024, 3, 3)),
        ("2024.12.25", date(2024, 12, 25), date(2024, 12, 25)),
        ("2024.06.10 ~ 2024.06.10", date(2024, 6, 10), date(2024, 6, 10)),
        ("잘못된 날짜 형식", None, None),
        ("", None, None),
    ]


# ============================================
# Test Data: Event Code Extraction
# ============================================

@pytest.fixture
def event_code_test_cases():
    """이벤트 코드 추출 테스트 케이스"""
    return [
        # (onclick_string, expected_code)
        ("funcView('COMP001')", "COMP001"),
        ('funcView("COMP002")', "COMP002"),
        ("funcView(COMP003)", "COMP003"),
        ("funcView('2024ABC')", "2024ABC"),
        ("invalidFunction('COMP004')", ""),
        ("funcView()", ""),
        ("", ""),
    ]


# ============================================
# Test Data: Bracket Sizes
# ============================================

@pytest.fixture
def bracket_size_test_cases():
    """브라켓 크기 계산 테스트 케이스"""
    return [
        # (participant_count, expected_bracket_size)
        (1, 4),
        (3, 4),
        (4, 4),
        (5, 8),
        (8, 8),
        (9, 16),
        (14, 16),
        (16, 16),
        (17, 32),
        (30, 32),
        (32, 32),
        (33, 64),
        (60, 64),
        (64, 64),
        (65, 128),
        (100, 128),
        (128, 128),
        (129, 128),  # 최대 크기
    ]


# ============================================
# Test Data: Starting Rounds
# ============================================

@pytest.fixture
def starting_round_test_cases():
    """시작 라운드 결정 테스트 케이스"""
    return [
        # (bracket_size, expected_starting_round)
        (4, '준결승'),
        (8, '8강'),
        (16, '16강'),
        (32, '32강'),
        (64, '64강'),
        (128, '128강'),
        (999, '32강'),  # 잘못된 크기 → 기본값
    ]


# ============================================
# Error Response Fixtures
# ============================================

@pytest.fixture
def http_500_error_html():
    """500 Internal Server Error HTML"""
    return """
    <html>
        <head><title>500 Internal Server Error</title></head>
        <body><h1>Internal Server Error</h1></body>
    </html>
    """


@pytest.fixture
def http_404_error_html():
    """404 Not Found HTML"""
    return """
    <html>
        <head><title>404 Not Found</title></head>
        <body><h1>Page Not Found</h1></body>
    </html>
    """


@pytest.fixture
def timeout_error_response():
    """Timeout 에러 시뮬레이션용"""
    return None  # Used to trigger timeout in tests


# ============================================
# Pool Results Fixtures
# ============================================

@pytest.fixture
def pool_results_valid():
    """정상적인 풀 결과 데이터"""
    return {
        "pool_rounds": [
            {
                "round": 1,
                "bouts": [
                    {
                        "player1": "박소윤",
                        "player2": "김철수",
                        "score1": 5,
                        "score2": 3
                    }
                ]
            }
        ],
        "pool_total_ranking": [
            {"rank": 1, "name": "박소윤", "wins": 5, "losses": 0},
            {"rank": 2, "name": "김철수", "wins": 4, "losses": 1}
        ]
    }


@pytest.fixture
def pool_results_missing_scores():
    """점수가 없는 풀 결과"""
    return {
        "pool_rounds": [
            {
                "round": 1,
                "bouts": [
                    {
                        "player1": "박소윤",
                        "player2": "김철수",
                        "score1": None,
                        "score2": None
                    }
                ]
            }
        ]
    }


# ============================================
# DE Bracket Fixtures
# ============================================

@pytest.fixture
def de_bracket_valid():
    """정상적인 DE 브라켓 데이터"""
    return {
        "bracket_size": 16,
        "seeding": [
            {'seed': i, 'name': f'{i}번 시드', 'team': f'팀{i}'}
            for i in range(1, 17)
        ],
        "full_bouts": [
            {
                "round_name": "16강",
                "player1_seed": 1,
                "player2_seed": 16,
                "player1_score": 15,
                "player2_score": 10,
                "winner_seed": 1
            }
        ]
    }


@pytest.fixture
def de_bracket_incomplete():
    """불완전한 DE 브라켓 (full_bouts 없음)"""
    return {
        "bracket_size": 16,
        "seeding": [
            {'seed': i, 'name': f'{i}번 시드'}
            for i in range(1, 17)
        ],
        "full_bouts": []  # 경기 데이터 없음
    }
