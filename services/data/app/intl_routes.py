"""국제 트랙 라우트 — FIE 공식 랭킹(한국 선수) + 아시안게임 2026 결과.

server.py 에는 `configure()` 한 번과 `include_router()` 한 줄만 들어간다. 여기서 읽는 표는
data_fie_rankings / data_intl_* 뿐이며 competitions/events/rankings 는 건드리지 않는다
(국내 랭킹과 분리된 축 — 협회도 국내 4개 대회 점수와 FIE 점수를 별도 축으로 둔다).

페이지
    GET /fie-rankings, /{lang}/fie-rankings
    GET /international/asian-games-2026, /{lang}/international/asian-games-2026
API
    GET /api/fie-rankings?season=2027&weapon=E&gender=F&country=KOR&limit=50
    GET /api/international/asian-games-2026?event_key=M.SABRE-------------&country=KOR

라우트 등록 순서가 중요하다: `/api/...` 를 `/{lang}/...` 보다 먼저 두지 않으면
'/api/fie-rankings' 가 lang='api' 로 매칭돼 리다이렉트된다 (2026-09-27 실측 302).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

GAMES = "AG2026"
FIE_SOURCE_HOME = "https://fie.org/athletes"
AG_SOURCE_HOME = "https://results.asiangames2026.org/"
_CACHE_TTL = 600  # 초. 데이터는 하루 1~2회만 바뀐다

WEAPON_KO = {"F": "플뢰레", "E": "에페", "S": "사브르"}
WEAPON_EN = {"F": "Foil", "E": "Épée", "S": "Sabre"}
GENDER_KO = {"F": "여자", "M": "남자"}
GENDER_EN = {"F": "Women", "M": "Men"}
LIST_ORDER = [("F", "F"), ("F", "M"), ("E", "F"), ("E", "M"), ("S", "F"), ("S", "M")]

_KST = timezone(timedelta(hours=9))

# server.py 가 configure() 로 넣어 주는 것들
_deps: Dict[str, Any] = {}
_cache: Dict[str, Any] = {}


def configure(*, templates, get_db: Callable[[], Any], i18n_context: Callable, supported_langs, default_lang: str) -> None:
    _deps.update(templates=templates, get_db=get_db, i18n_context=i18n_context,
                 supported_langs=supported_langs, default_lang=default_lang)


def _db():
    db = _deps["get_db"]()
    if db is None:
        raise RuntimeError("Supabase 클라이언트가 아직 없음")
    return db


def _cached(key: str, loader: Callable[[], Any]) -> Any:
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    value = loader()
    _cache[key] = (now, value)
    return value


def invalidate_cache() -> None:
    _cache.clear()


def _kst(value: Any) -> str:
    """ISO(UTC) → 'YYYY-MM-DD HH:MM KST'."""
    if not value:
        return ""
    try:
        text = str(value).replace("Z", "+00:00")
        if "." in text:
            head, _, tail = text.partition(".")
            digits = "".join(ch for ch in tail if ch.isdigit())
            text = f"{head}.{digits[:6]}{tail[len(digits):]}"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_KST).strftime("%Y-%m-%d %H:%M KST")
    except Exception:
        return str(value)[:16]


def _default_lang(request: Request) -> str:
    cookie = request.cookies.get("lang")
    return cookie if cookie in _deps["supported_langs"] else _deps["default_lang"]


# ─────────────────────────────────────────────────────────────
# FIE 랭킹 — 데이터
# ─────────────────────────────────────────────────────────────
def _fie_seasons(db) -> List[int]:
    res = db.table("data_fie_rankings").select("season").order("season", desc=True).limit(1).execute()
    if not res.data:
        return []
    latest = res.data[0]["season"]
    res2 = db.table("data_fie_rankings").select("season").order("season").limit(1).execute()
    earliest = res2.data[0]["season"]
    return list(range(latest, earliest - 1, -1))


def _fie_season_data(db, season: int, top_n: int = 10) -> Dict[str, Any]:
    kor = (db.table("data_fie_rankings")
           .select("weapon,gender,fie_rank,athlete_name,country,points,results,total_ranked,player_name_ko,player_id,season_label,fetched_at,source_url")
           .eq("season", season).eq("category", "S").eq("country", "KOR")
           .order("fie_rank").execute().data or [])
    top = (db.table("data_fie_rankings")
           .select("weapon,gender,fie_rank,athlete_name,country,points,player_name_ko")
           .eq("season", season).eq("category", "S").lte("fie_rank", top_n)
           .order("fie_rank").execute().data or [])
    lists: Dict[str, Dict[str, Any]] = {}
    for weapon, gender in LIST_ORDER:
        key = f"{weapon}{gender}"
        k_rows = [r for r in kor if r["weapon"] == weapon and r["gender"] == gender]
        t_rows = [r for r in top if r["weapon"] == weapon and r["gender"] == gender]
        meta = k_rows[0] if k_rows else None
        lists[key] = {
            "key": key, "weapon": weapon, "gender": gender,
            "label_ko": f"{GENDER_KO[gender]} {WEAPON_KO[weapon]}",
            "label_en": f"{GENDER_EN[gender]}'s {WEAPON_EN[weapon]}",
            "kor": k_rows, "top": t_rows,
            "total_ranked": meta["total_ranked"] if meta else None,
            "fetched_at": _kst(meta["fetched_at"]) if meta else "",
            "source_url": meta["source_url"] if meta else None,
            "best": k_rows[0] if k_rows else None,
            "top16": sum(1 for r in k_rows if r["fie_rank"] <= 16),
        }
    season_label = next((r["season_label"] for r in kor if r.get("season_label")), f"{season - 1}/{season}")
    return {"season": season, "season_label": season_label, "lists": lists,
            "kor_total": len(kor), "top16_total": sum(l["top16"] for l in lists.values())}


# ─────────────────────────────────────────────────────────────
# 아시안게임 2026 — 데이터
# ─────────────────────────────────────────────────────────────
def _bout_view(b: Dict[str, Any], me: Optional[str]) -> Dict[str, Any]:
    """한국 선수(또는 KOR 팀) 시점으로 '나 vs 상대' 형태로 뒤집는다."""
    i_am_home = (b["home_name"] == me) if me else (b["home_org"] == "KOR")
    mine = "home" if i_am_home else "away"
    opp = "away" if i_am_home else "home"
    result = None
    if b["is_bye"]:
        result = "bye"
    elif b["winner"]:
        result = "W" if b["winner"] == mine else "L"
    return {
        "phase_desc": b["phase_desc"], "is_pool": b["is_pool"], "pool_no": b["pool_no"],
        "my_score": b[f"{mine}_score"], "opp_score": b[f"{opp}_score"],
        "opp_name": b[f"{opp}_name"], "opp_org": b[f"{opp}_org"],
        "result": result, "status": b["status"], "bout_time": b["bout_time"],
    }


def _ag_data(db) -> Dict[str, Any]:
    events = (db.table("data_intl_events").select("*").eq("games", GAMES)
              .order("display_order").execute().data or [])
    if not events:
        return {"events": [], "medals": {"gold": 0, "silver": 0, "bronze": 0, "total": 0}, "medal_rows": [], "fetched_at": ""}
    ids = [e["id"] for e in events]
    results = (db.table("data_intl_results").select("*").in_("event_id", ids)
               .order("rank").execute().data or [])
    bouts = (db.table("data_intl_bouts").select("*").in_("event_id", ids)
             .or_("home_org.eq.KOR,away_org.eq.KOR")
             .order("phase_order").order("unit_key").execute().data or [])

    by_event_results: Dict[int, List[Dict]] = {}
    for r in results:
        by_event_results.setdefault(r["event_id"], []).append(r)
    by_event_bouts: Dict[int, List[Dict]] = {}
    for b in bouts:
        by_event_bouts.setdefault(b["event_id"], []).append(b)

    medal_rows: List[Dict[str, Any]] = []
    out_events: List[Dict[str, Any]] = []
    for e in events:
        rs = by_event_results.get(e["id"], [])
        ranked = [r for r in rs if r["rank"] is not None]
        podium = [r for r in ranked if r["rank"] <= 3]
        kor = [r for r in rs if r["country"] == "KOR"]
        ev_bouts = by_event_bouts.get(e["id"], [])
        paths: Dict[str, List[Dict[str, Any]]] = {}
        for r in kor:
            if e["is_team"]:
                mine = [b for b in ev_bouts if "KOR" in (b["home_org"], b["away_org"])]
            else:
                mine = [b for b in ev_bouts if r["athlete_name"] in (b["home_name"], b["away_name"])]
            paths[r["athlete_name"]] = [_bout_view(b, None if e["is_team"] else r["athlete_name"]) for b in mine]
            if r["medal"]:
                medal_rows.append({"event_name_ko": e["event_name_ko"], "event_name": e["event_name"],
                                   "is_team": e["is_team"], "medal": r["medal"], "athlete_name": r["athlete_name"],
                                   "player_name_ko": r["player_name_ko"], "members": r.get("members") or []})
        out_events.append({
            **e, "podium": podium, "kor": kor, "paths": paths,
            "ranked_count": len(ranked), "fetched_at_kst": _kst(e["fetched_at"]),
        })
    medals = {m: sum(1 for r in medal_rows if r["medal"] == m) for m in ("gold", "silver", "bronze")}
    medals["total"] = sum(medals.values())
    latest = max((e["fetched_at"] for e in events), default=None)
    return {"events": out_events, "medals": medals, "medal_rows": medal_rows, "fetched_at": _kst(latest)}


# ─────────────────────────────────────────────────────────────
# API — 반드시 /{lang}/… 페이지 라우트보다 먼저 등록
# ─────────────────────────────────────────────────────────────
@router.get("/api/fie-rankings")
async def api_fie_rankings(
    season: Optional[int] = None,
    weapon: Optional[str] = Query(None, pattern="^[FES]$"),
    gender: Optional[str] = Query(None, pattern="^[FM]$"),
    country: Optional[str] = Query(None, min_length=3, max_length=3),
    limit: int = Query(100, ge=1, le=2000),
):
    """FIE 개인 랭킹 행. 기본은 최신 시즌·전체 종목·KOR. country=ALL 이면 전 국가."""
    db = _db()
    seasons = _cached("fie:seasons", lambda: _fie_seasons(db))
    if not seasons:
        return {"season": None, "rows": [], "note": "no data"}
    season = season if season in seasons else seasons[0]
    q = (db.table("data_fie_rankings")
         .select("season,season_label,category,weapon,gender,fie_rank,athlete_name,country,points,results,total_ranked,player_name_ko,player_id,fetched_at,source_url")
         .eq("season", season).eq("category", "S"))
    if weapon:
        q = q.eq("weapon", weapon)
    if gender:
        q = q.eq("gender", gender)
    country = (country or "KOR").upper()
    if country != "ALL":
        q = q.eq("country", country)
    rows = q.order("weapon").order("gender").order("fie_rank").limit(limit).execute().data or []
    return {
        "season": season, "seasons": seasons, "count": len(rows), "rows": rows,
        "source": FIE_SOURCE_HOME,
        "note": "FIE 공식 랭킹 스냅샷. 국내 랭킹 포인트와 별도 축. 순위·점수 수치만 저장.",
    }


@router.get("/api/international/asian-games-2026")
async def api_ag2026(event_key: Optional[str] = None, country: Optional[str] = None):
    """종목별 최종순위 상위 3 + (country=KOR 이면) 한국 선수 결과·경기 경로."""
    db = _db()
    data = _cached("ag2026", lambda: _ag_data(db))
    events = data["events"]
    if event_key:
        events = [e for e in events if e["event_key"] == event_key]
    out = []
    for e in events:
        item = {k: e[k] for k in ("event_key", "event_name", "event_name_ko", "weapon", "gender", "is_team",
                                   "start_date", "status", "source_url", "fetched_at")}
        item["podium"] = [{k: r[k] for k in ("rank", "rank_eq", "athlete_name", "country", "medal", "members")} for r in e["podium"]]
        if country and country.upper() == "KOR":
            item["kor"] = [{k: r[k] for k in ("rank", "rank_eq", "athlete_name", "country", "medal", "player_name_ko", "player_id", "members")} for r in e["kor"]]
            item["paths"] = e["paths"]
        out.append(item)
    return {
        "games": GAMES, "events": out, "medals_kor": data["medals"], "fetched_at": data["fetched_at"],
        "source": AG_SOURCE_HOME,
        "note": "Aichi-Nagoya 2026 공식 결과 시스템의 순위·스코어 수치만 저장. 국내 랭킹과 별도 축.",
    }


# ─────────────────────────────────────────────────────────────
# 페이지
# ─────────────────────────────────────────────────────────────
@router.get("/fie-rankings", response_class=HTMLResponse, include_in_schema=False)
async def fie_rankings_redirect(request: Request):
    return RedirectResponse(url=f"/{_default_lang(request)}/fie-rankings", status_code=302)


@router.get("/{lang}/fie-rankings", response_class=HTMLResponse)
async def fie_rankings_page(request: Request, lang: str, season: Optional[int] = None):
    if lang not in _deps["supported_langs"]:
        return RedirectResponse(url=f"/{_deps['default_lang']}/fie-rankings", status_code=302)
    db = _db()
    seasons = _cached("fie:seasons", lambda: _fie_seasons(db))
    if not seasons:
        data = {"season": None, "season_label": "", "lists": {}, "kor_total": 0, "top16_total": 0}
    else:
        if season not in seasons:
            season = seasons[0]
        data = _cached(f"fie:{season}", lambda: _fie_season_data(db, season))
    context = {
        "request": request, "seasons": seasons, "list_order": [f"{w}{g}" for w, g in LIST_ORDER],
        "source_home": FIE_SOURCE_HOME, **data, **_deps["i18n_context"](request, lang),
    }
    return _deps["templates"].TemplateResponse("fie_rankings.html", context)


@router.get("/international/asian-games-2026", response_class=HTMLResponse, include_in_schema=False)
async def ag2026_redirect(request: Request):
    return RedirectResponse(url=f"/{_default_lang(request)}/international/asian-games-2026", status_code=302)


@router.get("/{lang}/international/asian-games-2026", response_class=HTMLResponse)
async def ag2026_page(request: Request, lang: str):
    if lang not in _deps["supported_langs"]:
        return RedirectResponse(url=f"/{_deps['default_lang']}/international/asian-games-2026", status_code=302)
    db = _db()
    data = _cached("ag2026", lambda: _ag_data(db))
    context = {"request": request, "source_home": AG_SOURCE_HOME, **data, **_deps["i18n_context"](request, lang)}
    return _deps["templates"].TemplateResponse("intl_asian_games.html", context)
