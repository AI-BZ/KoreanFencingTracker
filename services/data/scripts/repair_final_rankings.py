"""final_rankings 오염 종목을 협회 원본으로 재수집해 복구한다 (재개 가능).

대상은 `scripts/audit_final_rankings.audit_event()` 가 매 실행 시 DB 에서 다시 판정한다
(F01~F06, F08~F10, F12 중 하나라도 있는 종목). 그래서 고쳐진 종목은 자동으로 빠지고,
처리 이력은 `logs/repair_final_rankings.jsonl` 에 남아 같은 종목을 두 번 긁지 않는다.

배경: 국가대표 선발 대회(Dual DE)의 final_rankings 가 예선 브래킷 기준으로 계산돼
저장된 사례(2021~2025 전 대회), 우승자 행이 빠진 순위표(1위 없음, 최대 순위 = 인원+1),
풀·최종순위 결손(2025 김창환배) 등. 상세 판정 기준은 audit 스크립트 docstring 참조.

안전조건 — 아래를 전부 통과할 때만 final_rankings 를 교체한다 (하나라도 어긋나면 기록만):
  ① LIVE 가 비어있지 않고 스스로 건전할 것: 1위 정확히 1명, (2명 이상이면) 2위 정확히 1명,
     동률 한도(3위≤2, 5위≤4, 9위≤8, 17위≤16, 33위≤32) 안, 최대 순위 ≤ 인원, 깨진 항목 0
     — 단체전도 같은 규칙(협회 단체 순위표도 1·2·3·3 구조). 1명짜리 표는 1위 검사만.
  ② LIVE 인원 ≥ DB 인원의 90%
  ③ DB 이름 집합과 LIVE 이름 집합의 겹침 ≥ 80% (DB 가 비어 있으면 생략)
  ④ 결승에 점수가 있으면(LIVE DE 우선, 없으면 DB DE) 그 승자 = LIVE 1위
DE 교체는 별도 조건: `_de_bracket_regression` 통과 + 경기 수·점수 수 비감소 + LIVE 가 실제로
더 나을 것(경기·점수가 늘거나, 없던 `de_phase` 가 붙음) → `de_revisions` 에 source="repair" 기록.
풀 교체는 DB 풀이 비었거나 (LIVE 고유 풀 수 ≥ DB **그리고** LIVE 선수 항목 수 ≥ DB, 둘 중
하나는 더 큼) 일 때, 또는 DB 풀이 오염(팬텀 풀/동일 풀 중복, `audit.pool_health`)됐고 LIVE 가
건전하며 고유 선수를 DB 의 90% 이상 담을 때만 — KFA 는 풀 종료 후 미진출자를 지우므로 풀 수가 같아도 사람이
줄어 있을 수 있다 → `pool_revisions` 에 기록. 풀이 있는데 pool_total_ranking 이 비어 있으면
스케줄러 저장 정책과 같은 방식(`calculate_pool_total_ranking`)으로 채운다.
교체 전 final_rankings 전체를 진행 로그에 남겨 되돌릴 수 있게 한다.

사용법:
    cd services/data
    PYTHONPATH=".:../../packages" python scripts/repair_final_rankings.py --dry-run
    PYTHONPATH=".:../../packages" python scripts/repair_final_rankings.py --year 2025 --limit 12
    PYTHONPATH=".:../../packages" python scripts/repair_final_rankings.py --comp COMPM00633
    PYTHONPATH=".:../../packages" python scripts/repair_final_rankings.py --time-budget 540 --parallel 2
"""
import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from loguru import logger
from supabase import create_client

from scraper.full_scraper import KFFFullScraper
from scheduler.competition_detector import (
    _de_bracket_regression, _de_scored_bout_count, _de_bout_identities,
)
from app.pool_calculator import calculate_pool_total_ranking, enrich_with_advancement_status
from app.de_revisions import record_revision as record_de_revision
from app.pool_revisions import record_revision as record_pool_revision
from audit_final_rankings import audit_event, TIE_LIMITS, _final_champion, pool_health, pool_unique_players
from repair_forfeit_winners import find_page_num

PROGRESS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "logs", "repair_final_rankings.jsonl")
REPAIR_CODES = {"F01", "F02", "F03", "F04", "F05", "F06", "F08", "F09", "F10", "F12"}
NOTE = "final_rankings 오염 복구 재수집 (2026-09 감사)"


# ---------------------------------------------------------------- 판정 도우미
def parse_final(final) -> Tuple[List[Tuple[str, int]], int]:
    """[(name, rank)], 깨진 항목 수"""
    out, bad = [], 0
    for fr in final or []:
        if not isinstance(fr, dict) or any(str(k).startswith("$") for k in fr):
            bad += 1
            continue
        n = (fr.get("name") or "").strip()
        try:
            r = int(fr.get("rank") or 0)
        except (TypeError, ValueError):
            r = 0
        if not n or r <= 0:
            bad += 1
            continue
        out.append((n, r))
    return out, bad


def live_final_problem(final) -> Optional[str]:
    """안전조건 ① — LIVE final_rankings 가 스스로 건전하지 않으면 사유."""
    rows, bad = parse_final(final)
    if not rows:
        return "LIVE final 비어 있음"
    if bad:
        return f"LIVE 깨진 항목 {bad}건"
    rc = Counter(r for _, r in rows)
    if rc.get(1, 0) != 1:
        return f"LIVE 1위 {rc.get(1, 0)}명"
    if len(rows) >= 2 and rc.get(2, 0) != 1:
        return f"LIVE 2위 {rc.get(2, 0)}명"
    over = [f"{r}위 {rc[r]}명" for r, lim in TIE_LIMITS.items() if rc.get(r, 0) > lim]
    if over:
        return "LIVE 동률 초과 " + ", ".join(over)
    if max(rc) > len(rows):
        return f"LIVE 최대 {max(rc)}위 > {len(rows)}명"
    return None


def final_replace_problem(old_final, new_final, champion: Optional[str]) -> Optional[str]:
    p = live_final_problem(new_final)
    if p:
        return p
    old_rows, _ = parse_final(old_final)
    new_rows, _ = parse_final(new_final)
    if old_rows and len(new_rows) < 0.9 * len(old_rows):
        return f"LIVE 인원 {len(new_rows)} < DB {len(old_rows)}의 90%"
    on = {n for n, _ in old_rows}
    nn = {n for n, _ in new_rows}
    if on:
        ov = len(on & nn) / len(on)
        if ov < 0.8:
            return f"이름 겹침 {ov:.0%} < 80% (DB {len(on)}명 중 {len(on & nn)}명)"
    if champion:
        first = [n for n, r in new_rows if r == 1]
        if first and first[0] != champion:
            return f"결승 승자 {champion} ≠ LIVE 1위 {first[0]}"
    return None


def _has_phase(de: dict) -> bool:
    """DE bout 에 de_phase 가 붙어 있는가 (2026-08-18 이후 스크래퍼)."""
    if not isinstance(de, dict):
        return False
    for sub in ("first_de", "second_de"):
        for b in ((de.get(sub) or {}).get("full_bouts") or (de.get(sub) or {}).get("bouts") or []):
            if isinstance(b, dict) and b.get("de_phase"):
                return True
    return any(isinstance(b, dict) and b.get("de_phase") for b in (de.get("full_bouts") or de.get("bouts") or []))


def _pool_stats(pools) -> Tuple[int, int]:
    pools = pools or []
    return (len({str(p.get("pool_number")) for p in pools}),
            sum(len(p.get("results") or []) for p in pools))


# ---------------------------------------------------------------- 대상/진행
def load_progress() -> Dict[str, dict]:
    done = {}
    if os.path.exists(PROGRESS):
        for line in open(PROGRESS, encoding="utf-8"):
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("sub"):
                done[e["sub"]] = e
    return done


def log_progress(entry: dict):
    os.makedirs(os.path.dirname(PROGRESS), exist_ok=True)
    entry["at"] = datetime.now().isoformat(timespec="seconds")
    with open(PROGRESS, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def find_targets(db, years, comp_filter, retry: bool, include_pool: bool = False):
    codes_wanted = REPAIR_CODES | ({"F13"} if include_pool else set())
    comps = {c["id"]: c for c in db.table("competitions").select("id, comp_idx, comp_name, start_date").execute().data}
    done = load_progress()
    targets, off = [], 0
    while True:
        rows = (db.table("events").select("id, competition_id, sub_event_cd, event_name, category, raw_data")
                .range(off, off + 199).execute().data or [])
        for ev in rows:
            comp = comps.get(ev["competition_id"])
            if not comp:
                continue
            year = int(comp["start_date"][:4])
            if years and year not in years:
                continue
            if comp_filter and comp["comp_idx"] not in comp_filter:
                continue
            r = audit_event(ev)
            codes = set(r["codes"]) & codes_wanted
            if not codes:
                continue
            prev = done.get(ev["sub_event_cd"])
            if prev and not retry:
                continue
            is_nt = "F04" in codes or (r["de_format"] == "dual_de")
            targets.append({
                "id": ev["id"], "competition_id": ev["competition_id"], "sub_event_cd": ev["sub_event_cd"],
                "event_name": ev["event_name"], "comp_idx": comp["comp_idx"], "comp_name": comp["comp_name"],
                "year": year, "codes": r["codes"], "prio": 0 if is_nt else 1,
            })
        off += 200
        if len(rows) < 200:
            break
    # 국가대표(dual DE) 먼저, 최근 연도 먼저, 같은 대회끼리 묶어서
    targets.sort(key=lambda t: (t["prio"], -t["year"], t["comp_idx"], t["event_name"]))
    return targets


# ---------------------------------------------------------------- 1종목 처리
def apply_repair(db, t: dict, res: dict, dry_run: bool) -> dict:
    """LIVE 결과를 안전조건으로 걸러 DB 에 반영. 결과 요약 dict 반환."""
    row = db.table("events").select("raw_data").eq("id", t["id"]).execute().data[0]
    raw = row["raw_data"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    old_final = raw.get("final_rankings") or []
    old_de = raw.get("de_bracket") or {}
    old_pools = raw.get("pool_rounds") or []
    old_ptr = raw.get("pool_total_ranking") or []
    new_final = res.get("final_rankings") or []
    new_de = res.get("de_bracket") or {}
    new_pools = res.get("pool_rounds") or []

    out = {"final": "kept", "de": "kept", "pool": "kept", "reasons": {}}
    changed = False

    # --- DE
    o_b, n_b = len(_de_bout_identities(old_de)), len(_de_bout_identities(new_de))
    o_s, n_s = _de_scored_bout_count(old_de), _de_scored_bout_count(new_de)
    de_to_save = old_de
    if n_b > 0:
        reg = _de_bracket_regression(new_de, old_de) if old_de else None
        if reg:
            out["reasons"]["de"] = f"가드 거부: {reg[:120]}"
        elif n_b < o_b:
            out["reasons"]["de"] = f"경기 감소 {o_b}→{n_b}"
        elif n_s < o_s:
            out["reasons"]["de"] = f"점수 감소 {o_s}→{n_s}"
        elif n_b == o_b and n_s == o_s and not (_has_phase(new_de) and not _has_phase(old_de)):
            out["reasons"]["de"] = "LIVE 가 더 낫지 않음(같은 경기·점수 수) → 유지"
        else:
            de_to_save = new_de
            out["de"] = f"replaced bouts {o_b}→{n_b} scored {o_s}→{n_s}"
            changed = True
    else:
        out["reasons"]["de"] = "LIVE DE 비어 있음"

    # --- 풀
    o_d, o_e = _pool_stats(old_pools)
    n_d, n_e = _pool_stats(new_pools)
    pools_to_save = old_pools
    old_ph, new_ph = pool_health(old_pools), pool_health(new_pools)
    o_u, n_u = pool_unique_players(old_pools), pool_unique_players(new_pools)
    # 같은 수면 바꾸지 않는다 — 교체는 '더 완전할 때'만
    if new_pools and (not old_pools or (n_d >= o_d and n_e >= o_e and (n_d > o_d or n_e > o_e))):
        pools_to_save = new_pools
        out["pool"] = f"replaced pools {o_d}/{o_e}→{n_d}/{n_e}"
        changed = True
    # DB 풀이 오염(팬텀/중복)됐고 LIVE 는 건전하며 고유 선수를 90% 이상 담고 있으면 교체
    elif new_pools and old_ph and not new_ph and n_u >= 0.9 * o_u:
        pools_to_save = new_pools
        out["pool"] = f"replaced corrupt pools ({old_ph}) {o_d}/{o_e}→{n_d}/{n_e}, 고유 {o_u}→{n_u}"
        changed = True
    elif new_pools and old_ph:
        out["reasons"]["pool"] = f"DB 풀 오염({old_ph})이나 LIVE 부적합: 건전={not new_ph}, 고유 {n_u}/{o_u} → 유지"
    elif new_pools and (n_d, n_e) == (o_d, o_e):
        out["reasons"]["pool"] = f"LIVE 풀 = DB ({n_d}개/{n_e}명) → 유지"
    elif new_pools:
        out["reasons"]["pool"] = f"LIVE 풀 {n_d}개/{n_e}명 < DB {o_d}개/{o_e}명 → 유지"
    else:
        out["reasons"]["pool"] = "LIVE 풀 비어 있음"
    ptr_to_save = old_ptr
    if pools_to_save and (pools_to_save is not old_pools or not old_ptr):
        calc = calculate_pool_total_ranking(pools_to_save)
        if calc:
            status_src = res.get("pool_total_ranking") or old_ptr
            if status_src:
                calc = enrich_with_advancement_status(calc, status_src)
            ptr_to_save = calc
            if len(calc) != len(old_ptr):
                out["pool"] += f" | pool_total {len(old_ptr)}→{len(calc)}"
                changed = True

    # --- final
    champion = _final_champion(de_to_save) or _final_champion(old_de) or _final_champion(new_de)
    p = final_replace_problem(old_final, new_final, champion)
    if p:
        out["reasons"]["final"] = p
    else:
        # 내용이 같으면 쓰지 않는다
        o_rows, _ = parse_final(old_final)
        n_rows, _ = parse_final(new_final)
        if sorted(o_rows) == sorted(n_rows) and len(old_final) == len(new_final):
            out["final"] = "same"
        else:
            out["final"] = f"replaced {len(old_final)}→{len(new_final)}"
            changed = True

    if not changed:
        out["result"] = "no_change"
        return out
    if dry_run:
        out["result"] = "dry_run"
        return out

    if out["final"].startswith("replaced"):
        raw["final_rankings"] = new_final
        raw["final_rankings_source"] = "kfa"
        raw["_final_rankings_repair"] = {"at": datetime.now().isoformat(timespec="seconds"),
                                         "prev_count": len(old_final), "new_count": len(new_final)}
        out["old_final"] = old_final          # 되돌리기용 원본 보존
    if de_to_save is not old_de:
        raw["de_bracket"] = new_de
        if res.get("de_matches"):
            raw["de_matches"] = res["de_matches"]
    if pools_to_save is not old_pools:
        raw["pool_rounds"] = pools_to_save
    if ptr_to_save is not old_ptr:
        raw["pool_total_ranking"] = ptr_to_save
    db.table("events").update({"raw_data": raw}).eq("id", t["id"]).execute()
    if de_to_save is not old_de:
        record_de_revision(db, sub_event_cd=t["sub_event_cd"], de_bracket=new_de, event_id=t["id"],
                           competition_id=t["competition_id"], previous_de_bracket=old_de,
                           source="repair", note=NOTE)
    if pools_to_save is not old_pools:
        record_pool_revision(db, sub_event_cd=t["sub_event_cd"], pool_rounds=pools_to_save, event_id=t["id"],
                             competition_id=t["competition_id"], previous_pool_rounds=old_pools,
                             source="repair", note=NOTE)
    out["result"] = "fixed"
    return out


async def worker(name: str, queue: asyncio.Queue, db, page_cache: dict, page_locks: dict,
                 stats: Counter, dry_run: bool, deadline: float):
    async with KFFFullScraper(headless=True) as s:
        while True:
            if time.time() > deadline:
                break
            try:
                t = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            tag = f"{t['year']} {t['comp_name'][:20]} / {t['event_name']}"
            ev_cd = t["comp_idx"]
            lock = page_locks.setdefault(ev_cd, asyncio.Lock())
            async with lock:
                if ev_cd not in page_cache:
                    page_cache[ev_cd] = await find_page_num(s, ev_cd)
                    logger.info(f"[{name}] 대회 목록 페이지: {ev_cd} → {page_cache[ev_cd]}")
            pnum = page_cache[ev_cd]
            if pnum is None:
                logger.warning(f"[{name}] ⏭ 대회 목록에서 못 찾음 {tag}")
                log_progress({"sub": t["sub_event_cd"], "tag": tag, "codes": t["codes"], "result": "comp_not_listed"})
                stats["failed"] += 1
                continue
            try:
                res = await s.get_full_results(ev_cd, t["sub_event_cd"], page_num=pnum)
            except Exception as e:
                logger.warning(f"[{name}] ❌ 스크랩 실패 {tag}: {e}")
                log_progress({"sub": t["sub_event_cd"], "tag": tag, "codes": t["codes"],
                              "result": "scrape_failed", "error": str(e)[:200]})
                stats["failed"] += 1
                continue
            try:
                out = apply_repair(db, t, res, dry_run)
            except Exception as e:
                logger.exception(f"[{name}] ❌ 적용 실패 {tag}: {e}")
                log_progress({"sub": t["sub_event_cd"], "tag": tag, "codes": t["codes"],
                              "result": "apply_failed", "error": str(e)[:200]})
                stats["failed"] += 1
                continue
            r = out["result"]
            stats[r] += 1
            icon = {"fixed": "✅", "no_change": "⏭", "dry_run": "🔍"}.get(r, "?")
            logger.info(f"[{name}] {icon} {tag}: final={out['final']} de={out['de']} pool={out['pool']} "
                        f"{('사유 ' + str(out['reasons'])) if out['reasons'] else ''}")
            if not dry_run:
                log_progress({"sub": t["sub_event_cd"], "tag": tag, "codes": t["codes"], "result": r,
                              "final": out["final"], "de": out["de"], "pool": out["pool"],
                              "reasons": out["reasons"], "old_final": out.get("old_final")})


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--year", type=int, action="append")
    ap.add_argument("--comp", action="append", help="comp_idx 필터 (반복 가능)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--retry", action="store_true", help="이전에 처리 기록이 있는 종목도 다시 시도")
    ap.add_argument("--time-budget", type=int, default=540, help="초. 넘기면 새 종목을 더 집지 않는다")
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--list", action="store_true", help="대상만 출력")
    ap.add_argument("--include-pool", action="store_true",
                    help="풀 오염(F13)만 있는 종목도 대상에 넣는다 (2019~2024 전체가 해당하므로 기본은 제외)")
    args = ap.parse_args()

    db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    targets = find_targets(db, args.year, args.comp, args.retry, args.include_pool)
    logger.info(f"남은 복구 대상: {len(targets)}종목 "
                f"(국가대표/dual {sum(1 for t in targets if t['prio'] == 0)}, 연도 {sorted(Counter(t['year'] for t in targets).items())})")
    if not targets:
        return
    batch = targets[:args.limit]
    if args.list or args.dry_run:
        for t in batch:
            logger.info(f"  {t['year']} {t['comp_idx']} {t['comp_name'][:22]} / {t['event_name']} — {t['codes']}")
        if args.list:
            return

    queue: asyncio.Queue = asyncio.Queue()
    for t in batch:
        queue.put_nowait(t)
    stats: Counter = Counter()
    deadline = time.time() + args.time_budget
    page_cache: dict = {}
    page_locks: dict = {}
    await asyncio.gather(*[
        worker(f"w{i}", queue, db, page_cache, page_locks, stats, args.dry_run, deadline)
        for i in range(max(1, args.parallel))
    ])
    logger.info(f"이번 실행: {dict(stats)} | 미처리 {queue.qsize()} | 남은 대상(실행 전 기준) {len(targets)}")


if __name__ == "__main__":
    asyncio.run(main())
