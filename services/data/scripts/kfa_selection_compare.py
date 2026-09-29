"""협회(KFA) 국가대표 선발 합산표 vs 우리 DB final_rankings 대조.

협회는 매년 "국가대표 선발을 위한 4개 대회 결과 합산 점수 랭킹 현황" PDF 를 공지한다.
행 형식: `순위 총점 이름 생년월일 소속 [순위 점수]×4`. 4개 열은 대회별 순위·점수이고,
배점은 `ranking/selection_points.rank_to_points` 와 같다 (1:32 2:26 3·4:20 5~8:14 9~16:8
17~32:4 33~64:2 65~96:1 97~128:0.5).

이 표는 우리 final_rankings 의 정답지다. 종목(무기×성별)마다
  · 행별 총점 일치 여부
  · 열(대회)별 순위/점수 일치 여부 — 어느 대회가 틀렸는지 바로 드러난다
  · 상위 N명(사브르 12, 그 외 8) 집합 겹침
을 계산한다. 불일치는 원인별로 분류한다:
  comp_missing        그 대회가 DB 에 종목 자체가 없음 (수집 안 됨)
  name_not_in_ours    협회는 순위가 있는데 우리 final_rankings 에 그 이름이 없음
  kfa_zero_ours_rank  협회 0점(미출전/미기록)인데 우리는 순위를 줌
  rank_diff           양쪽 다 있는데 순위가 다름

표 출처 (게시판 boardNo): 2024=10303, 2025=10578, 2026=10916.

⚠️ 이 스크립트의 합계 수치를 "우리 랭킹의 정확도"로 읽지 말 것 (2026-09-28).
   이것은 **final_rankings 의 순위·점수만** 대조하는 도구다. 선발 규정의 두 규칙이 빠져 있다:
     · 제20조 ② 1호 "예선 뿔을 통과해 DE 에 진출한 선수만 점수" → 풀 탈락자를 우리가
       순위로 갖고 있으면 `kfa_zero_ours_rank` 로 잡힌다(2025 여사브르 27건). 오류가 아니다.
     · 제20조 ③ 동점 규칙(순위 목록 사전식 비교) → 총점만으로 정렬해 동점자 순서가 협회와
       달라진다. 실제로 2025 여사브르 12위를 최혜정(협회와 동일) 대신 김하은으로 내놓는다
       (셋 다 30점 동점).
   국가대표 선발 포인트의 정답 대조는 `ranking/national_team.py` 를 거치는 NT 표 검증으로
   한다 — 그 기준에서는 2025 최종표 97.6%, 2026 98.5%, 6종목 상위 8/12 집합·순서 전부 일치,
   2025 선발 명단 56/56 이다. 이 스크립트는 "어느 대회 칸의 순위가 틀렸나"를 찾는 용도로만 쓴다.
`--fetch` 로 PDF 를 받아 `data/kfa_selection_tables/kfa_{boardNo}_{i}.txt` 로 추출한다.

사용법:
    cd services/data
    PYTHONPATH=".:../../packages" python scripts/kfa_selection_compare.py            # 전체
    PYTHONPATH=".:../../packages" python scripts/kfa_selection_compare.py --year 2025 --verbose
    PYTHONPATH=".:../../packages" python scripts/kfa_selection_compare.py --fetch    # 표 재다운로드
"""
import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from ranking.selection_points import rank_to_points

KFA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "kfa_selection_tables")

# 표별 열 순서 → 대회 comp_idx. 열 제목은 표 안에 있다:
#   2024: "대통령배대회(2024) 김창환배대회(2024) 종목별오픈대회(2024) 국가대표선발대회(2024)"
#   2025: "2025 대통령배 2025 김창환배 2025 오픈대회 2025 국가대표 선발대회"
#   2026: "2026 대통령배 2025 김창환배 2026 오픈대회 2026 국가대표 선발대회"  ← 김창환배는 2025 것
TABLES = {
    2024: {"board": 10303, "columns": ["COMPM00592", "COMPM00597", "COMPM00541", "COMPM00596"],
           "labels": ["대통령배24", "김창환배24", "종목별오픈24", "국대선발24"]},
    2025: {"board": 10578, "columns": ["COMPM00654", "COMPM00658", "COMPM00608", "COMPM00633"],
           "labels": ["대통령배25", "김창환배25", "종목별오픈25", "국대선발25"]},
    2026: {"board": 10916, "columns": ["COMPM00722", "COMPM00658", "COMPM00680", "COMPM00709"],
           "labels": ["대통령배26", "김창환배25", "종목별오픈26", "국대선발26"]},
}

# 한 줄 = 한 행. 뒤에 붙는 숫자 쌍이 대회별 (순위, 점수)다. 빈 칸(미출전)은 PDF 텍스트에서
# 사라지므로 쌍이 4개 미만인 행은 어느 열이 비었는지 알 수 없다 → 총점만 대조하고
# 열별 대조에서는 제외한다(`ambiguous`).
LINE = re.compile(r'^\s*(\d{1,3})\s+(\d{1,3}(?:\.\d)?)\s+([가-힣]{2,5})\s*(\d\d\.\d\d\.\d\d)\s*(.*?)\s*$')
NUM = re.compile(r'^\d+(?:\.\d)?$')
SECTION = re.compile(r'종목\s*:\s*(남자|여자)\s*(사브르|에뻬|에페|플러레|플뢰레)')
WEAPON = {"사브르": "sabre", "에뻬": "epee", "에페": "epee", "플러레": "foil", "플뢰레": "foil"}


def parse_table(path: str) -> Dict[Tuple[str, str], List[dict]]:
    """txt → {(weapon, gender): [row, ...]}.

    pypdf 는 페이지 헤더('종목 : 여자사브르')를 그 페이지의 행 **뒤에** 뱉는다. 그래서
    위치로 섹션을 나누면 한 페이지씩 밀린다. 섹션은 순위가 1로 되돌아오는 지점으로
    나누고, 섹션 이름은 헤더의 등장 순서(중복 제거)로 붙인다. 둘의 개수가 다르면 실패.
    """
    text = open(path, encoding="utf-8").read()
    headers: List[Tuple[str, str]] = []
    for m in SECTION.finditer(text):
        key = (WEAPON[m.group(2)], m.group(1)[0])
        if key not in headers:
            headers.append(key)
    sections: List[List[dict]] = []
    cur: List[dict] = []
    for line in text.splitlines():
        m = LINE.match(line)
        if not m:
            continue
        rank, total, name, birth, tail = m.groups()
        toks = tail.split()
        nums: List[str] = []
        while toks and NUM.match(toks[-1]):
            nums.insert(0, toks.pop())
        if len(nums) % 2 == 1:      # 소속 끝이 숫자인 경우는 없지만, 홀수면 맨 앞을 소속으로 돌린다
            toks.append(nums.pop(0))
        pairs = [(int(float(nums[i])), float(nums[i + 1])) for i in range(0, len(nums), 2)]
        if not pairs or len(pairs) > 4:
            continue
        rank = int(rank)
        if rank == 1 and cur:
            sections.append(cur)
            cur = []
        cur.append({"rank": rank, "total": float(total), "name": name, "birth": birth,
                    "team": " ".join(toks), "per": pairs, "ambiguous": len(pairs) < 4})
    if cur:
        sections.append(cur)
    if len(sections) != len(headers):
        raise ValueError(f"{path}: 섹션 {len(sections)}개 ≠ 헤더 {len(headers)}개 {headers}")
    return {h: rows for h, rows in zip(headers, sections)}


def load_tables(kfa_dir: str = KFA_DIR, years=None) -> Dict[int, Dict[Tuple[str, str], List[dict]]]:
    res = {}
    for year, spec in TABLES.items():
        if years and year not in years:
            continue
        merged: Dict[Tuple[str, str], List[dict]] = {}
        for i in range(0, 4):
            p = os.path.join(kfa_dir, f"kfa_{spec['board']}_{i}.txt")
            if not os.path.exists(p):
                continue
            for k, rows in parse_table(p).items():
                merged.setdefault(k, []).extend(rows)
        if merged:
            res[year] = merged
    return res


def our_ranks(events: List[dict], comps_by_id: Dict[int, dict]) -> Dict[str, Dict[Tuple[str, str], Dict[str, int]]]:
    """{comp_idx: {(weapon, gender): {name: rank}}} — 개인전 final_rankings 만."""
    out: Dict[str, Dict[Tuple[str, str], Dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    for ev in events:
        comp = comps_by_id.get(ev.get("competition_id"))
        if not comp:
            continue
        if ev.get("category") == "단체" or "단체" in (ev.get("event_name") or ""):
            continue
        raw = ev.get("raw_data") or {}
        if isinstance(raw, str):
            raw = json.loads(raw)
        key = (ev.get("weapon"), ev.get("gender"))
        for fr in raw.get("final_rankings") or []:
            n = (fr.get("name") or "").strip()
            try:
                r = int(fr.get("rank") or 0)
            except (TypeError, ValueError):
                continue
            if n and r > 0:
                # 같은 이름이 두 번이면(동명이인) 더 좋은 순위를 둔다 — 협회표도 이름 하나로 적는다
                prev = out[comp["comp_idx"]][key].get(n)
                out[comp["comp_idx"]][key][n] = r if prev is None else min(prev, r)
    return out


def compare(events: List[dict], comps: List[dict], kfa_dir: str = KFA_DIR, years=None) -> dict:
    comps_by_id = {c["id"]: c for c in comps}
    present = {c["comp_idx"] for c in comps
               if any(e.get("competition_id") == c["id"] for e in events)}
    ours = our_ranks(events, comps_by_id)
    tables = load_tables(kfa_dir, years)
    report = {"years": {}}
    for year, sections in sorted(tables.items()):
        spec = TABLES[year]
        yrep = {"columns": spec["columns"], "labels": spec["labels"],
                "comp_in_db": [c in present for c in spec["columns"]], "sections": {}}
        for (weapon, gender), rows in sorted(sections.items()):
            topn = 12 if weapon == "sabre" else 8
            sec = {"rows": len(rows), "total_match": 0, "col_match": [0, 0, 0, 0],
                   "col_rows": [0, 0, 0, 0], "reasons": defaultdict(int), "mismatches": []}
            our_total: Dict[str, float] = defaultdict(float)
            for ci, cidx in enumerate(spec["columns"]):
                for n, r in ours.get(cidx, {}).get((weapon, gender), {}).items():
                    our_total[n] += rank_to_points(r)
            for row in rows:
                ours_sum = 0.0
                row_ok = True
                if row["ambiguous"]:
                    sec["ambiguous"] = sec.get("ambiguous", 0) + 1
                    ours_sum = sum(rank_to_points(r) for r in [
                        ours.get(c, {}).get((weapon, gender), {}).get(row["name"]) for c in spec["columns"]] if r)
                    if abs(ours_sum - row["total"]) < 0.01:
                        sec["total_match"] += 1
                    continue
                for ci, (k_rank, k_pts) in enumerate(row["per"]):
                    cidx = spec["columns"][ci]
                    o_rank = ours.get(cidx, {}).get((weapon, gender), {}).get(row["name"])
                    o_pts = rank_to_points(o_rank) if o_rank else 0.0
                    ours_sum += o_pts
                    sec["col_rows"][ci] += 1
                    if abs(o_pts - k_pts) < 0.01:
                        sec["col_match"][ci] += 1
                        continue
                    row_ok = False
                    if cidx not in present:
                        reason = "comp_missing"
                    elif o_rank is None:
                        reason = "name_not_in_ours"
                    elif k_pts == 0:
                        reason = "kfa_zero_ours_rank"
                    else:
                        reason = "rank_diff"
                    sec["reasons"][reason] += 1
                    sec["mismatches"].append({"col": spec["labels"][ci], "kfa_rank": row["rank"],
                                              "name": row["name"], "kfa": [k_rank, k_pts],
                                              "ours_rank": o_rank, "reason": reason})
                if abs(ours_sum - row["total"]) < 0.01:
                    sec["total_match"] += 1
            kfa_top = [r["name"] for r in rows[:topn]]
            our_top = [n for n, _ in sorted(our_total.items(), key=lambda x: (-x[1], x[0]))[:topn]]
            sec["topn"] = topn
            sec["top_overlap"] = len(set(kfa_top) & set(our_top))
            sec["kfa_top"] = kfa_top
            sec["our_top"] = our_top
            sec["reasons"] = dict(sec["reasons"])
            yrep["sections"][f"{gender}{weapon}"] = sec
        report["years"][year] = yrep
    return report


def print_report(report: dict, verbose: bool = False):
    for year, y in report["years"].items():
        print(f"\n=== {year} 협회 합산표 vs 우리 DB  (열: "
              + ", ".join(f"{l}{'' if ok else '[DB없음]'}" for l, ok in zip(y['labels'], y['comp_in_db'])) + ")")
        tot_rows = tot_match = 0
        col_m = [0, 0, 0, 0]; col_r = [0, 0, 0, 0]
        for name, s in y["sections"].items():
            tot_rows += s["rows"]; tot_match += s["total_match"]
            for i in range(4):
                col_m[i] += s["col_match"][i]; col_r[i] += s["col_rows"][i]
            cols = " ".join(f"{m}/{r}" for m, r in zip(s["col_match"], s["col_rows"]))
            print(f"  {name:8s} 행 {s['rows']:3d} 총점일치 {s['total_match']:3d} "
                  f"| 열별 {cols} (열불명 {s.get('ambiguous', 0)}행) | 상위{s['topn']} 겹침 "
                  f"{s['top_overlap']}/{s['topn']} | 사유 {s['reasons']}")
            if verbose:
                print(f"           협회 상위: {s['kfa_top']}")
                print(f"           우리 상위: {s['our_top']}")
                for mm in s["mismatches"][:12]:
                    print(f"           - {mm}")
        pct = tot_match / tot_rows * 100 if tot_rows else 0
        print(f"  합계: 총점 일치 {tot_match}/{tot_rows} ({pct:.1f}%) | 열별 "
              + " ".join(f"{l} {m}/{r}" for l, m, r in zip(y["labels"], col_m, col_r)))


async def fetch_tables(kfa_dir: str = KFA_DIR):
    """협회 공지 게시판에서 PDF 를 받아 txt 로 추출한다."""
    from pypdf import PdfReader
    from scraper.client import KFFClient
    os.makedirs(kfa_dir, exist_ok=True)
    async with KFFClient() as c:
        for year, spec in TABLES.items():
            b = spec["board"]
            body = await c._get(f"/board/view?code=notice&boardNo={b}&repNo=0&masterNo={b}&pageNum=1")
            urls = list(dict.fromkeys(re.findall(
                r'href="(https?://fencing\.sports\.or\.kr/upload_fencing/[^"]+)"', body)))
            for i, u in enumerate(urls):
                async with c._session.get(u) as r:
                    data = await r.read()
                pdf = os.path.join(kfa_dir, f"kfa_{b}_{i}.pdf")
                open(pdf, "wb").write(data)
                txt = "\n".join((pg.extract_text() or "") for pg in PdfReader(pdf).pages)
                open(os.path.join(kfa_dir, f"kfa_{b}_{i}.txt"), "w", encoding="utf-8").write(txt)
                print(f"{year}: {pdf} ({len(data)} bytes, {len(txt)} chars)")


def load_db():
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
    return events, comps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, action="append")
    ap.add_argument("--kfa-dir", default=KFA_DIR)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out", help="JSON 리포트 저장 경로")
    args = ap.parse_args()
    if args.fetch:
        asyncio.run(fetch_tables(args.kfa_dir))
    events, comps = load_db()
    rep = compare(events, comps, args.kfa_dir, args.year)
    print_report(rep, args.verbose)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        json.dump(rep, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
