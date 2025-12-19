"""
FencingLab 분석 엔진 테스트
"""

import pytest
import json
from pathlib import Path
from app.player_analytics import (
    FencingLabAnalyzer,
    MatchResult,
    PlayerAnalytics,
    get_analyzer,
    reload_analyzer
)


class TestMatchResult:
    """MatchResult 데이터클래스 테스트"""

    def test_match_result_creation(self):
        """MatchResult 객체 생성"""
        match = MatchResult(
            competition_name="테스트 대회",
            event_name="남자 플러레",
            round_name="32강전",
            opponent_name="상대",
            opponent_team="테스트팀",
            player_score=15,
            opponent_score=10,
            is_win=True,
            score_diff=5,
            is_de=True,
            date="2025-01-15"
        )
        assert match.player_score == 15
        assert match.is_win == True

    def test_clutch_match(self):
        """1점 차 접전 경기 판정"""
        match = MatchResult(
            competition_name="테스트",
            event_name="테스트",
            round_name="결승",
            opponent_name="상대",
            opponent_team="",
            player_score=15,
            opponent_score=14,
            is_win=True,
            score_diff=1,
            is_de=True
        )
        assert match.is_clutch == True
        assert match.is_blowout == False

    def test_blowout_match(self):
        """5점 이상 차이 경기 판정"""
        match = MatchResult(
            competition_name="테스트",
            event_name="테스트",
            round_name="32강",
            opponent_name="상대",
            opponent_team="",
            player_score=15,
            opponent_score=8,
            is_win=True,
            score_diff=7,
            is_de=True
        )
        assert match.is_clutch == False
        assert match.is_blowout == True

    def test_total_score(self):
        """총 득점 계산"""
        match = MatchResult(
            competition_name="테스트",
            event_name="테스트",
            round_name="16강",
            opponent_name="상대",
            opponent_team="",
            player_score=15,
            opponent_score=12,
            is_win=True,
            score_diff=3,
            is_de=True
        )
        assert match.total_score == 27


class TestPlayerAnalytics:
    """PlayerAnalytics 데이터클래스 테스트"""

    def test_analytics_creation(self):
        """PlayerAnalytics 기본 생성"""
        analytics = PlayerAnalytics(
            player_name="테스트선수",
            team="테스트팀"
        )
        assert analytics.player_name == "테스트선수"
        assert analytics.total_matches == 0
        assert analytics.win_rate == 0.0

    def test_analytics_to_dict(self):
        """딕셔너리 변환"""
        analytics = PlayerAnalytics(
            player_name="테스트선수",
            team="테스트팀",
            total_matches=10,
            win_rate=80.0
        )
        d = analytics.to_dict()
        assert isinstance(d, dict)
        assert d['player_name'] == "테스트선수"
        assert d['total_matches'] == 10


class TestFencingLabAnalyzer:
    """FencingLabAnalyzer 클래스 테스트"""

    @pytest.fixture
    def analyzer(self):
        """분석기 인스턴스"""
        return FencingLabAnalyzer("data/fencing_full_data_v3.json")

    def test_analyzer_initialization(self, analyzer):
        """분석기 초기화"""
        assert analyzer is not None
        assert analyzer.data is not None

    def test_get_club_players(self, analyzer):
        """클럽별 선수 목록 조회"""
        players = analyzer.get_club_players("최병철펜싱클럽")
        assert isinstance(players, list)
        # 최병철펜싱클럽 선수가 있으면 테스트
        if len(players) > 0:
            assert "박소윤" in players or "오주원" in players or "구지효" in players

    def test_is_allowed_player(self, analyzer):
        """허용된 클럽 선수 확인"""
        # 최병철펜싱클럽 선수가 있으면 테스트
        players = analyzer.get_club_players("최병철펜싱클럽")
        if len(players) > 0:
            assert analyzer.is_allowed_player(players[0]) == True

    def test_analyze_player_not_found(self, analyzer):
        """존재하지 않는 선수 분석"""
        result = analyzer.analyze_player("존재하지않는선수명12345")
        assert result is None

    def test_analyze_player_with_data(self, analyzer):
        """선수 분석 (데이터 있는 경우)"""
        # 최병철펜싱클럽 선수 중 데이터 있는 선수 찾기
        players = analyzer.get_club_players("최병철펜싱클럽")
        for player_name in players:
            result = analyzer.analyze_player(player_name, team_filter="최병철펜싱클럽")
            if result and result.total_matches > 0:
                assert result.player_name == player_name
                assert result.team == "최병철펜싱클럽"
                assert result.win_rate >= 0
                assert result.radar_attack >= 0
                assert result.radar_defense >= 0
                break

    def test_clutch_analysis(self, analyzer):
        """접전 분석 로직"""
        # 가상의 경기 데이터로 테스트
        from app.player_analytics import PlayerAnalytics

        analytics = PlayerAnalytics(player_name="테스트", team="테스트")

        # 강심장 케이스 (60% 이상)
        matches = [
            MatchResult("대회", "종목", "결승", "상대", "", 15, 14, True, 1, True),
            MatchResult("대회", "종목", "결승", "상대", "", 15, 14, True, 1, True),
            MatchResult("대회", "종목", "결승", "상대", "", 14, 15, False, -1, True),
        ]
        analyzer._analyze_clutch(analytics, matches)

        assert analytics.clutch_matches == 3
        assert analytics.clutch_wins == 2
        # 66.7%
        assert analytics.clutch_rate > 60
        assert analytics.clutch_grade == "강심장"

    def test_tempo_analysis(self, analyzer):
        """경기 템포 분석"""
        from app.player_analytics import PlayerAnalytics

        analytics = PlayerAnalytics(player_name="테스트", team="테스트")

        # 수비형 (총점수 낮음)
        de_matches = [
            MatchResult("대회", "종목", "32강", "상대", "", 5, 4, True, 1, True),
            MatchResult("대회", "종목", "16강", "상대", "", 6, 5, True, 1, True),
        ]
        analyzer._analyze_tempo(analytics, de_matches)

        assert analytics.avg_total_score < 20
        assert analytics.tempo_grade == "수비 마스터"

    def test_margin_analysis(self, analyzer):
        """점수 차 분석"""
        from app.player_analytics import PlayerAnalytics

        analytics = PlayerAnalytics(player_name="테스트", team="테스트")

        # 회복 탄력성 부족 (큰 점수 차 패배 많음)
        matches = [
            MatchResult("대회", "종목", "32강", "상대", "", 15, 10, True, 5, True),
            MatchResult("대회", "종목", "16강", "상대", "", 8, 15, False, -7, True),
            MatchResult("대회", "종목", "8강", "상대", "", 6, 15, False, -9, True),
        ]
        # total_losses 설정 (analyze_player에서 설정되는 값)
        analytics.total_losses = sum(1 for m in matches if not m.is_win)
        analyzer._analyze_margin(analytics, matches)

        assert analytics.blowout_losses == 2
        assert analytics.margin_grade == "회복 탄력성 부족"


class TestSingletonPattern:
    """싱글톤 패턴 테스트"""

    def test_get_analyzer_singleton(self):
        """싱글톤 인스턴스 반환"""
        analyzer1 = get_analyzer()
        analyzer2 = get_analyzer()
        assert analyzer1 is analyzer2

    def test_reload_analyzer(self):
        """분석기 리로드"""
        old_analyzer = get_analyzer()
        new_analyzer = reload_analyzer()
        assert old_analyzer is not new_analyzer


class TestRadarCalculation:
    """Radar Chart 계산 테스트"""

    def test_radar_values_range(self):
        """Radar 값 범위 (0-100)"""
        analyzer = FencingLabAnalyzer("data/fencing_full_data_v3.json")
        players = analyzer.get_club_players("최병철펜싱클럽")

        for player in players[:5]:  # 첫 5명만 테스트
            analytics = analyzer.analyze_player(player, team_filter="최병철펜싱클럽")
            if analytics and analytics.total_matches > 0:
                assert 0 <= analytics.radar_attack <= 100
                assert 0 <= analytics.radar_defense <= 100
                assert 0 <= analytics.radar_clutch <= 100
                assert 0 <= analytics.radar_resilience <= 100
                assert 0 <= analytics.radar_experience <= 100


# pytest 실행
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
