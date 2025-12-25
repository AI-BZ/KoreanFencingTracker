"""
전체 DE 데이터 재스크래핑 스크립트 v2

개선사항:
- 직접 URL 접근 (comp_idx 사용) - 검색 불필요
- 오래된 대회도 정상 접근 가능
- 더 빠른 스크래핑 (페이지 검색 불필요)

데이터 파이프라인:
1. events.raw_data.de_bracket 업데이트
2. matches 테이블 업데이트 (DE 경기)
3. 최종 순위 검증 및 업데이트
"""
import asyncio
import json
import signal
import sys
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.async_api import async_playwright, Page
from loguru import logger

from scraper.de_scraper_v4 import DEScraper
from database.supabase_client import get_supabase_client

# 로그 설정
LOG_FILE = f"logs/rescrape_de_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
os.makedirs("logs", exist_ok=True)
logger.add(LOG_FILE, rotation="10 MB", level="INFO")

# 진행 상태 저장 파일 (중단 시 재개용)
PROGRESS_FILE = "data/rescrape_progress_v2.json"

# 종료 플래그
shutdown_requested = False


def signal_handler(signum, frame):
    """Ctrl+C 핸들러"""
    global shutdown_requested
    logger.warning("⚠️ 종료 요청 수신 - 현재 작업 완료 후 종료됩니다...")
    shutdown_requested = True


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


@dataclass
class ScrapeResult:
    """스크래핑 결과"""
    event_id: int
    event_name: str
    success: bool
    bout_count: int = 0
    champion: str = ""
    error: str = ""


def load_progress() -> Dict[str, Any]:
    """진행 상태 로드"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_ids": [], "failed_ids": [], "last_run": None}


def save_progress(progress: Dict[str, Any]):
    """진행 상태 저장"""
    progress["last_run"] = datetime.now().isoformat()
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def get_events_to_scrape(year_filter: Optional[int] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """스크래핑 대상 이벤트 조회

    Args:
        year_filter: 특정 연도만 필터링 (None이면 전체)
        limit: 최대 개수 제한 (None이면 전체)
    """
    supabase = get_supabase_client()

    # 모든 이벤트 조회 (페이지네이션으로 1000개 제한 우회)
    all_events = []
    for offset in range(0, 5000, 1000):
        result = supabase.table("events").select(
            "id, event_name, event_cd, sub_event_cd, competition_id, raw_data"
        ).order("id", desc=True).range(offset, offset + 999).execute()

        if not result.data:
            break
        all_events.extend(result.data)

    if not all_events:
        return []

    logger.info(f"  총 이벤트 로드: {len(all_events)}개")

    # Python에서 개인전 필터링 ((개) 포함, 단체 제외)
    filtered_events = [
        e for e in all_events
        if "(개)" in e.get("event_name", "") and "단체" not in e.get("event_name", "")
    ]

    logger.info(f"  개인전 이벤트: {len(filtered_events)}개")

    if not filtered_events:
        return []

    # 대회 정보 조회 (comp_idx 포함)
    comp_ids = list(set(e["competition_id"] for e in filtered_events))
    comp_result = supabase.table("competitions").select(
        "id, comp_idx, comp_name, start_date"
    ).in_("id", comp_ids).execute()

    comp_map = {c["id"]: c for c in comp_result.data}

    events = []
    for e in filtered_events:
        comp = comp_map.get(e["competition_id"], {})
        start_date = comp.get("start_date", "")

        # 연도 필터링
        if year_filter and start_date:
            try:
                event_year = int(start_date[:4])
                if event_year != year_filter:
                    continue
            except:
                pass

        # v4 DE 데이터 유무 확인
        raw_data = e.get("raw_data") or {}
        de_bracket = raw_data.get("de_bracket") or {}
        has_v4_de = bool(de_bracket.get("bouts"))

        events.append({
            "id": e["id"],
            "event_name": e["event_name"],
            "event_cd": e["event_cd"],
            "sub_event_cd": e["sub_event_cd"],
            "comp_idx": comp.get("comp_idx", e["event_cd"]),  # fallback to event_cd
            "comp_name": comp.get("comp_name", ""),
            "start_date": start_date,
            "has_v4_de": has_v4_de
        })

    # v4 DE 없는 이벤트만 필터링
    events = [e for e in events if not e["has_v4_de"]]

    if limit:
        events = events[:limit]

    return events


async def scrape_event_de_direct(page: Page, event: Dict[str, Any], base_url: str) -> ScrapeResult:
    """단일 이벤트 DE 스크래핑 (직접 URL 접근 방식)"""
    event_id = event["id"]
    event_name = event["event_name"]
    comp_idx = event["comp_idx"]
    sub_event_cd = event["sub_event_cd"]

    try:
        # 1. 직접 대회 상세 페이지로 이동 (핵심 개선!)
        record_url = f"{base_url}/game/compListView?code=game&eventCd={comp_idx}&gubun=2&pageNum=1"
        logger.debug(f"  직접 URL 접근: {record_url}")

        response = await page.goto(record_url, timeout=30000)

        if not response or response.status != 200:
            return ScrapeResult(
                event_id=event_id,
                event_name=event_name,
                success=False,
                error=f"페이지 로드 실패 (status: {response.status if response else 'None'})"
            )

        await asyncio.sleep(2)

        # 페이지에 "대회를 찾을 수 없습니다" 같은 에러 메시지 확인
        content = await page.content()
        if "대회를 찾을 수 없" in content or "존재하지 않" in content:
            return ScrapeResult(
                event_id=event_id,
                event_name=event_name,
                success=False,
                error="대회 페이지 없음 (KFF 사이트에서 삭제됨)"
            )

        # 2. 대진표 탭 클릭
        bracket_tab = page.locator("a[onclick*='funcLeftSub']:has-text('대진표')")
        if await bracket_tab.count() == 0:
            # 대진표 탭이 없으면 다른 방식 시도
            bracket_tab = page.locator("a:has-text('대진표')")

        if await bracket_tab.count() == 0:
            return ScrapeResult(
                event_id=event_id,
                event_name=event_name,
                success=False,
                error="대진표 탭 없음"
            )

        await bracket_tab.first.click(timeout=10000)
        await asyncio.sleep(2)

        # 3. 종목 선택 (sub_event_cd 사용)
        select_locator = page.locator('select')
        if await select_locator.count() > 0:
            try:
                # 먼저 select 옵션 확인
                options = await page.locator('select option').all()
                option_values = []
                for opt in options:
                    val = await opt.get_attribute('value')
                    if val:
                        option_values.append(val)

                if sub_event_cd in option_values:
                    await page.select_option('select', sub_event_cd, timeout=5000)
                    await asyncio.sleep(2)
                elif option_values:
                    # sub_event_cd가 없으면 COMPS로 시작하는 첫 번째 옵션 선택
                    for val in option_values:
                        if val.startswith('COMPS'):
                            await page.select_option('select', val, timeout=5000)
                            await asyncio.sleep(2)
                            break
            except Exception as e:
                logger.debug(f"  종목 선택 오류 (계속 진행): {e}")

        # 4. 엘리미나시옹디렉트 탭 클릭
        de_tab = page.locator("a:has-text('엘리미나시옹디렉트')")
        if await de_tab.count() == 0:
            return ScrapeResult(
                event_id=event_id,
                event_name=event_name,
                success=False,
                error="엘리미나시옹디렉트 탭 없음 (풀 경기만 있을 수 있음)"
            )

        await de_tab.first.click(timeout=10000)
        await asyncio.sleep(2)

        # 5. DE Scraper v4 실행
        scraper = DEScraper(page)
        bracket = await scraper.parse_de_bracket()
        result = bracket.to_dict()

        bout_count = len(result.get("bouts", []))
        champion_info = result.get("champion", {})
        champion_name = champion_info.get("name", "") if champion_info else ""

        if bout_count == 0:
            return ScrapeResult(
                event_id=event_id,
                event_name=event_name,
                success=False,
                error="경기 데이터 없음"
            )

        # 6. Supabase 업데이트
        update_success = update_supabase(event_id, result)

        if update_success:
            return ScrapeResult(
                event_id=event_id,
                event_name=event_name,
                success=True,
                bout_count=bout_count,
                champion=champion_name
            )
        else:
            return ScrapeResult(
                event_id=event_id,
                event_name=event_name,
                success=False,
                error="Supabase 업데이트 실패"
            )

    except Exception as e:
        logger.error(f"스크래핑 오류 [{event_id}] {event_name}: {e}")
        return ScrapeResult(
            event_id=event_id,
            event_name=event_name,
            success=False,
            error=str(e)
        )


def update_supabase(event_id: int, de_data: Dict[str, Any]) -> bool:
    """DE 데이터를 Supabase에 업데이트"""
    try:
        supabase = get_supabase_client()

        # 1. events.raw_data 업데이트
        result = supabase.table("events").select("raw_data").eq("id", event_id).execute()

        if not result.data:
            logger.error(f"Event ID {event_id} not found")
            return False

        existing_raw_data = result.data[0].get("raw_data") or {}
        existing_raw_data["de_bracket"] = de_data
        existing_raw_data["de_updated_at"] = datetime.now().isoformat()
        existing_raw_data["de_scraper_version"] = "v4"

        # champion 정보를 final_rankings에도 반영 (데이터 파이프라인 일관성)
        champion = de_data.get("champion", {})
        if champion and champion.get("name"):
            # final_rankings가 없으면 DE 결과에서 생성
            if not existing_raw_data.get("final_rankings"):
                final_rankings = generate_final_rankings_from_de(de_data)
                if final_rankings:
                    existing_raw_data["final_rankings"] = final_rankings

        update_result = supabase.table("events").update({
            "raw_data": existing_raw_data,
            "updated_at": datetime.now().isoformat()
        }).eq("id", event_id).execute()

        if not update_result.data:
            return False

        # 2. matches 테이블 업데이트
        update_matches_table(event_id, de_data)

        return True

    except Exception as e:
        logger.error(f"Supabase 업데이트 오류: {e}")
        return False


def generate_final_rankings_from_de(de_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """DE 결과에서 최종 순위 생성 (데이터 파이프라인 보강)"""
    rankings = []
    bouts = de_data.get("bouts", [])

    if not bouts:
        return rankings

    # 라운드별로 정리
    rounds = {}
    for bout in bouts:
        round_name = bout.get("round_name", bout.get("round", ""))
        if round_name not in rounds:
            rounds[round_name] = []
        rounds[round_name].append(bout)

    # 1위: 결승 승자 (champion)
    champion = de_data.get("champion", {})
    if champion and champion.get("name"):
        rankings.append({
            "rank": 1,
            "name": champion.get("name"),
            "team": champion.get("team", "")
        })

        # 2위: 결승 패자
        final_bouts = rounds.get("결승", [])
        if final_bouts:
            final = final_bouts[0]
            loser_name = final.get("player1_name") if champion.get("name") == final.get("player2_name") else final.get("player2_name")
            loser_team = final.get("player1_team") if champion.get("name") == final.get("player2_name") else final.get("player2_team")
            if loser_name and loser_name != "None":
                rankings.append({
                    "rank": 2,
                    "name": loser_name,
                    "team": loser_team or ""
                })

        # 3-4위: 준결승 패자
        semifinal_bouts = rounds.get("준결승", [])
        rank = 3
        for bout in semifinal_bouts:
            winner = bout.get("winner_name")
            if winner:
                loser = bout.get("player1_name") if winner == bout.get("player2_name") else bout.get("player2_name")
                loser_team = bout.get("player1_team") if winner == bout.get("player2_name") else bout.get("player2_team")
                if loser and loser != "None" and loser not in [r["name"] for r in rankings]:
                    rankings.append({
                        "rank": rank,
                        "name": loser,
                        "team": loser_team or ""
                    })
                    rank += 1

    return rankings


def update_matches_table(event_id: int, de_data: Dict[str, Any]) -> int:
    """matches 테이블 업데이트"""
    try:
        supabase = get_supabase_client()
        bouts = de_data.get("bouts", [])

        if not bouts:
            return 0

        # 기존 DE 경기 삭제
        supabase.table("matches").delete().eq("event_id", event_id).like("round_name", "%강%").execute()
        supabase.table("matches").delete().eq("event_id", event_id).eq("round_name", "결승").execute()
        supabase.table("matches").delete().eq("event_id", event_id).eq("round_name", "준결승").execute()

        # 새 경기 삽입
        matches_to_insert = []
        for bout in bouts:
            round_name = bout.get("round_name", bout.get("round", ""))
            match_number = bout.get("match_number", bout.get("matchNumber", 0))

            # 선수 정보 추출 (v4 flat 형식)
            p1_name = bout.get("player1_name")
            p1_score = bout.get("player1_score")
            p2_name = bout.get("player2_name")
            p2_score = bout.get("player2_score")
            winner_name = bout.get("winner_name")

            # None 또는 빈 값 건너뛰기 (bye match)
            if not p1_name or p1_name == "None" or not p2_name or p2_name == "None":
                continue

            match_data = {
                "event_id": event_id,
                "round_name": round_name,
                "match_number": match_number,
                "player1_name": p1_name,
                "player1_score": p1_score,
                "player2_name": p2_name,
                "player2_score": p2_score,
                "match_status": "completed" if winner_name else "pending",
                "raw_data": bout
            }
            matches_to_insert.append(match_data)

        if matches_to_insert:
            supabase.table("matches").insert(matches_to_insert).execute()

        return len(matches_to_insert)

    except Exception as e:
        logger.error(f"matches 테이블 업데이트 오류: {e}")
        return 0


async def main():
    """메인 실행"""
    global shutdown_requested

    import argparse
    parser = argparse.ArgumentParser(description="DE 재스크래핑 v2 (직접 URL 접근)")
    parser.add_argument("--year", type=int, help="특정 연도만 스크래핑")
    parser.add_argument("--limit", type=int, help="최대 이벤트 수")
    parser.add_argument("--reset", action="store_true", help="진행 상태 초기화")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("DE 전체 재스크래핑 v2 시작 (직접 URL 접근)")
    logger.info("=" * 60)

    # 진행 상태 로드
    if args.reset:
        progress = {"completed_ids": [], "failed_ids": [], "last_run": None}
        save_progress(progress)
        logger.info("진행 상태 초기화됨")
    else:
        progress = load_progress()

    completed_ids = set(progress.get("completed_ids", []))
    failed_ids = set(progress.get("failed_ids", []))

    # 스크래핑 대상 조회
    logger.info(f"스크래핑 대상 조회 중... (연도: {args.year or '전체'})")
    all_events = get_events_to_scrape(year_filter=args.year, limit=args.limit)

    # 이미 완료된 이벤트 제외
    events_to_scrape = [e for e in all_events if e["id"] not in completed_ids]

    logger.info(f"v4 DE 없는 이벤트: {len(all_events)}개")
    logger.info(f"이전 완료: {len(completed_ids)}개")
    logger.info(f"스크래핑 대상: {len(events_to_scrape)}개")

    if not events_to_scrape:
        logger.info("스크래핑할 이벤트가 없습니다.")
        return

    BASE_URL = "https://fencing.sports.or.kr"

    success_count = 0
    fail_count = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(30000)

        try:
            for i, event in enumerate(events_to_scrape):
                if shutdown_requested:
                    logger.warning("사용자 요청으로 종료합니다.")
                    break

                logger.info(f"\n[{i+1}/{len(events_to_scrape)}] {event['event_name']}")
                logger.info(f"  대회: {event['comp_name']} ({event['start_date']})")
                logger.info(f"  comp_idx: {event['comp_idx']}")

                result = await scrape_event_de_direct(page, event, BASE_URL)

                if result.success:
                    success_count += 1
                    completed_ids.add(event["id"])
                    logger.info(f"  ✅ 성공: {result.bout_count}경기, 우승: {result.champion}")
                else:
                    fail_count += 1
                    failed_ids.add(event["id"])
                    logger.warning(f"  ❌ 실패: {result.error}")

                # 진행 상태 저장 (5개마다)
                if (i + 1) % 5 == 0:
                    progress["completed_ids"] = list(completed_ids)
                    progress["failed_ids"] = list(failed_ids)
                    save_progress(progress)
                    logger.info(f"  💾 진행 상태 저장 ({success_count} 성공, {fail_count} 실패)")

                # 서버 부하 방지
                await asyncio.sleep(1.5)

        finally:
            await browser.close()

    # 최종 진행 상태 저장
    progress["completed_ids"] = list(completed_ids)
    progress["failed_ids"] = list(failed_ids)
    save_progress(progress)

    logger.info("\n" + "=" * 60)
    logger.info("DE 재스크래핑 v2 완료")
    logger.info(f"성공: {success_count}개")
    logger.info(f"실패: {fail_count}개")
    logger.info(f"성공률: {success_count / (success_count + fail_count) * 100:.1f}%" if (success_count + fail_count) > 0 else "N/A")
    logger.info(f"로그 파일: {LOG_FILE}")
    logger.info("=" * 60)

    if success_count > 0:
        logger.info("\n⚠️ 서버 재시작이 필요합니다!")
        logger.info("   변경된 데이터를 반영하려면 서버를 재시작하세요.")


if __name__ == "__main__":
    asyncio.run(main())
