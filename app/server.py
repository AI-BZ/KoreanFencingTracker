"""
Korean Fencing Tracker - FastAPI 웹 서버
선수 중심 검색 + 필터 기반 UI
포트: 내부 71, 외부 7171
"""
import os
import json
import re
from datetime import date, datetime
from typing import List, Optional, Dict, Any, Set
from pathlib import Path
from collections import defaultdict

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from loguru import logger

# 랭킹 계산기
from ranking.calculator import (
    RankingCalculator,
    AGE_GROUP_CODES,
    CATEGORY_CODES,
    CATEGORY_APPLICABLE_AGE_GROUPS,
)

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATIC_DIR = PROJECT_ROOT / "static"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# FastAPI 앱
app = FastAPI(
    title="Korean Fencing Tracker",
    description="대한펜싱협회 대회 결과 추적 사이트 - 선수 중심",
    version="2.0.0"
)

# 정적 파일 및 템플릿
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 데이터 저장소 (메모리 캐시)
_data_cache: Dict[str, Any] = {}
_player_index: Dict[str, List[Dict]] = {}  # 선수별 전적 인덱스
_filter_options: Dict[str, Set] = {}  # 필터 옵션 캐시
_ranking_calculator: Optional[RankingCalculator] = None  # 랭킹 계산기


# ==================== Pydantic Models ====================

class FilterOptions(BaseModel):
    weapons: List[str]
    genders: List[str]
    age_groups: List[str]
    years: List[int]
    event_types: List[str]
    categories: List[str] = []  # 전문/동호인


class RankingEntry(BaseModel):
    """랭킹 항목"""
    rank: int
    name: str
    teams: List[str]
    points: float
    competitions: int
    gold: int
    silver: int
    bronze: int
    best_results: List[Dict] = []


class RankingResponse(BaseModel):
    """랭킹 응답"""
    weapon: str
    gender: str
    age_group: str
    age_group_name: str
    category: Optional[str] = None
    category_name: Optional[str] = None
    total: int
    rankings: List[RankingEntry]


class EventSummary(BaseModel):
    event_cd: str
    sub_event_cd: str
    name: str
    weapon: str
    gender: str
    age_group: str
    event_type: str
    competition_name: str
    competition_date: str
    year: int


class PlayerRecord(BaseModel):
    rank: Optional[int]
    competition_name: str
    competition_date: str
    event_name: str
    weapon: str
    gender: str
    age_group: str
    event_type: str
    team: str
    win_rate: str = ""
    year: int


class PlayerProfile(BaseModel):
    name: str
    teams: List[str]
    total_records: int
    records: List[PlayerRecord]
    stats: Dict[str, Any]


class CompetitionSummary(BaseModel):
    event_cd: str
    name: str
    start_date: Optional[str]
    end_date: Optional[str]
    status: str
    location: str = ""
    event_count: int = 0
    year: int = 0


# ==================== Data Loading & Indexing ====================

def extract_age_group(event_name: str) -> str:
    """종목명에서 연령대 추출"""
    patterns = [
        (r'9세이하', 'U9'),
        (r'11세이하', 'U11'),
        (r'13세이하', 'U13'),
        (r'17세이하', 'U17'),
        (r'초등', '초등'),
        (r'남중|여중|중등', '중등'),
        (r'남고|여고|고등', '고등'),
        (r'남대|여대|대학', '대학'),
        (r'일반', '일반'),
        (r'마스터즈|시니어', '마스터즈'),
    ]
    for pattern, group in patterns:
        if re.search(pattern, event_name):
            return group
    return '일반'


def build_player_index():
    """선수별 전적 인덱스 구축"""
    global _player_index
    _player_index = defaultdict(list)

    for comp in _data_cache.get("competitions", []):
        comp_info = comp.get("competition", {})
        comp_name = comp_info.get("name", "")
        comp_date = comp_info.get("start_date", "")
        year = int(comp_date[:4]) if comp_date else 0

        for event in comp.get("events", []):
            sub_event_cd = event.get("sub_event_cd", "")
            event_results = comp.get("results", {}).get(sub_event_cd, {})

            # pool_results에서 선수 추출
            for pool in event_results.get("pool_results", []):
                for player in pool.get("results", []):
                    player_name = player.get("name", "").strip()
                    if not player_name:
                        continue

                    record = {
                        "rank": player.get("rank"),
                        "competition_name": comp_name,
                        "competition_date": comp_date,
                        "event_name": event.get("name", ""),
                        "weapon": event.get("weapon", ""),
                        "gender": event.get("gender", ""),
                        "age_group": extract_age_group(event.get("name", "")),
                        "event_type": event.get("event_type", ""),
                        "team": player.get("team", ""),
                        "win_rate": player.get("win_rate", ""),
                        "year": year,
                        "event_cd": comp_info.get("event_cd", ""),
                        "sub_event_cd": sub_event_cd
                    }
                    _player_index[player_name].append(record)

            # final_results에서도 추출
            for final in event_results.get("final_results", []):
                player_name = final.get("name", "").strip()
                if not player_name:
                    continue

                # 중복 체크 (같은 대회, 같은 종목)
                existing = [r for r in _player_index[player_name]
                           if r["competition_name"] == comp_name
                           and r["event_name"] == event.get("name", "")]
                if existing:
                    # 기존 기록에 순위 업데이트
                    existing[0]["rank"] = final.get("rank", existing[0]["rank"])
                else:
                    record = {
                        "rank": final.get("rank"),
                        "competition_name": comp_name,
                        "competition_date": comp_date,
                        "event_name": event.get("name", ""),
                        "weapon": event.get("weapon", ""),
                        "gender": event.get("gender", ""),
                        "age_group": extract_age_group(event.get("name", "")),
                        "event_type": event.get("event_type", ""),
                        "team": final.get("team", ""),
                        "win_rate": "",
                        "year": year,
                        "event_cd": comp_info.get("event_cd", ""),
                        "sub_event_cd": sub_event_cd
                    }
                    _player_index[player_name].append(record)

    logger.info(f"선수 인덱스 구축 완료: {len(_player_index)}명")


def build_filter_options():
    """필터 옵션 캐시 구축"""
    global _filter_options
    _filter_options = {
        "weapons": set(),
        "genders": set(),
        "age_groups": set(),
        "years": set(),
        "event_types": set()
    }

    for comp in _data_cache.get("competitions", []):
        comp_info = comp.get("competition", {})
        comp_date = comp_info.get("start_date", "")
        if comp_date:
            try:
                _filter_options["years"].add(int(comp_date[:4]))
            except:
                pass

        for event in comp.get("events", []):
            weapon = event.get("weapon", "")
            if weapon:
                _filter_options["weapons"].add(weapon)

            gender = event.get("gender", "")
            if gender:
                _filter_options["genders"].add(gender)

            event_type = event.get("event_type", "")
            if event_type:
                _filter_options["event_types"].add(event_type)

            age_group = extract_age_group(event.get("name", ""))
            _filter_options["age_groups"].add(age_group)

    logger.info(f"필터 옵션 구축 완료: {dict((k, len(v)) for k, v in _filter_options.items())}")


def load_data():
    """JSON 데이터 파일 로드 및 인덱싱"""
    global _data_cache, _ranking_calculator

    # 우선순위: full_data_v2 > test_full_data > full_data > fencing_data
    data_files = [
        DATA_DIR / "fencing_full_data_v2.json",
        DATA_DIR / "test_full_data.json",  # 테스트용 데이터 (1개 대회, 풀 결과)
        DATA_DIR / "fencing_full_data.json",
        DATA_DIR / "fencing_data.json"
    ]

    data_file = None
    for f in data_files:
        if f.exists():
            data_file = f
            break

    if data_file:
        with open(data_file, "r", encoding="utf-8") as f:
            _data_cache = json.load(f)
        logger.info(f"데이터 로드 완료: {len(_data_cache.get('competitions', []))}개 대회 ({data_file.name})")

        # 인덱스 구축
        build_filter_options()
        build_player_index()

        # 랭킹 계산기 초기화
        try:
            _ranking_calculator = RankingCalculator(str(data_file))
            logger.info(f"랭킹 계산기 초기화 완료: {len(_ranking_calculator.results)}개 결과")
        except Exception as e:
            logger.error(f"랭킹 계산기 초기화 실패: {e}")
            _ranking_calculator = None
    else:
        logger.warning(f"데이터 파일 없음")
        _data_cache = {"competitions": [], "meta": {}}


def get_competitions() -> List[Dict]:
    """대회 목록 반환"""
    return _data_cache.get("competitions", [])


def get_competition(event_cd: str) -> Optional[Dict]:
    """특정 대회 조회"""
    for comp in get_competitions():
        if comp.get("competition", {}).get("event_cd") == event_cd:
            return comp
    return None


# ==================== API Endpoints ====================

@app.on_event("startup")
async def startup_event():
    """서버 시작 시 데이터 로드"""
    load_data()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """메인 페이지 - 필터 기반 검색"""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "title": "Korean Fencing Tracker"
    })


@app.get("/api/filters")
async def api_filters():
    """필터 옵션 API"""
    return FilterOptions(
        weapons=sorted(_filter_options.get("weapons", [])),
        genders=sorted(_filter_options.get("genders", [])),
        age_groups=sorted(_filter_options.get("age_groups", []),
                         key=lambda x: ['U9', 'U11', 'U13', 'U17', '초등', '중등', '고등', '대학', '일반', '마스터즈'].index(x) if x in ['U9', 'U11', 'U13', 'U17', '초등', '중등', '고등', '대학', '일반', '마스터즈'] else 99),
        years=sorted(_filter_options.get("years", []), reverse=True),
        event_types=sorted(_filter_options.get("event_types", [])),
        categories=["PRO", "CLUB"]  # 전문, 동호인
    )


@app.get("/api/events")
async def api_events(
    weapon: Optional[str] = None,
    gender: Optional[str] = None,
    age_group: Optional[str] = None,
    year: Optional[int] = None,
    event_type: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200)
):
    """필터 기반 종목 검색 API"""
    events = []

    for comp in get_competitions():
        comp_info = comp.get("competition", {})
        comp_date = comp_info.get("start_date", "")
        comp_year = int(comp_date[:4]) if comp_date else 0

        # 연도 필터
        if year and comp_year != year:
            continue

        for event in comp.get("events", []):
            # 무기 필터
            if weapon and event.get("weapon") != weapon:
                continue

            # 성별 필터
            if gender and event.get("gender") != gender:
                continue

            # 종목 타입 필터
            if event_type and event.get("event_type") != event_type:
                continue

            # 연령대 필터
            event_age = extract_age_group(event.get("name", ""))
            if age_group and event_age != age_group:
                continue

            # 검색어 필터
            if search:
                search_lower = search.lower()
                if (search_lower not in event.get("name", "").lower() and
                    search_lower not in comp_info.get("name", "").lower()):
                    continue

            events.append(EventSummary(
                event_cd=event.get("event_cd", ""),
                sub_event_cd=event.get("sub_event_cd", ""),
                name=event.get("name", ""),
                weapon=event.get("weapon", ""),
                gender=event.get("gender", ""),
                age_group=event_age,
                event_type=event.get("event_type", ""),
                competition_name=comp_info.get("name", ""),
                competition_date=comp_date,
                year=comp_year
            ))

    # 날짜순 정렬 (최신순)
    events.sort(key=lambda x: x.competition_date, reverse=True)

    # 페이지네이션
    total = len(events)
    start = (page - 1) * per_page
    end = start + per_page

    return {
        "events": events[start:end],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page
    }


@app.get("/api/player/{player_name}")
async def api_player_profile(
    player_name: str,
    weapon: Optional[str] = None,
    year: Optional[int] = None
):
    """선수 전적 조회 API"""
    # 정확히 일치하는 선수 찾기
    records = _player_index.get(player_name, [])

    # 부분 일치 검색
    if not records:
        for name, recs in _player_index.items():
            if player_name in name:
                records = recs
                player_name = name
                break

    if not records:
        raise HTTPException(status_code=404, detail="선수를 찾을 수 없습니다")

    # 필터 적용
    filtered = records
    if weapon:
        filtered = [r for r in filtered if r["weapon"] == weapon]
    if year:
        filtered = [r for r in filtered if r["year"] == year]

    # 팀 목록 추출
    teams = list(set(r["team"] for r in records if r["team"]))

    # 통계 계산
    stats = {
        "total": len(records),
        "by_weapon": {},
        "by_year": {},
        "medals": {"gold": 0, "silver": 0, "bronze": 0}
    }

    for r in records:
        # 무기별
        w = r["weapon"]
        if w not in stats["by_weapon"]:
            stats["by_weapon"][w] = 0
        stats["by_weapon"][w] += 1

        # 연도별
        y = str(r["year"])
        if y not in stats["by_year"]:
            stats["by_year"][y] = 0
        stats["by_year"][y] += 1

        # 메달
        rank = r.get("rank")
        if rank == 1:
            stats["medals"]["gold"] += 1
        elif rank == 2:
            stats["medals"]["silver"] += 1
        elif rank == 3:
            stats["medals"]["bronze"] += 1

    # 날짜순 정렬 (최신순)
    filtered.sort(key=lambda x: x["competition_date"], reverse=True)

    return PlayerProfile(
        name=player_name,
        teams=teams,
        total_records=len(records),
        records=[PlayerRecord(**r) for r in filtered],
        stats=stats
    )


@app.get("/api/player/search")
async def api_player_search(q: str = Query(..., min_length=1)):
    """선수 검색 API (자동완성용)"""
    q_lower = q.lower()
    matches = []

    for name in _player_index.keys():
        if q_lower in name.lower():
            records = _player_index[name]
            teams = list(set(r["team"] for r in records if r["team"]))
            matches.append({
                "name": name,
                "teams": teams,
                "record_count": len(records)
            })

    # 기록 많은 순 정렬
    matches.sort(key=lambda x: x["record_count"], reverse=True)

    return {"results": matches[:20], "total": len(matches)}


@app.get("/api/competitions")
async def api_competitions(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    year: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None
):
    """대회 목록 API"""
    competitions = get_competitions()

    filtered = []
    for comp in competitions:
        comp_info = comp.get("competition", {})
        comp_date = comp_info.get("start_date", "")
        comp_year = int(comp_date[:4]) if comp_date else 0

        # 연도 필터
        if year and comp_year != year:
            continue

        # 상태 필터
        if status and comp_info.get("status") != status:
            continue

        # 검색어 필터
        if search:
            name = comp_info.get("name", "").lower()
            if search.lower() not in name:
                continue

        filtered.append(CompetitionSummary(
            event_cd=comp_info.get("event_cd", ""),
            name=comp_info.get("name", ""),
            start_date=comp_info.get("start_date"),
            end_date=comp_info.get("end_date"),
            status=comp_info.get("status", ""),
            location=comp_info.get("location", ""),
            event_count=len(comp.get("events", [])),
            year=comp_year
        ))

    # 날짜순 정렬
    filtered.sort(key=lambda x: x.start_date or "", reverse=True)

    # 페이지네이션
    total = len(filtered)
    start = (page - 1) * per_page
    end = start + per_page

    return {
        "competitions": filtered[start:end],
        "total": total,
        "page": page,
        "per_page": per_page
    }


@app.get("/api/competition/{event_cd}")
async def api_competition_detail(event_cd: str):
    """대회 상세 정보 API"""
    comp = get_competition(event_cd)
    if not comp:
        raise HTTPException(status_code=404, detail="대회를 찾을 수 없습니다")
    return comp


@app.get("/api/stats")
async def api_stats():
    """통계 API"""
    competitions = get_competitions()

    stats = {
        "total_competitions": len(competitions),
        "total_events": sum(len(c.get("events", [])) for c in competitions),
        "total_players": len(_player_index),
        "by_year": {},
        "by_weapon": {"플러레": 0, "에뻬": 0, "사브르": 0}
    }

    for comp in competitions:
        comp_info = comp.get("competition", {})
        comp_date = comp_info.get("start_date", "")
        if comp_date:
            year = comp_date[:4]
            stats["by_year"][year] = stats["by_year"].get(year, 0) + 1

        for event in comp.get("events", []):
            weapon = event.get("weapon", "")
            if weapon in stats["by_weapon"]:
                stats["by_weapon"][weapon] += 1

    return stats


# ==================== Ranking API ====================

@app.get("/api/rankings")
async def api_rankings(
    weapon: str = Query(..., description="무기 (플러레/에뻬/사브르)"),
    gender: str = Query(..., description="성별 (남/여)"),
    age_group: str = Query(..., description="연령대 (E1/E2/E3/MS/HS/UNI/SR)"),
    category: Optional[str] = Query(None, description="구분 (PRO/CLUB) - 중학교 이상만"),
    year: Optional[int] = Query(None, description="시즌 연도"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200)
):
    """
    랭킹 조회 API

    연령대 코드:
    - E1: 초등 1-2 (U9)
    - E2: 초등 3-4 (U11)
    - E3: 초등 5-6 (U13)
    - MS: 중등 (전문/동호인 분리)
    - HS: 고등 (전문/동호인 분리)
    - UNI: 대학 (전문/동호인 분리)
    - SR: 일반 (전문/동호인 분리)

    구분:
    - PRO: 전문 선수
    - CLUB: 동호인 (클럽, 생활체육)
    """
    if not _ranking_calculator:
        raise HTTPException(status_code=503, detail="랭킹 시스템이 초기화되지 않았습니다")

    # 중학교 이상이면서 카테고리 미지정 시 기본값 PRO
    if age_group in CATEGORY_APPLICABLE_AGE_GROUPS and not category:
        category = "PRO"

    # 초등부는 카테고리 무시
    if age_group not in CATEGORY_APPLICABLE_AGE_GROUPS:
        category = None

    rankings = _ranking_calculator.calculate_rankings(
        weapon=weapon,
        gender=gender,
        age_group=age_group,
        category=category,
        year=year
    )

    # 페이지네이션
    total = len(rankings)
    start = (page - 1) * per_page
    end = start + per_page
    page_rankings = rankings[start:end]

    return RankingResponse(
        weapon=weapon,
        gender=gender,
        age_group=age_group,
        age_group_name=AGE_GROUP_CODES.get(age_group, age_group),
        category=category,
        category_name=CATEGORY_CODES.get(category) if category else None,
        total=total,
        rankings=[
            RankingEntry(
                rank=r.current_rank,
                name=r.player_name,
                teams=r.teams,
                points=r.total_points,
                competitions=r.competitions_count,
                gold=r.gold_count,
                silver=r.silver_count,
                bronze=r.bronze_count,
                best_results=r.best_results
            )
            for r in page_rankings
        ]
    )


@app.get("/api/rankings/options")
async def api_ranking_options():
    """랭킹 필터 옵션 API"""
    return {
        "weapons": ["플러레", "에뻬", "사브르"],
        "genders": ["남", "여"],
        "age_groups": [
            {"code": "E1", "name": "초등 1-2 (U9)", "has_category": False},
            {"code": "E2", "name": "초등 3-4 (U11)", "has_category": False},
            {"code": "E3", "name": "초등 5-6 (U13)", "has_category": False},
            {"code": "MS", "name": "중등", "has_category": True},
            {"code": "HS", "name": "고등", "has_category": True},
            {"code": "UNI", "name": "대학", "has_category": True},
            {"code": "SR", "name": "일반", "has_category": True},
        ],
        "categories": [
            {"code": "PRO", "name": "전문"},
            {"code": "CLUB", "name": "동호인"},
        ],
        "years": sorted(_filter_options.get("years", []), reverse=True)
    }


@app.get("/api/rankings/player/{player_name}")
async def api_player_rankings(player_name: str):
    """선수의 모든 카테고리 랭킹 조회"""
    if not _ranking_calculator:
        raise HTTPException(status_code=503, detail="랭킹 시스템이 초기화되지 않았습니다")

    # 선수의 모든 결과에서 카테고리 추출
    player_results = [r for r in _ranking_calculator.results if r.player_name == player_name]

    if not player_results:
        raise HTTPException(status_code=404, detail="선수를 찾을 수 없습니다")

    # 유니크한 카테고리 조합 추출
    categories = set()
    for r in player_results:
        key = (r.weapon, r.gender, r.age_group, r.category if r.age_group in CATEGORY_APPLICABLE_AGE_GROUPS else None)
        categories.add(key)

    # 각 카테고리별 랭킹 조회
    rankings_info = []
    for weapon, gender, age_group, category in categories:
        rankings = _ranking_calculator.calculate_rankings(
            weapon=weapon,
            gender=gender,
            age_group=age_group,
            category=category
        )

        # 해당 선수의 순위 찾기
        for r in rankings:
            if r.player_name == player_name:
                rankings_info.append({
                    "weapon": weapon,
                    "gender": gender,
                    "age_group": age_group,
                    "age_group_name": AGE_GROUP_CODES.get(age_group, age_group),
                    "category": category,
                    "category_name": CATEGORY_CODES.get(category) if category else None,
                    "rank": r.current_rank,
                    "total_in_category": len(rankings),
                    "points": r.total_points,
                    "competitions": r.competitions_count,
                    "gold": r.gold_count,
                    "silver": r.silver_count,
                    "bronze": r.bronze_count
                })
                break

    return {
        "player_name": player_name,
        "rankings": rankings_info
    }


# ==================== HTML Pages ====================

@app.get("/player/{player_name}", response_class=HTMLResponse)
async def player_page(request: Request, player_name: str):
    """선수 전적 페이지"""
    return templates.TemplateResponse("player.html", {
        "request": request,
        "player_name": player_name,
        "title": f"{player_name} - 전적"
    })


@app.get("/competition/{event_cd}", response_class=HTMLResponse)
async def competition_detail_page(request: Request, event_cd: str):
    """대회 상세 페이지"""
    comp = get_competition(event_cd)
    if not comp:
        raise HTTPException(status_code=404, detail="대회를 찾을 수 없습니다")

    return templates.TemplateResponse("competition.html", {
        "request": request,
        "competition": comp
    })


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = ""):
    """검색 페이지"""
    return templates.TemplateResponse("search.html", {
        "request": request,
        "query": q
    })


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """AI 채팅 페이지"""
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "title": "AI 검색"
    })


@app.get("/rankings", response_class=HTMLResponse)
async def rankings_page(request: Request):
    """랭킹 페이지"""
    return templates.TemplateResponse("rankings.html", {
        "request": request,
        "title": "랭킹"
    })


# ==================== 서버 실행 ====================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.server:app",
        host="0.0.0.0",
        port=71,
        reload=True,
        log_level="info"
    )
