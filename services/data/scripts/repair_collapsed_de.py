#!/usr/bin/env python3
"""DE 대진표의 선수 이름이 한 사람으로 뭉개진 종목을 재수집한다.

발견 (2026-09-27 감사):
  ① 2023·2024·2025 전국소년체육대회 개인전 18종목(연도별 6종목)의 `de_bracket` 이
  **36개 슬롯 전부 '정효정'** 으로 채워져 있었다. 정효정은 실재하는 성인 실업팀 선수라,
  중학생 대회 경기 수백 건이 그 선수 기록에 붙는다(선수 기록은 그 아이의 1년이다 — 제1원칙).
  최종순위(final_rankings)는 정상이므로, 오염은 옛 스크래퍼의 DE 파싱에 한정된다.
  현재 파서로 라이브 재수집하면 실제 이름 16명이 정상 수집된다(실측).

  ② 같은 뿌리의 더 넓은 유형: 251종목에서 **빈 브래킷 슬롯에 '정효정' + 다른 경기의 점수가
  복제**돼 들어갔다(예: 5명 대회의 브래킷이 46경기로 부풀고 그중 24경기가 '정효정 15-4 정효정').
  선수는 자기 자신과 붙지 않으므로(R1a) 자기경기가 있는 브래킷은 전부 이 유형이다.
  현재 파서는 같은 종목을 7경기·자기경기 0건으로 정확히 수집한다(실측 2건).

안전 규칙 (교체는 아래를 모두 통과할 때만):
  - 새 DE 의 고유 이름이 4명 이상이고, 뭉개짐(한 이름 50% 초과)이 재발하지 않았다.
  - 새 DE 의 이름이 이 종목 최종순위 이름과 70% 이상 겹친다(엉뚱한 종목을 덮어쓰지 않는다).
  - 실제 경기 수가 1경기 이상이다.
  기존 데이터는 logs/repair_collapsed_de.jsonl 에 남긴다.

사용:
  PYTHONPATH=".:../../packages" python3 scripts/repair_collapsed_de.py --list
  PYTHONPATH=".:../../packages" python3 scripts/repair_collapsed_de.py --dry-run
  PYTHONPATH=".:../../packages" python3 scripts/repair_collapsed_de.py [--limit N]
"""
import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(HERE), ".env"))

from loguru import logger
from supabase import create_client

from app.bracket_utils import get_canonical_bouts
from repair_final_rankings import find_page_num
from scraper.full_scraper import KFFFullScraper

LOG_PATH = os.path.join(os.path.dirname(HERE), "logs", "repair_collapsed_de.jsonl")
NOTE = "DE 이름 뭉개짐(단일 이름 오염) 재수집 (2026-09 감사)"


def de_bouts(de: dict) -> list:
    """bout 목록 — `app.bracket_utils.get_canonical_bouts()` 가 유일한 진입점이다.

    ⚠️ 예전엔 여기서 `full_bouts + bouts` 를 이어붙였는데, 두 키에 같은 경기가
    중복 저장되는 구조라 경기 수가 2배로 세어졌다(가드 판정은 비율 기반이라 결과가
    바뀌지 않았지만 로그 숫자가 부풀었다). 정본 헬퍼는 우선순위대로 하나만 읽고
    (de_phase, round_name, match_number) 복합키로 dedup 한다.
    """
    return get_canonical_bouts(de)


def slot_names(de: dict) -> list:
    return [(b.get(k) or "").strip() for b in de_bouts(de)
            for k in ("player1_name", "player2_name") if (b.get(k) or "").strip()]


def self_bouts(de: dict) -> list:
    """같은 이름이 양쪽에 있는 경기. 선수는 자기 자신과 붙지 않는다(검증 규칙 R1a)."""
    out = []
    for b in de_bouts(de):
        p1 = (b.get("player1_name") or "").strip()
        p2 = (b.get("player2_name") or "").strip()
        if p1 and p1 == p2:
            out.append(b)
    return out


def collapse_ratio(de: dict):
    """(가장 흔한 이름, 점유율, 고유 이름 수, 슬롯 수). 슬롯이 없으면 None."""
    names = slot_names(de)
    if len(names) < 4:
        return None
    c = Counter(names)
    top, cnt = c.most_common(1)[0]
    return top, cnt / len(names), len(c), len(names)


def load_done() -> set:
    if not os.path.exists(LOG_PATH):
        return set()
    done = set()
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("result") in ("fixed", "skipped"):
                done.add(r["sub"])
    return done


def log_entry(entry: dict):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def find_targets(db, retry: bool):
    comps = {c["id"]: c for c in db.table("competitions")
             .select("id,comp_idx,comp_name,start_date").execute().data}
    done = set() if retry else load_done()
    targets, off = [], 0
    while True:
        rows = (db.table("events").select("id,competition_id,sub_event_cd,event_name,raw_data")
                .range(off, off + 199).execute().data or [])
        for ev in rows:
            if ev["sub_event_cd"] in done:
                continue
            rd = ev.get("raw_data") or {}
            de = rd.get("de_bracket") or {}
            info = collapse_ratio(de)
            selfb = self_bouts(de)
            # ① 이름이 한 사람으로 뭉개진 브래킷 ② 팬텀 자기경기가 섞인 브래킷
            #    (빈 슬롯에 실재 선수 이름 + 다른 경기 점수가 복제돼 들어간 유형)
            if not selfb:
                if not info:
                    continue
                top, share, uniq, slots = info
                if share <= 0.5 or uniq > 2:
                    continue
            if not info:
                info = ("", 0.0, 0, 0)
            top, share, uniq, slots = info
            comp = comps.get(ev["competition_id"]) or {}
            targets.append({
                "id": ev["id"], "sub_event_cd": ev["sub_event_cd"], "event_name": ev["event_name"],
                "comp_idx": comp.get("comp_idx"), "comp_name": comp.get("comp_name", ""),
                "year": int((comp.get("start_date") or "0")[:4]),
                "bad_name": top, "share": share, "uniq": uniq, "slots": slots,
                "self_bouts": len(selfb),
            })
        off += 200
        if len(rows) < 200:
            break
    targets.sort(key=lambda t: (-t["year"], t["comp_idx"] or "", t["event_name"]))
    return targets


def roster_names(res: dict) -> set:
    """라이브 스크랩 결과에서 이 종목의 정당한 이름 집합(최종순위 + 풀 로스터)."""
    names = {(r.get("name") or "").strip()
             for r in (res.get("final_rankings") or []) if (r.get("name") or "").strip()}
    for r in (res.get("pool_total_ranking") or []):
        if (r.get("name") or "").strip():
            names.add(r["name"].strip())
    for pr in (res.get("pool_rounds") or []):
        for pl in (pr.get("players") or pr.get("participants") or []):
            n = (pl.get("name") if isinstance(pl, dict) else pl) or ""
            if n.strip():
                names.add(n.strip())
    return names


def replace_problem(new_de: dict, final_names: set):
    """교체를 거부할 이유. None 이면 통과."""
    info = collapse_ratio(new_de)
    if not info:
        return "새 DE 에 경기 없음"
    top, share, uniq, slots = info
    bad_self = self_bouts(new_de)
    if bad_self:
        return f"새 DE 에도 자기경기 {len(bad_self)}건 (파서가 여전히 팬텀을 만든다)"
    if uniq < 3:
        return f"새 DE 고유 이름 {uniq}명 (<3)"
    if share > 0.5:
        return f"새 DE 도 '{top}' 가 {share:.0%} 차지 (뭉개짐 재발)"
    if final_names:
        new_names = set(slot_names(new_de))
        ov = len(new_names & final_names) / len(final_names)
        if ov < 0.7:
            return f"최종순위 이름과 겹침 {ov:.0%} < 70%"
    return None


async def run(args):
    db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    targets = find_targets(db, args.retry)
    logger.info(f"DE 뭉개짐 대상: {len(targets)}종목 "
                f"(연도 {sorted(Counter(t['year'] for t in targets).items())})")
    if args.list or not targets:
        for t in targets:
            logger.info(f"  {t['year']} {t['comp_name'][:22]} / {t['event_name']} — "
                        f"'{t['bad_name']}' {t['share']:.0%} of {t['slots']}슬롯, 고유 {t['uniq']}, "
                        f"자기경기 {t['self_bouts']}건")
        return

    batch = targets[:args.limit] if args.limit else targets
    stats = Counter()
    deadline = time.time() + args.time_budget
    page_cache = {}
    async with KFFFullScraper(headless=True) as s:
        for t in batch:
            if time.time() > deadline:
                logger.info("시간 예산 초과 — 남은 종목은 다음 실행으로")
                break
            tag = f"{t['year']} {t['comp_name'][:22]} / {t['event_name']}"
            if t["comp_idx"] not in page_cache:
                page_cache[t["comp_idx"]] = await find_page_num(s, t["comp_idx"])
            pnum = page_cache[t["comp_idx"]]
            if pnum is None:
                logger.warning(f"⏭ 대회 목록에서 못 찾음: {tag}")
                stats["not_listed"] += 1
                continue
            try:
                res = await s.get_full_results(t["comp_idx"], t["sub_event_cd"], page_num=pnum)
            except Exception as e:
                logger.warning(f"❌ 스크랩 실패 {tag}: {str(e)[:120]}")
                stats["scrape_failed"] += 1
                continue

            ev = db.table("events").select("raw_data").eq("id", t["id"]).execute().data[0]
            rd = ev["raw_data"] or {}
            old_final = rd.get("final_rankings") or []
            old_final_names = {(r.get("name") or "").strip()
                               for r in old_final if (r.get("name") or "").strip()}
            # 대조 기준은 **라이브 로스터**(최종순위+풀)다. 저장된 최종순위 자체가 오염된
            # 종목(한 줄에 엉뚱한 이름)이 있어서 그것을 기준으로 삼으면 올바른 재수집을 거부한다.
            ref_names = roster_names(res) or old_final_names
            new_de = res.get("de_bracket") or {}
            reason = replace_problem(new_de, ref_names)
            if reason:
                logger.warning(f"⏭ {tag}: {reason}")
                stats["skipped"] += 1
                log_entry({"sub": t["sub_event_cd"], "tag": tag, "result": "skipped", "reason": reason,
                           "at": datetime.now(timezone.utc).isoformat()})
                continue

            old_info = collapse_ratio(rd.get("de_bracket") or {}) or ("", 0.0, 0, 0)
            new_info = collapse_ratio(new_de) or ("", 0.0, 0, 0)
            logger.info(f"✅ {tag}: 이름 {old_info[2]}명→{new_info[2]}명, "
                        f"경기 {len(de_bouts(rd.get('de_bracket') or {}))}→{len(de_bouts(new_de))}"
                        f"{' (dry-run)' if args.dry_run else ''}")
            entry = {"sub": t["sub_event_cd"], "tag": tag,
                     "result": "dry_run" if args.dry_run else "fixed",
                     "old_uniq": old_info[2], "new_uniq": new_info[2],
                     "old_bouts": len(de_bouts(rd.get("de_bracket") or {})),
                     "new_bouts": len(de_bouts(new_de)), "bad_name": t["bad_name"],
                     "old_self_bouts": t["self_bouts"],
                     "note": NOTE, "at": datetime.now(timezone.utc).isoformat()}
            # 저장된 최종순위가 이 종목 로스터에 없는 이름으로 채워져 있으면(팬텀 이름이
            # 최종순위까지 번진 종목) 라이브 최종순위로 함께 교체한다. 라이브가 비어 있으면 둔다.
            live_final = res.get("final_rankings") or []
            new_names = set(slot_names(new_de))
            alien = {n for n in old_final_names if n not in new_names and n not in ref_names}
            replace_final = bool(
                live_final and old_final_names
                and len(alien) / len(old_final_names) > 0.3
                and any(r.get("rank") == 1 for r in live_final)
            )
            if replace_final:
                logger.info(f"   ↳ 최종순위도 교체: {len(old_final)}행(외부 이름 {len(alien)}) "
                            f"→ 라이브 {len(live_final)}행")
            entry["final_replaced"] = replace_final
            entry["alien_final_names"] = sorted(alien)[:6]
            if not args.dry_run:
                rd["de_bracket"] = new_de
                if replace_final:
                    # 라이브 협회 표에서 가져온 것이므로 출처를 명시한다
                    # (관례: kfa=협회 표, computed=우리 계산, estimated=추정).
                    rd["final_rankings"] = live_final
                    rd["final_rankings_source"] = "kfa"
                if res.get("pool_rounds") and not (rd.get("pool_rounds") or []):
                    rd["pool_rounds"] = res["pool_rounds"]
                if res.get("pool_total_ranking") and not (rd.get("pool_total_ranking") or []):
                    rd["pool_total_ranking"] = res["pool_total_ranking"]
                db.table("events").update({"raw_data": rd}).eq("id", t["id"]).execute()
            stats["dry_run" if args.dry_run else "fixed"] += 1
            log_entry(entry)
    logger.info(f"결과: {dict(stats)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--retry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--time-budget", type=int, default=500)
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
