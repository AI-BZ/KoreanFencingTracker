"""
펜싱 용어 체계 (Fencing Terminology System)

=== 계층 구조 (Hierarchy) ===
Tournament (대회) > Event (종목) > Bout (경기)

=== 핵심 용어 ===
- Tournament: 대회 전체 (예: 회장배 전국남녀종별선수권)
- Event: 대회 내 세부 종목 (예: 남자 플뢰레 개인전) - 랭킹 산정 기준
- Bout: 선수 A vs B의 1대1 대결 - 승률 분석의 최소 단위 (Core Data)
- Match: 보통 단체전(Team Match) 또는 Bout과 혼용 - UI에서 유저 친화적 표기

=== Bout Type ===
- Pool: 예선 (5점 내기, 3분) - 순발력 데이터
- DE: Direct Elimination / 본선 (15점 내기, 3분 3회전) - 지구력/운영 데이터

=== 용어 사용 가이드 ===
- 내부 개발/기획: Bout (명확한 구분)
- 유저 노출 (앱 화면): Match 또는 경기
"""

from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


# =============================================================================
# 1. 계층 구조 열거형 (Hierarchy Enums)
# =============================================================================

class FencingHierarchy(Enum):
    """펜싱 데이터 계층 구조"""
    TOURNAMENT = "tournament"  # 대회 전체
    EVENT = "event"            # 종목 (랭킹 산정 기준)
    BOUT = "bout"              # 개별 경기 (최소 분석 단위)


class BoutType(Enum):
    """경기 유형 - 분석의 핵심 구분"""
    POOL = "Pool"              # 예선: 5점, 3분
    DE = "DE"                  # 본선: 15점, 3분 3회전
    TEAM = "Team"              # 단체전
    UNKNOWN = "Unknown"


class BoutFormat(Enum):
    """경기 형식"""
    POOL_5 = "pool_5"          # 풀 5점 경기
    DE_15 = "de_15"            # DE 15점 경기
    DE_10 = "de_10"            # DE 10점 경기 (일부 대회)
    TEAM_45 = "team_45"        # 단체전 45점


# =============================================================================
# 2. 용어 매핑 시스템 (Terminology Mapping)
# =============================================================================

@dataclass
class TermMapping:
    """용어 매핑 정보"""
    canonical: str              # 표준 용어 (내부용)
    canonical_kr: str           # 표준 한국어
    display_en: str             # UI 표시용 영어
    display_kr: str             # UI 표시용 한국어
    aliases: List[str]          # 동의어 목록
    description: str = ""       # 설명


# 라운드 유형 매핑 (Round Type Mapping)
ROUND_TYPE_MAPPINGS: Dict[str, TermMapping] = {
    "Pool": TermMapping(
        canonical="Pool",
        canonical_kr="풀",
        display_en="Pool",
        display_kr="예선",
        aliases=[
            "예선", "풀", "뿔", "pool", "Pool", "POOL",
            "pool_round", "pool_rounds", "풀라운드", "예선전",
            "poule", "Poule"  # 프랑스어
        ],
        description="예선 라운드 (5점 경기)"
    ),
    "DE": TermMapping(
        canonical="DE",
        canonical_kr="본선",
        display_en="Direct Elimination",
        display_kr="본선",
        aliases=[
            "본선", "DE", "de", "D.E.", "d.e.",
            "Direct Elimination", "direct_elimination", "direct elimination",
            "엘리미나시옹디렉트", "엘리미나시옹 디렉트", "엘리미나시옹_디렉트",
            "Elimination Directe", "elimination directe",  # 프랑스어
            "de_bracket", "de_round", "de_rounds",
            "토너먼트", "녹아웃", "knockout", "elimination"
        ],
        description="본선 토너먼트 (15점 경기)"
    ),
    "final": TermMapping(
        canonical="final",
        canonical_kr="결승",
        display_en="Final",
        display_kr="결승",
        aliases=[
            "결승", "결승전", "final", "Final", "FINAL",
            "gold_medal_bout", "금메달전"
        ],
        description="결승전"
    ),
    "semifinal": TermMapping(
        canonical="semifinal",
        canonical_kr="준결승",
        display_en="Semifinal",
        display_kr="준결승",
        aliases=[
            "준결승", "4강", "semifinal", "semi-final", "Semi-Final",
            "semi_final", "4강전"
        ],
        description="준결승 (4강)"
    ),
    "quarterfinal": TermMapping(
        canonical="quarterfinal",
        canonical_kr="8강",
        display_en="Quarterfinal",
        display_kr="8강",
        aliases=[
            "8강", "8강전", "quarterfinal", "quarter-final", "Quarter-Final",
            "quarter_final"
        ],
        description="8강전"
    ),
}

# DE 라운드 매핑 (특정 라운드 이름)
DE_ROUND_MAPPINGS: Dict[str, TermMapping] = {
    "t256": TermMapping(canonical="t256", canonical_kr="256강", display_en="Round of 256", display_kr="256강", aliases=["256강", "256강전", "t256", "T256"]),
    "t128": TermMapping(canonical="t128", canonical_kr="128강", display_en="Round of 128", display_kr="128강", aliases=["128강", "128강전", "t128", "T128"]),
    "t64": TermMapping(canonical="t64", canonical_kr="64강", display_en="Round of 64", display_kr="64강", aliases=["64강", "64강전", "t64", "T64"]),
    "t32": TermMapping(canonical="t32", canonical_kr="32강", display_en="Round of 32", display_kr="32강", aliases=["32강", "32강전", "t32", "T32"]),
    "t16": TermMapping(canonical="t16", canonical_kr="16강", display_en="Round of 16", display_kr="16강", aliases=["16강", "16강전", "t16", "T16"]),
    "t8": TermMapping(canonical="t8", canonical_kr="8강", display_en="Quarterfinal", display_kr="8강", aliases=["8강", "8강전", "t8", "T8", "quarterfinal"]),
    "t4": TermMapping(canonical="t4", canonical_kr="4강", display_en="Semifinal", display_kr="준결승", aliases=["4강", "4강전", "t4", "T4", "semifinal", "준결승"]),
    "t2": TermMapping(canonical="t2", canonical_kr="결승", display_en="Final", display_kr="결승", aliases=["결승", "결승전", "t2", "T2", "final"]),
    "bronze": TermMapping(canonical="bronze", canonical_kr="동메달전", display_en="Bronze Medal Bout", display_kr="동메달전", aliases=["동메달전", "3위결정전", "bronze", "Bronze"]),
}

# 계층 용어 매핑 (Hierarchy Term Mapping)
HIERARCHY_MAPPINGS: Dict[str, TermMapping] = {
    "tournament": TermMapping(
        canonical="tournament",
        canonical_kr="대회",
        display_en="Tournament",
        display_kr="대회",
        aliases=[
            "대회", "tournament", "Tournament", "TOURNAMENT",
            "competition", "Competition", "대회전체", "전국대회"
        ],
        description="대회 전체 (최상위)"
    ),
    "event": TermMapping(
        canonical="event",
        canonical_kr="종목",
        display_en="Event",
        display_kr="종목",
        aliases=[
            "종목", "event", "Event", "EVENT",
            "category", "Category", "세부종목", "경기종목"
        ],
        description="대회 내 세부 종목 (랭킹 산정 기준)"
    ),
    "bout": TermMapping(
        canonical="bout",
        canonical_kr="경기",
        display_en="Bout",
        display_kr="경기",
        aliases=[
            "경기", "bout", "Bout", "BOUT",
            "대결", "1:1", "개인전경기"
        ],
        description="선수 A vs B의 1대1 대결 (최소 분석 단위)"
    ),
    "match": TermMapping(
        canonical="match",
        canonical_kr="매치",
        display_en="Match",
        display_kr="경기",
        aliases=[
            "매치", "match", "Match", "MATCH",
            "게임", "시합"
        ],
        description="Bout의 UI 친화적 표현 또는 단체전"
    ),
}

# 무기 매핑 (Weapon Mapping)
WEAPON_MAPPINGS: Dict[str, TermMapping] = {
    "foil": TermMapping(
        canonical="foil",
        canonical_kr="플뢰레",
        display_en="Foil",
        display_kr="플뢰레",
        aliases=[
            "플뢰레", "플러레", "foil", "Foil", "FOIL",
            "F", "f", "fleuret", "Fleuret"  # 프랑스어
        ]
    ),
    "epee": TermMapping(
        canonical="epee",
        canonical_kr="에페",
        display_en="Épée",
        display_kr="에페",
        aliases=[
            "에페", "에뻬", "epee", "Epee", "EPEE", "épée", "Épée",
            "E", "e"
        ]
    ),
    "sabre": TermMapping(
        canonical="sabre",
        canonical_kr="사브르",
        display_en="Sabre",
        display_kr="사브르",
        aliases=[
            "사브르", "샤브르", "세이버", "sabre", "Sabre", "SABRE",
            "saber", "Saber",  # 미국식
            "S", "s"
        ]
    ),
}

# 성별 매핑 (Gender Mapping)
GENDER_MAPPINGS: Dict[str, TermMapping] = {
    "men": TermMapping(
        canonical="men",
        canonical_kr="남자",
        display_en="Men's",
        display_kr="남자",
        aliases=["남자", "남", "men", "Men", "MEN", "M", "male", "Male"]
    ),
    "women": TermMapping(
        canonical="women",
        canonical_kr="여자",
        display_en="Women's",
        display_kr="여자",
        aliases=["여자", "여", "women", "Women", "WOMEN", "W", "F", "female", "Female"]
    ),
    "mixed": TermMapping(
        canonical="mixed",
        canonical_kr="혼성",
        display_en="Mixed",
        display_kr="혼성",
        aliases=["혼성", "mixed", "Mixed", "MIXED", "X"]
    ),
}


# =============================================================================
# 3. 용어 변환 클래스 (Terminology Converter)
# =============================================================================

class FencingTerminology:
    """펜싱 용어 변환 및 정규화 클래스"""

    # 모든 매핑을 통합한 역방향 인덱스
    _alias_to_canonical: Dict[str, Tuple[str, str]] = {}  # alias -> (category, canonical)
    _initialized: bool = False

    @classmethod
    def _initialize(cls):
        """역방향 인덱스 초기화"""
        if cls._initialized:
            return

        all_mappings = {
            "round_type": ROUND_TYPE_MAPPINGS,
            "de_round": DE_ROUND_MAPPINGS,
            "hierarchy": HIERARCHY_MAPPINGS,
            "weapon": WEAPON_MAPPINGS,
            "gender": GENDER_MAPPINGS,
        }

        for category, mappings in all_mappings.items():
            for canonical, term_mapping in mappings.items():
                # 표준 용어도 인덱스에 추가
                cls._alias_to_canonical[canonical.lower()] = (category, canonical)
                cls._alias_to_canonical[term_mapping.canonical_kr.lower()] = (category, canonical)
                # 별칭들 추가
                for alias in term_mapping.aliases:
                    cls._alias_to_canonical[alias.lower()] = (category, canonical)

        cls._initialized = True

    @classmethod
    def normalize(cls, term: str, category: Optional[str] = None) -> Optional[str]:
        """
        용어를 표준 형식으로 정규화

        Args:
            term: 변환할 용어
            category: 카테고리 제한 (round_type, de_round, hierarchy, weapon, gender)

        Returns:
            표준 용어 또는 None
        """
        cls._initialize()

        if not term:
            return None

        lookup = term.lower().strip()

        if lookup in cls._alias_to_canonical:
            found_category, canonical = cls._alias_to_canonical[lookup]
            if category is None or found_category == category:
                return canonical

        return None

    @classmethod
    def normalize_round_type(cls, term: str) -> str:
        """라운드 유형 정규화 (Pool 또는 DE)"""
        result = cls.normalize(term, "round_type")
        if result:
            return result

        # DE 라운드 이름인 경우 'DE'로 반환
        if cls.normalize(term, "de_round"):
            return "DE"

        return "Unknown"

    @classmethod
    def normalize_de_round(cls, term: str) -> Optional[str]:
        """DE 라운드 이름 정규화 (t32, t16, t8 등)"""
        return cls.normalize(term, "de_round")

    @classmethod
    def normalize_weapon(cls, term: str) -> Optional[str]:
        """무기 정규화"""
        return cls.normalize(term, "weapon")

    @classmethod
    def normalize_gender(cls, term: str) -> Optional[str]:
        """성별 정규화"""
        return cls.normalize(term, "gender")

    @classmethod
    def get_display_name(cls, canonical: str, lang: str = "ko", context: str = "ui") -> str:
        """
        표준 용어의 표시 이름 반환

        Args:
            canonical: 표준 용어
            lang: 언어 (ko, en)
            context: 컨텍스트 (ui=유저용, internal=개발용)

        Returns:
            표시 이름
        """
        cls._initialize()

        # 모든 매핑에서 검색
        for mappings in [ROUND_TYPE_MAPPINGS, DE_ROUND_MAPPINGS, HIERARCHY_MAPPINGS,
                         WEAPON_MAPPINGS, GENDER_MAPPINGS]:
            if canonical in mappings:
                mapping = mappings[canonical]
                if lang == "ko":
                    return mapping.display_kr if context == "ui" else mapping.canonical_kr
                else:
                    return mapping.display_en if context == "ui" else mapping.canonical

        return canonical

    @classmethod
    def get_bout_type(cls, round_name: str) -> BoutType:
        """라운드 이름에서 경기 유형 추론"""
        normalized = cls.normalize_round_type(round_name)

        if normalized == "pool":
            return BoutType.POOL
        elif normalized == "de":
            return BoutType.DE
        else:
            return BoutType.UNKNOWN

    @classmethod
    def get_bout_format(cls, bout_type: BoutType, score: int = 0) -> BoutFormat:
        """경기 유형과 점수로 형식 추론"""
        if bout_type == BoutType.POOL:
            return BoutFormat.POOL_5
        elif bout_type == BoutType.DE:
            if score >= 15:
                return BoutFormat.DE_15
            elif score >= 10:
                return BoutFormat.DE_10
            return BoutFormat.DE_15  # 기본값
        elif bout_type == BoutType.TEAM:
            return BoutFormat.TEAM_45
        return BoutFormat.POOL_5


# =============================================================================
# 4. 데이터 스키마 상수 (Schema Constants)
# =============================================================================

# DB 컬럼/필드 이름 (내부용)
class SchemaFields:
    """DB 스키마 필드 이름 상수"""

    # 계층 구조
    TOURNAMENT_ID = "tournament_id"
    EVENT_ID = "event_id"
    BOUT_ID = "bout_id"

    # 경기 유형
    BOUT_TYPE = "bout_type"           # 'pool' | 'de' | 'team'
    BOUT_FORMAT = "bout_format"       # 'pool_5' | 'de_15' | 'de_10' | 'team_45'
    ROUND_TYPE = "round_type"         # 'pool' | 'de'
    ROUND_NAME = "round_name"         # 't32', 't16', 't8', etc.

    # 라운드 데이터 (표준 이름)
    POOL_ROUNDS = "pool_rounds"       # 예선 라운드 데이터
    DE_BRACKET = "de_bracket"         # 본선 대진표 데이터
    FINAL_RANKINGS = "final_rankings" # 최종 순위

    # 경기 결과
    PLAYER_A_ID = "player_a_id"
    PLAYER_B_ID = "player_b_id"
    SCORE_A = "score_a"
    SCORE_B = "score_b"
    WINNER_ID = "winner_id"
    VICTORY_TYPE = "victory_type"     # 'V' (victory) | 'D' (defeat)


# =============================================================================
# 5. 유틸리티 함수 (Utility Functions)
# =============================================================================

def convert_korean_round_to_canonical(korean_round: str) -> str:
    """
    한국어 라운드 이름을 표준 형식으로 변환

    예: "엘리미나시옹디렉트" -> "de"
        "32강전" -> "t32"
        "예선" -> "pool"
    """
    # DE 라운드 먼저 확인
    de_round = FencingTerminology.normalize_de_round(korean_round)
    if de_round:
        return de_round

    # 라운드 유형 확인
    round_type = FencingTerminology.normalize_round_type(korean_round)
    if round_type != "unknown":
        return round_type

    return korean_round


def get_display_round_name(canonical: str, lang: str = "ko", short: bool = False) -> str:
    """
    표준 라운드 이름을 표시용으로 변환

    Args:
        canonical: 표준 라운드 이름 (예: 'de', 't32', 'pool')
        lang: 언어 ('ko', 'en')
        short: 짧은 형식 여부

    Returns:
        표시용 이름
    """
    if canonical == "de":
        if short:
            return "DE" if lang == "en" else "본선"
        return "Direct Elimination" if lang == "en" else "본선"

    if canonical == "pool":
        return "Pool" if lang == "en" else "예선"

    return FencingTerminology.get_display_name(canonical, lang, "ui")


def parse_bout_info(round_name: str, score_a: int = 0, score_b: int = 0) -> dict:
    """
    라운드 이름과 점수로 경기 정보 파싱

    Returns:
        {
            "bout_type": "pool" | "de",
            "bout_format": "pool_5" | "de_15",
            "round_canonical": "t32" | "pool",
            "round_display_ko": "32강" | "예선",
            "round_display_en": "Round of 32" | "Pool",
            "max_score": 5 | 15
        }
    """
    bout_type = FencingTerminology.get_bout_type(round_name)
    max_score = max(score_a, score_b)
    bout_format = FencingTerminology.get_bout_format(bout_type, max_score)

    # 표준 라운드 이름
    round_canonical = convert_korean_round_to_canonical(round_name)

    return {
        "bout_type": bout_type.value,
        "bout_format": bout_format.value,
        "round_canonical": round_canonical,
        "round_display_ko": get_display_round_name(round_canonical, "ko"),
        "round_display_en": get_display_round_name(round_canonical, "en"),
        "max_score": 5 if bout_type == BoutType.POOL else 15,
    }


# =============================================================================
# 6. 마이그레이션 헬퍼 (Migration Helpers)
# =============================================================================

def migrate_round_names(data: dict) -> dict:
    """
    기존 데이터의 라운드 이름을 표준화

    '엘리미나시옹디렉트' -> 'de'
    '예선' -> 'pool'
    '32강전' -> 't32'
    """
    if not isinstance(data, dict):
        return data

    result = {}
    for key, value in data.items():
        # 키 변환
        new_key = key
        if key in ["엘리미나시옹디렉트", "엘리미나시옹 디렉트"]:
            new_key = "de"
        elif "pool" in key.lower() or key == "예선":
            new_key = key  # pool 관련은 유지

        # 값 재귀 처리
        if isinstance(value, dict):
            result[new_key] = migrate_round_names(value)
        elif isinstance(value, list):
            result[new_key] = [migrate_round_names(item) if isinstance(item, dict) else item for item in value]
        else:
            result[new_key] = value

    return result


# =============================================================================
# 편의 함수 (Convenience Functions)
# =============================================================================

# 자주 사용하는 정규화 함수 단축
normalize_round = FencingTerminology.normalize_round_type
normalize_weapon = FencingTerminology.normalize_weapon
normalize_gender = FencingTerminology.normalize_gender
get_bout_type = FencingTerminology.get_bout_type
get_display = FencingTerminology.get_display_name


if __name__ == "__main__":
    # 테스트
    print("=== 용어 정규화 테스트 ===")

    test_terms = [
        "엘리미나시옹디렉트",
        "엘리미나시옹 디렉트",
        "DE",
        "Direct Elimination",
        "본선",
        "Pool",
        "예선",
        "풀",
        "32강전",
        "t32",
        "플뢰레",
        "foil",
        "에뻬",
    ]

    for term in test_terms:
        round_type = FencingTerminology.normalize_round_type(term)
        de_round = FencingTerminology.normalize_de_round(term)
        weapon = FencingTerminology.normalize_weapon(term)

        print(f"  '{term}':")
        if round_type != "unknown":
            print(f"    → round_type: {round_type}")
        if de_round:
            print(f"    → de_round: {de_round}")
        if weapon:
            print(f"    → weapon: {weapon}")

    print("\n=== 경기 정보 파싱 테스트 ===")
    test_rounds = [("32강전", 15, 12), ("예선", 5, 3), ("엘리미나시옹디렉트", 15, 10)]

    for round_name, score_a, score_b in test_rounds:
        info = parse_bout_info(round_name, score_a, score_b)
        print(f"  '{round_name}' ({score_a}-{score_b}):")
        print(f"    → {info}")
