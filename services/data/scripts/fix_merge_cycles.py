#!/usr/bin/env python3
"""`players.merged_into` 가 서로를 가리키는 상호 순환(A↔B)을 푼다.

문제 (2026-09-29 전수 조회): 62쌍 124행이 서로를 "나는 저쪽으로 병합됐다"고 가리킨다.
병합 절차(`data_pipeline/sync.py`)는 source 에만 `merged_into`·`is_active=False` 를
남기도록 돼 있는데, 두 방향으로 두 번 실행되면서 **정본이 없는 상태**가 됐다.
`merged_into IS NULL` 로 거르는 모든 조회(FIE·아시안게임 선수 매칭,
`scheduler/player_data_updater`)에서 **두 행이 모두 빠진다** — 그 선수는 어디에도 없다.

판정 기준: 이 이름이 **한 사람인지 두 사람인지는 선수 식별기(PlayerIdentityResolver)가
정한다.** 사이트의 선수 정체성은 그 엔진이 결정하고, 협회 표 대조(2026-09-28, NT 97.6%)
로 검증된 기준이다. `players` 행의 소속을 프로필의 소속 이력과 맞춰 본다.

  ① 한 프로필이 두 소속을 모두 갖고 있다 → 같은 사람. 정본 하나를 정하고 나머지를
     그쪽으로 병합한다(기록도 정본으로 옮긴다 — 병합 절차와 같은 순서).
     정본 선택: 프로필의 현재 소속과 일치하는 쪽 > is_active > 기록 많은 쪽 > 큰 id.
  ② 프로필이 갈려 있다 → 다른 사람. 병합 자체가 잘못이므로 **양쪽 모두 해제**한다
     (merged_into=NULL, is_active=True). 이미 옮겨진 경기 기록은 되돌리지 않는다 —
     어느 기록이 누구 것인지 이 테이블만으로는 알 수 없다. 로그에 남겨 사람이 본다.
  ③ 소속을 프로필에서 못 찾는다 → 판정 보류. 건드리지 않고 목록만 남긴다.

사용:
  PYTHONPATH=".:../../packages" python3 scripts/fix_merge_cycles.py --dry-run
  PYTHONPATH=".:../../packages" python3 scripts/fix_merge_cycles.py
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(HERE), ".env"))

from loguru import logger
from supabase import create_client

from app.player_identity import PlayerIdentityResolver, canonical_team_name

LOG_PATH = os.path.join(os.path.dirname(HERE), "logs", "fix_merge_cycles.jsonl")
RECORD_TABLES = [("matches", "player1_id"), ("matches", "player2_id"),
                 ("matches", "winner_id"), ("rankings", "player_id"),
                 ("members", "player_id")]


def load_players(db):
    rows, off = [], 0
    while True:
        page = (db.table("players")
                .select("id,player_name,team_name,merged_into,is_active,updated_at")
                .range(off, off + 999).execute().data or [])
        rows += page
        off += 1000
        if len(page) < 1000:
            break
    return rows


def build_resolver(db):
    sys.path.insert(0, HERE)
    import run_validation as rv
    events, comps, _orgs = rv.load_raw(None)
    competitions = rv.build_competitions(events, comps, None)
    r = PlayerIdentityResolver()
    for c in competitions:
        r.add_competition_data(c)
    r.resolve_identities()
    return r


def record_count(db, pid):
    total = 0
    for table, field in RECORD_TABLES:
        try:
            res = db.table(table).select("id", count="exact").eq(field, pid).execute()
            total += res.count or 0
        except Exception:
            pass
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    players = load_players(db)
    by_id = {p["id"]: p for p in players}
    pairs = [(p, by_id[p["merged_into"]]) for p in players
             if p.get("merged_into") in by_id
             and by_id[p["merged_into"]].get("merged_into") == p["id"]
             and p["id"] < p["merged_into"]]
    logger.info(f"상호 순환 {len(pairs)}쌍 (행 {len(pairs) * 2}개)")

    resolver = build_resolver(db)
    stats = {"같은사람": 0, "다른사람": 0, "보류": 0}

    for a, b in pairs:
        name = a["player_name"]
        ta, tb = canonical_team_name(a.get("team_name") or ""), canonical_team_name(b.get("team_name") or "")
        profiles = [resolver.profiles[pid] for pid in resolver.name_to_profiles.get(name, [])]
        pa = {p.player_id for p in profiles if any(canonical_team_name(t) == ta for t in p.teams)}
        pb = {p.player_id for p in profiles if any(canonical_team_name(t) == tb for t in p.teams)}
        entry = {"name": name, "a": a["id"], "b": b["id"], "team_a": a.get("team_name"),
                 "team_b": b.get("team_name"), "at": datetime.now(timezone.utc).isoformat()}

        if not pa or not pb:
            stats["보류"] += 1
            entry.update(verdict="보류", reason="소속을 프로필에서 못 찾음")
            logger.warning(f"⏭ {name}: 보류 ({a.get('team_name')} / {b.get('team_name')})")
        elif pa & pb:
            shared = sorted(pa & pb)[0]
            profile = resolver.profiles[shared]
            current = canonical_team_name(profile.current_team or "")
            ra, rb = record_count(db, a["id"]), record_count(db, b["id"])
            def score(row, team, rec):
                return (team == current, bool(row.get("is_active")), rec, row["id"])
            keep, drop = (a, b) if score(a, ta, ra) > score(b, tb, rb) else (b, a)
            stats["같은사람"] += 1
            entry.update(verdict="같은사람", profile=shared, keep=keep["id"], drop=drop["id"],
                         records={"a": ra, "b": rb}, current_team=profile.current_team)
            logger.info(f"✅ {name}: 정본 {keep['id']}({keep.get('team_name')}) "
                        f"← {drop['id']}({drop.get('team_name')}) 병합"
                        f"{' (dry-run)' if args.dry_run else ''}")
            if not args.dry_run:
                moved = {}
                for table, field in RECORD_TABLES:
                    try:
                        res = db.table(table).update({field: keep["id"]}).eq(field, drop["id"]).execute()
                        if res.data:
                            moved[f"{table}.{field}"] = len(res.data)
                    except Exception as e:
                        logger.warning(f"   기록 이전 실패 {table}.{field}: {str(e)[:80]}")
                entry["moved"] = moved
                db.table("players").update({"merged_into": None, "is_active": True}).eq("id", keep["id"]).execute()
                db.table("players").update({"merged_into": keep["id"], "is_active": False}).eq("id", drop["id"]).execute()
        else:
            stats["다른사람"] += 1
            entry.update(verdict="다른사람", profiles={"a": sorted(pa), "b": sorted(pb)})
            logger.info(f"🔀 {name}: 다른 사람 → 양쪽 병합 해제 "
                        f"({a.get('team_name')} / {b.get('team_name')})"
                        f"{' (dry-run)' if args.dry_run else ''}")
            if not args.dry_run:
                for row in (a, b):
                    db.table("players").update({"merged_into": None, "is_active": True}).eq("id", row["id"]).execute()

        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.info(f"결과: {stats}")


if __name__ == "__main__":
    main()
