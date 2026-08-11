"""DE/bout 변환 유틸리티.

server.py에서 추출한 자기완결적 DE(Direct Elimination) 브래킷 및 bout 변환
함수 모음. 동작 불변(behavior-preserving) 리팩터링으로 순수 이동됨.
"""
from typing import Dict, List, Set
from collections import defaultdict

from loguru import logger

from app.bracket_utils import normalize_bracket_data


def _normalize_bout_data(bout: Dict) -> Dict:
    """
    bout 데이터를 정규화합니다.

    중첩 형식(player1.name)을 flat 형식(player1_name)으로 변환합니다.
    이를 통해 서버 코드 전체에서 일관된 데이터 형식을 사용할 수 있습니다.

    Args:
        bout: 원본 bout 딕셔너리

    Returns:
        정규화된 bout 딕셔너리
    """
    if not bout or not isinstance(bout, dict):
        return bout

    normalized = dict(bout)  # 원본 복사

    # player1 중첩 형식 → flat 형식
    player1 = bout.get("player1", {})
    if isinstance(player1, dict):
        if "player1_name" not in normalized or not normalized["player1_name"]:
            normalized["player1_name"] = player1.get("name", "")
        if "player1_team" not in normalized or not normalized["player1_team"]:
            normalized["player1_team"] = player1.get("team", "")
        if "player1_score" not in normalized:
            score = player1.get("score")
            if score is not None:
                normalized["player1_score"] = score

    # player2 중첩 형식 → flat 형식
    player2 = bout.get("player2", {})
    if isinstance(player2, dict):
        if "player2_name" not in normalized or not normalized["player2_name"]:
            normalized["player2_name"] = player2.get("name", "")
        if "player2_team" not in normalized or not normalized["player2_team"]:
            normalized["player2_team"] = player2.get("team", "")
        if "player2_score" not in normalized:
            score = player2.get("score")
            if score is not None:
                normalized["player2_score"] = score

    # winner 중첩 형식 → flat 형식
    winner = bout.get("winner", {})
    if isinstance(winner, dict):
        if "winner_name" not in normalized or not normalized["winner_name"]:
            normalized["winner_name"] = winner.get("name", "")
        if "winner_team" not in normalized or not normalized["winner_team"]:
            normalized["winner_team"] = winner.get("team", "")

    # loser 중첩 형식 → flat 형식
    loser = bout.get("loser", {})
    if isinstance(loser, dict):
        if "loser_name" not in normalized or not normalized["loser_name"]:
            normalized["loser_name"] = loser.get("name", "")
        if "loser_team" not in normalized or not normalized["loser_team"]:
            normalized["loser_team"] = loser.get("team", "")

    # round/round_name 정규화
    if "round" in normalized and "round_name" not in normalized:
        normalized["round_name"] = normalized["round"]
    elif "round_name" in normalized and "round" not in normalized:
        normalized["round"] = normalized["round_name"]

    # winner_name이 null인 경우 점수 기반으로 winner 결정
    # 결승 등에서 wingbn 속성이 설정되지 않은 경우를 처리
    if not normalized.get("winner_name"):
        p1_score = normalized.get("player1_score")
        p2_score = normalized.get("player2_score")
        p1_name = normalized.get("player1_name", "")
        p2_name = normalized.get("player2_name", "")

        # 점수가 모두 있고 유효한 경우에만 처리
        if p1_score is not None and p2_score is not None and p1_name and p2_name:
            try:
                p1_score_int = int(p1_score) if not isinstance(p1_score, int) else p1_score
                p2_score_int = int(p2_score) if not isinstance(p2_score, int) else p2_score

                if p1_score_int > p2_score_int:
                    normalized["winner_name"] = p1_name
                    normalized["loser_name"] = p2_name
                elif p2_score_int > p1_score_int:
                    normalized["winner_name"] = p2_name
                    normalized["loser_name"] = p1_name
            except (ValueError, TypeError):
                pass  # 점수 변환 실패 시 무시

    return normalized


def _reconstruct_bouts_from_duplicated_bbr(
    raw_bouts: list, bracket_size: int
) -> List[Dict]:
    """중복된 bouts_by_round에서 올바른 라운드명으로 bout 재배정.

    스크래퍼 버그로 전체 브래킷 경기가 모든 라운드 키에 복사된 경우,
    match_number 범위를 이용해 각 bout의 실제 라운드를 결정합니다.

    bracket_size=32일 때:
      match #1~#16: 32강 (16경기)
      match #17~#24: 16강 (8경기)
      match #25~#28: 8강 (4경기)
      match #29~#30: 준결승 (2경기)
      match #31: 결승 (1경기)
    """
    if not raw_bouts or bracket_size < 4:
        return []

    # 라운드별 match_number 범위 계산
    round_ranges = []  # [(start, end, round_name)]
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
        nb = _normalize_bout_data(bout)
        mn = nb.get("match_number")
        if mn is not None:
            correct_round = get_round_for_match(int(mn))
            nb["round_name"] = correct_round
            nb["round"] = correct_round
        # self-bout 필터
        p1 = (nb.get("player1_name") or "").strip()
        p2 = (nb.get("player2_name") or "").strip()
        if p1 and p2 and p1 == p2:
            continue
        result.append(nb)
    return result


# 라운드 순서 (낮은 라운드 → 높은 라운드)
_ROUND_PROGRESSION = ["256강", "128강", "64강", "32강", "16강", "8강", "준결승", "결승"]
_ROUND_RANK = {r: i for i, r in enumerate(_ROUND_PROGRESSION)}


def _dedup_keep_highest_round(bouts: List[Dict]) -> List[Dict]:
    """동일 선수쌍 중복 제거: 가장 높은 라운드(진행이 늦은 라운드)의 bout만 유지.

    스크래퍼 버그로 같은 경기가 여러 라운드에 저장된 경우,
    예: 32강과 16강에 동일한 경기 → 16강(higher)만 유지.
    """
    best_bout: Dict[tuple, tuple] = {}

    for i, bout in enumerate(bouts):
        p1 = (bout.get("player1_name") or "").strip()
        p2 = (bout.get("player2_name") or "").strip()
        if not p1 or not p2:
            best_bout[("_nopair", i)] = (0, i, bout)
            continue

        pair_key = tuple(sorted([p1, p2]))
        rnd = (bout.get("round_name") or bout.get("round") or "").strip()
        rank = _ROUND_RANK.get(rnd, -1)

        if pair_key not in best_bout or rank > best_bout[pair_key][0]:
            best_bout[pair_key] = (rank, i, bout)

    return [bout for _, idx, bout in sorted(best_bout.values(), key=lambda x: x[1])]


def _get_full_bouts_from_de_bracket(de_bracket: Dict) -> List[Dict]:
    """
    DE bracket에서 full_bouts를 추출합니다.

    일부 이벤트는 full_bouts 필드 없이 bouts_by_round만 가지고 있습니다.
    이 함수는 full_bouts가 없거나 비어있으면 bouts_by_round에서 추출합니다.

    Args:
        de_bracket: DE bracket 데이터 딕셔너리

    Returns:
        bout 딕셔너리 리스트 (full_bouts 또는 bouts_by_round에서 추출)
    """
    if not de_bracket or not isinstance(de_bracket, dict):
        return []

    # dual_de 형식 처리: first_de와 second_de에서 재귀 추출 + de_phase 태깅
    if de_bracket.get("format") == "dual_de":
        all_bouts = []
        phase_map = {"first_de": "qualifying", "second_de": "main"}
        for sub_key in ("first_de", "second_de"):
            sub_bracket = de_bracket.get(sub_key, {})
            if isinstance(sub_bracket, dict):
                sub_bouts = _get_full_bouts_from_de_bracket(sub_bracket)
                phase = phase_map[sub_key]
                for bout in sub_bouts:
                    bout["de_phase"] = phase
                all_bouts.extend(sub_bouts)
        return all_bouts

    full_bouts = de_bracket.get("full_bouts", [])

    # full_bouts가 있고 비어있지 않으면 정규화 후 반환
    if full_bouts and isinstance(full_bouts, list) and len(full_bouts) > 0:
        # 각 bout 데이터 정규화 (중첩 형식 → flat 형식) + self-bout 필터
        normalized = []
        for bout in full_bouts:
            if not isinstance(bout, dict):
                continue
            nb = _normalize_bout_data(bout)
            p1 = (nb.get("player1_name") or "").strip()
            p2 = (nb.get("player2_name") or "").strip()
            if p1 and p2 and p1 == p2:
                continue  # self-bout 제외
            normalized.append(nb)
        # 중복 제거: 같은 선수쌍이 여러 라운드에 있으면 가장 높은 라운드만 유지
        return _dedup_keep_highest_round(normalized)

    # full_bouts가 없거나 비어있으면 bouts_by_round에서 추출
    bouts_by_round = de_bracket.get("bouts_by_round", {})
    if isinstance(bouts_by_round, dict):
        # 스크래퍼 버그 감지: 모든 라운드 키에 전체 브래킷 경기가 복사된 경우
        # (예: 8강=32, 16강=32, 32강=32 → 정상이면 8강=4, 16강=8, 32강=16)
        round_bout_counts = {k: len(v) for k, v in bouts_by_round.items() if isinstance(v, list)}
        counts = list(round_bout_counts.values())
        is_duplicated = False
        if len(counts) >= 2:
            max_count = max(counts)
            same_count = sum(1 for c in counts if c == max_count)
            # 절반 이상의 라운드가 같은 bout 수이고, 그 수가 4 초과면 중복 패턴
            if same_count >= len(counts) * 0.5 and max_count > 4:
                is_duplicated = True
                logger.warning(
                    f"⚠️ bouts_by_round 중복 감지: {round_bout_counts} → "
                    f"가장 많은 라운드 데이터만 사용"
                )

        if is_duplicated:
            # 가장 많은 bout을 가진 라운드 키 사용 (가장 완전한 데이터)
            best_key = max(round_bout_counts, key=round_bout_counts.get)
            raw_bouts = bouts_by_round[best_key]
            bracket_size = de_bracket.get("bracket_size", 0)
            full_bouts = _reconstruct_bouts_from_duplicated_bbr(
                raw_bouts, bracket_size
            )
        else:
            full_bouts = []
            for round_name, round_bouts in bouts_by_round.items():
                if isinstance(round_bouts, list):
                    for bout in round_bouts:
                        if isinstance(bout, dict):
                            # 정규화된 bout 생성
                            normalized_bout = _normalize_bout_data(bout)
                            # round_name 추가 (없으면)
                            if "round" not in normalized_bout and "round_name" not in normalized_bout:
                                normalized_bout["round"] = round_name
                                normalized_bout["round_name"] = round_name
                            # self-bout 필터 (p1==p2 스크래퍼 버그)
                            p1 = (normalized_bout.get("player1_name") or "").strip()
                            p2 = (normalized_bout.get("player2_name") or "").strip()
                            if p1 and p2 and p1 == p2:
                                continue
                            full_bouts.append(normalized_bout)
        return full_bouts

    return []


def _normalize_de_bracket_for_api(de_bracket: Dict) -> Dict:
    """
    API 응답용 DE 브라켓 정규화

    원본 구조를 유지하면서 bouts_by_round만 리매핑
    (bracket_size에 맞지 않는 라운드를 올바른 라운드로 변환)
    """
    if not de_bracket:
        return de_bracket

    # normalize_bracket_data 호출하여 리매핑 수행
    normalized = normalize_bracket_data(de_bracket)

    # Dual DE 형식인 경우 to_dict() 반환
    if hasattr(normalized, 'format') and normalized.format == 'dual_de':
        # NormalizedDualDEBracket 객체 - to_dict()로 변환
        return normalized.to_dict()

    # 원본 구조 복사
    result = dict(de_bracket)

    # 정규화된 값으로 교체
    result['bracket_size'] = normalized.bracket_size
    result['participant_count'] = normalized.participant_count
    result['starting_round'] = normalized.starting_round
    result['rounds'] = normalized.rounds

    # bouts_by_round 교체 (리매핑된 버전)
    result['bouts_by_round'] = {
        round_name: [bout.to_dict() for bout in bouts]
        for round_name, bouts in normalized.bouts_by_round.items()
    }

    # bouts도 교체 (리매핑된 버전)
    result['bouts'] = [bout.to_dict() for bout in normalized.bouts]

    return result


def _build_rank_chart_data(enriched_records: list) -> list:
    """Build chart data for rank progression line chart (최근 20개 대회)"""
    chart_data = []
    for r in sorted(enriched_records, key=lambda x: x.get("competition_date", "")):
        rank = r.get("rank")
        if rank and rank <= 64 and not r.get("is_in_progress"):
            chart_data.append({
                "label": (r.get("competition_name") or "")[:15],
                "date": r.get("competition_date", ""),
                "event": r.get("event_name", ""),
                "rank": rank,
                "total": r.get("total_participants", 0),
            })
    return chart_data[-20:]


def _extract_bout_player_info(bout: Dict) -> Dict:
    """
    다양한 bout 데이터 형식에서 플레이어 정보를 통일된 형태로 추출.

    지원 형식:
    1. flat: player1_name, player2_name, winner_name, player1_score, player2_score
    2. simple: player1, player2, winner, score1, score2 (문자열)
    3. nested: player1: {name, team}, player2: {name, team}, winner: {name}

    Returns:
        {"p1": name, "p2": name, "p1_team": team, "p2_team": team,
         "winner": name, "round_name": str, "is_bye": bool}
    """
    if not isinstance(bout, dict):
        return {}

    round_name = bout.get("round_name") or bout.get("round") or ""

    # 형식 1: flat (player1_name, player2_name, winner_name)
    if "player1_name" in bout:
        return {
            "p1": bout.get("player1_name") or "",
            "p2": bout.get("player2_name") or "",
            "p1_team": bout.get("player1_team") or "",
            "p2_team": bout.get("player2_team") or "",
            "winner": bout.get("winner_name") or bout.get("winner") or "",
            "round_name": round_name,
            "is_bye": bout.get("is_bye", False),
        }

    # 형식 2/3: player1 필드가 문자열인지 딕셔너리인지 확인
    p1_raw = bout.get("player1")
    p2_raw = bout.get("player2")
    winner_raw = bout.get("winner") or bout.get("winner_name")

    if isinstance(p1_raw, str):
        # 형식 2: simple string fields
        return {
            "p1": p1_raw or "",
            "p2": p2_raw if isinstance(p2_raw, str) else "",
            "p1_team": bout.get("team1") or bout.get("player1_team") or "",
            "p2_team": bout.get("team2") or bout.get("player2_team") or "",
            "winner": winner_raw if isinstance(winner_raw, str) else "",
            "round_name": round_name,
            "is_bye": bout.get("is_bye", False),
        }

    if isinstance(p1_raw, dict):
        # 형식 3: nested dict fields
        winner_name = ""
        if isinstance(winner_raw, dict):
            winner_name = winner_raw.get("name") or ""
        elif isinstance(winner_raw, str):
            winner_name = winner_raw
        return {
            "p1": p1_raw.get("name") or "",
            "p2": (p2_raw.get("name") or "") if isinstance(p2_raw, dict) else "",
            "p1_team": p1_raw.get("team") or "",
            "p2_team": (p2_raw.get("team") or "") if isinstance(p2_raw, dict) else "",
            "winner": winner_name,
            "round_name": round_name,
            "is_bye": bout.get("is_bye", False),
        }

    return {}


def compute_dual_de_final_rankings(de_bracket: Dict, pool_total_ranking: List = None) -> List[Dict]:
    """
    Dual DE 이벤트의 최종 순위를 Second DE 경기 결과에서 동적 계산.

    국가대표 선발전 등 Dual DE 형식에서는 DB에 저장된 final_rankings가
    First DE 결과일 수 있으므로, Second DE(본선) 경기 결과에서 직접 계산.

    순위 결정 원칙 (FIE 표준 - FencingTime 실제 결과 확인):
    - 1위: 결승 승자
    - 2위: 결승 패자
    - 3위 (동률 3T): 준결승 패자 2명 — 유일한 동률 순위
    - 5~8위: 8강 패자 4명, 풀 시드 순 개별 순위
    - 9~16위: 16강 패자 8명, 풀 시드 순 개별 순위
    - 17~32위: 32강 패자 16명, 풀 시드 순 개별 순위
    - 33~64위: 64강 패자 32명, 풀 시드 순 개별 순위
    - 65+: First DE 탈락자 (라운드별 시드 기반 개별 순위)
    - 이후: Pool 탈락자 (풀 순위 기반 개별 순위)

    Args:
        de_bracket: event raw_data의 de_bracket (format=="dual_de")
        pool_total_ranking: pool 종합 순위 리스트 (DE 미진출 선수 포함용)

    Returns:
        List[Dict]: [{"rank": 1, "name": "...", "team": "..."}, ...] 또는 빈 리스트
    """
    if not isinstance(de_bracket, dict):
        return []

    second_de = de_bracket.get("second_de", {})
    if not isinstance(second_de, dict):
        return []

    # Second DE에 bouts가 있는지 확인
    raw_bouts = second_de.get("bouts", [])
    if not raw_bouts:
        raw_bouts = second_de.get("full_bouts", [])
    if not raw_bouts:
        return []

    # 시딩 정보 (순위 내 정렬용)
    seeding_map: Dict[str, int] = {}
    for s in second_de.get("seeding", []):
        name = (s.get("name") or "").strip()
        seed = s.get("seed", 0)
        if name and seed:
            seeding_map[name] = seed

    # bout 데이터를 통일된 형식으로 파싱하여 라운드별 그룹화
    from app.bracket_utils import normalize_round_name
    bouts_by_round: Dict[str, List[Dict]] = defaultdict(list)
    for raw_bout in raw_bouts:
        info = _extract_bout_player_info(raw_bout)
        if info and info.get("round_name"):
            rn = normalize_round_name(info["round_name"])
            bouts_by_round[rn].append(info)

    final_rankings: List[Dict] = []
    assigned_players: Set[str] = set()

    def get_losers(round_name: str) -> List[Dict]:
        """특정 라운드에서 패자 목록 반환 (시딩 순으로 정렬)"""
        losers = []
        for bout_info in bouts_by_round.get(round_name, []):
            if bout_info.get("is_bye"):
                continue
            winner = bout_info["winner"].strip() if bout_info.get("winner") else ""
            p1 = bout_info["p1"].strip() if bout_info.get("p1") else ""
            p2 = bout_info["p2"].strip() if bout_info.get("p2") else ""
            if winner and p1 and p2:
                loser_name = p2 if winner == p1 else p1
                loser_team = bout_info["p2_team"] if winner == p1 else bout_info["p1_team"]
                if loser_name and loser_name not in assigned_players:
                    losers.append({
                        "name": loser_name,
                        "team": loser_team or "",
                        "_seed": seeding_map.get(loser_name, 999),
                    })
        # 같은 순위 내에서 시딩이 높은(숫자 작은) 선수가 먼저
        losers.sort(key=lambda x: x["_seed"])
        return losers

    # champion 정보 (bout 데이터보다 정확한 팀명 소스)
    champion_info = second_de.get("champion") or {}
    if isinstance(champion_info, str):
        try:
            import json as _json
            champion_info = _json.loads(champion_info)
        except Exception:
            champion_info = {}

    # 1. 결승: 1위(승자), 2위(패자)
    for bout_info in bouts_by_round.get("결승", []):
        winner = bout_info["winner"].strip() if bout_info.get("winner") else ""
        p1 = bout_info["p1"].strip() if bout_info.get("p1") else ""
        p2 = bout_info["p2"].strip() if bout_info.get("p2") else ""
        if winner and p1 and p2:
            winner_team = bout_info["p1_team"] if winner == p1 else bout_info["p2_team"]
            loser_name = p2 if winner == p1 else p1
            loser_team = bout_info["p2_team"] if winner == p1 else bout_info["p1_team"]

            # champion 객체의 팀명이 있으면 우선 사용 (bout 데이터가 부정확할 수 있음)
            if champion_info.get("name") == winner and champion_info.get("team"):
                winner_team = champion_info["team"]

            final_rankings.append({"rank": 1, "name": winner, "team": winner_team or ""})
            assigned_players.add(winner)

            if loser_name:
                final_rankings.append({"rank": 2, "name": loser_name, "team": loser_team or ""})
                assigned_players.add(loser_name)

    # 2. 준결승: 동률 3위 (FIE 표준 — 유일한 동률 순위)
    losers = get_losers("준결승")
    for loser in losers:
        final_rankings.append({
            "rank": 3,
            "name": loser["name"],
            "team": loser["team"],
        })
        assigned_players.add(loser["name"])

    # 3. 8강 이후: 시드 기반 개별 순위 (FIE 표준)
    #    같은 라운드 탈락자는 풀 시드 순으로 5,6,7,8 / 9,10,...,16 등 개별 부여
    for round_name, start_rank in [
        ("8강", 5), ("16강", 9),
        ("32강", 17), ("64강", 33), ("128강", 65),
    ]:
        losers = get_losers(round_name)
        for i, loser in enumerate(losers):
            final_rankings.append({
                "rank": start_rank + i,
                "name": loser["name"],
                "team": loser["team"],
            })
            assigned_players.add(loser["name"])

    if not final_rankings:
        return []

    # 4. First DE 탈락자들: 라운드별 시드 기반 개별 순위
    max_rank = max((r["rank"] for r in final_rankings), default=0)
    first_de = de_bracket.get("first_de", {})
    if isinstance(first_de, dict):
        first_de_bouts = first_de.get("bouts", []) or first_de.get("full_bouts", [])

        # First DE 시딩 정보 (second_de seeding도 fallback으로 사용)
        first_de_seeding: Dict[str, int] = {}
        for s in first_de.get("seeding", []):
            name = (s.get("name") or "").strip()
            seed = s.get("seed", 0)
            if name and seed:
                first_de_seeding[name] = seed

        # First DE bouts를 라운드별로 그룹화
        first_de_by_round: Dict[str, List[Dict]] = defaultdict(list)
        for raw_bout in first_de_bouts:
            info = _extract_bout_player_info(raw_bout)
            if not info:
                continue
            rn = normalize_round_name(info.get("round_name", ""))
            if rn:
                first_de_by_round[rn].append(info)

        # 라운드 순서: 결승에 가까운 라운드가 높은 순위
        # (64강 first_de 패자 > 128강 패자 > 256강 패자)
        round_priority = ["64강", "128강", "256강"]

        for round_name in round_priority:
            if round_name not in first_de_by_round:
                continue

            losers = []
            for bout_info in first_de_by_round[round_name]:
                if bout_info.get("is_bye"):
                    continue
                winner = bout_info["winner"].strip() if bout_info.get("winner") else ""
                p1 = bout_info["p1"].strip() if bout_info.get("p1") else ""
                p2 = bout_info["p2"].strip() if bout_info.get("p2") else ""
                if winner and p1 and p2:
                    loser_name = p2 if winner == p1 else p1
                    loser_team = bout_info["p2_team"] if winner == p1 else bout_info["p1_team"]
                    if loser_name and loser_name not in assigned_players:
                        losers.append({
                            "name": loser_name,
                            "team": loser_team or "",
                            "_seed": first_de_seeding.get(loser_name,
                                     seeding_map.get(loser_name, 999)),
                        })

            # 시드 순 정렬 (낮은 시드 = 높은 순위)
            losers.sort(key=lambda x: x["_seed"])

            # 개별 순위 부여
            next_rank = max_rank + 1
            for i, loser in enumerate(losers):
                final_rankings.append({
                    "rank": next_rank + i,
                    "name": loser["name"],
                    "team": loser["team"],
                })
                assigned_players.add(loser["name"])

            if losers:
                max_rank = next_rank + len(losers) - 1

    # 5. Pool-only 참가자 (DE 미진출자): 풀 순위 기반 개별 순위
    if pool_total_ranking:
        max_rank = max((r["rank"] for r in final_rankings), default=0)
        pool_only = []
        for pr in pool_total_ranking:
            pname = (pr.get("name") or "").strip()
            if pname and pname not in assigned_players:
                pool_only.append({
                    "name": pname,
                    "team": pr.get("team", ""),
                    "_pool_rank": pr.get("rank", 999),
                })

        # Pool 순위 순으로 정렬
        pool_only.sort(key=lambda x: x["_pool_rank"])

        next_rank = max_rank + 1
        for i, pp in enumerate(pool_only):
            final_rankings.append({
                "rank": next_rank + i,
                "name": pp["name"],
                "team": pp["team"],
            })

    # 순위순 정렬 (같은 순위 내에서는 이름순)
    final_rankings.sort(key=lambda x: (x["rank"], x["name"]))

    return final_rankings


def transform_de_bracket(event_data: Dict) -> Dict:
    """DE bracket 데이터를 템플릿 호환 형식으로 변환 (bracket_utils 사용)"""
    de_bracket = event_data.get("de_bracket", {})
    if not de_bracket:
        return event_data

    # bracket_utils로 정규화 (Dual DE 형식도 자동 감지)
    normalized = normalize_bracket_data(de_bracket)

    # NormalizedBracket이 None인 경우 원본 반환
    if normalized is None:
        return event_data

    # Dual DE 형식인 경우 dict로 변환하여 Jinja2 템플릿 호환성 확보
    if hasattr(normalized, 'format') and normalized.format == 'dual_de':
        # dataclass를 dict로 변환 (Jinja2에서 속성 접근 가능하도록)
        normalized_dict = normalized.to_dict()
        event_data["normalized_bracket"] = normalized_dict
        return event_data

    # 단일 DE: NormalizedBracket 객체를 event_data에 추가
    event_data["normalized_bracket"] = normalized

    # 기존 템플릿 호환성을 위한 변환 (레거시 지원 - 단일 DE만)
    # 속성명: bouts_by_round (matches_by_round 아님)
    transformed_rounds = {}
    if hasattr(normalized, 'bouts_by_round') and normalized.bouts_by_round:
        for round_name, bouts in normalized.bouts_by_round.items():
            transformed_rounds[round_name] = [b.to_dict() for b in bouts]

    event_data["de_bracket"] = transformed_rounds
    event_data["de_seeding"] = getattr(normalized, 'seeding', [])
    event_data["de_rounds"] = getattr(normalized, 'rounds', [])

    return event_data


def _is_de_final_complete(de_bracket: Dict) -> bool:
    """이벤트의 결승(Final) 경기가 완료되었는지 판정.

    최종순위는 결승이 끝난 뒤에만 확정된다. 결승 전에는 DE 진행 결과일 뿐이므로,
    진행 중 이벤트에서 브래킷 위치/시드로 추정한 조기 1·2·3등이 확정 순위처럼
    노출되는 것을 막는 게이트로 쓰인다.

    완료 조건: round_name이 '결승'인 bout이 존재하고, 그 bout에 승자가 기록되어
    있어야 한다 (winner_name이 있거나, 양쪽 점수가 확정적이어야 함).

    Args:
        de_bracket: DE bracket 데이터 (dual_de 포함). 원본(정규화 전) 딕셔너리.

    Returns:
        결승이 완료되었으면 True, 결승 bout이 없거나 미결이면 False.
    """
    if not de_bracket or not isinstance(de_bracket, dict):
        return False

    for bout in _get_full_bouts_from_de_bracket(de_bracket):
        round_name = (bout.get("round_name") or bout.get("round") or "").strip()
        if round_name != "결승":
            continue
        # 결승 bout 발견 — 승자 확정 여부 확인
        if (bout.get("winner_name") or "").strip():
            return True
        s1, s2 = bout.get("player1_score"), bout.get("player2_score")
        try:
            if s1 is not None and s2 is not None and str(s1) != "" and str(s2) != "" \
                    and int(s1) != int(s2):
                return True
        except (TypeError, ValueError):
            pass
    return False
