"""
DE 데이터 Re-scrape 및 Supabase 업로드 스크립트
DE Scraper v4를 사용하여 불완전한 DE 데이터를 재스크래핑하고 Supabase에 저장

Usage:
    # 불완전한 DE 데이터를 가진 이벤트 확인 (dry-run)
    python scripts/rescrape_de_to_supabase.py --dry-run

    # 2025년 협회장배만 재스크래핑
    python scripts/rescrape_de_to_supabase.py --year 2025 --comp-name 협회장배

    # 특정 이벤트 ID만 재스크래핑
    python scripts/rescrape_de_to_supabase.py --event-ids 60,61,62
"""
import asyncio
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional
from playwright.async_api import async_playwright, Page
from loguru import logger
import sys
import os

# 프로젝트 루트 추가
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# de_scraper_v4 직접 import (scraper/__init__.py 우회)
import importlib.util
de_scraper_spec = importlib.util.spec_from_file_location(
    "de_scraper_v4",
    os.path.join(PROJECT_ROOT, "scraper", "de_scraper_v4.py")
)
de_scraper_module = importlib.util.module_from_spec(de_scraper_spec)
de_scraper_spec.loader.exec_module(de_scraper_module)
DEScraper = de_scraper_module.DEScraper

from database.supabase_client import get_supabase_client

# 필수 라운드 - 이 중 하나라도 없으면 불완전
REQUIRED_ROUNDS = ["8강", "준결승", "결승"]


def find_incomplete_de_events(
    year_filter: Optional[int] = None,
    comp_name_filter: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    8강/준결승/결승이 누락된 이벤트 찾기
    """
    supabase = get_supabase_client()

    # 기본 쿼리 - 개인전만, bouts가 있는 이벤트만
    query = supabase.table("events").select(
        "id, event_name, event_cd, sub_event_cd, raw_data, "
        "competitions!inner(id, comp_idx, comp_name, start_date)"
    ).like("event_name", "%개)%")

    if year_filter:
        query = query.gte("competitions.start_date", f"{year_filter}-01-01")
        query = query.lt("competitions.start_date", f"{year_filter + 1}-01-01")

    if comp_name_filter:
        query = query.ilike("competitions.comp_name", f"%{comp_name_filter}%")

    result = query.order("id", desc=True).limit(500).execute()

    incomplete_events = []

    for event in result.data:
        raw_data = event.get("raw_data") or {}
        de_bracket = raw_data.get("de_bracket") or {}
        rounds = de_bracket.get("rounds") or []
        bouts = de_bracket.get("bouts") or []

        # bouts가 있지만 필수 라운드가 누락된 경우
        if bouts and len(bouts) > 0:
            missing = [r for r in REQUIRED_ROUNDS if r not in rounds]
            if missing:
                comp = event.get("competitions", {})
                incomplete_events.append({
                    "id": event["id"],
                    "event_name": event["event_name"],
                    "event_cd": event["event_cd"],
                    "sub_event_cd": event["sub_event_cd"],
                    "comp_idx": comp.get("comp_idx", event["event_cd"]),
                    "comp_name": comp.get("comp_name", ""),
                    "start_date": comp.get("start_date", ""),
                    "existing_rounds": rounds,
                    "missing_rounds": missing,
                    "bout_count": len(bouts),
                    "raw_data": raw_data
                })

    # 제한 적용
    return incomplete_events[:limit]


async def scrape_de_direct(page: Page, comp_idx: str, sub_event_cd: str) -> Optional[Dict]:
    """
    직접 URL 접근 방식으로 DE 스크래핑 (더 빠르고 안정적)
    """
    BASE_URL = "https://fencing.sports.or.kr"

    try:
        # 1. 직접 대회 상세 페이지로 이동
        url = f"{BASE_URL}/game/compListView?code=game&eventCd={comp_idx}&gubun=2&pageNum=1"
        await page.goto(url, timeout=30000)
        await asyncio.sleep(2)

        # 2. 대진표 탭 클릭
        bracket_tab = page.locator("a[onclick*='funcLeftSub']:has-text('대진표')")
        if await bracket_tab.count() == 0:
            bracket_tab = page.locator("a:has-text('대진표')")

        if await bracket_tab.count() > 0:
            await bracket_tab.first.click(timeout=10000)
            await asyncio.sleep(2)
        else:
            logger.warning("대진표 탭 없음")
            return None

        # 3. 종목 선택
        select = page.locator("select")
        if await select.count() > 0:
            options = await page.locator("select option").all()
            option_values = [await opt.get_attribute("value") for opt in options if await opt.get_attribute("value")]

            if sub_event_cd in option_values:
                await page.select_option("select", sub_event_cd, timeout=5000)
            elif option_values:
                # COMPS로 시작하는 첫 번째 옵션
                for val in option_values:
                    if val and val.startswith("COMPS"):
                        await page.select_option("select", val, timeout=5000)
                        break
            await asyncio.sleep(2)

        # 4. 엘리미나시옹디렉트 탭 클릭
        de_tab = page.locator("a:has-text('엘리미나시옹디렉트')")
        if await de_tab.count() > 0:
            await de_tab.first.click(timeout=10000)
            await asyncio.sleep(2)
        else:
            logger.warning("엘리미나시옹디렉트 탭 없음")
            return None

        # 5. DEScraper v4 실행
        scraper = DEScraper(page)
        bracket = await scraper.parse_de_bracket()
        return bracket.to_dict()

    except Exception as e:
        logger.error(f"스크래핑 오류: {e}")
        return None


async def scrape_de_for_event(
    event_cd: str,
    sub_event_cd: str,
    event_name: str,
    page_num: int = 1
) -> dict:
    """특정 종목의 DE 데이터 스크래핑 (기존 방식 - 호환성 유지)"""
    BASE_URL = "https://fencing.sports.or.kr"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(30000)

        try:
            logger.info(f"스크래핑 시작: {event_name}")

            # 1. 대회 목록 페이지
            await page.goto(f"{BASE_URL}/game/compList?code=game", timeout=15000)
            await asyncio.sleep(2)

            # 2. 페이지 이동
            if page_num > 1:
                for i in range(page_num - 1):
                    try:
                        next_btn = page.locator("a:has-text('다음페이지')")
                        await next_btn.click(timeout=3000)
                        await asyncio.sleep(1)
                    except Exception:
                        break

            # 3. 대회 클릭
            link = page.locator(f"a[onclick*='{event_cd}']")
            await link.first.click(timeout=5000)
            await asyncio.sleep(2)

            # 4. 대진표 탭 클릭
            bracket_tab = page.locator("a[onclick*='funcLeftSub']:has-text('대진표')")
            await bracket_tab.first.click(timeout=5000)
            await asyncio.sleep(2)

            # 5. 종목 선택
            await page.select_option('select', sub_event_cd)
            await asyncio.sleep(2)

            # 6. 엘리미나시옹디렉트 탭 클릭
            de_tab = page.locator("a:has-text('엘리미나시옹디렉트')")
            await de_tab.first.click(timeout=5000)
            await asyncio.sleep(2)

            # 7. DE Scraper v4 실행
            scraper = DEScraper(page)
            bracket = await scraper.parse_de_bracket()
            result = bracket.to_dict()

            logger.info(f"  - 시작 라운드: {result.get('starting_round')}")
            logger.info(f"  - 경기 수: {len(result.get('bouts', []))}")
            logger.info(f"  - 우승자: {result.get('champion', {}).get('name') if result.get('champion') else 'N/A'}")

            return result

        except Exception as e:
            logger.error(f"스크래핑 오류: {e}")
            import traceback
            traceback.print_exc()
            return {}
        finally:
            await browser.close()


def upload_de_to_supabase(event_id: int, de_data: dict) -> bool:
    """DE 데이터를 Supabase events 테이블의 raw_data에 저장"""
    try:
        supabase = get_supabase_client()

        # 기존 raw_data 조회
        result = supabase.table("events").select("raw_data").eq("id", event_id).execute()

        if not result.data:
            logger.error(f"Event ID {event_id} not found")
            return False

        # raw_data 업데이트 (de_bracket 추가)
        existing_raw_data = result.data[0].get("raw_data") or {}
        existing_raw_data["de_bracket"] = de_data
        existing_raw_data["de_updated_at"] = datetime.now().isoformat()

        # 업데이트
        update_result = supabase.table("events").update({
            "raw_data": existing_raw_data,
            "updated_at": datetime.now().isoformat()
        }).eq("id", event_id).execute()

        if update_result.data:
            logger.info(f"Event ID {event_id} DE 데이터 업데이트 완료")
            return True
        else:
            logger.error(f"업데이트 실패: {update_result}")
            return False

    except Exception as e:
        logger.error(f"Supabase 업로드 오류: {e}")
        return False


def upload_de_matches_to_supabase(event_id: int, de_data: dict) -> int:
    """DE 경기 데이터를 matches 테이블에 저장"""
    try:
        supabase = get_supabase_client()
        bouts = de_data.get("bouts", [])

        if not bouts:
            logger.warning(f"Event ID {event_id}: 저장할 경기 없음")
            return 0

        # 기존 DE 경기 삭제 (re-scrape)
        supabase.table("matches").delete().eq("event_id", event_id).like("round_name", "%강%").execute()

        # 새 경기 데이터 삽입
        matches_to_insert = []
        for bout in bouts:
            match_data = {
                "event_id": event_id,
                "round_name": bout.get("round_name"),
                "match_number": bout.get("match_number"),
                "player1_name": bout.get("player1_name"),
                "player1_score": bout.get("player1_score"),
                "player2_name": bout.get("player2_name"),
                "player2_score": bout.get("player2_score"),
                "match_status": "completed" if bout.get("winner_name") else "pending",
                "raw_data": bout
            }
            matches_to_insert.append(match_data)

        if matches_to_insert:
            result = supabase.table("matches").insert(matches_to_insert).execute()
            logger.info(f"Event ID {event_id}: {len(matches_to_insert)}개 경기 저장 완료")
            return len(matches_to_insert)

        return 0

    except Exception as e:
        logger.error(f"matches 테이블 업로드 오류: {e}")
        return 0


async def main():
    """메인 실행"""
    parser = argparse.ArgumentParser(description="불완전한 DE 데이터 재스크래핑")
    parser.add_argument("--year", type=int, help="연도 필터 (예: 2025)")
    parser.add_argument("--comp-name", type=str, help="대회명 필터 (예: 협회장배)")
    parser.add_argument("--event-ids", type=str, help="특정 이벤트 ID들 (예: 60,61,62)")
    parser.add_argument("--limit", type=int, default=50, help="최대 처리 개수")
    parser.add_argument("--dry-run", action="store_true", help="실제 스크래핑 없이 대상만 확인")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("불완전한 DE 데이터 재스크래핑")
    logger.info(f"필터: year={args.year}, comp_name={args.comp_name}")
    logger.info("=" * 60)

    # 1. 불완전한 이벤트 찾기
    if args.event_ids:
        # 특정 이벤트 ID 지정
        event_ids = [int(x.strip()) for x in args.event_ids.split(",")]
        supabase = get_supabase_client()
        result = supabase.table("events").select(
            "id, event_name, event_cd, sub_event_cd, raw_data, "
            "competitions!inner(id, comp_idx, comp_name, start_date)"
        ).in_("id", event_ids).execute()

        incomplete_events = []
        for event in result.data:
            raw_data = event.get("raw_data") or {}
            de_bracket = raw_data.get("de_bracket") or {}
            rounds = de_bracket.get("rounds") or []
            comp = event.get("competitions", {})

            incomplete_events.append({
                "id": event["id"],
                "event_name": event["event_name"],
                "event_cd": event["event_cd"],
                "sub_event_cd": event["sub_event_cd"],
                "comp_idx": comp.get("comp_idx", event["event_cd"]),
                "comp_name": comp.get("comp_name", ""),
                "start_date": comp.get("start_date", ""),
                "existing_rounds": rounds,
                "missing_rounds": [r for r in REQUIRED_ROUNDS if r not in rounds],
                "raw_data": raw_data
            })
    else:
        incomplete_events = find_incomplete_de_events(
            year_filter=args.year,
            comp_name_filter=args.comp_name,
            limit=args.limit
        )

    logger.info(f"불완전한 이벤트: {len(incomplete_events)}개")

    if not incomplete_events:
        logger.info("재스크래핑할 이벤트가 없습니다.")
        return

    # 이벤트 목록 출력
    for i, event in enumerate(incomplete_events):
        logger.info(f"  [{i+1}] ID:{event['id']} {event['comp_name']} - {event['event_name']}")
        logger.info(f"       기존: {event['existing_rounds']}, 누락: {event['missing_rounds']}")

    if args.dry_run:
        logger.info("\n[DRY-RUN] 실제 스크래핑 없이 종료")
        return

    # 2. 스크래핑 실행
    success_count = 0
    fail_count = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(30000)

        try:
            for i, event in enumerate(incomplete_events):
                logger.info(f"\n[{i+1}/{len(incomplete_events)}] {event['event_name']}")

                # DE 스크래핑 (직접 URL 방식)
                de_data = await scrape_de_direct(
                    page,
                    comp_idx=event["comp_idx"],
                    sub_event_cd=event["sub_event_cd"]
                )

                if not de_data or not de_data.get("bouts"):
                    logger.warning(f"  DE 데이터 없음")
                    fail_count += 1
                    continue

                new_rounds = de_data.get("rounds", [])
                bout_count = len(de_data.get("bouts", []))
                champion = de_data.get("champion", {})

                logger.info(f"  라운드: {new_rounds}")
                logger.info(f"  경기 수: {bout_count}")
                logger.info(f"  우승자: {champion.get('name') if champion else 'N/A'}")

                # Supabase 업데이트
                existing_raw_data = event.get("raw_data", {})
                success = upload_de_to_supabase(event["id"], de_data)

                if success:
                    match_count = upload_de_matches_to_supabase(event["id"], de_data)
                    logger.info(f"  ✅ 성공: {match_count}개 경기 저장")
                    success_count += 1
                else:
                    logger.error(f"  ❌ Supabase 업데이트 실패")
                    fail_count += 1

                # 딜레이
                await asyncio.sleep(2)

        finally:
            await browser.close()

    logger.info("\n" + "=" * 60)
    logger.info(f"완료: 성공={success_count}, 실패={fail_count}")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
