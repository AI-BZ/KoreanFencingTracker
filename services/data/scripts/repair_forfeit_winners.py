"""기권승 승자 누락 종목을 재수집해 교정한다.

배경: `_apply_forfeit_notes()` 가 기권을 표시하면서 승자를 채우지 않아
`is_forfeit=true` 인데 `winner_name` 이 빈 경기가 남았다. 예선 마지막 라운드에서
그런 경기가 나오면 그 선수가 진출자 명단에서 빠지고, 시드는 '본선 시딩 − 진출자'로
구하므로 시드/진출자 수가 어긋난다(2026-08-28 김창환배 남자 사브르 33/31).
스크래퍼는 2026-09-10 에 고쳤고, 이 스크립트는 그 전에 저장된 데이터를 다시 받아온다.

안전 장치 — 아래를 모두 통과할 때만 쓴다(하나라도 어긋나면 건너뛰고 기록):
  ① `_de_bracket_regression()` 가 거부하지 않을 것
  ② 경기 수가 줄지 않을 것
  ③ 점수 입력된 경기 수가 줄지 않을 것
  ④ 기권-승자없음 경기가 줄어들 것 (이 작업의 목적)
풀 데이터는 건드리지 않는다 — KFA 는 본선 미진출자를 지우므로 기존이 더 완전하다.

재개 가능: 대상 목록을 매번 DB 에서 다시 구하므로, 고쳐진 종목은 자동으로 빠진다.

사용법:
    cd services/data
    PYTHONPATH=".:../../packages" python scripts/repair_forfeit_winners.py --dry-run
    PYTHONPATH=".:../../packages" python scripts/repair_forfeit_winners.py --limit 8
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from loguru import logger
from supabase import create_client

from scraper.full_scraper import KFFFullScraper
from scheduler.competition_detector import (
    _de_bracket_regression, _de_scored_bout_count, _de_bout_identities,
)
from app.de_revisions import record_revision as record_de_revision

PROGRESS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "logs", "repair_forfeit_winners.jsonl")

# 대회 목록은 페이지네이션돼 있고, get_full_results 는 기본값 page_num=1 만 본다.
# 오래된 대회는 뒤 페이지에 있어 "링크를 못 찾음 → 5초 타임아웃 → 빈 DE" 로 끝난다.
# (실측: 제65회 대통령배 COMPM00654 가 그렇게 실패했다. 2026-09-21)
# 그래서 대회마다 실제 페이지 번호를 한 번 찾아 두고 재사용한다.
MAX_LIST_PAGES = 40


async def find_page_num(scraper, comp_idx: str):
    """대회 목록에서 이 대회가 있는 페이지 번호. 못 찾으면 None."""
    page = await scraper._browser.new_page()
    page.set_default_timeout(15000)
    try:
        await page.goto(f"{scraper.BASE_URL}/game/compList?code=game",
                        wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(800)
        for n in range(1, MAX_LIST_PAGES + 1):
            if await page.locator(f'a[onclick*="{comp_idx}"]').count() > 0:
                return n
            nxt = page.locator("a:has-text('다음페이지')")
            try:
                if not await nxt.is_visible():
                    return None
                await nxt.click(timeout=3000)
                await page.wait_for_timeout(900)
            except Exception:
                return None
        return None
    finally:
        await page.close()


def bad_bout_count(de_bracket) -> int:
    """기권인데 승자가 비어 있는 경기 수."""
    if not isinstance(de_bracket, dict):
        return 0
    n = 0
    for b in de_bracket.get("full_bouts") or []:
        if not isinstance(b, dict):
            continue
        if b.get("is_forfeit") and not str(b.get("winner_name") or "").strip() \
                and not b.get("is_bye"):
            n += 1
    return n


def find_targets(db):
    """교정 대상 종목 목록. 매 실행마다 새로 구해 재개를 자동으로 만든다."""
    targets = []
    page, size = 0, 500
    while True:
        rows = (db.table("events").select("id, competition_id, sub_event_cd, event_name, raw_data")
                .range(page * size, page * size + size - 1).execute().data or [])
        for ev in rows:
            raw = ev.get("raw_data") or {}
            if isinstance(raw, str):
                raw = json.loads(raw)
            de = raw.get("de_bracket") or {}
            n = bad_bout_count(de)
            if n:
                targets.append({
                    "id": ev["id"], "competition_id": ev["competition_id"],
                    "sub_event_cd": ev["sub_event_cd"], "event_name": ev["event_name"],
                    "bad": n,
                })
        if len(rows) < size:
            break
        page += 1
    return targets


def log_progress(entry: dict):
    os.makedirs(os.path.dirname(PROGRESS), exist_ok=True)
    entry["at"] = datetime.now().isoformat(timespec="seconds")
    with open(PROGRESS, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=8, help="이번 실행에서 처리할 종목 수")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    targets = find_targets(db)
    logger.info(f"남은 교정 대상: {len(targets)}종목 / {sum(t['bad'] for t in targets)}경기")
    if not targets:
        logger.info("완료 — 대상 없음")
        return

    comp_idx = {}
    for cid in {t["competition_id"] for t in targets}:
        r = db.table("competitions").select("comp_idx, comp_name").eq("id", cid).execute().data
        if r:
            comp_idx[cid] = (r[0]["comp_idx"], r[0]["comp_name"])

    # 같은 대회의 종목끼리 묶어 처리 — 페이지 탐색을 대회당 1회로 줄인다
    targets.sort(key=lambda t: (t["competition_id"], t["event_name"]))

    batch = targets[:args.limit]
    if args.dry_run:
        for t in batch:
            ci = comp_idx.get(t["competition_id"], ("?", "?"))
            logger.info(f"[dry-run] {ci[1][:24]} / {t['event_name']} — 기권-승자없음 {t['bad']}건")
        return

    fixed = skipped = failed = 0
    page_cache = {}
    async with KFFFullScraper(headless=True) as s:      # 브라우저 1개 재사용
        for t in batch:
            ci = comp_idx.get(t["competition_id"])
            if not ci:
                logger.warning(f"대회 정보 없음: {t['sub_event_cd']}")
                failed += 1
                continue
            ev_cd, comp_name = ci
            tag = f"{comp_name[:22]} / {t['event_name']}"

            if ev_cd not in page_cache:
                page_cache[ev_cd] = await find_page_num(s, ev_cd)
                logger.info(f"   대회 목록 페이지: {ev_cd} → {page_cache[ev_cd]}")
            pnum = page_cache[ev_cd]
            if pnum is None:
                logger.warning(f"⏭ 대회 목록에서 못 찾음 {tag} → 건너뜀")
                log_progress({"sub": t["sub_event_cd"], "tag": tag, "result": "comp_not_listed"})
                skipped += 1
                continue

            try:
                res = await s.get_full_results(ev_cd, t["sub_event_cd"], page_num=pnum)
            except Exception as e:
                logger.warning(f"❌ 스크랩 실패 {tag}: {e}")
                log_progress({"sub": t["sub_event_cd"], "tag": tag, "result": "scrape_failed",
                              "error": str(e)[:200]})
                failed += 1
                continue

            new_de = res.get("de_bracket") or {}
            if not new_de.get("full_bouts"):
                logger.warning(f"⏭ DE 비어 있음 {tag} → 건너뜀")
                log_progress({"sub": t["sub_event_cd"], "tag": tag, "result": "empty_de"})
                skipped += 1
                continue

            row = db.table("events").select("raw_data").eq("id", t["id"]).execute().data[0]
            raw = row["raw_data"]
            if isinstance(raw, str):
                raw = json.loads(raw)
            old_de = raw.get("de_bracket") or {}

            o_b, n_b = len(_de_bout_identities(old_de)), len(_de_bout_identities(new_de))
            o_s, n_s = _de_scored_bout_count(old_de), _de_scored_bout_count(new_de)
            o_bad, n_bad = bad_bout_count(old_de), bad_bout_count(new_de)

            reason = None
            reg = _de_bracket_regression(new_de, old_de)
            if reg:
                reason = f"가드 거부: {reg[:120]}"
            elif n_b < o_b:
                reason = f"경기 감소 {o_b}→{n_b}"
            elif n_s < o_s:
                reason = f"점수 감소 {o_s}→{n_s}"
            elif n_bad >= o_bad:
                reason = f"기권-승자없음 개선 없음 {o_bad}→{n_bad}"

            if reason:
                logger.warning(f"⏭ {tag} → 쓰지 않음 ({reason})")
                log_progress({"sub": t["sub_event_cd"], "tag": tag, "result": "skipped",
                              "reason": reason, "bouts": [o_b, n_b], "scored": [o_s, n_s],
                              "bad": [o_bad, n_bad]})
                skipped += 1
                continue

            raw["de_bracket"] = new_de
            if res.get("de_matches"):
                raw["de_matches"] = res["de_matches"]
            db.table("events").update({"raw_data": raw}).eq("id", t["id"]).execute()
            record_de_revision(
                db, sub_event_cd=t["sub_event_cd"], de_bracket=new_de,
                event_id=t["id"], competition_id=t["competition_id"],
                previous_de_bracket=old_de, source="repair",
                note="기권승 승자 누락 교정 재수집 (2026-09)",
            )
            logger.info(f"✅ {tag}: 기권-승자없음 {o_bad}→{n_bad}, "
                        f"경기 {o_b}→{n_b}, 점수 {o_s}→{n_s}")
            log_progress({"sub": t["sub_event_cd"], "tag": tag, "result": "fixed",
                          "bouts": [o_b, n_b], "scored": [o_s, n_s], "bad": [o_bad, n_bad]})
            fixed += 1

    logger.info(f"이번 배치: 교정 {fixed} / 건너뜀 {skipped} / 실패 {failed} "
                f"(남은 대상 {len(targets) - fixed})")


if __name__ == "__main__":
    asyncio.run(main())
