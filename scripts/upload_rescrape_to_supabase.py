"""
재스크래핑된 데이터를 Supabase에 업로드
- events.raw_data에 de_bracket, pool_rounds 등 저장
"""
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from loguru import logger

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://tjfjuasvjzjawyckengv.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


def upload_rescrape_data(json_file: str):
    """재스크래핑 데이터를 Supabase에 업로드"""
    if not SUPABASE_KEY:
        logger.error("SUPABASE_KEY 환경변수를 설정해주세요")
        return False

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Supabase 연결됨")

    # JSON 데이터 로드
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    competitions = data.get("competitions", [])
    logger.info(f"대회 수: {len(competitions)}")

    stats = {
        "competitions_updated": 0,
        "events_updated": 0,
        "events_created": 0,
        "errors": 0
    }

    for comp in competitions:
        # 중첩 구조 지원: competition 키 안에 있거나 직접 있는 경우
        comp_info = comp.get("competition", comp)
        comp_idx = comp_info.get("comp_idx") or comp_info.get("event_cd")
        comp_name = comp_info.get("comp_name") or comp_info.get("name", "Unknown")

        if not comp_idx:
            logger.warning(f"comp_idx 없음: {comp_name}")
            continue

        # 1. 대회 ID 조회 (있으면 사용, 없으면 생성)
        try:
            result = supabase.table("competitions").select("id").eq(
                "comp_idx", comp_idx
            ).execute()

            if result.data:
                comp_id = result.data[0]["id"]
                logger.info(f"기존 대회: {comp_name} (ID: {comp_id})")
            else:
                # 대회 생성
                comp_data = {
                    "comp_idx": comp_idx,
                    "comp_name": comp_name,
                    "start_date": comp_info.get("start_date"),
                    "end_date": comp_info.get("end_date"),
                    "venue": comp_info.get("venue") or comp_info.get("location", ""),
                    "status": comp_info.get("status", "completed")
                }
                result = supabase.table("competitions").insert(comp_data).execute()
                if result.data:
                    comp_id = result.data[0]["id"]
                    logger.info(f"새 대회 생성: {comp_name} (ID: {comp_id})")
                    stats["competitions_updated"] += 1
                else:
                    logger.error(f"대회 생성 실패: {comp_idx}")
                    continue

        except Exception as e:
            logger.error(f"대회 처리 오류: {e}")
            stats["errors"] += 1
            continue

        # 2. 종목 업데이트
        events = comp.get("events", [])
        for event in events:
            sub_event_cd = event.get("sub_event_cd")
            event_name = event.get("name") or event.get("event_name")

            if not sub_event_cd:
                logger.warning(f"sub_event_cd 없음: {event_name}")
                continue

            # raw_data 구성
            raw_data = {
                "pool_rounds": event.get("pool_rounds", []),
                "pool_total_ranking": event.get("pool_total_ranking", {}),
                "de_bracket": event.get("de_bracket", {}),
                "final_ranking": event.get("final_ranking", [])
            }

            # 기존 종목 조회
            try:
                result = supabase.table("events").select("id, raw_data").eq(
                    "competition_id", comp_id
                ).eq("sub_event_cd", sub_event_cd).execute()

                if result.data:
                    # 기존 종목 업데이트
                    event_id = result.data[0]["id"]
                    existing_raw = result.data[0].get("raw_data") or {}

                    # 기존 데이터와 병합 (새 데이터가 우선)
                    merged_raw = {**existing_raw, **raw_data}

                    supabase.table("events").update({
                        "raw_data": merged_raw
                    }).eq("id", event_id).execute()

                    de_count = len(raw_data.get("de_bracket", {}).get("bouts", []))
                    logger.debug(f"  종목 업데이트: {event_name} (DE: {de_count}개)")
                    stats["events_updated"] += 1
                else:
                    # 새 종목 생성
                    event_data = {
                        "competition_id": comp_id,
                        "event_cd": comp_idx,
                        "sub_event_cd": sub_event_cd,
                        "event_name": event_name,
                        "weapon": event.get("weapon"),
                        "gender": event.get("gender"),
                        "age_group": event.get("age_group"),
                        "raw_data": raw_data
                    }
                    supabase.table("events").insert(event_data).execute()
                    logger.debug(f"  새 종목 생성: {event_name}")
                    stats["events_created"] += 1

            except Exception as e:
                logger.error(f"종목 처리 오류 ({event_name}): {e}")
                stats["errors"] += 1

        logger.info(f"  {len(events)}개 종목 처리 완료")

    logger.info("=" * 50)
    logger.info("업로드 완료!")
    logger.info(f"  대회 업데이트: {stats['competitions_updated']}")
    logger.info(f"  종목 업데이트: {stats['events_updated']}")
    logger.info(f"  종목 생성: {stats['events_created']}")
    logger.info(f"  오류: {stats['errors']}")

    return stats["errors"] == 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python upload_rescrape_to_supabase.py <json_file>")
        print("Example: python upload_rescrape_to_supabase.py data/rescrape_2025.json")
        sys.exit(1)

    json_file = sys.argv[1]
    if not Path(json_file).exists():
        print(f"파일이 없습니다: {json_file}")
        sys.exit(1)

    success = upload_rescrape_data(json_file)
    sys.exit(0 if success else 1)
