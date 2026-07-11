#!/usr/bin/env python3
"""
특정 이벤트 재스크래핑 스크립트
"""

import asyncio
import os
import sys
import json
import logging
from datetime import datetime

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from playwright.async_api import async_playwright
from supabase import create_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Supabase 클라이언트
url = os.environ.get('SUPABASE_URL')
key = os.environ.get('SUPABASE_KEY')
supabase = create_client(url, key)


async def rescrape_event(comp_idx: str, sub_event_cd: str):
    """특정 이벤트 재스크래핑"""

    from scraper.de_scraper_v4 import DEScraper

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='ko-KR'
        )
        page = await context.new_page()

        try:
            # 1. 대회 페이지 접속
            base_url = "https://fencing.sports.or.kr/service/competition"
            comp_url = f"{base_url}/competitionResult.do?event_cd={comp_idx}"

            logger.info(f"대회 페이지 접속: {comp_url}")
            await page.goto(comp_url, wait_until='networkidle', timeout=30000)
            await asyncio.sleep(2)

            # 2. 대진표 탭 클릭
            await page.click('a:has-text("대진표")')
            await asyncio.sleep(2)

            # 3. 종목 선택
            select_element = page.locator('select#searchSubcd')
            options = await select_element.locator('option').all()

            target_option = None
            for opt in options:
                val = await opt.get_attribute('value')
                text = await opt.inner_text()
                if val == sub_event_cd:
                    target_option = opt
                    logger.info(f"종목 발견: {text} ({val})")
                    break

            if not target_option:
                logger.error(f"종목을 찾을 수 없음: {sub_event_cd}")
                return None

            # 종목 선택
            await select_element.select_option(value=sub_event_cd)
            await asyncio.sleep(1)

            # 검색 버튼 클릭
            search_btn = page.locator('button:has-text("검색"), a:has-text("검색"), input[type="submit"]')
            if await search_btn.count() > 0:
                await search_btn.first.click()
            await asyncio.sleep(2)

            # 4. 엘리미나시옹디렉트 탭 클릭
            de_tab = page.locator('a:has-text("엘리미나시옹디렉트")')
            if await de_tab.count() > 0:
                await de_tab.click()
                await asyncio.sleep(2)
            else:
                logger.warning("엘리미나시옹디렉트 탭 없음")

            # 5. DE 스크래핑
            scraper = DEScraper(page)
            bracket = await scraper.parse_de_bracket()

            if bracket:
                bracket_dict = bracket.to_dict()
                logger.info(f"스크래핑 결과:")
                logger.info(f"  bracket_size: {bracket_dict.get('bracket_size')}")
                logger.info(f"  starting_round: {bracket_dict.get('starting_round')}")
                logger.info(f"  seeding: {len(bracket_dict.get('seeding', []))}명")
                logger.info(f"  bouts: {len(bracket_dict.get('bouts', []))}개")

                # bouts_by_round 출력
                bouts_by_round = bracket_dict.get('bouts_by_round', {})
                for round_name, bouts in bouts_by_round.items():
                    logger.info(f"  {round_name}: {len(bouts)}경기")

                return bracket_dict
            else:
                logger.warning("스크래핑 결과 없음")
                return None

        except Exception as e:
            logger.error(f"스크래핑 오류: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            await browser.close()


async def update_event_in_db(sub_event_cd: str, de_bracket: dict):
    """Supabase에 DE 브라켓 데이터 업데이트"""

    # 기존 이벤트 조회
    result = supabase.table('events').select('id, raw_data').eq('sub_event_cd', sub_event_cd).execute()

    if not result.data:
        logger.error(f"이벤트 없음: {sub_event_cd}")
        return False

    event = result.data[0]
    event_id = event['id']
    raw_data = event.get('raw_data', {}) or {}

    # raw_data에 de_bracket 업데이트
    raw_data['de_bracket'] = de_bracket

    # 업데이트
    update_result = supabase.table('events').update({
        'raw_data': raw_data,
        'updated_at': datetime.now().isoformat()
    }).eq('id', event_id).execute()

    if update_result.data:
        logger.info(f"DB 업데이트 완료: event_id={event_id}")
        return True
    else:
        logger.error(f"DB 업데이트 실패")
        return False


async def main():
    # 재스크래핑 대상
    comp_idx = "COMPM00520"  # 2023 생활체육(클럽, 동호인) 전국펜싱대회
    sub_event_cd = "COMPS000000000002550"  # 엘리트부 남자 사브르(개)

    logger.info(f"재스크래핑 시작: {comp_idx} / {sub_event_cd}")

    # 스크래핑
    de_bracket = await rescrape_event(comp_idx, sub_event_cd)

    if de_bracket and de_bracket.get('bouts'):
        # DB 업데이트
        success = await update_event_in_db(sub_event_cd, de_bracket)
        if success:
            logger.info("재스크래핑 및 DB 업데이트 완료!")
        else:
            logger.error("DB 업데이트 실패")
    else:
        logger.warning("스크래핑 결과가 없거나 bouts가 비어있음")


if __name__ == "__main__":
    asyncio.run(main())
