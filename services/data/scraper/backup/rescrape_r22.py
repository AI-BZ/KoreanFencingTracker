"""2건 R22 이벤트 재스크래핑 (pool_rounds 수집)

R22 검증에서 pool_total_ranking은 있으나 pool_rounds가 0인 이벤트 재수집.
사용 후 삭제.
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from supabase import create_client

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# Target events (R22 hits)
TARGETS = [
    {
        "event_id": 2533,
        "event_cd": "COMPM00654",
        "sub_event_cd": "COMPS000000000003557",
        "name": "제65회 대통령배 남자 에뻬(개)",
    },
    {
        "event_id": 327,
        "event_cd": "COMPM00633",
        "sub_event_cd": "COMPS000000000003401",
        "name": "2025 국대선발 남자 에뻬(개)",
    },
]


async def rescrape():
    from scraper.full_scraper import KFFFullScraper

    async with KFFFullScraper(headless=True) as scraper:
        # Find page_num for each competition
        print("KFF 대회 목록 탐색 중...")
        all_comps = await scraper.get_all_competitions()
        print(f"  총 {len(all_comps)}개 대회 발견")

        comp_page_map = {comp.event_cd: comp.page_num for comp in all_comps}

        for target in TARGETS:
            ecd = target["event_cd"]
            sub = target["sub_event_cd"]
            eid = target["event_id"]
            name = target["name"]

            page_num = comp_page_map.get(ecd)
            if page_num is None:
                print(f"\n❌ {name}: event_cd={ecd} not found in KFF listings")
                continue

            print(f"\n{'='*60}")
            print(f"재스크래핑: {name}")
            print(f"  event_cd={ecd}, sub={sub}, page={page_num}")
            print(f"{'='*60}")

            t0 = time.time()
            results = await scraper.get_full_results(ecd, sub, page_num=page_num)
            elapsed = time.time() - t0

            pool_rounds = results.get("pool_rounds", [])
            pool_diag = results.get("_pool_diagnostics", {})
            scrape_warnings = results.get("_scrape_warnings", [])
            duration_ms = results.get("_duration_ms", 0)

            print(f"  pool_rounds: {len(pool_rounds)}개 풀")
            print(f"  pool_diagnostics: {json.dumps(pool_diag, ensure_ascii=False)}")
            print(f"  scrape_warnings: {len(scrape_warnings)}건")
            for w in scrape_warnings:
                print(f"    [{w['severity']}] {w['message']}")
            print(f"  소요 시간: {elapsed:.1f}s ({duration_ms}ms)")

            # Load existing raw_data
            existing = sb.table("events").select("raw_data").eq("id", eid).execute()
            if not existing.data:
                print(f"  ❌ event_id={eid} not found in DB")
                continue

            raw_data = existing.data[0].get("raw_data", {})
            if isinstance(raw_data, str):
                raw_data = json.loads(raw_data)

            metadata = {
                "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "scraper_version": "3.1",
                "pool_diagnostics": pool_diag,
                "scrape_warnings": scrape_warnings,
                "duration_ms": duration_ms,
                "rescrape_reason": "R22_pool_rounds_missing",
            }

            if len(pool_rounds) > 0:
                raw_data["pool_rounds"] = pool_rounds
                metadata["rescrape_result"] = f"success_{len(pool_rounds)}_pools"
            else:
                metadata["rescrape_result"] = "still_empty"

            raw_data["_scrape_metadata"] = metadata

            sb.table("events").update({
                "raw_data": raw_data,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }).eq("id", eid).execute()

            if len(pool_rounds) > 0:
                print(f"  ✅ DB 업데이트 완료: event_id={eid}, pool_rounds={len(pool_rounds)}개 풀")
            else:
                print(f"  ⚠️ pool_rounds 여전히 0 — 진단 데이터 저장 완료")


if __name__ == "__main__":
    asyncio.run(rescrape())
