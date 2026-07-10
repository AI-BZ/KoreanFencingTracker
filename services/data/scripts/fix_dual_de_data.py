#!/usr/bin/env python3
"""
Dual DE 기존 데이터 일괄 보정 스크립트

기존 DB에 저장된 dual_de 이벤트들의 데이터를 보정합니다:
1. 각 bout의 winner_name 추론 (점수 기반, wingbn 미설정 시)
2. champion 추론 (결승 bout에서)
3. status 재계산 (경기 데이터 기반)
4. full_bouts 재구성 (first_de + second_de 합산)
5. participant_count 계산

사용법:
    cd services/data
    PYTHONPATH=".:../../packages" python scripts/fix_dual_de_data.py --dry-run
    PYTHONPATH=".:../../packages" python scripts/fix_dual_de_data.py --execute
"""

import argparse
import os
import sys
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client, Client


def get_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL", "https://tjfjuasvjzjawyckengv.supabase.co")
    key = os.environ.get("SUPABASE_KEY")
    if not key:
        from dotenv import load_dotenv
        load_dotenv()
        key = os.environ.get("SUPABASE_KEY")
    if not key:
        raise ValueError("SUPABASE_KEY 환경변수가 필요합니다")
    return create_client(url, key)


def infer_winner_for_bout(bout: Dict[str, Any]) -> Optional[str]:
    """bout에서 점수 기반으로 승자 추론. 이미 winner_name이 있으면 그대로 반환."""
    winner = bout.get("winner_name")
    if winner:
        return winner

    p1 = bout.get("player1_name") or bout.get("red_name")
    p2 = bout.get("player2_name") or bout.get("green_name")

    s1 = bout.get("player1_score") or bout.get("score1") or bout.get("red_score")
    s2 = bout.get("player2_score") or bout.get("score2") or bout.get("green_score")

    try:
        s1_int = int(s1) if s1 is not None else 0
        s2_int = int(s2) if s2 is not None else 0
    except (ValueError, TypeError):
        return None

    if s1_int > s2_int and s1_int > 0 and p1:
        return p1
    elif s2_int > s1_int and s2_int > 0 and p2:
        return p2
    return None


def get_bouts_from_sub_bracket(sub: Dict[str, Any]) -> List[Dict[str, Any]]:
    """서브 브라켓에서 bouts 추출 (재귀적)."""
    bouts = sub.get("bouts") or sub.get("full_bouts") or []
    if bouts:
        return bouts

    # matches 구조에서 변환
    matches = sub.get("matches", [])
    result = []
    for m in matches:
        bout = {
            "player1_name": m.get("red_name"),
            "player2_name": m.get("green_name"),
            "player1_score": m.get("red_score"),
            "player2_score": m.get("green_score"),
            "winner_name": m.get("winner_name"),
            "round_name": m.get("round_name"),
            "match_number": m.get("match_number"),
        }
        result.append(bout)
    return result


def infer_champion_from_bouts(bouts: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """결승 bout에서 champion 추론."""
    final_round_names = ('결승', 'Final', '1-2', '2강')
    final_bouts = [b for b in bouts if b.get("round_name") in final_round_names]
    if not final_bouts:
        return None

    bout = final_bouts[0]
    winner = infer_winner_for_bout(bout)
    if winner:
        # winner_team 추론
        p1 = bout.get("player1_name") or bout.get("red_name")
        p2 = bout.get("player2_name") or bout.get("green_name")
        if winner == p1:
            team = bout.get("player1_team") or bout.get("red_team") or ""
        elif winner == p2:
            team = bout.get("player2_team") or bout.get("green_team") or ""
        else:
            team = ""
        return {"name": winner, "team": team}
    return None


def determine_status(first_de: Dict, second_de: Optional[Dict]) -> str:
    """경기 데이터 기반 status 결정."""
    if not first_de:
        return "pending"

    first_bouts = get_bouts_from_sub_bracket(first_de)

    # second_de가 존재하면 first_de는 이미 완료된 것
    if second_de:
        second_bouts = get_bouts_from_sub_bracket(second_de)
        if not second_bouts:
            return "second_de_in_progress"

        # 결승 완료 여부
        final_round_names = ('결승', 'Final', '1-2', '2강')
        final_bouts = [b for b in second_bouts if b.get("round_name") in final_round_names]
        if final_bouts and infer_winner_for_bout(final_bouts[0]):
            return "completed"

        # 결승이 없거나 승자 미정이어도, 준결승 이상 라운드가 있으면 completed 처리
        # (KFF에서 결승 점수를 0-0으로 기록한 경우)
        round_names = set(b.get("round_name") for b in second_bouts)
        if '준결승' in round_names or '결승' in round_names:
            return "completed"

        return "second_de_in_progress"

    # second_de 없음
    if not first_bouts:
        return "first_de_in_progress"

    # first_de: 모든 경기에 승자 있는지
    non_bye_first = [b for b in first_bouts
                     if b.get("player1_name") and b.get("player2_name")]
    if non_bye_first:
        all_winners = all(infer_winner_for_bout(b) for b in non_bye_first)
        if not all_winners:
            return "first_de_in_progress"

    return "first_de_complete"


def fix_event(raw_data: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """단일 이벤트의 raw_data를 보정. (변경된 raw_data, 변경사항 목록) 반환."""
    changes = []
    data = deepcopy(raw_data)
    de_bracket = data.get("de_bracket")
    if not de_bracket:
        return data, []

    first_de = de_bracket.get("first_de") or {}
    second_de = de_bracket.get("second_de") or {}

    # 1. bout별 winner_name 추론
    winner_fixed = 0
    for label, sub in [("first_de", first_de), ("second_de", second_de)]:
        bouts = get_bouts_from_sub_bracket(sub)
        for bout in bouts:
            if not bout.get("winner_name"):
                inferred = infer_winner_for_bout(bout)
                if inferred:
                    bout["winner_name"] = inferred
                    winner_fixed += 1
        # bouts를 다시 저장
        if bouts and "bouts" in sub:
            sub["bouts"] = bouts
        elif bouts and "full_bouts" in sub:
            sub["full_bouts"] = bouts

    if winner_fixed > 0:
        changes.append(f"winner_name 추론: {winner_fixed}건")

    # 2. full_bouts 재구성
    first_bouts = get_bouts_from_sub_bracket(first_de)
    second_bouts = get_bouts_from_sub_bracket(second_de)
    all_bouts = first_bouts + second_bouts
    old_full_bouts = de_bracket.get("full_bouts") or []
    if len(all_bouts) != len(old_full_bouts):
        changes.append(f"full_bouts: {len(old_full_bouts)} → {len(all_bouts)}")
    de_bracket["full_bouts"] = all_bouts

    # 3. participant_count 계산
    player_names = set()
    for b in all_bouts:
        for key in ("player1_name", "player2_name", "red_name", "green_name"):
            name = b.get(key)
            if name:
                player_names.add(name)
    old_count = de_bracket.get("participant_count", 0)
    new_count = len(player_names)
    if old_count != new_count:
        changes.append(f"participant_count: {old_count} → {new_count}")
    de_bracket["participant_count"] = new_count

    # 4. champion 추론
    old_champion = de_bracket.get("champion")
    # second_de의 bouts에서 champion 추론
    champion = None
    if second_bouts:
        champion = infer_champion_from_bouts(second_bouts)
    if not champion and all_bouts:
        champion = infer_champion_from_bouts(all_bouts)

    if champion and not old_champion:
        changes.append(f"champion: null → {champion['name']}")
        de_bracket["champion"] = champion
    elif champion and old_champion:
        old_name = old_champion.get("name") if isinstance(old_champion, dict) else str(old_champion)
        if old_name != champion["name"]:
            changes.append(f"champion: {old_name} → {champion['name']}")
            de_bracket["champion"] = champion

    # 5. status 재계산
    old_status = de_bracket.get("status", "")
    new_status = determine_status(first_de, second_de if second_de else None)
    if old_status != new_status:
        changes.append(f"status: {old_status} → {new_status}")
    de_bracket["status"] = new_status

    # 서브 브라켓 업데이트
    if first_de:
        de_bracket["first_de"] = first_de
    if second_de:
        de_bracket["second_de"] = second_de

    data["de_bracket"] = de_bracket
    return data, changes


def main():
    parser = argparse.ArgumentParser(description="Dual DE 기존 데이터 일괄 보정")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="변경 내용만 출력 (기본값)")
    parser.add_argument("--execute", action="store_true",
                        help="실제 DB 업데이트 실행")
    args = parser.parse_args()

    execute = args.execute
    if execute:
        print("🔴 실행 모드: DB에 실제 업데이트를 적용합니다!")
    else:
        print("🔵 Dry-run 모드: 변경 내용만 출력합니다.")

    supabase = get_supabase_client()

    # dual_de 이벤트 전체 조회
    print("\n📊 dual_de 이벤트 조회 중...")
    result = supabase.table("events") \
        .select("id, event_name, competition_id, raw_data, de_format") \
        .eq("de_format", "dual_de") \
        .execute()

    events = result.data or []
    print(f"   총 {len(events)}개 이벤트 발견\n")

    if not events:
        print("✅ dual_de 이벤트가 없습니다.")
        return

    total_changes = 0
    updated_count = 0
    error_count = 0
    stats = {
        "winner_inferred": 0,
        "champion_inferred": 0,
        "status_changed": 0,
        "full_bouts_fixed": 0,
    }

    print("=" * 70)
    for i, event in enumerate(events, 1):
        event_id = event["id"]
        event_name = event.get("event_name", "Unknown")
        raw_data = event.get("raw_data") or {}

        try:
            fixed_data, changes = fix_event(raw_data)
        except Exception as e:
            print(f"❌ [{event_id}] {event_name}: 오류 - {e}")
            error_count += 1
            continue

        if not changes:
            continue

        # 통계 수집
        for c in changes:
            if "winner_name" in c:
                stats["winner_inferred"] += 1
            if "champion" in c:
                stats["champion_inferred"] += 1
            if "status" in c:
                stats["status_changed"] += 1
            if "full_bouts" in c:
                stats["full_bouts_fixed"] += 1

        total_changes += len(changes)
        updated_count += 1

        print(f"\n[{i}/{len(events)}] {event_name} (id={event_id})")
        for c in changes:
            print(f"  → {c}")

        if execute:
            try:
                supabase.table("events").update({
                    "raw_data": fixed_data
                }).eq("id", event_id).execute()
                print("  ✅ DB 업데이트 완료")
            except Exception as e:
                print(f"  ❌ DB 업데이트 실패: {e}")
                error_count += 1

    # 최종 결과
    print("\n" + "=" * 70)
    print("\n📊 보정 결과 요약:")
    print(f"  전체 이벤트: {len(events)}개")
    print(f"  변경된 이벤트: {updated_count}개")
    print(f"  총 변경 항목: {total_changes}건")
    print(f"  오류: {error_count}건")
    print("\n  상세:")
    print(f"    winner_name 추론: {stats['winner_inferred']}개 이벤트")
    print(f"    champion 추론: {stats['champion_inferred']}개 이벤트")
    print(f"    status 변경: {stats['status_changed']}개 이벤트")
    print(f"    full_bouts 재구성: {stats['full_bouts_fixed']}개 이벤트")

    if not execute and updated_count > 0:
        print("\n💡 실제 적용하려면: PYTHONPATH=\".:../../packages\" python scripts/fix_dual_de_data.py --execute")


if __name__ == "__main__":
    main()
