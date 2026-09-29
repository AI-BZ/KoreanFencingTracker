"""DE 대진 개정 이력의 기준선(1차)을 채운다.

data_de_revisions 는 2026-08-29 에 도입됐다. 그 전의 대진 변경은 어디에도 기록되지
않았으므로(events.raw_data 덮어쓰기) 복원할 수 없다. 이 스크립트는 '지금 시점의
대진'을 1차 개정으로 남겨 기준선을 만든다. source='backfill' 로 표시되므로 UI 는
이것이 '최초 게시'가 아니라 '우리가 처음 관측한 시점'임을 밝힐 수 있다.

사용법:
    cd services/data
    PYTHONPATH=".:../../packages" python scripts/backfill_de_revisions.py --dry-run
    PYTHONPATH=".:../../packages" python scripts/backfill_de_revisions.py --since 2026-08-01
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from loguru import logger
from supabase import create_client

from app.de_revisions import record_revision, fingerprint


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="이 날짜 이후 시작한 대회만 (YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    q = db.table("competitions").select("id, comp_name, start_date")
    if args.since:
        q = q.gte("start_date", args.since)
    comps = {c["id"]: c for c in (q.execute().data or [])}
    if not comps:
        logger.warning("대상 대회 없음")
        return

    existing = set()
    page, size = 0, 1000
    while True:
        res = (db.table("data_de_revisions").select("sub_event_cd")
               .range(page * size, page * size + size - 1).execute())
        rows = res.data or []
        existing.update(r["sub_event_cd"] for r in rows)
        if len(rows) < size:
            break
        page += 1

    recorded = skipped = empty = 0
    for comp_id, comp in sorted(comps.items(), key=lambda kv: kv[1]["start_date"] or ""):
        events = (db.table("events").select("id, sub_event_cd, event_name, raw_data")
                  .eq("competition_id", comp_id).execute().data or [])
        for ev in events:
            sub_cd = ev["sub_event_cd"]
            if sub_cd in existing:
                skipped += 1
                continue
            raw = ev.get("raw_data") or {}
            if isinstance(raw, str):
                raw = json.loads(raw)
            de = raw.get("de_bracket") or {}
            if not de.get("full_bouts"):
                empty += 1
                continue

            if args.dry_run:
                _, _, n_p, n_b, _ = fingerprint(de)
                logger.info(f"[dry-run] {comp['comp_name'][:26]} / {ev['event_name']}: "
                            f"{n_p}명 {n_b}경기")
                recorded += 1
                continue

            if record_revision(
                db, sub_event_cd=sub_cd, de_bracket=de,
                event_id=ev["id"], competition_id=comp_id,
                source="backfill",
                note="도입 시점 스냅샷 — 이전 대진 변경 이력은 남아 있지 않음",
            ):
                recorded += 1

    logger.info(f"완료: 기록 {recorded}건 / 기존 보유 {skipped}건 / DE 없음 {empty}건")


if __name__ == "__main__":
    main()
