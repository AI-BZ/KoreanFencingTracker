#!/usr/bin/env python3
"""저장된 final_rankings 에 1위가 없는 종목을 우리 DE 데이터로 재계산해 채운다.

배경 (2026-09-27 감사):
  단체전 일부(2025년 체전·소년체전·문체부장관기 등 40종목)는 협회가 **최종순위 표를
  게시하지 않는다**(라이브 확인: final 0행). 그래서 우리가 `compute_full_final_rankings()`
  로 계산해 저장했는데, 저장 시점에는 결승 승자가 비어 있어서 **1위 행이 없는 표**(2위부터
  시작)가 그대로 남았다. 그 뒤 DE 재수집으로 결승 점수·승자가 채워졌으므로 지금 다시
  계산하면 1위가 들어온다.

  `app/server.py` 는 표시 시점에 "1위로 시작하지 않으면 재계산"하는 우회가 있어 화면은
  맞게 나왔지만, DB·API·랭킹 계산이 읽는 저장값은 여전히 깨져 있었다. 화면 우회로 DB
  오류를 덮지 않는다(제1원칙).

안전 규칙:
  - 협회 표가 존재하는 종목(`final_rankings_source == 'kfa'`)은 건드리지 않는다.
  - 재계산 결과가 ① 1위를 포함하고 ② 기존 표의 이름을 모두 담고 ③ 행 수가 줄지 않을 때만 저장.
  - 저장 시 `final_rankings_source='computed'` 를 명시한다(협회 표와 구분 — CLAUDE.md 규칙).
  - 기존 표는 로그에 남긴다(logs/repair_computed_team_finals.jsonl).

사용:
  PYTHONPATH=".:../../packages" python3 scripts/repair_computed_team_finals.py --dry-run
  PYTHONPATH=".:../../packages" python3 scripts/repair_computed_team_finals.py
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from loguru import logger
from supabase import create_client

from app.bracket_utils import compute_full_final_rankings, get_canonical_bouts

LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "logs", "repair_computed_team_finals.jsonl")


def ranks_of(final):
    return [r.get("rank") for r in final or [] if isinstance(r.get("rank"), int)]


def names_of(final):
    return {(r.get("name") or "").strip() for r in final or [] if (r.get("name") or "").strip()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    comps = {c["id"]: c for c in db.table("competitions")
             .select("id,comp_idx,comp_name,start_date").execute().data}

    rows, off = [], 0
    while True:
        page = (db.table("events").select("id,competition_id,sub_event_cd,event_name,raw_data")
                .range(off, off + 199).execute().data or [])
        rows += page
        off += 200
        if len(page) < 200:
            break
    logger.info(f"이벤트 {len(rows)}개 조회")

    stats = Counter()
    for ev in rows:
        rd = ev.get("raw_data") or {}
        old = rd.get("final_rankings") or []
        if not old or 1 in ranks_of(old):
            continue
        if (rd.get("final_rankings_source") or "").lower() == "kfa":
            stats["skip_kfa_source"] += 1
            continue
        de = rd.get("de_bracket") or {}
        pool_total = rd.get("pool_total_ranking") or []
        comp = comps.get(ev["competition_id"]) or {}
        tag = (f"{(comp.get('start_date') or '')[:4]} {comp.get('comp_name', '')[:24]} "
               f"/ {ev['event_name']}")

        # 1위는 **실제 결승 승자**여야 한다. DE 가 없으면 compute 는 풀 순위를 그대로
        # 최종순위로 돌려주는데(폴백), 그건 우승을 지어내는 것이므로 받지 않는다.
        # bout 은 스크래퍼 경로에 따라 full_bouts / bouts / bouts_by_round 중 어디에든 있다.
        # bout 은 `get_canonical_bouts()` 로만 읽는다(키를 더하면 이중집계된다).
        de_bouts = get_canonical_bouts(de)
        champs = {(b.get("winner_name") or "").strip()
                  for b in de_bouts
                  if b.get("round_name") in ("결승", "우승") and (b.get("winner_name") or "").strip()}

        new = compute_full_final_rankings(de, pool_total)
        reason = None
        if not new:
            reason = "재계산 결과 없음"
        elif not champs:
            reason = f"결승 승자 없음 (DE bout {len(de_bouts)}개) — 재수집 대상"
        elif 1 not in ranks_of(new):
            reason = "재계산에도 1위 없음 (결승 승자 미확정)"
        elif next(r["name"] for r in new if r.get("rank") == 1) not in champs:
            reason = f"1위가 결승 승자와 불일치 (계산 {next(r['name'] for r in new if r.get('rank') == 1)} vs 결승 {sorted(champs)})"
        elif not names_of(old) <= names_of(new):
            missing = sorted(names_of(old) - names_of(new))[:4]
            reason = f"기존 이름 누락 {missing}"
        elif len(new) < len(old):
            reason = f"행 수 감소 {len(old)}→{len(new)}"
        if reason:
            stats["skipped"] += 1
            logger.warning(f"⏭ {tag}: {reason}")
            entry = {"sub": ev["sub_event_cd"], "tag": tag, "result": "skipped", "reason": reason,
                     "old_rows": len(old), "at": datetime.now(timezone.utc).isoformat()}
        else:
            champ = next(r["name"] for r in new if r.get("rank") == 1)
            logger.info(f"✅ {tag}: {len(old)}행 → {len(new)}행, 1위 {champ}"
                        f"{' (dry-run)' if args.dry_run else ''}")
            entry = {"sub": ev["sub_event_cd"], "tag": tag,
                     "result": "dry_run" if args.dry_run else "fixed",
                     "old_rows": len(old), "new_rows": len(new), "champion": champ,
                     "old_final": old, "at": datetime.now(timezone.utc).isoformat()}
            if not args.dry_run:
                rd["final_rankings"] = new
                rd["final_rankings_source"] = "computed"
                db.table("events").update({"raw_data": rd}).eq("id", ev["id"]).execute()
            stats["dry_run" if args.dry_run else "fixed"] += 1

        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        if args.limit and sum(stats.values()) >= args.limit:
            break

    logger.info(f"결과: {dict(stats)}")


if __name__ == "__main__":
    main()
