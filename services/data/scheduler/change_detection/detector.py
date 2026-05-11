"""
변경 감지기 (Change Detector)

Playwright를 사용하여 협회 사이트에서 종목별 상태 지문을 추출합니다.
가벼운 체크만 수행하여 빠르게 변경 여부를 판단합니다.
"""

import asyncio
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

from playwright.async_api import async_playwright, Browser, Page, Playwright
from loguru import logger

from .fingerprint import EventFingerprint, CompetitionFingerprint


# 상수
BASE_URL = "https://fencing.sports.or.kr"
DEFAULT_TIMEOUT = 15000  # 15초
SEARCH_WAIT_MS = 2000    # 검색 후 대기 시간


@dataclass
class DetectionConfig:
    """변경 감지 설정"""
    # 타임아웃
    page_timeout_ms: int = 15000
    search_wait_ms: int = 2000

    # 재시도
    max_retries: int = 2
    retry_delay_sec: float = 3.0

    # 병렬 처리 (브라우저 인스턴스 공유하므로 순차 처리)
    headless: bool = True

    # 활성 시간대
    active_hours_start: int = 8
    active_hours_end: int = 21


class ChangeDetector:
    """
    협회 사이트 변경 감지기

    사용법:
        detector = ChangeDetector()
        fingerprint = await detector.capture_competition_fingerprint("COMPM00679")

        # 이전 지문과 비교
        changed_events = fingerprint.get_changed_events(old_fingerprint)
    """

    def __init__(self, config: Optional[DetectionConfig] = None):
        self.config = config or DetectionConfig()
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def __aenter__(self):
        """컨텍스트 매니저 진입"""
        await self._init_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """컨텍스트 매니저 종료"""
        await self._close_browser()

    async def _init_browser(self):
        """브라우저 초기화"""
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.config.headless
            )
            logger.debug("변경 감지용 브라우저 시작")

    async def _close_browser(self):
        """브라우저 종료"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.debug("변경 감지용 브라우저 종료")

    async def capture_competition_fingerprint(
        self,
        comp_cd: str,
        comp_name: str = ""
    ) -> CompetitionFingerprint:
        """
        대회의 모든 종목 지문 캡처 (재시도 로직 포함)

        Args:
            comp_cd: 대회 코드 (예: COMPM00679)
            comp_name: 대회명 (로깅용)

        Returns:
            CompetitionFingerprint: 대회 상태 지문
        """
        last_error = None

        # 재시도 로직
        for attempt in range(self.config.max_retries + 1):
            if attempt > 0:
                logger.info(
                    f"재시도 {attempt}/{self.config.max_retries}: {comp_name or comp_cd}"
                )
                await asyncio.sleep(self.config.retry_delay_sec)

            fingerprint = await self._capture_fingerprint_once(comp_cd, comp_name)

            # 성공 시 반환
            if not fingerprint.error:
                return fingerprint

            last_error = fingerprint.error

            # 종목 없음은 재시도 불필요
            if "종목 없음" in str(last_error):
                return fingerprint

        # 모든 재시도 실패
        logger.error(
            f"지문 캡처 최종 실패 ({self.config.max_retries + 1}회 시도): "
            f"{comp_name or comp_cd} - {last_error}"
        )
        return fingerprint

    async def _capture_fingerprint_once(
        self,
        comp_cd: str,
        comp_name: str = ""
    ) -> CompetitionFingerprint:
        """단일 시도 지문 캡처 (내부 메서드)"""
        start_time = time.time()

        fingerprint = CompetitionFingerprint(
            comp_cd=comp_cd,
            comp_name=comp_name
        )

        page = None
        try:
            await self._init_browser()
            page = await self._browser.new_page()
            page.set_default_timeout(self.config.page_timeout_ms)

            # 1. 대회 목록 페이지 → 대회 클릭 → 경기결과 탭
            events = await self._navigate_to_competition(page, comp_cd)

            if not events:
                fingerprint.error = f"종목 없음: {comp_cd}"
                logger.warning(f"대회 {comp_cd}에 종목이 없습니다")
                return fingerprint

            # 2. 각 종목의 지문 캡처
            for event in events:
                try:
                    event_fp = await self._capture_event_fingerprint(
                        page, event['value'], event['text']
                    )
                    fingerprint.events[event['value']] = event_fp
                except Exception as e:
                    logger.error(f"종목 지문 캡처 실패 {event['value']}: {e}")
                    fingerprint.events[event['value']] = EventFingerprint(
                        sub_event_cd=event['value'],
                        event_name=event['text'],
                        error=str(e)
                    )

            elapsed_ms = int((time.time() - start_time) * 1000)
            fingerprint.detection_duration_ms = elapsed_ms
            fingerprint.captured_at = datetime.now()

            logger.info(
                f"대회 지문 캡처 완료: {comp_name or comp_cd} "
                f"({fingerprint.valid_event_count}/{fingerprint.event_count}개 종목, "
                f"{elapsed_ms}ms)"
            )

        except Exception as e:
            fingerprint.error = str(e)
            logger.error(f"대회 지문 캡처 실패 {comp_cd}: {e}")

        finally:
            if page:
                await page.close()

        return fingerprint

    async def _navigate_to_competition(
        self,
        page: Page,
        comp_cd: str
    ) -> List[Dict[str, str]]:
        """
        대회 경기결과 페이지로 이동하고 종목 목록 반환

        Returns:
            종목 목록: [{'value': 'COMPS...', 'text': '남자 플러레(개)'}, ...]
        """
        # 1. 대회 목록 페이지로 이동
        await page.goto(
            f"{BASE_URL}/game/compList?code=game",
            wait_until="networkidle",
            timeout=20000
        )
        await page.wait_for_timeout(2000)

        # 2. 대회 링크 찾아서 클릭
        link = page.locator(f'a[onclick*="{comp_cd}"]')
        link_count = await link.count()

        if link_count == 0:
            logger.warning(f"대회 링크 없음: {comp_cd}")
            return []

        await link.first.click(timeout=7000)
        await page.wait_for_timeout(3000)

        # 3. 경기결과 탭 클릭
        result_tab = page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
        if await result_tab.count() > 0:
            await result_tab.click(timeout=5000)
            await page.wait_for_timeout(2000)

        # 4. 종목 목록 추출
        options = await page.locator('select').first.locator('option').all()

        events = []
        for opt in options:
            val = await opt.get_attribute('value')
            if val and val.startswith('COMPS'):
                text = await opt.inner_text()
                events.append({'value': val, 'text': text.strip()})

        return events

    async def _capture_event_fingerprint(
        self,
        page: Page,
        sub_event_cd: str,
        event_name: str
    ) -> EventFingerprint:
        """
        종목 지문 캡처

        1. 종목 SELECT 선택
        2. 검색 버튼 클릭
        3. 지표 추출 (Pool V/D, DE 완료, 최종순위)
        """
        # 1. 종목 선택
        select_elem = page.locator('select').first
        await select_elem.select_option(sub_event_cd)
        await page.wait_for_timeout(500)

        # 2. 검색 버튼 클릭 (핵심!)
        search_btn = page.locator("a[href='#search']").first
        await search_btn.click()
        await page.wait_for_timeout(self.config.search_wait_ms)

        # 3. 지표 추출
        indicators = await page.evaluate("""
            () => {
                const result = {
                    poolGroups: 0,
                    poolRows: 0,
                    poolVdCount: 0,
                    deCompleted: 0,
                    deCells: 0,
                    finalRankingRows: 0
                };

                // Pool 그룹 및 V/D 결과 수
                const pouleDiv = document.querySelector('#pouleAjax');
                if (pouleDiv) {
                    const tables = pouleDiv.querySelectorAll('table');
                    result.poolGroups = tables.length;

                    tables.forEach(t => {
                        result.poolRows += t.querySelectorAll('tr').length;
                    });

                    // V/D 셀 수 (실제 경기 결과)
                    const vdCells = pouleDiv.querySelectorAll('td');
                    vdCells.forEach(cell => {
                        const text = cell.innerText.trim();
                        if (/^[VD]\\d/.test(text)) {
                            result.poolVdCount++;
                        }
                    });
                }

                // DE 대진표 - 여러 구조 지원
                // 1) #tournament_container (래퍼 div)
                // 2) #A_table (구형 DE 테이블)
                // 3) .tournament_table (신형 - 국가대표 선발전 등)
                const tournamentDiv = document.querySelector('#tournament_container')
                    || document.querySelector('#A_table')
                    || document.querySelector('.tournament_table');
                if (tournamentDiv) {
                    const cells = tournamentDiv.querySelectorAll('td');
                    result.deCells = cells.length;

                    // 완료된 경기 (점수 패턴 - td 내 텍스트)
                    cells.forEach(cell => {
                        const text = cell.innerText;
                        if (/\\d+\\s*[-:]\\s*\\d+/.test(text)) {
                            result.deCompleted++;
                        }
                    });

                    // .tournament_table의 .user_box 요소도 카운트 (score 속성)
                    const userBoxes = tournamentDiv.querySelectorAll('.user_box[score]');
                    userBoxes.forEach(box => {
                        const score = parseInt(box.getAttribute('score')) || 0;
                        if (score > 0) {
                            result.deCompleted++;
                        }
                    });
                }

                // 최종 순위
                const rankingDiv = document.querySelector('#layer_final_ranking');
                if (rankingDiv) {
                    result.finalRankingRows = rankingDiv.querySelectorAll('tr').length;
                }

                return result;
            }
        """)

        return EventFingerprint(
            sub_event_cd=sub_event_cd,
            event_name=event_name,
            pool_groups=indicators['poolGroups'],
            pool_rows=indicators['poolRows'],
            pool_vd_count=indicators['poolVdCount'],
            de_completed=indicators['deCompleted'],
            de_cells=indicators['deCells'],
            final_ranking_rows=indicators['finalRankingRows']
        )

    async def capture_single_event(
        self,
        comp_cd: str,
        sub_event_cd: str,
        event_name: str = ""
    ) -> EventFingerprint:
        """단일 종목 지문 캡처 (테스트/디버깅용)"""
        page = None
        try:
            await self._init_browser()
            page = await self._browser.new_page()
            page.set_default_timeout(self.config.page_timeout_ms)

            # 대회 페이지로 이동
            await self._navigate_to_competition(page, comp_cd)

            # 종목 지문 캡처
            return await self._capture_event_fingerprint(
                page, sub_event_cd, event_name
            )

        except Exception as e:
            logger.error(f"단일 종목 지문 캡처 실패: {e}")
            return EventFingerprint(
                sub_event_cd=sub_event_cd,
                event_name=event_name,
                error=str(e)
            )
        finally:
            if page:
                await page.close()

    def is_active_time(self) -> bool:
        """활성 시간대인지 확인"""
        current_hour = datetime.now().hour
        return (
            self.config.active_hours_start
            <= current_hour
            < self.config.active_hours_end
        )


async def quick_detect_changes(
    comp_cd: str,
    comp_name: str = "",
    previous_fingerprint: Optional[CompetitionFingerprint] = None
) -> Tuple[CompetitionFingerprint, List[str]]:
    """
    빠른 변경 감지 (독립 실행용)

    Returns:
        (현재 지문, 변경된 종목 코드 목록)
    """
    async with ChangeDetector() as detector:
        current = await detector.capture_competition_fingerprint(comp_cd, comp_name)

        if previous_fingerprint is None:
            # 이전 지문 없으면 모든 종목이 "변경됨"
            changed = list(current.events.keys())
        else:
            changed = current.get_changed_events(previous_fingerprint)

        return current, changed
