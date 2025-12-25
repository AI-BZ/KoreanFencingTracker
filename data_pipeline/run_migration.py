#!/usr/bin/env python3
"""
데이터 정규화 마이그레이션 실행 스크립트
사용법:
    python -m data_pipeline.run_migration --dry-run   # 미리보기
    python -m data_pipeline.run_migration --execute   # 실제 실행
"""
import asyncio
import argparse
import json
import sys
import os
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client, Client
from data_pipeline.pipeline import NormalizationMigration, MigrationResult


def get_supabase_client() -> Client:
    """Supabase 클라이언트 생성 (독립적)"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL과 SUPABASE_KEY 환경변수를 설정해주세요")
    return create_client(url, key)


def print_result(result: MigrationResult, verbose: bool = False):
    """마이그레이션 결과 출력"""
    print(f"\n{'='*60}")
    print(f"테이블: {result.table}")
    print(f"{'='*60}")
    print(f"총 레코드: {result.total_records:,}")
    print(f"정규화 대상: {result.normalized_count:,}")
    print(f"오류 건수: {result.error_count}")
    print(f"소요 시간: {result.duration_seconds:.2f}초")

    if verbose and result.changes:
        print(f"\n변경 내역 (상위 20건):")
        for i, change in enumerate(result.changes[:20]):
            print(f"  {i+1}. ID: {change.get('id')}")
            if 'changes' in change:
                for field, (old, new) in change['changes'].items():
                    print(f"      {field}: '{old}' → '{new}'")
            elif 'old_weapon' in change:
                print(f"      weapon: '{change['old_weapon']}' → '{change['new_weapon']}'")
            elif 'extracted_age_group' in change:
                print(f"      age_group: NULL → '{change['extracted_age_group']}'")
                print(f"      event_name: {change.get('event_name', '')[:50]}...")

        if len(result.changes) > 20:
            print(f"  ... 외 {len(result.changes) - 20}건")


async def run_migration(dry_run: bool = True, verbose: bool = False):
    """마이그레이션 실행"""
    print(f"\n{'#'*60}")
    print(f"# 데이터 정규화 마이그레이션 {'(미리보기)' if dry_run else '(실제 실행)'}")
    print(f"# 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}")

    if not dry_run:
        print("\n⚠️  경고: 실제 데이터가 변경됩니다!")
        confirm = input("계속하시겠습니까? (yes/no): ")
        if confirm.lower() != 'yes':
            print("취소됨")
            return

    supabase = get_supabase_client()
    migration = NormalizationMigration(supabase)

    results = []

    # 1. 무기명 정규화 (에페→에뻬, 플뢰레→플러레)
    print("\n[1/3] 무기명 정규화...")
    weapon_result = await migration.fix_weapon_names(dry_run=dry_run)
    print_result(weapon_result, verbose)
    results.append(weapon_result)

    # 2. age_group 추출 (event_name에서)
    print("\n[2/3] 연령대(age_group) 추출...")
    age_result = await migration.extract_age_groups(dry_run=dry_run)
    print_result(age_result, verbose)
    results.append(age_result)

    # 3. 전체 이벤트 정규화
    print("\n[3/3] 전체 이벤트 정규화...")
    event_result = await migration.normalize_events(dry_run=dry_run)
    print_result(event_result, verbose)
    results.append(event_result)

    # 요약
    print(f"\n{'='*60}")
    print("마이그레이션 요약")
    print(f"{'='*60}")
    total_normalized = sum(r.normalized_count for r in results)
    total_errors = sum(r.error_count for r in results)
    total_time = sum(r.duration_seconds for r in results)

    print(f"총 정규화 대상: {total_normalized:,} 건")
    print(f"총 오류: {total_errors} 건")
    print(f"총 소요 시간: {total_time:.2f}초")

    if dry_run:
        print(f"\n💡 실제 적용하려면 --execute 옵션을 사용하세요:")
        print(f"   python -m data_pipeline.run_migration --execute")

    return results


async def verify_data_integrity():
    """데이터 무결성 검증"""
    print("\n데이터 무결성 검증 중...")

    supabase = get_supabase_client()

    # 1. 무기명 체크 - 비표준 값 조회
    weapon_check = supabase.table("events").select("id, weapon", count="exact").in_(
        "weapon", ["에페", "플뢰레", ""]
    ).execute()

    non_standard_weapons = weapon_check.count or 0
    print(f"  비표준 무기명 (에페, 플뢰레, 빈값): {non_standard_weapons}건")

    # 2. age_group 체크
    age_check = supabase.table("events").select("id", count="exact").or_(
        "age_group.is.null,age_group.eq."
    ).execute()

    empty_age_groups = age_check.count or 0
    print(f"  빈 age_group: {empty_age_groups}건")

    # 3. 총 이벤트 수
    total_check = supabase.table("events").select("id", count="exact").execute()
    total_events = total_check.count or 0
    print(f"  총 이벤트: {total_events}건")

    # 4. 정규화율 계산
    normalized_age_rate = ((total_events - empty_age_groups) / total_events * 100) if total_events > 0 else 0
    print(f"  age_group 채워진 비율: {normalized_age_rate:.1f}%")

    if non_standard_weapons == 0:
        print("\n✅ 무기명 정규화 완료!")
    else:
        print(f"\n⚠️ 무기명 정규화 필요: {non_standard_weapons}건")

    return non_standard_weapons == 0


def main():
    parser = argparse.ArgumentParser(description="데이터 정규화 마이그레이션")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="미리보기 모드 (기본값)")
    parser.add_argument("--execute", action="store_true",
                        help="실제 실행 (데이터 변경)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="상세 출력")
    parser.add_argument("--verify", action="store_true",
                        help="데이터 무결성 검증만 수행")

    args = parser.parse_args()

    if args.verify:
        asyncio.run(verify_data_integrity())
    else:
        dry_run = not args.execute
        asyncio.run(run_migration(dry_run=dry_run, verbose=args.verbose))


if __name__ == "__main__":
    main()
