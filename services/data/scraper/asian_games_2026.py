"""2026 아이치·나고야 아시안게임 펜싱 결과 수집 → data_intl_events / data_intl_results / data_intl_bouts.

국내 랭킹과 완전히 분리된 트랙이다. competitions/events 에는 아무것도 쓰지 않는다.

실측 (2026-09-27):
  * 백엔드(Bornan Sports): https://back.results.asiangames2026.org/s/AG2026/en/FEN/...
    응답은 content-type 이 JSON 이지만 실제로는 zlib 압축 바이트를 UTF-8 로 다시 인코딩한
    것이라 `zlib.decompress(raw.decode("utf-8").encode("latin-1"))` 로 풀어야 한다.
    - /disc/data                 종목 12개 (Events[].EvKey, Desc, IsTeam, Order)
    - /final-rank/{EvKey}        Competitors[]: Reg, Rk, RkEq, Name, Org, BirthDateRaw, Medal(ME_GOLD…), IRM,
                                 단체전은 Members[] (Name, Reg, BirthDateRaw)
    - /brackets/{EvKey}          [ {Code:'FNL', Phases:[{Code, Desc, Matches:[{Home,Away,Info}]}]} ]
                                 Home/Away: Name, Org, Res(점수 문자열), Win. Info: Key, Status, IsBye, DateTimeRaw
                                 단체전 동메달 결정전 없음 (준결승 패자 2명 동메달)
    - /groups/{EvKey}            개인전 풀. Groups[].Matches[]: Key, PoolRound, Home/Away(Result). 단체전은 빈 목록
    인증 없음. 프론트에 Cloudflare Turnstile 이 있으나 백엔드 직접 호출은 통과.
  * 운용 원칙: 순위·대진·스코어 수치만 저장. 사진·텍스트·해설 복제 금지. 출처 URL 행마다 기록.
    요청 간격 1초 이상, 하루 1~2회. 전체 미러링 아님 — 펜싱 종목 12개만.

사용:
    PYTHONPATH=".:../../packages" python scraper/asian_games_2026.py             # 12종목 전체
    PYTHONPATH=".:../../packages" python scraper/asian_games_2026.py --event M.SABRE-------------
    PYTHONPATH=".:../../packages" python scraper/asian_games_2026.py --rematch    # 선수 매칭만 다시
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import zlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from loguru import logger

from app.intl_player_match import IntlPlayerMatcher, summarize_matches

GAMES = "AG2026"
DISCIPLINE = "FEN"
BACKEND = "https://back.results.asiangames2026.org/s/AG2026/en/FEN"
PUBLIC_SITE = "https://results.asiangames2026.org/"
USER_AGENT = "Mozilla/5.0 (compatible; FencingMind/1.0; +https://data.fencingmind.ai)"
REQUEST_DELAY = 1.2

_MEDAL = {"ME_GOLD": "gold", "ME_SILVER": "silver", "ME_BRONZE": "bronze"}
_WEAPON_KO = {"EPEE": "에페", "FOIL": "플뢰레", "SABRE": "사브르", "SABR": "사브르"}
_POOL_NO_RE = re.compile(r"Pool\s+(\d+)")


# ─────────────────────────────────────────────────────────────
# 클라이언트
# ─────────────────────────────────────────────────────────────
class AGClient:
    def __init__(self, delay: float = REQUEST_DELAY):
        self.http = httpx.Client(headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                                 timeout=60, follow_redirects=True)
        self.delay = delay
        self._last = 0.0

    def close(self) -> None:
        self.http.close()

    def get(self, path: str) -> Any:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        resp = self.http.get(BACKEND + path)
        self._last = time.monotonic()
        resp.raise_for_status()
        return decode_payload(resp.content)


def decode_payload(raw: bytes) -> Any:
    """zlib 바이트를 UTF-8 로 재인코딩한 응답을 되돌린다. 평문 JSON 이면 그대로."""
    try:
        return json.loads(zlib.decompress(raw.decode("utf-8").encode("latin-1")))
    except Exception:
        return json.loads(raw)


# ─────────────────────────────────────────────────────────────
# 변환
# ─────────────────────────────────────────────────────────────
def parse_event_key(ev_key: str) -> Dict[str, Any]:
    """'W.TEAMEPEE----------' → gender F, weapon E, is_team True, 한국어 이름."""
    code = ev_key.rstrip("-")
    gender_c, _, rest = code.partition(".")
    is_team = rest.startswith("TEAM")
    wcode = rest[4:] if is_team else rest
    weapon = {"EPEE": "E", "FOIL": "F", "SABRE": "S", "SABR": "S"}.get(wcode)
    gender = "F" if gender_c == "W" else "M"
    name_ko = f"{'여자' if gender == 'F' else '남자'} {_WEAPON_KO.get(wcode, wcode)} {'단체' if is_team else '개인'}"
    return {"gender": gender, "weapon": weapon, "is_team": is_team, "event_name_ko": name_ko}


def _int(s: Any) -> Optional[int]:
    if s is None:
        return None
    t = str(s).strip()
    return int(t) if t.lstrip("-").isdigit() else None


def _date(s: Any) -> Optional[str]:
    t = (s or "").strip()
    return t[:10] if len(t) >= 10 else None


def _side(side: Dict[str, Any]) -> Dict[str, Any]:
    org = (side.get("Org") or "").strip()
    return {
        "name": side.get("Name") or None,
        "org": org[:3] if org and org != "BYE" else None,
        "score": _int(side.get("Res") if "Res" in side else side.get("Result")),
        "win": bool(side.get("Win")),
    }


def bracket_bouts(brackets: Any, event_key: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    order = 100  # 풀(1~99) 뒤에 오도록
    for block in brackets or []:
        for phase in block.get("Phases", []):
            order += 1
            for m in phase.get("Matches", []):
                info = m.get("Info", {})
                h, a = _side(m.get("Home", {})), _side(m.get("Away", {}))
                winner = "home" if h["win"] else ("away" if a["win"] else None)
                out.append({
                    "unit_key": info.get("Key") or f"{phase.get('Code')}.{len(out):06d}",
                    "phase_code": phase.get("Code"), "phase_desc": phase.get("Desc"),
                    "phase_order": order, "is_pool": False, "pool_no": None,
                    "home_name": h["name"], "home_org": h["org"], "home_score": h["score"],
                    "away_name": a["name"], "away_org": a["org"], "away_score": a["score"],
                    "winner": winner, "is_bye": bool(info.get("IsBye")),
                    "status": (info.get("Status") or "").lower() or None,
                    "bout_time": info.get("DateTimeRaw") or None,
                })
    return out


def pool_bouts(groups: Any) -> List[Dict[str, Any]]:
    """/groups 는 한 경기를 두 선수 시점으로 두 번 준다 (Home/Away 뒤집힘, Key 동일).
    실측 여자 에페: 162건 중 고유 Key 81건. 첫 등장만 남긴다."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for gi, g in enumerate((groups or {}).get("Groups", []) if isinstance(groups, dict) else []):
        pm = _POOL_NO_RE.search(g.get("DescA") or g.get("Desc") or "")
        pool_no = int(pm.group(1)) if pm else gi + 1
        for m in g.get("Matches", []):
            if not m.get("Key") or m["Key"] in seen:
                continue
            seen.add(m["Key"])
            h, a = _side(m.get("Home", {})), _side(m.get("Away", {}))
            winner = None
            if h["score"] is not None and a["score"] is not None and h["score"] != a["score"]:
                winner = "home" if h["score"] > a["score"] else "away"
            out.append({
                "unit_key": m.get("Key"), "phase_code": g.get("Key"),
                "phase_desc": g.get("DescA") or g.get("Desc"), "phase_order": pool_no,
                "is_pool": True, "pool_no": pool_no,
                "home_name": h["name"], "home_org": h["org"], "home_score": h["score"],
                "away_name": a["name"], "away_org": a["org"], "away_score": a["score"],
                "winner": winner, "is_bye": False,
                "status": "official" if winner else None,
                "bout_time": m.get("DateTimeRaw") or None,
            })
    return out


def event_status(final_rank: Dict[str, Any], bouts: List[Dict[str, Any]]) -> str:
    comps = (final_rank or {}).get("Competitors") or []
    ranked = [c for c in comps if _int(c.get("Rk"))]
    last = [b for b in bouts if not b["is_pool"] and b["phase_code"] and b["phase_code"].endswith(".FNL-")]
    if ranked and any(b["status"] == "official" for b in last):
        return "official"
    if bouts and any(b["status"] == "official" or b["home_score"] is not None for b in bouts):
        return "in_progress"
    return "scheduled"


# ─────────────────────────────────────────────────────────────
# 저장
# ─────────────────────────────────────────────────────────────
def _db():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def _match(matcher: Optional[IntlPlayerMatcher], name: str, org: str, log: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not matcher or org != "KOR":
        return {"player_name_ko": None, "player_id": None}
    m = matcher.match(name, "KOR")
    log.append({**m, "name": name})
    return {"player_name_ko": m["player_name_ko"], "player_id": m["player_id"]}


def store_event(db, ev: Dict[str, Any], final_rank: Dict[str, Any], bouts: List[Dict[str, Any]],
                matcher: Optional[IntlPlayerMatcher], start_date: Optional[str]) -> Dict[str, Any]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    ev_key = ev["EvKey"]
    meta = parse_event_key(ev_key)
    status = event_status(final_rank, bouts)
    ev_row = {
        "games": GAMES, "discipline": DISCIPLINE, "event_key": ev_key,
        "event_name": ev.get("Desc") or ev_key, "event_name_ko": meta["event_name_ko"],
        "weapon": meta["weapon"], "gender": meta["gender"], "is_team": meta["is_team"],
        "display_order": ev.get("Order"), "start_date": start_date, "status": status,
        "source_url": f"{BACKEND}/final-rank/{ev_key}", "fetched_at": fetched_at,
    }
    res = db.table("data_intl_events").upsert(ev_row, on_conflict="games,event_key").execute()
    event_id = res.data[0]["id"]

    match_log: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    for c in (final_rank or {}).get("Competitors") or []:
        org = (c.get("Org") or "")[:3]
        name = c.get("Name") or ""
        members = []
        for mb in c.get("Members") or []:
            mm = _match(matcher, mb.get("Name") or "", org, match_log)
            members.append({"name": mb.get("Name"), "reg_id": mb.get("Reg"),
                            "birth_date": _date(mb.get("BirthDateRaw")),
                            "substitute": bool(mb.get("Substitute")), **mm})
        pm = {"player_name_ko": None, "player_id": None} if meta["is_team"] else _match(matcher, name, org, match_log)
        results.append({
            "event_id": event_id, "reg_id": c.get("Reg") or name, "rank": _int(c.get("Rk")),
            "rank_eq": bool(c.get("RkEq")), "athlete_name": name, "country": org,
            "birth_date": _date(c.get("BirthDateRaw")), "medal": _MEDAL.get(c.get("Medal") or ""),
            "is_team": meta["is_team"], "members": members, "irm": (c.get("IRM") or None),
            **pm, "fetched_at": fetched_at,
        })
    if results:
        db.table("data_intl_results").upsert(results, on_conflict="event_id,reg_id").execute()
        db.table("data_intl_results").delete().eq("event_id", event_id).lt("fetched_at", fetched_at).execute()

    bout_rows = [{"event_id": event_id, **b, "fetched_at": fetched_at} for b in bouts if b.get("unit_key")]
    for i in range(0, len(bout_rows), 500):
        db.table("data_intl_bouts").upsert(bout_rows[i:i + 500], on_conflict="event_id,unit_key").execute()
    if bout_rows:
        db.table("data_intl_bouts").delete().eq("event_id", event_id).lt("fetched_at", fetched_at).execute()

    kor_results = [r for r in results if r["country"] == "KOR"]
    return {
        "event_key": ev_key, "event_id": event_id, "status": status,
        "ranked": len(results), "bouts": len(bout_rows),
        "pool_bouts": sum(1 for b in bouts if b["is_pool"]),
        "kor": [(r["rank"], r["athlete_name"], r["medal"]) for r in kor_results],
        "match": summarize_matches(match_log),
        "unmatched": sorted({m["name"] for m in match_log if not m["player_name_ko"]}),
    }


def refresh_asian_games(db=None, event_keys: Optional[List[str]] = None, delay: float = REQUEST_DELAY,
                        dry_run: bool = False) -> Dict[str, Any]:
    """12종목 최종순위·대진·풀 적재. 스케줄러(대회 기간 하루 2회)와 CLI 가 같이 쓴다."""
    db = db or (None if dry_run else _db())
    matcher = IntlPlayerMatcher(db) if db else None
    client = AGClient(delay=delay)
    summary: List[Dict[str, Any]] = []
    days: List[Any] = []
    try:
        disc = client.get("/disc/data")
        events = disc.get("Events") or []
        # 일자별 첫 유닛 시각으로 종목 시작일을 알 수 있지만 호출이 많아진다. Days 만 기록해 둔다.
        days = [d.get("DateRaw") or d.get("Date") for d in disc.get("Days") or []]
        if event_keys:
            events = [e for e in events if e["EvKey"] in event_keys]
        for ev in events:
            key = ev["EvKey"]
            try:
                final_rank = client.get(f"/final-rank/{key}")
                brackets = client.get(f"/brackets/{key}")
                groups = client.get(f"/groups/{key}") if not ev.get("IsTeam") else {}
            except Exception as e:
                logger.error(f"AG {key} 수집 실패: {e}")
                summary.append({"event_key": key, "error": str(e)})
                continue
            bouts = pool_bouts(groups) + bracket_bouts(brackets, key)
            times = sorted(b["bout_time"][:10] for b in bouts if b.get("bout_time"))
            start_date = times[0] if times else None
            if dry_run:
                comps = (final_rank or {}).get("Competitors") or []
                summary.append({"event_key": key, "status": event_status(final_rank, bouts),
                                "ranked": len(comps), "bouts": len(bouts), "start_date": start_date,
                                "kor": [(c.get("Rk"), c.get("Name"), c.get("Medal")) for c in comps if c.get("Org") == "KOR"]})
                continue
            summary.append(store_event(db, ev, final_rank, bouts, matcher, start_date))
    finally:
        client.close()
    for s in summary:
        logger.info(f"AG {s}")
    return {"events": summary, "days": days, "fetched_at": datetime.now(timezone.utc).isoformat()}


def rematch_players(db=None) -> Dict[str, Any]:
    """재수집 없이 KOR 행(개인 + 단체 멤버)의 매칭만 다시 채운다 (overrides 갱신 후)."""
    db = db or _db()
    matcher = IntlPlayerMatcher(db)
    ev = db.table("data_intl_events").select("id").eq("games", GAMES).execute()
    ids = [e["id"] for e in ev.data or []]
    log: List[Dict[str, Any]] = []
    for eid in ids:
        rows = db.table("data_intl_results").select("id,athlete_name,is_team,members").eq("event_id", eid).eq("country", "KOR").execute()
        for r in rows.data or []:
            upd: Dict[str, Any] = {}
            if r["is_team"]:
                members = []
                for mb in r.get("members") or []:
                    m = matcher.match(mb.get("name") or "", "KOR")
                    log.append({**m, "name": mb.get("name")})
                    members.append({**mb, "player_name_ko": m["player_name_ko"], "player_id": m["player_id"]})
                upd["members"] = members
            else:
                m = matcher.match(r["athlete_name"], "KOR")
                log.append({**m, "name": r["athlete_name"]})
                upd = {"player_name_ko": m["player_name_ko"], "player_id": m["player_id"]}
            db.table("data_intl_results").update(upd).eq("id", r["id"]).execute()
    return {"rows": len(log), "match": summarize_matches(log),
            "unmatched": sorted({m["name"] for m in log if not m["player_name_ko"]})}


def main() -> None:
    ap = argparse.ArgumentParser(description="아시안게임 2026 펜싱 결과 수집")
    ap.add_argument("--event", action="append", help="EvKey (예: M.SABRE-------------). 반복 가능")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rematch", action="store_true")
    args = ap.parse_args()
    if args.rematch:
        print(rematch_players())
        return
    out = refresh_asian_games(event_keys=args.event, dry_run=args.dry_run)
    for s in out["events"]:
        print(s)


if __name__ == "__main__":
    main()
