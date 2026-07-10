"""
변경 감지 시스템 통합 테스트

테스트 항목:
1. EventFingerprint / CompetitionFingerprint 생성
2. 상태 해시 계산 및 비교
3. StateManager 변경 감지
4. ChangeDetector 지문 캡처 (실제 사이트)

실행:
    cd services/data
    python scripts/test_change_detection.py
"""
import asyncio
import sys

# 경로 설정
sys.path.insert(0, '/Users/gyejinpark/Documents/GitHub/FencingMind-data/services/data')

from loguru import logger
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")


def test_fingerprint_classes():
    """1. Fingerprint 클래스 테스트"""
    print("\n" + "=" * 60)
    print("1. Fingerprint 클래스 테스트")
    print("=" * 60)

    from scheduler.change_detection import EventFingerprint, CompetitionFingerprint

    # EventFingerprint 생성
    event1 = EventFingerprint(
        sub_event_cd="COMPS001",
        event_name="남자 플뢰레(개인)",
        pool_groups=4,
        pool_rows=32,
        pool_vd_count=120,
        de_completed=8,
        de_cells=64,
        final_ranking_rows=0
    )

    print(f"  ✓ EventFingerprint 생성: {event1.event_name}")
    print(f"    - 상태 해시: {event1.state_hash}")
    print(f"    - 유효: {event1.is_valid}")
    print(f"    - 진행 상태: {event1.event_status}")
    print(f"    - Pool 데이터: {event1.has_pool_data}")
    print(f"    - DE 데이터: {event1.has_de_data}")

    # 변경된 EventFingerprint
    event2 = EventFingerprint(
        sub_event_cd="COMPS001",
        event_name="남자 플뢰레(개인)",
        pool_groups=4,
        pool_rows=32,
        pool_vd_count=150,  # 변경됨
        de_completed=15,     # 변경됨
        de_cells=64,
        final_ranking_rows=0
    )

    print("\n  ✓ 변경된 EventFingerprint:")
    print(f"    - 이전 해시: {event1.state_hash}")
    print(f"    - 새 해시: {event2.state_hash}")
    print(f"    - 변경 여부: {event2.has_changed(event1)}")

    # 차이 계산
    diff = event2.diff(event1)
    print(f"    - 차이: {diff}")

    # CompetitionFingerprint 생성
    comp_fp = CompetitionFingerprint(
        comp_cd="COMPM00679",
        comp_name="2025 테스트 대회"
    )
    comp_fp.events["COMPS001"] = event1
    comp_fp.events["COMPS002"] = EventFingerprint(
        sub_event_cd="COMPS002",
        event_name="여자 사브르(개인)",
        pool_vd_count=80
    )

    print(f"\n  ✓ CompetitionFingerprint 생성: {comp_fp.comp_name}")
    print(f"    - 종목 수: {comp_fp.event_count}")
    print(f"    - 통합 해시: {comp_fp.combined_hash}")

    return True


def test_state_manager():
    """2. StateManager 테스트"""
    print("\n" + "=" * 60)
    print("2. StateManager 테스트")
    print("=" * 60)

    from scheduler.change_detection import StateManager, EventFingerprint, CompetitionFingerprint

    manager = StateManager(use_db=False)

    # 첫 번째 지문 저장 (새 대회)
    fp1 = CompetitionFingerprint(comp_cd="COMPM001", comp_name="테스트대회1")
    fp1.events["EV001"] = EventFingerprint(
        sub_event_cd="EV001",
        event_name="남자 에페",
        pool_vd_count=100,
        de_completed=0
    )
    fp1.events["EV002"] = EventFingerprint(
        sub_event_cd="EV002",
        event_name="여자 에페",
        pool_vd_count=80,
        de_completed=0
    )

    changes1 = manager.compare_and_update(fp1)
    print("  ✓ 첫 번째 지문 저장 (새 대회)")
    print(f"    - 변경 기록 수: {len(changes1)}")
    print(f"    - 변경 유형: {[c.change_type for c in changes1]}")

    # 두 번째 지문 (일부 종목 변경)
    fp2 = CompetitionFingerprint(comp_cd="COMPM001", comp_name="테스트대회1")
    fp2.events["EV001"] = EventFingerprint(
        sub_event_cd="EV001",
        event_name="남자 에페",
        pool_vd_count=120,  # Pool 진행
        de_completed=0
    )
    fp2.events["EV002"] = EventFingerprint(
        sub_event_cd="EV002",
        event_name="여자 에페",
        pool_vd_count=80,   # 변경 없음
        de_completed=5      # DE 시작
    )

    changes2 = manager.compare_and_update(fp2)
    print("\n  ✓ 두 번째 지문 (일부 변경)")
    print(f"    - 변경 기록 수: {len(changes2)}")
    for change in changes2:
        print(f"      - {change.event_name}: {change.change_type}")

    # 통계 확인
    stats = manager.get_statistics()
    print("\n  ✓ StateManager 통계:")
    print(f"    - 추적 중인 대회: {stats['competitions_tracked']}")
    print(f"    - 총 변경 감지: {stats['total_changes_detected']}")
    print(f"    - 변경 유형별: {stats['changes_by_type']}")

    return True


async def test_detector_dry_run():
    """3. ChangeDetector 테스트 (실제 사이트 접근)"""
    print("\n" + "=" * 60)
    print("3. ChangeDetector 테스트 (실제 사이트)")
    print("=" * 60)

    from scheduler.change_detection import ChangeDetector
    from scheduler.change_detection.detector import DetectionConfig

    # 단축된 타임아웃 설정
    config = DetectionConfig(
        page_timeout_ms=20000,
        search_wait_ms=2000,
        max_retries=1
    )

    # 테스트용 대회 코드 (실제 존재하는 대회)
    # 주의: 대회 목록에서 현재 유효한 대회 코드를 사용해야 함
    test_comp_cd = "COMPM00714"  # 실제 대회 코드로 변경 필요

    print(f"  - 테스트 대회 코드: {test_comp_cd}")
    print("  - 이 테스트는 실제 협회 사이트에 접근합니다.")
    print("  - 진행하시겠습니까? (y/n): ", end="")

    # 자동 테스트 모드에서는 스킵
    try:
        import select
        # 5초 타임아웃으로 입력 대기
        if select.select([sys.stdin], [], [], 5)[0]:
            response = sys.stdin.readline().strip()
        else:
            response = 'n'
            print("n (타임아웃)")
    except:
        response = 'n'
        print("n (자동 스킵)")

    if response.lower() != 'y':
        print("  → 실제 사이트 테스트 스킵")
        return True

    print("\n  🔍 실제 사이트에서 지문 캡처 시작...")

    try:
        async with ChangeDetector(config) as detector:
            fingerprint = await detector.capture_competition_fingerprint(
                test_comp_cd, "테스트 대회"
            )

            if fingerprint.error:
                print(f"  ❌ 지문 캡처 실패: {fingerprint.error}")
                return False

            print("\n  ✓ 지문 캡처 성공:")
            print(f"    - 종목 수: {fingerprint.event_count}")
            print(f"    - 유효 종목: {fingerprint.valid_event_count}")
            print(f"    - 소요 시간: {fingerprint.detection_duration_ms}ms")
            print(f"    - 통합 해시: {fingerprint.combined_hash}")

            print("\n  ✓ 종목별 상태:")
            for sub_cd, event_fp in fingerprint.events.items():
                print(f"    - {event_fp.event_name}")
                print(f"      Pool V/D: {event_fp.pool_vd_count}")
                print(f"      DE 완료: {event_fp.de_completed}")
                print(f"      순위: {event_fp.final_ranking_rows}")
                print(f"      상태: {event_fp.event_status}")
                print(f"      해시: {event_fp.state_hash}")

            return True

    except Exception as e:
        print(f"  ❌ 테스트 오류: {e}")
        return False


def test_scheduler_integration():
    """4. 스케줄러 통합 테스트"""
    print("\n" + "=" * 60)
    print("4. 스케줄러 통합 테스트")
    print("=" * 60)

    try:
        from scheduler.scheduler import FencingScheduler

        scheduler = FencingScheduler()

        print("  ✓ FencingScheduler 인스턴스 생성 성공")
        print(f"    - 변경 감지 활성화: {scheduler._change_detection_enabled}")
        print(f"    - StateManager 초기화: {scheduler._state_manager is not None}")

        # 상태 조회 (스케줄러 시작 전)
        status = scheduler.get_status()
        print("\n  ✓ 스케줄러 상태:")
        print(f"    - 실행 중: {status['is_running']}")
        print(f"    - 변경 감지 실행 중: {status['change_detection_running']}")
        print("    - 스케줄:")
        for key, value in status['schedule'].items():
            print(f"      - {key}: {value}")

        return True

    except Exception as e:
        print(f"  ❌ 스케줄러 통합 테스트 오류: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """메인 테스트 실행"""
    print("\n" + "🔥" * 30)
    print("변경 감지 시스템 통합 테스트")
    print("🔥" * 30)

    results = []

    # 1. Fingerprint 클래스 테스트
    try:
        results.append(("Fingerprint 클래스", test_fingerprint_classes()))
    except Exception as e:
        print(f"❌ 오류: {e}")
        results.append(("Fingerprint 클래스", False))

    # 2. StateManager 테스트
    try:
        results.append(("StateManager", test_state_manager()))
    except Exception as e:
        print(f"❌ 오류: {e}")
        results.append(("StateManager", False))

    # 3. ChangeDetector 테스트 (선택적)
    try:
        results.append(("ChangeDetector", await test_detector_dry_run()))
    except Exception as e:
        print(f"❌ 오류: {e}")
        results.append(("ChangeDetector", False))

    # 4. 스케줄러 통합 테스트
    try:
        results.append(("스케줄러 통합", test_scheduler_integration()))
    except Exception as e:
        print(f"❌ 오류: {e}")
        results.append(("스케줄러 통합", False))

    # 결과 요약
    print("\n" + "=" * 60)
    print("테스트 결과 요약")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} - {name}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 모든 테스트 통과!")
    else:
        print("⚠️ 일부 테스트 실패")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    asyncio.run(main())
