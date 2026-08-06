"""
FencingLab - 선수 경기 분석 엔진 v3
실제 데이터 기반 분석 (가상 지표 제거)
동명이인 구분: 이름|팀 조합으로 선수 식별

분석 가능 항목:
- Pool (5점제) 승률
- DE (15점제) 승률
- 접전 승률 (1점차 경기: 5:4, 15:14)
- 경기 종료 유형별 승률 (풀스코어 vs 시간종료)
- 평균 점수차
"""

from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from loguru import logger


# i18n translations for analytics
ANALYTICS_TRANSLATIONS = {
    "ko": {
        # Clutch grades
        "grade_strong": "강심장",
        "grade_average": "평균",
        "grade_weak": "접전 취약",
        "grade_insufficient": "데이터 부족",
        # Clutch insights
        "clutch_strong": "1점차 접전에서 {wins}승 {losses}패. 승부처에서 강합니다.",
        "clutch_average": "1점차 접전에서 {wins}승 {losses}패. 평균적인 성과입니다.",
        "clutch_weak": "1점차 접전에서 {wins}승 {losses}패. 접전에서 불안한 경향이 있습니다.",
        "clutch_insufficient": "1점차 접전 경기가 {matches}회로 분석에 부족합니다.",
        # Finish type insights
        "fullscore_strong": "풀스코어 경기에서 {diff}%p 더 강합니다. 빠른 득점에 강점이 있습니다.",
        "timeout_strong": "시간종료 경기에서 {diff}%p 더 강합니다. 경기 운영 능력이 좋습니다.",
        "finish_balanced": "종료 유형에 따른 승률 차이가 크지 않습니다.",
        "timeout_occurred": "시간종료 경기 {matches}회 발생",
        "mostly_fullscore": "대부분 목표점 도달로 경기 종료",
    },
    "en": {
        # Clutch grades
        "grade_strong": "Clutch",
        "grade_average": "Average",
        "grade_weak": "Struggles",
        "grade_insufficient": "Insufficient Data",
        # Clutch insights
        "clutch_strong": "{wins}W {losses}L in 1-point games. Strong under pressure.",
        "clutch_average": "{wins}W {losses}L in 1-point games. Average performance.",
        "clutch_weak": "{wins}W {losses}L in 1-point games. Tends to struggle in close matches.",
        "clutch_insufficient": "Only {matches} close matches. Insufficient for analysis.",
        # Finish type insights
        "fullscore_strong": "{diff}%p stronger in full-score games. Strong at quick scoring.",
        "timeout_strong": "{diff}%p stronger in timeout games. Good at match management.",
        "finish_balanced": "No significant difference by match ending type.",
        "timeout_occurred": "{matches} timeout games occurred",
        "mostly_fullscore": "Most matches ended at target score",
    }
}


def get_analytics_text(key: str, lang: str = "ko", **kwargs) -> str:
    """Get translated analytics text"""
    translations = ANALYTICS_TRANSLATIONS.get(lang, ANALYTICS_TRANSLATIONS["ko"])
    text = translations.get(key, ANALYTICS_TRANSLATIONS["ko"].get(key, key))
    return text.format(**kwargs) if kwargs else text


def make_player_key(name: str, team: str) -> str:
    """선수 고유 키 생성 (이름|팀)"""
    return f"{name}|{team}"


def parse_player_key(key: str) -> Tuple[str, str]:
    """선수 키에서 이름과 팀 분리"""
    if "|" in key:
        parts = key.split("|", 1)
        return parts[0], parts[1]
    return key, ""


@dataclass
class MatchResult:
    """개별 경기 결과"""
    competition_name: str
    event_name: str
    round_name: str  # "Pool 1", "32강전", "결승전" 등
    opponent_name: str
    opponent_team: str
    # 부전승·기권·미완료 경기는 점수가 없을 수 있다 (None)
    player_score: Optional[int]
    opponent_score: Optional[int]
    is_win: bool
    is_pool: bool  # Pool(5점제) vs DE(15점제)
    date: str = ""
    event_cd: str = ""  # 이벤트 페이지 링크용

    @property
    def has_scores(self) -> bool:
        """점수가 기록된 경기인지 (점수 기반 분석 대상 여부)"""
        return self.player_score is not None and self.opponent_score is not None

    @property
    def score_diff(self) -> Optional[int]:
        """점수차 (양수=승리, 음수=패배). 점수 미기록 시 None"""
        if not self.has_scores:
            return None
        return self.player_score - self.opponent_score

    @property
    def score_display(self) -> str:
        """표시용 점수 문자열. 점수 미기록 시 '-'"""
        if not self.has_scores:
            return "-"
        return f"{self.player_score}:{self.opponent_score}"

    @property
    def is_clutch(self) -> bool:
        """1점 차 접전 경기인지 (점수를 모르면 접전으로 세지 않음)"""
        diff = self.score_diff
        return diff is not None and abs(diff) == 1

    @property
    def is_timeout(self) -> bool:
        """시간종료 경기인지 (목표점 미도달: Pool 5점, DE 15점)"""
        if not self.has_scores:
            return False
        max_score = 5 if self.is_pool else 15
        return max(self.player_score, self.opponent_score) < max_score

    @property
    def is_fullscore(self) -> bool:
        """풀스코어 경기인지 (목표점 도달: Pool 5점, DE 15점)"""
        if not self.has_scores:
            return False
        max_score = 5 if self.is_pool else 15
        return max(self.player_score, self.opponent_score) >= max_score


@dataclass
class PlayerAnalytics:
    """선수 분석 결과 - 실제 데이터 기반"""
    player_name: str
    team: str

    # 전체 통계
    total_matches: int = 0
    total_wins: int = 0
    total_losses: int = 0
    win_rate: float = 0.0

    # Pool (5점제) 통계
    pool_matches: int = 0
    pool_wins: int = 0
    pool_losses: int = 0
    pool_win_rate: float = 0.0

    # DE (15점제) 통계
    de_matches: int = 0
    de_wins: int = 0
    de_losses: int = 0
    de_win_rate: float = 0.0

    # 접전 분석 (1점차 경기)
    clutch_matches: int = 0
    clutch_wins: int = 0
    clutch_losses: int = 0
    clutch_rate: float = 0.0  # 접전 승률
    clutch_grade: str = ""
    clutch_insight: str = ""

    # 경기 종료 유형 분석 (풀스코어 vs 시간종료)
    fullscore_matches: int = 0  # 목표점 도달 경기 (5점/15점)
    fullscore_wins: int = 0
    fullscore_win_rate: float = 0.0
    timeout_matches: int = 0  # 시간종료 경기 (목표점 미도달)
    timeout_wins: int = 0
    timeout_win_rate: float = 0.0
    finish_type_insight: str = ""  # 종료 유형별 분석 인사이트

    # 점수차 분석
    avg_win_margin: float = 0.0  # 승리 시 평균 점수차
    avg_loss_margin: float = 0.0  # 패배 시 평균 점수차
    blowout_wins: int = 0  # 압승 (3점차 이상)
    blowout_losses: int = 0  # 완패 (3점차 이상)

    # 최근 경기
    recent_matches: list = field(default_factory=list)

    # 최근 6경기 분석
    recent_6_matches: list = field(default_factory=list)
    recent_6_win_rate: float = 0.0
    recent_6_wins: int = 0
    recent_6_losses: int = 0
    recent_6_trend: str = ""  # "상승", "하락", "유지"

    # 월별 히스토리 (그래프용)
    match_history: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


class FencingLabAnalyzer:
    """FencingLab 분석 엔진 v3 - 동명이인 구분 지원"""

    ALLOWED_CLUBS = ["최병철펜싱클럽"]  # 허용된 클럽 목록

    # 최병철펜싱클럽 산하로 관리되는 외부 소속 선수들
    # {현재소속(실제 데이터 팀명 포함): [선수이름, ...]}
    AFFILIATED_PLAYERS = {
        "성남펜싱아카데미": ["이홍"],
        "광주시G-스포츠클럽": ["한지우"],
        "이지펜싱클럽": ["김시연"],  # 동명이인 있음 (중경고, 은성중)
        "엔티언 펜싱클럽 김포": ["박민지"],  # 동명이인 있음 (경남대, 전남여고)
        "하이브 펜싱클럽": ["박보경"],
        "스킬펜싱클럽": ["한지호"],
        "라피크엔시스": ["오시울"],
        "엔티언펜싱클럽": ["한준열"],
    }

    def __init__(self, data: Optional[Dict] = None):
        """FencingLab 분석기 초기화

        Args:
            data: 대회 데이터 딕셔너리 (Supabase 캐시에서 전달)
                  None인 경우 서버의 _data_cache 사용
        """
        self.data = data
        # 키: "이름|팀" 형태로 동명이인 구분
        self.player_matches: Dict[str, List[MatchResult]] = defaultdict(list)
        # 이름 -> [팀1, 팀2, ...] (동명이인 조회용)
        self.name_to_teams: Dict[str, set] = defaultdict(set)
        self._load_data()

    def is_allowed_player(self, player_name: str, team: str) -> bool:
        """허용된 클럽 소속 선수인지 확인"""
        # 허용된 클럽 소속인지 확인
        if any(club in team for club in self.ALLOWED_CLUBS):
            return True

        # 산하 관리 선수인지 확인
        for affiliated_team, players in self.AFFILIATED_PLAYERS.items():
            if affiliated_team in team and player_name in players:
                return True

        return False

    def get_all_tracked_players(self) -> Dict[str, List[Dict[str, str]]]:
        """모든 추적 대상 선수를 소속별로 반환

        Returns:
            {소속명: [{name, team}, ...], ...}
        """
        result = {}

        # 최병철펜싱클럽 선수들
        for club in self.ALLOWED_CLUBS:
            club_players = self.get_club_players(club)
            if club_players:
                result[club] = club_players

        # 산하 관리 선수들
        for affiliated_team, player_names in self.AFFILIATED_PLAYERS.items():
            affiliated_list = []
            for player_name in player_names:
                # 해당 선수의 실제 팀 정보 찾기
                teams = self.get_teams_for_name(player_name)
                for team in teams:
                    if affiliated_team in team:
                        affiliated_list.append({"name": player_name, "team": team})
                        break
                else:
                    # 팀 정보를 찾지 못한 경우 지정된 소속 사용
                    affiliated_list.append({"name": player_name, "team": affiliated_team})

            if affiliated_list:
                result[affiliated_team] = affiliated_list

        return result

    def get_teams_for_name(self, player_name: str) -> List[str]:
        """이름에 해당하는 모든 팀 목록 반환 (동명이인 조회)"""
        return sorted(list(self.name_to_teams.get(player_name, set())))

    def has_homonym(self, player_name: str) -> bool:
        """동명이인이 있는지 확인"""
        teams = self.name_to_teams.get(player_name, set())
        return len(teams) > 1

    def _load_data(self):
        """데이터 로드 및 선수별 경기 인덱싱

        🚨 NOTE: JSON 파일 로드 제거됨 (2025-12-22)
        이제 서버의 Supabase 캐시에서 데이터를 전달받습니다.
        """
        # 데이터가 None이면 서버 캐시에서 가져옴
        if self.data is None:
            try:
                from app.server import _data_cache
                self.data = _data_cache if _data_cache else {"competitions": []}
            except ImportError:
                logger.warning("서버 캐시를 가져올 수 없음")
                self.data = {"competitions": []}

        if not self.data or not self.data.get("competitions"):
            logger.warning("FencingLab: 데이터 없음")
            self.data = {"competitions": []}
            return

        self._index_all_matches()

        # 통계 계산
        unique_players = len(self.player_matches)
        unique_names = len(self.name_to_teams)
        homonyms = sum(1 for teams in self.name_to_teams.values() if len(teams) > 1)

        logger.info(f"FencingLab 데이터 로드 완료: {unique_players}명 (동명이인: {homonyms}건)")

    def _index_all_matches(self):
        """선수별 모든 경기 기록 인덱싱 (Pool + DE)"""
        for comp in self.data.get("competitions", []):
            comp_info = comp.get("competition", {})
            comp_name = comp_info.get("name", "")
            comp_date = comp_info.get("start_date", "")

            for event in comp.get("events", []):
                event_name = event.get("name", "")
                event_cd = event.get("event_cd", "")

                # Pool 경기 파싱
                self._parse_pool_rounds(
                    event.get("pool_rounds", []),
                    comp_name, event_name, comp_date, event_cd
                )

                # DE 경기 파싱 (기존 방식 - 승자만)
                self._parse_de_matches(
                    event.get("de_matches", []),
                    comp_name, event_name, comp_date, event_cd
                )

                # DE 경기 파싱 (신규 방식 - 승자+패자 모두)
                de_bracket = event.get("de_bracket", {})
                if isinstance(de_bracket, dict):
                    full_bouts = de_bracket.get("full_bouts", [])
                    bouts_by_round = de_bracket.get("bouts_by_round", {})

                    if full_bouts:
                        # 1순위: full_bouts (가장 정확한 형식)
                        self._parse_full_bouts(full_bouts, comp_name, event_name, comp_date, event_cd)
                    elif bouts_by_round and isinstance(bouts_by_round, dict) and len(bouts_by_round) > 0:
                        # 2순위: bouts_by_round (full_bouts 없을 때 대체)
                        self._parse_bouts_by_round(bouts_by_round, comp_name, event_name, comp_date, event_cd)

                # final_rankings에서도 선수 팀 정보 추출
                for r in event.get("final_rankings", []):
                    player_name = r.get("name", "")
                    team = r.get("team", "")
                    if player_name and team:
                        self.name_to_teams[player_name].add(team)

    def _add_player_match(self, player_name: str, player_team: str, match: MatchResult):
        """선수 경기 기록 추가 (이름|팀 키 사용)"""
        if not player_name or not player_team:
            return

        player_key = make_player_key(player_name, player_team)
        self.player_matches[player_key].append(match)
        self.name_to_teams[player_name].add(player_team)

    def _parse_pool_rounds(self, pool_rounds: list, comp_name: str, event_name: str, comp_date: str, event_cd: str = ""):
        """Pool 라운드에서 개별 경기 추출"""
        for pool_round in pool_rounds:
            round_num = pool_round.get("round_number", 1)
            pool_num = pool_round.get("pool_number", 1)
            round_name = f"Pool {pool_num}" if round_num == 1 else f"Pool {round_num}-{pool_num}"

            results = pool_round.get("results", [])

            # 같은 풀의 모든 선수 정보 수집
            players_in_pool = []
            for r in results:
                players_in_pool.append({
                    "name": r.get("name", ""),
                    "team": r.get("team", ""),
                    "scores": r.get("scores", [])
                })

            # 각 선수의 경기 기록 추출
            for i, player_data in enumerate(players_in_pool):
                player_name = player_data["name"]
                player_team = player_data["team"]

                if not player_name or not player_team:
                    continue

                scores = player_data["scores"]

                # scores 배열에서 상대방과의 경기 추출
                for j, score_data in enumerate(scores):
                    if score_data is None or score_data == "" or j >= len(players_in_pool):
                        continue  # 자기 자신과의 경기 또는 빈 값

                    opponent_data = players_in_pool[j]
                    if opponent_data["name"] == player_name and opponent_data["team"] == player_team:
                        continue

                    # score_data가 dict인 경우 (구 형식)
                    if isinstance(score_data, dict):
                        match_type = score_data.get("type", "")
                        player_score = score_data.get("score", 0)
                    # score_data가 str인 경우 (익산 등 신규 형식)
                    else:
                        score_str = str(score_data).strip()
                        if score_str.upper() == "V":
                            match_type = "V"
                            player_score = 5  # 기본 승리 점수
                        elif score_str.isdigit():
                            match_type = "D"
                            player_score = int(score_str)
                        else:
                            continue  # 알 수 없는 형식

                    # 상대방 점수 추론
                    opponent_score = self._get_opponent_score(opponent_data["scores"], i)

                    if match_type and player_name:
                        match = MatchResult(
                            competition_name=comp_name,
                            event_name=event_name,
                            round_name=round_name,
                            opponent_name=opponent_data["name"],
                            opponent_team=opponent_data["team"],
                            player_score=player_score,
                            opponent_score=opponent_score,
                            is_win=(match_type == "V"),
                            is_pool=True,
                            date=comp_date,
                            event_cd=event_cd
                        )
                        self._add_player_match(player_name, player_team, match)

    def _get_opponent_score(self, opponent_scores: list, player_index: int) -> int:
        """상대방의 점수 배열에서 해당 선수와의 경기 점수 추출"""
        if player_index < len(opponent_scores) and opponent_scores[player_index]:
            score_data = opponent_scores[player_index]
            # dict 형식 (구 형식)
            if isinstance(score_data, dict):
                return score_data.get("score", 0)
            # str 형식 (익산 등 신규 형식)
            else:
                score_str = str(score_data).strip()
                if score_str.upper() == "V":
                    return 5  # 기본 승리 점수
                elif score_str.isdigit():
                    return int(score_str)
        return 0

    def _parse_full_bouts(self, full_bouts: list, comp_name: str, event_name: str, comp_date: str, event_cd: str = ""):
        """DE full_bouts에서 승자+패자 경기 결과 추출 (신규 데이터 형식)"""
        for bout in full_bouts:
            round_name = bout.get("round", "")
            score = bout.get("score", {})
            winner = bout.get("winner", {})
            loser = bout.get("loser", {})

            winner_name = winner.get("name", "")
            winner_team = winner.get("team", "")
            winner_score = winner.get("score", 0)

            loser_name = loser.get("name", "")
            loser_team = loser.get("team", "")
            loser_score = loser.get("score", 0)

            if not winner_name or not loser_name:
                continue

            # 팀 정보가 없으면 이름으로 추측 시도
            if not winner_team:
                teams = self.name_to_teams.get(winner_name, set())
                if len(teams) == 1:
                    winner_team = list(teams)[0]
                else:
                    continue  # 동명이인 구분 불가

            if not loser_team:
                teams = self.name_to_teams.get(loser_name, set())
                if len(teams) == 1:
                    loser_team = list(teams)[0]
                else:
                    continue  # 동명이인 구분 불가

            # 승자 기록
            winner_match = MatchResult(
                competition_name=comp_name,
                event_name=event_name,
                round_name=round_name,
                opponent_name=loser_name,
                opponent_team=loser_team,
                player_score=winner_score,
                opponent_score=loser_score,
                is_win=True,
                is_pool=False,
                date=comp_date,
                event_cd=event_cd
            )
            self._add_player_match(winner_name, winner_team, winner_match)

            # 패자 기록 (핵심!)
            loser_match = MatchResult(
                competition_name=comp_name,
                event_name=event_name,
                round_name=round_name,
                opponent_name=winner_name,
                opponent_team=winner_team,
                player_score=loser_score,
                opponent_score=winner_score,
                is_win=False,
                is_pool=False,
                date=comp_date,
                event_cd=event_cd
            )
            self._add_player_match(loser_name, loser_team, loser_match)

    def _parse_bouts_by_round(self, bouts_by_round: dict, comp_name: str, event_name: str, comp_date: str, event_cd: str = ""):
        """DE bouts_by_round에서 승자+패자 경기 결과 추출 (full_bouts 없을 때 대체)

        bouts_by_round 형식:
        {
            "16강": [
                {
                    "player1": {"name": "선수A", "team": "팀A", "score": 15},
                    "player2": {"name": "선수B", "team": "팀B", "score": 10},
                    "winnerName": "선수A",
                    "isBye": false,
                    "round": "16강"
                },
                ...
            ],
            "32강": [...],
            ...
        }
        """
        if not isinstance(bouts_by_round, dict):
            return

        for round_name, bouts in bouts_by_round.items():
            if not isinstance(bouts, list):
                continue

            for bout in bouts:
                # Bye 경기 건너뛰기 (두 가지 형식 모두 지원)
                if bout.get("isBye", False) or bout.get("is_bye", False):
                    continue

                # 두 가지 데이터 형식 지원:
                # 1. Nested 형식: player1: {name, team, score}
                # 2. Flat 형식: player1_name, player1_team, player1_score
                player1 = bout.get("player1", {})
                player2 = bout.get("player2", {})

                # Flat 형식 체크 (player1_name이 있으면 flat 형식)
                if bout.get("player1_name"):
                    p1_name = bout.get("player1_name", "")
                    p1_team = bout.get("player1_team", "")
                    p1_score = bout.get("player1_score", 0) or 0
                    p2_name = bout.get("player2_name", "")
                    p2_team = bout.get("player2_team", "")
                    p2_score = bout.get("player2_score", 0) or 0
                    winner_name_str = bout.get("winner_name", "") or bout.get("winnerName", "")
                else:
                    # Nested 형식
                    if not player1 or not player2:
                        continue
                    p1_name = player1.get("name", "")
                    p1_team = player1.get("team", "")
                    p1_score = player1.get("score", 0) or 0
                    p2_name = player2.get("name", "")
                    p2_team = player2.get("team", "")
                    p2_score = player2.get("score", 0) or 0
                    winner_name_str = bout.get("winnerName", "") or bout.get("winner_name", "")

                if not p1_name or not p2_name:
                    continue

                # 팀 정보 없으면 이름으로 추측
                if not p1_team:
                    teams = self.name_to_teams.get(p1_name, set())
                    if len(teams) == 1:
                        p1_team = list(teams)[0]
                    else:
                        continue  # 동명이인 구분 불가

                if not p2_team:
                    teams = self.name_to_teams.get(p2_name, set())
                    if len(teams) == 1:
                        p2_team = list(teams)[0]
                    else:
                        continue  # 동명이인 구분 불가

                # 승자/패자 판별
                if winner_name_str == p1_name:
                    winner_name, winner_team, winner_score = p1_name, p1_team, p1_score
                    loser_name, loser_team, loser_score = p2_name, p2_team, p2_score
                elif winner_name_str == p2_name:
                    winner_name, winner_team, winner_score = p2_name, p2_team, p2_score
                    loser_name, loser_team, loser_score = p1_name, p1_team, p1_score
                else:
                    # winnerName이 없으면 점수로 판별
                    if p1_score > p2_score:
                        winner_name, winner_team, winner_score = p1_name, p1_team, p1_score
                        loser_name, loser_team, loser_score = p2_name, p2_team, p2_score
                    elif p2_score > p1_score:
                        winner_name, winner_team, winner_score = p2_name, p2_team, p2_score
                        loser_name, loser_team, loser_score = p1_name, p1_team, p1_score
                    else:
                        continue  # 동점 - 판별 불가

                # 승자 기록
                winner_match = MatchResult(
                    competition_name=comp_name,
                    event_name=event_name,
                    round_name=round_name,
                    opponent_name=loser_name,
                    opponent_team=loser_team,
                    player_score=winner_score,
                    opponent_score=loser_score,
                    is_win=True,
                    is_pool=False,
                    date=comp_date,
                    event_cd=event_cd
                )
                self._add_player_match(winner_name, winner_team, winner_match)

                # 패자 기록
                loser_match = MatchResult(
                    competition_name=comp_name,
                    event_name=event_name,
                    round_name=round_name,
                    opponent_name=winner_name,
                    opponent_team=winner_team,
                    player_score=loser_score,
                    opponent_score=winner_score,
                    is_win=False,
                    is_pool=False,
                    date=comp_date,
                    event_cd=event_cd
                )
                self._add_player_match(loser_name, loser_team, loser_match)

    def _parse_de_matches(self, de_matches: list, comp_name: str, event_name: str, comp_date: str, event_cd: str = ""):
        """DE 대진표에서 경기 결과 추출 (기존 방식 - 승자만)"""
        matches_by_round: Dict[str, List[dict]] = defaultdict(list)

        for m in de_matches:
            if m.get("is_match_result") and m.get("score"):
                round_name = m.get("round", "")
                matches_by_round[round_name].append(m)

        for round_name, round_matches in matches_by_round.items():
            for m in round_matches:
                score = m.get("score", {})
                winner_score = score.get("winner_score", 0)
                loser_score = score.get("loser_score", 0)

                if winner_score == 0 and loser_score == 0:
                    continue

                player_name = m.get("name", "")
                player_team = m.get("team", "")

                if not player_name:
                    continue

                # 팀 정보가 없으면 건너뜀 (동명이인 구분 불가)
                if not player_team:
                    # 이름으로 팀 추측 시도 (해당 이름의 팀이 1개뿐이면)
                    teams = self.name_to_teams.get(player_name, set())
                    if len(teams) == 1:
                        player_team = list(teams)[0]
                    else:
                        continue

                # 승자 경기 기록 (DE 데이터는 승자만 기록됨)
                match = MatchResult(
                    competition_name=comp_name,
                    event_name=event_name,
                    round_name=round_name,
                    opponent_name="(상대)",
                    opponent_team="",
                    player_score=winner_score,
                    opponent_score=loser_score,
                    is_win=True,
                    is_pool=False,
                    date=comp_date,
                    event_cd=event_cd
                )
                self._add_player_match(player_name, player_team, match)

    def get_club_players(self, club_name: str) -> List[Dict[str, str]]:
        """클럽별 선수 목록 반환 (이름과 팀 정보 포함)"""
        players = []
        for player_key in self.player_matches.keys():
            name, team = parse_player_key(player_key)
            if club_name in team:
                players.append({"name": name, "team": team})
        return sorted(players, key=lambda x: x["name"])

    def analyze_player(self, player_name: str, team: str, lang: str = "ko") -> Optional[PlayerAnalytics]:
        """선수 분석 실행 - 이름과 팀 필수, lang for i18n"""
        player_key = make_player_key(player_name, team)
        matches = self.player_matches.get(player_key, [])

        if not matches:
            return None

        analytics = PlayerAnalytics(
            player_name=player_name,
            team=team
        )

        # Pool/DE 경기 분리
        pool_matches = [m for m in matches if m.is_pool]
        de_matches = [m for m in matches if not m.is_pool]

        # 전체 통계
        analytics.total_matches = len(matches)
        analytics.total_wins = sum(1 for m in matches if m.is_win)
        analytics.total_losses = analytics.total_matches - analytics.total_wins
        if analytics.total_matches > 0:
            analytics.win_rate = round(analytics.total_wins / analytics.total_matches * 100, 1)

        # Pool (5점제) 통계
        analytics.pool_matches = len(pool_matches)
        analytics.pool_wins = sum(1 for m in pool_matches if m.is_win)
        analytics.pool_losses = analytics.pool_matches - analytics.pool_wins
        if analytics.pool_matches > 0:
            analytics.pool_win_rate = round(analytics.pool_wins / analytics.pool_matches * 100, 1)

        # DE (15점제) 통계
        analytics.de_matches = len(de_matches)
        analytics.de_wins = sum(1 for m in de_matches if m.is_win)
        analytics.de_losses = analytics.de_matches - analytics.de_wins
        if analytics.de_matches > 0:
            analytics.de_win_rate = round(analytics.de_wins / analytics.de_matches * 100, 1)

        # 접전 분석
        self._analyze_clutch(analytics, matches, lang)

        # 경기 종료 유형 분석 (풀스코어 vs 시간종료)
        self._analyze_finish_type(analytics, matches, lang)

        # 점수차 분석
        self._analyze_margin(analytics, matches)

        # Result text for i18n
        win_text = "Wins" if lang == "en" else "승"
        loss_text = "Losses" if lang == "en" else "패"

        # 최근 경기 기록 (대회명, 날짜, 링크 포함)
        sorted_matches = sorted(matches, key=lambda x: x.date, reverse=True)
        analytics.recent_matches = [
            {
                "competition": m.competition_name,
                "event": m.event_name,
                "event_cd": m.event_cd,
                "round": m.round_name,
                "opponent": m.opponent_name,
                "score": m.score_display,
                "result": win_text if m.is_win else loss_text,
                "type": "Pool" if m.is_pool else "DE",
                "date": m.date
            }
            for m in sorted_matches[:15]
        ]

        # 최근 6경기 분석
        self._analyze_recent_6(analytics, sorted_matches)

        # 월별 히스토리
        analytics.match_history = self._build_match_history(matches)

        return analytics

    def _analyze_clutch(self, analytics: PlayerAnalytics, matches: List[MatchResult], lang: str = "ko"):
        """접전 승률 분석 (1점 차 경기)"""
        clutch_matches = [m for m in matches if m.is_clutch]
        analytics.clutch_matches = len(clutch_matches)
        analytics.clutch_wins = sum(1 for m in clutch_matches if m.is_win)
        analytics.clutch_losses = analytics.clutch_matches - analytics.clutch_wins

        if analytics.clutch_matches >= 3:
            analytics.clutch_rate = round(analytics.clutch_wins / analytics.clutch_matches * 100, 1)

            if analytics.clutch_rate >= 60:
                analytics.clutch_grade = get_analytics_text("grade_strong", lang)
                analytics.clutch_insight = get_analytics_text("clutch_strong", lang, wins=analytics.clutch_wins, losses=analytics.clutch_losses)
            elif analytics.clutch_rate >= 40:
                analytics.clutch_grade = get_analytics_text("grade_average", lang)
                analytics.clutch_insight = get_analytics_text("clutch_average", lang, wins=analytics.clutch_wins, losses=analytics.clutch_losses)
            else:
                analytics.clutch_grade = get_analytics_text("grade_weak", lang)
                analytics.clutch_insight = get_analytics_text("clutch_weak", lang, wins=analytics.clutch_wins, losses=analytics.clutch_losses)
        else:
            analytics.clutch_grade = get_analytics_text("grade_insufficient", lang)
            analytics.clutch_insight = get_analytics_text("clutch_insufficient", lang, matches=analytics.clutch_matches)

    def _analyze_finish_type(self, analytics: PlayerAnalytics, matches: List[MatchResult], lang: str = "ko"):
        """경기 종료 유형 분석 (풀스코어 vs 시간종료)

        - 풀스코어: 목표점(Pool 5점, DE 15점) 도달로 종료
        - 시간종료: 제한시간 경과, 목표점 미도달로 종료
        """
        fullscore_matches = [m for m in matches if m.is_fullscore]
        timeout_matches = [m for m in matches if m.is_timeout]

        # 풀스코어 경기 통계
        analytics.fullscore_matches = len(fullscore_matches)
        analytics.fullscore_wins = sum(1 for m in fullscore_matches if m.is_win)
        if analytics.fullscore_matches > 0:
            analytics.fullscore_win_rate = round(
                analytics.fullscore_wins / analytics.fullscore_matches * 100, 1
            )

        # 시간종료 경기 통계
        analytics.timeout_matches = len(timeout_matches)
        analytics.timeout_wins = sum(1 for m in timeout_matches if m.is_win)
        if analytics.timeout_matches > 0:
            analytics.timeout_win_rate = round(
                analytics.timeout_wins / analytics.timeout_matches * 100, 1
            )

        # 인사이트 생성
        if analytics.timeout_matches >= 3 and analytics.fullscore_matches >= 3:
            diff = analytics.fullscore_win_rate - analytics.timeout_win_rate
            if diff >= 15:
                analytics.finish_type_insight = get_analytics_text("fullscore_strong", lang, diff=round(abs(diff)))
            elif diff <= -15:
                analytics.finish_type_insight = get_analytics_text("timeout_strong", lang, diff=round(abs(diff)))
            else:
                analytics.finish_type_insight = get_analytics_text("finish_balanced", lang)
        elif analytics.timeout_matches > 0:
            analytics.finish_type_insight = get_analytics_text("timeout_occurred", lang, matches=analytics.timeout_matches)
        else:
            analytics.finish_type_insight = get_analytics_text("mostly_fullscore", lang)

    def _analyze_margin(self, analytics: PlayerAnalytics, matches: List[MatchResult]):
        """점수차 분석 (점수 미기록 경기는 평균/압승 집계에서 제외)"""
        scored = [m for m in matches if m.has_scores]
        wins = [m for m in scored if m.is_win]
        losses = [m for m in scored if not m.is_win]

        if wins:
            analytics.avg_win_margin = round(sum(m.score_diff for m in wins) / len(wins), 1)
        if losses:
            analytics.avg_loss_margin = round(sum(abs(m.score_diff) for m in losses) / len(losses), 1)

        # 압승/완패 (Pool: 3점차+, DE: 5점차+)
        analytics.blowout_wins = sum(1 for m in wins if
            (m.is_pool and m.score_diff >= 3) or (not m.is_pool and m.score_diff >= 5))
        analytics.blowout_losses = sum(1 for m in losses if
            (m.is_pool and abs(m.score_diff) >= 3) or (not m.is_pool and abs(m.score_diff) >= 5))

    def _analyze_recent_6(self, analytics: PlayerAnalytics, sorted_matches: List[MatchResult]):
        """최근 6경기 분석

        Args:
            analytics: 분석 결과 객체
            sorted_matches: 날짜 역순 정렬된 경기 목록
        """
        recent_6 = sorted_matches[:6]

        if len(recent_6) == 0:
            return

        analytics.recent_6_matches = [
            {
                "competition": m.competition_name,
                "event": m.event_name,
                "round": m.round_name,
                "opponent": m.opponent_name,
                "score": m.score_display,
                "result": "승" if m.is_win else "패",
                "type": "Pool" if m.is_pool else "DE",
                "date": m.date
            }
            for m in recent_6
        ]

        analytics.recent_6_wins = sum(1 for m in recent_6 if m.is_win)
        analytics.recent_6_losses = len(recent_6) - analytics.recent_6_wins
        analytics.recent_6_win_rate = round(analytics.recent_6_wins / len(recent_6) * 100, 1)

        # 트렌드 분석 (최근 6경기 vs 이전 6경기)
        if len(sorted_matches) >= 12:
            prev_6 = sorted_matches[6:12]
            prev_6_wins = sum(1 for m in prev_6 if m.is_win)
            prev_6_rate = round(prev_6_wins / len(prev_6) * 100, 1)

            diff = analytics.recent_6_win_rate - prev_6_rate
            if diff >= 10:
                analytics.recent_6_trend = "상승"
            elif diff <= -10:
                analytics.recent_6_trend = "하락"
            else:
                analytics.recent_6_trend = "유지"
        else:
            analytics.recent_6_trend = "데이터 부족"

    def _build_match_history(self, matches: List[MatchResult]) -> List[dict]:
        """월별 경기 히스토리 구축"""
        monthly = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})

        for m in matches:
            if m.date:
                month = m.date[:7]
            else:
                month = "unknown"

            monthly[month]["total"] += 1
            if m.is_win:
                monthly[month]["wins"] += 1
            else:
                monthly[month]["losses"] += 1

        result = []
        for month in sorted(monthly.keys()):
            if month != "unknown":
                data = monthly[month]
                result.append({
                    "month": month,
                    "wins": data["wins"],
                    "losses": data["losses"],
                    "total": data["total"],
                    "win_rate": round(data["wins"] / data["total"] * 100, 1) if data["total"] > 0 else 0
                })

        return result


# 싱글톤 인스턴스
_analyzer: Optional[FencingLabAnalyzer] = None


def get_analyzer() -> FencingLabAnalyzer:
    """분석기 싱글톤 인스턴스 반환"""
    global _analyzer
    if _analyzer is None:
        _analyzer = FencingLabAnalyzer()
    return _analyzer


def reload_analyzer(data_path: str = None):
    """분석기 리로드"""
    global _analyzer
    if data_path:
        _analyzer = FencingLabAnalyzer(data_path)
    else:
        _analyzer = FencingLabAnalyzer()
    return _analyzer
