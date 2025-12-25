"""
데이터 정규화 모듈
- 무기명, 성별, 연령대, 카테고리 정규화
- event_name에서 누락된 필드 추출
"""
import re
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass


# =============================================================================
# 정규화 매핑 테이블 (Single Source of Truth)
# =============================================================================

WEAPON_NORMALIZE_MAP = {
    # 비표준 → 표준
    "에페": "에뻬",
    "플뢰레": "플러레",
    "사브르": "사브르",  # 이미 표준
    # 영문 변환
    "epee": "에뻬",
    "foil": "플러레",
    "sabre": "사브르",
    "saber": "사브르",
    # 빈값 처리
    "": None,
    None: None,
}

GENDER_NORMALIZE_MAP = {
    # 표준 형식
    "남": "남",
    "여": "여",
    # 풀네임
    "남자": "남",
    "여자": "여",
    # 영문
    "m": "남",
    "f": "여",
    "male": "남",
    "female": "여",
    # 빈값
    "": None,
    None: None,
}

# 연령대 코드와 한글명 매핑
AGE_GROUP_MAP = {
    # 코드 → (코드, 한글명)
    "E1": ("E1", "초등 1-2"),
    "E2": ("E2", "초등 3-4"),
    "E3": ("E3", "초등 5-6"),
    "MS": ("MS", "중등"),
    "HS": ("HS", "고등"),
    "UNI": ("UNI", "대학"),
    "SR": ("SR", "일반"),
    # 한글 → 코드
    "초등저": "E1",
    "초등 저학년": "E1",
    "초등1-2": "E1",
    "초등 1-2": "E1",
    "초등중": "E2",
    "초등 중학년": "E2",
    "초등3-4": "E2",
    "초등 3-4": "E2",
    "초등고": "E3",
    "초등 고학년": "E3",
    "초등5-6": "E3",
    "초등 5-6": "E3",
    "초등부": "E3",  # 기본값으로 고학년
    "중등부": "MS",
    "중학교": "MS",
    "중학부": "MS",
    "고등부": "HS",
    "고등학교": "HS",
    "고교부": "HS",
    "대학부": "UNI",
    "대학생": "UNI",
    "일반부": "SR",
    "성인부": "SR",
    "시니어": "SR",
}

CATEGORY_NORMALIZE_MAP = {
    # 표준 형식
    "전문": "전문",
    "동호인": "동호인",
    # 변형
    "PRO": "전문",
    "pro": "전문",
    "CLUB": "동호인",
    "club": "동호인",
    "아마추어": "동호인",
    # 빈값
    "": None,
    None: None,
}


# =============================================================================
# 정규화 함수들
# =============================================================================

def normalize_weapon(weapon: Optional[str]) -> Optional[str]:
    """무기명 정규화: 에페→에뻬, 플뢰레→플러레"""
    if weapon is None:
        return None
    weapon_clean = weapon.strip().lower() if isinstance(weapon, str) else str(weapon)

    # 직접 매핑
    if weapon in WEAPON_NORMALIZE_MAP:
        return WEAPON_NORMALIZE_MAP[weapon]
    if weapon_clean in WEAPON_NORMALIZE_MAP:
        return WEAPON_NORMALIZE_MAP[weapon_clean]

    # 원본 반환 (이미 표준이거나 알 수 없는 값)
    return weapon.strip() if weapon else None


def normalize_gender(gender: Optional[str]) -> Optional[str]:
    """성별 정규화: 남자→남, 여자→여"""
    if gender is None:
        return None
    gender_clean = gender.strip().lower() if isinstance(gender, str) else str(gender)

    if gender in GENDER_NORMALIZE_MAP:
        return GENDER_NORMALIZE_MAP[gender]
    if gender_clean in GENDER_NORMALIZE_MAP:
        return GENDER_NORMALIZE_MAP[gender_clean]

    return gender.strip() if gender else None


def normalize_age_group(age_group: Optional[str]) -> Optional[str]:
    """연령대 정규화: 한글→코드 (E1, E2, E3, MS, HS, UNI, SR)"""
    if age_group is None or age_group == "":
        return None

    age_clean = age_group.strip()

    # 이미 코드 형식인 경우
    if age_clean.upper() in ["E1", "E2", "E3", "MS", "HS", "UNI", "SR"]:
        return age_clean.upper()

    # 한글에서 코드로 변환 (AGE_GROUP_MAP 사용)
    if age_clean in AGE_GROUP_MAP:
        result = AGE_GROUP_MAP[age_clean]
        if isinstance(result, tuple):
            return result[0]
        return result

    # 추가 한글 패턴 매칭
    korean_to_code = {
        "초등저": "E1",
        "초등 저학년": "E1",
        "초등중": "E2",
        "초등 중학년": "E2",
        "초등고": "E3",
        "초등 고학년": "E3",
        "초등부": "E3",
        "중등부": "MS",
        "중학부": "MS",
        "고등부": "HS",
        "고교부": "HS",
        "대학부": "UNI",
        "일반부": "SR",
        "성인부": "SR",
    }

    if age_clean in korean_to_code:
        return korean_to_code[age_clean]

    return age_clean


def normalize_category(category: Optional[str]) -> Optional[str]:
    """카테고리 정규화: 전문/동호인"""
    if category is None:
        return None
    category_clean = category.strip()

    if category in CATEGORY_NORMALIZE_MAP:
        return CATEGORY_NORMALIZE_MAP[category]
    if category_clean in CATEGORY_NORMALIZE_MAP:
        return CATEGORY_NORMALIZE_MAP[category_clean]

    return category_clean if category_clean else None


# =============================================================================
# event_name에서 필드 추출
# =============================================================================

# event_name 파싱 패턴
EVENT_NAME_PATTERNS = [
    # 패턴: "남자 중등부 에뻬 개인전 전문"
    re.compile(r"(남자?|여자?)\s*(초등[저중고]?부?|중등부?|고등부?|대학부?|일반부?|시니어)?\s*(에뻬|플러레|사브르)\s*(개인전|단체전)?\s*(전문|동호인)?"),
    # 패턴: "에뻬 남자 고등부"
    re.compile(r"(에뻬|플러레|사브르)\s*(남자?|여자?)\s*(초등[저중고]?부?|중등부?|고등부?|대학부?|일반부?)"),
    # 패턴: "U13 남자 에뻬"
    re.compile(r"U(\d+)\s*(남자?|여자?)\s*(에뻬|플러레|사브르)"),
]

U_AGE_MAP = {
    "9": "E1",
    "11": "E2",
    "13": "E3",
    "15": "MS",
    "17": "HS",
    "20": "UNI",
    "23": "SR",
}


@dataclass
class ExtractedEventInfo:
    """event_name에서 추출된 정보"""
    weapon: Optional[str] = None
    gender: Optional[str] = None
    age_group: Optional[str] = None
    event_type: Optional[str] = None  # 개인전/단체전
    category: Optional[str] = None


def extract_from_event_name(event_name: str) -> ExtractedEventInfo:
    """event_name에서 무기, 성별, 연령대, 종목유형, 카테고리 추출"""
    result = ExtractedEventInfo()

    if not event_name:
        return result

    name = event_name.strip()

    # 무기 추출
    for weapon in ["에뻬", "플러레", "사브르", "에페", "플뢰레"]:
        if weapon in name:
            result.weapon = normalize_weapon(weapon)
            break

    # 성별 추출
    if "남자" in name or "남 " in name or name.startswith("남"):
        result.gender = "남"
    elif "여자" in name or "여 " in name or name.startswith("여"):
        result.gender = "여"

    # 연령대 추출
    age_patterns = [
        # 학년 기반 패턴 (더 구체적인 것 먼저)
        (r"초등부?\s*\(?1-?2학년\)?", "E1"),
        (r"초등부?\s*\(?3-?4학년\)?", "E2"),
        (r"초등부?\s*\(?5-?6학년\)?", "E3"),
        # 저/중/고학년 패턴
        (r"초등\s*저", "E1"),
        (r"초등\s*중", "E2"),
        (r"초등\s*고", "E3"),
        # U-age 패턴
        (r"U9\b", "E1"),
        (r"U11\b", "E2"),
        (r"U13\b", "E3"),
        (r"U15\b", "MS"),
        (r"U17\b", "HS"),
        (r"U20\b", "UNI"),
        # 축약형 패턴 (남고, 여중, 남일 등) - 반드시 단어 시작에서
        (r"^[남여]고\b", "HS"),  # 남고, 여고
        (r"^[남여]중\b", "MS"),  # 남중, 여중
        (r"^[남여]일\b", "SR"),  # 남일, 여일
        (r"^[남여]대\b", "UNI"),  # 남대, 여대
        (r"^[남여]초\b", "E3"),  # 남초, 여초 (초등부 기본값)
        # 부/단위 패턴
        (r"중등부?|중학", "MS"),
        (r"고등부?|고교", "HS"),
        (r"대학부?|대학생", "UNI"),
        (r"일반부?|시니어|성인", "SR"),
        # 엘리트부 = 일반부/프로
        (r"엘리트부?", "SR"),
    ]

    for pattern, code in age_patterns:
        if re.search(pattern, name, re.IGNORECASE):
            result.age_group = code
            break

    # 종목 유형 추출
    if "단체" in name or "팀" in name:
        result.event_type = "단체전"
    elif "개인" in name:
        result.event_type = "개인전"

    # 카테고리 추출
    if "전문" in name:
        result.category = "전문"
    elif "동호인" in name or "아마추어" in name:
        result.category = "동호인"

    return result


# =============================================================================
# 레코드 정규화
# =============================================================================

def normalize_event_record(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    이벤트 레코드 전체 정규화
    - 기존 값이 있으면 정규화
    - 누락된 값은 event_name에서 추출 시도
    """
    normalized = event.copy()

    # 1. 기존 값 정규화
    if event.get("weapon"):
        normalized["weapon"] = normalize_weapon(event["weapon"])

    if event.get("gender"):
        normalized["gender"] = normalize_gender(event["gender"])

    if event.get("age_group"):
        normalized["age_group"] = normalize_age_group(event["age_group"])

    if event.get("category"):
        normalized["category"] = normalize_category(event["category"])

    # 2. event_name에서 누락된 필드 추출
    event_name = event.get("event_name", "")
    if event_name:
        extracted = extract_from_event_name(event_name)

        # 누락된 필드만 채움
        if not normalized.get("weapon") and extracted.weapon:
            normalized["weapon"] = extracted.weapon
            normalized["_weapon_source"] = "extracted"

        if not normalized.get("gender") and extracted.gender:
            normalized["gender"] = extracted.gender
            normalized["_gender_source"] = "extracted"

        if not normalized.get("age_group") and extracted.age_group:
            normalized["age_group"] = extracted.age_group
            normalized["_age_group_source"] = "extracted"

        if not normalized.get("category") and extracted.category:
            normalized["category"] = extracted.category
            normalized["_category_source"] = "extracted"

    return normalized


def normalize_player_record(player: Dict[str, Any]) -> Dict[str, Any]:
    """선수 레코드 정규화"""
    normalized = player.copy()

    # 이름 정규화 (공백 정리)
    if player.get("player_name"):
        normalized["player_name"] = player["player_name"].strip()

    # 팀명 정규화 (공백 정리)
    if player.get("team_name"):
        normalized["team_name"] = player["team_name"].strip()

    return normalized


# =============================================================================
# 배치 정규화
# =============================================================================

def normalize_events_batch(events: list) -> Tuple[list, Dict[str, int]]:
    """
    이벤트 배치 정규화
    Returns: (정규화된 이벤트 리스트, 통계)
    """
    normalized_events = []
    stats = {
        "total": len(events),
        "weapon_normalized": 0,
        "gender_normalized": 0,
        "age_group_extracted": 0,
        "category_normalized": 0,
    }

    for event in events:
        normalized = normalize_event_record(event)
        normalized_events.append(normalized)

        # 통계 수집
        if normalized.get("_weapon_source") == "extracted":
            stats["weapon_normalized"] += 1
        if normalized.get("_gender_source") == "extracted":
            stats["gender_normalized"] += 1
        if normalized.get("_age_group_source") == "extracted":
            stats["age_group_extracted"] += 1
        if normalized.get("_category_source") == "extracted":
            stats["category_normalized"] += 1

    return normalized_events, stats


def get_normalization_changes(original: Dict[str, Any], normalized: Dict[str, Any]) -> Dict[str, Tuple[Any, Any]]:
    """
    정규화 전후 변경사항 추출
    Returns: {필드명: (이전값, 이후값)}
    """
    changes = {}
    compare_fields = ["weapon", "gender", "age_group", "category"]

    for field in compare_fields:
        old_val = original.get(field)
        new_val = normalized.get(field)

        if old_val != new_val:
            changes[field] = (old_val, new_val)

    return changes
