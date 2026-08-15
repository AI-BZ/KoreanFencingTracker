#!/usr/bin/env python3
"""events.raw_data.pool_rounds 에 두 번씩 들어간 풀을 정리한다.

원인: KFA 경기결과 페이지에는 id="pouleAjax" 컨테이너가 두 개 있고 같은 풀 목록이
양쪽에 채워진다(두 번째는 '시간' 정보가 빠진 사본). 스크래퍼가 document 전체에서
풀 헤더를 찾는 바람에 모든 풀이 정확히 2번 저장됐다. 2025-01-11 대회부터 발생.

스크래퍼는 full_scraper.py 에서 첫 번째 컨테이너로 범위를 좁혀 고쳤고, 이 스크립트는
이미 저장된 데이터를 정리한다.

정리 규칙:
  - pool_number 로 묶는다.
  - 묶음 안의 results / bouts 가 서로 다르면 손대지 않고 보고만 한다.
    (같은 번호의 다른 풀일 수 있으므로 임의로 버리지 않는다 — 제1원칙)
  - 같으면 메타 정보(시간/삐스트/심판)가 가장 많이 채워진 항목 하나만 남긴다.

사용:
  python scripts/dedup_pool_rounds.py            # 검사만 (기본)
  python scripts/dedup_pool_rounds.py --apply    # 실제 반영
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
from supabase import create_client  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

META_FIELDS = ("time", "piste", "referee")


def substantive(pool: dict) -> str:
    """풀의 실질 데이터(명단·경기결과)만 뽑은 지문. 메타 정보는 제외한다."""
    return json.dumps(
        {"results": pool.get("results"), "bouts": pool.get("bouts")},
        sort_keys=True,
        ensure_ascii=False,
    )


def meta_score(pool: dict) -> int:
    return sum(1 for f in META_FIELDS if str(pool.get(f) or "").strip())


def dedup(pools: list) -> tuple:
    """(정리된 목록, 제거 수, 충돌 목록) 반환. 충돌이 있으면 원본을 그대로 돌려준다."""
    groups = defaultdict(list)
    for idx, p in enumerate(pools):
        groups[str(p.get("pool_number"))].append((idx, p))

    conflicts = []
    keep_idx = set()
    for num, items in groups.items():
        if len(items) == 1:
            keep_idx.add(items[0][0])
            continue
        sigs = {substantive(p) for _, p in items}
        if len(sigs) > 1:
            conflicts.append(num)
            for i, _ in items:
                keep_idx.add(i)
            continue
        best = max(items, key=lambda it: (meta_score(it[1]), -it[0]))
        keep_idx.add(best[0])

    if conflicts:
        return pools, 0, conflicts
    cleaned = [p for i, p in enumerate(pools) if i in keep_idx]
    return cleaned, len(pools) - len(cleaned), []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 DB에 반영")
    ap.add_argument("--limit", type=int, default=0, help="처리할 이벤트 수 제한 (테스트용)")
    args = ap.parse_args()

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    comps = {
        c["id"]: (c.get("comp_name"), str(c.get("start_date")))
        for c in (sb.table("competitions").select("id,comp_name,start_date").execute().data or [])
    }

    rows, off = [], 0
    while True:
        r = (
            sb.table("events")
            .select("id,sub_event_cd,event_name,competition_id,raw_data")
            .range(off, off + 199)
            .execute()
        )
        if not r.data:
            break
        rows += r.data
        off += 200
    print(f"전체 이벤트 {len(rows)}개 검사")

    targets, conflict_events = [], []
    for e in rows:
        raw = e.get("raw_data") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                continue
        pools = raw.get("pool_rounds") or []
        if not pools:
            continue
        nums = [str(p.get("pool_number")) for p in pools]
        if len(nums) == len(set(nums)):
            continue
        cleaned, removed, conflicts = dedup(pools)
        if conflicts:
            conflict_events.append((e, conflicts))
            continue
        targets.append((e, raw, cleaned, removed))

    if args.limit:
        targets = targets[: args.limit]

    total_removed = sum(t[3] for t in targets)
    print(f"정리 대상 {len(targets)}개 이벤트 / 제거될 풀 {total_removed}개")
    if conflict_events:
        print(f"\n⚠️  같은 번호인데 내용이 다른 이벤트 {len(conflict_events)}개 — 손대지 않음:")
        for e, c in conflict_events[:20]:
            nm, sd = comps.get(e["competition_id"], ("?", "?"))
            print(f"   {sd} {nm[:30]:<30} {e['sub_event_cd']} {e['event_name']} 풀번호 {c[:6]}")

    by_year = Counter(comps.get(t[0]["competition_id"], ("?", "?"))[1][:4] for t in targets)
    print(f"연도별 대상: {dict(sorted(by_year.items()))}")

    if not args.apply:
        print("\n검사만 수행했다. 반영하려면 --apply 를 붙여라.")
        return

    done = 0
    for e, raw, cleaned, removed in targets:
        raw["pool_rounds"] = cleaned
        sb.table("events").update({"raw_data": raw}).eq("id", e["id"]).execute()
        done += 1
        if done % 50 == 0:
            print(f"  {done}/{len(targets)} 반영")
    print(f"완료: {done}개 이벤트, 풀 {total_removed}개 제거")


if __name__ == "__main__":
    main()
