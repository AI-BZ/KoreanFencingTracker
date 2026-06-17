"""
데이터 무결성 검증 시스템 (Data Integrity Validator)

모든 선수/이벤트에서 논리적 오류를 자동 탐지.
서버 시작 시 자동 실행 + API 엔드포인트로 수동 호출 가능.

검증 규칙:
  이벤트 레벨:
    R1: full_bouts 내부 중복 (동일 player1+player2+round)
    R2: winner_name 일관성 (winner ∉ {player1, player2})
    R3: 점수 범위 이상 (DE > 15, 음수, 동점인데 승자 있음)
    R4: 빈 round_name / 비표준 round_name
    R5: bracket 토폴로지 위반 (round N 승자가 round N+1에 없음)
    R6: final_rankings vs DE bracket 불일치

  선수 레벨:
    R7: 이벤트 내 동일 라운드 2경기 이상 (tournament_bouts 중복)
    R8: 라운드 진행 보존법칙 (round N wins > round N+1 total)
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
"""

import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict
from loguru import logger

from app.player_identity import PlayerIdentityResolver, get_team_type
from app.grade_estimator import GradeEstimator

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


class DataValidator:
    """데이터 무결성 검증기"""

    def __init__(self, competitions: List[Dict], org_cache: Optional[Dict[str, Dict[str, str]]] = None):
        self.competitions = competitions
        self.issues: List[ValidationIssue] = []
        # org_cache: {org_name: {org_type, province, city, ...}} from server.py _org_region_cache
        self.org_cache = org_cache or {}

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

                # pool_total_ranking에서 선수 수집
                for ranking in event.get("pool_total_ranking", []):
                    name = (ranking.get("name") or "").strip()
                    if name:
                        player_records[name].append({
                            "event_cd": event_cd,
                            "event_name": event_name,
                            "comp_name": comp_name,
                            "comp_date": comp_date,
                            "rank": ranking.get("rank"),
                            "team": ranking.get("team", ""),
                        })

                # final_rankings에서도 수집 (pool 없는 경우)
                for ranking in (event.get("final_rankings") or []):
                    name = (ranking.get("name") or "").strip()
                    if name and name not in player_records:
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

                # dual_de: 서브브라켓별 독립 검증
                if isinstance(de_bracket, dict) and de_bracket.get("format") == "dual_de":
                    first_bouts, second_bouts = _get_dual_de_sub_bouts(de_bracket)
                    for label, bouts in [("first_de", first_bouts), ("second_de", second_bouts)]:
                        self._r7_count_rounds(
                            player_lower, player_name, bouts,
                            event_cd, event_name, comp_name, label
                        )
                else:
                    full_bouts = _get_full_bouts_from_bracket(de_bracket)
                    self._r7_count_rounds(
                        player_lower, player_name, full_bouts,
                        event_cd, event_name, comp_name, ""
                    )

    def _r7_count_rounds(
        self, player_lower: str, player_name: str, bouts: List[Dict],
        event_cd: str, event_name: str, comp_name: str, bracket_label: str
    ):
        """R7 보조: bout 리스트에서 라운드별 중복 체크"""
        round_counts: Dict[str, int] = defaultdict(int)
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
                round_counts[rnd] += 1

        bracket_info = f" [{bracket_label}]" if bracket_label else ""
        for rnd, count in round_counts.items():
            if count > 1:
                self.issues.append(ValidationIssue(
                    rule_id="R7",
                    severity="ERROR",
                    player_name=player_name,
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=f"[{event_name}]{bracket_info} '{player_name}'이 {rnd}에서 {count}경기 (중복)",
                    data={"round": rnd, "bout_count": count, "bracket": bracket_label},
                ))

    def _check_r8_round_progression(self, player_name: str, records: List[Dict]):
        """R8: 라운드 진행 보존법칙 — round N wins > round N+1 total 이면 오류

        per-event 검증: 이벤트별로 독립적으로 검증하여 cross-event 합산 오탐 방지.
        시작 라운드(bracket_size) 이하의 비교는 건너뜀.
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

                # dual_de: 서브브라켓별 독립 검증
                # (first_de와 second_de의 같은 라운드명을 합산하면 오탐 발생)
                if de_bracket.get("format") == "dual_de":
                    for label in ("first_de", "second_de"):
                        sub = de_bracket.get(label, {})
                        if isinstance(sub, dict):
                            sub_bouts = _get_full_bouts_from_bracket(sub)
                            if sub_bouts:
                                self._r8_validate_bouts(
                                    player_lower, player_name, sub_bouts, sub,
                                    event_cd, f"{event_name} [{label}]", comp_name
                                )
                    continue

                full_bouts = _get_full_bouts_from_bracket(de_bracket)
                if not full_bouts:
                    continue

                # per-event round stats
                round_stats: Dict[str, Dict[str, int]] = {
                    cat: {"wins": 0, "losses": 0} for cat in CATEGORY_ORDER
                }
                seen_bouts: Set[str] = set()
                player_found = False

                for bout in full_bouts:
                    if bout.get("is_bye") or _is_self_bout(bout):
                        continue

                    winner = (bout.get("winner_name") or "").strip().lower()
                    p1 = (bout.get("player1_name") or "").strip().lower()
                    p2 = (bout.get("player2_name") or "").strip().lower()
                    rnd = (bout.get("round_name") or bout.get("round") or "").strip()

                    if not rnd or player_lower not in (p1, p2):
                        continue

                    player_found = True

                    # 중복 방지
                    opponent = p2 if player_lower == p1 else p1
                    bout_key = f"{rnd}|{opponent}"
                    if bout_key in seen_bouts:
                        continue
                    seen_bouts.add(bout_key)

                    category = get_round_category(rnd)
                    if category not in round_stats:
                        continue

                    if winner == player_lower:
                        round_stats[category]["wins"] += 1
                    else:
                        round_stats[category]["losses"] += 1

                if not player_found:
                    continue

                # 시작 라운드 파악: bracket 메타데이터 또는 bracket_size에서 추론
                starting_round = de_bracket.get("starting_round", "")
                bracket_size = de_bracket.get("bracket_size", 0)
                if not starting_round and bracket_size:
                    if bracket_size <= 8:
                        starting_round = "8강"
                    elif bracket_size <= 16:
                        starting_round = "16강"
                    elif bracket_size <= 32:
                        starting_round = "32강"
                    elif bracket_size <= 64:
                        starting_round = "64강"
                    else:
                        starting_round = "128강"

                starting_cat_idx = 0
                if starting_round:
                    starting_cat = get_round_category(starting_round)
                    if starting_cat in CATEGORY_ORDER:
                        starting_cat_idx = CATEGORY_ORDER.index(starting_cat)

                # 보존법칙 검증: 시작 라운드 이상에서만 체크
                for i in range(starting_cat_idx, len(CATEGORY_ORDER) - 1):
                    curr_cat = CATEGORY_ORDER[i]
                    next_cat = CATEGORY_ORDER[i + 1]

                    curr_wins = round_stats[curr_cat]["wins"]
                    next_total = round_stats[next_cat]["wins"] + round_stats[next_cat]["losses"]

                    if curr_wins == 0 or next_total == 0:
                        continue

                    if curr_wins > next_total:
                        diff = curr_wins - next_total
                        self.issues.append(ValidationIssue(
                            rule_id="R8",
                            severity="ERROR",
                            player_name=player_name,
                            event_cd=event_cd,
                            competition_name=comp_name,
                            message=(
                                f"[{event_name}] 라운드 진행 보존법칙 위반: "
                                f"{CATEGORY_NAMES[curr_cat]} 승리 {curr_wins}회 → "
                                f"{CATEGORY_NAMES[next_cat]} 출전 {next_total}회 "
                                f"({diff}경기 유실)"
                            ),
                            data={
                                "current_round": curr_cat,
                                "current_wins": curr_wins,
                                "next_round": next_cat,
                                "next_total": next_total,
                                "missing": diff,
                                "event_cd": event_cd,
                            },
                        ))

    def _r8_validate_bouts(
        self, player_lower: str, player_name: str, full_bouts: List[Dict],
        de_bracket: Dict, event_cd: str, event_name: str, comp_name: str
    ):
        """R8 보조: bout 리스트에서 라운드 진행 보존법칙 검증"""
        round_stats: Dict[str, Dict[str, int]] = {
            cat: {"wins": 0, "losses": 0} for cat in CATEGORY_ORDER
        }
        seen_bouts: Set[str] = set()
        player_found = False

        for bout in full_bouts:
            if bout.get("is_bye") or _is_self_bout(bout):
                continue

            winner = (bout.get("winner_name") or "").strip().lower()
            p1 = (bout.get("player1_name") or "").strip().lower()
            p2 = (bout.get("player2_name") or "").strip().lower()
            rnd = (bout.get("round_name") or bout.get("round") or "").strip()

            if not rnd or player_lower not in (p1, p2):
                continue

            player_found = True

            opponent = p2 if player_lower == p1 else p1
            bout_key = f"{rnd}|{opponent}"
            if bout_key in seen_bouts:
                continue
            seen_bouts.add(bout_key)

            category = get_round_category(rnd)
            if category not in round_stats:
                continue

            if winner == player_lower:
                round_stats[category]["wins"] += 1
            else:
                round_stats[category]["losses"] += 1

        if not player_found:
            return

        starting_round = de_bracket.get("starting_round", "") if isinstance(de_bracket, dict) else ""
        bracket_size = de_bracket.get("bracket_size", 0) if isinstance(de_bracket, dict) else 0
        if not starting_round and bracket_size:
            if bracket_size <= 8:
                starting_round = "8강"
            elif bracket_size <= 16:
                starting_round = "16강"
            elif bracket_size <= 32:
                starting_round = "32강"
            elif bracket_size <= 64:
                starting_round = "64강"
            else:
                starting_round = "128강"

        starting_cat_idx = 0
        if starting_round:
            starting_cat = get_round_category(starting_round)
            if starting_cat in CATEGORY_ORDER:
                starting_cat_idx = CATEGORY_ORDER.index(starting_cat)

        for i in range(starting_cat_idx, len(CATEGORY_ORDER) - 1):
            curr_cat = CATEGORY_ORDER[i]
            next_cat = CATEGORY_ORDER[i + 1]

            curr_wins = round_stats[curr_cat]["wins"]
            next_total = round_stats[next_cat]["wins"] + round_stats[next_cat]["losses"]

            if curr_wins == 0 or next_total == 0:
                continue

            if curr_wins > next_total:
                diff = curr_wins - next_total
                self.issues.append(ValidationIssue(
                    rule_id="R8",
                    severity="ERROR",
                    player_name=player_name,
                    event_cd=event_cd,
                    competition_name=comp_name,
                    message=(
                        f"[{event_name}] 라운드 진행 보존법칙 위반: "
                        f"{CATEGORY_NAMES[curr_cat]} 승리 {curr_wins}회 → "
                        f"{CATEGORY_NAMES[next_cat]} 출전 {next_total}회 "
                        f"({diff}경기 유실)"
                    ),
                    data={
                        "current_round": curr_cat,
                        "current_wins": curr_wins,
                        "next_round": next_cat,
                        "next_total": next_total,
                        "missing": diff,
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
                severity = "RESOLVED" if is_registered else "ERROR"
                suffix = " [KNOWN_HOMONYMS 등록됨]" if is_registered else ""
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
            severity = "RESOLVED" if is_registered else "ERROR"
            suffix = " [KNOWN_HOMONYMS 등록됨]" if is_registered else ""
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
                self.issues.append(ValidationIssue(
                    rule_id="R11",
                    severity=severity,
                    player_name=player_name,
                    event_cd="",
                    competition_name="",
                    message=(
                        f"'{player_name}' 나이그룹 역행: "
                        f"{max_group_seen}({max_date_seen}) → {group}({comp_date})"
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

            if is_registered:
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
        pool_total = raw_data.get("pool_total_ranking", [])
        pool_rounds = raw_data.get("pool_rounds", [])

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
        bouts = _get_full_bouts_from_bracket(bracket)
        bout_count = len(bouts)
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


def run_validation(competitions: List[Dict]) -> Dict:
    """전체 검증 실행 및 요약 반환"""
    validator = DataValidator(competitions)
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
