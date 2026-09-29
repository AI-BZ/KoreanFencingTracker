"""전 연도 이벤트 final_rankings 전수 감사 (쓰기 없음).

배경: 2025 국가대표선수 선발대회·제65회 대통령배의 개인전 final_rankings 가 예선 브래킷
기준으로 잘못 계산돼 있었다 (1·2위 없음, 5위 4명 초과, 본선 시드 32명이 33~38위).
김창환배(2025)는 풀이 비어 있고 최종순위가 절반 이상 결손이다. 같은 유형의 오염이
다른 연도에도 있는지 전 이벤트를 판정한다.

판정 규칙 (이벤트별로 해당하는 코드를 전부 기록):
  F01 NO_WINNER          final_rankings 비어있지 않은데 1위가 정확히 1명이 아님
  F02 NO_RUNNER_UP       2명 이상인데 2위가 정확히 1명이 아님
  F03 TIE_OVERFLOW       동률 초과: 3위>2, 5위>4, 9위>8, 17위>16, 33위>32
  F04 SEEDS_DEMOTED      dual_de 의 seeded_players(seed≤32) 중 최종순위≥33 비율>60% 또는
                         최종순위 없음 >5명  (본선 시드가 예선 순위로 매겨진 흔적)
  F05 FINAL_SHORT_POOL   final 수 < pool_total_ranking 수의 60%
  F06 FINAL_SHORT_DE     실제 DE 경기 ≥63 인데 final <32
  F07 POOL_MISSING       pool_rounds 비어 있는데 final 또는 DE 경기가 있음 (풀 결손, 개인전만.
                         협회가 풀을 아예 게시하지 않는 대회군은 제외 → F14)
  F08 MALFORMED          이름 없음 / rank≤0 / '$1' 같은 깨진 키를 가진 항목
  F09 RANK_GAP           최대 순위 > 항목 수 (중간이 빠진 순위표)
  F10 FINAL_MISSING      final 비어 있는데 점수 입력된 DE 경기가 있음 (개인전만)
  F11 DUP_NAME           같은 이름이 두 번 (동명이인일 수 있음 — 정보성)
  F12 CHAMPION_MISMATCH  결승 점수가 있는데 결승 승자 ≠ final 1위
  F13 POOL_CORRUPT       풀 구조 오염 — 참가자 명단이 풀로 잘못 파싱된 팬텀 풀(13명 이상) 또는
                         같은 선수 집합의 풀이 두 번 저장됨 (2019~2024 풀 있는 종목 전부 = 1,187개.
                         구 스크래퍼 형식이라 별도 작업 대상. 정보성 — 이상 종목 수에 넣지 않음)
  F14 POOL_NOT_PUBLISHED 협회가 이 대회의 풀을 게시하지 않음 → 결손이 아니다 (정보성, F07 대체)

F01~F04, F06, F09, F12 는 '오염'(잘못된 순위), F05, F07, F10 은 '결손', F08 은 '형식',
F11·F13·F14 는 정보. 요약에서는 정보성 코드를 이상 종목 수에 넣지 않는다.

협회 합산표(2024·2025·2026)와의 총점 일치율은 `scripts/kfa_selection_compare.py` 로
같이 산출해 감사 전 기준치로 남긴다 (`--kfa`).

사용법:
    cd services/data
    PYTHONPATH=".:../../packages" python scripts/audit_final_rankings.py --kfa
    PYTHONPATH=".:../../packages" python scripts/audit_final_rankings.py --year 2025 --list
출력: logs/audit_final_rankings.json (이상 종목 목록 + 집계)
"""
import argparse
import json
import os
import pickle
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from app.bracket_utils import is_bye_bout
from scheduler.competition_detector import _de_bout_identities, _de_scored_bout_count

RULES = {
    "F01": "NO_WINNER", "F02": "NO_RUNNER_UP", "F03": "TIE_OVERFLOW", "F04": "SEEDS_DEMOTED",
    "F05": "FINAL_SHORT_POOL", "F06": "FINAL_SHORT_DE", "F07": "POOL_MISSING", "F08": "MALFORMED",
    "F09": "RANK_GAP", "F10": "FINAL_MISSING", "F11": "DUP_NAME", "F12": "CHAMPION_MISMATCH",
    "F13": "POOL_CORRUPT", "F14": "POOL_NOT_PUBLISHED",
}
INFO_ONLY = {"F11", "F13", "F14"}

# 협회가 구조적으로 **풀을 게시하지 않는** 대회군.
#
# 2026-09-28 확인: 전 연도 감사에서 F07(POOL_MISSING) 단독으로 남은 98종목이 전부
# 전국체육대회·전국소년체육대회였다. 협회 페이지를 라이브로 확인한 결과 이 대회들은
# 풀을 아예 게시하지 않으며(pool_rounds 0) 최종순위는 정상이다. 즉 F07 은 스크래핑
# 결손이 아니라 **오탐**이다.
#
# DB 실측이 이를 뒷받침한다 (2026-09-28 스냅샷):
#   전국체육대회·전국소년체육대회 개인전 96종목 → 풀 보유 0, 최종순위 보유 96
#   그 외 개인전 1,872종목        → 풀 보유 1,748 (93%)
# 풀 부재가 이 대회군에만 100% 몰려 있다 = 구조적 특성이지 우리 쪽 결손이 아니다.
#
# 이유도 대회 성격과 맞는다: 시도별 1명 선발이라 참가자가 13~18명뿐이어서 풀 없이 DE 만
# 치른다. 같은 이유로 랭킹 포인트에서도 제외되는 대회군이다(CLAUDE.md 자유 참가 원칙).
#
# ⚠️ 새 대회를 이 목록에 넣기 전에 반드시 협회 페이지에서 풀 미게시를 확인할 것.
#    확인 없이 추가하면 진짜 스크래핑 결손을 영구히 숨기게 된다.
POOL_NOT_PUBLISHED_COMPETITIONS = ("전국체육대회", "전국소년체육대회")
TIE_LIMITS = {3: 2, 5: 4, 9: 8, 17: 16, 33: 32}
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "audit_final_rankings.json")


def pool_health(pools) -> Optional[str]:
    """풀 구조 오염이면 사유, 아니면 None.

    구 스크래퍼는 ① 참가자 명단 표를 '풀'로 오파싱해 13명 이상 들어간 팬텀 풀을 만들고
    ② 같은 풀을 두 번 저장했다(선수 집합이 완전히 같은 풀 쌍). 동명이인 한둘로는 걸리지
    않도록 '완전히 같은 집합'만 중복으로 본다.
    """
    pools = [p for p in (pools or []) if isinstance(p, dict)]
    if not pools:
        return None
    reasons = []
    phantom = [p for p in pools if len(p.get("results") or []) > 12]
    if phantom:
        reasons.append(f"팬텀 풀 {len(phantom)}개")
    sets = []
    dup = 0
    for p in pools:
        if p in phantom:
            continue
        key = (p.get("round_number"), frozenset(
            ((r.get("name") or "").strip(), (r.get("team") or "").strip()) for r in (p.get("results") or [])))
        if key[1] and key in sets:
            dup += 1
        sets.append(key)
    if dup:
        reasons.append(f"동일 풀 중복 {dup}개")
    return ", ".join(reasons) or None


def pool_unique_players(pools) -> int:
    """팬텀 풀을 뺀 고유 (이름, 소속) 수."""
    keys = set()
    for p in pools or []:
        if not isinstance(p, dict) or len(p.get("results") or []) > 12:
            continue
        for r in p.get("results") or []:
            n = (r.get("name") or "").strip()
            if n:
                keys.add((n, (r.get("team") or "").strip()))
    return len(keys)


def _all_bouts(de: dict) -> List[dict]:
    out = []
    if not isinstance(de, dict):
        return out
    for sub in ("first_de", "second_de"):
        s = de.get(sub)
        if isinstance(s, dict):
            out.extend(b for b in (s.get("full_bouts") or s.get("bouts") or []) if isinstance(b, dict))
    if not out:
        out.extend(b for b in (de.get("full_bouts") or de.get("bouts") or []) if isinstance(b, dict))
    return out


def _final_champion(de: dict) -> Optional[str]:
    """진짜 결승의 승자. 판정할 수 없으면 None (추측하지 않는다).

    ⚠️ 어떤 대회는 **3-4위전을 '결승' 칸에 같이 넣는다** (2020 국가대표 선수 선발전:
    '결승' 라운드에 김상민-권영준(1-2위전)과 심승한-손태진(3-4위전)이 둘 다 있다).
    라운드명만 보고 첫 경기를 집으면 3위 선수를 우승자로 착각해 협회 표와 어긋난 것처럼
    보이고, 복구 스크립트가 올바른 협회 표를 거부한다. 그래서 결승 후보가 둘 이상이면
    **준결승 승자끼리 붙은 경기**를 진짜 결승으로 본다. 그래도 못 가리면 None.
    """
    bouts = _all_bouts(de)
    sf_winners = {(b.get("winner_name") or "").strip() for b in bouts
                  if (b.get("round_name") or "") == "준결승" and (b.get("winner_name") or "").strip()}
    finals = [b for b in bouts
              if (b.get("round_name") or "") in ("결승", "우승") and not is_bye_bout(b)]
    if len(finals) > 1:
        real = [b for b in finals
                if sf_winners and {(b.get("player1_name") or "").strip(),
                                   (b.get("player2_name") or "").strip()} <= sf_winners]
        if len(real) != 1:
            return None
        finals = real
        # 진짜 결승만 남았으면 점수가 안 올라온 경우에도 승자 표시(wingbn)는 신뢰한다.
        w = (finals[0].get("winner_name") or "").strip()
        if w:
            return w
    for b in finals:
        try:
            s1, s2 = int(b.get("player1_score") or 0), int(b.get("player2_score") or 0)
        except (TypeError, ValueError):
            continue
        if s1 <= 0 and s2 <= 0:
            continue
        w = (b.get("winner_name") or "").strip()
        if not w:
            w = (b.get("player1_name") if s1 > s2 else b.get("player2_name")) or ""
        return w.strip() or None
    return None


def audit_event(ev: dict, comp_name: str = "") -> dict:
    raw = ev.get("raw_data") or {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    final = raw.get("final_rankings") or []
    pool_rounds = raw.get("pool_rounds") or []
    ptr = raw.get("pool_total_ranking") or []
    de = raw.get("de_bracket") or {}
    de_real = len(_de_bout_identities(de)) if isinstance(de, dict) else 0
    de_scored = _de_scored_bout_count(de) if isinstance(de, dict) else 0

    codes: Dict[str, str] = {}
    ranks: List[int] = []
    names: List[str] = []
    malformed = 0
    for fr in final:
        if not isinstance(fr, dict) or any(k.startswith("$") for k in fr):
            malformed += 1
            continue
        n = (fr.get("name") or "").strip()
        try:
            r = int(fr.get("rank") or 0)
        except (TypeError, ValueError):
            r = 0
        if not n or r <= 0:
            malformed += 1
            continue
        ranks.append(r)
        names.append(n)
    rc = Counter(ranks)
    if final:
        if rc.get(1, 0) != 1:
            codes["F01"] = f"1위 {rc.get(1, 0)}명"
        if len(ranks) >= 2 and rc.get(2, 0) != 1:
            codes["F02"] = f"2위 {rc.get(2, 0)}명"
        over = [f"{r}위 {rc[r]}명" for r, lim in TIE_LIMITS.items() if rc.get(r, 0) > lim]
        if over:
            codes["F03"] = ", ".join(over)
        # F09: 순위표에 '구멍'이 있는지. 항목 수와 비교하면 **동률과 하위 생략을 오탐**한다.
        #   실측(2026-09-28): 2025 대통령배 단체전 3종목의 협회 표가 [1,2,3,5,9,9,9] 이다 —
        #   FIE 방식(5위·9위 동률)으로 상위만 게시한 정상 표인데, 7명뿐이라 "최대 9위 > 7명"
        #   으로 걸렸다. 같은 이유로 초등·클럽 소규모 종목 14건도 오탐이었다.
        #   실제 '구멍'은 **참가 인원보다 큰 순위**가 있을 때다. 인원 상한은 풀 인원 ·
        #   DE 시드 인원 · 순위표 행 수 중 가장 큰 값으로 잡는다(관대한 쪽).
        if ranks:
            de_seed_names = {
                (sd.get("name") or "").strip()
                for key in ("seeding", "seeded_players")
                for sd in (de.get(key) or []) if isinstance(sd, dict)
            } if isinstance(de, dict) else set()
            cap = max(len(ranks), len(ptr or []), len([n for n in de_seed_names if n]))
            if max(ranks) > cap:
                codes["F09"] = f"최대 {max(ranks)}위 > 참가 상한 {cap}명"
    if malformed:
        codes["F08"] = f"{malformed}건"
    dup = [n for n, c in Counter(names).items() if c > 1]
    if dup:
        codes["F11"] = ",".join(dup[:5])

    if isinstance(de, dict) and de.get("format") == "dual_de":
        seeds = [s for s in (de.get("seeded_players") or []) if isinstance(s, dict)
                 and (s.get("name") or "").strip() and int(s.get("seed") or 999) <= 32]
        if seeds:
            best: Dict[str, int] = {}
            for n, r in zip(names, ranks):
                best[n] = min(best.get(n, 10 ** 6), r)
            missing = [s["name"] for s in seeds if s["name"].strip() not in best]
            demoted = [s["name"] for s in seeds if best.get(s["name"].strip(), 0) >= 33]
            if len(demoted) / len(seeds) > 0.6 or len(missing) > 5:
                codes["F04"] = f"시드 {len(seeds)}명 중 33위 이하 {len(demoted)} / 순위없음 {len(missing)}"

    # F05: 순위표가 풀 인원보다 크게 짧은지. 단, 협회는 소규모 종목에서 **DE 진출자만**
    # 순위를 매긴다(실측 2026-09-28: 풀 8명 → DE 4명 → 순위표 4행 [1,2,3,3] 형태가 14종목).
    # 그건 결손이 아니라 협회 관례다. 그래서 'DE 판 크기'를 하한으로 함께 본다 —
    # 순위표가 DE 진출자 수 이상이면 F05 를 매기지 않는다.
    de_field = 0
    if isinstance(de, dict):
        de_field = max(
            len({(sd.get("name") or "").strip()
                 for key in ("seeding", "seeded_players")
                 for sd in (de.get(key) or []) if isinstance(sd, dict) and (sd.get("name") or "").strip()}),
            de_real + 1 if de_real else 0,
        )
    if ptr and len(final) < 0.6 * len(ptr) and len(final) < de_field:
        codes["F05"] = (f"final {len(final)} < 60% of pool {len(ptr)} "
                        f"(DE 진출자 {de_field}명보다도 적음)")
    if de_real >= 63 and len(final) < 32:
        codes["F06"] = f"DE {de_real}경기, final {len(final)}"
    # 단체전은 풀 단계가 없고(DE 만), 협회가 단체전 최종순위표를 내지 않는 해가 대부분이다
    # (2019~2024 단체 826종목 중 final 0건, 2025 만 47건). 둘 다 구조적이라 단체전엔 매기지 않는다.
    is_team = ev.get("category") == "단체" or "단체" in (ev.get("event_name") or "")
    pool_not_published = any(k in (comp_name or "") for k in POOL_NOT_PUBLISHED_COMPETITIONS)
    if not is_team:
        if not pool_rounds and (final or de_real):
            # 협회가 풀을 게시하지 않는 대회는 결손이 아니다 → 정보성 F14
            # (근거: POOL_NOT_PUBLISHED_COMPETITIONS 주석)
            if pool_not_published:
                codes["F14"] = f"협회 풀 미게시 (final {len(final)}, DE {de_real})"
            else:
                codes["F07"] = f"pool 0, final {len(final)}, DE {de_real}"
        if not final and de_scored > 0:
            codes["F10"] = f"DE 점수 {de_scored}건"
    ph = pool_health(pool_rounds)
    if ph:
        codes["F13"] = ph
    champ = _final_champion(de)
    if champ and final:
        first = [n for n, r in zip(names, ranks) if r == 1]
        if first and champ not in first:
            codes["F12"] = f"결승 승자 {champ} ≠ 1위 {first[0]}"

    return {
        "id": ev["id"], "sub_event_cd": ev.get("sub_event_cd"), "event_name": ev.get("event_name"),
        "category": ev.get("category"), "competition_id": ev.get("competition_id"),
        "final": len(final), "pool_rounds": len(pool_rounds), "pool_total": len(ptr),
        "de_real": de_real, "de_scored": de_scored,
        "de_format": (de.get("format") if isinstance(de, dict) else None),
        "codes": codes,
    }


def load_events(cache: Optional[str] = None):
    if cache and os.path.exists(cache):
        d = pickle.load(open(cache, "rb"))
        return d["events"], d["comps"]
    from supabase import create_client
    db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    comps = db.table("competitions").select("id, comp_idx, comp_name, start_date").execute().data
    events, off = [], 0
    while True:
        r = (db.table("events").select("id, competition_id, sub_event_cd, event_name, category, weapon, gender, raw_data")
             .range(off, off + 199).execute().data or [])
        events.extend(r); off += 200
        if len(r) < 200:
            break
    if cache:
        pickle.dump({"events": events, "comps": comps}, open(cache, "wb"))
    return events, comps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, action="append")
    ap.add_argument("--cache", help="이벤트 덤프 pickle (있으면 읽고, 없으면 DB 에서 받아 저장)")
    ap.add_argument("--kfa", action="store_true", help="협회 합산표 대조도 같이 출력")
    ap.add_argument("--list", action="store_true", help="이상 종목을 한 줄씩 출력")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    events, comps = load_events(args.cache)
    comp_by_id = {c["id"]: c for c in comps}
    rows = []
    for ev in events:
        comp = comp_by_id.get(ev.get("competition_id"))
        year = int((comp or {}).get("start_date", "0000")[:4] or 0)
        if args.year and year not in args.year:
            continue
        r = audit_event(ev, (comp or {}).get("comp_name", ""))
        r["year"] = year
        r["comp_idx"] = (comp or {}).get("comp_idx")
        r["comp_name"] = (comp or {}).get("comp_name")
        rows.append(r)

    flagged = [r for r in rows if set(r["codes"]) - INFO_ONLY]
    by_year_rule: Dict[int, Counter] = defaultdict(Counter)
    by_year_total: Counter = Counter()
    by_year_flagged: Counter = Counter()
    by_comp: Dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_year_total[r["year"]] += 1
        if set(r["codes"]) - INFO_ONLY:
            by_year_flagged[r["year"]] += 1
        for c in r["codes"]:
            by_year_rule[r["year"]][c] += 1
            if c not in INFO_ONLY:
                by_comp[f'{r["year"]} {r["comp_idx"]} {r["comp_name"]}'][c] += 1

    print(f"\n총 {len(rows)}종목 중 이상 {len(flagged)}종목 (F11 제외)")
    print("\n연도 × 유형 (종목 수):")
    codes = sorted(RULES)
    print("year  total flagged  " + " ".join(f"{c:>4}" for c in codes))
    for y in sorted(by_year_total):
        print(f"{y}  {by_year_total[y]:5d} {by_year_flagged[y]:7d}  "
              + " ".join(f"{by_year_rule[y].get(c, 0):4d}" for c in codes))
    tot = Counter()
    for y in by_year_rule:
        tot.update(by_year_rule[y])
    print(f"ALL   {sum(by_year_total.values()):5d} {sum(by_year_flagged.values()):7d}  "
          + " ".join(f"{tot.get(c, 0):4d}" for c in codes))

    print("\n대회별 (이상 종목이 있는 대회만, 이상 수 내림차순):")
    comp_rows = sorted(by_comp.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    for k, cnt in comp_rows:
        n_ev = len({r["id"] for r in flagged if f'{r["year"]} {r["comp_idx"]} {r["comp_name"]}' == k})
        print(f"  {k[:60]:60s} 종목 {n_ev:2d} | " + " ".join(f"{c}:{v}" for c, v in sorted(cnt.items())))

    if args.list:
        print("\n이상 종목 목록:")
        for r in sorted(flagged, key=lambda r: (r["year"], r["comp_idx"] or "", r["event_name"] or "")):
            print(f"  {r['year']} {r['comp_idx']} {r['event_name'][:24]:24s} final {r['final']:3d} pool {r['pool_rounds']:2d}/"
                  f"{r['pool_total']:3d} DE {r['de_real']:3d} | " + "; ".join(f"{c}={v}" for c, v in r["codes"].items()))

    kfa = None
    if args.kfa:
        from kfa_selection_compare import compare, print_report
        kfa = compare(events, comps)
        print_report(kfa)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump({"rules": RULES, "total": len(rows), "flagged": len(flagged),
               "by_year": {y: {"total": by_year_total[y], "flagged": by_year_flagged[y],
                               "rules": dict(by_year_rule[y])} for y in sorted(by_year_total)},
               "by_comp": {k: dict(v) for k, v in comp_rows},
               "events": flagged, "kfa": kfa},
              open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
