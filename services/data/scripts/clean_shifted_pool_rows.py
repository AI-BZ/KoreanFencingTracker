#!/usr/bin/env python3
"""풀 결과의 '열이 밀린 중복 행'을 제거한다.

실측 (2026-09-30 전수): `name` 이 숫자인 행이 1,929건 있다. 예 —
    {'position': 3, 'name': '1',      'team': '김경무',        'wins': 4, 'losses': 1, 'rank': 1}
    {'position': 1, 'name': '김경무', 'team': '대구대학교',     'wins': 4, 'losses': 1, 'rank': 1}
앞 행은 협회 표의 첫 칸(순번)이 이름 칸으로 밀려 들어간 **같은 선수의 중복 행**이다.
`services/data/CLAUDE.md` 의 풀 필터에도 같은 사고가 기록돼 있다("position이 이름으로 파싱").

이 행이 남아 있으면 '1' 이라는 가짜 선수가 생겨 성별·나이그룹 검증(R10/R11)에 걸리고,
풀 인원 집계도 부풀린다.

삭제 조건 (셋 다 만족할 때만 — 지어내지 않는다):
  1. `name` 이 숫자만으로 이루어져 있다
  2. 같은 풀 안에 `name == 그 행의 team` 인 정상 행이 있다 (진짜 선수가 따로 있다)
  3. 그 정상 행과 승/패가 같다 (같은 사람의 복제본임을 확인)

사용:
  PYTHONPATH=".:../../packages" python3 scripts/clean_shifted_pool_rows.py --dry-run
  PYTHONPATH=".:../../packages" python3 scripts/clean_shifted_pool_rows.py
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(HERE), ".env"))

from loguru import logger
from supabase import create_client

LOG_PATH = os.path.join(os.path.dirname(HERE), "logs", "clean_shifted_pool_rows.jsonl")


def classify(row, pool_rows):
    """숫자 이름 행의 처리 방법. (동작, 설명) 또는 None.

    실측한 두 형태 (2026-09-30):
      ① 같은 풀에 `name == 이 행의 team` 인 정상 행이 있다
         → 협회 표 첫 칸(순번)이 이름 칸으로 밀려 들어온 **중복 행**이다. 삭제한다.
         예) {'name':'1','team':'김경무'} 와 {'name':'김경무','team':'대구대학교'} 가 함께 있다.
      ② 정상 행이 없다 → 그 선수는 이 풀에 **이 행으로만** 존재한다. 지우면 선수가 사라진다.
         이름 칸을 되돌리고(team → name) 소속은 같은 종목의 순위표에서 찾아 채운다.
         못 찾으면 비워 둔다 — 지어내지 않는다.
    """
    name = (row.get("name") or "").strip()
    team = (row.get("team") or "").strip()
    if not name.isdigit() or not team:
        return None
    for other in pool_rows:
        if other is not row and (other.get("name") or "").strip() == team:
            return ("delete", f"'{name}'/{team} — 같은 풀에 정상 행({other.get('name')}/{other.get('team')}) 있음")
    return ("unshift", f"'{name}'/{team} — 정상 행 없음 → 이름 복원")


def team_lookup(rd):
    """이 종목의 순위표에서 이름 → 소속."""
    out = {}
    for src in ("pool_total_ranking", "final_rankings"):
        for r in (rd.get(src) or []):
            if isinstance(r, dict):
                nm = (r.get("name") or "").strip()
                tm = (r.get("team") or "").strip()
                if nm and tm and not nm.isdigit():
                    out.setdefault(nm, tm)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    rows, off = [], 0
    while True:
        page = (db.table("events").select("id,sub_event_cd,event_name,raw_data")
                .range(off, off + 199).execute().data or [])
        rows += page
        off += 200
        if len(page) < 200:
            break

    stats = Counter()
    for ev in rows:
        rd = ev.get("raw_data") or {}
        changed, removed = False, []
        lookup = team_lookup(rd)
        for pool in (rd.get("pool_rounds") or []):
            results = pool.get("results") or []
            keep = []
            for row in results:
                verdict = classify(row, results) if isinstance(row, dict) else None
                if not verdict:
                    keep.append(row)
                    continue
                action, reason = verdict
                changed = True
                if action == "delete":
                    removed.append("삭제 " + reason)
                else:
                    real_name = (row.get("team") or "").strip()
                    row["name"] = real_name
                    row["team"] = lookup.get(real_name, "")
                    removed.append(f"복원 {reason} → 소속 '{row['team'] or '(미상)'}'")
                    keep.append(row)
            pool["results"] = keep
        # 풀 종합 순위에도 같은 행이 있으면 함께 지운다
        ptr = rd.get("pool_total_ranking") or []
        if ptr:
            keep_ptr = [r for r in ptr
                        if not (isinstance(r, dict) and (r.get("name") or "").strip().isdigit())]
            if len(keep_ptr) != len(ptr):
                removed.append(f"pool_total_ranking {len(ptr) - len(keep_ptr)}행")
                rd["pool_total_ranking"] = keep_ptr
                changed = True

        if changed:
            stats["events"] += 1
            stats["rows"] += len(removed)
            logger.info(f"{'(dry-run) ' if args.dry_run else ''}✅ {ev['event_name']}: {len(removed)}행 제거")
            if not args.dry_run:
                db.table("events").update({"raw_data": rd}).eq("id", ev["id"]).execute()
            os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps({"sub": ev["sub_event_cd"], "event": ev["event_name"],
                                    "removed": removed[:20], "count": len(removed),
                                    "dry_run": args.dry_run,
                                    "at": datetime.now(timezone.utc).isoformat()},
                                   ensure_ascii=False) + "\n")
    logger.info(f"결과: 종목 {stats['events']}개 / 행 {stats['rows']}건")


if __name__ == "__main__":
    main()
