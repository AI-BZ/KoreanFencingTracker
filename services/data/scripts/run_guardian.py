#!/usr/bin/env python3
"""
Data Guardian CLI — 수동 실행용 엔트리포인트

사용법:
    cd services/data
    PYTHONPATH="." python scripts/run_guardian.py validate        # 전체 검증 + Discord
    PYTHONPATH="." python scripts/run_guardian.py health           # 건강 점검 + Discord
    PYTHONPATH="." python scripts/run_guardian.py report           # 주간 리포트 + Discord
    PYTHONPATH="." python scripts/run_guardian.py status           # 상태만 출력 (Discord 안 보냄)
"""

import asyncio
import sys
import os

# .env 로드
from dotenv import load_dotenv
load_dotenv()


async def cmd_validate():
    """전체 데이터 검증 + Discord 보고"""
    from app.data_guardian import get_guardian
    guardian = get_guardian()
    result = await guardian.run_full_validation()

    print("\n=== 검증 결과 ===")
    print(f"상태: {result.get('status', 'unknown')}")
    print(f"전체 이슈: {result.get('total_issues', 0)}")
    print(f"  ERROR: {result.get('errors', 0)}")
    print(f"  WARNING: {result.get('warnings', 0)}")

    by_rule = result.get("by_rule", {})
    if by_rule:
        print("\n규칙별 분포:")
        for rule, count in sorted(by_rule.items()):
            print(f"  {rule}: {count}건")

    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    if webhook:
        print("\nDiscord 알림 발송 완료")
    else:
        print("\nDISCORD_WEBHOOK_URL 미설정 — Discord 알림 미발송")


async def cmd_health():
    """건강 상태 점검 + Discord 보고"""
    from app.data_guardian import get_guardian
    guardian = get_guardian()
    result = await guardian.daily_health_check()

    print("\n=== 건강 점검 결과 ===")
    print(f"상태: {result.get('health_status', 'unknown')}")

    checks = result.get("checks", {})

    if "validation" in checks:
        v = checks["validation"]
        print(f"\n검증: ERROR {v.get('errors', 0)}건, WARNING {v.get('warnings', 0)}건")

    if "freshness" in checks:
        f = checks["freshness"]
        print(f"\n데이터 신선도: {f.get('stale_count', 0)}개 테이블 오래됨")
        for table, detail in f.get("details", {}).items():
            status = "STALE" if detail.get("is_stale") else "OK"
            hours = detail.get("hours_ago", "?")
            print(f"  {table}: {status} ({hours}시간 전)")

    if "homonyms" in checks:
        h = checks["homonyms"]
        count = h.get("unregistered_count", 0)
        if count > 0:
            print(f"\n동명이인 미등록: {count}건")
            for name in h.get("names", [])[:5]:
                print(f"  - {name}")


async def cmd_report():
    """주간 리포트 생성 + Discord 발송"""
    from app.data_guardian import get_guardian
    guardian = get_guardian()
    result = await guardian.weekly_report()

    print("\n=== 주간 리포트 ===")
    print(f"검증 실행: {result.get('validation_runs', 0)}회")
    print(f"ERROR 누적: {result.get('total_errors', 0)}건")
    print(f"WARNING 누적: {result.get('total_warnings', 0)}건")
    print(f"대회 수집: {result.get('scrape_competitions', 0)}개")
    print(f"종목 수집: {result.get('scrape_events', 0)}개")
    print(f"변경 감지: {result.get('changes_detected', 0)}건")
    print(f"\n주간 통계 리셋 완료")


async def cmd_status():
    """현재 상태 출력 (Discord 안 보냄)"""
    from app.data_guardian import get_guardian
    guardian = get_guardian()

    print("\n=== Data Guardian 상태 ===")

    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    print(f"Discord Webhook: {'설정됨' if webhook else '미설정'}")

    # 주간 통계
    stats = guardian._weekly_stats
    print(f"\n주간 누적 통계 (시작: {stats.get('week_start', '?')}):")
    print(f"  검증 실행: {stats.get('validation_runs', 0)}회")
    print(f"  ERROR: {stats.get('total_errors', 0)}건")
    print(f"  WARNING: {stats.get('total_warnings', 0)}건")
    print(f"  대회 수집: {stats.get('scrape_competitions', 0)}개")
    print(f"  종목 수집: {stats.get('scrape_events', 0)}개")

    # DB 연결 테스트
    db = guardian._get_db()
    if db:
        try:
            result = db.table("competitions").select("id", count="exact").execute()
            print(f"\nDB 연결: OK (competitions: {result.count}개)")
        except Exception as e:
            print(f"\nDB 연결: 오류 — {e}")
    else:
        print("\nDB 연결: 실패")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    commands = {
        "validate": cmd_validate,
        "health": cmd_health,
        "report": cmd_report,
        "status": cmd_status,
    }

    if command not in commands:
        print(f"알 수 없는 명령: {command}")
        print(f"사용 가능: {', '.join(commands.keys())}")
        sys.exit(1)

    asyncio.run(commands[command]())


if __name__ == "__main__":
    main()
