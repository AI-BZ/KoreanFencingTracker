"""
한국 펜싱 랭킹 계산 모듈

FIE + USA Fencing 방식을 참고한 랭킹 시스템
- 대회 등급별 기본 포인트
- 순위별 포인트 비율
- 참가자 수 보정 계수
- 연령대별 가중치
- Best N 결과 합산 방식
"""
import json
import re
import warnings
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from loguru import logger


# =====================================================
# 상수 정의
# =====================================================

# 참가자 수 기반 기본 포인트 (주요 결정 요인)
# 참가자가 많은 대회 = 더 가치있는 대회
PARTICIPANT_BASE_POINTS = {
    128: 1200,  # 128명 이상 (초대규모)
    64: 1000,   # 64-127명 (대규모)
    32: 800,    # 32-63명 (중규모)
    16: 500,    # 16-31명 (소규모)
    8: 300,     # 8-15명 (미니)
    0: 150,     # 8명 미만
}

def get_base_points_by_participants(count: int) -> int:
    """참가자 수에 따른 기본 포인트 반환"""
    if count >= 128:
        return 1200
    elif count >= 64:
        return 1000
    elif count >= 32:
        return 800
    elif count >= 16:
        return 500
    elif count >= 8:
        return 300
    else:
        return 150

# 대회 권위 보정 계수 (단순화: 정식 vs 동호인만 구분)
# 참가자 수가 주요 결정 요인, 권위는 보조 요인
COMPETITION_PRESTIGE = {
    # 해외 대회 (향후 확장용)
    "fie_world": 2.00,     # FIE 월드컵/세계선수권/올림픽
    "continental": 1.60,   # 대륙선수권 (아시안, 유럽 등)
    "major_national": 1.50, # 주요국 전국대회 (미국, 프랑스 등)
    # 한국 대회 (단순화)
    "정식": 1.00,          # 정식 대회 (기본값)
    "동호인": 0.90,        # 동호인/클럽 대회
}

def get_competition_prestige(name: str) -> float:
    """대회명에서 권위 계수 반환 (단순화: 정식 vs 동호인)"""
    # 동호인/클럽 대회 키워드
    amateur_keywords = ["클럽", "동호인", "생활체육", "아마추어", "Club", "Amateur"]

    if any(keyword in name for keyword in amateur_keywords):
        return COMPETITION_PRESTIGE["동호인"]  # 0.90

    # 그 외 모든 대회는 정식 대회
    return COMPETITION_PRESTIGE["정식"]  # 1.00

# [LEGACY] 대회 등급별 기본 포인트 (하위 호환용)
TIER_BASE_POINTS = {
    "S": 1000,  # 전국체전, 회장배 전국대회
    "A": 800,   # 전국선수권대회, 대학선수권
    "B": 500,   # 시/도 대회, 연맹배
    "C": 300,   # 클럽 대회, 오픈 대회
    "D": 400,   # 인터내셔널 (국내 개최)
}

# Best N 가중치 (상위 결과일수록 높은 가중치)
BEST_N_WEIGHTS = [1.0, 0.7, 0.5, 0.3, 0.2, 0.1]  # 최대 6개까지

# 순위별 포인트 비율 (메달권 격차 확대)
RANK_RATIOS = {
    1: 1.00,
    2: 0.65,
    3: 0.50,
    4: 0.40,
    # 5-8위 (QF 탈락, 시드 순 개별 — 간격 0.02)
    5: 0.30, 6: 0.28, 7: 0.26, 8: 0.24,
    # 9-16위 (16강 탈락, 시드 순 개별 — 간격 0.01)
    9: 0.20, 10: 0.19, 11: 0.18, 12: 0.17,
    13: 0.16, 14: 0.15, 15: 0.14, 16: 0.13,
    # 17-32위 (32강 탈락, 시드 순 개별 — 간격 0.005)
    17: 0.10, 18: 0.095, 19: 0.09, 20: 0.085,
    21: 0.08, 22: 0.075, 23: 0.07, 24: 0.065,
    25: 0.06, 26: 0.055, 27: 0.05, 28: 0.045,
    29: 0.04, 30: 0.035, 31: 0.03, 32: 0.025,
}

def get_rank_ratio(rank: int) -> float:
    """순위별 포인트 비율 반환 (라운드 내 시드 기반 소폭 차등)"""
    if rank in RANK_RATIOS:
        return RANK_RATIOS[rank]
    elif 33 <= rank <= 64:
        # 64강 탈락 (간격 ~0.001)
        return round(0.05 - (rank - 33) * 0.001, 4)
    elif 65 <= rank <= 128:
        return round(0.02 - (rank - 65) * 0.0002, 4)
    else:
        return 0.01

# 참가자 수 보정 계수
def get_participant_factor(count: int) -> float:
    """참가자 수에 따른 보정 계수"""
    if count >= 64:
        return 1.0
    elif count >= 32:
        return 0.9
    elif count >= 16:
        return 0.8
    elif count >= 8:
        return 0.6
    else:
        return 0.4

# 연령대 코드 (FIE/US Fencing 글로벌 표준)
# Y = Youth, Cadet = U17, Junior = U20, Veteran = Open/Senior
AGE_GROUP_CODES = {
    "Y8": "Y8",           # Youth 8 (초등 1-2학년, Under 8)
    "Y10": "Y10",         # Youth 10 (초등 3-4학년, Under 10)
    "Y12": "Y12",         # Youth 12 (초등 5-6학년, Under 12)
    "Y14": "Y14",         # Youth 14 (중등부, Under 14)
    "Cadet": "Cadet",     # Cadet (고등부, Under 17)
    "Junior": "Junior",   # Junior (대학부, Under 20)
    "Veteran": "Veteran", # Veteran/Senior (일반부, Open)
    "NT": "🇰🇷 국가대표",   # National Team (국가대표 선발대회)
}

# 한국어 표시명 (UI용)
AGE_GROUP_NAMES_KR = {
    "Y8": "Y8 (초등1-2)",
    "Y10": "Y10 (초등3-4)",
    "Y12": "Y12 (초등5-6)",
    "Y14": "Y14 (중등)",
    "Cadet": "Cadet (고등)",
    "Junior": "Junior (대학)",
    "Veteran": "Veteran (일반)",
    "NT": "🇰🇷 국가대표",
}

# 레거시 코드 매핑 (기존 데이터 호환)
LEGACY_AGE_GROUP_MAP = {
    "E1": "Y8",
    "E2": "Y10",
    "E3": "Y12",
    "MS": "Y14",
    "HS": "Cadet",
    "UNI": "Junior",
    "SR": "Veteran",
    # 한국어 직접 매핑
    "초등": "Y12",      # 기본 초등 → Y12
    "초등1-2": "Y8",
    "초등3-4": "Y10",
    "초등5-6": "Y12",
    "중등": "Y14",
    "고등": "Cadet",
    "대학": "Junior",
    "일반": "Veteran",
    "마스터즈": "Veteran",
}

# DB age_group 비표준 값 → 표준 코드 정규화
# events.age_group에 한국어 텍스트가 직접 저장된 경우 표준 코드로 변환
AGE_GROUP_NORMALIZE = {
    '일반부': 'SR', '일반': 'SR', '성인': 'SR',
    '중등부': 'MS', '중학교': 'MS', '중등': 'MS',
    '고등부': 'HS', '고등학교': 'HS', '고등': 'HS',
    '대학부': 'UNI', '대학': 'UNI',
    '초등부': 'E3', '초등': 'E3',
    '15세이하부': 'MS', '16세이하부': 'MS',  # 구 소년체전 형식
    '18세이하부': 'HS',                       # 구 소년체전 형식
}

# 연령대별 가중치 (글로벌 코드 + 레거시 코드)
AGE_GROUP_WEIGHTS = {
    # FIE 글로벌 코드
    "Y8": 0.4,
    "Y10": 0.5,
    "Y12": 0.6,
    "Y14": 0.7,
    "Cadet": 0.8,
    "Junior": 0.9,
    "Veteran": 1.0,
    # 레거시 코드 (동일한 가중치 적용)
    "E1": 0.4,    # Y8
    "E2": 0.5,    # Y10
    "E3": 0.6,    # Y12
    "MS": 0.7,    # Y14
    "HS": 0.8,    # Cadet
    "UNI": 0.9,   # Junior
    "SR": 1.0,    # Veteran
    # 특수 코드
    "U17": 0.75,  # Y14(0.7)와 Cadet(0.8) 사이
}

# 선수 구분 (Y14 이상부터 적용)
CATEGORY_CODES = {
    "PRO": "Pro",       # 전문 선수
    "CLUB": "Club",     # 클럽/동호인
}

# 동호인/전문 분류가 적용되는 연령대 (Y14 이상)
# U17도 MS/HS 사이이므로 포함
# NT(국가대표)는 특수 카테고리이지만 PRO만 해당
CATEGORY_APPLICABLE_AGE_GROUPS = ["Y14", "Cadet", "Junior", "Veteran", "MS", "HS", "UNI", "SR", "U17", "NT"]


# =====================================================
# 데이터 클래스
# =====================================================

@dataclass
class PlayerResult:
    """선수별 대회 결과"""
    player_name: str
    team: str
    event_name: str
    competition_name: str
    competition_date: date
    final_rank: int
    total_participants: int
    weapon: str
    gender: str
    age_group: str
    tier: str
    category: str = "PRO"  # PRO(전문) or CLUB(동호인)
    points: float = 0.0


@dataclass
class PlayerRanking:
    """선수 랭킹 정보"""
    player_name: str
    teams: List[str]
    weapon: str
    gender: str
    age_group: str
    total_points: float
    competitions_count: int
    best_results: List[Dict]
    gold_count: int = 0
    silver_count: int = 0
    bronze_count: int = 0
    current_rank: int = 0


# =====================================================
# 분류 함수
# =====================================================

def classify_competition_tier(name: str) -> str:
    """대회명으로 등급 분류"""
    name_lower = name.lower()

    # S등급: 전국체전, 회장배
    if any(x in name for x in ["전국체전", "회장배", "대통령배"]):
        return "S"

    # A등급: 선수권대회
    if any(x in name for x in ["선수권", "챔피언십", "Championship"]):
        return "A"

    # D등급: 국제대회
    if any(x in name for x in ["인터내셔널", "International", "국제"]):
        return "D"

    # B등급: 시도대회, 협회장배
    if any(x in name for x in ["시도대항", "협회장배", "도지사배", "시장배"]):
        return "B"

    # C등급: 기타
    return "C"


def classify_category(competition_name: str) -> str:
    """
    대회명으로 선수 구분 분류 (전문/동호인)

    동호인 대회 키워드: 클럽, 동호인, 생활체육, 아마추어
    그 외는 전문 대회로 분류
    """
    club_keywords = [
        "클럽", "동호인", "생활체육", "아마추어",
        "Club", "Amateur", "동호회"
    ]

    for keyword in club_keywords:
        if keyword in competition_name:
            return "CLUB"

    return "PRO"


def classify_competition_level(competition_name: str) -> str:
    """
    대회 레벨 분류: ELITE, AMATEUR, NATIONAL

    - NATIONAL: 대회명에 '국가대표' 포함된 모든 대회
    - AMATEUR: 동호인/클럽/생활체육 대회
    - ELITE: 나머지 모든 공식 대회 (종별, 선수권, 교육청 등)
    """
    name = competition_name

    # 겸 국가대표: 주 대회가 종별/오픈이면서 국가대표 선발을 겸하는 경우
    # → ELITE (일반 검색에서도 표시)
    if '겸' in name and '국가대표' in name:
        return 'ELITE'

    # NATIONAL - 순수 국가대표 선발대회만
    if '국가대표' in name:
        return 'NATIONAL'

    # AMATEUR 키워드
    amateur_keywords = ['동호인', '클럽', '생활체육', '아마추어', 'Club', 'Amateur']
    if any(kw in name for kw in amateur_keywords):
        return 'AMATEUR'

    # ELITE (기본값 - 나머지 모든 공식 대회)
    return 'ELITE'


def extract_age_group(event_name: str) -> str:
    """종목명에서 연령대 코드 추출

    익산 국제대회 매핑:
    - U9 (9세이하) = E1
    - U11 (11세이하) = E2
    - U13 (13세이하) = E3
    - U17 (17세이하) = U17 (특수 코드 - MS와 HS 양쪽 필터)
    - U20 (20세이하) = UNI

    국내 대회 매핑:
    - 초등부(1-2학년) = E1
    - 초등부(3-4학년) = E2
    - 초등부(5-6학년) = E3
    """

    # 초등 저학년 (1-2학년) - 9세 이하
    if any(x in event_name for x in ["9세이하", "U9", "9세", "1-2학년", "1~2학년", "초등1", "초등2"]):
        return "E1"

    # 초등 중학년 (3-4학년) - 11세 이하
    if any(x in event_name for x in ["11세이하", "U11", "11세", "3-4학년", "3~4학년", "초등3", "초등4"]):
        return "E2"

    # 초등 고학년 (5-6학년) - 13세 이하
    if any(x in event_name for x in ["13세이하", "U13", "13세", "5-6학년", "5~6학년", "초등5", "초등6"]):
        return "E3"

    # 17세이하 (U17) - 특수 처리: MS와 HS 양쪽에서 표시
    if any(x in event_name for x in ["17세이하", "U17"]):
        return "U17"

    # 중등 - U15, 남중, 여중
    if any(x in event_name for x in ["중등", "중학", "U15", "남중", "여중"]):
        return "MS"

    # 고등 - U18, 남고, 여고
    if any(x in event_name for x in ["고등", "고교", "U18", "남고", "여고"]):
        return "HS"

    # 대학 - U20
    if any(x in event_name for x in ["대학", "U20", "U23", "20세이하"]) or re.search(r"[남여]대\s", event_name):
        return "UNI"

    # 일반
    if any(x in event_name for x in ["일반", "시니어", "Senior"]):
        return "SR"

    # 대학부 패턴: "남대", "여대" 로 시작
    if event_name.startswith("남대") or event_name.startswith("여대"):
        return "UNI"

    return "SR"  # 기본값


def matches_age_group_for_ranking(result_age: str, filter_age: str) -> bool:
    """랭킹 필터링에서 연령대 매칭 확인

    U 코드와 표준 코드 매핑:
    - U9 = E1 (초등 1-2학년)
    - U11 = E2 (초등 3-4학년)
    - U13 = E3 (초등 5-6학년)
    - U17 = MS + HS (중학교 + 고등학교)
    - U20 = UNI (대학교)

    특수 케이스:
    - 빈 문자열: 매칭 안됨 (데이터 무결성 보호)

    Args:
        result_age: 선수 결과의 연령대 코드
        filter_age: 필터 연령대 코드

    Returns:
        True if matches, False otherwise
    """
    # 빈 문자열 age_group은 매칭 안됨
    if not result_age or not filter_age:
        return False

    # 정확히 일치
    if result_age == filter_age:
        return True

    # U 코드 → 표준 코드 매핑
    U_TO_STANDARD = {
        'U9': ['E1'],
        'U11': ['E2'],
        'U13': ['E3'],
        'U17': ['MS', 'HS'],  # U17은 MS와 HS 둘 다에 해당
        'U20': ['UNI'],
    }

    # 표준 코드 → U 코드 역매핑
    STANDARD_TO_U = {
        'E1': 'U9',
        'E2': 'U11',
        'E3': 'U13',
        'MS': 'U17',
        'HS': 'U17',
        'UNI': 'U20',
    }

    # result_age가 U 코드인 경우: filter_age가 해당 표준 코드인지 확인
    if result_age in U_TO_STANDARD:
        if filter_age in U_TO_STANDARD[result_age]:
            return True

    # result_age가 표준 코드인 경우: filter_age가 해당 U 코드인지 확인
    if result_age in STANDARD_TO_U:
        if filter_age == STANDARD_TO_U[result_age]:
            return True

    return False


def extract_weapon(event_name: str) -> str:
    """종목명에서 무기 추출"""
    if "플뢰레" in event_name or "플러레" in event_name or "foil" in event_name.lower():
        return "foil"
    elif "에페" in event_name or "에뻬" in event_name or "epee" in event_name.lower():
        return "epee"
    elif "사브르" in event_name or "sabre" in event_name.lower():
        return "sabre"
    return ""


def extract_gender(event_name: str) -> str:
    """종목명에서 성별 추출"""
    if "남" in event_name:
        return "남"
    elif "여" in event_name:
        return "여"
    return ""


# =====================================================
# 포인트 계산
# =====================================================

def calculate_points(
    tier: str,
    final_rank: int,
    total_participants: int,
    age_group: str,
    competition_name: str = ""
) -> float:
    """
    최종 포인트 계산 (v2: 참가자 수 기반)

    새 공식: 참가자기반포인트 × 권위보정 × 순위비율 × 연령대가중치

    Args:
        tier: 대회 등급 (legacy, 사용 안함)
        final_rank: 최종 순위
        total_participants: 총 참가자 수
        age_group: 연령대 코드
        competition_name: 대회명 (권위 보정용)
    """
    # 참가자 수 기반 기본 포인트 (주요 요인)
    base_points = get_base_points_by_participants(total_participants)

    # 대회 권위 보정 (보조 요인)
    prestige = get_competition_prestige(competition_name) if competition_name else 1.0

    # 순위 비율
    rank_ratio = get_rank_ratio(final_rank)

    # 연령대 가중치
    age_weight = AGE_GROUP_WEIGHTS.get(age_group, 1.0)

    # 최종 포인트 = 참가자기반포인트 × 권위보정 × 순위비율 × 연령대가중치
    points = base_points * prestige * rank_ratio * age_weight
    return round(points, 2)


def calculate_points_legacy(
    tier: str,
    final_rank: int,
    total_participants: int,
    age_group: str
) -> float:
    """
    [LEGACY] 기존 포인트 계산 (하위 호환용)

    공식: 기본 포인트 × 순위 비율 × 참가자 보정 × 연령대 가중치
    """
    base_points = TIER_BASE_POINTS.get(tier, 300)
    rank_ratio = get_rank_ratio(final_rank)
    participant_factor = get_participant_factor(total_participants)
    age_weight = AGE_GROUP_WEIGHTS.get(age_group, 1.0)

    points = base_points * rank_ratio * participant_factor * age_weight
    return round(points, 2)


# =====================================================
# 랭킹 계산기 클래스
# =====================================================

class RankingCalculator:
    """펜싱 랭킹 계산기

    런타임(서버)에서는 load_from_data()만 사용합니다.
    Supabase에서 로드한 데이터 딕셔너리를 전달하세요.
    """

    def __init__(self, data_file: str = None):
        self.results: List[PlayerResult] = []
        self.data = None
        self.org_age_lookup: Dict[str, str] = {}

        if data_file:
            warnings.warn(
                "data_file 파라미터는 deprecated입니다. "
                "load_from_data()를 사용하세요. (CLI 전용으로만 유지)",
                DeprecationWarning,
                stacklevel=2,
            )
            self.load_data(data_file)

    def load_data(self, data_file: str):
        """[DEPRECATED / CLI 전용] JSON 파일에서 데이터 로드

        ⚠️ 서버 런타임에서는 사용 금지 — load_from_data()를 사용하세요.
        이 메서드는 CLI(main())에서 오프라인 랭킹 계산 용도로만 유지됩니다.
        """
        warnings.warn(
            "load_data()는 deprecated입니다. "
            "서버에서는 load_from_data()를 사용하세요.",
            DeprecationWarning,
            stacklevel=2,
        )
        with open(data_file, "r", encoding="utf-8") as f:
            self.data = json.load(f)

        self._extract_results()
        logger.info(f"[CLI] JSON 데이터 로드 완료: {len(self.results)}개 결과")

    def load_from_data(self, data: dict, org_age_lookup: dict = None):
        """Supabase 캐시 데이터에서 로드 (서버 런타임 전용)

        Args:
            data: {"competitions": [...], "meta": {...}} 형식의 데이터 딕셔너리
                  (server.py의 load_data_from_supabase()가 생성)
            org_age_lookup: 조직명 → 나이그룹 매핑 (국가대표 서브랭킹용)
        """
        self.data = data
        self.org_age_lookup = org_age_lookup or {}
        self._extract_results()
        self._generate_national_sub_rankings()
        logger.info(f"메모리 데이터 로드 완료: {len(self.results)}개 결과")

    def _extract_results(self):
        """JSON 데이터에서 선수별 결과 추출"""
        if not self.data:
            return

        for comp_data in self.data.get("competitions", []):
            comp = comp_data.get("competition", {})
            comp_name = comp.get("name", "")
            comp_date_str = comp.get("start_date", "")

            # 날짜 파싱
            try:
                if isinstance(comp_date_str, str):
                    comp_date = datetime.strptime(comp_date_str, "%Y-%m-%d").date()
                else:
                    comp_date = comp_date_str
            except (ValueError, TypeError, AttributeError):
                comp_date = date.today()

            # 대회 등급 및 구분 분류
            tier = classify_competition_tier(comp_name)
            category = classify_category(comp_name)

            for event in comp_data.get("events", []):
                event_name = event.get("name", "")
                weapon = event.get("weapon", "") or extract_weapon(event_name)
                gender = event.get("gender", "") or extract_gender(event_name)
                # 데이터베이스의 age_group 필드 우선 사용, 없으면 이벤트명에서 추출
                age_group = event.get("age_group", "") or extract_age_group(event_name)
                # 비표준 한국어 age_group → 표준 코드 정규화
                age_group = AGE_GROUP_NORMALIZE.get(age_group, age_group)

                # 국가대표 선발대회: 빈 age_group → 'NT' 설정
                if not age_group and classify_competition_level(comp_name) == 'NATIONAL':
                    age_group = 'NT'

                total_participants = event.get("total_participants", 0)

                # 개인전만 처리 (단체전 제외)
                if "단" in event_name or "단체" in event_name:
                    continue

                # 최종 순위에서 결과 추출
                for ranking in event.get("final_rankings", []):
                    rank = ranking.get("rank", 0)
                    name = ranking.get("name", "")
                    team = ranking.get("team", "")

                    if not name or not rank:
                        continue

                    # 포인트 계산 (v2: 참가자 수 기반 + 대회 권위 보정)
                    points = calculate_points(
                        tier=tier,
                        final_rank=rank,
                        total_participants=total_participants,
                        age_group=age_group,
                        competition_name=comp_name
                    )

                    result = PlayerResult(
                        player_name=name,
                        team=team,
                        event_name=event_name,
                        competition_name=comp_name,
                        competition_date=comp_date,
                        final_rank=rank,
                        total_participants=total_participants,
                        weapon=weapon,
                        gender=gender,
                        age_group=age_group,
                        tier=tier,
                        category=category,
                        points=points
                    )

                    self.results.append(result)

    def _infer_player_age_group(self, player_name: str, team: str,
                                player_age_history: dict) -> str:
        """소속 org_type 또는 다른 대회 참가 이력으로 나이그룹 추론

        Args:
            player_name: 선수명
            team: 소속명
            player_age_history: {선수명: [(age_group, date), ...]} 매핑

        Returns:
            추론된 나이그룹 코드 (MS/HS/UNI/SR 등)
        """
        # 1. org_type lookup (중학교/고등학교/대학교/실업팀 등)
        age = self.org_age_lookup.get(team)
        if age:
            return age

        # 2. Cross-reference: 다른 대회에서의 최근 나이그룹
        if player_name in player_age_history:
            entries = player_age_history[player_name]
            # 날짜 역순 정렬 → 가장 최근 것 사용
            entries.sort(key=lambda x: x[1], reverse=True)
            for age_group, _ in entries:
                if age_group in ('MS', 'HS', 'UNI', 'SR', 'E1', 'E2', 'E3'):
                    return age_group

        # 3. 기본값: 일반부
        return 'SR'

    def _generate_national_sub_rankings(self):
        """국가대표 선발대회 (age_group='NT')의 나이리그별 서브랭킹 생성

        전체 결과에서 각 선수의 나이그룹을 추론하고,
        나이그룹별 서브랭킹 결과를 새로운 PlayerResult로 추가합니다.
        서브랭킹 결과는 해당 나이그룹 랭킹에 포함됩니다.
        """
        # 비국가대표 결과에서 선수별 나이그룹 이력 구축
        player_age_history = defaultdict(list)
        for r in self.results:
            if r.age_group and r.age_group not in ('', 'NT'):
                player_age_history[r.player_name].append(
                    (r.age_group, r.competition_date)
                )

        # NT 결과 찾기
        national_results = [r for r in self.results if r.age_group == 'NT']
        if not national_results:
            return

        # (대회명, 종목명, 대회일자)별로 그룹화
        event_groups = defaultdict(list)
        for r in national_results:
            key = (r.competition_name, r.event_name, r.competition_date)
            event_groups[key].append(r)

        # 각 국가대표 이벤트별 서브랭킹 생성
        new_results = []
        for (comp_name, event_name, comp_date), results in event_groups.items():
            # 각 선수의 나이그룹 추론
            player_ages = {}
            for r in results:
                age = self._infer_player_age_group(
                    r.player_name, r.team, player_age_history)
                player_ages[r.player_name] = age

            # 나이그룹별 그룹화
            age_groups = defaultdict(list)
            for r in results:
                age = player_ages[r.player_name]
                age_groups[age].append(r)

            # 서브랭킹 계산 및 새 결과 생성
            for age, players in age_groups.items():
                players.sort(key=lambda x: x.final_rank)
                for sub_rank, r in enumerate(players, 1):
                    # 전체 참가자 수 기반으로 포인트 계산 (서브그룹 수 아님)
                    points = calculate_points(
                        tier=r.tier,
                        final_rank=sub_rank,
                        total_participants=r.total_participants,
                        age_group=age,
                        competition_name=r.competition_name
                    )
                    new_results.append(PlayerResult(
                        player_name=r.player_name,
                        team=r.team,
                        event_name=r.event_name,
                        competition_name=r.competition_name,
                        competition_date=r.competition_date,
                        final_rank=sub_rank,
                        total_participants=r.total_participants,
                        weapon=r.weapon,
                        gender=r.gender,
                        age_group=age,
                        tier=r.tier,
                        category=r.category,
                        points=points
                    ))

        self.results.extend(new_results)
        if new_results:
            logger.info(f"국가대표 나이리그별 서브랭킹 {len(new_results)}건 생성")

    def calculate_rankings(
        self,
        weapon: str = None,
        gender: str = None,
        age_group: str = None,
        category: str = None,
        year: int = None,
        best_n: int = 4,
        rolling_months: int = 12,
        national_team_only: bool = False,
        excl_national: bool = False,
        excl_selection: bool = False
    ) -> List[PlayerRanking]:
        """
        랭킹 계산

        Args:
            weapon: 무기 필터 (foil/epee/sabre)
            gender: 성별 필터 (남/여)
            age_group: 연령대 필터 (E1/E2/E3/MS/HS/UNI/SR)
            category: 구분 필터 (PRO/CLUB) - 중학교 이상만 적용
            year: 시즌 연도 (None이면 롤링)
            best_n: 상위 N개 결과 합산
            rolling_months: 롤링 기간 (월)
            national_team_only: True면 국가대표 선발대회만 필터링
            excl_national: True면 전국체전/소년체전 제외
            excl_selection: True면 선발전 제외 (겸 국대선발은 제외하지 않음)

        Returns:
            랭킹 리스트
        """
        # 필터링
        filtered = self.results

        # 국가대표 선발대회만 필터링
        if national_team_only:
            filtered = [r for r in filtered if '국가대표' in r.competition_name]

        # 대회 제외 필터
        if excl_national:
            filtered = [r for r in filtered if not any(
                kw in r.competition_name for kw in ("전국체육대회", "소년체육대회", "전국체전")
            )]
        if excl_selection:
            filtered = [r for r in filtered if not (
                "선발" in r.competition_name and "겸" not in r.competition_name
            )]

        if weapon:
            filtered = [r for r in filtered if r.weapon == weapon]
        if gender:
            filtered = [r for r in filtered if r.gender == gender]
        if age_group:
            # U17 특수 처리: MS(중등), HS(고등) 필터에서 U17 결과도 포함
            filtered = [r for r in filtered if matches_age_group_for_ranking(r.age_group, age_group)]
        # 카테고리 필터 (중학교 이상만 적용, 단 국가대표는 전체)
        if category and age_group and age_group in CATEGORY_APPLICABLE_AGE_GROUPS:
            filtered = [r for r in filtered if r.category == category]

        # 기간 필터
        if year:
            # 시즌 포인트: 해당 연도
            filtered = [r for r in filtered if r.competition_date.year == year]
        else:
            # 롤링 포인트: 최근 N개월
            cutoff = date.today() - timedelta(days=rolling_months * 30)
            filtered = [r for r in filtered if r.competition_date >= cutoff]

        # 선수별 결과 그룹화
        player_results: Dict[str, List[PlayerResult]] = defaultdict(list)
        for r in filtered:
            key = r.player_name
            player_results[key].append(r)

        # 랭킹 계산
        rankings: List[PlayerRanking] = []

        for player_name, results in player_results.items():
            # 포인트 기준 정렬
            sorted_results = sorted(results, key=lambda x: x.points, reverse=True)

            # Best N 선택 (가중 합산)
            best_results = sorted_results[:best_n]
            # 가중치 적용: 1번째=100%, 2번째=70%, 3번째=50%, 4번째=30%...
            total_points = sum(
                r.points * BEST_N_WEIGHTS[i] if i < len(BEST_N_WEIGHTS) else r.points * 0.1
                for i, r in enumerate(best_results)
            )

            # 메달 집계
            gold = sum(1 for r in results if r.final_rank == 1)
            silver = sum(1 for r in results if r.final_rank == 2)
            bronze = sum(1 for r in results if r.final_rank == 3)

            # 현재 소속 - 가장 최근 대회의 소속만 사용 (소속 이력 X)
            sorted_by_date = sorted(results, key=lambda x: x.competition_date, reverse=True)
            current_team = next((r.team for r in sorted_by_date if r.team), None)
            teams = [current_team] if current_team else []

            ranking = PlayerRanking(
                player_name=player_name,
                teams=teams,
                weapon=weapon or "전체",
                gender=gender or "전체",
                age_group=age_group or "전체",
                total_points=round(total_points, 2),
                competitions_count=len(results),
                best_results=[
                    {
                        "event": r.event_name,
                        "competition": r.competition_name,
                        "date": r.competition_date.isoformat(),
                        "rank": r.final_rank,
                        "points": r.points
                    }
                    for r in best_results
                ],
                gold_count=gold,
                silver_count=silver,
                bronze_count=bronze
            )

            rankings.append(ranking)

        # 포인트 기준 정렬
        rankings.sort(key=lambda x: (
            -x.total_points,
            -x.gold_count,
            -x.silver_count,
            -x.bronze_count,
            -x.competitions_count
        ))

        # 순위 부여
        for i, r in enumerate(rankings, 1):
            r.current_rank = i

        return rankings

    def get_all_rankings(self, year: int = None) -> Dict[str, List[PlayerRanking]]:
        """
        모든 카테고리의 랭킹 계산

        Returns:
            {category_key: [rankings]} 형태의 딕셔너리
        """
        all_rankings = {}

        weapons = ["foil", "epee", "sabre"]
        genders = ["남", "여"]
        age_groups = ["E1", "E2", "E3", "MS", "HS", "UNI", "SR"]
        categories = ["PRO", "CLUB"]  # 전문/동호인

        for weapon in weapons:
            for gender in genders:
                for age_group in age_groups:
                    # 중학교 이상은 전문/동호인 분리
                    if age_group in CATEGORY_APPLICABLE_AGE_GROUPS:
                        for category in categories:
                            key = f"{weapon}_{gender}_{age_group}_{category}"
                            rankings = self.calculate_rankings(
                                weapon=weapon,
                                gender=gender,
                                age_group=age_group,
                                category=category,
                                year=year
                            )

                            if rankings:
                                all_rankings[key] = rankings
                                logger.info(f"{key}: {len(rankings)}명")
                    else:
                        # 초등부는 전문/동호인 구분 없음
                        key = f"{weapon}_{gender}_{age_group}"
                        rankings = self.calculate_rankings(
                            weapon=weapon,
                            gender=gender,
                            age_group=age_group,
                            year=year
                        )

                        if rankings:
                            all_rankings[key] = rankings
                            logger.info(f"{key}: {len(rankings)}명")

        return all_rankings

    def export_rankings(self, output_file: str, year: int = None):
        """랭킹 결과를 JSON으로 내보내기 (CLI/배치 전용)"""
        all_rankings = self.get_all_rankings(year=year)

        export_data = {
            "meta": {
                "generated_at": datetime.now().isoformat(),
                "type": "season" if year else "rolling",
                "year": year,
                "total_categories": len(all_rankings)
            },
            "rankings": {}
        }

        for key, rankings in all_rankings.items():
            export_data["rankings"][key] = [
                {
                    "rank": r.current_rank,
                    "name": r.player_name,
                    "teams": r.teams,
                    "points": r.total_points,
                    "competitions": r.competitions_count,
                    "medals": {
                        "gold": r.gold_count,
                        "silver": r.silver_count,
                        "bronze": r.bronze_count
                    },
                    "best_results": r.best_results
                }
                for r in rankings[:100]  # 상위 100명
            ]

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        logger.info(f"랭킹 내보내기 완료: {output_file}")

    def print_ranking_summary(self, rankings: List[PlayerRanking], title: str = "", top_n: int = 20):
        """랭킹 요약 출력"""
        print(f"\n{'='*60}")
        print(f" {title}")
        print(f"{'='*60}")
        print(f"{'순위':>4} {'이름':<10} {'소속':<15} {'포인트':>10} {'대회':>4} {'금':>3} {'은':>3} {'동':>3}")
        print(f"{'-'*60}")

        for r in rankings[:top_n]:
            team = r.teams[0] if r.teams else "-"
            if len(team) > 12:
                team = team[:12] + ".."
            print(f"{r.current_rank:>4} {r.player_name:<10} {team:<15} {r.total_points:>10.1f} {r.competitions_count:>4} {r.gold_count:>3} {r.silver_count:>3} {r.bronze_count:>3}")


# =====================================================
# CLI
# =====================================================

def main():
    """CLI 전용 — 오프라인 JSON 파일에서 랭킹 계산.

    서버 런타임에서는 이 함수를 사용하지 않습니다.
    서버는 load_from_data()로 Supabase 캐시 데이터를 사용합니다.
    """
    import argparse

    parser = argparse.ArgumentParser(description="한국 펜싱 랭킹 계산기 (CLI - JSON 기반)")
    parser.add_argument("--data", type=str, default="data/fencing_full_data_v2.json", help="데이터 파일 (CLI 전용)")
    parser.add_argument("--output", type=str, default="data/rankings.json", help="출력 파일")
    parser.add_argument("--weapon", type=str, help="무기 (foil/epee/sabre)")
    parser.add_argument("--gender", type=str, help="성별 (남/여)")
    parser.add_argument("--age-group", type=str, help="연령대 (E1/E2/E3/MS/HS/UNI/SR)")
    parser.add_argument("--year", type=int, help="시즌 연도 (생략시 롤링)")
    parser.add_argument("--all", action="store_true", help="모든 카테고리 랭킹 계산")
    parser.add_argument("--top", type=int, default=20, help="출력할 상위 N명")

    args = parser.parse_args()

    calculator = RankingCalculator(args.data)

    if args.all:
        calculator.export_rankings(args.output, year=args.year)
    else:
        rankings = calculator.calculate_rankings(
            weapon=args.weapon,
            gender=args.gender,
            age_group=args.age_group,
            year=args.year
        )

        title_parts = []
        if args.year:
            title_parts.append(f"{args.year}시즌")
        else:
            title_parts.append("롤링(12개월)")

        if args.age_group:
            title_parts.append(AGE_GROUP_CODES.get(args.age_group, args.age_group))
        if args.gender:
            title_parts.append(f"{args.gender}자")
        if args.weapon:
            title_parts.append(args.weapon)

        title = " ".join(title_parts) + " 랭킹"

        calculator.print_ranking_summary(rankings, title=title, top_n=args.top)


if __name__ == "__main__":
    main()
