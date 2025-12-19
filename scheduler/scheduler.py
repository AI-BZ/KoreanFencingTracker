"""
자동 스크래핑 스케줄러
"""
import asyncio
from typing import Optional, Callable
from datetime import datetime, date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from scraper.config import scheduler_config, iksan_config


class FencingScheduler:
    """펜싱 데이터 스크래핑 스케줄러"""

    def __init__(self, scraper_func, active_update_func=None, iksan_update_func=None):
        """
        Args:
            scraper_func: 전체 동기화 함수 (async)
            active_update_func: 진행중 대회 업데이트 함수 (async, optional)
            iksan_update_func: 익산 국제대회 업데이트 함수 (async, optional)
        """
        self.scheduler = AsyncIOScheduler()
        self.scraper_func = scraper_func
        self.active_update_func = active_update_func
        self.iksan_update_func = iksan_update_func
        self._is_running = False
        self._iksan_running = False
        self._last_full_sync: Optional[datetime] = None
        self._last_incremental: Optional[datetime] = None
        self._last_iksan_update: Optional[datetime] = None

    def setup(self):
        """스케줄러 설정"""
        # 매일 오전 6시 전체 동기화
        self.scheduler.add_job(
            self._run_full_sync,
            CronTrigger(hour=scheduler_config.daily_sync_hour, minute=0),
            id="daily_full_sync",
            name="Daily Full Sync",
            replace_existing=True
        )
        logger.info(f"매일 {scheduler_config.daily_sync_hour}시 전체 동기화 스케줄 등록")

        # 매시간 진행중 대회 업데이트 (활성화된 경우)
        if scheduler_config.hourly_update_enabled and self.active_update_func:
            self.scheduler.add_job(
                self._run_incremental_update,
                IntervalTrigger(hours=1),
                id="hourly_active_update",
                name="Hourly Active Update",
                replace_existing=True
            )
            logger.info("매시간 진행중 대회 업데이트 스케줄 등록")

        # 익산 국제대회 업데이트 (대회 기간 중 활성 시간대만)
        if self.iksan_update_func:
            self.scheduler.add_job(
                self._run_iksan_update,
                IntervalTrigger(minutes=iksan_config.update_interval_minutes),
                id="iksan_international_update",
                name="Iksan International Update",
                replace_existing=True
            )
            logger.info(f"익산 국제대회 업데이트 스케줄 등록 ({iksan_config.update_interval_minutes}분 간격)")

    async def _run_full_sync(self):
        """전체 동기화 실행"""
        if self._is_running:
            logger.warning("이미 스크래핑이 진행 중입니다")
            return

        self._is_running = True
        logger.info("=== 전체 동기화 시작 ===")

        try:
            await self.scraper_func()
            self._last_full_sync = datetime.now()
            logger.info(f"전체 동기화 완료: {self._last_full_sync}")
        except Exception as e:
            logger.error(f"전체 동기화 오류: {e}")
        finally:
            self._is_running = False

    async def _run_incremental_update(self):
        """진행중 대회 업데이트 실행"""
        if self._is_running:
            logger.debug("스크래핑 진행 중, 증분 업데이트 스킵")
            return

        if not self.active_update_func:
            return

        self._is_running = True
        logger.info("--- 진행중 대회 업데이트 시작 ---")

        try:
            await self.active_update_func()
            self._last_incremental = datetime.now()
            logger.info(f"증분 업데이트 완료: {self._last_incremental}")
        except Exception as e:
            logger.error(f"증분 업데이트 오류: {e}")
        finally:
            self._is_running = False

    async def _run_iksan_update(self):
        """익산 국제대회 업데이트 실행 (스텔스 모드)"""
        # 다른 스크래핑 진행 중이면 스킵
        if self._is_running or self._iksan_running:
            logger.debug("다른 스크래핑 진행 중, 익산 업데이트 스킵")
            return

        if not self.iksan_update_func:
            return

        # 대회 기간 체크 (U17/U20: 12/16-21, U13: 12/20-21)
        today = date.today()
        u17_start = date.fromisoformat(iksan_config.u17_u20_start)
        u17_end = date.fromisoformat(iksan_config.u17_u20_end)
        u13_start = date.fromisoformat(iksan_config.u13_start)
        u13_end = date.fromisoformat(iksan_config.u13_end)

        # 대회 기간이 아니면 스킵
        in_u17_period = u17_start <= today <= u17_end
        in_u13_period = u13_start <= today <= u13_end

        if not (in_u17_period or in_u13_period):
            logger.debug(f"익산 대회 기간 아님 (오늘: {today})")
            return

        # 활성 시간대 체크 (08:00 ~ 20:00)
        now = datetime.now()
        if not (iksan_config.active_hours_start <= now.hour < iksan_config.active_hours_end):
            logger.debug(f"익산 대회 활성 시간대 아님 (현재: {now.hour}시)")
            return

        self._iksan_running = True
        comp_type = []
        if in_u17_period:
            comp_type.append("U17/U20")
        if in_u13_period:
            comp_type.append("U13/U11/U9")

        logger.info(f"🎯 익산 국제대회 업데이트 시작 ({', '.join(comp_type)})")

        try:
            await self.iksan_update_func()
            self._last_iksan_update = datetime.now()
            logger.info(f"✅ 익산 업데이트 완료: {self._last_iksan_update}")
        except Exception as e:
            logger.error(f"❌ 익산 업데이트 오류: {e}")
        finally:
            self._iksan_running = False

    def start(self):
        """스케줄러 시작"""
        self.setup()
        self.scheduler.start()
        logger.info("스케줄러 시작됨")

    def stop(self):
        """스케줄러 중지"""
        self.scheduler.shutdown()
        logger.info("스케줄러 중지됨")

    def get_status(self) -> dict:
        """스케줄러 상태 조회"""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None
            })

        # 익산 대회 기간 상태 확인
        today = date.today()
        u17_start = date.fromisoformat(iksan_config.u17_u20_start)
        u17_end = date.fromisoformat(iksan_config.u17_u20_end)
        u13_start = date.fromisoformat(iksan_config.u13_start)
        u13_end = date.fromisoformat(iksan_config.u13_end)

        iksan_status = {
            "u17_u20": {
                "active": u17_start <= today <= u17_end,
                "period": f"{iksan_config.u17_u20_start} ~ {iksan_config.u17_u20_end}",
            },
            "u13_u11_u9": {
                "active": u13_start <= today <= u13_end,
                "period": f"{iksan_config.u13_start} ~ {iksan_config.u13_end}",
            },
            "last_update": self._last_iksan_update.isoformat() if self._last_iksan_update else None,
        }

        return {
            "is_running": self._is_running,
            "iksan_running": self._iksan_running,
            "last_full_sync": self._last_full_sync.isoformat() if self._last_full_sync else None,
            "last_incremental": self._last_incremental.isoformat() if self._last_incremental else None,
            "iksan": iksan_status,
            "jobs": jobs
        }

    async def run_now(self, sync_type: str = "full"):
        """즉시 실행"""
        if sync_type == "full":
            await self._run_full_sync()
        elif sync_type == "incremental":
            await self._run_incremental_update()
        elif sync_type == "iksan":
            await self._run_iksan_update()
        else:
            logger.warning(f"알 수 없는 동기화 타입: {sync_type}")
