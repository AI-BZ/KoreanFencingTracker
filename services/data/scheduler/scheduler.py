"""
스마트 스크래핑 스케줄러

이벤트 기반 스크래핑 시스템:
1. 대회 공고 감지 (매일) - 새 대회 발견 시 DB 등록
2. 이벤트 기반 스크래핑:
   - 대회 1주일 전: 준비 스크래핑 (참가자 명단)
   - 대회 당일: 스텔스 모드 스크래핑 (30분 간격, 사람처럼)
   - 대회 종료 후: 최종 결과 스크래핑
3. 변경 감지 기반 스크래핑 (5분 간격):
   - 협회 사이트의 경량 지문(fingerprint)을 캡처
   - 변경된 종목만 선택적으로 스크래핑
   - ~33분 지연 → ~6분 지연으로 개선
"""
import asyncio
import os
import signal
import random
from typing import Optional, Dict, Any
from datetime import datetime, date, time, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from scraper.config import scheduler_config, stealth_config

# 변경 감지 시스템
from scheduler.change_detection import ChangeDetector, StateManager


class FencingScheduler:
    """
    스마트 펜싱 데이터 스케줄러

    스케줄:
    - 대회 공고 감지: 매일 09:00
    - Pool 대진표: 30분 간격 (D-1/D-day 대회만, 중복 방지)
    - 🔥 변경 감지 스크래핑: 5분 간격 (대회 진행 중, 변경된 종목만)
    - 스텔스 스크래핑: 30분 간격 (대회 진행 중, 백업)
    - 최종 결과 수집: 매일 06:00 (어제 종료된 대회)
    - 🛡️ Data Guardian 건강 점검: 매일 22:00
    - 📊 Data Guardian 주간 리포트: 매주 월요일 08:00
    """

    def __init__(self):
        """스케줄러 초기화"""
        self.scheduler = AsyncIOScheduler()
        self._is_running = False
        self._change_detection_running = False  # 변경 감지 전용 락

        # 상태 추적
        self._last_detection: Optional[datetime] = None
        self._last_event_scrape: Optional[datetime] = None
        self._last_change_detection: Optional[datetime] = None
        self._last_stats: Dict[str, Any] = {}
        self._detected_competitions: list = []

        # 변경 감지 시스템
        self._state_manager = StateManager(use_db=False)  # 메모리 기반 (빠른 비교)
        self._change_detection_enabled = True

    def setup(self):
        """스케줄러 설정"""
        # 1. 대회 공고 감지 - 매일 09:00
        self.scheduler.add_job(
            self._run_competition_detection,
            CronTrigger(hour=9, minute=0),
            id="daily_competition_detection",
            name="Daily Competition Detection",
            replace_existing=True
        )
        logger.info("📅 매일 09:00 대회 공고 감지 스케줄 등록")

        # 2. Pool 대진표 사전 스크래핑 - 30분 간격 (매시 0분, 30분)
        #    D-1 또는 D-day 대회가 있을 때만 실제 스크래핑
        #    이미 풀 데이터가 있으면 스킵 (중복 방지)
        self.scheduler.add_job(
            self._run_pre_competition_scraping,
            CronTrigger(minute="0,30"),
            id="pre_competition_check",
            name="Pre-Competition Pool Check (30min)",
            replace_existing=True
        )
        logger.info("📋 30분 간격 대진표 사전 스크래핑 스케줄 등록 (중복 방지 포함)")

        # 3. 🔥 변경 감지 기반 스크래핑 - 5분 간격 (핵심 기능)
        #    협회 사이트 상태 지문 캡처 → 변경된 종목만 선택적 스크래핑
        self.scheduler.add_job(
            self._run_change_detection_scraping,
            IntervalTrigger(minutes=5),
            id="change_detection_scraping",
            name="🔥 Change Detection Scraping (5min)",
            replace_existing=True
        )
        logger.info("🔥 5분 간격 변경 감지 스크래핑 등록 (메인)")

        # 4. 스텔스 스크래핑 - 매시 정각과 30분 (백업)
        #    변경 감지 실패 시 백업으로 전체 스크래핑
        self.scheduler.add_job(
            self._run_event_based_scraping,
            CronTrigger(minute="0,30"),  # 매시 0분, 30분에 실행
            id="stealth_event_scraping",
            name="Stealth Event-Based Scraping (30min backup)",
            replace_existing=True
        )
        logger.info("🥷 매시 0분/30분 스텔스 스크래핑 등록 (백업)")

        # 5. 최종 결과 수집 - 매일 06:00
        #    (어제 종료된 대회의 최종 결과)
        self.scheduler.add_job(
            self._run_final_results_collection,
            CronTrigger(hour=6, minute=0),
            id="daily_final_results",
            name="Daily Final Results Collection",
            replace_existing=True
        )
        logger.info("🏁 매일 06:00 최종 결과 수집 스케줄 등록")

        # 6. 선수 데이터 자동 업데이트 - 매일 07:00
        #    (종료된 대회의 선수 team_name, team_history 업데이트)
        self.scheduler.add_job(
            self._run_player_data_updates,
            CronTrigger(hour=7, minute=30),
            id="daily_player_updates",
            name="Daily Player Data Updates",
            replace_existing=True
        )
        logger.info("👤 매일 07:30 선수 데이터 자동 업데이트 스케줄 등록")

        # 7. 예정 대회 종목/참가자 사전 수집 - 매일 10:00, 15:00
        #    D-7 ~ D-1 대회의 종목 목록 확인 + 참가자 명단 수집
        self.scheduler.add_job(
            self._run_upcoming_preparation,
            CronTrigger(hour="10,15", minute=0),
            id="upcoming_preparation",
            name="📋 Upcoming Competition Preparation",
            replace_existing=True
        )
        logger.info("📋 매일 10:00/15:00 예정 대회 종목/참가자 사전 수집 등록")

        # 8. 📡 미래 대회 모니터링 - 매일 11:00, 18:00
        #    모든 미래 대회(start_date > today)에 대해 경량 API로 종목+참가자 변경 감시
        #    D-7 이전 공백 해소 (기존 upcoming_preparation은 D-7만 커버)
        self.scheduler.add_job(
            self._run_future_competition_monitoring,
            CronTrigger(hour="11,18", minute=0),
            id="future_competition_monitoring",
            name="📡 Future Competition Monitoring",
            replace_existing=True
        )
        logger.info("📡 매일 11:00/18:00 미래 대회 모니터링 등록 (경량 API)")

        # 9. 🛡️ Data Guardian 건강 점검 - 매일 22:00
        self.scheduler.add_job(
            self._run_guardian_health_check,
            CronTrigger(hour=22, minute=0),
            id="guardian_daily_health",
            name="🛡️ Data Guardian Daily Health Check",
            replace_existing=True
        )
        logger.info("🛡️ 매일 22:00 Data Guardian 건강 점검 등록")

        # 10. 📊 Data Guardian 주간 리포트 - 매주 월요일 08:00
        self.scheduler.add_job(
            self._run_guardian_weekly_report,
            CronTrigger(day_of_week="mon", hour=8, minute=0),
            id="guardian_weekly_report",
            name="📊 Data Guardian Weekly Report",
            replace_existing=True
        )
        logger.info("📊 매주 월요일 08:00 Data Guardian 주간 리포트 등록")

        # 11. 🧹 좀비 Playwright 프로세스 정리 - 매시간
        self.scheduler.add_job(
            lambda: self._cleanup_zombie_playwright(),
            CronTrigger(minute=45),
            id="playwright_cleanup",
            name="🧹 Playwright Zombie Cleanup",
            replace_existing=True
        )
        logger.info("🧹 매시 45분 좀비 Playwright 프로세스 정리 등록")

    async def _run_competition_detection(self):
        """대회 공고 감지 실행"""
        if self._is_running:
            logger.warning("다른 작업 진행 중, 대회 감지 스킵")
            return

        self._is_running = True
        logger.info("=== 대회 공고 감지 시작 ===")

        try:
            from scheduler.competition_detector import CompetitionDetector

            detector = CompetitionDetector()
            result = await detector.run()

            self._last_detection = datetime.now()
            self._detected_competitions = result.get("competitions", [])

            if result.get("detected", 0) > 0:
                logger.info(f"🆕 {result['detected']}개 새 대회 발견!")
                for comp in self._detected_competitions:
                    logger.info(f"   - {comp['name']} ({comp['start_date']})")

                # 신규 대회 초기 수집 후 서버 캐시 새로고침
                if result.get("initial_events_created", 0) > 0:
                    await self._refresh_server_cache()
            else:
                logger.info("새 대회 없음")

        except ImportError as e:
            logger.error(f"대회 감지 모듈 import 오류: {e}")
        except Exception as e:
            logger.error(f"대회 감지 오류: {e}")
        finally:
            self._is_running = False

    async def _run_pre_competition_scraping(self):
        """대회 전 Pool 대진표 스크래핑 (30분 간격, 중복 방지)

        D-1 또는 D-day 대회가 있을 때만 실행.
        이미 풀 데이터가 DB에 있는 대회는 스킵.
        """
        if self._is_running:
            logger.debug("다른 작업 진행 중, 대진표 스크래핑 스킵")
            return

        try:
            from scheduler.competition_detector import EventBasedScraper

            scraper = EventBasedScraper()
            comps = await scraper.get_competitions_to_scrape()

            pre_comps = comps.get("pre_competition", [])
            if not pre_comps:
                logger.debug("📋 수집할 대진표 없음 (내일/오늘 시작 대회 없음)")
                return

            # 이미 풀 데이터가 있는 대회 제외
            comps_to_scrape = []
            for comp in pre_comps:
                if not await self._has_pool_data(comp, scraper):
                    comps_to_scrape.append(comp)
                else:
                    logger.debug(f"📋 풀 대진표 이미 수집됨: {comp.get('comp_name', 'Unknown')}")

            if not comps_to_scrape:
                logger.debug("📋 모든 대회 풀 대진표 이미 수집됨")
                return

            # 실제 스크래핑 실행
            self._is_running = True
            logger.info(f"=== Pool 대진표 사전 스크래핑 시작: {len(comps_to_scrape)}개 대회 ===")

            result = await scraper.scrape_pre_competition(comps_to_scrape)
            self._last_stats["pre_competition"] = result
            logger.info(f"✅ 대진표 스크래핑 완료: {result.get('total_events', 0)}개 종목")

            # 성공 시 서버 캐시 새로고침
            if result.get("total_events", 0) > 0:
                await scraper._refresh_server_cache()

        except ImportError as e:
            logger.error(f"스크래퍼 import 오류: {e}")
        except Exception as e:
            logger.error(f"대진표 스크래핑 오류: {e}")
        finally:
            self._is_running = False

    async def _has_pool_data(self, comp: dict, scraper) -> bool:
        """대회의 풀 대진표가 이미 DB에 있는지 확인

        Args:
            comp: 대회 정보 (id 또는 comp_idx 포함)
            scraper: EventBasedScraper 인스턴스 (DB 접근용)

        Returns:
            True if pool_rounds data exists for any event in this competition
        """
        try:
            db = scraper.db
            if not db:
                return False

            comp_id = comp.get("id")
            if not comp_id:
                return False

            # 해당 대회의 이벤트 중 pool_rounds가 있는지 확인
            events = db.table("events").select(
                "id, raw_data"
            ).eq(
                "competition_id", comp_id
            ).execute()

            if not events.data:
                return False

            for event in events.data:
                raw_data = event.get("raw_data") or {}
                pool_rounds = raw_data.get("pool_rounds")
                if pool_rounds and len(pool_rounds) > 0:
                    return True

            return False
        except Exception as e:
            logger.warning(f"풀 데이터 확인 오류: {e}")
            return False

    async def _run_change_detection_scraping(self):
        """
        🔥 변경 감지 기반 스크래핑 (5분 간격, 핵심 기능)

        작동 방식:
        1. 진행 중인 대회의 상태 지문(fingerprint)을 캡처
        2. 이전 지문과 비교하여 변경된 종목 감지
        3. 변경된 종목만 선택적으로 스크래핑

        이점:
        - 기존: ~33분 지연 (30분 스케줄 + 랜덤 딜레이 + 스크래핑 시간)
        - 개선: ~6분 지연 (5분 스케줄 + 경량 감지 + 선택적 스크래핑)
        """
        # 변경 감지 비활성화 상태면 스킵
        if not self._change_detection_enabled:
            return

        # 다른 변경 감지 작업 진행 중이면 스킵 (경쟁 방지)
        if self._change_detection_running:
            logger.debug("🔥 다른 변경 감지 진행 중, 스킵")
            return

        # 전체 스크래핑 진행 중이면 변경 감지 스킵
        if self._is_running:
            logger.debug("🔥 전체 스크래핑 진행 중, 변경 감지 스킵")
            return

        # 활성 시간대 체크 (08:00 ~ 21:00)
        current_hour = datetime.now().hour
        if not (stealth_config.active_hours_start <= current_hour < stealth_config.active_hours_end):
            logger.debug(f"🔥 비활성 시간대 ({current_hour}시), 변경 감지 스킵")
            return

        self._change_detection_running = True

        try:
            from scheduler.competition_detector import EventBasedScraper

            # 1. 진행 중인 대회 조회
            scraper = EventBasedScraper()
            comps = await scraper.get_competitions_to_scrape()
            ongoing_comps = comps.get("ongoing", [])

            if not ongoing_comps:
                logger.debug("🔥 진행 중인 대회 없음, 변경 감지 스킵")
                return

            logger.info(f"🔥 변경 감지: {len(ongoing_comps)}개 대회 체크 중...")

            # 2. 각 대회의 상태 지문 캡처 및 변경 감지
            total_changes = 0
            total_scraped_events = 0

            async with ChangeDetector() as detector:
                for comp in ongoing_comps:
                    comp_cd = comp.get("comp_idx")
                    comp_name = comp.get("comp_name", "Unknown")

                    if not comp_cd:
                        continue

                    try:
                        # 지문 캡처
                        fingerprint = await detector.capture_competition_fingerprint(
                            comp_cd, comp_name
                        )

                        if fingerprint.error:
                            logger.warning(f"🔥 지문 캡처 실패 ({comp_name}): {fingerprint.error}")
                            continue

                        # 변경된 종목 코드 조회
                        changed_events = self._state_manager.get_changed_event_codes(fingerprint)

                        if changed_events:
                            logger.info(
                                f"🔥 변경 감지: {comp_name} - {len(changed_events)}개 종목 변경"
                            )

                            # 변경 기록 저장 (통계/분석용)
                            changes = self._state_manager.compare_and_update(fingerprint)
                            total_changes += len(changes)

                            # 3. 변경된 종목만 선택적 스크래핑
                            scraped = await self._scrape_changed_events(
                                comp, changed_events, scraper
                            )
                            total_scraped_events += scraped

                        else:
                            # 변경 없음 - 지문 업데이트만
                            self._state_manager.save_fingerprint(fingerprint)
                            logger.debug(f"🔥 변경 없음: {comp_name}")

                    except Exception as e:
                        logger.error(f"🔥 대회 변경 감지 오류 ({comp_name}): {e}")
                        continue

            # 결과 기록
            self._last_change_detection = datetime.now()
            self._last_stats["change_detection"] = {
                "competitions_checked": len(ongoing_comps),
                "changes_detected": total_changes,
                "events_scraped": total_scraped_events,
                "checked_at": datetime.now().isoformat()
            }

            if total_changes > 0:
                logger.info(
                    f"🔥 변경 감지 완료: {total_changes}개 변경, "
                    f"{total_scraped_events}개 종목 스크래핑"
                )

                # 스크래핑 완료 후 서버 캐시 새로고침
                if total_scraped_events > 0:
                    await scraper._refresh_server_cache()

                    # 🛡️ 스크래핑 후 자동 검증 (변경 감지)
                    comp_names = ", ".join(
                        c.get("comp_name", "") for c in ongoing_comps[:3]
                    )
                    await self._run_guardian_post_scrape(
                        comp_name=f"변경감지: {comp_names}",
                        events_count=total_scraped_events,
                    )

        except ImportError as e:
            logger.error(f"🔥 변경 감지 모듈 import 오류: {e}")
        except Exception as e:
            logger.error(f"🔥 변경 감지 오류: {e}")
        finally:
            self._change_detection_running = False

    async def _scrape_changed_events(
        self,
        comp: Dict[str, Any],
        changed_events: list,
        scraper
    ) -> int:
        """
        변경된 종목만 선택적으로 스크래핑

        Args:
            comp: 대회 정보 (comp_idx, comp_name 등)
            changed_events: 변경된 종목 코드 목록
            scraper: EventBasedScraper 인스턴스

        Returns:
            스크래핑된 종목 수
        """
        if not changed_events:
            return 0

        comp_name = comp.get("comp_name", "Unknown")
        comp_idx = comp.get("comp_idx")

        logger.info(
            f"🎯 선택적 스크래핑: {comp_name} - "
            f"{len(changed_events)}개 종목 ({', '.join(changed_events[:3])}...)"
        )

        try:
            # EventBasedScraper에 선택적 스크래핑 메서드 사용
            result = await scraper.scrape_specific_events(
                comp, changed_events
            )

            return result.get("events_saved", 0)

        except AttributeError:
            # scrape_specific_events가 없으면 전체 스크래핑 (fallback)
            logger.warning(
                f"🎯 선택적 스크래핑 미지원, 전체 스크래핑으로 대체: {comp_name}"
            )
            result = await scraper._scrape_competition_direct(comp, scrape_type="full")
            return result.get("events_saved", 0)

        except Exception as e:
            logger.error(f"🎯 선택적 스크래핑 오류 ({comp_name}): {e}")
            return 0

    async def _run_event_based_scraping(self):
        """
        스텔스 모드 이벤트 기반 스크래핑 (30분 간격)

        사람처럼 행동:
        - 랜덤 시작 딜레이 (0~60초)
        - 활성 시간대에만 실행 (08:00 ~ 21:00)
        - 진행 중 대회만 스크래핑
        """
        if self._is_running:
            logger.debug("다른 작업 진행 중, 스텔스 스크래핑 스킵")
            return

        # 활성 시간대 체크
        current_hour = datetime.now().hour
        if not (stealth_config.active_hours_start <= current_hour < stealth_config.active_hours_end):
            logger.debug(f"비활성 시간대 ({current_hour}시), 스텔스 스크래핑 스킵")
            return

        self._is_running = True

        try:
            # 🥷 스텔스: 랜덤 시작 딜레이 (사람처럼 정확히 30분마다 안 함)
            startup_delay = random.uniform(0, 60)
            logger.info(f"🥷 스텔스 모드: {startup_delay:.0f}초 후 스크래핑 시작...")
            await asyncio.sleep(startup_delay)

            from scheduler.competition_detector import EventBasedScraper

            scraper = EventBasedScraper()
            comps = await scraper.get_competitions_to_scrape()

            # 진행 중인 대회가 있을 때만 실제 스크래핑
            ongoing_count = len(comps.get("ongoing", []))
            upcoming_count = len(comps.get("upcoming", []))

            if ongoing_count > 0:
                logger.info(f"🥷 스텔스 스크래핑: {ongoing_count}개 진행 중 대회")
                result = await scraper.scrape_ongoing_stealth(comps["ongoing"])
                self._last_event_scrape = datetime.now()
                self._last_stats["ongoing"] = result
            elif upcoming_count > 0:
                # 대회 시작 3일 이내면 준비 스크래핑
                for comp in comps["upcoming"]:
                    start_date = date.fromisoformat(comp["start_date"])
                    days_until = (start_date - date.today()).days
                    if days_until <= 3:
                        logger.info(f"📅 대회 {days_until}일 전: {comp['comp_name']}")
            else:
                logger.debug("스크래핑할 대회 없음")

        except ImportError as e:
            logger.error(f"이벤트 스크래퍼 import 오류: {e}")
        except Exception as e:
            logger.error(f"스텔스 스크래핑 오류: {e}")
        finally:
            self._is_running = False

    async def _run_final_results_collection(self):
        """최종 결과 수집 실행 (어제 종료된 대회)"""
        if self._is_running:
            logger.warning("다른 작업 진행 중, 최종 결과 수집 스킵")
            return

        self._is_running = True
        logger.info("=== 최종 결과 수집 시작 ===")

        try:
            from scheduler.competition_detector import EventBasedScraper

            scraper = EventBasedScraper()
            comps = await scraper.get_competitions_to_scrape()

            just_ended = comps.get("just_ended", [])
            if just_ended:
                logger.info(f"🏁 {len(just_ended)}개 종료 대회 최종 결과 수집")
                result = await scraper.scrape_just_ended(just_ended)
                self._last_stats["just_ended"] = result

                # 🛡️ 스크래핑 후 자동 검증
                for comp in just_ended:
                    await self._run_guardian_post_scrape(
                        comp_name=comp.get("comp_name", ""),
                        events_count=result.get("events_saved", 0),
                    )
            else:
                logger.debug("어제 종료된 대회 없음")

        except ImportError as e:
            logger.error(f"스크래퍼 import 오류: {e}")
        except Exception as e:
            logger.error(f"최종 결과 수집 오류: {e}")
        finally:
            self._is_running = False

    async def _run_player_data_updates(self):
        """
        선수 데이터 자동 업데이트 (종료된 대회 기반)

        실행 내용:
        1. 종료된 대회 중 아직 처리되지 않은 대회 감지
        2. 대회 데이터 무결성 검증
        3. 선수 team_name을 최신 대회 소속으로 업데이트
        4. 선수 team_history 날짜 기간 업데이트
        5. 모든 변경 사항 감사 로그 기록
        6. 서버 캐시 및 identity_resolver 새로고침 (자동)
        """
        if self._is_running:
            logger.warning("다른 작업 진행 중, 선수 데이터 업데이트 스킵")
            return

        self._is_running = True
        logger.info("=== 선수 데이터 자동 업데이트 시작 ===")

        try:
            from scheduler.player_data_updater import PlayerDataPipeline

            # 실제 실행 (dry_run=False)
            pipeline = PlayerDataPipeline(dry_run=False)
            result = pipeline.run(
                days_lookback=7,  # 7일 이내 종료된 대회만
                limit=10,  # 한 번에 10개 대회까지
                triggered_by='scheduler'
            )

            # 결과 저장
            self._last_stats["player_updates"] = result

            if result.get("competitions_processed", 0) > 0:
                logger.info(
                    f"👤 선수 업데이트 완료: "
                    f"{result.get('competitions_processed', 0)}개 대회, "
                    f"{result.get('total_players_updated', 0)}명 팀 변경, "
                    f"{result.get('total_histories_updated', 0)}건 이력 업데이트"
                )

                # 6. 서버 캐시 및 identity_resolver 자동 새로고침
                await self._refresh_server_cache()
            else:
                logger.debug("👤 업데이트할 대회 없음")

        except ImportError as e:
            logger.error(f"선수 업데이트 모듈 import 오류: {e}")
        except Exception as e:
            logger.error(f"선수 데이터 업데이트 오류: {e}")
        finally:
            self._is_running = False

    async def _run_upcoming_preparation(self):
        """
        예정 대회 종목/참가자 사전 수집 (D-7 ~ D-1)

        1. 7일 이내 시작 대회 중 이벤트가 없는 대회 → 종목 목록 스크래핑
        2. 이벤트가 있는 대회 중 참가자 미수집 종목 → 참가자 명단 수집
        """
        if self._is_running:
            logger.debug("다른 작업 진행 중, 예정 대회 준비 스킵")
            return

        self._is_running = True
        logger.info("=== 📋 예정 대회 종목/참가자 사전 수집 시작 ===")

        try:
            from scheduler.competition_detector import EventBasedScraper

            scraper = EventBasedScraper()
            comps = await scraper.get_competitions_to_scrape()
            upcoming = comps.get("upcoming", [])

            if not upcoming:
                logger.debug("📋 7일 이내 시작 대회 없음")
                return

            total_events_created = 0
            total_participants_fetched = 0

            for comp in upcoming:
                comp_name = comp.get("comp_name", "Unknown")
                comp_idx = comp.get("comp_idx")
                comp_id = comp.get("id")

                if not comp_idx or not comp_id:
                    continue

                logger.info(f"📋 예정 대회 준비: {comp_name} (시작: {comp.get('start_date')})")

                # 1단계: 이벤트가 없으면 종목 목록 스크래핑으로 생성
                events = scraper.db.table("events").select("id, event_name, sub_event_cd, raw_data").eq(
                    "competition_id", comp_id
                ).execute()

                if not events.data:
                    logger.info(f"  📋 종목 없음 → 종목 목록 스크래핑 (경량)")
                    result = await scraper._scrape_competition_direct(comp, scrape_type="events_only")
                    events_created = result.get("events_saved", 0)
                    total_events_created += events_created
                    logger.info(f"  ✅ {events_created}개 종목 생성")

                # 2단계: 참가자 미수집 종목에 대해 참가자 수집
                await scraper._fetch_participants(comp)
                total_participants_fetched += 1

            self._last_stats["upcoming_preparation"] = {
                "competitions_checked": len(upcoming),
                "events_created": total_events_created,
                "checked_at": datetime.now().isoformat(),
            }

            if total_events_created > 0:
                logger.info(f"📋 예정 대회 준비 완료: {total_events_created}개 종목 생성")
                await self._refresh_server_cache()
            else:
                logger.info("📋 예정 대회 준비 완료 (새 종목 없음)")

        except ImportError as e:
            logger.error(f"예정 대회 준비 import 오류: {e}")
        except Exception as e:
            logger.error(f"예정 대회 준비 오류: {e}")
        finally:
            self._is_running = False

    async def _run_future_competition_monitoring(self):
        """
        📡 미래 대회 모니터링 (매일 11:00, 18:00)

        모든 미래 대회(start_date > today)에 대해 경량 HTTP API로:
        - 종목 없는 대회 → 종목 목록 수집
        - 종목 있는 대회 → 참가자 변경 감지 및 업데이트

        기존 upcoming_preparation(D-7)과 달리:
        - 감지 직후 ~ 대회 시작까지 전 기간 커버
        - Playwright 없이 HTTP API만 사용 (경량)
        """
        if self._is_running:
            logger.debug("다른 작업 진행 중, 미래 대회 모니터링 스킵")
            return

        self._is_running = True
        logger.info("=== 📡 미래 대회 모니터링 시작 ===")

        try:
            from scheduler.competition_detector import EventBasedScraper

            scraper = EventBasedScraper()
            result = await scraper.monitor_future_competitions()

            self._last_stats["future_monitoring"] = result

            # 변경 발생 시 서버 캐시 새로고침
            events_created = result.get("events_created", 0)
            participants_updated = result.get("participants_updated", 0)

            if events_created > 0 or participants_updated > 0:
                await self._refresh_server_cache()

        except ImportError as e:
            logger.error(f"📡 모니터링 모듈 import 오류: {e}")
        except Exception as e:
            logger.error(f"📡 미래 대회 모니터링 오류: {e}")
        finally:
            self._is_running = False

    # ==================== Data Guardian 연동 ====================

    async def _run_guardian_health_check(self):
        """🛡️ Data Guardian 건강 점검 (매일 22:00)"""
        logger.info("=== 🛡️ Data Guardian 건강 점검 시작 ===")
        try:
            from app.data_guardian import get_guardian
            guardian = get_guardian()
            result = await guardian.daily_health_check()
            health = result.get("health_status", "unknown")
            logger.info(f"🛡️ 건강 점검 완료: {health}")
            self._last_stats["guardian_health"] = result
        except ImportError as e:
            logger.error(f"🛡️ Data Guardian import 오류: {e}")
        except Exception as e:
            logger.error(f"🛡️ 건강 점검 오류: {e}")

    async def _run_guardian_weekly_report(self):
        """📊 Data Guardian 주간 리포트 (매주 월요일 08:00)"""
        logger.info("=== 📊 Data Guardian 주간 리포트 시작 ===")
        try:
            from app.data_guardian import get_guardian
            guardian = get_guardian()
            result = await guardian.weekly_report()
            logger.info(
                f"📊 주간 리포트 완료: "
                f"검증 {result.get('validation_runs', 0)}회, "
                f"ERROR {result.get('total_errors', 0)}건"
            )
            self._last_stats["guardian_weekly"] = result
        except ImportError as e:
            logger.error(f"📊 Data Guardian import 오류: {e}")
        except Exception as e:
            logger.error(f"📊 주간 리포트 오류: {e}")

    async def _run_guardian_post_scrape(self, comp_name: str = "", events_count: int = 0):
        """🛡️ 스크래핑 후 자동 검증 (post-scrape hook)"""
        try:
            from app.data_guardian import get_guardian
            guardian = get_guardian()
            result = await guardian.post_scrape_validation(
                comp_name=comp_name,
                events_count=events_count,
            )
            errors = result.get("errors", 0)
            if errors > 0:
                logger.warning(f"🛡️ 스크래핑 후 검증: {comp_name} — ERROR {errors}건")
            else:
                logger.info(f"🛡️ 스크래핑 후 검증: {comp_name} — 이상 없음")
        except ImportError:
            pass  # guardian 미설치 시 무시
        except Exception as e:
            logger.debug(f"🛡️ post-scrape 검증 오류 (무시): {e}")

    async def _refresh_server_cache(self):
        """서버 캐시 및 identity_resolver 새로고침"""
        try:
            import httpx

            # 서버 포트 자동 감지 (환경변수 또는 기본값)
            import os
            server_port = os.getenv("SERVER_PORT", "9071")
            logger.info("🔄 서버 캐시 새로고침 요청...")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"http://localhost:{server_port}/api/refresh-data",
                    headers={"X-Internal-Token": os.getenv("INTERNAL_API_TOKEN", "")},
                    timeout=60.0
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        logger.info(f"✅ 서버 캐시 새로고침 완료: {result.get('profiles', 0)}개 프로필")
                    else:
                        logger.warning(f"서버 캐시 새로고침 실패: {result.get('message', 'Unknown error')}")
                else:
                    logger.warning(f"서버 캐시 새로고침 HTTP 오류: {response.status_code}")
        except Exception as e:
            logger.error(f"서버 캐시 새로고침 오류: {e}")

    @staticmethod
    def _cleanup_zombie_playwright():
        """좀비 Playwright 프로세스 정리 (파일 디스크립터 누수 방지)"""
        import subprocess
        try:
            result = subprocess.run(
                ["pgrep", "-f", "playwright/driver/node"],
                capture_output=True, text=True
            )
            pids = [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
            if len(pids) > 10:
                logger.warning(f"🧹 좀비 Playwright 프로세스 {len(pids)}개 감지, 정리 중...")
                subprocess.run(["pkill", "-f", "playwright/driver/node"],
                              capture_output=True)
                logger.info("🧹 좀비 Playwright 프로세스 정리 완료")
        except Exception as e:
            logger.debug(f"Playwright 정리 스킵: {e}")

    def start(self):
        """스케줄러 시작"""
        self._cleanup_zombie_playwright()
        self.setup()
        self.scheduler.start()
        logger.info("🚀 스마트 스케줄러 시작됨")
        logger.info("   - 최종 결과: 매일 06:00")
        logger.info("   - 👤 선수 데이터 업데이트: 매일 07:30")
        logger.info("   - 대회 감지: 매일 09:00 (→ 신규 대회 즉시 종목+참가자 수집)")
        logger.info("   - 📋 예정 대회 준비: 매일 10:00/15:00 (D-7, Playwright)")
        logger.info("   - 📡 미래 대회 모니터링: 매일 11:00/18:00 (전체, 경량 API)")
        logger.info("   - Pool 대진표: 30분 간격 (D-1/D-day 대회만, 중복 방지)")
        logger.info(f"   - 🔥 변경 감지 스크래핑: 5분 간격 (메인) "
                   f"({stealth_config.active_hours_start}:00~{stealth_config.active_hours_end}:00)")
        logger.info(f"   - 🥷 스텔스 스크래핑: 30분 간격 (백업)")
        logger.info("   - 🛡️ Data Guardian 건강 점검: 매일 22:00")
        logger.info("   - 📊 Data Guardian 주간 리포트: 매주 월요일 08:00")

    def stop(self):
        """스케줄러 중지"""
        self.scheduler.shutdown()
        logger.info("🛑 스케줄러 중지됨")

    def get_status(self) -> dict:
        """스케줄러 상태 조회"""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None
            })

        # 변경 감지 시스템 통계
        change_detection_stats = self._state_manager.get_statistics()

        return {
            "is_running": self._is_running,
            "change_detection_running": self._change_detection_running,
            "change_detection_enabled": self._change_detection_enabled,
            "last_detection": self._last_detection.isoformat() if self._last_detection else None,
            "last_event_scrape": self._last_event_scrape.isoformat() if self._last_event_scrape else None,
            "last_change_detection": self._last_change_detection.isoformat() if self._last_change_detection else None,
            "detected_competitions": self._detected_competitions,
            "last_stats": self._last_stats,
            "change_detection_stats": change_detection_stats,
            "jobs": jobs,
            "schedule": {
                "final_results": "매일 06:00",
                "player_updates": "👤 매일 07:30 (선수 데이터 자동 업데이트)",
                "detection": "매일 09:00 (→ 신규 대회 즉시 종목+참가자 수집)",
                "upcoming_preparation": "📋 매일 10:00/15:00 (D-7 예정 대회, Playwright)",
                "future_monitoring": "📡 매일 11:00/18:00 (모든 미래 대회, 경량 API)",
                "pre_competition": "30분 간격 (D-1/D-day 대회만, 중복 방지)",
                "change_detection": f"🔥 5분 간격 (메인) "
                                   f"({stealth_config.active_hours_start}:00~{stealth_config.active_hours_end}:00)",
                "stealth_scraping": f"🥷 30분 간격 (백업)",
                "guardian_health": "🛡️ 매일 22:00 (Data Guardian 건강 점검)",
                "guardian_weekly": "📊 매주 월요일 08:00 (Data Guardian 주간 리포트)",
            }
        }

    async def run_now(self, task_type: str = "detect") -> Dict[str, Any]:
        """즉시 실행

        Args:
            task_type:
                - "detect": 대회 공고 감지 (→ 신규 대회 즉시 종목+참가자 수집)
                - "pre": Pool 대진표 사전 스크래핑
                - "change": 🔥 변경 감지 기반 스크래핑 (권장)
                - "scrape": 스텔스 스크래핑 (백업)
                - "final": 최종 결과 수집
                - "players": 👤 선수 데이터 자동 업데이트
                - "upcoming": 📋 예정 대회 종목/참가자 사전 수집 (D-7)
                - "monitor": 📡 미래 대회 모니터링 (전체, 경량 API)
                - "validate": 🛡️ Data Guardian 데이터 검증
                - "health": 🛡️ Data Guardian 건강 점검
                - "report": 📊 Data Guardian 주간 리포트
                - "all": 전체 실행

        Returns:
            실행 결과
        """
        results = {}

        if task_type in ["detect", "all"]:
            await self._run_competition_detection()
            results["detection"] = {
                "completed": True,
                "detected": len(self._detected_competitions)
            }

        if task_type in ["pre", "all"]:
            await self._run_pre_competition_scraping()
            results["pre_competition"] = {
                "completed": True,
                "stats": self._last_stats.get("pre_competition", {})
            }

        if task_type in ["change", "all"]:
            # 🔥 변경 감지 기반 스크래핑 (권장)
            await self._run_change_detection_scraping()
            results["change_detection"] = {
                "completed": True,
                "stats": self._last_stats.get("change_detection", {})
            }

        if task_type in ["scrape", "all"]:
            await self._run_event_based_scraping()
            results["scraping"] = {
                "completed": True,
                "stats": self._last_stats.get("ongoing", {})
            }

        if task_type in ["final", "all"]:
            await self._run_final_results_collection()
            results["final"] = {
                "completed": True,
                "stats": self._last_stats.get("just_ended", {})
            }

        if task_type in ["players", "all"]:
            # 👤 선수 데이터 자동 업데이트
            await self._run_player_data_updates()
            results["player_updates"] = {
                "completed": True,
                "stats": self._last_stats.get("player_updates", {})
            }

        if task_type in ["upcoming", "all"]:
            # 📋 예정 대회 종목/참가자 사전 수집
            await self._run_upcoming_preparation()
            results["upcoming_preparation"] = {
                "completed": True,
                "stats": self._last_stats.get("upcoming_preparation", {})
            }

        if task_type in ["monitor", "all"]:
            # 📡 미래 대회 모니터링 (전체, 경량 API)
            await self._run_future_competition_monitoring()
            results["future_monitoring"] = {
                "completed": True,
                "stats": self._last_stats.get("future_monitoring", {})
            }

        if task_type in ["validate"]:
            # 🛡️ Data Guardian 데이터 검증
            try:
                from app.data_guardian import get_guardian
                guardian = get_guardian()
                result = await guardian.run_full_validation()
                results["guardian_validate"] = {"completed": True, "stats": result}
            except Exception as e:
                results["guardian_validate"] = {"completed": False, "error": str(e)}

        if task_type in ["health", "all"]:
            # 🛡️ Data Guardian 건강 점검
            await self._run_guardian_health_check()
            results["guardian_health"] = {
                "completed": True,
                "stats": self._last_stats.get("guardian_health", {})
            }

        if task_type in ["report"]:
            # 📊 Data Guardian 주간 리포트
            await self._run_guardian_weekly_report()
            results["guardian_weekly"] = {
                "completed": True,
                "stats": self._last_stats.get("guardian_weekly", {})
            }

        valid_types = [
            "detect", "pre", "change", "scrape", "final", "players",
            "upcoming", "monitor", "validate", "health", "report", "all",
        ]
        if task_type not in valid_types:
            return {"error": f"Unknown task type: {task_type}. Valid types: {valid_types}"}

        return {**results, "status": self.get_status()}


# 전역 스케줄러 인스턴스 (서버에서 사용)
_scheduler_instance: Optional[FencingScheduler] = None


def get_scheduler() -> FencingScheduler:
    """스케줄러 싱글톤 인스턴스 반환"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = FencingScheduler()
    return _scheduler_instance
