"""
개인 종목 참가선수 목록 가져오기
- KFF API enterPlayerJsonSelectList 직접 호출
- DB의 raw_data.participants에 저장

사용법:
    cd services/data
    PYTHONPATH="." python scripts/fetch_participants.py --comp COMPM00691
    PYTHONPATH="." python scripts/fetch_participants.py --all --since 2025-01-01
    PYTHONPATH="." python scripts/fetch_participants.py --all  # 전체 대회
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from loguru import logger
from scraper.client import KFFClient
from scraper.config import Endpoints
from supabase import create_client


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


async def fetch_players_direct(client: KFFClient, event_cd: str, sub_event_cd: str):
    """API 직접 호출하여 참가선수 목록 반환"""
    data = {"eventCd": event_cd, "subEventCd": sub_event_cd}
    response = await client._post(Endpoints.ENTER_PLAYER_LIST, data)
    parsed = json.loads(response)

    # 응답 형식: {"_TfGame": {...}, "_TfEnterPlayerList": [...]}
    if isinstance(parsed, dict):
        player_list = parsed.get("_TfEnterPlayerList", [])
    elif isinstance(parsed, list):
        player_list = parsed
    else:
        return []

    players = []
    for item in player_list:
        name = item.get("plyNm", "")
        team = item.get("teamNm", "")
        if name:
            players.append({"name": name, "team": team})
    return players


async def fetch_and_save_participants(comp_idx: str, competition_id: int):
    """참가선수 데이터가 없는 종목에 대해 가져와서 DB 저장"""

    db = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 모든 종목 조회
    events = db.table("events").select(
        "id, event_name, sub_event_cd, raw_data"
    ).eq("competition_id", competition_id).execute()

    if not events.data:
        logger.warning(f"  종목 없음 ({comp_idx})")
        return 0

    # 참가자 없는 종목만 필터
    events_to_fetch = []
    for event in events.data:
        raw_data = event.get("raw_data") or {}
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)
        participants = raw_data.get("participants")
        if not participants or len(participants) == 0:
            events_to_fetch.append(event)

    if not events_to_fetch:
        logger.info(f"  ✅ 모든 종목에 참가자 데이터 있음 ({comp_idx})")
        return 0

    logger.info(f"  📋 {len(events_to_fetch)}개 종목 참가자 가져오기")

    fetched_count = 0
    async with KFFClient() as client:
        for event in events_to_fetch:
            event_id = event["id"]
            event_name = event["event_name"]
            sub_event_cd = event["sub_event_cd"]

            try:
                players = await fetch_players_direct(client, comp_idx, sub_event_cd)

                if not players:
                    logger.debug(f"    ⚠️ {event_name}: 참가자 없음 (API 응답 없음)")
                    continue

                # DB 저장 형식 (num/name/team)
                participants = []
                for i, p in enumerate(players, 1):
                    participants.append({
                        "num": str(i),
                        "name": p["name"],
                        "team": p["team"]
                    })

                # raw_data에 participants 추가 (기존 데이터 보존)
                raw_data = event.get("raw_data") or {}
                if isinstance(raw_data, str):
                    raw_data = json.loads(raw_data)
                raw_data["participants"] = participants

                # DB 업데이트
                db.table("events").update({
                    "raw_data": raw_data
                }).eq("id", event_id).execute()

                fetched_count += 1
                logger.info(f"    ✅ {event_name}: {len(participants)}명 저장")

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"    ❌ {event_name}: {e}")
                continue

    return fetched_count


async def main():
    parser = argparse.ArgumentParser(description="참가선수 목록 가져오기 (KFF API)")
    parser.add_argument("--comp", type=str, help="특정 대회 코드 (예: COMPM00691)")
    parser.add_argument("--all", action="store_true", help="참가자 없는 모든 대회 처리")
    parser.add_argument("--since", type=str, default=None,
                        help="이 날짜 이후 대회만 (예: 2025-01-01)")
    parser.add_argument("--dry-run", action="store_true", help="실행 없이 대상 목록만 출력")

    args = parser.parse_args()

    db = create_client(SUPABASE_URL, SUPABASE_KEY)

    if args.comp:
        # 특정 대회
        comp = db.table("competitions").select("id, comp_idx, comp_name") \
            .eq("comp_idx", args.comp).single().execute()
        if not comp.data:
            logger.error(f"대회를 찾을 수 없음: {args.comp}")
            return
        logger.info(f"🏆 {comp.data['comp_name']} ({args.comp})")
        await fetch_and_save_participants(args.comp, comp.data["id"])

    elif args.all:
        # 참가자가 없는 모든 대회
        query = db.table("competitions").select("id, comp_idx, comp_name, start_date") \
            .order("start_date", desc=True)
        if args.since:
            query = query.gte("start_date", args.since)
        comps = query.execute()

        if not comps.data:
            logger.info("대회 없음")
            return

        total_fetched = 0
        for comp in comps.data:
            comp_idx = comp["comp_idx"]
            comp_id = comp["id"]
            comp_name = comp["comp_name"]

            # 참가자 있는 종목 수 확인
            events = db.table("events").select("id, raw_data") \
                .eq("competition_id", comp_id).execute()
            if not events.data:
                continue

            missing = 0
            for ev in events.data:
                raw = ev.get("raw_data") or {}
                if isinstance(raw, str):
                    raw = json.loads(raw)
                if not raw.get("participants"):
                    missing += 1

            if missing == 0:
                continue

            if args.dry_run:
                logger.info(f"[DRY-RUN] {comp_name}: {missing}/{len(events.data)}개 종목 참가자 없음")
                continue

            logger.info(f"\n🏆 {comp_name} ({comp_idx}) - {missing}개 종목")
            count = await fetch_and_save_participants(comp_idx, comp_id)
            total_fetched += count

        logger.info(f"\n🎉 전체 완료: {total_fetched}개 종목 참가자 저장")

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
