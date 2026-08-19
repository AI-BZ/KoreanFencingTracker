"""
account 서비스 백그라운드 스케줄러.

현재 등록된 잡: 탈퇴 회원 개인정보 파기 (deletion.service.purge_due_members)

구현 선택 (APScheduler 를 쓰지 않은 이유):
    services/data/scheduler/scheduler.py 는 APScheduler 를 쓴다. 확인 결과
    apscheduler 는 운영 인터프리터(Python.framework 3.13)에는 설치돼 있지만
    homebrew python3(3.14)에는 없고, requirements.txt 에도 선언돼 있지 않다.
    즉 apscheduler 에 의존하면 account 서버의 기동 가능 여부가 어떤
    인터프리터로 띄웠는지에 좌우된다. 파기 잡은 법적 의무 이행 경로이므로
    임포트 실패로 서버가 죽는 위험을 만들지 않기 위해 의존성 없는 asyncio
    태스크로 구현한다. 나중에 requirements.txt 에 apscheduler 를 추가하면
    _loop 만 AsyncIOScheduler + IntervalTrigger 로 교체하면 된다
    (_run_once 는 그대로 재사용).

supabase-py 클라이언트는 동기 블로킹이므로 asyncio.to_thread 로 감싼다.
"""
from __future__ import annotations

import asyncio

from loguru import logger

from .service import purge_due_members

_task: asyncio.Task | None = None


def _run_once(*, limit: int, dry_run: bool):
    """스레드에서 실행되는 동기 파기 1회분."""
    from shared_core.db.client import get_supabase_client

    return purge_due_members(
        get_supabase_client(),
        limit=limit,
        dry_run=dry_run,
        actor="scheduler",
    )


async def _loop(*, interval_seconds: int, limit: int, dry_run: bool) -> None:
    # 기동 직후 즉시 돌지 않는다: 배포 롤백 여유를 남긴다.
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await asyncio.to_thread(_run_once, limit=limit, dry_run=dry_run)
        except asyncio.CancelledError:
            logger.info("[scheduler] 탈퇴 파기 잡 중단됨")
            raise
        except Exception as exc:  # noqa: BLE001 - 잡 실패로 루프가 죽으면 안 된다
            logger.error(f"[scheduler] 탈퇴 파기 잡 실패: {exc}")


def start(*, interval_minutes: int, limit: int, dry_run: bool) -> None:
    """스케줄러 기동. 이미 떠 있으면 무시한다."""
    global _task
    if _task is not None and not _task.done():
        logger.warning("[scheduler] 이미 실행 중 - 중복 기동 무시")
        return

    interval_seconds = max(60, interval_minutes * 60)
    _task = asyncio.create_task(
        _loop(interval_seconds=interval_seconds, limit=limit, dry_run=dry_run),
        name="account-deletion-purge",
    )
    mode = "DRY-RUN(기록만)" if dry_run else "EXECUTE(실제 파기)"
    logger.info(
        f"[scheduler] 탈퇴 파기 잡 시작 - {interval_minutes}분 간격, "
        f"배치 최대 {limit}건, 모드 {mode}"
    )


async def stop() -> None:
    """스케줄러 정지 (lifespan 종료 시)."""
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[scheduler] 종료 중 예외: {exc}")
    finally:
        _task = None
