"""
국가대표 선발 포인트 랭킹 — 대한펜싱협회 「국가대표 선발 규정」(2025.04.23 개정) 그대로.

이 모듈은 "NT 전체 랭킹"(랭킹 페이지 국가대표 섹션, 프로필의 국가대표 카드)의 유일한
계산 경로다. 협회가 시즌 중 공지판에 올리는 「N년 국가대표 선발을 위한 4개 대회 합산
점수 및 랭킹 현황」 표와 같은 값이 나와야 한다.

규정 조문 (원문 확인: 협회 공지 boardNo=10479 첨부 「국가대표 선발 규정」):
- 제18조(선발시기): 당해 연도 국가대표 선발은 8월 중 시행. (아시안게임·올림픽 해는 종료 후,
  세계선수권이 8월 이후면 그 종료 후) → N년 4개 대회 결과 = "N년 국가대표 선발 포인트".
- 제20조 ①: 대통령배, 김창환배, 종목별오픈대회, 국가대표 선발대회 — 4개 국내대회
  **개인전** 성적 점수 + FIE 개인전 랭킹 점수의 합산 순위로 선발.
- 제20조 ② 1호: 배점은 FIE 월드컵 점수. 1위 32, 2위 26, 3위 20, 5~8위 14, 9~16위 8,
  17~32위 4, 33~64위 2, 65~96위 1, 97~128위 0.5. **예선뿔을 통과해 엘리미나시옹
  디렉트(DE)에 진출한 선수에 한해** 점수 부여 (풀 탈락자 0점).
- 제20조 ② 2호: 국가대표가 국제대회 참가로 국내대회 불참 시 국제대회 DE 성적으로 대체 배점
  (1위 36 … 129~256위 3, 그 외·예선탈락 2). 국제대회 결과 데이터가 없어 **미반영** —
  배점표만 준비해 둔다.
- 제20조 ② 3호: FIE 개인전 랭킹 1~16위는 1위 32점부터 16위 17점까지 1점씩 차감.
  FIE 랭킹 데이터(`data_fie_rankings`)가 있으면 가산, 없으면 0점 + "미반영" 표시.
- 제20조 ③ 동점: 4개 대회 중 1위가 많은 순, 다음 2위 … 상위 성적이 많은 순. 전부 같으면
  대통령배 → 김창환배 → 종목별오픈 → 국가대표선발대회 성적 순.
- 제21조: 종목별 16명 = 선수촌 입촌 8명(선발 순위) + 25세이하 8명(후보). 증원되는 해가 있다
  (2025년 남녀 사브르 12명 — 협회 2025.09.11 선발 명단, boardNo=10576).

연도 창은 협회 표와 같다: **기준일(지난해 = 12/31, 올해 = 오늘) 시점에 4개 대회 각각 가장
최근에 결과가 나온 회차 1개씩**. 아직 안 열렸거나 결과가 없는 대회 칸에는 직전 연도 회차를
이월한다(2026.08.26 표의 "2025 김창환배"; 2016.11.21 부칙 제2조 "차년도 선발 시 중복 적용").
4개가 모두 N년 회차면 달력 연도와 같다. 이월은 직전 연도까지만이고, 이월 칸은 `is_carryover`·
`edition_year`로 표시해 UI가 "2025 김창환배 · 직전 회차"처럼 회차 연도를 붙인다. 끝난 회차인데
결과가 없으면 이월하지 않고 `no_results`(우리 데이터 결손)로 둔다.

나이리그 랭킹과 NT 나이리그 서브랭킹(`calculator.py`)은 이 모듈과 무관하다 — 손대지 않는다.
"""
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Set, Tuple

from loguru import logger


# =====================================================
# 배점표 (제20조 ②)
# =====================================================

# 1호: 국내 4개 대회 — (구간 상한 순위, 점수). 3위는 공동 3위(3, 4위) 둘 다 20점.
NT_POINT_TABLE: List[Tuple[int, float]] = [
    (1, 32.0), (2, 26.0), (4, 20.0), (8, 14.0), (16, 8.0),
    (32, 4.0), (64, 2.0), (96, 1.0), (128, 0.5),
]

# 2호: 국제대회 대체 배점 — 국제대회 결과 데이터가 없어 미반영. 구조만 준비.
NT_INTERNATIONAL_POINT_TABLE: List[Tuple[int, float]] = [
    (1, 36.0), (2, 32.0), (4, 28.0), (8, 24.0), (16, 20.0),
    (32, 14.0), (64, 8.0), (128, 4.0), (256, 3.0),
]
NT_INTERNATIONAL_DEFAULT_POINTS = 2.0  # "이외 및 예선탈락자는 2점"

# 3호: FIE 개인전 랭킹 1~16위 → 32점부터 1점씩 차감 (16위 17점)
FIE_RANK_MAX = 16


def _table_points(rank: int, table: List[Tuple[int, float]]) -> float:
    if not rank or rank < 1:
        return 0.0
    for upper, pts in table:
        if rank <= upper:
            return pts
    return 0.0


def nt_rank_points(rank: int) -> float:
    """제20조 ② 1호 — 국내 4개 대회 순위 → 점수. 129위 이하 0점."""
    return _table_points(rank, NT_POINT_TABLE)


def nt_international_points(rank: Optional[int]) -> float:
    """제20조 ② 2호 — 국제대회 DE 성적 → 대체 점수 (예선 탈락·순위 없음 = 2점).

    현재 국제대회 결과 데이터가 없어 호출되는 곳은 없다. 규정 구조 보존용.
    """
    if not rank or rank < 1 or rank > 256:
        return NT_INTERNATIONAL_DEFAULT_POINTS
    return _table_points(rank, NT_INTERNATIONAL_POINT_TABLE)


def fie_rank_points(fie_rank: Optional[int]) -> float:
    """제20조 ② 3호 — FIE 개인전 랭킹 1~16위 → 32점 … 17점."""
    if not fie_rank or fie_rank < 1 or fie_rank > FIE_RANK_MAX:
        return 0.0
    return float(33 - fie_rank)


# =====================================================
# 대상 대회 (제20조 ①) — 순서가 곧 동점 우선순위(제20조 ③)
# =====================================================

NT_COMPETITIONS: List[Dict] = [
    {"id": "president_cup", "label": "대통령배", "pattern": r"대통령배", "month_hint": 8},
    {"id": "kim_changhwan", "label": "김창환배", "pattern": r"김창환배", "month_hint": 9},
    {"id": "jongbyul_open", "label": "종목별오픈", "pattern": r"종목별\s*오픈", "month_hint": 1},
    {"id": "national_selection", "label": "국가대표 선발대회",
     "pattern": r"국가대표\s*선수?\s*선발\s*(대회|전)", "month_hint": 6},
]
NT_COMP_ORDER = [c["id"] for c in NT_COMPETITIONS]
NT_COMP_LABELS = {c["id"]: c["label"] for c in NT_COMPETITIONS}

# 이름에 이 말이 들어가면 4개 대회가 아니다.
#  유소년·청소년 국가대표 선발전: 별개 대회(랭킹 전면 제외 규칙과 동일)
#  파견선수 선발전: 지명 참가 대회 (자유 참가 원칙)
#  클럽/동호인/테스트: 공식 4개 대회가 아님
_NT_EXCLUDE = re.compile(r"유소년|청소년|파견|클럽|동호인|테스트")


def classify_nt_competition(comp_name: str) -> Optional[str]:
    """대회명이 제20조 ①의 4개 대회 중 어느 것인지. 아니면 None.

    '겸 국가대표선수 선발대회'가 붙은 대통령배·김창환배·종목별오픈은 각각 그 대회로,
    '겸'이 없는 "N년 펜싱 국가대표선수 선발대회"만 국가대표 선발대회로 분류한다.
    """
    name = comp_name or ""
    if _NT_EXCLUDE.search(name):
        return None
    for comp in NT_COMPETITIONS[:3]:
        if re.search(comp["pattern"], name):
            return comp["id"]
    if "겸" not in name and re.search(NT_COMPETITIONS[3]["pattern"], name):
        return "national_selection"
    return None


# 제21조 ①: 선발 8명. 증원된 해(제21조 ②)는 협회 선발 명단으로 확인한 것만 적는다.
NT_SELECTION_QUOTA_DEFAULT = 8
NT_SELECTION_QUOTA_OVERRIDES: Dict[Tuple[int, str], int] = {
    (2025, "sabre"): 12,  # 2025.09.11 선발 명단(boardNo=10576): 남녀 사브르 12명, 플러레·에뻬 8명
}
NT_U25_CANDIDATE_QUOTA = 8  # 제21조 ① 25세이하 후보선수 8명 (세계청소년선수권 입상자 최대 4명 우선)


def nt_selection_quota(year: int, weapon: str) -> int:
    return NT_SELECTION_QUOTA_OVERRIDES.get((year, weapon), NT_SELECTION_QUOTA_DEFAULT)


# =====================================================
# 이름 정규화
# =====================================================

# 동명이인 표식: '김재원(*)', '김재원(2)', 생년월일 접미 '김주희050513'
_NAME_MARKER = re.compile(r"\s*(?:\((?:\*|\d+)\)|\d{6})\s*$")


def normalize_name(name: str) -> str:
    """DE 대진표와 최종 순위표를 이름으로 맞출 때 쓰는 정규화.

    최종 순위표의 동명이인 표식 '김재원(*)'·'김주희050513'(생년월일 접미)은 대진표에는
    '김재원'·'김주희'로 실려 있어 표식을 떼고 비교한다. 랭킹 행의 이름(표시용)은 원문을 유지한다.
    """
    return _NAME_MARKER.sub("", (name or "").strip())


# =====================================================
# 데이터 클래스
# =====================================================

@dataclass
class NTColumn:
    """협회 표의 대회 칸 하나 (대통령배·김창환배·종목별오픈·국대선발)."""
    comp_id: str
    label: str
    status: str                     # completed | in_progress | upcoming | no_results(끝났는데 결과 데이터 없음)
    comp_name: str = ""
    comp_idx: str = ""
    start_date: str = ""
    end_date: str = ""
    month_hint: int = 0
    qualification_source: str = ""  # de_bracket | pool_status | rank_only | ""
    edition_year: int = 0           # 이 칸에 쓴 회차의 개최 연도
    is_carryover: bool = False      # 직전 연도 회차를 이월한 칸 (부칙 제2조)
    pending_comp_name: str = ""     # 열렸지만 아직 결과가 없는 더 새 회차

    def to_dict(self) -> Dict:
        return {
            "comp_id": self.comp_id, "label": self.label, "status": self.status,
            "comp_name": self.comp_name, "comp_idx": self.comp_idx,
            "start_date": self.start_date, "end_date": self.end_date,
            "month_hint": self.month_hint,
            "qualification_source": self.qualification_source,
            "edition_year": self.edition_year, "is_carryover": self.is_carryover,
            "pending_comp_name": self.pending_comp_name,
        }


@dataclass
class NTCompResult:
    """한 선수의 한 대회 성적 칸."""
    comp_id: str
    rank: int
    points: float
    qualified: bool                 # 예선뿔 통과(DE 진출) 여부 — False면 0점
    qualification_source: str
    team: str = ""
    comp_name: str = ""
    comp_idx: str = ""
    comp_date: str = ""
    event_name: str = ""
    sub_event_cd: str = ""


@dataclass
class NTPlayerRanking:
    player_name: str
    team: str
    weapon: str
    gender: str
    domestic_points: float
    fie_rank: Optional[int]
    fie_points: float
    total_points: float              # = domestic_points (협회 「4개 대회 합산표」와 같은 값)
    results: Dict[str, NTCompResult]
    current_rank: int = 0            # 4개 대회 합산 순위 (협회 표 순위)
    selection_points: float = 0.0    # 국내 + FIE (제20조 ① 합산) — 선발에 쓰는 값
    selection_rank: int = 0          # selection_points 순위 (FIE 없으면 current_rank 와 같음)


@dataclass
class NTRankingTable:
    year: int
    weapon: str
    gender: str
    columns: List[NTColumn]
    rankings: List[NTPlayerRanking]
    quota: int
    fie_applied: bool

    @property
    def completed_count(self) -> int:
        return sum(1 for c in self.columns if c.status == "completed")

    def meta(self) -> Dict:
        """UI/API가 표 머리글을 그릴 때 쓰는 요약 (모든 행이 공유)."""
        return {
            "year": self.year,
            "columns": [c.to_dict() for c in self.columns],
            "completed_count": self.completed_count,
            "total_competitions": len(self.columns),
            "carryover_count": sum(1 for c in self.columns if c.is_carryover),
            "quota": self.quota,
            "u25_quota": NT_U25_CANDIDATE_QUOTA,
            "fie_applied": self.fie_applied,
            "international_applied": False,  # 제20조 ② 2호 — 데이터 없음
            "regulation": "대한펜싱협회 국가대표 선발 규정 제18조·제20조·제21조 (2025.04.23 개정)",
        }


# =====================================================
# 계산기
# =====================================================

# fie_lookup(weapon, gender, year) -> {선수명: FIE 개인전 랭킹 순위} 또는 None
FieLookup = Callable[[str, str, int], Optional[Dict[str, int]]]

# identity_lookup(name, comp_cd, event_name, team) -> player_id 또는 None('모름')
IdentityLookup = Callable[[str, str, str, str], Optional[str]]

_POINT_BRACKETS = [(1, 1), (2, 2), (3, 4), (5, 8), (9, 16), (17, 32), (33, 64), (65, 96), (97, 128)]


class NationalTeamRankingCalculator:
    """서버 캐시(`{"competitions": [{"competition": {...}, "events": [...]}]}`)로 계산한다."""

    def __init__(self, data: Optional[Dict], fie_lookup: Optional[FieLookup] = None,
                 team_groups_lookup: Optional[Callable[[str], List[Set[str]]]] = None,
                 identity_lookup: Optional[IdentityLookup] = None):
        self.data = data or {}
        self.fie_lookup = fie_lookup
        # 동명이인 분리용 2차 근거: 이름 → [같은 사람의 소속 집합, ...].
        # 소속 개명(인천광역시중구청→영종구청)·이적을 한 사람으로 묶어 준다. 없으면 소속명 그대로.
        self.team_groups_lookup = team_groups_lookup
        # 1차 근거: 이 순위 행이 **누구의 것인지** 리졸버에게 직접 묻는다.
        # 소속 집합만으로는 한 소속이 두 사람에게 걸쳐 있을 때(김현진 — 인천광역시중구청이
        # 영종구청 사람과 독도스포츠단 사람 양쪽에 있음) 어느 쪽인지 고를 수 없고,
        # '먼저 걸린 집합'을 쓰면 프로세스마다 답이 달라졌다 (2026-10-08).
        self.identity_lookup = identity_lookup
        # {year: {comp_id: comp_data}}
        self._by_year: Dict[int, Dict[str, Dict]] = defaultdict(dict)
        self._index()

    # ---------- 대회 색인 ----------

    @staticmethod
    def _comp_year(comp: Dict) -> Optional[int]:
        sd = comp.get("start_date") or ""
        if isinstance(sd, (date, datetime)):
            return sd.year
        try:
            return int(str(sd)[:4])
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _ranked_count(comp_data: Dict) -> int:
        return sum(len(ev.get("final_rankings") or []) for ev in comp_data.get("events", []))

    def _index(self):
        for comp_data in self.data.get("competitions", []):
            comp = comp_data.get("competition", {})
            comp_id = classify_nt_competition(comp.get("name", ""))
            if not comp_id:
                continue
            year = self._comp_year(comp)
            if year is None:
                continue
            existing = self._by_year[year].get(comp_id)
            if existing is not None:
                # 같은 해 같은 대회가 둘(2019 종목별오픈 169/COMPM00263) — 결과가 많은 쪽을 쓴다.
                keep_new = self._ranked_count(comp_data) > self._ranked_count(existing)
                logger.warning(
                    f"국가대표 4개 대회 중복: {year} {comp_id} — "
                    f"'{existing.get('competition', {}).get('name')}' vs '{comp.get('name')}', "
                    f"{'새' if keep_new else '기존'} 대회 사용")
                if not keep_new:
                    continue
            self._by_year[year][comp_id] = comp_data

    def available_years(self) -> List[int]:
        return sorted(self._by_year.keys(), reverse=True)

    # ---------- 회차 선택 (협회 방식: 기준일 시점 각 대회의 최근 개최분) ----------

    @staticmethod
    def selection_cutoff(year: int, today: Optional[date] = None) -> date:
        """N년 선발 포인트의 기준일.

        지난해 = 그 해 12월 31일(선발 시점 8~9월 이후 열린 회차는 어차피 다음 해 칸에도
        그대로 이월되므로 연말까지로 잡아도 같은 4개가 남는다), 올해 = 오늘.
        """
        today = today or date.today()
        end = date(year, 12, 31)
        return today if today < end else end

    def _select_edition(self, comp_id: str, year: int, weapon: str, gender: str,
                        cutoff: date) -> Tuple[Optional[Dict], Optional[Dict], Optional[Dict]]:
        """(결과에 쓸 회차, 그 회차의 종목, 결과가 아직 없는 더 새 회차).

        협회 표와 같은 규칙: 기준일까지 열린 회차 중 **가장 최근에 결과가 나온 것** 한 회차.
        새 회차가 열렸지만 결과가 없으면 직전 회차를 그대로 이월(2016.11.21 부칙 제2조
        "차년도 선발 시 중복 적용"; 2026.08.26 표의 "2025 김창환배"). 이월은 직전 연도까지만.
        """
        candidates = []
        for y in (year - 1, year):
            cd = self._by_year.get(y, {}).get(comp_id)
            if cd is None:
                continue
            sd = str(cd.get("competition", {}).get("start_date", "") or "")[:10]
            try:
                start = datetime.strptime(sd, "%Y-%m-%d").date()
            except ValueError:
                continue
            if start <= cutoff:
                candidates.append(cd)
        pending = None
        for cd in reversed(candidates):  # 최신 회차부터
            event = self._find_event(cd, weapon, gender)
            if event and event.get("final_rankings"):
                return cd, event, pending
            if pending is None:
                pending = cd
                # 이미 끝난 회차인데 결과가 없으면 우리 데이터 결손이지 "아직 안 열린 것"이 아니다.
                # 직전 회차를 이월하면 결손을 가리므로 여기서 멈춘다 (status → no_results).
                ed = str(cd.get("competition", {}).get("end_date", "") or "")[:10]
                try:
                    if datetime.strptime(ed, "%Y-%m-%d").date() < cutoff:
                        return None, None, pending
                except ValueError:
                    pass
        return None, None, pending

    # ---------- 종목 선택 ----------

    @staticmethod
    def _is_individual(event_name: str) -> bool:
        return "단" not in event_name and "단체" not in event_name

    @staticmethod
    def _find_event(comp_data: Dict, weapon: str, gender: str) -> Optional[Dict]:
        # 순환 import 회피: calculator.extract_* 는 이 모듈을 import 하지 않지만 반대로도 두지 않는다.
        from ranking.calculator import extract_weapon, extract_gender
        for ev in comp_data.get("events", []):
            name = ev.get("name", "") or ""
            if not NationalTeamRankingCalculator._is_individual(name):
                continue
            w = ev.get("weapon") or extract_weapon(name)
            g = ev.get("gender") or extract_gender(name)
            if w == weapon and g == gender:
                return ev
        return None

    # ---------- 예선 통과 판정 (제20조 ② 1호 단서) ----------

    @staticmethod
    def _de_participants(event: Dict) -> Set[str]:
        """DE 대진표(예선 DE·본선 DE 모두)에 이름이 실린 선수 = 예선뿔 통과자."""
        names: Set[str] = set()

        def add(n):
            n = normalize_name(n)
            if n and n.upper() != "BYE":
                names.add(n)

        def scan_bracket(b: Dict):
            if not isinstance(b, dict):
                return
            for s in b.get("seeding") or []:
                if isinstance(s, dict) and not s.get("is_bye"):
                    add(s.get("name"))
            for bout in b.get("bouts") or b.get("full_bouts") or []:
                if isinstance(bout, dict):
                    add(bout.get("player1_name"))
                    add(bout.get("player2_name"))
            for rnd in (b.get("bouts_by_round") or {}).values():
                for bout in rnd or []:
                    if isinstance(bout, dict):
                        add(bout.get("player1_name"))
                        add(bout.get("player2_name"))
            for q in b.get("first_de_qualifiers") or b.get("seeded_players") or []:
                if isinstance(q, dict):
                    add(q.get("name"))
                elif isinstance(q, str):
                    add(q)

        de = event.get("de_bracket") or {}
        scan_bracket(de)
        for key in ("first_de", "second_de"):
            scan_bracket(de.get(key) or {})
        for m in event.get("de_matches") or []:
            if isinstance(m, dict):
                add(m.get("player1_name"))
                add(m.get("player2_name"))
        return names

    @classmethod
    def _qualification(cls, event: Dict) -> Tuple[Optional[Set[str]], str]:
        """(예선 통과자 집합, 근거). 근거를 알 수 없으면 (None, 'rank_only')."""
        de_names = cls._de_participants(event)
        if de_names:
            return de_names, "de_bracket"
        ptr = event.get("pool_total_ranking") or []
        statuses = {p.get("status") for p in ptr if isinstance(p, dict)}
        if "진출" in statuses:
            return {normalize_name(p.get("name")) for p in ptr
                    if isinstance(p, dict) and p.get("status") == "진출"}, "pool_status"
        return None, "rank_only"

    # ---------- 본 계산 ----------

    @staticmethod
    def _homonym_names(events: List[Dict]) -> Set[str]:
        """같은 종목 순위표에 같은 이름이 다른 소속으로 두 번 이상 나오면 동명이인이다.

        협회 표는 생년월일로 사람을 가르지만 우리에겐 이름·소속만 있다. 동명이인으로 확인된
        이름만 (이름, 소속)으로 나누고, 나머지는 이름으로 합산한다(연중 이적 시 한 사람이
        갈라지는 부작용을 동명이인에게만 한정하기 위해).
        """
        homonyms: Set[str] = set()
        for ev in events:
            teams: Dict[str, Set[str]] = defaultdict(set)
            for fr in ev.get("final_rankings") or []:
                n = normalize_name(fr.get("name") or "")
                if n:
                    teams[n].add((fr.get("team") or "").strip())
            homonyms.update(n for n, ts in teams.items() if len(ts) > 1)
        return homonyms

    def _identity_key(self, name: str, res: "NTCompResult") -> str:
        """동명이인 분리 키.

        ① 리졸버가 이 순위 행의 주인을 알면 그 player_id (가장 정확 — 같은 소속을
           두 사람이 거쳐도, 한 사람의 소속이 개명돼도 흔들리지 않는다)
        ② 모르면 같은 사람의 소속 집합 (여러 집합에 걸리면 판정 포기)
        ③ 그래도 모르면 소속명 그대로
        """
        if self.identity_lookup is not None:
            try:
                pid = self.identity_lookup(name, res.comp_idx, res.event_name, res.team)
                if pid:
                    return pid
            except Exception as e:  # 보조 정보 — 실패해도 소속으로 계속
                logger.debug(f"identity_lookup 실패 ({name}): {e}")
        return self._team_group_key(name, res.team)

    def _team_group_key(self, name: str, team: str) -> str:
        """신원 조회가 같은 사람의 소속 집합을 알면 그 집합의 대표 소속으로 묶는다.

        한 소속이 여러 집합(= 여러 사람)에 걸려 있으면 **아무 쪽도 고르지 않는다** —
        '먼저 걸린 집합'을 쓰면 집합 순회 순서에 따라 답이 달라진다.
        """
        if self.team_groups_lookup is not None:
            try:
                hits = [g for g in (self.team_groups_lookup(name) or []) if team in g]
                if len(hits) == 1:
                    return "|".join(sorted(hits[0]))
            except Exception as e:  # 보조 정보 — 실패해도 소속명으로 계속
                logger.debug(f"team_groups_lookup 실패 ({name}): {e}")
        return team

    def calculate(self, weapon: str, gender: str, year: int,
                  today: Optional[date] = None) -> NTRankingTable:
        """N년 국가대표 선발 포인트 표. `today` 는 테스트/과거 시점 재현용(기본 오늘)."""
        cutoff = self.selection_cutoff(year, today)
        columns: List[NTColumn] = []
        # {선수 키: {comp_id: NTCompResult}} — 키는 이름, 동명이인만 "이름|소속"
        per_player: Dict[str, Dict[str, NTCompResult]] = defaultdict(dict)
        display_name: Dict[str, str] = {}
        picked: Dict[str, Tuple[Optional[Dict], Optional[Dict], Optional[Dict]]] = {
            spec["id"]: self._select_edition(spec["id"], year, weapon, gender, cutoff)
            for spec in NT_COMPETITIONS
        }
        homonyms = self._homonym_names([ev for _, ev, _ in picked.values() if ev])

        for spec in NT_COMPETITIONS:
            cid = spec["id"]
            comp_data, event, pending = picked[cid]
            if comp_data is None:
                col = NTColumn(cid, spec["label"], "upcoming", month_hint=spec["month_hint"])
                if pending is not None:  # 열렸지만 결과가 없음: 진행 중이거나(in_progress) 데이터 결손(no_results)
                    pc = pending.get("competition", {})
                    col.start_date = str(pc.get("start_date", "") or "")[:10]
                    col.end_date = str(pc.get("end_date", "") or "")[:10]
                    col.comp_name = pc.get("name", "")
                    col.comp_idx = pc.get("event_cd", "") or pc.get("comp_idx", "")
                    col.edition_year = self._comp_year(pc) or 0
                    try:
                        ended = datetime.strptime(col.end_date, "%Y-%m-%d").date() < cutoff
                    except ValueError:
                        ended = False
                    col.status = "no_results" if ended else "in_progress"
                    col.pending_comp_name = col.comp_name
                columns.append(col)
                continue
            comp = comp_data.get("competition", {})
            col = NTColumn(
                cid, spec["label"], "completed",
                comp_name=comp.get("name", ""), comp_idx=comp.get("event_cd", "") or comp.get("comp_idx", ""),
                start_date=str(comp.get("start_date", "") or "")[:10],
                end_date=str(comp.get("end_date", "") or "")[:10],
                month_hint=spec["month_hint"],
            )
            col.edition_year = self._comp_year(comp) or year
            col.is_carryover = col.edition_year != year
            if pending is not None:
                col.pending_comp_name = pending.get("competition", {}).get("name", "")
            final_rankings = event.get("final_rankings") or []

            qualified_names, source = self._qualification(event)
            col.qualification_source = source
            columns.append(col)
            # 최종 순위표는 DE 진출자 전원이 풀 탈락자보다 위에 놓인다(FIE 순위 규정). 그래서
            # 대진표에서 확인된 DE 진출자 중 가장 낮은 순위까지는 이름이 대진표에 빠져 있어도
            # (예선 64강 경기 유실 등 데이터 결손) 진출자로 본다. 그 아래는 풀 탈락.
            de_rank_cap = 0
            if qualified_names:
                de_rank_cap = max((int(fr.get("rank") or 0) for fr in final_rankings
                                   if normalize_name(fr.get("name") or "") in qualified_names), default=0)

            for fr in final_rankings:
                raw_name = (fr.get("name") or "").strip()
                rank = fr.get("rank") or 0
                if not raw_name or not rank:
                    continue
                try:
                    rank = int(rank)
                except (TypeError, ValueError):
                    continue
                if qualified_names is None:
                    qualified = True  # 판정 근거 없음 — 순위표만 믿는다 (source='rank_only')
                else:
                    qualified = normalize_name(raw_name) in qualified_names or rank <= de_rank_cap
                points = nt_rank_points(rank) if qualified else 0.0
                res = NTCompResult(
                    comp_id=cid, rank=rank, points=points, qualified=qualified,
                    qualification_source=source, team=(fr.get("team") or "").strip(),
                    comp_name=col.comp_name, comp_idx=col.comp_idx, comp_date=col.start_date,
                    event_name=event.get("name", ""), sub_event_cd=event.get("sub_event_cd", "") or "",
                )
                key = raw_name
                if normalize_name(raw_name) in homonyms:
                    key = f"{normalize_name(raw_name)}|{self._identity_key(normalize_name(raw_name), res)}"
                display_name[key] = normalize_name(raw_name) if key != raw_name else raw_name
                prev = per_player[key].get(cid)
                # 같은 대회에 같은 이름이 두 번(데이터 중복)이면 더 좋은 순위만 남긴다.
                if prev is None or rank < prev.rank:
                    per_player[key][cid] = res

        fie_ranks: Optional[Dict[str, int]] = None
        if self.fie_lookup is not None:
            try:
                fie_ranks = self.fie_lookup(weapon, gender, year)
            except Exception as e:  # FIE 데이터는 보조 — 실패해도 국내 점수는 낸다
                logger.warning(f"FIE 랭킹 조회 실패 ({year} {weapon} {gender}): {e}")
                fie_ranks = None
        fie_applied = bool(fie_ranks)

        rankings: List[NTPlayerRanking] = []
        for key, results in per_player.items():
            name = display_name.get(key, key)
            domestic = sum(r.points for r in results.values())
            fie_rank = (fie_ranks or {}).get(normalize_name(name))
            fie_pts = fie_rank_points(fie_rank)
            # 소속: 가장 최근 대회의 소속 (현재 소속은 한 군데만 — 제0원칙 3)
            latest = max(results.values(), key=lambda r: r.comp_date or "")
            rankings.append(NTPlayerRanking(
                player_name=name, team=latest.team, weapon=weapon, gender=gender,
                domestic_points=domestic, fie_rank=fie_rank, fie_points=fie_pts,
                total_points=domestic, results=results, selection_points=domestic + fie_pts,
            ))

        # 표의 순위 = 국내 4개 대회 합산 (협회가 게시하는 「합산 점수 및 랭킹 현황」과 동일).
        # FIE 점수는 선발 시 합산되므로(제20조 ①) 별도 순위(selection_rank)로 둔다.
        rankings.sort(key=self._sort_key)
        for i, r in enumerate(rankings, 1):
            r.current_rank = i
        for i, r in enumerate(sorted(rankings, key=lambda x: self._sort_key(x, selection=True)), 1):
            r.selection_rank = i

        return NTRankingTable(
            year=year, weapon=weapon, gender=gender, columns=columns, rankings=rankings,
            quota=nt_selection_quota(year, weapon), fie_applied=fie_applied,
        )

    @staticmethod
    def _sort_key(r: NTPlayerRanking, selection: bool = False):
        """제20조 ③ 동점 규칙 (협회 표 실측으로 확인, 2026-09-27).

        1) 합산 점수 높은 순 (selection=True 면 국내+FIE)
        2) "1위 그리고 나서 2위 등에 오른 상위 성적이 많은 순" = 점수를 받은 순위들을 좋은 순으로
           늘어놓고 사전식 비교. [2,6,11,17] 이 [2,8,14,19] 보다 앞선다(2026 여사브르 양예솔·선은비),
           [6,10,18,20] < [6,15,23,28] < [7,11,29,30] (2025 여사브르 11~13위). 결과가 적은 쪽은
           빈 칸을 999 로 채워 뒤로 보낸다("상위 성적이 많은 순").
        3) 그래도 같으면 대통령배 → 김창환배 → 종목별오픈 → 국대선발 순위가 좋은 순
        4) 이름 (결정성 확보용 — 규정 밖)
        """
        pts = r.selection_points if selection else r.total_points
        ranks = sorted(res.rank for res in r.results.values() if res.points > 0)
        ranks = tuple(ranks + [9999] * (len(NT_COMP_ORDER) - len(ranks)))
        per_comp = tuple(
            (r.results[cid].rank if cid in r.results and r.results[cid].points > 0 else 9999)
            for cid in NT_COMP_ORDER
        )
        return (-pts, ranks, per_comp, r.player_name)


# =====================================================
# FIE 랭킹 로더 (data_fie_rankings — 다른 에이전트가 만드는 테이블)
# =====================================================

def fie_season_for_selection_year(year: int) -> int:
    """선발 연도 → 쓸 FIE 시즌 (FIE 표기: 2026 = 2025/26 시즌).

    제18조 선발은 8월 중이다. 그 시점의 FIE 개인전 랭킹은 7월 세계선수권으로 끝난 직전 시즌
    (N-1/N) 최종 랭킹이고, 새 시즌(N/N+1)은 10월 첫 월드컵 전까지 그 값을 이월한다.
    따라서 N년 선발 = FIE season N.
    """
    return year


def build_fie_lookup_from_rows(rows: List[Dict]) -> FieLookup:
    """`data_fie_rankings` 행 목록 → fie_lookup 함수.

    실제 스키마(intl-track, 2026-09-27): season INTEGER(FIE 표기, 2026 = 2025/26),
    weapon CHAR(1) 'F'/'E'/'S', gender CHAR(1) 'F'/'M', fie_rank, player_name_ko(한글 매칭,
    동명이인 미확정이면 NULL), country 'KOR', athlete_name(FIE 표기). 아래는 그 스키마와
    이전에 가정했던 일반형(weapon 'foil', gender '남') 둘 다 읽는다. player_name_ko 가 NULL 인
    행은 매칭할 한글 이름이 없으니 건너뛴다.
    """
    table: Dict[Tuple[str, str, int], Dict[str, int]] = defaultdict(dict)
    gmap = {"M": "남", "F": "여", "men": "남", "women": "여", "male": "남", "female": "여"}
    wmap = {"f": "foil", "e": "epee", "s": "sabre"}
    for row in rows or []:
        if row.get("country") and str(row["country"]).upper() != "KOR":
            continue
        name = normalize_name(row.get("player_name_ko") or row.get("player_name")
                              or row.get("name_ko") or row.get("name") or "")
        weapon = (row.get("weapon") or "").strip().lower()
        weapon = wmap.get(weapon, weapon)
        gender = (row.get("gender") or "").strip()
        gender = gmap.get(gender, gmap.get(gender.lower(), gender))
        year = row.get("season") or row.get("year")
        rank = row.get("fie_rank") or row.get("rank")
        try:
            year, rank = int(year), int(rank)
        except (TypeError, ValueError):
            continue
        if name and weapon and gender:
            prev = table[(weapon, gender, year)].get(name)
            if prev is None or rank < prev:
                table[(weapon, gender, year)][name] = rank

    def lookup(weapon: str, gender: str, year: int) -> Optional[Dict[str, int]]:
        return table.get((weapon, gender, fie_season_for_selection_year(year))) or None

    return lookup
