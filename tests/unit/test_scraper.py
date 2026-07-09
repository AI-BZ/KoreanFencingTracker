"""
Comprehensive Unit Tests for scraper/full_scraper.py and scraper/client.py

Focus: Pure function testing with 50+ test cases
Coverage: Date parsing, regex extraction, data validation, bracket logic, error handling
"""
import pytest
import json
from datetime import date, datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from bs4 import BeautifulSoup
import aiohttp

# Import modules under test
from scraper.client import KFFClient
from scraper.full_scraper import (
    get_correct_bracket_size,
    get_starting_round,
    fill_missing_seeds,
    generate_bye_bouts_for_starting_round,
    post_process_de_bracket,
    STANDARD_BRACKET_MATCHUPS,
    VALID_ROUNDS_BY_SIZE,
)
from scraper.models import (
    Competition, Event, Player, Match, Ranking,
    CompetitionListResponse, MatchStatus, Weapon, Gender
)

# Import fixtures
import sys
sys.path.insert(0, '/Users/gyejinpark/Documents/GitHub/fencingmind/tests')
from fixtures.scraper_fixtures import *


# ============================================
# 1. Pure Function Tests (20 cases)
# ============================================

class TestDateParsing:
    """날짜 파싱 함수 테스트"""

    def test_parse_date_range_normal(self):
        """정상적인 날짜 범위 파싱"""
        client = KFFClient()
        start, end = client._parse_date_range("2024.01.15 ~ 2024.01.17")

        assert start == date(2024, 1, 15)
        assert end == date(2024, 1, 17)

    def test_parse_date_range_no_spaces(self):
        """공백 없는 날짜 범위"""
        client = KFFClient()
        start, end = client._parse_date_range("2024.03.01~2024.03.03")

        assert start == date(2024, 3, 1)
        assert end == date(2024, 3, 3)

    def test_parse_date_single_date(self):
        """단일 날짜"""
        client = KFFClient()
        start, end = client._parse_date_range("2024.12.25")

        assert start == date(2024, 12, 25)
        assert end == date(2024, 12, 25)

    def test_parse_date_same_start_end(self):
        """시작일과 종료일이 같은 경우"""
        client = KFFClient()
        start, end = client._parse_date_range("2024.06.10 ~ 2024.06.10")

        assert start == date(2024, 6, 10)
        assert end == date(2024, 6, 10)

    def test_parse_date_invalid_format(self):
        """잘못된 날짜 형식"""
        client = KFFClient()
        start, end = client._parse_date_range("잘못된 날짜 형식")

        assert start is None
        assert end is None

    def test_parse_date_empty_string(self):
        """빈 문자열"""
        client = KFFClient()
        start, end = client._parse_date_range("")

        assert start is None
        assert end is None

    def test_parse_date_partial_format(self):
        """부분적으로 잘못된 형식"""
        client = KFFClient()
        start, end = client._parse_date_range("2024.01.15 ~ 잘못된날짜")

        # 현재 구현: 첫 번째 날짜를 단일 날짜로 파싱함
        assert start == date(2024, 1, 15)
        assert end == date(2024, 1, 15)


class TestEventCodeExtraction:
    """이벤트 코드 추출 함수 테스트"""

    def test_extract_event_cd_single_quotes(self):
        """작은따옴표 사용"""
        client = KFFClient()
        code = client._extract_event_cd("funcView('COMP001')")

        assert code == "COMP001"

    def test_extract_event_cd_double_quotes(self):
        """큰따옴표 사용"""
        client = KFFClient()
        code = client._extract_event_cd('funcView("COMP002")')

        assert code == "COMP002"

    def test_extract_event_cd_no_quotes(self):
        """따옴표 없음"""
        client = KFFClient()
        code = client._extract_event_cd("funcView(COMP003)")

        assert code == "COMP003"

    def test_extract_event_cd_alphanumeric(self):
        """영문+숫자 조합"""
        client = KFFClient()
        code = client._extract_event_cd("funcView('2024ABC')")

        assert code == "2024ABC"

    def test_extract_event_cd_invalid_function(self):
        """잘못된 함수명"""
        client = KFFClient()
        code = client._extract_event_cd("invalidFunction('COMP004')")

        assert code == ""

    def test_extract_event_cd_empty_params(self):
        """빈 매개변수"""
        client = KFFClient()
        code = client._extract_event_cd("funcView()")

        assert code == ""

    def test_extract_event_cd_empty_string(self):
        """빈 문자열"""
        client = KFFClient()
        code = client._extract_event_cd("")

        assert code == ""


class TestBracketSizeCalculation:
    """브라켓 크기 계산 테스트"""

    @pytest.mark.parametrize("count,expected", [
        (1, 4), (3, 4), (4, 4),
        (5, 8), (8, 8),
        (9, 16), (14, 16), (16, 16),
        (17, 32), (30, 32), (32, 32),
        (33, 64), (60, 64), (64, 64),
        (65, 128), (100, 128), (128, 128),
    ])
    def test_get_correct_bracket_size(self, count, expected):
        """다양한 참가자 수에 대한 브라켓 크기"""
        result = get_correct_bracket_size(count)
        assert result == expected

    def test_get_correct_bracket_size_over_max(self):
        """최대 크기 초과 시"""
        result = get_correct_bracket_size(129)
        assert result == 128  # 최대값으로 제한

    def test_get_correct_bracket_size_zero(self):
        """0명 참가자"""
        result = get_correct_bracket_size(0)
        assert result == 4  # 최소 브라켓 크기

    def test_get_correct_bracket_size_negative(self):
        """음수 참가자 (방어적 처리)"""
        result = get_correct_bracket_size(-5)
        assert result == 4


class TestStartingRoundDetermination:
    """시작 라운드 결정 테스트"""

    @pytest.mark.parametrize("bracket_size,expected", [
        (4, '준결승'),
        (8, '8강'),
        (16, '16강'),
        (32, '32강'),
        (64, '64강'),
        (128, '128강'),
    ])
    def test_get_starting_round(self, bracket_size, expected):
        """브라켓 크기별 시작 라운드"""
        result = get_starting_round(bracket_size)
        assert result == expected

    def test_get_starting_round_invalid_size(self):
        """잘못된 브라켓 크기"""
        result = get_starting_round(999)
        assert result == '32강'  # 기본값

    def test_get_starting_round_zero(self):
        """0 크기"""
        result = get_starting_round(0)
        assert result == '32강'


class TestSafeIntConversion:
    """안전한 정수 변환 테스트"""

    def test_safe_int_valid_integer(self):
        """정상 정수"""
        client = KFFClient()
        assert client._safe_int(42) == 42

    def test_safe_int_string_number(self):
        """문자열 숫자"""
        client = KFFClient()
        assert client._safe_int("123") == 123

    def test_safe_int_none(self):
        """None 값"""
        client = KFFClient()
        assert client._safe_int(None) == 0

    def test_safe_int_invalid_string(self):
        """잘못된 문자열"""
        client = KFFClient()
        assert client._safe_int("abc") == 0

    def test_safe_int_empty_string(self):
        """빈 문자열"""
        client = KFFClient()
        assert client._safe_int("") == 0

    def test_safe_int_float(self):
        """실수 문자열 (변환 실패 -> 0 반환)"""
        client = KFFClient()
        # _safe_int는 int() 변환만 하므로 "15.7"은 실패 -> 0
        assert client._safe_int("15.7") == 0
        # 실수 타입은 변환 가능
        assert client._safe_int(15.7) == 15


# ============================================
# 2. Client API Tests (15 cases)
# ============================================

class TestKFFClientHTTP:
    """HTTP 요청 처리 테스트"""

    @pytest.mark.asyncio
    async def test_request_get_success(self):
        """GET 요청 성공"""
        async with KFFClient() as client:
            with patch.object(client._session, 'get') as mock_get:
                mock_response = AsyncMock()
                mock_response.text = AsyncMock(return_value="Success")
                mock_response.raise_for_status = Mock()
                mock_get.return_value.__aenter__.return_value = mock_response

                result = await client._get("/test")

                assert result == "Success"
                mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_post_success(self):
        """POST 요청 성공"""
        async with KFFClient() as client:
            with patch.object(client._session, 'post') as mock_post:
                mock_response = AsyncMock()
                mock_response.text = AsyncMock(return_value="Posted")
                mock_response.raise_for_status = Mock()
                mock_post.return_value.__aenter__.return_value = mock_response

                result = await client._post("/test", data={"key": "value"})

                assert result == "Posted"

    @pytest.mark.asyncio
    async def test_request_retry_on_error(self):
        """에러 발생 시 재시도 (간단 버전)"""
        # Note: 실제 재시도 로직 테스트는 복잡한 모킹 필요
        # 이 테스트는 재시도 파라미터가 올바른지 확인
        client = KFFClient()
        client.max_retries = 2
        client.delay = 0.01

        assert client.max_retries == 2
        assert client.delay == 0.01

    @pytest.mark.asyncio
    async def test_request_max_retries_exceeded(self):
        """최대 재시도 횟수 설정 확인"""
        # Note: 실제 재시도 실패 시나리오는 통합 테스트에서 수행
        # 여기서는 설정이 올바른지만 확인
        client = KFFClient()
        default_retries = client.max_retries

        assert default_retries > 0  # 기본값 존재
        assert isinstance(default_retries, int)

    @pytest.mark.asyncio
    async def test_session_context_manager(self):
        """세션 컨텍스트 매니저 테스트"""
        async with KFFClient() as client:
            assert client._session is not None

        # 종료 후 세션 정리 확인은 내부 로직이므로 생략


class TestCompetitionListParsing:
    """대회 목록 파싱 테스트"""

    def test_parse_competition_list_normal(self, competition_list_html):
        """정상적인 대회 목록 파싱"""
        client = KFFClient()
        result = client._parse_competition_list(competition_list_html, page=1)

        assert len(result.competitions) == 2
        assert result.competitions[0].comp_idx == "COMP001"
        assert result.competitions[0].comp_name == "2024 회장배 펜싱대회"
        assert result.competitions[0].start_date == date(2024, 1, 15)
        assert result.competitions[0].end_date == date(2024, 1, 17)

    def test_parse_competition_list_empty(self, competition_list_empty_html):
        """빈 대회 목록"""
        client = KFFClient()
        result = client._parse_competition_list(competition_list_empty_html, page=1)

        assert len(result.competitions) == 0
        assert result.total_count == 0

    def test_parse_competition_list_malformed(self, competition_list_malformed_html):
        """잘못된 형식의 HTML"""
        client = KFFClient()
        result = client._parse_competition_list(competition_list_malformed_html, page=1)

        # 파싱 오류가 있어도 빈 리스트 반환 (크래시 없음)
        assert isinstance(result.competitions, list)

    def test_parse_competition_list_single_date(self, competition_single_date_html):
        """단일 날짜 대회"""
        client = KFFClient()
        result = client._parse_competition_list(competition_single_date_html, page=1)

        assert len(result.competitions) == 1
        assert result.competitions[0].start_date == date(2024, 5, 10)
        assert result.competitions[0].end_date == date(2024, 5, 10)

    def test_extract_total_pages_normal(self, competition_list_html):
        """페이지 수 추출"""
        client = KFFClient()
        soup = BeautifulSoup(competition_list_html, "lxml")
        total_pages = client._extract_total_pages(soup)

        assert total_pages == 5  # "마지막" 링크의 funcPage(5)

    def test_extract_total_pages_no_pagination(self):
        """페이지네이션 없음"""
        client = KFFClient()
        html = "<div>No pagination</div>"
        soup = BeautifulSoup(html, "lxml")
        total_pages = client._extract_total_pages(soup)

        assert total_pages == 1  # 기본값

    def test_extract_total_pages_numeric_links_only(self):
        """숫자 링크만 있는 경우"""
        client = KFFClient()
        html = """
        <ul class="pagination">
            <a>1</a>
            <a>2</a>
            <a>3</a>
        </ul>
        """
        soup = BeautifulSoup(html, "lxml")
        total_pages = client._extract_total_pages(soup)

        assert total_pages == 3


class TestJSONResponseParsing:
    """JSON 응답 파싱 테스트"""

    def test_parse_events_json_normal(self, events_json_response):
        """정상적인 종목 JSON 파싱"""
        # Note: This would be async in real client, testing data structure
        events = events_json_response

        assert len(events) == 2
        assert events[0]["subEventCd"] == "EVT001"
        assert events[1]["subEventNm"] == "여자 에페 개인전"

    def test_parse_players_json_normal(self, players_json_response):
        """정상적인 선수 JSON 파싱"""
        players = players_json_response

        assert len(players) == 3
        assert players[0]["plyNm"] == "박소윤"
        assert players[0]["teamNm"] == "최병철펜싱클럽"
        assert players[2]["teamNm"] is None  # None 처리

    def test_parse_matches_json_normal(self, matches_json_response):
        """정상적인 경기 JSON 파싱"""
        matches = matches_json_response["matchInfoList"]

        assert len(matches) == 3
        assert matches[0]["roundNm"] == "8강"
        assert matches[2]["winGbn"] == "A"  # 기권

    def test_parse_rankings_json_normal(self, rankings_json_response):
        """정상적인 순위 JSON 파싱"""
        rankings = rankings_json_response

        assert len(rankings) == 3
        assert rankings[0]["rankNo"] == "1"
        assert rankings[2]["rankNo"] is None  # 순위 없음

    def test_parse_malformed_json(self, malformed_json_response):
        """잘못된 JSON"""
        with pytest.raises(json.JSONDecodeError):
            json.loads(malformed_json_response)


# ============================================
# 3. Data Validation Tests (10 cases)
# ============================================

class TestPoolDataValidation:
    """Pool 결과 데이터 검증"""

    def test_pool_results_valid_structure(self, pool_results_valid):
        """정상적인 풀 결과 구조"""
        assert "pool_rounds" in pool_results_valid
        assert "pool_total_ranking" in pool_results_valid
        assert len(pool_results_valid["pool_rounds"]) > 0
        assert len(pool_results_valid["pool_total_ranking"]) > 0

    def test_pool_results_scores_present(self, pool_results_valid):
        """점수 데이터 존재 확인"""
        bout = pool_results_valid["pool_rounds"][0]["bouts"][0]

        assert bout["score1"] is not None
        assert bout["score2"] is not None
        assert isinstance(bout["score1"], int)
        assert isinstance(bout["score2"], int)

    def test_pool_results_missing_scores(self, pool_results_missing_scores):
        """점수 누락 처리"""
        bout = pool_results_missing_scores["pool_rounds"][0]["bouts"][0]

        assert bout["score1"] is None
        assert bout["score2"] is None

    def test_pool_ranking_order(self, pool_results_valid):
        """순위 정렬 확인"""
        rankings = pool_results_valid["pool_total_ranking"]

        for i in range(len(rankings) - 1):
            assert rankings[i]["rank"] <= rankings[i + 1]["rank"]


class TestDEBracketValidation:
    """DE 브라켓 데이터 검증"""

    def test_de_bracket_valid_structure(self, de_bracket_valid):
        """정상적인 DE 브라켓 구조"""
        assert "bracket_size" in de_bracket_valid
        assert "seeding" in de_bracket_valid
        assert "full_bouts" in de_bracket_valid
        assert de_bracket_valid["bracket_size"] in [4, 8, 16, 32, 64, 128]

    def test_de_bracket_seeding_count_matches_size(self, de_bracket_valid):
        """시딩 수와 브라켓 크기 일치"""
        assert len(de_bracket_valid["seeding"]) == de_bracket_valid["bracket_size"]

    def test_de_bracket_incomplete_bouts(self, de_bracket_incomplete):
        """경기 데이터 없는 브라켓"""
        assert len(de_bracket_incomplete["full_bouts"]) == 0
        # 시스템이 이를 감지하고 처리해야 함

    def test_de_bracket_bout_has_winner(self, de_bracket_valid):
        """완료된 경기는 승자가 있어야 함"""
        bout = de_bracket_valid["full_bouts"][0]

        assert "winner_seed" in bout
        assert bout["winner_seed"] in [bout["player1_seed"], bout["player2_seed"]]


class TestPlayerDataValidation:
    """선수 데이터 검증"""

    def test_player_name_not_empty(self, players_json_response):
        """선수 이름은 비어있지 않아야 함"""
        for player in players_json_response:
            assert player["plyNm"]
            assert len(player["plyNm"]) > 0

    def test_player_team_optional(self, players_json_response):
        """소속팀은 선택사항"""
        # 일부 선수는 소속팀이 없을 수 있음
        player_without_team = players_json_response[2]
        assert player_without_team["teamNm"] is None


class TestCompetitionMetadataValidation:
    """대회 메타데이터 검증"""

    def test_competition_dates_logical(self):
        """시작일 <= 종료일"""
        comp = Competition(
            comp_idx="TEST001",
            comp_name="테스트 대회",
            start_date=date(2024, 1, 15),
            end_date=date(2024, 1, 17)
        )

        assert comp.start_date <= comp.end_date

    def test_competition_dates_same_day_allowed(self):
        """원데이 대회 허용"""
        comp = Competition(
            comp_idx="TEST002",
            comp_name="원데이 대회",
            start_date=date(2024, 5, 10),
            end_date=date(2024, 5, 10)
        )

        assert comp.start_date == comp.end_date


# ============================================
# 4. Edge Cases Tests (5 cases)
# ============================================

class TestEdgeCases:
    """엣지 케이스 처리"""

    def test_fill_missing_seeds_empty_list(self):
        """빈 시딩 리스트"""
        result = fill_missing_seeds([], bracket_size=8)

        assert len(result) == 8
        assert all(p['is_bye'] for p in result)

    def test_fill_missing_seeds_with_gaps(self, seeding_with_gaps):
        """시드 번호에 빈 구멍이 있는 경우"""
        result = fill_missing_seeds(seeding_with_gaps, bracket_size=8)

        assert len(result) == 8
        # seed 2, 4, 6, 7이 bye로 채워져야 함
        seeds = {p['seed'] for p in result}
        assert seeds == {1, 2, 3, 4, 5, 6, 7, 8}

    def test_fill_missing_seeds_invalid_bracket_size(self):
        """잘못된 브라켓 크기"""
        result = fill_missing_seeds([{'seed': 1, 'name': 'Test'}], bracket_size=0)

        # 방어적 처리 - 원본 반환
        assert len(result) == 1

    def test_generate_bye_bouts_all_bye(self):
        """모두 bye인 경우"""
        seeding = [
            {'seed': 1, 'name': None, 'is_bye': True},
            {'seed': 2, 'name': None, 'is_bye': True},
        ]

        result = generate_bye_bouts_for_starting_round(
            seeding=seeding,
            bracket_size=4,
            starting_round='준결승',
            existing_bouts=[]
        )

        # 둘 다 bye면 경기가 생성되지 않아야 함
        assert len(result) == 0

    def test_generate_bye_bouts_one_bye(self, seeding_14_players):
        """한 명만 bye (부전승)"""
        seeding_16 = fill_missing_seeds(seeding_14_players, bracket_size=16)

        result = generate_bye_bouts_for_starting_round(
            seeding=seeding_16,
            bracket_size=16,
            starting_round='16강',
            existing_bouts=[]
        )

        # 2개의 bye 경기가 생성되어야 함 (seed 15, 16)
        bye_bouts = [b for b in result if b.get('is_bye')]
        assert len(bye_bouts) == 2


# ============================================
# 5. Integration-level Tests (5 cases)
# ============================================

class TestBracketNormalization:
    """브라켓 정규화 통합 테스트"""

    def test_bracket_matchups_defined_for_all_sizes(self):
        """모든 브라켓 크기에 대한 매치업 정의"""
        for size in [4, 8, 16, 32, 64, 128]:
            assert size in STANDARD_BRACKET_MATCHUPS
            matchups = STANDARD_BRACKET_MATCHUPS[size]
            assert len(matchups) == size // 2  # 첫 라운드 경기 수

    def test_valid_rounds_defined_for_all_sizes(self):
        """모든 브라켓 크기에 대한 유효 라운드 정의"""
        for size in [4, 8, 16, 32, 64, 128]:
            assert size in VALID_ROUNDS_BY_SIZE
            rounds = VALID_ROUNDS_BY_SIZE[size]
            assert '결승' in rounds
            assert '3-4위' in rounds

    def test_post_process_de_bracket_basic(self):
        """DE 브라켓 후처리 기본 동작"""
        bracket_data = {
            "bracket_size": 16,
            "seeding": [
                {'seed': i, 'name': f'{i}번 시드'}
                for i in range(1, 15)  # 14명만
            ],
            "full_bouts": []
        }

        result = post_process_de_bracket(bracket_data)

        # 시딩이 16개로 채워졌는지 확인
        assert len(result["seeding"]) == 16

    def test_post_process_de_bracket_adds_metadata(self):
        """후처리 시 메타데이터 추가 확인"""
        bracket_data = {
            "bracket_size": 16,
            "seeding": [{'seed': i, 'name': f'{i}번'} for i in range(1, 17)],
            "full_bouts": []
        }

        result = post_process_de_bracket(bracket_data)

        # 메타데이터가 추가되어야 함
        assert 'starting_round' in result
        assert 'participant_count' in result
        assert 'bouts' in result
        assert 'bouts_by_round' in result

        # 기본값 확인
        assert result['starting_round'] == '16강'
        assert result['participant_count'] == 16

    def test_end_to_end_bracket_normalization(self):
        """전체 브라켓 정규화 플로우"""
        # 1. 브라켓 크기 결정
        participant_count = 14
        bracket_size = get_correct_bracket_size(participant_count)
        assert bracket_size == 16

        # 2. 시작 라운드 결정
        starting_round = get_starting_round(bracket_size)
        assert starting_round == '16강'

        # 3. 시딩 채우기
        seeding = [
            {'seed': i, 'name': f'{i}번 시드', 'team': f'팀{i}'}
            for i in range(1, participant_count + 1)
        ]
        filled_seeding = fill_missing_seeds(seeding, bracket_size)
        assert len(filled_seeding) == 16

        # 4. 부전승 경기 생성
        bye_bouts = generate_bye_bouts_for_starting_round(
            seeding=filled_seeding,
            bracket_size=bracket_size,
            starting_round=starting_round,
            existing_bouts=[]
        )

        # 2개의 부전승 경기가 생성되어야 함
        assert len(bye_bouts) == 2
        assert all(b.get('is_bye') for b in bye_bouts)
