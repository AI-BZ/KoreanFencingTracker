"""FIE 공식 개인 랭킹 수집 → data_fie_rankings.

국내 랭킹과 완전히 분리된 트랙이다. competitions/events 에는 아무것도 쓰지 않는다.

실측 (2026-09-27):
  * 페이지: https://fie.org/athletes/detailed-ranking?season=2027&weapon=E&gender=F&category=S&type=I
    - 옛 주소 /athletes/general-ranks/ 는 404.
    - Nuxt SSR 로 <table class="dr-table"> 가 통째로 내려온다 (982행, 1.3MB). 페이지네이션 없음.
    - 열: Rank | Name | Nat. | 대회별 점수(가변, 버린 점수는 "(14.000)" + class dr-discarded) | Total points
    - JSON API 는 발견하지 못함 (/_fie/detailed-ranking 404).
  * season 은 FIE 표기: 2027 = 2026/2027 시즌 (9월 시작). h1 에 "Season 2026/2027" 원문.
  * robots.txt: "User-Agent: * / Disallow:" (전체 허용). 이용약관 본문은 클라이언트 렌더라
    SSR 에서 못 읽었고, 푸터 저작권 문구만 확인 ("No part of this site may be reproduced…").
    → 순위·점수 수치만 저장, 요청 간격 1.5초 이상, 주 1회.

사용:
    PYTHONPATH=".:../../packages" python scraper/fie_ranking.py            # 현재+직전 시즌 6종목
    PYTHONPATH=".:../../packages" python scraper/fie_ranking.py --season 2027 --weapon S --gender M
    PYTHONPATH=".:../../packages" python scraper/fie_ranking.py --rematch   # 재수집 없이 선수 매칭만
"""

from __future__ import annotations

import argparse
import html as html_lib
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from loguru import logger

from app.intl_player_match import IntlPlayerMatcher, summarize_matches

BASE_URL = "https://fie.org/athletes/detailed-ranking"
USER_AGENT = "Mozilla/5.0 (compatible; FencingMind/1.0; +https://data.fencingmind.ai)"
WEAPONS = ("F", "E", "S")
GENDERS = ("F", "M")
CATEGORY = "S"          # 시니어만. 협회 규정의 FIE 랭킹 가산은 시니어 개인전 기준
RANK_TYPE = "I"         # 개인전
REQUEST_DELAY = 1.5     # 초


def current_fie_season(today: Optional[date] = None) -> int:
    """FIE 시즌 표기. 9월부터 다음 해 번호를 쓴다 (2026-09 → 2027)."""
    today = today or date.today()
    return today.year + 1 if today.month >= 9 else today.year


def build_url(season: int, weapon: str, gender: str, category: str = CATEGORY) -> str:
    return f"{BASE_URL}?season={season}&weapon={weapon}&gender={gender}&category={category}&type={RANK_TYPE}"


# ─────────────────────────────────────────────────────────────
# 파싱
# ─────────────────────────────────────────────────────────────
_TABLE_RE = re.compile(r'<table class="dr-table".*?</table>', re.S)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<(t[hd])([^>]*)>(.*?)</t[hd]>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_SEASON_LABEL_RE = re.compile(r"Season\s+(\d{4}/\d{4})")


def _text(fragment: str) -> str:
    return html_lib.unescape(_TAG_RE.sub("", fragment)).strip()


def _points(text: str) -> Optional[float]:
    t = text.strip().strip("()").replace(",", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_ranking_html(page_html: str) -> Dict[str, Any]:
    """→ {season_label, columns:[...], rows:[{rank, name, country, points, results}]}"""
    m = _TABLE_RE.search(page_html)
    if not m:
        raise ValueError("dr-table 을 찾지 못함 — 페이지 구조가 바뀌었을 수 있음")
    rows_raw = _ROW_RE.findall(m.group(0))
    if not rows_raw:
        raise ValueError("표에 행이 없음")

    header = [(_text(c[2]), c[1]) for c in _CELL_RE.findall(rows_raw[0])]
    labels = [h[0] for h in header]
    if len(labels) < 4 or labels[0] != "Rank" or labels[-1] != "Total points":
        raise ValueError(f"예상 밖의 헤더: {labels[:3]} … {labels[-1:]}")
    comp_labels = labels[3:-1]

    rows: List[Dict[str, Any]] = []
    for raw in rows_raw[1:]:
        cells = _CELL_RE.findall(raw)
        if len(cells) != len(labels):
            logger.warning(f"열 개수 불일치 ({len(cells)} != {len(labels)}) — 행 건너뜀")
            continue
        rank_txt = _text(cells[0][2])
        if not rank_txt.isdigit():
            logger.warning(f"숫자가 아닌 순위 '{rank_txt}' — 행 건너뜀")
            continue
        results = []
        for label, (_, attrs, body) in zip(comp_labels, cells[3:-1]):
            pts = _points(_text(body))
            if pts is None:
                continue
            results.append({"label": label, "points": pts, "discarded": "dr-discarded" in attrs})
        rows.append({
            "rank": int(rank_txt),
            "name": _text(cells[1][2]),
            "country": _text(cells[2][2]),
            "points": _points(_text(cells[-1][2])),
            "results": results,
        })

    label_m = _SEASON_LABEL_RE.search(_TAG_RE.sub(" ", page_html))
    return {
        "season_label": label_m.group(1) if label_m else None,
        "columns": comp_labels,
        "rows": rows,
    }


def fetch_ranking(season: int, weapon: str, gender: str, client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    url = build_url(season, weapon, gender)
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        parsed = parse_ranking_html(resp.text)
        parsed["source_url"] = url
        return parsed
    finally:
        if own:
            client.close()


# ─────────────────────────────────────────────────────────────
# 저장
# ─────────────────────────────────────────────────────────────
def _db():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def store_ranking(db, season: int, weapon: str, gender: str, parsed: Dict[str, Any],
                  matcher: Optional[IntlPlayerMatcher] = None) -> Dict[str, Any]:
    """목록 하나를 upsert 하고, 이번 수집에 없던 행(탈락자)은 지운다."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = parsed["rows"]
    total = len(rows)
    payload: List[Dict[str, Any]] = []
    seen: set = set()
    match_log: List[Dict[str, Any]] = []
    unmatched: List[Tuple[int, str]] = []
    for r in rows:
        if r["name"] in seen:
            # 이름이 UNIQUE 키라 동명 2명이 한 목록에 있으면 뒤 사람은 못 담는다 — 보고만 한다
            logger.warning(f"[{season} {weapon}{gender}] 동명 중복 '{r['name']}' rank {r['rank']} 건너뜀")
            continue
        seen.add(r["name"])
        row = {
            "season": season, "season_label": parsed.get("season_label"),
            "category": CATEGORY, "weapon": weapon, "gender": gender,
            "fie_rank": r["rank"], "athlete_name": r["name"], "country": r["country"],
            "points": r["points"], "results": r["results"], "total_ranked": total,
            "player_name_ko": None, "player_id": None,
            "fetched_at": fetched_at, "source_url": parsed["source_url"],
        }
        if matcher and r["country"] == "KOR":
            mres = matcher.match(r["name"], "KOR")
            row["player_name_ko"] = mres["player_name_ko"]
            row["player_id"] = mres["player_id"]
            match_log.append(mres)
            if not mres["player_name_ko"]:
                unmatched.append((r["rank"], r["name"]))
        payload.append(row)

    for i in range(0, len(payload), 500):
        db.table("data_fie_rankings").upsert(
            payload[i:i + 500], on_conflict="season,category,weapon,gender,athlete_name"
        ).execute()
    stale = (
        db.table("data_fie_rankings").delete()
        .eq("season", season).eq("category", CATEGORY).eq("weapon", weapon).eq("gender", gender)
        .lt("fetched_at", fetched_at).execute()
    )
    return {
        "season": season, "weapon": weapon, "gender": gender,
        "rows": len(payload), "kor": sum(1 for r in rows if r["country"] == "KOR"),
        "removed_stale": len(stale.data or []),
        "match": summarize_matches(match_log), "unmatched": unmatched,
    }


def refresh_fie_rankings(db=None, seasons: Optional[List[int]] = None,
                         weapons=WEAPONS, genders=GENDERS, delay: float = REQUEST_DELAY,
                         dry_run: bool = False) -> Dict[str, Any]:
    """현재 + 직전 시즌 × 6종목. 스케줄러(주 1회)와 CLI 가 같이 쓴다."""
    db = db or (None if dry_run else _db())
    seasons = seasons or [current_fie_season(), current_fie_season() - 1]
    matcher = IntlPlayerMatcher(db) if db else None
    summary: List[Dict[str, Any]] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True) as client:
        first = True
        for season in seasons:
            for weapon in weapons:
                for gender in genders:
                    if not first:
                        time.sleep(delay)
                    first = False
                    try:
                        parsed = fetch_ranking(season, weapon, gender, client)
                    except Exception as e:
                        logger.error(f"FIE {season} {weapon}{gender} 수집 실패: {e}")
                        summary.append({"season": season, "weapon": weapon, "gender": gender, "error": str(e)})
                        continue
                    if dry_run:
                        kor = [r for r in parsed["rows"] if r["country"] == "KOR"]
                        summary.append({"season": season, "weapon": weapon, "gender": gender,
                                        "rows": len(parsed["rows"]), "kor": len(kor),
                                        "season_label": parsed.get("season_label")})
                        continue
                    summary.append(store_ranking(db, season, weapon, gender, parsed, matcher))
    for s in summary:
        logger.info(f"FIE {s}")
    return {"lists": summary, "fetched_at": datetime.now(timezone.utc).isoformat()}


def rematch_players(db=None) -> Dict[str, Any]:
    """재수집 없이 KOR 행의 player_name_ko/player_id 만 다시 채운다 (overrides 갱신 후)."""
    db = db or _db()
    matcher = IntlPlayerMatcher(db)
    res = db.table("data_fie_rankings").select("id,athlete_name").eq("country", "KOR").execute()
    log = []
    unmatched = set()
    for row in res.data or []:
        m = matcher.match(row["athlete_name"], "KOR")
        log.append(m)
        if not m["player_name_ko"]:
            unmatched.add(row["athlete_name"])
        db.table("data_fie_rankings").update(
            {"player_name_ko": m["player_name_ko"], "player_id": m["player_id"]}
        ).eq("id", row["id"]).execute()
    return {"rows": len(log), "match": summarize_matches(log), "unmatched": sorted(unmatched)}


def main() -> None:
    ap = argparse.ArgumentParser(description="FIE 랭킹 수집")
    ap.add_argument("--season", type=int, action="append", help="FIE 시즌 표기 (예: 2027). 반복 가능")
    ap.add_argument("--weapon", choices=WEAPONS)
    ap.add_argument("--gender", choices=GENDERS)
    ap.add_argument("--dry-run", action="store_true", help="저장하지 않고 행 수만 출력")
    ap.add_argument("--rematch", action="store_true", help="재수집 없이 선수 매칭만 다시")
    args = ap.parse_args()
    if args.rematch:
        print(rematch_players())
        return
    out = refresh_fie_rankings(
        seasons=args.season,
        weapons=(args.weapon,) if args.weapon else WEAPONS,
        genders=(args.gender,) if args.gender else GENDERS,
        dry_run=args.dry_run,
    )
    for s in out["lists"]:
        print(s)


if __name__ == "__main__":
    main()
