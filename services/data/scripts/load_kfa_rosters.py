"""협회 공지 첨부 텍스트 → data_kfa_rosters 적재.

입력은 data_kfa_notices.attachments[].text (DB 컬럼)만이다. 파일은 읽지 않는다.

흐름:
  1. ranking_points 공지의 합산표를 전부 파싱해 연도별 '가장 최근 게시' 표만 남긴다
     → seed_rank 조회용 (year, gender, weapon, name) → 순위
  2. national_team / candidate_u25 / youth 공지의 명단표를 파싱한다
     (공문처럼 명단이 아닌 첨부는 종목 머리글이 없어 0건으로 걸러진다)
  3. replacement 공지의 교체 명단을 파싱한다. year 는 그 공지일 이전 가장 최근
     national_team 명단의 연도다 — 협회는 2025.09 선발 명단을 "2026 국가대표"라고도
     부르기 때문에 공지 연도를 쓰면 안 된다.
  4. MEDIA_ROSTERS (언론·SNS 확인분) 를 source_type='media' 로 넣는다
  5. seed_rank 를 채우고 UNIQUE(roster_type, year, weapon, gender, player_name) 로 upsert
  6. roster_type × year × 종목 인원표와 선언 인원 대조 결과를 출력한다

사용법:
    cd services/data
    PYTHONPATH=".:../../packages" python scripts/load_kfa_rosters.py --dry-run
    PYTHONPATH=".:../../packages" python scripts/load_kfa_rosters.py
"""
import argparse
import os
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from loguru import logger
from supabase import create_client

from app.kfa_roster_parser import (
    RosterEntry,
    media_roster_entries,
    parse_ranking_points,
    parse_replacement_notice,
    parse_roster_document,
    ranking_lookup,
)

ROSTER_DOC_TAGS = {"national_team", "candidate_u25", "youth", "kkumnamu"}


def _fetch_notices(db, tags: List[str]) -> List[dict]:
    res = (db.table("data_kfa_notices")
           .select("board_no, title, posted_at, url, tags, attachments")
           .overlaps("tags", tags).order("posted_at").execute())
    return res.data or []


def _to_date(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


def build_ranking_lookup(notices: List[dict]) -> Tuple[Dict[Tuple[int, str, str, str], int], Dict[int, int]]:
    """연도별 가장 최근 합산표만 남겨 (year,gender,weapon,name)→rank. 두 번째 반환은 year→board_no."""
    latest_by_year: Dict[int, dict] = {}
    rows_by_board: Dict[int, list] = {}
    for n in notices:
        if "ranking_points" not in (n.get("tags") or []):
            continue
        rows = []
        for a in n.get("attachments") or []:
            if a.get("text_extracted"):
                rows.extend(parse_ranking_points(a.get("text") or ""))
        if not rows:
            continue
        rows_by_board[n["board_no"]] = rows
        year = Counter(r.year for r in rows).most_common(1)[0][0]
        prev = latest_by_year.get(year)
        if prev is None or (n.get("posted_at") or "") > (prev.get("posted_at") or ""):
            latest_by_year[year] = n
    lookup: Dict[Tuple[int, str, str, str], int] = {}
    source: Dict[int, int] = {}
    for year, n in latest_by_year.items():
        lookup.update(ranking_lookup(rows_by_board[n["board_no"]]))
        source[year] = n["board_no"]
        logger.info(f"합산표 {year}: boardNo {n['board_no']} ({n.get('posted_at')}) {len(rows_by_board[n['board_no']])}행")
    return lookup, source


def collect_entries(notices: List[dict]) -> Tuple[List[dict], List[str]]:
    """명단표·교체 공문 → 적재 행(dict) 목록 + 검증 경고."""
    records: List[dict] = []
    warnings: List[str] = []
    nt_years: List[Tuple[date, int]] = []  # (announced_at, year) — 교체 공지의 연도 결정용

    # 1) 명단표
    for n in notices:
        tags = set(n.get("tags") or [])
        if not (tags & ROSTER_DOC_TAGS):
            continue
        # 지도자 채용 공고·참가신청서에도 종목별 표가 있어 명단표로 오인된다.
        # 실제 명단 공지는 제목에 반드시 '명단'이 있고 채용·견적(procurement)이 아니다.
        if "procurement" in tags or "명단" not in n.get("title", ""):
            continue
        posted = _to_date(n.get("posted_at"))
        for a in n.get("attachments") or []:
            if not a.get("text_extracted"):
                continue
            doc = parse_roster_document(a.get("text") or "")
            if not doc.entries:
                continue
            if not doc.roster_type or doc.roster_type == "unknown":
                warnings.append(f"{n['board_no']} {a['name'][:40]}: 문서 유형 미상 → 건너뜀")
                continue
            if not doc.year:
                warnings.append(f"{n['board_no']} {a['name'][:40]}: 연도 미상 → 건너뜀")
                continue
            for w in doc.warnings:
                warnings.append(f"{n['board_no']} {a['name'][:40]}: {w}")
            note = None
            if a.get("kind") == "hwp":
                note = "HWP 문단 텍스트에서 파싱 (표 구조 없이 셀 순서로 이름·소속 짝지음)"
            if doc.roster_type == "national_team" and posted:
                nt_years.append((posted, doc.year))
            for e in doc.entries:
                records.append(_record(e, n, posted, note))
            logger.info(f"{n['board_no']} {doc.roster_type} {doc.year}: {len(doc.entries)}명 ({a['name'][:40]})")

    # 2) 교체 공문
    nt_years.sort()
    for n in notices:
        if "replacement" not in (n.get("tags") or []):
            continue
        posted = _to_date(n.get("posted_at"))
        year = None
        if posted:
            for d, y in nt_years:
                if d <= posted:
                    year = y
        for a in n.get("attachments") or []:
            if not a.get("text_extracted"):
                continue
            entries = parse_replacement_notice(a.get("text") or "")
            if not entries:
                continue
            if year is None:
                warnings.append(f"{n['board_no']}: 교체 대상 명단 연도를 정할 수 없음 → 건너뜀")
                break
            note = (f"{year}년 선발 국가대표 명단의 결원 교체 (협회 공지 {posted} 게시). "
                    f"협회 본문은 '{posted.year if posted else ''} 국가대표'라 표기하나 명단 기준 연도는 {year}")
            for e in entries:
                e.year = year
                e.note = f"{e.note}; {note}" if e.note else note
                records.append(_record(e, n, posted, None))
            logger.info(f"{n['board_no']} replacement → {year}: {len(entries)}명")
            break

    # 3) 언론·SNS 확인분
    for e in media_roster_entries():
        records.append({
            **asdict(e), "source_board_no": None, "source_url": None,
            "source_type": "media", "announced_at": None,
        })
    return records, warnings


def _record(e: RosterEntry, notice: dict, posted: Optional[date], note: Optional[str]) -> dict:
    d = asdict(e)
    if note and not d.get("note"):
        d["note"] = note
    d.update({
        "source_board_no": notice["board_no"],
        "source_url": notice.get("url"),
        "source_type": "kfa",
        "announced_at": posted.isoformat() if posted else None,
    })
    return d


def fill_team_for_media(records: List[dict]) -> None:
    """media 행의 소속은 같은 이름·종목의 가장 최근 kfa 행에서 가져온다 (없으면 NULL)."""
    latest: Dict[Tuple[str, str, str], Tuple[int, str]] = {}
    for r in records:
        if r["source_type"] != "kfa" or not r.get("team"):
            continue
        k = (r["gender"], r["weapon"], r["player_name"])
        if k not in latest or r["year"] > latest[k][0]:
            latest[k] = (r["year"], r["team"])
    for r in records:
        if r["source_type"] == "media" and not r.get("team"):
            hit = latest.get((r["gender"], r["weapon"], r["player_name"]))
            if hit:
                r["team"] = hit[1]
                r["note"] = f"{r['note']}; 소속은 {hit[0]}년 협회 명단 기준"


def fill_seed_rank(records: List[dict], lookup: Dict, source: Dict[int, int]) -> int:
    hit = 0
    for r in records:
        rank = lookup.get((r["year"], r["gender"], r["weapon"], r["player_name"]))
        if rank is not None:
            r["seed_rank"] = rank
            hit += 1
            src = f"seed_rank = {r['year']}년 협회 합산 랭킹 순위 (boardNo {source.get(r['year'])})"
            r["note"] = f"{r['note']}; {src}" if r.get("note") else src
    return hit


def dedupe(records: List[dict]) -> List[dict]:
    """UNIQUE 키 중복은 뒤의 것(더 최근 공지)으로."""
    out: Dict[Tuple, dict] = {}
    for r in records:
        out[(r["roster_type"], r["year"], r["weapon"], r["gender"], r["player_name"])] = r
    return list(out.values())


def print_summary(records: List[dict]) -> None:
    table = defaultdict(lambda: defaultdict(int))
    for r in records:
        table[(r["roster_type"], r["year"], r["source_type"])][f"{r['gender']}{r['weapon'][0]}"] += 1
    cols = ["남s", "남e", "남f", "여s", "여e", "여f"]
    print("\nroster_type                 year  src    " + "  ".join(f"{c:>3}" for c in cols) + "  total  seed_rank")
    for key in sorted(table):
        row = table[key]
        total = sum(row.values())
        seeded = sum(1 for r in records if (r["roster_type"], r["year"], r["source_type"]) == key and r.get("seed_rank"))
        print(f"{key[0]:<27} {key[1]}  {key[2]:<5}  " + "  ".join(f"{row.get(c, 0):>3}" for c in cols)
              + f"  {total:>5}  {seeded:>5}")


def sync_rosters(db=None, dry_run: bool = False, verbose: bool = False) -> dict:
    """공지 첨부에서 명단을 파싱해 `data_kfa_rosters` 에 upsert. 스케줄러도 이 함수를 쓴다.

    전체를 다시 읽어 upsert 하는 멱등 동작이다 — 새 공지 하나만 들어와도 전체를 다시
    맞추므로, 과거 공지의 파싱이 개선되면 그 효과도 함께 반영된다.
    UNIQUE(roster_type, year, weapon, gender, player_name) 기준 upsert 라 중복이 쌓이지 않는다.
    """
    db = db or create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    notices = _fetch_notices(db, sorted(ROSTER_DOC_TAGS | {"replacement", "ranking_points"}))
    lookup, source = build_ranking_lookup(notices)
    records, warnings = collect_entries(notices)
    fill_team_for_media(records)
    records = dedupe(records)
    seeded = fill_seed_rank(records, lookup, source)

    if verbose:
        print_summary(records)
        if warnings:
            print("\n검증 경고:")
            for w in warnings:
                print("  -", w)
        else:
            print("\n검증 경고 없음 (모든 명단표의 선언 인원 = 파싱 인원)")

    result = {"notices": len(notices), "records": len(records),
              "seeded": seeded, "warnings": warnings[:20], "saved": 0}
    if dry_run:
        return result

    now = datetime.now().isoformat()
    for i in range(0, len(records), 200):
        batch = [{**r, "updated_at": now} for r in records[i:i + 200]]
        db.table("data_kfa_rosters").upsert(
            batch, on_conflict="roster_type,year,weapon,gender,player_name"
        ).execute()
        result["saved"] += len(batch)
    result["total"] = db.table("data_kfa_rosters").select("id", count="exact").execute().count
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    out = sync_rosters(db, dry_run=args.dry_run, verbose=True)
    logger.info(f"대상 공지 {out['notices']}건 / 적재 행 {out['records']}건, "
                f"seed_rank 대조 성공 {out['seeded']}건")
    if args.dry_run:
        print("\n(dry-run: 저장 안 함)")
        return
    logger.info(f"저장 완료: data_kfa_rosters 총 {out.get('total')}행")


if __name__ == "__main__":
    main()
