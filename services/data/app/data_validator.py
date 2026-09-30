"""
데이터 무결성 검증 시스템 (Data Integrity Validator)

모든 선수/이벤트에서 논리적 오류를 자동 탐지.
서버 시작 시 자동 실행 + API 엔드포인트로 수동 호출 가능.

범위 주의: 이 모듈은 넘겨받은 competitions 만 본다. 프로덕션 Guardian
(`app/data_guardian.py`)은 **최근 N개 대회만** 넘긴다(일일 20, 그 외 50 / 전체 148개).
전 연도 전수 검증은 `scripts/run_validation.py` 뿐이다(약 14분).

검증 규칙:
  이벤트 레벨:
    R1: full_bouts 내부 중복 (동일 player1+player2+round)
    R1a: self-bout (player1 == player2) — raw bout 을 직접 본다 (ERROR)
    R1c: 라운드 정원 초과 = 팬텀 경기 (ERROR)
    R26: final_rankings 에 1위/2위 결손 또는 중복 (ERROR)
    R27: final_rankings 에 로스터(풀·DE·참가자)에 없는 이름 (WARNING)
    R28: DE 슬롯이 한 이름으로 뭉개짐 (ERROR: 내용 중복 / WARNING: 동명이인 가능)
    R2: winner_name 일관성 (winner ∉ {player1, player2})
    R3: 점수 범위 이상 (DE > 15, 음수, 동점인데 승자 있음)
    R4: 빈 round_name / 비표준 round_name
    R5: bracket 토폴로지 위반 (round N 승자가 round N+1에 없음)
    R6: final_rankings vs DE bracket 불일치

  선수 레벨:
    R7: 이벤트 내 동일 라운드 2경기 이상 (내용 중복=ERROR / 동명이인 설명 가능=WARNING)
    R8: 라운드 진행 보존법칙 — 이긴 라운드의 다음 라운드에 선수가 없음
        (2026-09-28 수정: 라운드를 5칸으로 뭉쳐 비교하던 산술 오류로 ERROR 3,488건이
         전부 오탐이었다. 실제 라운드 단위 비교로 교체 → 같은 데이터에서 2건)
    R9: Pool 경기수 이상 (한 이벤트 pool_bouts > 8)
    R10: 성별 불일치 (남/여 종목 동시 출전)
    R11: 나이그룹 역행 (시간 지나면 나이그룹은 올라가거나 유지)
    R12: 무기 3종 이상 (동명이인 의심)
    R13: 같은 대회(날짜)에서 다른 소속 출전 (동명이인 미등록 의심)
    R14: 같은 이벤트 final_rankings에 같은 이름 2회+ 등장 (같은 팀 동명이인)
    R15: bracket_size vs bout count 일관성 (bracket_size가 bout 수에 비해 너무 작음)
    R16: Dual DE 완전성 (second_de에 bouts/seeding 누락)
    R17: Final rankings vs DE 결승 승자 불일치 (강화된 R6, raw bouts 직접 탐색)
    R18: KFF 외부 소스 비교 (옵션 - 기본 비활성, validate_external()로 호출)
    R19: 이벤트 레벨 vs 참가자 org_type 교차 검증 (org_cache 필요)
    R20: 같은 학교 레벨(중/고)인데 다른 도/광역시 → 동명이인 의심 (org_cache 필요)
    R21: 3년 이상 활동 공백 후 다른 팀에서 재등장 → 동명이인 의심
    R22: pool_total_ranking 존재하나 pool_rounds 비어있음 → 스크래핑 실패 감지
    R23: Pool 기권(Abandon) 감지 — 기권자 존재 시 INFO, 기권 bout이 승/패에 포함됐으면 WARNING
    R24: Dual DE 공유 라운드 유실 — 본선 starting_round(예: 64강)가 예선(first_de)에 없음 (ERROR)
         + dual_de인데 first_de/second_de 한쪽만 데이터가 있는 반쪽 스크래핑 (ERROR)
    R25: Dual DE bout에 de_phase 누락 — 예선/본선 구분 불가 (ERROR, 이벤트 단위 집계)
         + 페이즈 없는 bout끼리 (round_name, match_number) 충돌 = 잠재적 병합 사고 (ERROR)
"""

import asyncio
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set, Tuple
from collections import Counter, defaultdict
from loguru import logger

from app.player_identity import PlayerIdentityResolver, get_team_type
from app.grade_estimator import GradeEstimator
# Dual DE 페이즈 규약은 bracket_utils가 단일 원본이다. 여기서 다시 구현하면
# 검증기와 실제 저장/표시 로직이 서로 다른 기준으로 갈라진다 — 그 순간
# "검증은 통과했는데 화면은 틀린" 상태가 되고, 검증기 자체가 무의미해진다.
from app.bracket_utils import (
    DE_PHASE_QUALIFYING,
    DE_PHASE_MAIN,
    EXPECTED_BOUTS_BY_ROUND,
    get_bout_phase,
    is_bye_bout,
    phase_bout_key,
    normalize_round_name,
)

# KNOWN_HOMONYMS 참조 (등록된 동명이인은 RESOLVED로 다운그레이드)
_KNOWN_HOMONYMS = PlayerIdentityResolver.KNOWN_HOMONYMS


# === 라운드 관련 상수 ===

ROUND_ORDER_LIST = ["256강", "128강", "64강", "32강", "16강", "8강", "4강", "결승"]
ROUND_ORDER_MAP = {r: i for i, r in enumerate(ROUND_ORDER_LIST)}

# round_stats 카테고리 → 라운드 순서 매핑 (server.py 동일)
CATEGORY_ORDER = ["t32_and_below", "t16", "t8", "semifinal", "final"]
CATEGORY_NAMES = {
    "t32_and_below": "~32강",
    "t16": "16강",
    "t8": "8강",
    "semifinal": "4강",
    "final": "결승",
}

# 나이그룹 레벨 (높을수록 상위)
AGE_GROUP_LEVELS = {
    "초등부": 1, "초등": 1,
    "중등부": 2, "중등": 2, "중학": 2,
    "고등부": 3, "고등": 3, "고교": 3,
    "대학부": 4, "대학": 4,
    "일반부": 5, "일반": 5, "시니어": 5,
}


@dataclass
class ValidationIssue:
    """검증 오류 하나"""
    rule_id: str           # "R1", "R2", ...
    severity: str          # "ERROR" | "WARNING" | "RESOLVED"
    player_name: str       # 관련 선수 ("" if event-level)
    event_cd: str          # 관련 이벤트 sub_event_cd
    competition_name: str  # 대회명
    message: str           # 상세 설명
    data: Dict = field(default_factory=dict)  # 증거 데이터

    def to_dict(self) -> Dict:
        return asdict(self)


def get_round_category(round_name: str) -> str:
    """라운드 이름 → 카테고리 매핑 (server.py 동일 로직)

    주의: substring 매칭 금지! "64강"에 "4강"이 포함되어 오분류되는 버그 방지.
    반드시 정규식으로 숫자를 정확히 추출하여 매칭.
    """
    if not round_name:
        return "t32_and_below"
    # 숫자+강 패턴 추출로 정확한 라운드 식별
    num_match = re.search(r'(\d+)강', round_name)
    if num_match:
        round_num = int(num_match.group(1))
        if round_num == 4:
            return "semifinal"
        elif round_num == 8:
            return "t8"
        elif round_num == 16:
            return "t16"
        else:
            return "t32_and_below"  # 32강, 64강, 128강, 256강
    # 숫자+강 패턴이 아닌 경우 키워드 매칭
    if "결승" in round_name and "준결승" not in round_name:
        return "final"
    elif "준결승" in round_name:
        return "semifinal"
    else:
        return "t32_and_below"


def _extract_gender(event_name: str) -> str:
    """이벤트 이름에서 성별 추출"""
    if not event_name:
        return ""
    # 혼합 이벤트 우선 체크 ("남녀" 포함 시 성별 미지정)
    if "남녀" in event_name:
        return ""
    if "남자" in event_name or "남" == event_name[:1]:
        return "M"
    if "여자" in event_name or "여" == event_name[:1]:
        return "F"
    return ""


def _extract_age_group(event_name: str) -> str:
    """이벤트 이름에서 나이그룹 추출"""
    if not event_name:
        return ""
    for group in AGE_GROUP_LEVELS:
        if group in event_name:
            return group
    return ""


def _extract_weapon(event_name: str) -> str:
    """이벤트 이름에서 무기 추출"""
    if not event_name:
        return ""
    for weapon in ["플뢰레", "에페", "사브르"]:
        if weapon in event_name:
            return weapon
    return ""


def _get_proper_bracket_size(participant_count: int) -> int:
    """참가자 수에 적합한 bracket_size (2의 거듭제곱) 반환"""
    if participant_count <= 0:
        return 0
    size = 1
    while size < participant_count:
        size *= 2
    return size


def _get_player_name(bout: Dict, key: str) -> str:
    """bout에서 player1_name 또는 player2_name 추출"""
    name = (bout.get(f"{key}_name") or "").strip()
    if not name:
        obj = bout.get(key)
        if isinstance(obj, dict):
            name = (obj.get("name") or "").strip()
    return name


# 라운드 순서 (낮은 라운드 → 높은 라운드)
_ROUND_PROGRESSION = ["256강", "128강", "64강", "32강", "16강", "8강", "준결승", "결승"]
_ROUND_NEXT = {_ROUND_PROGRESSION[i]: _ROUND_PROGRESSION[i + 1]
               for i in range(len(_ROUND_PROGRESSION) - 1)}


_ROUND_RANK = {r: i for i, r in enumerate(_ROUND_PROGRESSION)}


def _dedup_keep_highest_round(bouts: List[Dict]) -> List[Dict]:
    """동일 선수쌍 중복 제거: 가장 높은 라운드(진행이 늦은 라운드)의 bout만 유지.

    스크래퍼 버그로 같은 경기가 여러 라운드에 저장된 경우,
    예: 32강과 16강에 동일한 경기 → 16강(higher)만 유지.
    이렇게 하면 실제 대회 라운드에 가까운 라벨이 보존됨.
    """
    # pair_key → (round_rank, index, bout) — 가장 높은 라운드 유지
    best_bout: Dict[tuple, tuple] = {}

    for i, bout in enumerate(bouts):
        p1 = _get_player_name(bout, "player1")
        p2 = _get_player_name(bout, "player2")
        if not p1 or not p2:
            best_bout[("_nopair", i)] = (0, i, bout)
            continue

        pair_key = tuple(sorted([p1, p2]))
        rnd = (bout.get("round_name") or bout.get("round") or "").strip()
        rank = _ROUND_RANK.get(rnd, -1)

        if pair_key not in best_bout or rank > best_bout[pair_key][0]:
            best_bout[pair_key] = (rank, i, bout)

    # 원래 순서 유지하면서 반환
    return [bout for _, idx, bout in sorted(best_bout.values(), key=lambda x: x[1])]


def _get_full_bouts_from_bracket(de_bracket: Dict) -> List[Dict]:
    """DE bracket에서 full_bouts 추출 (server.py:123 간소화 버전)"""
    if not de_bracket or not isinstance(de_bracket, dict):
        return []

    if de_bracket.get("format") == "dual_de":
        all_bouts = []
        for sub_key in ("first_de", "second_de"):
            sub_bracket = de_bracket.get(sub_key, {})
            if isinstance(sub_bracket, dict):
                all_bouts.extend(_get_full_bouts_from_bracket(sub_bracket))
        return all_bouts

    full_bouts = (de_bracket.get("full_bouts") or [])
    if full_bouts and isinstance(full_bouts, list):
        result = []
        for b in full_bouts:
            if not isinstance(b, dict):
                continue
            p1 = _get_player_name(b, "player1")
            p2 = _get_player_name(b, "player2")
            # self-bout 제거
            if p1 and p2 and p1 == p2:
                continue
            result.append(b)
        # 중복 제거: 같은 선수쌍이 여러 라운드에 있으면 가장 높은 라운드만 유지
        return _dedup_keep_highest_round(result)

    bouts_by_round = de_bracket.get("bouts_by_round", {})
    if isinstance(bouts_by_round, dict):
        # 스크래퍼 버그 감지: 모든 라운드 키에 전체 브래킷이 복사된 경우
        round_bout_counts = {k: len(v) for k, v in bouts_by_round.items()
                             if isinstance(v, list)}
        counts = list(round_bout_counts.values())
        is_duplicated = False
        if len(counts) >= 2:
            max_count = max(counts)
            same_count = sum(1 for c in counts if c == max_count)
            if same_count >= len(counts) * 0.5 and max_count > 4:
                is_duplicated = True

        if is_duplicated:
            # 가장 많은 bout을 가진 라운드 사용, match_number로 올바른 라운드 재배정
            best_key = max(round_bout_counts, key=round_bout_counts.get)
            raw_bouts = bouts_by_round[best_key]
            bracket_size = de_bracket.get("bracket_size", 0)
            return _reconstruct_bouts_from_duplicated_bbr(raw_bouts, bracket_size)

        result = []
        for round_name, round_bouts in bouts_by_round.items():
            if isinstance(round_bouts, list):
                for bout in round_bouts:
                    if isinstance(bout, dict):
                        b = dict(bout)
                        if "round_name" not in b:
                            b["round_name"] = round_name
                        # self-bout 제거 (Path 1과 동일)
                        p1 = _get_player_name(b, "player1")
                        p2 = _get_player_name(b, "player2")
                        if p1 and p2 and p1 == p2:
                            continue
                        result.append(b)
        return result

    return []


def _reconstruct_bouts_from_duplicated_bbr(
    raw_bouts: list, bracket_size: int
) -> List[Dict]:
    """중복된 bouts_by_round에서 match_number로 올바른 라운드명 재배정"""
    if not raw_bouts or bracket_size < 4:
        return []

    round_ranges = []
    size = bracket_size
    start = 1
    while size >= 2:
        n_matches = size // 2
        round_name = f"{size}강" if size > 4 else ("준결승" if size == 4 else "결승")
        round_ranges.append((start, start + n_matches - 1, round_name))
        start += n_matches
        size //= 2

    def get_round_for_match(match_num: int) -> str:
        for rng_start, rng_end, rnd in round_ranges:
            if rng_start <= match_num <= rng_end:
                return rnd
        return "unknown"

    result = []
    for bout in raw_bouts:
        if not isinstance(bout, dict):
            continue
        b = dict(bout)
        mn = b.get("match_number")
        if mn is not None:
            correct_round = get_round_for_match(int(mn))
            b["round_name"] = correct_round
        # self-bout 제거 (Path 1과 동일)
        p1 = _get_player_name(b, "player1")
        p2 = _get_player_name(b, "player2")
        if p1 and p2 and p1 == p2:
            continue
        result.append(b)
    return result


# === R24/R25 (Dual DE) 전용 헬퍼 ===
#
# 이 헬퍼들이 _get_full_bouts_from_bracket()을 쓰지 않는 이유:
# 그 함수는 self-bout 제거 + 동일 선수쌍 중복 제거(가장 높은 라운드만 유지)를 한다.
# 표시용으로는 옳지만 "유실 감지"에는 치명적이다 — 정리된 뒤의 목록을 세면
# 사라진 경기가 원래 없었던 것처럼 보인다. R24/R25는 저장된 그대로(raw)를 본다.

# R5/R6와 동일한 라운드명 변형 표. 기존 규칙의 지역 상수를 건드리지 않기 위해
# 별도로 둔다(기존 규칙 동작 변경 금지).
_DUAL_DE_ROUND_VARIANTS = {
    "준결승": "4강", "4강전": "4강",
    "결승전": "결승",
    "8강전": "8강", "16강전": "16강", "32강전": "32강",
    "64강전": "64강", "128강전": "128강", "256강전": "256강",
}


def _normalize_de_round(raw: object) -> str:
    """라운드명 정규화. '64강전'/'준결승' 같은 변형 때문에 공유 라운드 대조가
    빗나가면, 실제로는 유실됐는데 R24가 침묵하거나 그 반대가 된다."""
    if not isinstance(raw, str):
        return ""
    name = raw.strip()
    if not name:
        return ""
    name = normalize_round_name(name)
    return _DUAL_DE_ROUND_VARIANTS.get(name, name)


def _bout_round_name(bout: Dict) -> str:
    """bout에서 라운드명 추출 (round_name → round 순)"""
    if not isinstance(bout, dict):
        return ""
    return _normalize_de_round(bout.get("round_name") or bout.get("round") or "")


def _collect_raw_de_bouts(bracket: object) -> List[Dict]:
    """sub-bracket에서 저장된 bout을 가공 없이 수집.

    R16과 동일한 우선순위(full_bouts → bouts → bouts_by_round)를 쓴다.
    한 브래킷이 full_bouts와 bouts에 같은 내용을 중복 보관하는 경우가 있어
    전부 합치면 경기 수가 부풀려지기 때문에, 먼저 채워진 소스 하나만 쓴다.
    first_de/second_de는 None일 수 있다(빈 dict가 아니다) — 반드시 방어한다.
    """
    if not isinstance(bracket, dict) or not bracket:
        return []

    for key in ("full_bouts", "bouts"):
        raw = bracket.get(key)
        if isinstance(raw, list) and raw:
            return [b for b in raw if isinstance(b, dict)]

    bbr = bracket.get("bouts_by_round")
    result: List[Dict] = []
    if isinstance(bbr, dict):
        for round_name, round_bouts in bbr.items():
            if not isinstance(round_bouts, list):
                continue
            for bout in round_bouts:
                if not isinstance(bout, dict):
                    continue
                b = dict(bout)
                if not b.get("round_name"):
                    b["round_name"] = round_name
                result.append(b)
    return result


def _bout_identity(bout: Dict) -> Tuple:
    """같은 bout이 여러 소스(최상위 full_bouts + sub-bracket)에 중복 저장된 것을
    합치기 위한 내용 기반 키.

    🔴 여기서 phase_bout_key()를 쓰면 안 된다. 페이즈가 없는 레코드에서는
    예선 64강 #1과 본선 64강 #1이 **같은 키**가 되어(그게 바로 이 사고의 원인이다)
    서로 다른 경기가 하나로 합쳐진다. 즉 R25가 세어야 할 유실 증거를
    R25 자신이 지워버린다. 선수 이름/점수까지 넣어야 둘이 갈라진다.
    """
    return (
        get_bout_phase(bout),
        _bout_round_name(bout),
        bout.get("match_number"),
        _get_player_name(bout, "player1"),
        _get_player_name(bout, "player2"),
        bout.get("player1_score"),
        bout.get("player2_score"),
    )


def _is_team_event(event_name: str) -> bool:
    """단체전 감지 (R3와 동일 기준). 단체전은 dual DE를 쓰지 않는다."""
    if not event_name:
        return False
    return "단체" in event_name or "(단)" in event_name


def _bout_label(bout: Dict) -> str:
    """로그에 남길 bout 식별 문자열 — 사람이 KFA 페이지에서 바로 찾을 수 있어야 한다."""
    key = phase_bout_key(bout)
    rnd = key[1] or _bout_round_name(bout) or "?"
    num = key[2]
    p1 = _get_player_name(bout, "player1") or "?"
    p2 = _get_player_name(bout, "player2") or "?"
    return f"{rnd} #{num} {p1} vs {p2}"


def _get_dual_de_sub_bouts(de_bracket: Dict) -> Tuple[List[Dict], List[Dict]]:
    """dual_de에서 first_de, second_de 별도 추출 (R7용)"""
    if not de_bracket or not isinstance(de_bracket, dict):
        return [], []
    if de_bracket.get("format") != "dual_de":
        return _get_full_bouts_from_bracket(de_bracket), []

    first = de_bracket.get("first_de", {})
    second = de_bracket.get("second_de", {})
    return (
        _get_full_bouts_from_bracket(first) if isinstance(first, dict) else [],
        _get_full_bouts_from_bracket(second) if isinstance(second, dict) else [],
    )


def _is_self_bout(bout: Dict) -> bool:
    """self-bout 여부 체크 (p1 == p2)"""
    p1 = (bout.get("player1_name") or "").strip()
    p2 = (bout.get("player2_name") or "").strip()
    return bool(p1 and p2 and p1 == p2)


# === 이름 정규화 (동명이인 표식) ===

_STAR_SUFFIX = re.compile(r"(\(\*\))+$")


def canon_player_name(raw: object) -> str:
    """최종순위표의 동명이인 표식 `(*)` 를 떼어 대진표 이름과 대조 가능한 형태로 만든다.

    협회 최종순위표는 같은 종목에 동명이인이 있으면 `김재원(*)` 처럼 별표를 붙이지만
    DE 대진표와 풀 결과에는 별표가 없다. 떼지 않고 비교하면 최종순위의 거의 모든
    동명이인이 "로스터에 없는 이름"으로 잡힌다 — 실측으로 217종목이 걸렸고, 별표를
    떼자 7종목만 남았다(2026-09-28). 즉 210종목이 순수 오탐이었다.
    """
    if not isinstance(raw, str):
        return ""
    return _STAR_SUFFIX.sub("", raw.strip()).strip()


# DE 라운드 진행 순서 (정규화된 이름 기준).
# `_normalize_de_round()` 이 준결승 → 4강 으로 바꾸므로 여기서도 4강 표기를 쓴다.
# '3-4위'(3위 결정전)는 진행 경로가 아니라 곁가지이므로 제외한다 — 준결승 승자는
# 결승으로, 패자는 3-4위로 간다. 이걸 진행 순서에 넣으면 결승 진출자가 3-4위에
# 없다는 이유로 오탐이 난다.
_DE_ROUND_SEQUENCE = ["256강", "128강", "64강", "32강", "16강", "8강", "4강", "결승"]
_DE_ROUND_INDEX = {r: i for i, r in enumerate(_DE_ROUND_SEQUENCE)}


def _collect_phase_bouts(de_bracket: Dict) -> Dict[str, List[Dict]]:
    """이벤트의 DE bout 을 위상별로, 저장된 그대로(raw) 모은다.

    `_get_full_bouts_from_bracket()` 을 쓰지 않는 이유는 R24/R25 와 같다 — 그 함수는
    self-bout 과 동일 선수쌍 중복을 **입력 단계에서 먼저 지운다.** 지워진 목록을 세면
    오염이 애초에 없었던 것처럼 보인다. 오염을 세는 규칙(R1a/R1c/R28)은 raw 를 봐야 한다.

    반환 키: "qualifying" / "main" / "" (위상 개념이 없거나 태깅 안 된 것).
    같은 경기가 최상위 full_bouts 와 sub-bracket 에 이중 저장된 경우가 있어
    `_bout_identity()` 로 합친다.
    """
    if not isinstance(de_bracket, dict) or not de_bracket:
        return {}

    if de_bracket.get("format") == "dual_de":
        first_de = de_bracket.get("first_de") or {}
        second_de = de_bracket.get("second_de") or {}
        flat = de_bracket.get("full_bouts")
        candidates = [b for b in flat if isinstance(b, dict)] if isinstance(flat, list) else []
        if isinstance(first_de, dict):
            candidates += _collect_raw_de_bouts(first_de)
        if isinstance(second_de, dict):
            candidates += _collect_raw_de_bouts(second_de)
    else:
        candidates = _collect_raw_de_bouts(de_bracket)

    merged: Dict[Tuple, Dict] = {}
    for bout in candidates:
        merged.setdefault(_bout_identity(bout), bout)

    grouped: Dict[str, List[Dict]] = defaultdict(list)
    for bout in merged.values():
        grouped[get_bout_phase(bout) or ""].append(bout)
    return dict(grouped)


def _bout_content_key(bout: Dict) -> Tuple:
    """경기 '내용' 키 — 선수쌍과 점수. 라운드/번호는 넣지 않는다.

    팬텀 경기는 빈 슬롯에 **다른 경기의 내용을 그대로 복제**해 넣은 것이므로,
    같은 내용 키가 여러 슬롯에 나타나는 것이 오염의 지문이다.
    """
    return (
        _get_player_name(bout, "player1"),
        _get_player_name(bout, "player2"),
        bout.get("player1_score"),
        bout.get("player2_score"),
    )


class DataValidator:
    """데이터 무결성 검증기"""

    def __init__(self, competitions: List[Dict], org_cache: Optional[Dict[str, Dict[str, str]]] = None,
                 identity_resolver=None):
        self.competitions = competitions
        self.issues: List[ValidationIssue] = []
        # org_cache: {org_name: {org_type, province, city, ...}} from server.py _org_region_cache
        self.org_cache = org_cache or {}
        # identity_resolver: PlayerIdentityResolver — 동명이인이 **실제로 분리됐는지** 판정에 쓴다.
        # 없으면 예전처럼 KNOWN_HOMONYMS(수동 등록) 기준으로만 판정한다.
        self.identity_resolver = identity_resolver
        self._identity_index: Optional[Dict[str, Dict[tuple, Set[str]]]] = None

    # ---------------------------------------------------------------- 동명이인 판정
    def _build_identity_index(self) -> Dict[str, Dict[tuple, Set[str]]]:
        """이름 → {(날짜, 팀): {player_id...}, ("G", 날짜, 성별): {...}, ("A", 날짜, 나이): {...}}

        리졸버가 만든 프로필의 원본 레코드를 훑어 "어느 기록이 어느 사람에게 갔는지"를 만든다.
        이걸로 '같은 날 다른 소속' 같은 충돌이 **서로 다른 프로필로 갈라져 있는지** 본다.
        """
        index: Dict[str, Dict[tuple, Set[str]]] = defaultdict(lambda: defaultdict(set))
        resolver = self.identity_resolver
        if not resolver:
            return index
        for profile in getattr(resolver, "profiles", {}).values():
            name = profile.name
            for rec in getattr(profile, "records", []) or []:
                date = rec.get("comp_date") or ""
                team = (rec.get("team") or "").strip()
                ev = rec.get("event_name") or ""
                if date and team:
                    index[name][(date, team)].add(profile.player_id)
                gender = _extract_gender(ev)
                if date and gender:
                    index[name][("G", date, gender)].add(profile.player_id)
                age = rec.get("age_group") or ""
                if date and age:
                    index[name][("A", date, age)].add(profile.player_id)
        return index

    def _profiles_attribute_pure(self, name: str, attr: str) -> Optional[str]:
        """이름의 모든 프로필이 그 속성으로 **각각 하나**만 갖는지. 그렇다면 설명 문구.

        성별은 사람의 불변 속성이고(제1원칙), 나이그룹은 시간이 지나면 올라가기만 한다.
        한 이름에 남·여가 섞여 있어도 **프로필마다는 한 성별뿐**이면, 그 이름은 이미
        서로 다른 사람으로 갈라져 있다는 뜻이다. 날짜별 충돌이 아니라 '경력 전체' 신호는
        이렇게 본다(날짜 키로는 대조할 대상이 없다).
        """
        resolver = self.identity_resolver
        if not resolver:
            return None
        pids = getattr(resolver, "name_to_profiles", {}).get(name) or []
        profiles = [resolver.profiles[p] for p in pids if p in getattr(resolver, "profiles", {})]
        if len(profiles) < 2:
            return None
        for profile in profiles:
            values = set()
            for rec in getattr(profile, "records", []) or []:
                v = _extract_gender(rec.get("event_name") or "") if attr == "gender" else (rec.get("age_group") or "")
                if v:
                    values.add(v)
            if len(values) > 1:
                return None  # 이 프로필 안에서 이미 섞여 있다 → 분리가 설명하지 못한다
        label = "성별" if attr == "gender" else "연령대"
        return f"프로필 {len(profiles)}개가 각각 한 {label}만 가짐 → 분리 완료"

    def _homonym_separated(self, name: str, keys: List[tuple]) -> Optional[str]:
        """충돌하는 기록들이 서로 다른 프로필에 들어가 있으면 설명 문구를, 아니면 None.

        판정 기준(2026-09-29 확정): **수동 등록 목록이 아니라 실제 분리 결과**로 본다.
        등록 목록(KNOWN_HOMONYMS)은 자동 규칙으로 못 가르는 예외를 손으로 지정하는 수단이지,
        "이 이름은 처리됐다"는 표식이 아니다. 예전 판정은 등록 여부만 봤기 때문에, 리졸버가
        이미 300명을 갈라 놓은 뒤에도 전부 ERROR 로 남아 있었다(2026-09-28 전수 검증에서
        R13 300명 전원이 '이미 분리됨'이었다).
        """
        if self._identity_index is None:
            self._identity_index = self._build_identity_index()
        per_name = self._identity_index.get(name)
        if not per_name:
            return None
        id_sets = [per_name.get(k) or set() for k in keys]
        if any(not s for s in id_sets):
            return None
        # 서로 겹치지 않는 조합이 하나라도 있으면 '다른 사람으로 갈라져 있다'
        for i in range(len(id_sets)):
            for j in range(i + 1, len(id_sets)):
                if not (id_sets[i] & id_sets[j]):
                    total = len({pid for s in id_sets for pid in s})
                    return f"프로필 {total}개로 분리됨 → 서로 다른 사람으로 처리 완료"
        return None

    def validate_all(self) -> List[ValidationIssue]:
        """전체 검증: 이벤트 레벨 + 선수 레벨"""
        self.issues = []
        self._validate_all_events()
        self._validate_all_players()
        return self.issues

    def validate_player(self, player_name: str) -> List[ValidationIssue]:
        """특정 선수만 검증"""
        self.issues = []
        records = self._collect_player_records(player_name)
        if records:
            self._validate_player_records(player_name, records)
        return self.issues

    # =========================================================================
    # 이벤트 레벨 검증 (R1 ~ R6)
    # =========================================================================

    def _validate_all_events(self):
        """모든 이벤트의 DE bracket + final_rankings 검증"""
        for comp in self.competitions:
            comp_info = comp.get("competition", {})
            comp_name = comp_info.get("name", "알 수 없는 대회")

            for event in (comp.get("events") or []):
                event_cd = event.get("sub_event_cd", "")
                event_name = event.get("event_name", "") or event.get("name", "")

                # R14: 같은 이벤트 같은 이름 중복 (DE 유무와 무관)
                self._check_r14_same_event_duplicate_names(
                    event, event_cd, comp_name, event_name
                )

                # R22: Pool 완전성 체크 (DE 유무와 무관)
                self._check_r22_pool_completeness(
                    event, event_cd, comp_name, event_name
                )

                # R23: Pool 기권(Abandon) 감지
                self._check_r23_pool_forfeit(
                    event, event_cd, comp_name, event_name
                )

                # R26/R27: final_rankings 자체 건전성 (DE 유무와 무관)
                self._check_r26_final_ranking_structure(
                    event, event_cd, comp_name, event_name
                )
                self._check_r27_final_ranking_roster(
                    event, event_cd, comp_name, event_name
                )

                # R19: 이벤트 레벨 vs 참가자 org_type 교차 검증
                if self.org_cache:
                    self._check_r19_event_level_vs_org_type(
                        event, event_cd, comp_name, event_name
                    )

                de_bracket = event.get("de_bracket", {})

                if not isinstance(de_bracket, dict) or not de_bracket:
                    continue

                # R15-R17: bracket/dual_de 구조 검증 (full_bouts 추출 전에 실행)
                self._check_r15_bracket_size_consistency(
                    event, event_cd, comp_name, event_name, de_bracket
                )
                self._check_r16_dual_de_completeness(
                    event, event_cd, comp_name, event_name, de_bracket
                )
                self._check_r17_final_rankings_vs_de_winner(
                    event, event_cd, comp_name, event_name, de_bracket
                )
                # R24/R25: dual_de 전용. 두 규칙 모두 내부에서 format을 확인하므로
                # 단일 DE/단체전에서는 즉시 반환된다(무해).
                self._check_r24_dual_de_shared_round(
                    event, event_cd, comp_name, event_name, de_bracket
                )
                self._check_r25_de_phase_tagging(
                    event, event_cd, comp_name, event_name, de_bracket
                )

                # R1a/R1c/R28: 팬텀 경기 계열. 반드시 `_get_full_bouts_from_bracket()`
                # **앞에서** raw 로 돌린다 — 그 함수가 self-bout 과 중복을 먼저 지우므로
                # 뒤에서 돌리면 세려는 증거가 이미 없다 (R1a 가 0건이던 원인).
                self._check_r1a_self_bouts(event_cd, comp_name, event_name, de_bracket)
                self._check_r1c_phantom_bouts(event_cd, comp_name, event_name, de_bracket)
                self._check_r28_de_name_collapse(event_cd, comp_name, event_name, de_bracket)

                full_bouts = _get_full_bouts_from_bracket(de_bracket)
                if not full_bouts:
                    continue

                self._check_r1_duplicate_bouts(
                    full_bouts, event_cd, comp_name, event_name
                )
                self._check_r2_winner_consistency(
                    full_bouts, event_cd, comp_name, event_name
                )
                self._check_r3_score_anomaly(
                    full_bouts, event_cd, comp_name, event_name
                )
                self._check_r4_round_name(
                    full_bouts, event_cd, comp_name, event_name
                )
                self._check_r5_bracket_topology(
                    full_bouts, event_cd, comp_name, event_name, de_bracket
                )
                self._check_r6_ranking_bracket_mismatch(
                    event, event_cd, comp_name, full_bouts
                )

    def _check_r1_duplicate_bouts(
        self, full_bouts: List[Dict], event_cd: str, comp_name: str, event_name: str
    ):
        """R1: full_bouts 내 동일 bout 중복 (R1a: self-bout, R1b: 진짜 중복)"""
        seen = {}
        for bout in full_bouts:
            if bout.get("is_bye"):
                continue
            p1 = (bout.get("player1_name") or "").strip()
            p2 = (bout.get("player2_name") or "").strip()
            rnd = (bout.get("round_name") or bout.get("round") or "").strip()
            if not p1 or not p2 or not rnd:
                continue

            # self-bout 분리 (스크래퍼 버그: player1 == player2)
            # ⚠️ 이 분기는 실질적으로 도달하지 않는다 — full_bouts 는
            # `_get_full_bouts_from_bracket()` 이 self-bout 을 이미 지운 목록이다.
            # 실제 R1a 탐지는 raw 를 보는 `_check_r1a_self_bouts()` 가 한다.
            # 다른 호출자가 필터 없는 목록을 넘기는 경우를 위해 남겨 둔다.
            if p1 == p2:
                self.issues.append(ValidationIssue(
                    rule_id="R1a",
                    severity="ERROR",
                    player_name=p1,
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=f"[{event_name}] self-bout: {p1} vs {p1} @ {rnd} (스크래퍼 버그)",
                    data={"player": p1, "round": rnd},
                ))
                continue

            # 순서 무관 키 (진짜 중복 체크)
            key = (tuple(sorted([p1, p2])), rnd)
            if key in seen:
                self.issues.append(ValidationIssue(
                    rule_id="R1b",
                    severity="ERROR",
                    player_name="",
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=f"[{event_name}] 중복 bout: {p1} vs {p2} @ {rnd}",
                    data={"player1": p1, "player2": p2, "round": rnd, "count": seen[key] + 1},
                ))
            seen[key] = seen.get(key, 0) + 1

    # =========================================================================
    # R1a / R1c / R28: 팬텀 경기 계열 — raw bout 을 직접 본다
    #
    # 2026-09-28 에 확인된 오염: 참가자가 7명뿐인 32 브래킷 종목(event 1440)에서
    # 빈 슬롯 12개에 '정효정' 이라는 **한 이름이 양쪽에 복제**되고 점수까지 15-1 로
    # 똑같이 들어가 있었다. 같은 형태가 2019~2025 에 걸쳐 89종목 1,218경기.
    # self-bout 이름은 전수에서 단 하나('정효정')였다 — 즉 직전 파싱의 잔류값이
    # 빈 슬롯에 새는 스크래퍼 버그이고, 특정 대회의 특성이 아니다.
    # =========================================================================

    def _check_r1a_self_bouts(
        self, event_cd: str, comp_name: str, event_name: str, de_bracket: Dict
    ):
        """R1a: DE 에 player1 == player2 인 자기경기 (ERROR, 이벤트×이름 단위 집계)

        🔴 이 규칙은 2026-09-28 까지 **한 번도 발동할 수 없었다.**
        R1 은 `_get_full_bouts_from_bracket()` 의 반환값을 받는데 그 함수가 세 경로 모두에서
        `p1 == p2` 를 먼저 버린다. 세려던 증거를 입력에서 지운 셈이다. 실측으로 전수 검증
        리포트의 R1a 는 0건이었지만 DB 에는 자기경기 1,218개(89종목)가 남아 있었다.
        그래서 여기서는 raw bout 을 직접 본다.

        자기경기는 실제 펜싱에서 불가능하다 — 같은 사람이 피스트 양쪽에 설 수 없다.
        동명이인 두 명이 맞붙는 것과는 다르다. 협회 순위표는 동명이인을 `(*)` 로 갈라
        적고(→ `canon_player_name()`), 경기마다 점수가 다르다. 반면 이 오염은 점수까지
        복제돼 있어 `identical_score` 로 구분된다.

        bout 하나당 이슈를 만들면 1,218건이 리포트를 덮으므로 (이벤트, 이름)당 1건으로
        집계하고 샘플만 첨부한다.
        """
        by_name: Dict[str, List[Dict]] = defaultdict(list)
        for bouts in _collect_phase_bouts(de_bracket).values():
            for bout in bouts:
                p1 = _get_player_name(bout, "player1")
                if p1 and p1 == _get_player_name(bout, "player2"):
                    by_name[p1].append(bout)

        for name, bouts in by_name.items():
            scores = {(b.get("player1_score"), b.get("player2_score")) for b in bouts}
            identical = len(scores) == 1 and len(bouts) > 1
            samples = [_bout_label(b) for b in bouts[:5]]
            self.issues.append(ValidationIssue(
                rule_id="R1a",
                severity="ERROR",
                player_name=name,
                event_cd=event_cd,
                competition_name=comp_name,
                message=(
                    f"[{event_name}] self-bout {len(bouts)}경기: '{name}' 이 양쪽에 동시 배치"
                    + (f" (점수까지 전부 동일 {sorted(scores)[0]} → 빈 슬롯에 복제된 팬텀)"
                       if identical else "")
                    + f". 샘플: {'; '.join(samples)}"
                ),
                data={
                    "player": name,
                    "bout_count": len(bouts),
                    "identical_score": identical,
                    "distinct_scores": len(scores),
                    "sample_bouts": samples,
                },
            ))

    def _check_r1c_phantom_bouts(
        self, event_cd: str, comp_name: str, event_name: str, de_bracket: Dict
    ):
        """R1c: 한 라운드의 실제 경기 수가 브래킷 정원을 넘음 = 팬텀 경기 (ERROR)

        16강은 최대 8경기, 32강은 16경기다 (`EXPECTED_BOUTS_BY_ROUND`). 그보다 많으면
        존재하지 않는 경기가 빈 슬롯에 채워졌다는 뜻이다. 부전승은 경기가 아니므로
        `is_bye_bout()` 기준으로 빼고 센다 (CLAUDE.md "슬롯 수 ≠ 경기 수").

        ⚠️ dual_de 인데 de_phase 가 없는 레코드는 건너뛴다. 예선 64강 32경기와 본선 64강
        32경기가 같은 칸에 쌓여 64 > 32 로 보이지만, 그건 정원 초과가 아니라 위상 누락이고
        R25 가 이미 ERROR 로 잡는다. 여기서 또 세면 같은 사실이 두 규칙에서 중복 계상된다.
        """
        phases = _collect_phase_bouts(de_bracket)
        if not phases:
            return
        if de_bracket.get("format") == "dual_de" and set(phases) == {""}:
            return  # 위상 누락 — R25 담당

        for phase, bouts in phases.items():
            by_round: Dict[str, List[Dict]] = defaultdict(list)
            for bout in bouts:
                if is_bye_bout(bout):
                    continue
                rnd = _bout_round_name(bout)
                if rnd:
                    by_round[rnd].append(bout)

            # 준결승 승자 — 3-4위전 판별에 쓴다 (아래 참조)
            sf_winners = {
                (b.get("winner_name") or "").strip()
                for b in by_round.get("준결승", []) + by_round.get("4강", [])
                if (b.get("winner_name") or "").strip()
            }

            for rnd, round_bouts in by_round.items():
                capacity = EXPECTED_BOUTS_BY_ROUND.get(rnd)
                if not capacity or len(round_bouts) <= capacity:
                    continue
                # ⚠️ '결승' 칸에 경기가 2개인 것은 정상일 수 있다 — 어떤 대회는 **3-4위전을
                # 결승과 같은 칸에 넣는다**(실측 2026-09-28: 2020 국가대표 선발전 남자 에뻬의
                # '결승' 라운드에 김상민-권영준(1-2위전)과 심승한-손태진(3-4위전)이 함께 있다;
                # 유소년 국가대표 선발전 11종목도 같은 형태). 준결승 승자끼리 붙은 경기가
                # 정확히 하나이고 나머지가 준결승 **패자**끼리 붙은 경기면 3-4위전이므로
                # 팬텀이 아니다.
                if rnd in ("결승", "우승") and len(round_bouts) == capacity + 1 and sf_winners:
                    def _pair(b):
                        return {(b.get("player1_name") or "").strip(),
                                (b.get("player2_name") or "").strip()}
                    title_bouts = [b for b in round_bouts if _pair(b) <= sf_winners]
                    third_place = [b for b in round_bouts
                                   if _pair(b) and not (_pair(b) & sf_winners)]
                    if len(title_bouts) == 1 and len(third_place) == len(round_bouts) - 1:
                        continue
                dup = Counter(_bout_content_key(b) for b in round_bouts)
                worst_key, worst_n = dup.most_common(1)[0]
                label = f"{'예선' if phase == DE_PHASE_QUALIFYING else '본선'} " if phase else ""
                self.issues.append(ValidationIssue(
                    rule_id="R1c",
                    severity="ERROR",
                    player_name="",
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=(
                        f"[{event_name}] {label}{rnd} 실제 경기 {len(round_bouts)}개 > 정원 {capacity}개"
                        f" → 빈 슬롯에 팬텀 경기 {len(round_bouts) - capacity}개."
                        + (f" 같은 내용({worst_key[0]} vs {worst_key[1]} "
                           f"{worst_key[2]}-{worst_key[3]})이 {worst_n}회 반복"
                           if worst_n > 1 else "")
                    ),
                    data={
                        "phase": phase or None,
                        "round_name": rnd,
                        "bout_count": len(round_bouts),
                        "capacity": capacity,
                        "excess": len(round_bouts) - capacity,
                        "max_repeated_content": worst_n,
                    },
                ))

    def _check_r28_de_name_collapse(
        self, event_cd: str, comp_name: str, event_name: str, de_bracket: Dict
    ):
        """R28: DE 슬롯이 한 이름으로 뭉개짐 (ERROR / 동명이인 가능성은 WARNING)

        한 선수가 차지할 수 있는 슬롯 수에는 상한이 있다. 단일 DE 는 256강→결승 8라운드,
        dual DE 는 예선 최대 3 + 본선 6 = 9. 실측으로도 오염되지 않은 종목의 최대 점유는
        **9슬롯**(정유준)이었다. 따라서 10슬롯 이상은 구조적으로 불가능하다.

        다만 10슬롯이 항상 팬텀은 아니다 — 같은 종목에 동명이인 두 명이 있으면 한 이름이
        합쳐서 10슬롯을 넘을 수 있다(CLAUDE.md: 제66회 대통령배 4종목 전부 동명이인 2명).
        그래서 등급을 갈라 매긴다:
          ERROR   — 그 이름이 실린 경기의 과반이 **내용까지 중복된** 경기 (= 복제 팬텀)
          WARNING — 중복 증거 없이 슬롯만 많음 (동명이인 가능 → 사람이 확인)
        """
        slots: Dict[str, List[Dict]] = defaultdict(list)
        for bouts in _collect_phase_bouts(de_bracket).values():
            for bout in bouts:
                if is_bye_bout(bout):
                    continue
                for key in ("player1", "player2"):
                    name = _get_player_name(bout, key)
                    if name:
                        slots[name].append(bout)

        for name, bouts in slots.items():
            if len(bouts) < 10:
                continue
            dup = Counter(_bout_content_key(b) for b in bouts)
            repeated = sum(n for n in dup.values() if n > 1)
            is_phantom = repeated * 2 > len(bouts)
            self.issues.append(ValidationIssue(
                rule_id="R28",
                severity="ERROR" if is_phantom else "WARNING",
                player_name=name,
                event_cd=event_cd,
                competition_name=comp_name,
                message=(
                    f"[{event_name}] '{name}' 이 DE 슬롯 {len(bouts)}개 점유 "
                    f"(한 선수의 구조적 상한은 9) — "
                    + ("내용 중복 경기 "
                       f"{repeated}개 → 복제된 팬텀"
                       if is_phantom else "중복 증거 없음 → 동명이인 여부 확인 필요")
                ),
                data={
                    "player": name,
                    "slot_count": len(bouts),
                    "repeated_content_bouts": repeated,
                    "phantom": is_phantom,
                },
            ))

    # =========================================================================
    # R26 / R27: final_rankings 자체의 건전성
    # =========================================================================

    def _check_r26_final_ranking_structure(
        self, event: Dict, event_cd: str, comp_name: str, event_name: str
    ):
        """R26: final_rankings 에 1위/2위가 없거나 둘 이상 (ERROR)

        FIE 규정상 **동률은 3위(3T)만 존재**한다(CLAUDE.md). 1위와 2위는 결승 결과이므로
        각각 정확히 1명이다. 0명이면 순위표가 잘린 것이고, 2명 이상이면 예선 브래킷 기준으로
        잘못 계산된 것이다 — 2025 국가대표 선발대회·제65회 대통령배에서 실제로 1·2위가 없고
        본선 시드 32명이 33~38위로 밀린 오염이 있었다(`scripts/audit_final_rankings.py` F01/F02).

        최종순위는 KFA 가 진실의 원천이므로(제1원칙 5항) 이 규칙이 걸린 종목은 자체 계산으로
        메우지 말고 협회 순위표를 다시 받아야 한다.
        """
        final = event.get("final_rankings")
        if not isinstance(final, list) or not final:
            return

        ranks: List[int] = []
        for entry in final:
            if not isinstance(entry, dict) or not canon_player_name(entry.get("name")):
                continue
            try:
                rank = int(entry.get("rank") or 0)
            except (TypeError, ValueError):
                continue
            if rank > 0:
                ranks.append(rank)
        if not ranks:
            return

        counts = Counter(ranks)
        for place in (1, 2):
            if place == 2 and len(ranks) < 2:
                continue
            got = counts.get(place, 0)
            if got == 1:
                continue
            self.issues.append(ValidationIssue(
                rule_id="R26",
                severity="ERROR",
                player_name="",
                event_cd=event_cd,
                competition_name=comp_name,
                message=(
                    f"[{event_name}] 최종순위 {place}위가 {got}명 (정확히 1명이어야 함) — "
                    f"총 {len(ranks)}명, 최고 순위 {min(ranks)}위. "
                    f"{'순위표가 잘렸거나' if got == 0 else '동률로 잘못 계산됐거나'} "
                    f"예선 기준으로 매겨진 순위표 → KFA 최종순위 재수집 필요"
                ),
                data={
                    "place": place,
                    "count": got,
                    "total_entries": len(ranks),
                    "best_rank": min(ranks),
                },
            ))

    def _check_r27_final_ranking_roster(
        self, event: Dict, event_cd: str, comp_name: str, event_name: str
    ):
        """R27: final_rankings 에 그 종목 로스터(풀·DE·시딩·참가자)에 없는 이름 (WARNING)

        순위표에만 있고 어디에서도 경기하지 않은 이름은 ⑴ 다른 종목의 순위표가 섞였거나
        ⑵ 팬텀 이름이 순위표까지 올라온 경우다 (실측: 종목 2개의 final_rankings 가
        '정효정' 1명뿐이었다).

        오탐을 줄이는 두 장치:
          · 이름은 `canon_player_name()` 으로 `(*)` 를 떼고 비교한다. 안 떼면 동명이인
            표식 때문에 217종목이 걸린다(실측) — 떼면 7종목.
          · 로스터 자체가 결손이면(로스터 < 순위표의 80%) 판정하지 않는다. 그건 순위표가
            아니라 풀/DE 가 없는 문제이고 R22·감사 F07/F10 이 담당한다.
        등급은 WARNING — 풀 데이터가 부분 결손인 정상 종목도 있어 사람이 확인해야 한다.
        """
        if _is_team_event(event_name):
            return
        final = event.get("final_rankings")
        if not isinstance(final, list) or not final:
            return

        final_names = [canon_player_name(f.get("name")) for f in final if isinstance(f, dict)]
        final_names = [n for n in final_names if n]
        if not final_names:
            return

        roster: Set[str] = set()
        for pool in (event.get("pool_rounds") or []):
            if isinstance(pool, dict):
                for row in (pool.get("results") or []):
                    if isinstance(row, dict):
                        name = canon_player_name(row.get("name"))
                        if name:
                            roster.add(name)
        for row in (event.get("pool_total_ranking") or []):
            if isinstance(row, dict):
                name = canon_player_name(row.get("name"))
                if name:
                    roster.add(name)
        for row in (event.get("participants") or []):
            if isinstance(row, dict):
                name = canon_player_name(row.get("name"))
                if name:
                    roster.add(name)

        de_bracket = event.get("de_bracket")
        if isinstance(de_bracket, dict) and de_bracket:
            for bouts in _collect_phase_bouts(de_bracket).values():
                for bout in bouts:
                    for key in ("player1", "player2"):
                        name = canon_player_name(_get_player_name(bout, key))
                        if name:
                            roster.add(name)
            seeds = [de_bracket]
            seeds += [de_bracket.get("first_de") or {}, de_bracket.get("second_de") or {}]
            for src in seeds:
                if not isinstance(src, dict):
                    continue
                for key in ("seeding", "seeded_players", "first_de_qualifiers"):
                    for row in (src.get(key) or []):
                        if isinstance(row, dict):
                            name = canon_player_name(row.get("name"))
                            if name:
                                roster.add(name)
                        elif isinstance(row, str):
                            name = canon_player_name(row)
                            if name:
                                roster.add(name)

        if not roster or len(roster) < 0.8 * len(final_names):
            return  # 로스터 결손 — 이 규칙으로 판정할 근거가 없다

        missing = sorted({n for n in final_names if n not in roster})
        if not missing:
            return

        self.issues.append(ValidationIssue(
            rule_id="R27",
            severity="WARNING",
            player_name=missing[0] if len(missing) == 1 else "",
            event_cd=event_cd,
            competition_name=comp_name,
            message=(
                f"[{event_name}] 최종순위에 있으나 풀·DE·참가자 명단 어디에도 없는 이름 "
                f"{len(missing)}명 / {len(final_names)}명 (로스터 {len(roster)}명): "
                f"{', '.join(missing[:6])}"
            ),
            data={
                "missing_names": missing[:20],
                "missing_count": len(missing),
                "final_count": len(final_names),
                "roster_count": len(roster),
            },
        ))

    def _check_r2_winner_consistency(
        self, full_bouts: List[Dict], event_cd: str, comp_name: str, event_name: str
    ):
        """R2: winner_name이 player1도 player2도 아닌 경우"""
        for bout in full_bouts:
            if bout.get("is_bye"):
                continue
            winner = (bout.get("winner_name") or "").strip()
            p1 = (bout.get("player1_name") or "").strip()
            p2 = (bout.get("player2_name") or "").strip()
            rnd = bout.get("round_name") or bout.get("round") or ""

            if not winner or not p1 or not p2:
                continue

            if winner != p1 and winner != p2:
                self.issues.append(ValidationIssue(
                    rule_id="R2",
                    severity="ERROR",
                    player_name="",
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=f"[{event_name}] winner '{winner}' ∉ {{'{p1}', '{p2}'}} @ {rnd}",
                    data={"winner": winner, "player1": p1, "player2": p2, "round": rnd},
                ))

    def _check_r3_score_anomaly(
        self, full_bouts: List[Dict], event_cd: str, comp_name: str, event_name: str
    ):
        """R3: 점수 범위 이상 (단체전은 45점제)"""
        # 단체전 감지: 이벤트 이름에 "단체" 또는 "(단)" 포함
        is_team_event = "단체" in event_name or "(단)" in event_name
        max_score = 45 if is_team_event else 15

        for bout in full_bouts:
            if bout.get("is_bye"):
                continue
            p1_score = bout.get("player1_score")
            p2_score = bout.get("player2_score")
            rnd = bout.get("round_name") or bout.get("round") or ""
            p1 = (bout.get("player1_name") or "").strip()
            p2 = (bout.get("player2_name") or "").strip()

            if p1_score is None or p2_score is None:
                continue

            try:
                s1 = int(p1_score)
                s2 = int(p2_score)
            except (ValueError, TypeError):
                self.issues.append(ValidationIssue(
                    rule_id="R3",
                    severity="WARNING",
                    player_name="",
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=f"[{event_name}] 점수 파싱 불가: {p1_score} vs {p2_score} @ {rnd}",
                    data={"p1_score": str(p1_score), "p2_score": str(p2_score)},
                ))
                continue

            # 음수 점수
            if s1 < 0 or s2 < 0:
                self.issues.append(ValidationIssue(
                    rule_id="R3",
                    severity="ERROR",
                    player_name="",
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=f"[{event_name}] 음수 점수: {p1}({s1}) vs {p2}({s2}) @ {rnd}",
                    data={"p1": p1, "p2": p2, "s1": s1, "s2": s2, "round": rnd},
                ))

            # DE 점수 > max_score (개인전 15, 단체전 45)
            if s1 > max_score or s2 > max_score:
                self.issues.append(ValidationIssue(
                    rule_id="R3",
                    severity="WARNING",
                    player_name="",
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=f"[{event_name}] DE 점수 >{max_score}: {p1}({s1}) vs {p2}({s2}) @ {rnd}",
                    data={"p1": p1, "p2": p2, "s1": s1, "s2": s2, "round": rnd,
                          "is_team": is_team_event, "max_score": max_score},
                ))

            # 동점인데 승자가 있음 (연장전 가능하므로 WARNING)
            winner = (bout.get("winner_name") or "").strip()
            if s1 == s2 and winner and s1 > 0:
                self.issues.append(ValidationIssue(
                    rule_id="R3",
                    severity="WARNING",
                    player_name="",
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=f"[{event_name}] 동점({s1}:{s2})이지만 승자={winner} @ {rnd}",
                    data={"s1": s1, "s2": s2, "winner": winner, "round": rnd},
                ))

    def _check_r4_round_name(
        self, full_bouts: List[Dict], event_cd: str, comp_name: str, event_name: str
    ):
        """R4: 빈 round_name 또는 비표준 값"""
        standard_patterns = re.compile(
            r"^(256|128|64|32|16|8)강(전)?$|^(4강|준결승|결승|결승전|3-4위|3-4위전|3위결정전)$"
        )
        for bout in full_bouts:
            if bout.get("is_bye"):
                continue
            rnd = bout.get("round_name") or bout.get("round") or ""
            rnd = rnd.strip()

            if not rnd:
                p1 = (bout.get("player1_name") or "").strip()
                p2 = (bout.get("player2_name") or "").strip()
                self.issues.append(ValidationIssue(
                    rule_id="R4",
                    severity="ERROR",
                    player_name="",
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=f"[{event_name}] 빈 round_name: {p1} vs {p2}",
                    data={"player1": p1, "player2": p2},
                ))
            elif not standard_patterns.match(rnd):
                # 비표준이지만 카테고리 매핑은 되는지 체크
                cat = get_round_category(rnd)
                if cat == "t32_and_below" and "강" not in rnd:
                    self.issues.append(ValidationIssue(
                        rule_id="R4",
                        severity="WARNING",
                        player_name="",
                        event_cd=event_cd,
                        competition_name=comp_name,
                        message=f"[{event_name}] 비표준 round_name: '{rnd}'",
                        data={"round_name": rnd, "mapped_category": cat},
                    ))

    def _check_r5_bracket_topology(
        self, full_bouts: List[Dict], event_cd: str, comp_name: str, event_name: str,
        de_bracket: Optional[Dict] = None
    ):
        """R5: bracket 토폴로지 위반 — round N 승자가 round N+1에 없음

        준결승/4강전 등 라운드명 변형을 정규화하고,
        비연속 라운드(8강→결승 사이 4강 누락) 시 검증을 건너뜀.
        dual_de 이벤트는 first_de/second_de를 독립 검증.
        """
        # dual_de: first_de/second_de 독립 검증
        if de_bracket and isinstance(de_bracket, dict) and de_bracket.get("format") == "dual_de":
            for sub_key in ("first_de", "second_de"):
                sub_bracket = de_bracket.get(sub_key, {})
                if isinstance(sub_bracket, dict):
                    sub_bouts = _get_full_bouts_from_bracket(sub_bracket)
                    if sub_bouts:
                        self._check_r5_bracket_topology(
                            sub_bouts, event_cd, comp_name,
                            f"{event_name} [{sub_key}]"
                        )
            return

        # 라운드명 정규화 매핑
        ROUND_NORMALIZE = {
            "준결승": "4강", "4강전": "4강",
            "결승전": "결승",
            "8강전": "8강", "16강전": "16강", "32강전": "32강",
            "64강전": "64강", "128강전": "128강", "256강전": "256강",
        }

        def normalize_round(rnd: str) -> str:
            return ROUND_NORMALIZE.get(rnd, rnd)

        # 라운드별 승자/참가자 수집 (정규화된 라운드명 사용)
        winners_by_round: Dict[str, Set[str]] = defaultdict(set)
        participants_by_round: Dict[str, Set[str]] = defaultdict(set)

        for bout in full_bouts:
            if bout.get("is_bye") or _is_self_bout(bout):
                continue
            rnd = normalize_round((bout.get("round_name") or bout.get("round") or "").strip())
            if not rnd:
                continue

            p1 = (bout.get("player1_name") or "").strip()
            p2 = (bout.get("player2_name") or "").strip()
            winner = (bout.get("winner_name") or "").strip()

            if p1:
                participants_by_round[rnd].add(p1)
            if p2:
                participants_by_round[rnd].add(p2)
            if winner:
                winners_by_round[rnd].add(winner)

        # 라운드 순서대로 검증 (정규화된 라운드 기준)
        active_rounds = [r for r in ROUND_ORDER_LIST if r in winners_by_round]

        for i in range(len(active_rounds) - 1):
            curr_round = active_rounds[i]
            next_round = active_rounds[i + 1]

            # 비연속 라운드 체크: ROUND_ORDER_MAP에서 인덱스 차이가 1이 아니면 스킵
            curr_idx = ROUND_ORDER_MAP.get(curr_round, -1)
            next_idx = ROUND_ORDER_MAP.get(next_round, -1)
            if next_idx - curr_idx != 1:
                # 중간 라운드가 누락된 경우 — 검증 의미 없음
                continue

            # 현재 라운드 승자 중 다음 라운드에 없는 사람
            curr_winners = winners_by_round[curr_round]
            next_participants = participants_by_round.get(next_round, set())

            if not next_participants:
                continue

            missing = curr_winners - next_participants
            if missing and len(missing) <= len(curr_winners) * 0.5:
                for name in list(missing)[:5]:
                    self.issues.append(ValidationIssue(
                        rule_id="R5",
                        severity="WARNING",
                        player_name=name,
                        event_cd=event_cd,
                        competition_name=comp_name,
                        message=f"[{event_name}] {curr_round} 승자 '{name}'이 {next_round}에 없음",
                        data={"current_round": curr_round, "next_round": next_round},
                    ))

    def _check_r6_ranking_bracket_mismatch(
        self, event: Dict, event_cd: str, comp_name: str, full_bouts: List[Dict]
    ):
        """R6: final_rankings vs DE bracket 결과 불일치"""
        final_rankings = (event.get("final_rankings") or [])
        event_name = event.get("event_name", "") or event.get("name", "")

        if not final_rankings or not full_bouts:
            return

        # dual_de: 최종 순위는 second_de(본선) 결과와 비교
        de_bracket = event.get("de_bracket", {})
        if isinstance(de_bracket, dict) and de_bracket.get("format") == "dual_de":
            second_de = de_bracket.get("second_de", {})
            if isinstance(second_de, dict):
                full_bouts = _get_full_bouts_from_bracket(second_de)
                if not full_bouts:
                    return

        # 라운드명 정규화
        ROUND_NORMALIZE = {
            "준결승": "4강", "4강전": "4강",
            "결승전": "결승",
            "8강전": "8강", "16강전": "16강", "32강전": "32강",
            "64강전": "64강", "128강전": "128강", "256강전": "256강",
        }

        # DE에서 각 선수의 최고 도달 라운드/탈락 라운드 계산
        player_last_win_round: Dict[str, str] = {}
        player_lost_round: Dict[str, str] = {}

        for bout in full_bouts:
            if bout.get("is_bye") or _is_self_bout(bout):
                continue
            winner = (bout.get("winner_name") or "").strip()
            p1 = (bout.get("player1_name") or "").strip()
            p2 = (bout.get("player2_name") or "").strip()
            rnd_raw = (bout.get("round_name") or bout.get("round") or "").strip()
            rnd = ROUND_NORMALIZE.get(rnd_raw, rnd_raw)

            # winner_name이 없으면 점수로 추론 (dual_de ~50% null)
            if not winner:
                s1 = bout.get("player1_score")
                s2 = bout.get("player2_score")
                try:
                    s1_int = int(s1) if s1 is not None else 0
                    s2_int = int(s2) if s2 is not None else 0
                except (ValueError, TypeError):
                    s1_int, s2_int = 0, 0
                if s1_int > s2_int and s1_int > 0:
                    winner = p1
                elif s2_int > s1_int and s2_int > 0:
                    winner = p2

            if not winner or not rnd:
                continue

            loser = p2 if winner == p1 else p1 if winner == p2 else ""

            # 승자의 최고 승리 라운드
            if winner:
                prev = player_last_win_round.get(winner, "")
                if not prev or ROUND_ORDER_MAP.get(rnd, -1) > ROUND_ORDER_MAP.get(prev, -1):
                    player_last_win_round[winner] = rnd

            # 패자의 탈락 라운드
            if loser:
                player_lost_round[loser] = rnd

        # 1위는 결승 승자여야 함
        for ranking_record in final_rankings:
            name = (ranking_record.get("name") or "").strip()
            rank = ranking_record.get("rank")
            if not name or not rank:
                continue

            if rank == 1:
                last_win = player_last_win_round.get(name, "")
                if last_win and "결승" not in last_win:
                    self.issues.append(ValidationIssue(
                        rule_id="R6",
                        severity="ERROR",
                        player_name=name,
                        event_cd=event_cd,
                        competition_name=comp_name,
                        message=f"[{event_name}] 1위 '{name}'의 최고 승리 라운드가 '{last_win}' (결승 아님)",
                        data={"rank": rank, "last_win_round": last_win},
                    ))
            elif rank == 2:
                lost = player_lost_round.get(name, "")
                if lost and "결승" not in lost:
                    self.issues.append(ValidationIssue(
                        rule_id="R6",
                        severity="WARNING",
                        player_name=name,
                        event_cd=event_cd,
                        competition_name=comp_name,
                        message=f"[{event_name}] 2위 '{name}'의 탈락 라운드가 '{lost}' (결승 아님)",
                        data={"rank": rank, "lost_round": lost},
                    ))

    # =========================================================================
    # 선수 레벨 검증 (R7 ~ R12)
    # =========================================================================

    def _validate_all_players(self):
        """모든 선수의 크로스 이벤트 검증"""
        # 선수별 레코드 수집
        player_records: Dict[str, List[Dict]] = defaultdict(list)

        for comp in self.competitions:
            comp_info = comp.get("competition", {})
            comp_name = comp_info.get("name", "")
            comp_date = comp_info.get("start_date", "")

            for event in (comp.get("events") or []):
                event_cd = event.get("sub_event_cd", "")
                event_name = event.get("event_name", "") or event.get("name", "")

                # 🔴 단체전은 선수 레벨 규칙에서 제외한다 (2026-09-29).
                # 단체전 순위표의 `name` 은 **팀명**이다('K1펜싱클럽', '경기선발', '경남대학교').
                # 이것을 선수로 수집하면 같은 팀이 남자부·여자부에 모두 나갔다는 이유로
                # R10(성별 불일치)이 '동명이인 오염'을 외친다 — 실측 2026-09-29에 R10
                # ERROR 189개 이름 중 상당수가 팀명이었다. 선수 식별기(PlayerIdentityResolver)
                # 는 처음부터 `is_team_event()` 로 단체전을 빼고 있었는데, 검증기만 안 빼고 있었다.
                if _is_team_event(event_name):
                    continue

                # pool_total_ranking에서 선수 수집
                seen_in_event: Set[str] = set()
                for ranking in (event.get("pool_total_ranking") or []):
                    if not isinstance(ranking, dict):
                        continue
                    name = (ranking.get("name") or "").strip()
                    if name:
                        seen_in_event.add(name)
                        player_records[name].append({
                            "event_cd": event_cd,
                            "event_name": event_name,
                            "comp_name": comp_name,
                            "comp_date": comp_date,
                            "rank": ranking.get("rank"),
                            "team": ranking.get("team", ""),
                        })

                # final_rankings에서도 수집 (풀이 없는 종목)
                #
                # 🔴 2026-09-28 수정. 이전 조건은 `if name not in player_records` 였다.
                # 이는 "그 선수가 **다른 대회에서 한 번이라도 수집된 적 있으면** 이 종목의
                # 최종순위는 보지 않는다"는 뜻이어서, 풀이 없는 종목의 기록이 통째로 누락됐다.
                # 협회가 풀을 게시하지 않는 전국체육대회·전국소년체육대회(개인전 96종목)가
                # 정확히 그런 종목이고, 그 선수들은 레코드가 1개도 안 쌓여 `len(records) < 2`
                # 로 걸러져 **선수 레벨 규칙(R7~R13, R20, R21) 전체를 건너뛰었다.**
                # 올바른 가드는 "이 종목에서 이미 풀로 수집했는가" 다 — 같은 종목 중복만 막는다.
                for ranking in (event.get("final_rankings") or []):
                    if not isinstance(ranking, dict):
                        continue
                    name = (ranking.get("name") or "").strip()
                    if name and name not in seen_in_event:
                        player_records[name].append({
                            "event_cd": event_cd,
                            "event_name": event_name,
                            "comp_name": comp_name,
                            "comp_date": comp_date,
                            "rank": ranking.get("rank"),
                            "team": ranking.get("team", ""),
                        })

        # 선수별 검증
        for player_name, records in player_records.items():
            if len(records) < 2:
                continue
            self._validate_player_records(player_name, records)

    def _collect_player_records(self, player_name: str) -> List[Dict]:
        """특정 선수의 레코드 수집"""
        records = []
        player_lower = player_name.lower()

        for comp in self.competitions:
            comp_info = comp.get("competition", {})
            comp_name = comp_info.get("name", "")
            comp_date = comp_info.get("start_date", "")

            for event in (comp.get("events") or []):
                event_cd = event.get("sub_event_cd", "")
                event_name = event.get("event_name", "") or event.get("name", "")

                for ranking in event.get("pool_total_ranking", []):
                    name = (ranking.get("name") or "").strip()
                    if name.lower() == player_lower:
                        records.append({
                            "event_cd": event_cd,
                            "event_name": event_name,
                            "comp_name": comp_name,
                            "comp_date": comp_date,
                            "rank": ranking.get("rank"),
                            "team": ranking.get("team", ""),
                        })

                for ranking in (event.get("final_rankings") or []):
                    name = (ranking.get("name") or "").strip()
                    if name.lower() == player_lower:
                        # 이미 pool에서 추가된 이벤트인지 체크
                        already = any(r["event_cd"] == event_cd for r in records)
                        if not already:
                            records.append({
                                "event_cd": event_cd,
                                "event_name": event_name,
                                "comp_name": comp_name,
                                "comp_date": comp_date,
                                "rank": ranking.get("rank"),
                                "team": ranking.get("team", ""),
                            })

        return records

    def _validate_player_records(self, player_name: str, records: List[Dict]):
        """한 선수의 레코드 검증 (R7 ~ R13, R20 ~ R21)"""
        self._check_r7_event_round_dup(player_name, records)
        self._check_r8_round_progression(player_name, records)
        self._check_r9_pool_bout_count(player_name, records)
        self._check_r10_gender_inconsistency(player_name, records)
        self._check_r11_age_regression(player_name, records)
        self._check_r12_weapon_count(player_name, records)
        self._check_r13_same_date_multi_team(player_name, records)
        self._check_r20_same_school_level_diff_province(player_name, records)
        self._check_r21_activity_gap(player_name, records)

    def _check_r7_event_round_dup(self, player_name: str, records: List[Dict]):
        """R7: 한 이벤트 내 동일 라운드 2경기 이상

        dual_de 이벤트는 first_de/second_de를 독립 검증
        (같은 라운드명이라도 서로 다른 브라켓이면 정상)
        """
        player_lower = player_name.lower()

        for comp in self.competitions:
            comp_info = comp.get("competition", {})
            comp_name = comp_info.get("name", "")

            for event in (comp.get("events") or []):
                event_cd = event.get("sub_event_cd", "")
                event_name = event.get("event_name", "") or event.get("name", "")
                de_bracket = event.get("de_bracket", {})

                if not isinstance(de_bracket, dict):
                    continue

                # 같은 종목 순위표에 이 이름이 서로 다른 소속으로 올라와 있으면
                # 동명이인 두 명이 그 종목에 함께 출전한 것이다 — 그러면 한 라운드에
                # "그 이름"의 경기가 2개인 것은 정상이다. 등급 판정에 쓴다(아래 참조).
                homonym_teams = self._r7_event_team_count(event, player_lower)

                # dual_de: 서브브라켓별 독립 검증
                if isinstance(de_bracket, dict) and de_bracket.get("format") == "dual_de":
                    first_bouts, second_bouts = _get_dual_de_sub_bouts(de_bracket)
                    for label, bouts in [("first_de", first_bouts), ("second_de", second_bouts)]:
                        self._r7_count_rounds(
                            player_lower, player_name, bouts,
                            event_cd, event_name, comp_name, label, homonym_teams
                        )
                else:
                    full_bouts = _get_full_bouts_from_bracket(de_bracket)
                    self._r7_count_rounds(
                        player_lower, player_name, full_bouts,
                        event_cd, event_name, comp_name, "", homonym_teams
                    )

    @staticmethod
    def _r7_event_team_count(event: Dict, player_lower: str) -> int:
        """이 종목 순위표에서 이 이름이 몇 개의 서로 다른 소속으로 나타나는가.

        2 이상이면 그 종목에 동명이인이 함께 출전했다는 뜻이다. 협회 순위표는 이 경우
        이름에 `(*)` 를 붙이므로(→ `canon_player_name()`) 별표를 뗀 이름으로 센다.
        """
        teams: Set[str] = set()
        for source in ("final_rankings", "pool_total_ranking"):
            for row in (event.get(source) or []):
                if not isinstance(row, dict):
                    continue
                if canon_player_name(row.get("name")).lower() == player_lower:
                    team = (row.get("team") or "").strip()
                    if team:
                        teams.add(team)
        return len(teams)

    def _r7_count_rounds(
        self, player_lower: str, player_name: str, bouts: List[Dict],
        event_cd: str, event_name: str, comp_name: str, bracket_label: str,
        homonym_teams: int = 0,
    ):
        """R7 보조: bout 리스트에서 라운드별 중복 체크.

        한 선수가 한 라운드에서 두 경기를 치를 수는 없다. 그래도 이름 기준으로는 두 경기가
        정당하게 나올 수 있다 — **같은 종목에 동명이인 두 명**이 있는 경우다. CLAUDE.md 실측:
        제66회 대통령배 dual 종목 4개가 전부 동명이인 2명씩이었다(김민서·김나연·김도영 …).

        그래서 2026-09-28 부터 등급을 갈라 매긴다:
          ERROR   — 두 경기의 **내용(선수쌍+점수)이 같음** = 복제된 팬텀, 또는
                    순위표에 이 이름의 소속이 하나뿐 = 동명이인으로 설명되지 않음
          WARNING — 순위표에 이 이름이 2개 이상의 소속으로 있음 = 동명이인으로 설명 가능
        이렇게 하면 "사람이 봐야 하는 것"과 "데이터가 깨진 것"이 리포트에서 갈라진다.
        """
        by_round: Dict[str, List[Dict]] = defaultdict(list)
        seen_bouts: Set[tuple] = set()

        for bout in bouts:
            if bout.get("is_bye") or _is_self_bout(bout):
                continue
            p1 = (bout.get("player1_name") or "").strip().lower()
            p2 = (bout.get("player2_name") or "").strip().lower()
            rnd = (bout.get("round_name") or bout.get("round") or "").strip()

            if player_lower in (p1, p2) and rnd:
                opponent = p2 if player_lower == p1 else p1
                bout_key = (rnd, opponent)
                if bout_key in seen_bouts:
                    continue
                seen_bouts.add(bout_key)
                by_round[rnd].append(bout)

        bracket_info = f" [{bracket_label}]" if bracket_label else ""
        for rnd, round_bouts in by_round.items():
            count = len(round_bouts)
            if count <= 1:
                continue

            contents = Counter(_bout_content_key(b) for b in round_bouts)
            duplicated = any(n > 1 for n in contents.values())
            explained = homonym_teams >= 2 and not duplicated

            if duplicated:
                reason = "두 경기의 선수쌍·점수가 동일 → 복제된 팬텀 경기"
            elif explained:
                reason = (f"순위표에 이 이름이 소속 {homonym_teams}곳으로 등재 "
                          f"→ 동명이인 {homonym_teams}명으로 설명 가능 (확인 필요)")
            else:
                reason = "순위표상 소속이 하나 → 동명이인으로 설명되지 않음"

            self.issues.append(ValidationIssue(
                rule_id="R7",
                severity="WARNING" if explained else "ERROR",
                player_name=player_name,
                event_cd=event_cd,
                competition_name=comp_name,
                message=(
                    f"[{event_name}]{bracket_info} '{player_name}'이 {rnd}에서 "
                    f"{count}경기 (한 선수는 한 라운드에 1경기) — {reason}"
                ),
                data={
                    "round": rnd,
                    "bout_count": count,
                    "bracket": bracket_label,
                    "homonym_team_count": homonym_teams,
                    "duplicated_content": duplicated,
                    "opponents": [
                        f"{_get_player_name(b, 'player1')} vs {_get_player_name(b, 'player2')}"
                        for b in round_bouts[:4]
                    ],
                },
            ))

    def _check_r8_round_progression(self, player_name: str, records: List[Dict]):
        """R8: 라운드 진행 보존법칙 — 어떤 라운드를 이겼으면 다음 라운드에 있어야 한다.

        🔴 2026-09-28 규칙 수정 (오탐 제거).
        이전 구현은 라운드를 `CATEGORY_ORDER` 5칸으로 **뭉쳐서** 비교했다. 그런데
        `get_round_category()` 는 256강·128강·64강·32강을 모두 `t32_and_below` 한 칸에 넣는다.
        그래서 64강을 이기고 32강도 이긴 뒤 16강을 한 번 치른 **정상적인 선수**가
        "~32강 승리 2회 → 16강 출전 1회 (1경기 유실)" 로 걸렸다. 전수 검증 3,488건 ERROR 의
        표본이 전부 이 형태였다 — 데이터 오류가 아니라 규칙의 산술 오류다.

        수정: 뭉치지 않고 **실제 라운드**(`_DE_ROUND_SEQUENCE`) 를 그대로 쓴다. 보존법칙은
        라운드 단위로만 성립한다 — 한 라운드에서 이긴 선수는 그 브래킷에 존재하는 다음
        라운드에 반드시 등장한다.

        판정 시 두 가지를 반드시 지킨다:
          · **다음 라운드는 '그 브래킷에 실재하는' 다음 라운드**다. 32강이 없는 브래킷에서
            64강 승자는 16강에 나타난다. 이름표 순서로 +1 하면 오탐이 난다.
          · **부전승도 출전으로 본다.** 부전승은 경기가 아니지만(CLAUDE.md) 그 라운드에
            선수가 있었다는 증거다. 빼고 세면 부전승으로 올라간 선수가 유실로 잡힌다.

        dual DE 는 예선/본선을 독립 브래킷으로 따로 검증한다 — 예선 64강 승자가 본선 64강에
        없는 것은 정상이다(본선은 시드 재배정).
        """
        for comp in self.competitions:
            comp_name = comp.get("competition", {}).get("name", "")

            for event in (comp.get("events") or []):
                event_cd = event.get("sub_event_cd", "")
                event_name = event.get("event_name", "") or event.get("name", "")
                de_bracket = event.get("de_bracket", {})
                if not isinstance(de_bracket, dict) or not de_bracket:
                    continue

                if de_bracket.get("format") == "dual_de":
                    for label in ("first_de", "second_de"):
                        sub = de_bracket.get(label) or {}
                        if isinstance(sub, dict):
                            sub_bouts = _get_full_bouts_from_bracket(sub)
                            if sub_bouts:
                                self._r8_validate_bouts(
                                    player_name, sub_bouts,
                                    event_cd, f"{event_name} [{label}]", comp_name
                                )
                    continue

                full_bouts = _get_full_bouts_from_bracket(de_bracket)
                if full_bouts:
                    self._r8_validate_bouts(
                        player_name, full_bouts, event_cd, event_name, comp_name
                    )

    def _r8_validate_bouts(
        self, player_name: str, full_bouts: List[Dict],
        event_cd: str, event_name: str, comp_name: str
    ):
        """R8 보조: 한 브래킷 안에서 실제 라운드 단위로 보존법칙 검증."""
        player_lower = player_name.lower()

        # 이 브래킷에 실재하는 라운드 (부전승 포함 — 라운드의 존재 여부 판단용)
        present_rounds: Set[str] = set()
        # 선수가 등장한 라운드 (부전승 포함 = 그 라운드에 있었다는 증거)
        appeared: Set[str] = set()
        # 선수가 이긴 라운드 (부전승 제외 — 실제 대결에서 이긴 것만)
        won: Set[str] = set()

        for bout in full_bouts:
            rnd = _normalize_de_round(bout.get("round_name") or bout.get("round") or "")
            if rnd not in _DE_ROUND_INDEX:
                continue
            present_rounds.add(rnd)

            p1 = _get_player_name(bout, "player1").strip().lower()
            p2 = _get_player_name(bout, "player2").strip().lower()
            if player_lower not in (p1, p2):
                continue
            appeared.add(rnd)

            if is_bye_bout(bout) or _is_self_bout(bout):
                continue
            # winner_name 은 자주 비어 있다 — 실측으로 한 종목의 32경기 중 승자 필드가
            # 채워진 것이 절반이 안 됐다(점수는 다 있었다). winner_name 만 보면 규칙이
            # 조용히 눈을 감는다(오탐이 아니라 미탐). 그래서 점수로 보완한다.
            if self._r17_extract_winner(bout).strip().lower() == player_lower:
                won.add(rnd)

        if not won:
            return

        ordered = sorted(present_rounds, key=lambda r: _DE_ROUND_INDEX[r])
        for i, rnd in enumerate(ordered):
            if rnd not in won or i + 1 >= len(ordered):
                continue
            nxt = ordered[i + 1]
            if nxt in appeared:
                continue
            self.issues.append(ValidationIssue(
                rule_id="R8",
                severity="ERROR",
                player_name=player_name,
                event_cd=event_cd,
                competition_name=comp_name,
                message=(
                    f"[{event_name}] 라운드 진행 보존법칙 위반: "
                    f"'{player_name}' 이 {rnd}을 이겼는데 다음 라운드 {nxt}에 없음 "
                    f"(이 브래킷의 라운드: {' → '.join(ordered)})"
                ),
                data={
                    "won_round": rnd,
                    "missing_round": nxt,
                    "bracket_rounds": ordered,
                    "event_cd": event_cd,
                },
            ))

    def _check_r9_pool_bout_count(self, player_name: str, records: List[Dict]):
        """R9: Pool 경기수 이상 (한 이벤트 pool_bouts > 8)"""
        player_lower = player_name.lower()

        for comp in self.competitions:
            comp_info = comp.get("competition", {})
            comp_name = comp_info.get("name", "")

            for event in (comp.get("events") or []):
                event_name = event.get("event_name", "") or event.get("name", "")
                if _is_team_event(event_name):
                    continue  # 단체전 순위표의 이름은 팀명이다 (위 _validate_all_players 주석 참조)
                event_cd = event.get("sub_event_cd", "")

                for pool in (event.get("pool_rounds") or []):
                    pool_results = (pool.get("results") or [])
                    player_in_pool = False

                    for result in pool_results:
                        if (result.get("name") or "").lower() == player_lower:
                            player_in_pool = True
                            bouts = result.get("bouts", []) or result.get("matches", []) or []
                            scores = result.get("scores", []) or []
                            bout_count = len(bouts) or len([s for s in scores if s is not None])

                            if bout_count > 8:
                                self.issues.append(ValidationIssue(
                                    rule_id="R9",
                                    severity="WARNING",
                                    player_name=player_name,
                                    event_cd=event_cd,
                                    competition_name=comp_name,
                                    message=f"[{event_name}] Pool 경기수 {bout_count}개 (보통 4-7)",
                                    data={"bout_count": bout_count, "pool_size": len(pool_results)},
                                ))
                            break

    def _check_r10_gender_inconsistency(self, player_name: str, records: List[Dict]):
        """R10: 남자/여자 종목 동시 출전 → 동명이인 오염

        KNOWN_HOMONYMS에 등록된 이름은 severity를 RESOLVED로 다운그레이드.
        """
        is_registered = player_name in _KNOWN_HOMONYMS

        genders_by_date: Dict[str, Set[str]] = defaultdict(set)

        for r in records:
            gender = _extract_gender(r.get("event_name", ""))
            comp_date = r.get("comp_date", "")
            if gender and comp_date:
                genders_by_date[comp_date].add(gender)

        # 같은 날 다른 성별
        for date, genders in genders_by_date.items():
            if len(genders) > 1:
                separated = self._homonym_separated(
                    player_name, [("G", date, g) for g in sorted(genders)]
                )
                severity = "RESOLVED" if (separated or is_registered) else "ERROR"
                suffix = (f" [{separated}]" if separated
                          else (" [KNOWN_HOMONYMS 등록됨]" if is_registered else ""))
                self.issues.append(ValidationIssue(
                    rule_id="R10",
                    severity=severity,
                    player_name=player_name,
                    event_cd="",
                    competition_name="",
                    message=f"'{player_name}' 성별 불일치: {date}에 남/여 종목 동시 출전 → 동명이인 오염 의심{suffix}",
                    data={"date": date, "genders": list(genders), "registered": is_registered},
                ))

        # 전체 기간에서 성별 변경
        all_genders = set()
        for genders in genders_by_date.values():
            all_genders.update(genders)

        if len(all_genders) > 1:
            pure = self._profiles_attribute_pure(player_name, "gender")
            severity = "RESOLVED" if (pure or is_registered) else "ERROR"
            suffix = (f" [{pure}]" if pure
                      else (" [KNOWN_HOMONYMS 등록됨]" if is_registered else ""))
            self.issues.append(ValidationIssue(
                rule_id="R10",
                severity=severity,
                player_name=player_name,
                event_cd="",
                competition_name="",
                message=f"'{player_name}' 경력 전체에서 성별 변경 감지: {all_genders} → 동명이인 가능성{suffix}",
                data={"genders": list(all_genders), "registered": is_registered},
            ))

    def _check_r11_age_regression(self, player_name: str, records: List[Dict]):
        """R11: 나이그룹 역행 (일반부 → 고등부 등)"""
        dated_groups = []
        for r in records:
            ag = _extract_age_group(r.get("event_name", ""))
            comp_date = r.get("comp_date", "")
            if ag and comp_date:
                level = AGE_GROUP_LEVELS.get(ag, 0)
                if level > 0:
                    dated_groups.append((comp_date, ag, level))

        if len(dated_groups) < 2:
            return

        dated_groups.sort(key=lambda x: x[0])

        max_level_seen = 0
        max_group_seen = ""
        max_date_seen = ""

        for comp_date, group, level in dated_groups:
            if level < max_level_seen:
                # 일반부는 전 연령 참가 가능 → 일반부 후 하위 그룹 출전은 WARNING
                severity = "ERROR"
                if max_group_seen in ("일반부", "일반", "시니어"):
                    severity = "WARNING"
                # 역행하는 두 기록이 이미 서로 다른 프로필로 갈라져 있으면 처리된 것이다.
                separated = self._homonym_separated(
                    player_name,
                    [("A", max_date_seen, max_group_seen), ("A", comp_date, group)],
                )
                if separated:
                    severity = "RESOLVED"
                self.issues.append(ValidationIssue(
                    rule_id="R11",
                    severity=severity,
                    player_name=player_name,
                    event_cd="",
                    competition_name="",
                    message=(
                        f"'{player_name}' 나이그룹 역행: "
                        f"{max_group_seen}({max_date_seen}) → {group}({comp_date})"
                        + (f" [{separated}]" if separated else "")
                    ),
                    data={
                        "prev_group": max_group_seen, "prev_date": max_date_seen,
                        "curr_group": group, "curr_date": comp_date,
                    },
                ))
                break  # 첫 역행만 보고
            if level > max_level_seen:
                max_level_seen = level
                max_group_seen = group
                max_date_seen = comp_date

    def _check_r12_weapon_count(self, player_name: str, records: List[Dict]):
        """R12: 무기 3종 이상 → 동명이인 의심"""
        weapons = set()
        for r in records:
            weapon = _extract_weapon(r.get("event_name", ""))
            if weapon:
                weapons.add(weapon)

        if len(weapons) >= 3:
            self.issues.append(ValidationIssue(
                rule_id="R12",
                severity="WARNING",
                player_name=player_name,
                event_cd="",
                competition_name="",
                message=f"'{player_name}' 무기 {len(weapons)}종 사용: {weapons} → 동명이인 가능성",
                data={"weapons": list(weapons), "count": len(weapons)},
            ))


    def _check_r13_same_date_multi_team(self, player_name: str, records: List[Dict]):
        """R13: 같은 날 다른 소속 → 동명이인 자동 감지

        같은 날 같은 이름이 다른 팀으로 출전 = 100% 동명이인 (물리적 불가).
        추가로 무기/성별/나이그룹 속성 분석으로 분리 난이도를 보고.

        Severity:
        - RESOLVED: KNOWN_HOMONYMS에 등록됨 → 프로필 분리 완료
        - WARNING: 속성(무기/성별/나이그룹)이 2개 이상 달라서 자동 분리 가능
        - ERROR: 속성 차이가 1개 이하 → 분리가 어려운 동명이인 (수동 확인 필요)
        """
        is_registered = player_name in _KNOWN_HOMONYMS

        # {날짜: [{team, event_name, ...}]}
        by_date: Dict[str, list] = defaultdict(list)
        for r in records:
            comp_date = r.get("comp_date", "")
            team = (r.get("team") or "").strip()
            if comp_date and team:
                by_date[comp_date].append(r)

        for comp_date, date_records in by_date.items():
            teams = {(r.get("team") or "").strip() for r in date_records}
            if len(teams) <= 1:
                continue

            # 속성 분석: 무기, 성별, 나이그룹 추출
            weapons = set()
            genders = set()
            age_groups = set()
            for r in date_records:
                ev = r.get("event_name", "")
                if "플" in ev:
                    weapons.add("F")
                elif "에" in ev:
                    weapons.add("E")
                elif "사브르" in ev or "싸브르" in ev:
                    weapons.add("S")
                if "남" in ev:
                    genders.add("M")
                if "여" in ev:
                    genders.add("F")
                for ag_pat, ag_label in [("초", "초등"), ("중", "중등"),
                                          ("고", "고등"), ("대", "일반")]:
                    if ag_pat in ev:
                        age_groups.add(ag_label)

            # 속성 차이 수 계산 (무기/성별/나이그룹 중 몇 개가 다른가)
            diff_attrs = sum([
                len(weapons) > 1,
                len(genders) > 1,
                len(age_groups) > 1,
            ])

            separated = self._homonym_separated(
                player_name, [(comp_date, t) for t in sorted(teams)]
            )
            if separated:
                severity = "RESOLVED"
                detail = separated
            elif is_registered:
                severity = "RESOLVED"
                detail = "KNOWN_HOMONYMS 등록됨 → 프로필 분리 완료"
            elif diff_attrs >= 2:
                severity = "WARNING"
                detail = "속성 2개+ 다름 → 자동 분리 가능"
            else:
                severity = "ERROR"
                detail = "속성 유사 → 수동 확인 필요"

            self.issues.append(ValidationIssue(
                rule_id="R13",
                severity=severity,
                player_name=player_name,
                event_cd="",
                competition_name="",
                message=(
                    f"'{player_name}' 같은 날({comp_date}) 다른 소속 "
                    f"{teams} [{detail}]"
                ),
                data={
                    "date": comp_date,
                    "teams": list(teams),
                    "weapons": list(weapons),
                    "genders": list(genders),
                    "age_groups": list(age_groups),
                    "diff_attr_count": diff_attrs,
                    "registered": is_registered,
                },
            ))

    def _check_r20_same_school_level_diff_province(self, player_name: str, records: List[Dict]):
        """R20: 같은 학교 레벨(중/고)인데 다른 도/광역시 → 동명이인 의심

        두암중(광주) vs 진장중(울산) 같은 케이스.
        KNOWN_HOMONYMS에 등록된 이름은 제외.
        org_cache가 없으면 건너뜀.
        """
        if not self.org_cache:
            return
        if player_name in _KNOWN_HOMONYMS:
            return

        # Collect unique teams with type and province
        team_info: Dict[str, Dict] = {}
        for r in records:
            team = (r.get("team") or "").strip()
            if not team or team in team_info:
                continue
            team_type = get_team_type(team)
            province = self.org_cache.get(team, {}).get("province", "")
            team_info[team] = {"type": team_type, "province": province}

        # Check pairs of same school level in different provinces
        school_types = ("middle", "high")
        teams_by_type: Dict[str, List] = defaultdict(list)
        for team, info in team_info.items():
            if info["type"] in school_types and info["province"]:
                teams_by_type[info["type"]].append((team, info["province"]))

        for school_type, team_list in teams_by_type.items():
            if len(team_list) < 2:
                continue
            for i, (t1, p1) in enumerate(team_list):
                for t2, p2 in team_list[i + 1:]:
                    if p1 != p2:
                        self.issues.append(ValidationIssue(
                            rule_id="R20",
                            severity="WARNING",
                            player_name=player_name,
                            event_cd="",
                            competition_name="",
                            message=(
                                f"'{player_name}' 같은 {school_type} 레벨, 다른 지역: "
                                f"{t1}({p1}) vs {t2}({p2}) → 동명이인 의심"
                            ),
                            data={
                                "team1": t1, "province1": p1,
                                "team2": t2, "province2": p2,
                                "school_type": school_type,
                            },
                        ))
                        return  # 첫 발견만 보고

    def _check_r21_activity_gap(self, player_name: str, records: List[Dict]):
        """R21: 3년 이상 활동 공백 후 다른 팀에서 재등장 → 동명이인 의심

        KNOWN_HOMONYMS에 등록된 이름은 제외.
        """
        if player_name in _KNOWN_HOMONYMS:
            return

        dated = sorted(
            [r for r in records if r.get("comp_date")],
            key=lambda x: x["comp_date"],
        )
        if len(dated) < 2:
            return

        from datetime import datetime

        for i in range(len(dated) - 1):
            d1 = (dated[i].get("comp_date") or "")[:10]
            d2 = (dated[i + 1].get("comp_date") or "")[:10]
            t1 = (dated[i].get("team") or "").strip()
            t2 = (dated[i + 1].get("team") or "").strip()

            if not d1 or not d2 or not t1 or not t2 or t1 == t2:
                continue

            try:
                dt1 = datetime.strptime(d1, "%Y-%m-%d")
                dt2 = datetime.strptime(d2, "%Y-%m-%d")
            except (ValueError, TypeError):
                continue

            gap_years = (dt2 - dt1).days / 365.25
            if gap_years >= 3.0:
                self.issues.append(ValidationIssue(
                    rule_id="R21",
                    severity="WARNING",
                    player_name=player_name,
                    event_cd="",
                    competition_name="",
                    message=(
                        f"'{player_name}' {gap_years:.1f}년 활동 공백 후 다른 팀: "
                        f"{t1}({d1}) → {t2}({d2}) → 동명이인 의심"
                    ),
                    data={
                        "team_before": t1, "last_active": d1,
                        "team_after": t2, "reappeared": d2,
                        "gap_years": round(gap_years, 1),
                    },
                ))
                return  # 첫 발견만 보고

    def _check_r22_pool_completeness(
        self, event: Dict, event_cd: str, comp_name: str, event_name: str
    ):
        """R22: pool_total_ranking 있으면서 pool_rounds 비어있는 경우 (스크래핑 실패 감지)"""
        raw_data = event.get("raw_data", event)
        # 🔴 `or []` 가 필요하다. 이 키들은 **존재하면서 값이 None** 인 레코드가 있고
        # (`raw.get("pool_rounds")` 가 그대로 None 을 넘긴다), `.get(k, [])` 는 그때
        # 기본값을 쓰지 않으므로 `len(None)` 으로 TypeError 가 나 검증 전체가 중단된다.
        pool_total = raw_data.get("pool_total_ranking") or []
        pool_rounds = raw_data.get("pool_rounds") or []

        if len(pool_total) > 0 and len(pool_rounds) == 0:
            self.issues.append(ValidationIssue(
                rule_id="R22",
                severity="ERROR",
                player_name="",
                event_cd=event_cd,
                competition_name=comp_name,
                message=(
                    f"{event_name}: pool_total_ranking {len(pool_total)}명 존재하나 "
                    f"pool_rounds 0개 — 풀 상세 데이터 스크래핑 실패 의심"
                ),
                data={
                    "pool_total_count": len(pool_total),
                    "pool_rounds_count": 0,
                    "scrape_metadata": raw_data.get("_scrape_metadata", {}),
                },
            ))

    def _check_r23_pool_forfeit(
        self, event: Dict, event_cd: str, comp_name: str, event_name: str
    ):
        """R23: Pool 기권(Abandon) 감지

        기권자(is_forfeit=True)가 풀에 존재하면 INFO 로그.
        기권자의 wins/losses가 0이 아닌 경우 → 기권 bout이 승/패에 잘못 포함됨 → WARNING.
        """
        raw_data = event.get("raw_data", event)
        pool_rounds = raw_data.get("pool_rounds", [])
        if not pool_rounds:
            return

        for pool in pool_rounds:
            pool_num = pool.get("pool_number", "?")
            round_num = pool.get("round_number", "?")
            results = pool.get("results", [])

            for result in results:
                if not result.get("is_forfeit"):
                    continue

                name = (result.get("name") or "").strip()
                team = (result.get("team") or "").strip()
                wins = result.get("wins", 0) or 0
                losses = result.get("losses", 0) or 0

                # 기권 감지 INFO
                self.issues.append(ValidationIssue(
                    rule_id="R23",
                    severity="INFO",
                    player_name=name,
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=(
                        f"{event_name} 뿔{round_num}-{pool_num}: "
                        f"'{name}'({team}) 기권(Abandon) 감지"
                    ),
                    data={
                        "pool_number": pool_num,
                        "round_number": round_num,
                    },
                ))

                # 기권자의 wins/losses가 0이 아니면 잘못된 집계
                if wins > 0 or losses > 0:
                    self.issues.append(ValidationIssue(
                        rule_id="R23",
                        severity="WARNING",
                        player_name=name,
                        event_cd=event_cd,
                        competition_name=comp_name,
                        message=(
                            f"{event_name} 뿔{round_num}-{pool_num}: "
                            f"기권자 '{name}'의 승/패가 {wins}W-{losses}L로 기록됨 "
                            f"— 기권 bout이 승/패에 포함된 것으로 의심"
                        ),
                        data={
                            "wins": wins,
                            "losses": losses,
                            "pool_number": pool_num,
                            "round_number": round_num,
                        },
                    ))

    def _check_r14_same_event_duplicate_names(
        self, event: Dict, event_cd: str, comp_name: str, event_name: str
    ):
        """R14: 같은 이벤트 final_rankings에 같은 이름이 2회+ 등장 (같은 팀 동명이인)

        같은 이벤트(같은 성별/무기/나이그룹)에 같은 이름이 2번 등장하면
        물리적으로 한 사람이 될 수 없으므로 동명이인 확정.
        같은 팀이면 자동 분리 불가 (어떤 기록이 누구의 것인지 판별 불가).
        """
        rankings = (event.get("final_rankings") or [])
        if not rankings:
            return

        # 이름별 등장 횟수 + 팀 수집
        name_info: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "teams": set()})
        for r in rankings:
            name = (r.get("name") or "").strip()
            if not name:
                continue
            name_info[name]["count"] += 1
            team = (r.get("team") or "").strip()
            if team:
                name_info[name]["teams"].add(team)

        for name, info in name_info.items():
            if info["count"] < 2:
                continue
            teams = info["teams"]
            if len(teams) <= 1:
                # 같은 팀에서 2번 등장 = 같은 팀 동명이인 (자동 분리 불가)
                self.issues.append(ValidationIssue(
                    rule_id="R14",
                    severity="WARNING",
                    player_name=name,
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=(
                        f"'{name}' 같은 이벤트({event_name})에 "
                        f"{info['count']}회 등장, 팀: {teams or '없음'} "
                        f"→ 같은 팀 동명이인 (자동 분리 불가)"
                    ),
                    data={
                        "event_name": event_name,
                        "count": info["count"],
                        "teams": list(teams),
                    },
                ))
            # 다른 팀이면 R13에서 이미 잡으므로 여기선 건너뜀


    # =========================================================================
    # Bracket/Dual DE 구조 검증 (R15 ~ R18)
    # =========================================================================

    def _check_r15_bracket_size_consistency(
        self, event: Dict, event_cd: str, comp_name: str, event_name: str,
        de_bracket: Dict
    ):
        """R15: bracket_size vs bout count 일관성

        bracket_size가 N이면 최대 N-1 경기 가능.
        bout 수가 bracket_size-1보다 크면 bracket_size 오류.
        또한 bracket_size가 2의 거듭제곱인지 확인.
        dual_de는 first_de/second_de를 각각 독립 검증.
        """
        if de_bracket.get("format") == "dual_de":
            for sub_key in ("first_de", "second_de"):
                sub = de_bracket.get(sub_key, {})
                if isinstance(sub, dict) and sub:
                    self._r15_check_sub_bracket(
                        sub, event_cd, comp_name, f"{event_name} [{sub_key}]"
                    )
        else:
            self._r15_check_sub_bracket(de_bracket, event_cd, comp_name, event_name)

    def _r15_check_sub_bracket(
        self, bracket: Dict, event_cd: str, comp_name: str, event_name: str
    ):
        """R15 보조: 개별 bracket의 bracket_size vs bout count 검증"""
        bracket_size = bracket.get("bracket_size")
        if not bracket_size or not isinstance(bracket_size, (int, float)):
            return
        bracket_size = int(bracket_size)

        # bout 수 계산
        #
        # 🔴 2026-09-28 오탐 수정. 같은 경기가 **라운드명 이표기**로 두 번 저장된 레코드가 있다.
        # 실측(2023 생활체육 고등부 남자 사브르): 4 슬롯 브래킷에 '준결승 #1 최정민 vs (공란)'
        # 과 '4강 #1 최정민 vs (공란)' 이 따로 들어가 bout 4개로 세어졌고, bracket_size 4 <
        # 필요 5명 으로 ERROR 가 났다. 실제 슬롯은 3개(준결승 2 + 결승 1)로 정상이다.
        # `_get_full_bouts_from_bracket()` 의 선수쌍 dedup 은 **한쪽 이름이 공란(부전승)이면
        # 짝을 만들 수 없어** 이 중복을 못 지운다. 그래서 여기서 라운드명을 정규화한
        # (라운드, 경기번호, 선수1, 선수2) 로 한 번 더 합친다. 이 수정으로 ERROR 37 → 1.
        #
        # 부전승은 세는 데서 빼지 않는다 — 부전승도 브래킷 슬롯을 차지하므로
        # "N 슬롯 브래킷의 경기 레코드는 N-1 개 이하" 라는 이 규칙의 근거에 포함된다.
        bouts = _get_full_bouts_from_bracket(bracket)
        slot_keys = {
            (
                _normalize_de_round(b.get("round_name") or b.get("round") or ""),
                b.get("match_number"),
                _get_player_name(b, "player1"),
                _get_player_name(b, "player2"),
            )
            for b in bouts
        }
        bout_count = len(slot_keys)
        if bout_count == 0:
            return

        # bracket_size가 2의 거듭제곱인지 확인
        if bracket_size > 0 and (bracket_size & (bracket_size - 1)) != 0:
            self.issues.append(ValidationIssue(
                rule_id="R15",
                severity="WARNING",
                player_name="",
                event_cd=event_cd,
                competition_name=comp_name,
                message=f"[{event_name}] bracket_size={bracket_size}는 2의 거듭제곱이 아님",
                data={"bracket_size": bracket_size, "bout_count": bout_count},
            ))

        # bracket_size가 bout_count + 1보다 작으면 오류
        # (N명 참가 → N-1 경기이므로, bout_count + 1 ≤ bracket_size 이어야 함)
        min_participants = bout_count + 1
        proper_bracket_size = _get_proper_bracket_size(min_participants)

        if bracket_size < min_participants:
            self.issues.append(ValidationIssue(
                rule_id="R15",
                severity="ERROR",
                player_name="",
                event_cd=event_cd,
                competition_name=comp_name,
                message=(
                    f"[{event_name}] bracket_size={bracket_size}이지만 "
                    f"bout {bout_count}개 → 최소 {min_participants}명 필요 "
                    f"(적정 bracket_size={proper_bracket_size})"
                ),
                data={
                    "bracket_size": bracket_size,
                    "bout_count": bout_count,
                    "min_participants": min_participants,
                    "proper_bracket_size": proper_bracket_size,
                },
            ))

    def _check_r16_dual_de_completeness(
        self, event: Dict, event_cd: str, comp_name: str, event_name: str,
        de_bracket: Dict
    ):
        """R16: Dual DE 완전성 검증

        dual_de 이벤트에서:
        - second_de가 없으면 ERROR
        - second_de에 bouts가 없으면 ERROR
        - first_de에 bouts 있고 second_de에 없으면 WARNING
        - second_de에 seeding이 없으면 WARNING
        """
        if de_bracket.get("format") != "dual_de":
            return

        second_de = de_bracket.get("second_de", {})
        first_de = de_bracket.get("first_de", {})

        if not isinstance(second_de, dict):
            self.issues.append(ValidationIssue(
                rule_id="R16",
                severity="ERROR",
                player_name="",
                event_cd=event_cd,
                competition_name=comp_name,
                message=f"[{event_name}] dual_de이지만 second_de가 없음",
                data={},
            ))
            return

        # second_de bouts 확인 (full_bouts, bouts, bouts_by_round 모두 체크)
        second_bouts = list(second_de.get("full_bouts", []) or [])
        if not second_bouts:
            second_bouts = list(second_de.get("bouts", []) or [])
        if not second_bouts:
            bbr = second_de.get("bouts_by_round", {})
            if isinstance(bbr, dict):
                for round_bouts in bbr.values():
                    if isinstance(round_bouts, list):
                        second_bouts.extend(round_bouts)

        if not second_bouts:
            self.issues.append(ValidationIssue(
                rule_id="R16",
                severity="ERROR",
                player_name="",
                event_cd=event_cd,
                competition_name=comp_name,
                message=f"[{event_name}] dual_de의 second_de에 bouts가 없음",
                data={
                    "second_de_keys": list(second_de.keys()) if isinstance(second_de, dict) else [],
                },
            ))

            # first_de에는 bouts가 있는지 비교
            if isinstance(first_de, dict):
                first_bouts = _get_full_bouts_from_bracket(first_de)
                if first_bouts:
                    self.issues.append(ValidationIssue(
                        rule_id="R16",
                        severity="WARNING",
                        player_name="",
                        event_cd=event_cd,
                        competition_name=comp_name,
                        message=(
                            f"[{event_name}] first_de에는 bout {len(first_bouts)}개 있지만 "
                            f"second_de에는 없음 → 데이터 불완전"
                        ),
                        data={"first_de_bout_count": len(first_bouts)},
                    ))

        # second_de seeding 확인
        seeding = (second_de.get("seeding") or [])
        if not seeding:
            self.issues.append(ValidationIssue(
                rule_id="R16",
                severity="WARNING",
                player_name="",
                event_cd=event_cd,
                competition_name=comp_name,
                message=f"[{event_name}] dual_de의 second_de에 seeding이 없음",
                data={},
            ))

    def _check_r17_final_rankings_vs_de_winner(
        self, event: Dict, event_cd: str, comp_name: str, event_name: str,
        de_bracket: Dict
    ):
        """R17: Final rankings vs DE 결승 승자 교차검증 (강화된 R6)

        R6보다 강화: raw bouts에서 직접 결승 bout의 승자를 찾아
        final_rankings 1위와 비교. bracket 정규화가 깨져도 동작.

        dual_de: second_de의 결승 승자 vs final_rankings[0]
        regular: DE bracket의 결승 승자 vs final_rankings[0]
        """
        final_rankings = (event.get("final_rankings") or [])
        if not final_rankings:
            return

        # final_rankings에서 1위 찾기
        first_place = None
        for r in final_rankings:
            rank = r.get("rank")
            if rank == 1 or rank == "1":
                first_place = (r.get("name") or "").strip()
                break

        if not first_place:
            return

        # 결승 승자를 찾을 대상 bracket 결정
        target_bracket = de_bracket
        bracket_label = ""

        if de_bracket.get("format") == "dual_de":
            second_de = de_bracket.get("second_de", {})
            if not isinstance(second_de, dict) or not second_de:
                return  # R16에서 이미 감지
            target_bracket = second_de
            bracket_label = " [second_de]"

        final_winner = self._r17_find_final_winner(target_bracket)

        if not final_winner:
            return  # 결승 bout을 찾을 수 없음 (데이터 부족)

        if final_winner != first_place:
            self.issues.append(ValidationIssue(
                rule_id="R17",
                severity="ERROR",
                player_name=first_place,
                event_cd=event_cd,
                competition_name=comp_name,
                message=(
                    f"[{event_name}]{bracket_label} DE 결승 승자 '{final_winner}'와 "
                    f"final_rankings 1위 '{first_place}'가 불일치"
                ),
                data={
                    "de_final_winner": final_winner,
                    "ranking_first_place": first_place,
                    "is_dual_de": de_bracket.get("format") == "dual_de",
                },
            ))

    def _r17_find_final_winner(self, bracket: Dict) -> str:
        """R17 보조: bracket에서 결승 bout의 승자 찾기 (raw 데이터 직접 탐색)"""
        if not isinstance(bracket, dict):
            return ""

        FINAL_NAMES = {"결승", "결승전", "Final", "final"}

        # Path 1: full_bouts / bouts에서 결승 찾기
        for bouts_key in ("full_bouts", "bouts"):
            bouts = bracket.get(bouts_key, [])
            if isinstance(bouts, list):
                for bout in bouts:
                    if not isinstance(bout, dict):
                        continue
                    rnd = (bout.get("round_name") or bout.get("round") or "").strip()
                    if rnd in FINAL_NAMES or ("결승" in rnd and "준결승" not in rnd):
                        winner = self._r17_extract_winner(bout)
                        if winner:
                            return winner

        # Path 2: bouts_by_round에서 결승 찾기
        bbr = bracket.get("bouts_by_round", {})
        if isinstance(bbr, dict):
            for round_name, round_bouts in bbr.items():
                if round_name in FINAL_NAMES or ("결승" in round_name and "준결승" not in round_name):
                    if isinstance(round_bouts, list):
                        for bout in round_bouts:
                            if isinstance(bout, dict):
                                winner = self._r17_extract_winner(bout)
                                if winner:
                                    return winner

        # Path 3: match_number 기반 (bracket_size에서 결승 match_number 계산)
        bracket_size = bracket.get("bracket_size", 0)
        if bracket_size and isinstance(bracket_size, (int, float)):
            final_match_num = int(bracket_size) - 1
            for bouts_key in ("full_bouts", "bouts"):
                bouts = bracket.get(bouts_key, [])
                if isinstance(bouts, list):
                    for bout in bouts:
                        if isinstance(bout, dict) and bout.get("match_number") == final_match_num:
                            winner = self._r17_extract_winner(bout)
                            if winner:
                                return winner

        return ""

    def _r17_extract_winner(self, bout: Dict) -> str:
        """R17 보조: bout에서 승자 추출 (winner_name 또는 점수 기반 추론)"""
        winner = (bout.get("winner_name") or "").strip()
        if winner:
            return winner

        # 점수 기반 추론
        p1 = _get_player_name(bout, "player1")
        p2 = _get_player_name(bout, "player2")
        s1 = bout.get("player1_score")
        s2 = bout.get("player2_score")

        try:
            s1_int = int(s1) if s1 is not None else 0
            s2_int = int(s2) if s2 is not None else 0
        except (ValueError, TypeError):
            return ""

        if s1_int > s2_int and s1_int > 0 and p1:
            return p1
        elif s2_int > s1_int and s2_int > 0 and p2:
            return p2

        return ""

    # =========================================================================
    # R24 / R25: Dual DE (예선+본선) 전용 검증
    #
    # dual DE는 예선(first_de)과 본선(second_de)이 **같은 이름의 라운드**를 갖는다.
    # 예: 예선 64강 32경기 + 본선 64강 32경기 — 이름만 같을 뿐 완전히 다른 경기다.
    # 라운드 이름만으로 bout을 식별하는 코드가 하나라도 있으면 두 페이즈가
    # 조용히 병합되고, 한쪽이 통째로 사라진다. 아래 두 규칙이 그 감시선이다.
    # =========================================================================

    def _dual_de_phase_sources(self, de_bracket: Dict) -> Tuple[Dict, Dict, List[Dict]]:
        """dual_de에서 (first_de, second_de, 최상위 flat full_bouts) 안전 추출.

        first_de/second_de는 `{}`가 아니라 `None`으로 저장된 레코드가 실제로 있다.
        `de_bracket.get("first_de", {})`는 키가 존재하고 값이 None이면 None을 돌려주므로
        `or {}`까지 해야 안전하다.
        """
        first_de = de_bracket.get("first_de") or {}
        second_de = de_bracket.get("second_de") or {}
        if not isinstance(first_de, dict):
            first_de = {}
        if not isinstance(second_de, dict):
            second_de = {}

        flat = de_bracket.get("full_bouts")
        flat_bouts = [b for b in flat if isinstance(b, dict)] if isinstance(flat, list) else []
        return first_de, second_de, flat_bouts

    def _check_r24_dual_de_shared_round(
        self, event: Dict, event_cd: str, comp_name: str, event_name: str,
        de_bracket: Dict
    ):
        """R24: dual DE의 공유 라운드가 예선(first_de)에서 통째로 사라짐 (ERROR)

        🔴 실제 사고 2회 — 2026-08-17, 2026-08-18.
        예선 64강 32경기가 사라져 저장된 대진표가 159경기 → 127경기로 줄었다.
        두 번 다 first_de에는 128강 64경기만 남고 64강은 0경기였다. 본선에도 64강이
        있었기 때문에 "64강은 있다"고 보이는 화면상으로는 유실이 드러나지 않았다.
        이 규칙이 세 번째를 막는 마지막 방어선이다.

        판정: 본선(second_de)의 starting_round = 예선이 본선으로 합류하는 공유 라운드.
        예선 브래킷에 그 라운드의 경기가 단 하나도 없으면 유실이다.

        추가로 dual_de인데 예선/본선 중 한쪽만 데이터가 있는 '반쪽 스크래핑'도 ERROR.
        (R16은 second_de 누락만 본다. 그 반대 방향 — 본선만 있고 예선이 통째로 빈 경우 —
         이 규칙이 잡는다. 겹치는 구간이 있어도 유실 감지는 중복이 침묵보다 낫다.)
        """
        if de_bracket.get("format") != "dual_de":
            return  # 단일 DE는 공유 라운드 개념 자체가 없다
        if _is_team_event(event_name):
            return  # 단체전은 dual DE를 쓰지 않는다

        first_de, second_de, flat_bouts = self._dual_de_phase_sources(de_bracket)

        first_bouts = _collect_raw_de_bouts(first_de)
        second_bouts = _collect_raw_de_bouts(second_de)
        # 일부 레코드는 sub-bracket을 비워두고 최상위 full_bouts에만 저장한다.
        # 그 경우 페이즈 태그가 유일한 소속 근거다.
        flat_qualifying = [b for b in flat_bouts
                           if get_bout_phase(b) == DE_PHASE_QUALIFYING]
        flat_main = [b for b in flat_bouts if get_bout_phase(b) == DE_PHASE_MAIN]

        has_first = bool(first_bouts or flat_qualifying)
        has_second = bool(second_bouts or flat_main)

        if has_first != has_second:
            missing = "first_de(예선)" if has_second else "second_de(본선)"
            present = "second_de(본선)" if has_second else "first_de(예선)"
            present_count = len(second_bouts or flat_main) if has_second else len(first_bouts or flat_qualifying)
            self.issues.append(ValidationIssue(
                rule_id="R24",
                severity="ERROR",
                player_name="",
                event_cd=event_cd,
                competition_name=comp_name,
                message=(
                    f"[{event_name}] dual_de인데 {missing}에 경기가 하나도 없음 "
                    f"({present}만 {present_count}경기) → 반쪽만 스크래핑된 상태. "
                    f"해당 이벤트 재스크래핑 필요"
                ),
                data={
                    "first_de_bout_count": len(first_bouts),
                    "second_de_bout_count": len(second_bouts),
                    "flat_qualifying_count": len(flat_qualifying),
                    "flat_main_count": len(flat_main),
                    "missing_phase": missing,
                },
            ))
            return  # 반쪽 상태에서는 공유 라운드 대조가 의미 없다

        if not has_first and not has_second:
            return  # 완전 빈 dual_de는 R16 담당

        # --- 공유 라운드 결정 ---
        shared_round = _normalize_de_round(second_de.get("starting_round"))
        second_all = second_bouts or flat_main
        if not shared_round:
            # starting_round가 없으면 본선 경기 중 가장 이른 라운드로 대체한다.
            # 없는 값을 지어내지 않고, 근거를 못 찾으면 침묵한다.
            second_rounds = {_bout_round_name(b) for b in second_all}
            candidates = [r for r in ROUND_ORDER_LIST if r in second_rounds]
            shared_round = candidates[0] if candidates else ""
        if not shared_round:
            return

        # --- 예선 라운드별 경기 수 집계 ---
        # 같은 경기가 first_de와 최상위 full_bouts에 둘 다 실릴 수 있다.
        # 페이즈를 뺀 (라운드, 경기번호)로 합쳐야 숫자가 부풀지 않는다.
        qual_seen: Dict[Tuple, Dict] = {}
        for bout in list(first_bouts) + list(flat_qualifying):
            qual_seen.setdefault(_bout_identity(bout), bout)

        first_round_counts: Dict[str, int] = defaultdict(int)
        for bout in qual_seen.values():
            rnd = _bout_round_name(bout)
            if rnd:
                first_round_counts[rnd] += 1

        if first_round_counts.get(shared_round, 0) > 0:
            return  # 정상

        expected = EXPECTED_BOUTS_BY_ROUND.get(shared_round)
        expected_text = f"{expected}경기" if expected else "해당 라운드 경기"
        counts_text = ", ".join(
            f"{r}={first_round_counts[r]}"
            for r in ROUND_ORDER_LIST if first_round_counts.get(r)
        ) or "(경기 없음)"

        self.issues.append(ValidationIssue(
            rule_id="R24",
            severity="ERROR",
            player_name="",
            event_cd=event_cd,
            competition_name=comp_name,
            message=(
                f"[{event_name}] dual_de 공유 라운드 '{shared_round}'의 예선 경기가 "
                f"first_de에 0개 → 예선 {shared_round} {expected_text}가 유실됨. "
                f"first_de 라운드별 경기 수: {counts_text}. "
                f"(본선 second_de.starting_round='{shared_round}', "
                f"본선 {shared_round} {sum(1 for b in second_all if _bout_round_name(b) == shared_round)}경기 존재) "
                f"→ 2026-08-17/2026-08-18과 동일 유형. 해당 이벤트 재스크래핑 필요"
            ),
            data={
                "shared_round": shared_round,
                "first_de_round_counts": dict(first_round_counts),
                "first_de_bout_count": len(qual_seen),
                "second_de_bout_count": len(second_all),
                "second_de_starting_round": second_de.get("starting_round"),
                "expected_bouts_in_shared_round": expected,
            },
        ))

    def _check_r25_de_phase_tagging(
        self, event: Dict, event_cd: str, comp_name: str, event_name: str,
        de_bracket: Dict
    ):
        """R25: dual DE bout에 de_phase가 없음 (ERROR, 이벤트 단위 집계)

        de_phase가 없는 순간 그 bout은 본선 bout과 구별할 방법이 사라진다.
        라운드 이름으로 키잉하는 소비자(중복 제거, 대진표 조립, H2H 집계)는
        예선 64강과 본선 64강을 같은 경기로 보고 한쪽을 버린다 — 이것이
        2026-08-17/18 유실의 메커니즘이다.

        🔴 반드시 format == "dual_de" 에서만 발동한다.
        단일 DE·단체전·비-dual 레거시까지 검사하면 수천 건의 무의미한 ERROR가 쏟아져
        검증 리포트 자체를 못 쓰게 된다(= 진짜 오류가 묻힌다).
        기존 dual 레코드가 걸리는 것은 의도된 결과다 — 실제로 재스크래핑이 필요하다.

        bout 하나당 이슈를 만들지 않고 이벤트당 1건으로 집계한다(경기 수가 100건대라
        그대로 뱉으면 리포트가 폭발한다). 샘플 5건만 첨부한다.
        """
        if de_bracket.get("format") != "dual_de":
            return
        if _is_team_event(event_name):
            return

        first_de, second_de, flat_bouts = self._dual_de_phase_sources(de_bracket)

        # 같은 경기가 여러 소스에 중복 등장할 수 있으므로 신원 키로 합친다.
        all_bouts: Dict[Tuple, Dict] = {}
        for bout in (list(flat_bouts)
                     + _collect_raw_de_bouts(first_de)
                     + _collect_raw_de_bouts(second_de)):
            all_bouts.setdefault(_bout_identity(bout), bout)

        if not all_bouts:
            return  # 빈 dual_de는 R16/R24 담당

        untagged: List[Dict] = []
        for bout in all_bouts.values():
            phase = get_bout_phase(bout)
            if phase not in (DE_PHASE_QUALIFYING, DE_PHASE_MAIN):
                untagged.append(bout)

        total = len(all_bouts)
        if untagged:
            samples = [_bout_label(b) for b in untagged[:5]]
            bad_values = sorted({
                str(b.get("de_phase")) for b in untagged
                if isinstance(b, dict) and b.get("de_phase")
            })
            extra = f" 규약 외 값: {bad_values}." if bad_values else ""
            self.issues.append(ValidationIssue(
                rule_id="R25",
                severity="ERROR",
                player_name="",
                event_cd=event_cd,
                competition_name=comp_name,
                message=(
                    f"[{event_name}] dual_de인데 de_phase 없는 DE bout "
                    f"{len(untagged)}/{total}개 → 예선/본선 구분 불가 "
                    f"(라운드명만으로는 예선 64강과 본선 64강이 같은 경기로 취급됨)."
                    f"{extra} 샘플: {'; '.join(samples)}"
                    f" → 해당 이벤트 재스크래핑 필요"
                ),
                data={
                    "untagged_count": len(untagged),
                    "total_bout_count": total,
                    "sample_bouts": samples,
                    "invalid_phase_values": bad_values,
                },
            ))

        # --- 페이즈 없는 bout끼리의 (라운드, 경기번호) 충돌 ---
        # 페이즈가 서로 다른 두 bout이 같은 (라운드, 번호)를 갖는 건 정상이다
        # (예선 64강 #1 / 본선 64강 #1). 문제는 **양쪽 다 페이즈가 없을 때** —
        # 이건 이미 구분 불가능한 상태로 저장돼 있다는 뜻이고, 아무 소비자나
        # 라운드+번호로 dedup하는 순간 한쪽이 삭제된다.
        collision_groups: Dict[Tuple, List[Dict]] = defaultdict(list)
        for bout in all_bouts.values():
            key = phase_bout_key(bout)
            collision_groups[(key[1], key[2])].append(bout)

        collisions = []
        for (rnd, num), bouts in collision_groups.items():
            if len(bouts) < 2:
                continue
            if all(get_bout_phase(b) is None for b in bouts):
                collisions.append({
                    "round_name": rnd,
                    "match_number": num,
                    "bouts": [_bout_label(b) for b in bouts[:3]],
                })

        if collisions:
            sample_text = "; ".join(
                f"{c['round_name']} #{c['match_number']} ({' / '.join(c['bouts'])})"
                for c in collisions[:3]
            )
            self.issues.append(ValidationIssue(
                rule_id="R25",
                severity="ERROR",
                player_name="",
                event_cd=event_cd,
                competition_name=comp_name,
                message=(
                    f"[{event_name}] 페이즈 없는 bout끼리 (round_name, match_number) 충돌 "
                    f"{len(collisions)}건 → 예선/본선 구분 근거가 전혀 없어 "
                    f"중복 제거 시 한쪽이 삭제됨(잠재적 유실). 충돌: {sample_text}"
                ),
                data={
                    "collision_count": len(collisions),
                    "collisions": collisions[:10],
                },
            ))

    def _check_r18_kff_external_comparison(
        self, event: Dict, event_cd: str, comp_name: str, event_name: str
    ):
        """R18: KFF 외부 소스 비교 (옵션 - 기본 비활성)

        KFF 원본 데이터와 저장된 데이터의 final_rankings를 비교.
        네트워크 접근이 필요하므로 기본 비활성.
        validate_external()으로 명시적 호출 필요.

        TODO: KFF 페이지 파싱 로직 구현
        - event_cd로 KFF URL 구성 (fencing.sports.or.kr)
        - scraper client로 final_rankings 추출
        - 저장된 데이터와 순위/이름 비교
        """
        final_rankings = (event.get("final_rankings") or [])
        if not final_rankings:
            return

        # TODO: KFF 외부 데이터 fetch 구현
        # 구현 시 아래 패턴 사용:
        #
        # kff_rankings = self._fetch_kff_rankings(event_cd)
        # if not kff_rankings:
        #     return
        #
        # for i, (stored, kff) in enumerate(zip(final_rankings, kff_rankings)):
        #     stored_name = (stored.get("name") or "").strip()
        #     kff_name = (kff.get("name") or "").strip()
        #     stored_rank = stored.get("rank")
        #     kff_rank = kff.get("rank")
        #     if stored_name != kff_name or stored_rank != kff_rank:
        #         self.issues.append(ValidationIssue(
        #             rule_id="R18",
        #             severity="ERROR",
        #             player_name=stored_name,
        #             event_cd=event_cd,
        #             competition_name=comp_name,
        #             message=(
        #                 f"[{event_name}] KFF 순위 불일치: "
        #                 f"저장={stored_rank}위 {stored_name}, "
        #                 f"KFF={kff_rank}위 {kff_name}"
        #             ),
        #             data={
        #                 "stored_rank": stored_rank, "stored_name": stored_name,
        #                 "kff_rank": kff_rank, "kff_name": kff_name,
        #                 "position": i + 1,
        #             },
        #         ))

        logger.debug(f"R18: KFF 외부 비교 미구현 (event_cd={event_cd})")

    # =========================================================================
    # R19: 이벤트 레벨 vs 참가자 org_type 교차 검증
    # =========================================================================

    # 이벤트 school_level → 허용되는 org_type 매핑
    # club은 모든 레벨에서 허용 (클럽 소속 학생이 학교급별 대회 출전 가능)
    _LEVEL_ALLOWED_ORG_TYPES = {
        'elementary': {'elementary', 'club'},
        'elem_1_2': {'elementary', 'club'},
        'elem_3_4': {'elementary', 'club'},
        'elem_5_6': {'elementary', 'club'},
        'middle': {'middle', 'club'},
        'high': {'high', 'club'},
    }

    # 학교급을 특정할 수 없는 org_type — R19 대상에서 제외한다.
    #
    # 🔴 2026-09-28 오탐 수정. R19 WARNING 271건 중 **221건이 international_school** 이었다.
    # 국제학교는 한 학교에 K-12 가 모두 있어서 org_type 하나로 학교급을 특정할 수 없다.
    # 초등부에 나온 국제학교 학생은 정상이지 오분류가 아니다. 'association'(시·도 펜싱협회)도
    # 연령대를 담지 않는다. 이 둘을 제외하면 남는 것은 실제로 의심스러운 건들이다
    # (예: 실업팀 소속이 초등부에 등장 → org_type 오분류 또는 이름 오염).
    _AGE_AGNOSTIC_ORG_TYPES = {'international_school', 'association', 'academy', 'other'}

    def _check_r19_event_level_vs_org_type(
        self, event: Dict, event_cd: str, comp_name: str, event_name: str
    ):
        """R19: 이벤트 school_level에 맞지 않는 org_type 참가자 감지

        예: 대학대회 이벤트에 middle org_type 선수가 있으면 org_type 오분류 의심.
        """
        level = GradeEstimator.parse_school_level(event_name)
        if not level:
            return  # 일반부/대학부 등은 검사 안 함

        allowed = self._LEVEL_ALLOWED_ORG_TYPES.get(level)
        if not allowed:
            return

        # final_rankings에서 참가자 팀 수집
        for r in (event.get("final_rankings") or []):
            team = (r.get("team") or "").strip()
            name = (r.get("name") or "").strip()
            if not team:
                continue

            # org_cache에서 org_type 조회
            org_info = self.org_cache.get(team, {})
            org_type = org_info.get("org_type", "")
            if not org_type:
                # 캐시에 없으면 get_team_type()으로 추론
                org_type = get_team_type(team)

            if org_type in self._AGE_AGNOSTIC_ORG_TYPES:
                continue

            if org_type and org_type not in allowed:
                self.issues.append(ValidationIssue(
                    rule_id="R19",
                    severity="WARNING",
                    player_name=name,
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=(
                        f"이벤트 레벨 '{level}'에 부적합한 org_type '{org_type}' 참가자: "
                        f"{name}({team}) in {event_name}"
                    ),
                    data={
                        "event_level": level,
                        "org_type": org_type,
                        "team": team,
                        "event_name": event_name,
                    },
                ))

    def validate_external(self, max_comparisons: int = 10) -> List[ValidationIssue]:
        """외부 소스 비교 검증 (R18) - 명시적 호출 필요

        Args:
            max_comparisons: 최대 비교 횟수 (기본 10, rate limit)

        Returns:
            R18 검증 결과 이슈 목록
        """
        self.issues = []
        comparison_count = 0

        for comp in self.competitions:
            if comparison_count >= max_comparisons:
                break
            comp_info = comp.get("competition", {})
            comp_name = comp_info.get("name", "알 수 없는 대회")

            for event in (comp.get("events") or []):
                if comparison_count >= max_comparisons:
                    break
                event_cd = event.get("sub_event_cd", "")
                event_name = event.get("event_name", "") or event.get("name", "")

                self._check_r18_kff_external_comparison(
                    event, event_cd, comp_name, event_name
                )
                comparison_count += 1

        return self.issues


class ThrottledDataValidator(DataValidator):
    """검증 도중 CPU를 양보하는 래퍼.

    검증은 순수 CPU 작업이라 한 번 돌기 시작하면 코어 하나를 100% 물고 늘어진다.
    2026-08-15 에는 대회 데이터 일괄 수정이 변경 감지를 건드려 post_scrape_validation
    이 돌았고, 이벤트 루프 안에서 동기로 실행되는 바람에 서버가 16분간 응답하지
    못했다(Cloudflare 접속 불가). 검증 로직과 결과는 그대로 두고 duty cycle만 건다.

    부모에서 메서드 이름이 바뀌면 이 오버라이드는 호출되지 않는다 —
    CPU 양보만 사라지고 검증 자체는 정상 동작한다.
    """

    _WORK_SLICE = 0.05  # 0.05초 일한 뒤 duty 에 맞춰 쉰다

    def __init__(self, *args, cpu_duty: float = 0.25, **kwargs):
        super().__init__(*args, **kwargs)
        self._cpu_duty = min(max(cpu_duty, 0.05), 1.0)
        self._slice_started = time.monotonic()

    def _yield_cpu(self):
        elapsed = time.monotonic() - self._slice_started
        if elapsed < self._WORK_SLICE:
            return
        if self._cpu_duty < 1.0:
            time.sleep(elapsed * (1.0 / self._cpu_duty - 1.0))
        self._slice_started = time.monotonic()

    # 이벤트당 1회 호출되는 지점
    def _check_r14_same_event_duplicate_names(self, *args, **kwargs):
        result = super()._check_r14_same_event_duplicate_names(*args, **kwargs)
        self._yield_cpu()
        return result

    # 선수당 1회 호출되는 지점 — 검증 시간의 대부분
    def _validate_player_records(self, *args, **kwargs):
        result = super()._validate_player_records(*args, **kwargs)
        self._yield_cpu()
        return result


async def run_validation_async(
    competitions: List[Dict],
    org_cache: Optional[Dict] = None,
    cpu_duty: Optional[float] = None,
) -> Dict:
    """검증을 별도 스레드에서 CPU 양보하며 실행. 이벤트 루프를 막지 않는다.

    async 컨텍스트(스크래핑 후 검증, 헬스체크)에서는 run_validation() 대신 이걸 쓴다.
    """
    if cpu_duty is None:
        try:
            cpu_duty = float(os.getenv("VALIDATION_CPU_DUTY", "0.25"))
        except (TypeError, ValueError):
            cpu_duty = 0.25

    def _work() -> Dict:
        return run_validation(competitions, org_cache=org_cache, cpu_duty=cpu_duty)

    return await asyncio.to_thread(_work)


def run_validation(
    competitions: List[Dict],
    org_cache: Optional[Dict] = None,
    cpu_duty: Optional[float] = None,
) -> Dict:
    """전체 검증 실행 및 요약 반환

    cpu_duty 를 주면 검증 도중 CPU를 양보한다 (0.25 = 25%만 사용).
    """
    if cpu_duty is None:
        validator = DataValidator(competitions, org_cache=org_cache)
    else:
        validator = ThrottledDataValidator(competitions, org_cache=org_cache, cpu_duty=cpu_duty)
    issues = validator.validate_all()

    errors = [i for i in issues if i.severity == "ERROR"]
    warnings = [i for i in issues if i.severity == "WARNING"]
    resolved = [i for i in issues if i.severity == "RESOLVED"]

    # 규칙별 통계 (severity별)
    by_rule: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for issue in issues:
        by_rule[issue.rule_id][issue.severity] += 1

    # 하위 호환: by_rule 플랫 형태도 유지
    by_rule_flat: Dict[str, int] = defaultdict(int)
    for issue in issues:
        by_rule_flat[issue.rule_id] += 1

    return {
        "total_issues": len(issues),
        "errors": len(errors),
        "warnings": len(warnings),
        "resolved": len(resolved),
        "active_issues": len(errors) + len(warnings),
        "by_rule": dict(by_rule_flat),
        "by_rule_severity": {k: dict(v) for k, v in by_rule.items()},
        "issues": issues,
    }
