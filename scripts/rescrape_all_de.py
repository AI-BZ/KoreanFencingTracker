"""
전체 DE 데이터 재스크래핑 스크립트

DE Scraper v4를 사용하여 모든 대회의 DE 데이터를 재스크래핑하고 Supabase에 업로드

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
LOG_FILE = f"logs/rescrape_de_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
os.makedirs("logs", exist_ok=True)
logger.add(LOG_FILE, rotation="10 MB", level="INFO")

# 진행 상태 저장 파일 (중단 시 재개용)
PROGRESS_FILE = "data/rescrape_progress.json"

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


def get_events_to_scrape() -> List[Dict[str, Any]]:
    """스크래핑 대상 이벤트 조회"""
    supabase = get_supabase_client()

    # 개인전만 조회 (단체전 제외), 최신 대회부터
    result = supabase.table("events").select(
        "id, event_name, event_cd, sub_event_cd, competition_id, raw_data"
    ).not_.like("event_name", "%단체%").not_.like("event_name", "%단%").order("id", desc=True).execute()

    if not result.data:
        return []

    # 대회 정보 조회
    comp_ids = list(set(e["competition_id"] for e in result.data))
    comp_result = supabase.table("competitions").select(
        "id, comp_name, start_date"
    ).in_("id", comp_ids).execute()

    comp_map = {c["id"]: c for c in comp_result.data}

    events = []
    for e in result.data:
        comp = comp_map.get(e["competition_id"], {})
        events.append({
            "id": e["id"],
            "event_name": e["event_name"],
            "event_cd": e["event_cd"],
            "sub_event_cd": e["sub_event_cd"],
            "comp_name": comp.get("comp_name", ""),
            "start_date": comp.get("start_date", ""),
            "has_de": bool(e.get("raw_data", {}).get("de_bracket"))
        })

    return events


async def scrape_event_de(page: Page, event: Dict[str, Any], base_url: str) -> ScrapeResult:
    """단일 이벤트 DE 스크래핑"""
    event_id = event["id"]
    event_name = event["event_name"]
    event_cd = event["event_cd"]
    sub_event_cd = event["sub_event_cd"]

    try:
        # 1. 대회 목록 페이지로 이동
        await page.goto(f"{base_url}/game/compList?code=game", timeout=15000)
        await asyncio.sleep(2)

        # 2. 대회 클릭
        link = page.locator(f"a[onclick*='{event_cd}']")
        count = await link.count()

        if count == 0:
            # 다음 페이지 탐색 (최대 5페이지)
            found = False
            for _ in range(5):
                try:
                    next_btn = page.locator("a:has-text('다음페이지')")
                    if await next_btn.count() == 0:
                        break
                    await next_btn.click(timeout=3000)
                    await asyncio.sleep(1)

                    link = page.locator(f"a[onclick*='{event_cd}']")
                    if await link.count() > 0:
                        found = True
                        break
                except:
                    break

            if not found:
                return ScrapeResult(
                    event_id=event_id,
                    event_name=event_name,
                    success=False,
                    error="대회를 찾을 수 없음"
                )

        await link.first.click(timeout=5000)
        await asyncio.sleep(2)

        # 3. 대진표 탭 클릭
        bracket_tab = page.locator("a[onclick*='funcLeftSub']:has-text('대진표')")
        if await bracket_tab.count() == 0:
            return ScrapeResult(
                event_id=event_id,
                event_name=event_name,
                success=False,
                error="대진표 탭 없음"
            )

        await bracket_tab.first.click(timeout=5000)
        await asyncio.sleep(2)

        # 4. 종목 선택
        try:
            await page.select_option('select', sub_event_cd, timeout=5000)
        except:
            return ScrapeResult(
                event_id=event_id,
                event_name=event_name,
                success=False,
                error="종목 선택 실패"
            )
        await asyncio.sleep(2)

        # 5. 엘리미나시옹디렉트 탭 클릭
        de_tab = page.locator("a:has-text('엘리미나시옹디렉트')")
        if await de_tab.count() == 0:
            return ScrapeResult(
                event_id=event_id,
                event_name=event_name,
                success=False,
                error="엘리미나시옹디렉트 탭 없음 (풀 경기만 있을 수 있음)"
            )

        await de_tab.first.click(timeout=5000)
        await asyncio.sleep(2)

        # 6. DE Scraper v4 실행
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

        # 7. Supabase 업데이트
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

    # 라운드 순서 정의
    round_order = ["결승", "준결승", "8강", "16강", "32강", "64강", "128강"]

    # 1위: 결승 승자
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
            # v4 형식과 기존 형식 모두 지원
            round_name = bout.get("round_name", bout.get("round", ""))
            match_number = bout.get("match_number", bout.get("matchNumber", 0))

            # 선수 정보 추출
            if "player1_name" in bout:
                # v4 flat 형식
                p1_name = bout.get("player1_name")
                p1_score = bout.get("player1_score")
                p2_name = bout.get("player2_name")
                p2_score = bout.get("player2_score")
                winner_name = bout.get("winner_name")
            else:
                # nested 형식
                p1 = bout.get("player1", {})
                p2 = bout.get("player2", {})
                p1_name = p1.get("name")
                p1_score = p1.get("score")
                p2_name = p2.get("name")
                p2_score = p2.get("score")
                winner_name = bout.get("winnerName")

            # None 또는 빈 값 건너뛰기
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

    logger.info("=" * 60)
    logger.info("DE 전체 재스크래핑 시작")
    logger.info("=" * 60)

    # 진행 상태 로드
    progress = load_progress()
    completed_ids = set(progress.get("completed_ids", []))
    failed_ids = set(progress.get("failed_ids", []))

    # 스크래핑 대상 조회
    all_events = get_events_to_scrape()

    # 이미 완료된 이벤트 제외
    events_to_scrape = [e for e in all_events if e["id"] not in completed_ids]

    logger.info(f"총 이벤트: {len(all_events)}개")
    logger.info(f"완료된 이벤트: {len(completed_ids)}개")
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

                logger.info(f"\n[{i+1}/{len(events_to_scrape)}] {event['event_name']} ({event['comp_name']})")

                result = await scrape_event_de(page, event, BASE_URL)

                if result.success:
                    success_count += 1
                    completed_ids.add(event["id"])
                    logger.info(f"  ✅ 성공: {result.bout_count}경기, 우승: {result.champion}")
                else:
                    fail_count += 1
                    failed_ids.add(event["id"])
                    logger.warning(f"  ❌ 실패: {result.error}")

                # 진행 상태 저장 (10개마다)
                if (i + 1) % 10 == 0:
                    progress["completed_ids"] = list(completed_ids)
                    progress["failed_ids"] = list(failed_ids)
                    save_progress(progress)
                    logger.info(f"  💾 진행 상태 저장 ({success_count} 성공, {fail_count} 실패)")

                # 서버 부하 방지
                await asyncio.sleep(2)

        finally:
            await browser.close()

    # 최종 진행 상태 저장
    progress["completed_ids"] = list(completed_ids)
    progress["failed_ids"] = list(failed_ids)
    save_progress(progress)

    logger.info("\n" + "=" * 60)
    logger.info("DE 재스크래핑 완료")
    logger.info(f"성공: {success_count}개")
    logger.info(f"실패: {fail_count}개")
    logger.info(f"로그 파일: {LOG_FILE}")
    logger.info("=" * 60)

    if success_count > 0:
        logger.info("\n⚠️ 서버 재시작이 필요합니다!")
        logger.info("   변경된 데이터를 반영하려면 서버를 재시작하세요.")


if __name__ == "__main__":
    asyncio.run(main())
