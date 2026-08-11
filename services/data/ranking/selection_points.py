"""
선발 포인트 계산 모듈 (Selection Points Calculator)

두 가지 선발 시스템의 포인트를 계산:
1. 꿈나무 선발: 중1 학생 대상, 5개 대회 성적 합산 → 중2 초 종목·성별별 8명 선발
2. 청소년 대표 선발: 중2~고3 대상 육성 지원 프로그램, 4개 대회 성적 합산

포인트 배점표 (두 시스템 공유):
  1위=32, 2위=26, 공동3위=20, 5-8위=14, 9-16위=8,
  17-32위=4, 33-64위=2, 65-96위=1, 97-128위=0.5
"""
import re
from datetime import date, datetime
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict

from loguru import logger

from ranking.calculator import extract_weapon, extract_gender
from app.player_identity import detect_homonyms_from_competitions


# =====================================================
# 포인트 배점표
# =====================================================

def rank_to_points(rank: int) -> float:
    """순위를 선발 포인트로 변환

    공동3위(3,4위)는 동일 포인트.
    """
    if rank == 1:
        return 32.0
    elif rank == 2:
        return 26.0
    elif rank in (3, 4):
        return 20.0
    elif 5 <= rank <= 8:
        return 14.0
    elif 9 <= rank <= 16:
        return 8.0
    elif 17 <= rank <= 32:
        return 4.0
    elif 33 <= rank <= 64:
        return 2.0
    elif 65 <= rank <= 96:
        return 1.0
    elif 97 <= rank <= 128:
        return 0.5
    return 0.0


# =====================================================
# 대회 분류
# =====================================================

# 꿈나무 대상 대회 (중1 기간, 달력 연도 내 5개 대회)
# 달력 연도: Y년 1월 ~ Y년 12월
KKUMNAMU_COMP_PATTERNS = [
    {
        "id": "junghigh_president",
        "label": "중고연맹회장배",
        "pattern": r"한국중고펜싱연맹회장배",
        "month_hint": 3,
    },
    {
        "id": "kff_jongbyul",
        "label": "회장배종별",
        "pattern": r"회장배전국남녀종별",
        "month_hint": 4,
    },
    {
        "id": "munchae_junghigh",
        "label": "문체부장관기",
        "pattern": r"문화체육관광부장관기.*중고",
        "month_hint": 7,
    },
    {
        "id": "kff_national_jongbyul",
        "label": "전국종별",
        "pattern": r"전국남녀종별",
        "month_hint": 7,
    },
    {
        "id": "junghigh_jongbyul",
        "label": "중고연맹종별",
        "pattern": r"한국중고펜싱연맹.*종별",
        "month_hint": 11,
    },
]

# 청소년 대표 선발 대상 대회
NATIONAL_TEAM_COMP_PATTERNS = [
    {
        "id": "president_cup",
        "label": "대통령배",
        "pattern": r"대통령배",
        "priority": 1,  # 동점 우선순위
        "month_hint": 8,
    },
    {
        "id": "kim_changhwan",
        "label": "김창환배",
        "pattern": r"김창환배",
        "priority": 2,
        "month_hint": 9,
    },
    {
        "id": "jongmok_open",
        "label": "종목별오픈",
        "pattern": r"종목별.*오픈",
        "priority": 3,
        "month_hint": 1,
    },
    {
        "id": "national_selection",
        "label": "국대선발",
        "pattern": r"국가대표.*선발",
        "priority": 4,
        "month_hint": 5,
    },
]


def classify_kkumnamu_competition(comp_name: str) -> Optional[str]:
    """대회명이 꿈나무 대상 대회인지 분류.

    Returns:
        대회 ID (junghigh_president, kff_jongbyul, etc.) or None
    """
    for pat in KKUMNAMU_COMP_PATTERNS:
        if re.search(pat["pattern"], comp_name):
            # "회장배종별"은 중고연맹 대회가 아닌 KFF 대회만 매칭
            if pat["id"] == "kff_jongbyul":
                # 중고연맹 대회 제외
                if re.search(r"한국중고펜싱연맹", comp_name):
                    continue
                # 클럽/동호인 대회 제외
                if re.search(r"클럽|동호인", comp_name):
                    continue
            # 문체부장관기는 체고 대회 제외 (중고만)
            if pat["id"] == "munchae_junghigh":
                if re.search(r"체육고등학교", comp_name):
                    continue
            # 전국종별은 회장배종별/중고연맹종별/실업/클럽 제외
            if pat["id"] == "kff_national_jongbyul":
                if re.search(r"회장배|한국중고펜싱연맹|실업|클럽|동호인", comp_name):
                    continue
            return pat["id"]
    return None


def classify_national_team_competition(comp_name: str) -> Optional[str]:
    """대회명이 청소년 대표 선발 대상 대회인지 분류.

    "유소년" 대회는 청소년 대표 선발 대상이 아니므로 제외.

    Returns:
        대회 ID (president_cup, kim_changhwan, etc.) or None
    """
    # 유소년 대회 제외 (유소년 국가대표선수 선발전 등)
    if re.search(r"유소년", comp_name):
        return None
    for pat in NATIONAL_TEAM_COMP_PATTERNS:
        if re.search(pat["pattern"], comp_name):
            return pat["id"]
    return None


def is_pro_or_college_team(team: str) -> bool:
    """실업팀 또는 대학팀인지 판별

    실업팀: XX시청, XX도청, XX구청, 국군체육부대, XX도시공사, XX체육회 등
    대학팀: XX대학교, XX대 (단, 중/고등학교가 아닌 것)
    """
    if not team:
        return False
    # 실업팀 패턴
    if re.search(r'시청|도청|구청|군청|국군체육부대|도시공사|체육회$|협회$', team):
        return True
    # 대학팀 패턴 (XX대학교, XX대) - 중/고등학교는 제외
    if re.search(r'대학교|대학$', team):
        return True
    return False


def _get_comp_label(comp_id: str, patterns: list) -> str:
    """comp_id → 표시용 라벨"""
    for pat in patterns:
        if pat["id"] == comp_id:
            return pat["label"]
    return comp_id


# =====================================================
# 데이터 클래스
# =====================================================

@dataclass
class CompetitionPoints:
    """한 대회에서의 포인트"""
    comp_id: str  # 대회 패턴 ID
    comp_label: str  # 표시용 라벨
    comp_name: str  # 실제 대회명
    comp_idx: str  # DB comp_idx
    rank: int
    points: float
    event_name: str
    event_cd: str = ""
    sub_event_cd: str = ""
    comp_date: str = ""  # "2025-08-14" 형식


@dataclass
class PlayerSelectionPoints:
    """선수별 선발 포인트 결과"""
    name: str
    team: str
    total_points: float
    breakdown: List[CompetitionPoints]
    rank: int = 0
    grade: str = ""
    grade_confidence: str = ""
    best_rank: int = 0  # 대회 중 최고 순위 (동점자 정렬용)


# =====================================================
# 선발 포인트 계산기
# =====================================================

class SelectionPointCalculator:
    """선발 포인트 계산기

    서버의 _data_cache를 사용하여 포인트를 계산한다.
    """

    def __init__(self, data_cache: Dict[str, Any], grade_estimator=None):
        """
        Args:
            data_cache: _data_cache ({"competitions": [...]}) 서버 메모리 캐시
            grade_estimator: GradeEstimator 인스턴스 (중1 필터링용)
        """
        self._data_cache = data_cache
        self._grade_estimator = grade_estimator

    @staticmethod
    def _estimate_rankings_from_de(event_data: Dict) -> List[Dict]:
        """final_rankings 없을 때 DE 대진표에서 진행 중 순위 추정

        탈락자: 확정 순위 (해당 라운드 기반)
        생존자: 최소 보장 순위 (현재 진출 라운드 기반)
        풀 탈락자: bracket_size + 1 순위

        Returns:
            [{"name": str, "team": str, "rank": int}, ...]
        """
        de = event_data.get("de_bracket", {})
        full_bouts = de.get("full_bouts", [])
        seeding = de.get("seeding", [])
        bracket_size = de.get("bracket_size", 0)

        if not full_bouts:
            return []

        # 라운드별 탈락 순위 (해당 라운드 패배 = 이 순위 범위)
        round_to_min_rank = {
            '128강': 65, '64강': 33, '32강': 17, '16강': 9,
            '8강': 5, '준결승': 3, '결승': 2,
        }
        round_order = ['128강', '64강', '32강', '16강', '8강', '준결승', '결승']

        # 선수별 팀 정보 수집
        player_team = {}
        for s in seeding:
            name = (s.get('name') or '').strip()
            team = (s.get('team') or '').strip()
            if name and not s.get('is_bye'):
                player_team[name] = team
        for b in full_bouts:
            for prefix in ['player1', 'player2']:
                name = (b.get(f'{prefix}_name') or '').strip()
                team = (b.get(f'{prefix}_team') or '').strip()
                if name and team:
                    player_team[name] = team

        # 라운드별 bout 분류
        bouts_by_round = {}
        for b in full_bouts:
            rn = b.get('round_name', '')
            if rn:
                bouts_by_round.setdefault(rn, []).append(b)

        # 선수별 순위 결정
        assigned = {}  # name → rank

        for round_name in round_order:
            bouts = bouts_by_round.get(round_name, [])
            if not bouts:
                continue

            for b in bouts:
                p1 = (b.get('player1_name') or '').strip()
                p2 = (b.get('player2_name') or '').strip()
                if not p1 or not p2:
                    continue

                # 승자 판정: winner 필드 → 없으면 점수 비교
                winner = (b.get('winner') or '').strip()
                if not winner:
                    s1 = b.get('player1_score') or 0
                    s2 = b.get('player2_score') or 0
                    try:
                        s1, s2 = int(s1), int(s2)
                    except (ValueError, TypeError):
                        s1, s2 = 0, 0
                    if s1 > 0 or s2 > 0:
                        winner = p1 if s1 > s2 else p2

                if winner:
                    # 완료 bout → 패자 탈락 순위
                    loser = p2 if winner == p1 else p1
                    if loser and loser not in assigned:
                        assigned[loser] = round_to_min_rank.get(round_name, 99)
                    # 결승 승자 = 1위
                    if round_name == '결승' and winner not in assigned:
                        assigned[winner] = 1
                else:
                    # 미완료 bout → 참가자는 현재 라운드 보장 순위
                    for name in [p1, p2]:
                        if name and name not in assigned:
                            assigned[name] = round_to_min_rank.get(round_name, 99)

        # 결과 생성
        results = []
        for name, rank in assigned.items():
            team = player_team.get(name, '')
            results.append({"name": name, "team": team, "rank": rank})

        # 풀 탈락자 (DE에 진출 못한 선수) → bracket_size + 1 순위
        ptr = event_data.get("pool_total_ranking", [])
        if ptr and bracket_size:
            for p in ptr:
                pname = (p.get('name') or '').strip()
                if pname and pname not in assigned:
                    results.append({
                        "name": pname,
                        "team": (p.get('team') or '').strip(),
                        "rank": bracket_size + 1,
                    })

        return results

    @staticmethod
    def get_school_year(d) -> int:
        """날짜에서 학년도 계산. 3월~2월이 한 학년도."""
        if isinstance(d, str):
            try:
                d = datetime.strptime(d[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                return 0
        if isinstance(d, datetime):
            d = d.date()
        if not isinstance(d, date):
            return 0
        return d.year if d.month >= 3 else d.year - 1

    def _get_competitions_for_school_year(self, school_year: int) -> List[Dict]:
        """학년도에 해당하는 대회 목록 반환

        학년도 Y = Y년 3월 ~ (Y+1)년 2월
        """
        result = []
        for comp_data in self._data_cache.get("competitions", []):
            comp = comp_data.get("competition", {})
            start_date = comp.get("start_date", "")
            sy = self.get_school_year(start_date)
            if sy == school_year:
                result.append(comp_data)
        return result

    def _get_competitions_for_year(self, year: int) -> List[Dict]:
        """달력 연도에 해당하는 대회 목록"""
        result = []
        for comp_data in self._data_cache.get("competitions", []):
            comp = comp_data.get("competition", {})
            start_date = comp.get("start_date", "")
            if start_date and start_date[:4] == str(year):
                result.append(comp_data)
        return result

    def _is_middle_school_event(self, event_name: str) -> bool:
        """중등부 이벤트인지 확인"""
        return bool(re.search(r'남중|여중|중등', event_name))

    @staticmethod
    def _normalize_gender(gender: str) -> str:
        """성별 표기 통일: M/F/남/여 → 남/여"""
        g = gender.strip().upper()
        if g in ("M", "남"):
            return "남"
        if g in ("F", "여"):
            return "여"
        return gender

    def _match_weapon_gender(self, event_name: str, weapon: str, gender: str) -> bool:
        """이벤트가 지정 무기/성별과 일치하는지"""
        ev_weapon = extract_weapon(event_name)
        ev_gender = extract_gender(event_name)
        if weapon and ev_weapon != weapon:
            return False
        if gender and self._normalize_gender(ev_gender) != self._normalize_gender(gender):
            return False
        return True

    def _is_individual_event(self, event_name: str) -> bool:
        """개인전인지 확인 (단체전 제외)"""
        return "단" not in event_name and "단체" not in event_name

    def _get_year_teams(self, year: int) -> Dict[str, str]:
        """해당 연도 내 선수별 최신 소속 조회.

        해당 연도 대회 중 가장 최근 대회 기준 {name: team} 반환.
        동명이인 자동 감지: 같은 대회에서 다른 팀으로 출전한 이름은 제외.
        (같은 연도에 다른 팀이 있는 경우도 안전하게 제외)
        """
        # 자동 감지: 같은 대회 + 다른 팀 = 100% 동명이인 (Level 1 규칙)
        year_comps = [
            cd for cd in self._data_cache.get("competitions", [])
            if (cd.get("competition", {}).get("start_date", "") or "")[:4] == str(year)
        ]
        auto_homonyms = detect_homonyms_from_competitions(year_comps)

        # (name) → (latest_date, team)
        latest: Dict[str, Tuple[str, str]] = {}
        # 보조 감지: 같은 연도에 2개 이상 팀 (대회가 달라도)
        name_all_teams: Dict[str, set] = defaultdict(set)

        for comp_data in year_comps:
            comp = comp_data.get("competition", {})
            comp_date = comp.get("start_date", "")
            for event in comp_data.get("events", []):
                for r in event.get("final_rankings", []):
                    name = (r.get("name") or "").strip()
                    team = (r.get("team") or "").strip()
                    if not name or not team:
                        continue
                    name_all_teams[name].add(team)
                    prev = latest.get(name)
                    if prev is None or comp_date > prev[0]:
                        latest[name] = (comp_date, team)

        # 동명이인 제외: 자동 감지 결과 + 같은 연도 다중 팀
        excluded = set(auto_homonyms.keys())
        excluded.update(n for n, teams in name_all_teams.items() if len(teams) > 1)
        return {name: team for name, (_, team) in latest.items()
                if name not in excluded}

    def _update_teams_for_year(self, results: List[PlayerSelectionPoints], year: int):
        """선발 결과의 소속을 해당 연도 최신 소속으로 업데이트.

        동명이인 자동 감지: results 내 같은 이름 다른 팀, 또는
        전체 대회 데이터에서 같은 대회 다른 팀으로 확인된 이름은 소속 변경 건너뜀.
        """
        year_teams = self._get_year_teams(year)
        # results 내 동명이인 감지: 같은 이름, 다른 팀
        name_teams: Dict[str, set] = defaultdict(set)
        for r in results:
            name_teams[r.name].add(r.team)
        multi_team_names = {n for n, teams in name_teams.items() if len(teams) > 1}

        for r in results:
            if r.name in multi_team_names:
                continue  # 동명이인은 소속 변경하지 않음
            latest = year_teams.get(r.name)
            if latest and latest != r.team:
                r.team = latest

    def calculate_kkumnamu_points(
        self,
        school_year: int,
        weapon: str = "",
        gender: str = ""
    ) -> List[PlayerSelectionPoints]:
        """꿈나무 선발 포인트 계산

        Args:
            school_year: 연도 (예: 2026 → 2026년 1월 ~ 12월)
            weapon: 무기 필터 (foil/epee/sabre), 빈 문자열이면 전체
            gender: 성별 필터 (남/여), 빈 문자열이면 전체

        Returns:
            포인트 내림차순 정렬된 선수 리스트
        """
        competitions = self._get_competitions_for_year(school_year)

        # {(name, team): {comp_id: CompetitionPoints}}
        player_points: Dict[Tuple[str, str], Dict[str, CompetitionPoints]] = defaultdict(dict)

        for comp_data in competitions:
            comp = comp_data.get("competition", {})
            comp_name = comp.get("name", "")
            comp_idx = comp.get("event_cd", "")
            start_date = comp.get("start_date", "")

            comp_type = classify_kkumnamu_competition(comp_name)
            if not comp_type:
                continue

            comp_label = _get_comp_label(comp_type, KKUMNAMU_COMP_PATTERNS)

            for event in comp_data.get("events", []):
                event_name = event.get("name", "")

                # 중등부 + 개인전 + 무기/성별 매칭
                if not self._is_middle_school_event(event_name):
                    continue
                if not self._is_individual_event(event_name):
                    continue
                if not self._match_weapon_gender(event_name, weapon, gender):
                    continue

                event_cd = event.get("event_cd", "")
                sub_event_cd = event.get("sub_event_cd", "")

                # final_rankings 사용, 없으면 DE 대진표에서 진행 중 순위 추정
                rankings_data = event.get("final_rankings", [])
                if not rankings_data:
                    rankings_data = self._estimate_rankings_from_de(event)

                for ranking in rankings_data:
                    name = (ranking.get("name") or "").strip()
                    team = (ranking.get("team") or "").strip()
                    rank = ranking.get("rank", 0)

                    if not name or not rank:
                        continue

                    pts = rank_to_points(rank)
                    if pts <= 0:
                        continue

                    key = (name, team)
                    # 같은 대회 유형에서 더 높은 포인트만 유지
                    existing = player_points[key].get(comp_type)
                    if existing is None or pts > existing.points:
                        player_points[key][comp_type] = CompetitionPoints(
                            comp_id=comp_type,
                            comp_label=comp_label,
                            comp_name=comp_name,
                            comp_idx=comp_idx,
                            rank=rank,
                            points=pts,
                            event_name=event_name,
                            event_cd=event_cd,
                            sub_event_cd=sub_event_cd,
                            comp_date=start_date[:10] if start_date else "",
                        )

        # 중1 필터링 (GradeEstimator 사용)
        results = []
        filtered_out = 0
        grade_debug = {}
        for (name, team), comps in player_points.items():
            grade_info = {"grade": "미확인", "grade_num": None, "confidence": "unknown"}

            if self._grade_estimator:
                # 해당 학년도 기준으로 중1인지 확인
                ref_date = f"{school_year}-09-01"  # 학년도 중간쯤 기준
                level_prefix = "여중" if gender == "F" else "남중"
                grade_info = self._grade_estimator.estimate_grade(
                    name, team, f"{level_prefix} {weapon}(개)", ref_date
                )

                g = grade_info.get("grade", "?")
                grade_debug[g] = grade_debug.get(g, 0) + 1

                # 중1만 포함: grade_num이 2 또는 3이면 확실히 중1이 아님 → 제외
                grade_num = grade_info.get("grade_num")
                if grade_num is not None and grade_num != 1:
                    filtered_out += 1
                    continue

            breakdown = sorted(comps.values(), key=lambda x: x.points, reverse=True)
            total = sum(cp.points for cp in breakdown)
            best = min((cp.rank for cp in breakdown), default=0)

            results.append(PlayerSelectionPoints(
                name=name,
                team=team,
                total_points=total,
                breakdown=breakdown,
                grade=grade_info.get("grade", "미확인"),
                grade_confidence=grade_info.get("confidence", "unknown"),
                best_rank=best,
            ))

        logger.debug(f"꿈나무 필터링: 전체={len(player_points)}명, "
                      f"필터제외={filtered_out}명, 통과={len(results)}명, "
                      f"학년분포={grade_debug}")

        # 총점 내림차순 → 동점 시 최고순위 오름차순 → 이름
        results.sort(key=lambda x: (-x.total_points, x.best_rank, x.name))

        # 동점 동석 순위 부여
        self._assign_tied_ranks(results)

        # 해당 연도 소속으로 업데이트 (중→고 진학 등)
        self._update_teams_for_year(results, school_year)

        return results

    def calculate_national_team_points(
        self,
        season_year: int,
        weapon: str = "",
        gender: str = ""
    ) -> List[PlayerSelectionPoints]:
        """청소년 대표 선발 포인트 계산

        Args:
            season_year: 시즌 연도 (달력 연도: 2026 = 2026.01~2026.12)
            weapon: 무기 필터
            gender: 성별 필터

        Returns:
            포인트 내림차순 정렬된 선수 리스트
        """
        # 달력 연도 기준 (2026 = 2026년 1월 ~ 12월)
        all_comps = self._get_competitions_for_year(season_year)

        # {(name, team): {comp_id: CompetitionPoints}}
        player_points: Dict[Tuple[str, str], Dict[str, CompetitionPoints]] = defaultdict(dict)

        for comp_data in all_comps:
            comp = comp_data.get("competition", {})
            comp_name = comp.get("name", "")
            comp_idx = comp.get("event_cd", "")
            start_date = comp.get("start_date", "")

            comp_type = classify_national_team_competition(comp_name)
            if not comp_type:
                continue

            comp_label = _get_comp_label(comp_type, NATIONAL_TEAM_COMP_PATTERNS)

            for event in comp_data.get("events", []):
                event_name = event.get("name", "")

                if not self._is_individual_event(event_name):
                    continue
                if not self._match_weapon_gender(event_name, weapon, gender):
                    continue

                event_cd = event.get("event_cd", "")
                sub_event_cd = event.get("sub_event_cd", "")

                # final_rankings 사용, 없으면 DE 대진표에서 진행 중 순위 추정
                rankings_data = event.get("final_rankings", [])
                if not rankings_data:
                    rankings_data = self._estimate_rankings_from_de(event)

                for ranking in rankings_data:
                    name = (ranking.get("name") or "").strip()
                    team = (ranking.get("team") or "").strip()
                    rank = ranking.get("rank", 0)

                    if not name or not rank:
                        continue

                    pts = rank_to_points(rank)
                    if pts <= 0:
                        continue

                    key = (name, team)
                    existing = player_points[key].get(comp_type)
                    if existing is None or pts > existing.points:
                        player_points[key][comp_type] = CompetitionPoints(
                            comp_id=comp_type,
                            comp_label=comp_label,
                            comp_name=comp_name,
                            comp_idx=comp_idx,
                            rank=rank,
                            points=pts,
                            event_name=event_name,
                            event_cd=event_cd,
                            sub_event_cd=sub_event_cd,
                            comp_date=start_date[:10] if start_date else "",
                        )

        # 실업팀/대학 + 학년 필터링
        # season_year 대회 성적 → season_year+1 청소년 대표 선발
        # 대상: season_year 기준 중1~고2 (→ season_year+1에 중2~고3)
        results = []
        filtered_out = 0
        grade_debug = {}
        for (name, team), comps in player_points.items():
            # 실업팀/대학 선수 제외
            if is_pro_or_college_team(team):
                filtered_out += 1
                continue

            grade_info = {"school_level": None, "grade": "미확인",
                          "grade_num": None, "confidence": "unknown"}

            if self._grade_estimator:
                ref_date = f"{season_year}-09-01"
                grade_info = self._grade_estimator.estimate_grade_from_history(
                    name, team, ref_date
                )

                g = grade_info.get("grade", "?")
                grade_debug[g] = grade_debug.get(g, 0) + 1

                school_level = grade_info.get("school_level")
                grade_num = grade_info.get("grade_num")

                # 졸업자 제외
                if school_level == "graduated":
                    filtered_out += 1
                    continue

                # 필터링: 중1~고2 범위만 포함 (다음 해 중2~고3)
                if school_level is not None and grade_num is not None:
                    if school_level == "elementary":
                        # 초등학생 → 제외
                        filtered_out += 1
                        continue
                    if school_level == "high" and grade_num >= 3:
                        # 고3 → 제외 (다음 해 졸업)
                        filtered_out += 1
                        continue
                    # middle grade 1,2,3 → 포함 (다음 해 중2~고1)
                    # high grade 1,2 → 포함 (다음 해 고2~고3)
                else:
                    # school_level=None (미확인) → 제외 (대부분 일반인/성인)
                    filtered_out += 1
                    continue

            breakdown = sorted(comps.values(), key=lambda x: x.points, reverse=True)
            total = sum(cp.points for cp in breakdown)
            best = min((cp.rank for cp in breakdown), default=0)

            results.append(PlayerSelectionPoints(
                name=name,
                team=team,
                total_points=total,
                breakdown=breakdown,
                grade=grade_info.get("grade", "미확인"),
                grade_confidence=grade_info.get("confidence", "unknown"),
                best_rank=best,
            ))

        logger.debug(f"국대 필터링: 전체={len(player_points)}명, "
                      f"필터제외={filtered_out}명, 통과={len(results)}명, "
                      f"학년분포={grade_debug}")

        # 총점 내림차순 → 동점 시 최고순위 오름차순 → 이름
        results.sort(key=lambda x: (-x.total_points, x.best_rank, x.name))
        self._assign_tied_ranks(results)

        # 해당 연도 소속으로 업데이트 (중→고 진학 등)
        self._update_teams_for_year(results, season_year)

        return results

    @staticmethod
    def _assign_tied_ranks(results: List[PlayerSelectionPoints]):
        """동점자에게 같은 순위 부여 (스포츠 순위 방식: 1,2,2,4)"""
        if not results:
            return
        results[0].rank = 1
        for i in range(1, len(results)):
            if results[i].total_points == results[i - 1].total_points:
                results[i].rank = results[i - 1].rank
            else:
                results[i].rank = i + 1

    def get_comp_columns(
        self,
        patterns: List[Dict],
        year: int,
        period_type: str,
    ) -> List[Dict]:
        """대회 컬럼 정보 생성 (날짜, 상태, 정렬 포함)

        Args:
            patterns: KKUMNAMU_COMP_PATTERNS 또는 NATIONAL_TEAM_COMP_PATTERNS
            year: 달력 연도 (2026 = 2026.01~2026.12)
            period_type: "kkumnamu" 또는 "national_team"

        Returns:
            개최순 정렬된 대회 컬럼 리스트
        """
        # 달력 연도 기준 대회 수집
        comps = self._get_competitions_for_year(year)

        # 각 패턴별로 실제 대회 매칭
        classify_fn = classify_kkumnamu_competition if period_type == "kkumnamu" else classify_national_team_competition
        # {comp_id: start_date}
        matched: Dict[str, str] = {}
        for comp_data in comps:
            comp = comp_data.get("competition", {})
            comp_name = comp.get("name", "")
            sd = comp.get("start_date", "")
            comp_type = classify_fn(comp_name)
            if comp_type and sd:
                # 같은 패턴 대회가 여러 개면 첫 번째 사용
                if comp_type not in matched:
                    matched[comp_type] = sd[:10]

        columns = []
        for pat in patterns:
            pid = pat["id"]
            label = pat["label"]
            month_hint = pat.get("month_hint", 6)
            actual_date = matched.get(pid)

            if actual_date:
                # 실제 개최됨
                try:
                    d = datetime.strptime(actual_date, "%Y-%m-%d").date()
                    date_short = f"{d.year % 100:02d}.{d.month:02d}"
                except (ValueError, TypeError):
                    date_short = actual_date[:7]
                columns.append({
                    "id": pid,
                    "label": label,
                    "date": actual_date,
                    "date_short": date_short,
                    "sort_key": actual_date[:7],
                    "status": "completed",
                })
            else:
                # 미개최 → month_hint 기반 예상 (달력 연도 내)
                est_year = year
                date_short = f"~{est_year % 100:02d}.{month_hint:02d}"
                sort_key = f"{est_year}-{month_hint:02d}"
                columns.append({
                    "id": pid,
                    "label": label,
                    "date": None,
                    "date_short": date_short,
                    "sort_key": sort_key,
                    "status": "upcoming",
                })

        # 개최순 정렬 (sort_key 오름차순)
        columns.sort(key=lambda c: c["sort_key"])
        return columns

    def get_season_range(self, year: int, period_type: str = "") -> str:
        """시즌 범위 문자열 반환 (달력 연도)"""
        return f"{year}.01 ~ {year}.12"

    def get_player_selection_points(
        self,
        player_name: str,
        player_team: str = "",
        school_year: int = 0,
        season_year: int = 0,
    ) -> Dict[str, Any]:
        """개별 선수의 선발 포인트 조회

        Args:
            player_name: 선수 이름
            player_team: 소속팀 (정확한 매칭용)
            school_year: 꿈나무 학년도 (0이면 현재 학년도)
            season_year: 국대 시즌 연도 (0이면 현재 연도)

        Returns:
            {"kkumnamu": {...}, "national_team": {...}}
        """
        if school_year == 0:
            today = date.today()
            school_year = today.year if today.month >= 3 else today.year - 1
        if season_year == 0:
            season_year = date.today().year

        result = {
            "kkumnamu": None,
            "national_team": None,
        }

        # 꿈나무: 모든 무기/성별에서 해당 선수 찾기
        for weapon in ["foil", "epee", "sabre"]:
            for gender in ["남", "여"]:
                rankings = self.calculate_kkumnamu_points(school_year, weapon, gender)
                for r in rankings:
                    if r.name == player_name and (not player_team or r.team == player_team):
                        result["kkumnamu"] = {
                            "school_year": school_year,
                            "weapon": weapon,
                            "gender": gender,
                            "rank": r.rank,
                            "total_participants": len(rankings),
                            "total_points": r.total_points,
                            "grade": r.grade,
                            "grade_confidence": r.grade_confidence,
                            "breakdown": [
                                {
                                    "comp_id": cp.comp_id,
                                    "comp_label": cp.comp_label,
                                    "comp_name": cp.comp_name,
                                    "rank": cp.rank,
                                    "points": cp.points,
                                    "event_name": cp.event_name,
                                }
                                for cp in r.breakdown
                            ],
                        }
                        break
                if result["kkumnamu"]:
                    break
            if result["kkumnamu"]:
                break

        # 국가대표: 모든 무기/성별에서 해당 선수 찾기
        for weapon in ["foil", "epee", "sabre"]:
            for gender in ["남", "여"]:
                rankings = self.calculate_national_team_points(season_year, weapon, gender)
                for r in rankings:
                    if r.name == player_name and (not player_team or r.team == player_team):
                        result["national_team"] = {
                            "season_year": season_year,
                            "weapon": weapon,
                            "gender": gender,
                            "rank": r.rank,
                            "total_participants": len(rankings),
                            "total_points": r.total_points,
                            "breakdown": [
                                {
                                    "comp_id": cp.comp_id,
                                    "comp_label": cp.comp_label,
                                    "comp_name": cp.comp_name,
                                    "rank": cp.rank,
                                    "points": cp.points,
                                    "event_name": cp.event_name,
                                }
                                for cp in r.breakdown
                            ],
                        }
                        break
                if result["national_team"]:
                    break
            if result["national_team"]:
                break

        return result

    def get_available_years(self) -> Dict[str, List[int]]:
        """사용 가능한 연도 목록 (달력 연도 기준)

        Returns:
            {"kkumnamu_school_years": [...], "national_team_seasons": [...]}
        """
        kkumnamu_years = set()
        national_years = set()

        for comp_data in self._data_cache.get("competitions", []):
            comp = comp_data.get("competition", {})
            start_date = comp.get("start_date", "")
            comp_name = comp.get("name", "")

            if not start_date:
                continue

            try:
                yr = int(start_date[:4])
            except (ValueError, TypeError):
                continue

            if classify_kkumnamu_competition(comp_name):
                kkumnamu_years.add(yr)
            if classify_national_team_competition(comp_name):
                national_years.add(yr)

        return {
            "kkumnamu_school_years": sorted(kkumnamu_years, reverse=True),
            "national_team_seasons": sorted(national_years, reverse=True),
        }

    def get_kkumnamu_year_summary(self) -> List[Dict]:
        """연도별 꿈나무 선발 요약 (모든 종목/성별)

        Returns:
            [
                {
                    "school_year": 2026,
                    "categories": [
                        {"weapon": "foil", "weapon_kr": "플뢰레", "gender": "남",
                         "total": 26, "selected": [...top 8 players...]},
                        ...
                    ]
                },
                ...
            ]
        """
        available = self.get_available_years()
        years = available.get("kkumnamu_school_years", [])

        WEAPONS = [("foil", "플뢰레"), ("epee", "에페"), ("sabre", "사브르")]
        GENDERS = ["남", "여"]

        result = []
        for yr in years:
            categories = []
            for weapon_en, weapon_kr in WEAPONS:
                for gender in GENDERS:
                    rankings = self.calculate_kkumnamu_points(yr, weapon_en, gender)
                    # 선발 라인 (8위 이내)
                    selected = [
                        {
                            "rank": r.rank,
                            "name": r.name,
                            "team": r.team,
                            "total_points": r.total_points,
                        }
                        for r in rankings if r.rank <= 8
                    ]
                    categories.append({
                        "weapon": weapon_en,
                        "weapon_kr": weapon_kr,
                        "gender": gender,
                        "total": len(rankings),
                        "selected_count": len(selected),
                        "selected": selected,
                    })
            result.append({
                "school_year": yr,
                "categories": categories,
            })

        return result

    def get_national_team_year_summary(self) -> List[Dict]:
        """연도별 청소년 대표 선발 요약 (모든 종목/성별)

        Returns:
            [
                {
                    "season_year": 2026,
                    "categories": [
                        {"weapon": "foil", "weapon_kr": "플뢰레", "gender": "남",
                         "total": 30, "selected": [...top 8 players...]},
                        ...
                    ]
                },
                ...
            ]
        """
        available = self.get_available_years()
        years = available.get("national_team_seasons", [])

        WEAPONS = [("foil", "플뢰레"), ("epee", "에페"), ("sabre", "사브르")]
        GENDERS = ["남", "여"]

        result = []
        for yr in years:
            categories = []
            for weapon_en, weapon_kr in WEAPONS:
                for gender in GENDERS:
                    rankings = self.calculate_national_team_points(yr, weapon_en, gender)
                    selected = [
                        {
                            "rank": r.rank,
                            "name": r.name,
                            "team": r.team,
                            "total_points": r.total_points,
                        }
                        for r in rankings if r.rank <= 8
                    ]
                    categories.append({
                        "weapon": weapon_en,
                        "weapon_kr": weapon_kr,
                        "gender": gender,
                        "total": len(rankings),
                        "selected_count": len(selected),
                        "selected": selected,
                    })
            result.append({
                "season_year": yr,
                "categories": categories,
            })

        return result


# 무기 한국어 표시명
WEAPON_NAMES_KR = {
    "foil": "플뢰레",
    "epee": "에페",
    "sabre": "사브르",
}
