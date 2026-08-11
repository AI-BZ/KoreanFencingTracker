#!/usr/bin/env python3
"""
Dual DE 리스크래핑 결과 검증

리스크래핑 후 실행하여 flat dual_de 이벤트가 모두 구조화되었는지 확인.

사용법:
    cd services/data
    PYTHONPATH="." python scripts/verify_dual_de.py
"""

import os
import sys

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


def verify_all(supabase: Client) -> bool:
    """전체 검증 실행. Returns True if all pass."""
    all_pass = True

    # 1. de_format='dual_de'인 이벤트 전부 조회
    print("=" * 60)
    print("🔍 Dual DE 리스크래핑 검증")
    print("=" * 60)

    result = supabase.table("events") \
        .select("id, event_name, competition_id, raw_data, de_format") \
        .eq("de_format", "dual_de") \
        .execute()

    dual_events = result.data or []
    print(f"\n📊 de_format='dual_de' 이벤트: {len(dual_events)}개")

    # 검증 1: flat dual_de 잔존 확인
    flat_count = 0
    structured_count = 0
    missing_keys = []
    low_rankings = []

    for event in dual_events:
        raw_data = event.get("raw_data") or {}
        de_bracket = raw_data.get("de_bracket") or {}
        event_name = event.get("event_name", "Unknown")
        event_id = event["id"]

        has_format_key = de_bracket.get("format") == "dual_de"
        has_first_de = "first_de" in de_bracket
        has_second_de = "second_de" in de_bracket

        if has_format_key and has_first_de and has_second_de:
            structured_count += 1
        else:
            flat_count += 1
            issues = []
            if not has_format_key:
                issues.append("format키 없음")
            if not has_first_de:
                issues.append("first_de 없음")
            if not has_second_de:
                issues.append("second_de 없음")
            missing_keys.append(f"  ❌ [{event_id}] {event_name}: {', '.join(issues)}")

        # 검증 4: final_rankings 수 확인
        final_rankings = raw_data.get("final_rankings") or []
        bracket_size = de_bracket.get("bracket_size", 0)
        # dual_de는 first_de/second_de 각각의 bracket_size 합산
        if has_first_de and has_second_de:
            first_size = de_bracket.get("first_de", {}).get("bracket_size", 0)
            second_size = de_bracket.get("second_de", {}).get("bracket_size", 0)
            total_size = first_size + second_size
        else:
            total_size = bracket_size

        if total_size > 0 and len(final_rankings) < total_size * 0.5:
            low_rankings.append(
                f"  ⚠️ [{event_id}] {event_name}: "
                f"final_rankings={len(final_rankings)}, bracket_size={total_size}"
            )

    # 결과 출력
    print(f"\n✅ 검증 1: 구조화 dual_de = {structured_count}개")
    if flat_count > 0:
        print(f"❌ 검증 1 실패: flat dual_de 잔존 = {flat_count}개")
        for line in missing_keys:
            print(line)
        all_pass = False
    else:
        print("✅ flat dual_de 잔존 = 0개")

    # 검증 2+3: format 키 + first_de/second_de (위에서 이미 확인)
    print(f"\n✅ 검증 2-3: format=='dual_de' + first_de/second_de 키 → {'통과' if flat_count == 0 else '실패'}")

    # 검증 4: final_rankings
    if low_rankings:
        print(f"\n⚠️ 검증 4: final_rankings 부족 = {len(low_rankings)}개")
        for line in low_rankings:
            print(line)
    else:
        print("\n✅ 검증 4: final_rankings 모두 bracket_size 50% 이상")

    # 검증 5: flat dual_de 이벤트가 DB에 아직 남아있는지 (de_format은 dual_de이지만 de_bracket.format은 없는 경우)
    print(f"\n{'=' * 60}")
    flat_sql_count = 0
    for event in dual_events:
        raw_data = event.get("raw_data") or {}
        de_bracket = raw_data.get("de_bracket") or {}
        if de_bracket and de_bracket.get("format") != "dual_de":
            flat_sql_count += 1

    if flat_sql_count > 0:
        print(f"❌ de_format='dual_de' but de_bracket.format!='dual_de': {flat_sql_count}개")
        all_pass = False
    else:
        print("✅ 모든 dual_de 이벤트의 de_bracket.format 일치")

    # 최종 결과
    print(f"\n{'=' * 60}")
    if all_pass:
        print("🎉 전체 검증 통과!")
    else:
        print("⚠️ 일부 검증 실패 — 위 항목 확인 필요")
    print(f"{'=' * 60}")

    return all_pass


if __name__ == "__main__":
    supabase = get_supabase_client()
    success = verify_all(supabase)
    sys.exit(0 if success else 1)
