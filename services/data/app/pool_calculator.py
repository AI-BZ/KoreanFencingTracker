"""
Pool Total Ranking Calculator (풀 종합 순위 계산기)

pool_rounds 데이터를 집계하여 풀 종합 순위를 계산한다.
스크래핑 데이터가 없을 때 서버 자체 계산 결과를 표시하고,
스크래핑 데이터가 도착하면 비교 검증에 활용한다.

풀 순위 결정 기준 (FIE 규칙):
1. 승률 (V/M) - 내림차순
2. 지수 (indicator = 득점 - 실점) - 내림차순
3. 득점 (touches scored) - 내림차순
"""
from typing import List, Dict, Any

from loguru import logger


def calculate_pool_total_ranking(pool_rounds: List[Dict]) -> List[Dict]:
    """pool_rounds 데이터를 집계하여 풀 종합 순위를 계산

    Args:
        pool_rounds: [{pool_number, results: [{name, team, rank, wins, losses, indicator, touches/score, ...}]}]

    Returns:
        [{rank, name, team, wins, losses, indicator, touches, win_rate, total_bouts, source: "calculated"}]
    """
    if not pool_rounds:
        return []

    # 선수별 통계 집계
    player_stats: Dict[str, Dict[str, Any]] = {}
    forfeit_players: Dict[str, Dict[str, Any]] = {}  # 기권 선수 별도 관리

    for pool in pool_rounds:
        results = pool.get("results", [])
        for result in results:
            name = (result.get("name") or "").strip()
            if not name:
                continue

            team = (result.get("team") or "").strip()

            # 기권 선수는 별도 수집 (FIE t.95: 기권자 풀 결과 삭제)
            if result.get("is_forfeit"):
                key = f"{name}|{team}"
                if key not in forfeit_players:
                    forfeit_players[key] = {
                        "name": name,
                        "team": team,
                        "is_forfeit": True,
                    }
                continue

            wins = _safe_int(result.get("wins", 0))
            losses = _safe_int(result.get("losses", 0))
            indicator = _safe_int(result.get("indicator", 0))
            touches = _safe_int(result.get("touches") or result.get("score", 0))

            key = f"{name}|{team}"
            if key not in player_stats:
                player_stats[key] = {
                    "name": name,
                    "team": team,
                    "wins": 0,
                    "losses": 0,
                    "indicator": 0,
                    "touches": 0,
                }

            stats = player_stats[key]
            stats["wins"] += wins
            stats["losses"] += losses
            stats["indicator"] += indicator
            stats["touches"] += touches

    if not player_stats and not forfeit_players:
        return []

    # 승률 계산 및 정렬 (기권 선수 제외)
    rankings = []
    for stats in player_stats.values():
        total_bouts = stats["wins"] + stats["losses"]
        win_rate = stats["wins"] / total_bouts if total_bouts > 0 else 0.0
        rankings.append({
            "name": stats["name"],
            "team": stats["team"],
            "wins": stats["wins"],
            "losses": stats["losses"],
            "indicator": stats["indicator"],
            "touches": stats["touches"],
            "total_bouts": total_bouts,
            "win_rate": round(win_rate, 4),
        })

    # FIE 순위 결정: 승률 → 지수 → 득점 (모두 내림차순)
    rankings.sort(key=lambda x: (-x["win_rate"], -x["indicator"], -x["touches"]))

    # 순위 부여 (동순위 처리)
    for i, r in enumerate(rankings):
        if i == 0:
            r["rank"] = 1
        else:
            prev = rankings[i - 1]
            if (r["win_rate"] == prev["win_rate"] and
                    r["indicator"] == prev["indicator"] and
                    r["touches"] == prev["touches"]):
                r["rank"] = prev["rank"]  # 동순위
            else:
                r["rank"] = i + 1

        r["source"] = "calculated"

    # 기권 선수를 최하위에 추가 (FIE t.95: 순위표 맨 뒤, is_forfeit 마킹)
    if forfeit_players:
        last_rank = (rankings[-1]["rank"] + 1) if rankings else 1
        for fp in forfeit_players.values():
            rankings.append({
                "name": fp["name"],
                "team": fp["team"],
                "wins": 0,
                "losses": 0,
                "indicator": 0,
                "touches": 0,
                "total_bouts": 0,
                "win_rate": 0.0,
                "rank": last_rank,
                "source": "calculated",
                "is_forfeit": True,
            })
            logger.info(f"Pool 기권 선수: {fp['name']} ({fp['team']}) → 최하위 순위 {last_rank}")

    return rankings


def enrich_with_advancement_status(
    calculated: List[Dict],
    scraped: List[Dict],
) -> List[Dict]:
    """계산된 순위에 스크래핑된 진출/탈락 상태를 병합

    Args:
        calculated: calculate_pool_total_ranking()의 결과
        scraped: 스크래퍼가 가져온 pool_total_ranking (status='진출'/'탈락' 포함)

    Returns:
        calculated 목록에 status 필드가 추가된 결과
    """
    if not calculated or not scraped:
        return calculated

    # 스크래핑 데이터에서 진출자 이름 추출
    advanced_names = set()
    for r in scraped:
        if r.get("status") == "진출":
            name = (r.get("name") or "").strip()
            if name:
                advanced_names.add(name)

    # 진출자 정보가 없으면 원본 그대로 반환
    if not advanced_names:
        return calculated

    for r in calculated:
        name = r.get("name", "").strip()
        if name in advanced_names:
            r["status"] = "진출"

    return calculated


def compare_pool_rankings(
    calculated: List[Dict],
    scraped: List[Dict],
) -> Dict[str, Any]:
    """계산된 순위와 스크래핑된 순위를 비교

    Args:
        calculated: calculate_pool_total_ranking()의 결과
        scraped: 스크래퍼가 가져온 pool_total_ranking

    Returns:
        {
            "match": True/False,
            "total_calculated": int,
            "total_scraped": int,
            "differences": [
                {"name": str, "calc_rank": int, "scraped_rank": int, "detail": str}
            ],
            "missing_in_calculated": [str],
            "missing_in_scraped": [str],
        }
    """
    if not calculated or not scraped:
        return {
            "match": not calculated and not scraped,
            "total_calculated": len(calculated),
            "total_scraped": len(scraped),
            "differences": [],
            "missing_in_calculated": [],
            "missing_in_scraped": [],
        }

    # 이름 기반 매핑 (스크래핑 데이터는 name만 있을 수 있음)
    calc_by_name = {r["name"]: r for r in calculated}
    scraped_by_name = {}
    for i, r in enumerate(scraped):
        name = (r.get("name") or "").strip()
        if name:
            scraped_by_name[name] = {
                "rank": r.get("rank") or (i + 1),
                "team": r.get("team", ""),
            }

    differences = []
    missing_in_calculated = []
    missing_in_scraped = []

    # 스크래핑 데이터 기준으로 비교
    for name, scraped_info in scraped_by_name.items():
        if name not in calc_by_name:
            missing_in_calculated.append(name)
            continue

        calc_info = calc_by_name[name]
        calc_rank = calc_info["rank"]
        scraped_rank = scraped_info["rank"]

        if calc_rank != scraped_rank:
            diff = abs(calc_rank - scraped_rank)
            differences.append({
                "name": name,
                "calc_rank": calc_rank,
                "scraped_rank": scraped_rank,
                "rank_diff": diff,
                "detail": f"계산:{calc_rank}위 vs 스크래핑:{scraped_rank}위 (차이:{diff})",
            })

    # 계산에는 있지만 스크래핑에는 없는 선수
    for name in calc_by_name:
        if name not in scraped_by_name:
            missing_in_scraped.append(name)

    is_match = len(differences) == 0 and len(missing_in_calculated) == 0

    return {
        "match": is_match,
        "total_calculated": len(calculated),
        "total_scraped": len(scraped),
        "differences": differences,
        "missing_in_calculated": missing_in_calculated,
        "missing_in_scraped": missing_in_scraped,
    }


def _safe_int(val) -> int:
    """안전하게 정수 변환"""
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0
