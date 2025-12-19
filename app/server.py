"""
Korean Fencing Tracker - FastAPI 웹 서버
선수 중심 검색 + 필터 기반 UI
포트: 내부 71, 외부 7171

데이터 소스: Supabase (primary) / JSON (fallback)
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
from dotenv import load_dotenv

# Supabase 클라이언트
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    logger.warning("supabase 패키지가 설치되지 않음. JSON 파일만 사용합니다.")

# 랭킹 계산기
from ranking.calculator import (
    RankingCalculator,
    AGE_GROUP_CODES,
    AGE_GROUP_NAMES_KR,
    LEGACY_AGE_GROUP_MAP,
    CATEGORY_CODES,
    CATEGORY_APPLICABLE_AGE_GROUPS,
    classify_competition_level,
)

# 선수 식별 시스템
from app.player_identity import PlayerIdentityResolver, PlayerProfile as IdentityProfile

# Auth 모듈
from app.auth.router import router as auth_router, get_current_member

# 글로벌 연령 그룹 정렬 순서
AGE_GROUP_ORDER = ["Y8", "Y10", "Y12", "Y14", "Cadet", "Junior", "Veteran", "National"]

# 환경변수 로드
load_dotenv()

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATIC_DIR = PROJECT_ROOT / "static"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# FastAPI 앱
app = FastAPI(
    title="Korean Fencing Tracker",
    description="KFF 대회 결과 기반 선수 기록 분석 플랫폼",
    version="2.0.0"
)

# 정적 파일 및 템플릿
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Auth 라우터 등록
app.include_router(auth_router)

# 데이터 저장소 (메모리 캐시)
_data_cache: Dict[str, Any] = {}
_player_index: Dict[str, List[Dict]] = {}  # 선수별 전적 인덱스
_filter_options: Dict[str, Set] = {}  # 필터 옵션 캐시
_ranking_calculator: Optional[RankingCalculator] = None  # 랭킹 계산기
_supabase_client: Optional["Client"] = None  # Supabase 클라이언트
_data_source: str = "none"  # 현재 데이터 소스 ("supabase" or "json")
_identity_resolver: Optional[PlayerIdentityResolver] = None  # 선수 식별 시스템


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
    """
    종목명에서 연령대 추출 (FIE/US Fencing 글로벌 표준)

    글로벌 연령 구분:
    - Y8: 초등 1-2학년 (Under 8)
    - Y10: 초등 3-4학년 (Under 10)
    - Y12: 초등 5-6학년 (Under 12)
    - Y14: 중등부 (Under 14)
    - Cadet: 고등부 (Under 17)
    - Junior: 대학부 (Under 20)
    - Veteran: 일반부 (Open/Senior)
    """
    # 초등부 세분화 패턴 (학년 기반)
    elem_patterns = [
        (r'초등.*1[-~]?2|초등부.*1[-~]?2|1[-~]?2학년', 'Y8'),
        (r'초등.*3[-~]?4|초등부.*3[-~]?4|3[-~]?4학년', 'Y10'),
        (r'초등.*5[-~]?6|초등부.*5[-~]?6|5[-~]?6학년', 'Y12'),
    ]

    # 나이 기반 패턴 ((?<!\d)로 앞에 숫자가 없어야 함 - "18세이하"가 "8세이하"로 매칭되는 것 방지)
    age_patterns = [
        (r'(?<!\d)8세이하|U8|Y8', 'Y8'),
        (r'(?<!\d)9세이하|(?<!\d)10세이하|U10|Y10', 'Y10'),
        (r'11세이하|12세이하|U12|Y12', 'Y12'),
        (r'13세이하|14세이하|U14|Y14', 'Y14'),
        (r'15세이하|16세이하|17세이하|18세이하|U17|U18', 'Cadet'),
    ]

    # 일반 패턴
    general_patterns = [
        (r'남중|여중|중등', 'Y14'),
        (r'남고|여고|고등|카뎃|Cadet', 'Cadet'),
        (r'남대|여대|대학|주니어|Junior', 'Junior'),
        (r'일반|베테랑|시니어|마스터즈|Veteran|Senior|Open', 'Veteran'),
    ]

    # 초등부 세분화 먼저 체크
    for pattern, group in elem_patterns:
        if re.search(pattern, event_name, re.IGNORECASE):
            return group

    # 나이 기반 패턴 체크
    for pattern, group in age_patterns:
        if re.search(pattern, event_name, re.IGNORECASE):
            return group

    # 일반 패턴 체크
    for pattern, group in general_patterns:
        if re.search(pattern, event_name, re.IGNORECASE):
            return group

    # 초등부 기본값 (학년 미지정)
    if re.search(r'초등', event_name):
        return 'Y12'  # 기본 초등부 → Y12

    return 'Veteran'  # 기본값


def build_player_index():
    """선수별 전적 인덱스 구축 (v2 데이터 구조 지원)

    중요: 선수 랭킹/기록은 엘리미나시옹디렉트 (final_rankings) 결과만 사용
    Pool 결과는 포함하지 않음
    """
    global _player_index
    _player_index = defaultdict(list)

    for comp in _data_cache.get("competitions", []):
        comp_info = comp.get("competition", {})
        comp_name = comp_info.get("name", "")
        comp_date = comp_info.get("start_date", "")
        year = int(comp_date[:4]) if comp_date else 0

        for event in comp.get("events", []):
            sub_event_cd = event.get("sub_event_cd", "")
            event_name = event.get("name", "")
            age_group = event.get("age_group") or extract_age_group(event_name)
            total_participants = event.get("total_participants") or len(event.get("final_rankings", []))

            # 엘리미나시옹디렉트 (final_rankings)에서만 선수 추출
            # Pool 결과는 랭킹/기록에 포함하지 않음
            for final in event.get("final_rankings", []):
                player_name = final.get("name", "").strip()
                if not player_name:
                    continue

                # 중복 체크 (같은 대회, 같은 종목)
                existing = [r for r in _player_index[player_name]
                           if r["competition_name"] == comp_name
                           and r["event_name"] == event_name]
                if existing:
                    continue  # 이미 존재하면 건너뛰기

                record = {
                    "rank": final.get("rank"),
                    "competition_name": comp_name,
                    "competition_date": comp_date,
                    "event_name": event_name,
                    "weapon": event.get("weapon", ""),
                    "gender": event.get("gender", ""),
                    "age_group": age_group,
                    "event_type": event.get("event_type", ""),
                    "team": final.get("team", ""),
                    "win_rate": "",
                    "year": year,
                    "event_cd": comp_info.get("event_cd", ""),
                    "sub_event_cd": sub_event_cd,
                    "total_participants": total_participants
                }
                _player_index[player_name].append(record)

            # 기존 v1 구조도 지원 (하위 호환) - final_results만 사용
            event_results = comp.get("results", {}).get(sub_event_cd, {})
            if event_results:
                # Pool 결과는 사용하지 않음 - 엘리미나시옹디렉트 결과만 사용
                for final in event_results.get("final_results", []):
                    player_name = final.get("name", "").strip()
                    if not player_name:
                        continue
                    existing = [r for r in _player_index[player_name]
                               if r["competition_name"] == comp_name
                               and r["event_name"] == event_name]
                    if not existing:
                        record = {
                            "rank": final.get("rank"),
                            "competition_name": comp_name,
                            "competition_date": comp_date,
                            "event_name": event_name,
                            "weapon": event.get("weapon", ""),
                            "gender": event.get("gender", ""),
                            "age_group": age_group,
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


def init_supabase_client() -> Optional["Client"]:
    """Supabase 클라이언트 초기화"""
    global _supabase_client

    if not SUPABASE_AVAILABLE:
        return None

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        logger.warning("SUPABASE_URL 또는 SUPABASE_KEY 환경변수 없음")
        return None

    try:
        _supabase_client = create_client(url, key)
        logger.info("Supabase 클라이언트 초기화 완료")
        return _supabase_client
    except Exception as e:
        logger.error(f"Supabase 클라이언트 초기화 실패: {e}")
        return None


def load_data_from_supabase() -> bool:
    """Supabase에서 데이터 로드"""
    global _data_cache, _data_source

    if not _supabase_client:
        return False

    try:
        # 대회 목록 조회
        comp_result = _supabase_client.table("competitions").select("*").execute()
        if not comp_result.data:
            logger.warning("Supabase에 대회 데이터 없음")
            return False

        competitions_dict = {c["id"]: c for c in comp_result.data}

        # 종목 목록 조회 (페이지네이션으로 모든 데이터 로드)
        all_events = []
        page_size = 1000
        offset = 0
        while True:
            events_result = _supabase_client.table("events").select("*").range(offset, offset + page_size - 1).execute()
            if not events_result.data:
                break
            all_events.extend(events_result.data)
            if len(events_result.data) < page_size:
                break
            offset += page_size

        logger.info(f"종목 {len(all_events)}개 로드됨")

        events_by_comp = defaultdict(list)
        for e in all_events:
            events_by_comp[e["competition_id"]].append(e)

        # JSON 형식으로 변환 (기존 코드와 호환)
        competitions = []
        for comp in comp_result.data:
            comp_events = events_by_comp.get(comp["id"], [])

            # v1 스키마 -> v2 JSON 형식 변환
            event_list = []
            for e in comp_events:
                raw = e.get("raw_data") or {}

                # pool_rounds 필터링: summary pool 제외, 중복 제거, 데이터 정제
                raw_pools = raw.get("pool_rounds", [])
                filtered_pools = _filter_pool_rounds(raw_pools)

                event_data = {
                    "event_cd": e["event_cd"],
                    "sub_event_cd": e["sub_event_cd"],
                    "name": e["event_name"],
                    "weapon": e["weapon"],
                    "gender": e["gender"],
                    "event_type": e["category"],  # category -> event_type
                    "age_group": e["age_group"],
                    "total_participants": raw.get("total_participants", 0),
                    "pool_rounds": filtered_pools,
                    "pool_total_ranking": raw.get("pool_total_ranking", []),
                    "final_rankings": raw.get("final_rankings", []),
                    "de_bracket": raw.get("de_bracket", {}),
                    "de_matches": raw.get("de_matches", []),
                    "tournament_bracket": raw.get("tournament_bracket", [])
                }
                event_list.append(event_data)

            competitions.append({
                "competition": {
                    "event_cd": comp["comp_idx"],  # comp_idx -> event_cd
                    "name": comp["comp_name"],  # comp_name -> name
                    "start_date": comp["start_date"],
                    "end_date": comp["end_date"],
                    "status": comp["status"],
                    "location": comp.get("venue", ""),
                    "category": ""
                },
                "events": event_list
            })

        _data_cache = {
            "meta": {
                "source": "supabase",
                "loaded_at": datetime.now().isoformat(),
                "total_competitions": len(competitions)
            },
            "competitions": competitions
        }
        _data_source = "supabase"
        logger.info(f"Supabase 데이터 로드 완료: {len(competitions)}개 대회")
        return True

    except Exception as e:
        logger.error(f"Supabase 데이터 로드 실패: {e}")
        return False


def _filter_pool_rounds(pools: List[Dict]) -> List[Dict]:
    """풀 라운드 필터링: summary pool 제외, 중복 제거, 데이터 정제

    Issues fixed:
    1. Summary pools (>12 players) - 전체 선수 요약 테이블
    2. Duplicate pools - 같은 선수 목록이 2번 나타나는 경우 (content-based dedup)
    3. Corrupted first entry - "1 (정윤)" 처럼 position이 이름으로 파싱된 경우
    4. Pool renumbering - 1부터 순차적으로 재번호 부여
    """
    if not pools:
        return []

    seen_player_sets = set()  # Track unique player combinations
    filtered_pools = []

    for pool in pools:
        results = pool.get("results", [])

        # Skip pools with > 12 players (summary pools have all participants)
        if len(results) > 12:
            continue

        # Clean up corrupted results (position parsed as name)
        cleaned_results = []
        for result in results:
            name = result.get("name", "")
            # Skip if name is just a number (position was mistakenly parsed as name)
            if name and not name.isdigit():
                cleaned_results.append(result)

        if not cleaned_results:
            continue

        # Create a signature from player names to detect content duplicates
        player_signature = tuple(sorted([r.get("name", "") for r in cleaned_results]))

        # Skip if we've seen this exact player combination before
        if player_signature in seen_player_sets:
            continue
        seen_player_sets.add(player_signature)

        pool_copy = pool.copy()
        pool_copy["results"] = cleaned_results
        filtered_pools.append(pool_copy)

    # Renumber pools sequentially starting from 1
    for i, pool in enumerate(filtered_pools, start=1):
        pool["pool_number"] = i

    return filtered_pools


def load_data_from_json() -> bool:
    """JSON 파일에서 데이터 로드"""
    global _data_cache, _data_source

    # 우선순위: full_data_v2 > test_full_data > full_data > fencing_data
    data_files = [
        DATA_DIR / "fencing_full_data_v2.json",
        DATA_DIR / "test_full_data.json",
        DATA_DIR / "fencing_full_data.json",
        DATA_DIR / "fencing_data.json"
    ]

    for data_file in data_files:
        if data_file.exists():
            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    _data_cache = json.load(f)

                # Apply pool filtering to all competitions/events
                for comp in _data_cache.get("competitions", []):
                    for event in comp.get("events", []):
                        raw_pools = event.get("pool_rounds", [])
                        event["pool_rounds"] = _filter_pool_rounds(raw_pools)

                _data_source = "json"
                logger.info(f"JSON 데이터 로드 완료: {len(_data_cache.get('competitions', []))}개 대회 ({data_file.name})")
                return True
            except Exception as e:
                logger.error(f"JSON 파일 로드 실패 ({data_file}): {e}")

    return False


def build_identity_resolver():
    """선수 식별 시스템 구축 (동명이인/소속변경 처리)"""
    global _identity_resolver
    _identity_resolver = PlayerIdentityResolver()

    for comp_data in _data_cache.get("competitions", []):
        _identity_resolver.add_competition_data(comp_data)

    _identity_resolver.resolve_identities()

    # 영문 이름 채우기
    en_count = _identity_resolver.populate_english_names()
    verified_count = len([p for p in _identity_resolver.profiles.values() if p.name_en_verified])

    # 팀 정보 채우기 (ID, 영문명)
    team_count = _identity_resolver.populate_team_info()
    org_stats = _identity_resolver.get_organization_stats()

    logger.info(f"선수 식별 시스템 구축 완료: {len(_identity_resolver.profiles)}개 프로필, {len([n for n, p in _identity_resolver.name_to_profiles.items() if len(p) > 1])}개 동명이인")
    logger.info(f"영문 이름 설정 완료: {en_count}개 (검증됨: {verified_count}개)")
    logger.info(f"조직 정보 설정 완료: {team_count}개 팀 레코드, {org_stats.get('total', 0)}개 조직")


def load_data():
    """데이터 로드 (Supabase 우선, JSON fallback)"""
    global _data_cache, _ranking_calculator, _data_source

    # 환경변수로 강제 JSON 모드 설정 가능
    force_json = os.getenv("FORCE_JSON_DATA", "").lower() in ("1", "true", "yes")

    # 1. Supabase 클라이언트 초기화 (강제 JSON 모드가 아닐 때만)
    if not force_json:
        init_supabase_client()

    # 2. JSON 파일 우선 로드 (DE 데이터 포함)
    # Supabase에 DE 데이터가 없으므로 현재는 JSON 우선 사용
    if load_data_from_json():
        logger.info("📁 JSON 데이터 소스 사용 중 (DE 데이터 포함)")
    # 3. JSON 실패 시 Supabase 시도
    elif _supabase_client and load_data_from_supabase():
        logger.info("✅ Supabase 데이터 소스 사용 중")
    else:
        logger.warning("❌ 데이터 소스 없음")
        _data_cache = {"competitions": [], "meta": {}}
        _data_source = "none"
        return

    # 인덱스 구축
    build_filter_options()
    build_player_index()
    build_identity_resolver()  # 선수 식별 시스템 구축

    # 랭킹 계산기 초기화 (JSON 파일 필요)
    data_file = DATA_DIR / "fencing_full_data_v2.json"
    if data_file.exists():
        try:
            _ranking_calculator = RankingCalculator(str(data_file))
            logger.info(f"랭킹 계산기 초기화 완료: {len(_ranking_calculator.results)}개 결과")
        except Exception as e:
            logger.error(f"랭킹 계산기 초기화 실패: {e}")
            _ranking_calculator = None


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


@app.get("/api/status")
async def api_status():
    """데이터 소스 상태 API"""
    competitions = get_competitions()
    total_events = sum(len(c.get("events", [])) for c in competitions)

    return {
        "data_source": _data_source,
        "competitions": len(competitions),
        "events": total_events,
        "players": len(_player_index),
        "supabase_available": SUPABASE_AVAILABLE,
        "meta": _data_cache.get("meta", {})
    }


@app.get("/api/filters")
async def api_filters():
    """필터 옵션 API - 글로벌 표준 (FIE/US Fencing)"""
    # age_groups에 National 추가 (국가대표선발대회용)
    age_groups = list(_filter_options.get("age_groups", []))
    if "National" not in age_groups:
        age_groups.append("National")

    return FilterOptions(
        weapons=sorted(_filter_options.get("weapons", [])),
        genders=sorted(_filter_options.get("genders", [])),
        age_groups=sorted(age_groups,
                         key=lambda x: AGE_GROUP_ORDER.index(x) if x in AGE_GROUP_ORDER else 99),
        years=sorted(_filter_options.get("years", []), reverse=True),
        event_types=sorted(_filter_options.get("event_types", [])),
        categories=["PRO", "CLUB"]  # Pro, Club
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

    # National 선택 여부 확인
    is_national_filter = age_group == "National"

    for comp in get_competitions():
        comp_info = comp.get("competition", {})
        comp_name = comp_info.get("name", "")
        comp_date = comp_info.get("start_date", "")
        comp_year = int(comp_date[:4]) if comp_date else 0

        # 연도 필터
        if year and comp_year != year:
            continue

        # 대회 레벨 분류
        comp_level = classify_competition_level(comp_name)

        # National 필터: 국가대표 대회만 표시
        if is_national_filter:
            if comp_level != 'NATIONAL':
                continue
        else:
            # 다른 필터: 국가대표 대회는 제외 (National 이벤트에서만 표시)
            if comp_level == 'NATIONAL':
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

            # 연령대 필터 (National이 아닌 경우에만 적용)
            event_age = extract_age_group(event.get("name", ""))
            if age_group and not is_national_filter and event_age != age_group:
                continue

            # 검색어 필터
            if search:
                search_lower = search.lower()
                if (search_lower not in event.get("name", "").lower() and
                    search_lower not in comp_name.lower()):
                    continue

            events.append(EventSummary(
                event_cd=event.get("event_cd", ""),
                sub_event_cd=event.get("sub_event_cd", ""),
                name=event.get("name", ""),
                weapon=event.get("weapon", ""),
                gender=event.get("gender", ""),
                age_group=event_age,
                event_type=event.get("event_type", ""),
                competition_name=comp_name,
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


@app.get("/api/players/search")
async def api_player_search(q: str = Query(..., min_length=1)):
    """선수 검색 API (자동완성용) - 동명이인 구분 지원"""
    q_lower = q.lower()
    matches = []

    # 선수 식별 시스템 사용
    if _identity_resolver:
        search_results = _identity_resolver.search_players(q)

        for profile in search_results:
            matches.append({
                "name": profile.name,
                "name_en": profile.name_en,
                "player_id": profile.player_id,
                "teams": profile.teams,
                "current_team": profile.current_team,
                "record_count": len(profile.competition_ids),
                "weapons": list(profile.weapons),
                "has_disambiguation": _identity_resolver.has_disambiguation(profile.name),
                "team_history": [
                    {
                        "team": t.team,
                        "team_id": t.team_id,
                        "team_en": t.team_en,
                        "first_seen": t.first_seen,
                        "last_seen": t.last_seen,
                        "count": t.competition_count
                    }
                    for t in profile.team_history[-3:]  # 최근 3개 팀만
                ]
            })
    else:
        # Fallback: 기존 인덱스 사용 (이름 또는 소속으로 검색)
        matched_names = set()

        # 1. 이름으로 검색
        for name in _player_index.keys():
            if q_lower in name.lower():
                matched_names.add(name)

        # 2. 소속(팀)으로 검색 - 가장 최근 대회의 팀이 일치하는 선수만
        for name, records in _player_index.items():
            if name in matched_names:
                continue
            if records:
                # 가장 최근 기록의 팀 확인
                sorted_records = sorted(records, key=lambda x: x.get("competition_date", ""), reverse=True)
                current_team = sorted_records[0].get("team", "") if sorted_records else ""
                if current_team and q_lower in current_team.lower():
                    matched_names.add(name)

        # 결과 생성
        for name in matched_names:
            records = _player_index[name]
            sorted_records = sorted(records, key=lambda x: x.get("competition_date", ""), reverse=True)
            current_team = sorted_records[0].get("team", "") if sorted_records else ""
            teams = list(set(r["team"] for r in records if r["team"]))
            matches.append({
                "name": name,
                "name_en": None,
                "player_id": None,
                "teams": teams,
                "current_team": current_team,
                "record_count": len(records),
                "weapons": list(set(r["weapon"] for r in records if r["weapon"])),
                "has_disambiguation": False,
                "team_history": [
                    {"team": t, "team_id": None, "team_en": None, "first_seen": "", "last_seen": "", "count": 0}
                    for t in teams[:3]
                ]
            })

    # 기록 많은 순 정렬
    matches.sort(key=lambda x: x["record_count"], reverse=True)

    return {"results": matches[:30], "total": len(matches)}


@app.get("/api/players/by-id/{player_id}")
async def api_player_by_id(player_id: str):
    """선수 ID로 프로필 조회 (동명이인 구분용)"""
    if not _identity_resolver:
        raise HTTPException(status_code=503, detail="선수 식별 시스템이 초기화되지 않았습니다")

    profile = _identity_resolver.get_player_by_id(player_id)
    if not profile:
        raise HTTPException(status_code=404, detail="선수를 찾을 수 없습니다")

    return {
        "player_id": profile.player_id,
        "name": profile.name,
        "current_team": profile.current_team,
        "teams": profile.teams,
        "weapons": list(profile.weapons),
        "age_groups": list(profile.age_groups),
        "competition_count": len(profile.competition_ids),
        "team_history": [
            {
                "team": t.team,
                "first_seen": t.first_seen,
                "last_seen": t.last_seen,
                "competition_count": t.competition_count
            }
            for t in profile.team_history
        ],
        "podium_by_season": profile.podium_by_season,
        "has_disambiguation": _identity_resolver.has_disambiguation(profile.name)
    }


@app.get("/api/players/disambiguation/{name}")
async def api_player_disambiguation(name: str):
    """동명이인 목록 조회"""
    if not _identity_resolver:
        raise HTTPException(status_code=503, detail="선수 식별 시스템이 초기화되지 않았습니다")

    profiles = _identity_resolver.get_players_by_name(name)
    if not profiles:
        raise HTTPException(status_code=404, detail="선수를 찾을 수 없습니다")

    return {
        "name": name,
        "count": len(profiles),
        "profiles": [
            {
                "player_id": p.player_id,
                "current_team": p.current_team,
                "teams": p.teams,
                "weapons": list(p.weapons),
                "competition_count": len(p.competition_ids),
                "team_history": [
                    {
                        "team": t.team,
                        "first_seen": t.first_seen,
                        "last_seen": t.last_seen
                    }
                    for t in p.team_history[-3:]
                ]
            }
            for p in profiles
        ]
    }


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


# ==================== Helper Functions ====================

def calculate_head_to_head(player_name: str, records: List[Dict], profile_teams: Optional[Set[str]] = None) -> List[Dict]:
    """
    상대 전적 계산

    Pool + 엘리미나시옹디렉트 경기 모두 포함
    중복 방지: 대회+종목+라운드+상대 조합으로 유니크 키 생성

    Args:
        player_name: 선수 이름
        records: 선수 기록 목록
        profile_teams: 동명이인 구분용 팀 목록 (None이면 모든 경기 포함)
    """
    opponent_stats = {}
    seen_matches = set()  # 중복 방지용 set

    for comp in get_competitions():
        comp_info = comp.get("competition", {})
        comp_date = comp_info.get("start_date", "")
        comp_name = comp_info.get("name", "")

        for event in comp.get("events", []):
            event_name = event.get("name", "")

            # ===== 1. Pool 라운드에서 상대 전적 추출 =====
            for pool_idx, pool in enumerate(event.get("pool_rounds", [])):
                # 해당 선수가 이 풀에 있는지 확인 (동명이인 구분: 팀으로 필터링)
                player_in_pool = None
                for player in pool.get("results", []):
                    if player.get("name") == player_name:
                        # 동명이인 구분: profile_teams가 있으면 팀 매칭 확인
                        if profile_teams and player.get("team") not in profile_teams:
                            continue
                        player_in_pool = player
                        break

                if not player_in_pool:
                    continue

                # bouts에서 직접 대결 찾기
                for bout in pool.get("bouts", []):
                    opponent_name = None
                    my_score = 0
                    opponent_score = 0
                    result = None

                    if bout.get("player1_name") == player_name:
                        opponent_name = bout.get("player2_name")
                        opponent_team = bout.get("player2_team", "")
                        my_score = bout.get("player1_score", 0)
                        opponent_score = bout.get("player2_score", 0)
                        result = "V" if bout.get("winner_name") == player_name else "D"
                    elif bout.get("player2_name") == player_name:
                        opponent_name = bout.get("player1_name")
                        opponent_team = bout.get("player1_team", "")
                        my_score = bout.get("player2_score", 0)
                        opponent_score = bout.get("player1_score", 0)
                        result = "V" if bout.get("winner_name") == player_name else "D"

                    if opponent_name and opponent_name != player_name:
                        # 중복 체크용 유니크 키 (대회+종목+상대+점수)
                        # pool_idx 대신 점수를 사용하여 동일한 경기가 여러 풀에 중복 저장된 경우 방지
                        match_key = f"{comp_name}|{event_name}|Pool|{opponent_name}|{my_score}-{opponent_score}"
                        if match_key in seen_matches:
                            continue
                        seen_matches.add(match_key)

                        if opponent_name not in opponent_stats:
                            opponent_stats[opponent_name] = {
                                "name": opponent_name,
                                "team": opponent_team,
                                "wins": 0,
                                "losses": 0,
                                "matches": []
                            }

                        if result == "V":
                            opponent_stats[opponent_name]["wins"] += 1
                        else:
                            opponent_stats[opponent_name]["losses"] += 1

                        opponent_stats[opponent_name]["matches"].append({
                            "date": comp_date,
                            "tournament": comp_name,
                            "round": "Pool",
                            "score": f"{my_score}-{opponent_score}",
                            "result": result
                        })

            # ===== 2. 엘리미나시옹디렉트 대진표에서 상대 전적 추출 =====
            de_bracket = event.get("de_bracket", {})
            if isinstance(de_bracket, dict):
                for round_name, matches in de_bracket.items():
                    if not isinstance(matches, list):
                        continue
                    for match in matches:
                        # match가 딕셔너리가 아니면 스킵
                        if not isinstance(match, dict):
                            continue

                        opponent_name = None
                        my_score = 0
                        opponent_score = 0
                        result = None
                        opponent_team = ""

                        # player1이 해당 선수인 경우
                        if match.get("player1_name") == player_name:
                            # 동명이인 구분: profile_teams가 있으면 팀 매칭 확인
                            if profile_teams and match.get("player1_team") not in profile_teams:
                                continue
                            opponent_name = match.get("player2_name")
                            opponent_team = match.get("player2_team", "")
                            my_score = match.get("player1_score", 0)
                            opponent_score = match.get("player2_score", 0)
                            result = "V" if match.get("winner_name") == player_name else "D"
                        # player2가 해당 선수인 경우
                        elif match.get("player2_name") == player_name:
                            # 동명이인 구분: profile_teams가 있으면 팀 매칭 확인
                            if profile_teams and match.get("player2_team") not in profile_teams:
                                continue
                            opponent_name = match.get("player1_name")
                            opponent_team = match.get("player1_team", "")
                            my_score = match.get("player2_score", 0)
                            opponent_score = match.get("player1_score", 0)
                            result = "V" if match.get("winner_name") == player_name else "D"

                        if opponent_name and opponent_name != player_name:
                            # 중복 체크용 유니크 키 (대회+종목+라운드+상대+점수)
                            match_key = f"{comp_name}|{event_name}|{round_name}|{opponent_name}|{my_score}-{opponent_score}"
                            if match_key in seen_matches:
                                continue
                            seen_matches.add(match_key)

                            if opponent_name not in opponent_stats:
                                opponent_stats[opponent_name] = {
                                    "name": opponent_name,
                                    "team": opponent_team,
                                    "wins": 0,
                                    "losses": 0,
                                    "matches": []
                                }

                            if result == "V":
                                opponent_stats[opponent_name]["wins"] += 1
                            else:
                                opponent_stats[opponent_name]["losses"] += 1

                            opponent_stats[opponent_name]["matches"].append({
                                "date": comp_date,
                                "tournament": comp_name,
                                "round": round_name,  # 64강, 32강, etc.
                                "score": f"{my_score}-{opponent_score}",
                                "result": result
                            })

    # 승률 계산 및 정렬
    result = []
    for name, stats in opponent_stats.items():
        total = stats["wins"] + stats["losses"]
        if total > 0:
            win_rate = round(stats["wins"] / total * 100, 1)
            last_match = sorted(stats["matches"], key=lambda x: x["date"], reverse=True)[0] if stats["matches"] else {}

            result.append({
                "name": name,
                "team": stats["team"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "win_rate": win_rate,
                "last_result": last_match.get("result", ""),
                "last_score": last_match.get("score", ""),
                "last_match_date": last_match.get("date", ""),
                "matches": sorted(stats["matches"], key=lambda x: x["date"], reverse=True)
            })

    # 최근 경기 날짜 기준 정렬 (최신순)
    result.sort(key=lambda x: x["last_match_date"], reverse=True)
    return result


def get_event_from_competition(event_cd: str, sub_event_cd: str) -> tuple:
    """대회에서 특정 이벤트 조회"""
    for comp in get_competitions():
        if comp.get("competition", {}).get("event_cd") == event_cd:
            for event in comp.get("events", []):
                if event.get("sub_event_cd") == sub_event_cd:
                    return comp, event
    return None, None


# ==================== HTML Pages ====================

@app.get("/player/{player_name}", response_class=HTMLResponse)
async def player_page(request: Request, player_name: str, id: Optional[str] = None, team: Optional[str] = None):
    """선수 프로필 페이지 (fencingtracker 스타일)

    Args:
        player_name: 선수 이름
        id: 선수 ID (동명이인 구분용, Optional)
        team: 소속팀 (동명이인 구분용, Optional)
    """
    identity_profile = None
    has_disambiguation = False
    profile_identified_by_team = False

    # 선수 식별 시스템을 통한 조회
    if _identity_resolver:
        # ID가 주어진 경우 해당 프로필 조회
        if id:
            identity_profile = _identity_resolver.get_player_by_id(id)
            if identity_profile and identity_profile.name != player_name:
                identity_profile = None  # 이름 불일치 시 무시

        # ID가 없고 team이 주어진 경우 team으로 프로필 조회
        if not identity_profile and team:
            profiles = _identity_resolver.get_players_by_name(player_name)
            for p in profiles:
                if team in p.teams:
                    identity_profile = p
                    profile_identified_by_team = True
                    has_disambiguation = len(profiles) > 1
                    break

        # ID와 team 모두 없거나 찾지 못한 경우 이름으로 조회
        if not identity_profile:
            profiles = _identity_resolver.get_players_by_name(player_name)
            if profiles:
                identity_profile = profiles[0]  # 첫 번째 프로필 사용
                has_disambiguation = len(profiles) > 1

    # 선수 기록 조회 (기존 인덱스 또는 식별 시스템의 competition_ids 사용)
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

    # 동명이인 필터링: identity_profile이 있고 동명이인이 존재하는 경우, 해당 프로필 기록만 필터링
    # has_disambiguation이 True면 항상 필터링 (id/team 파라미터 없어도)
    if identity_profile and (id or profile_identified_by_team or has_disambiguation):
        profile_teams = set(identity_profile.teams)
        filtered_records = [
            r for r in records
            if r.get("team") in profile_teams
        ]
        if filtered_records:
            records = filtered_records

    # 팀 목록
    teams = list(set(r["team"] for r in records if r["team"]))

    # 연도별/무기별 분류
    years = sorted(set(r["year"] for r in records if r["year"]), reverse=True)
    weapons = sorted(set(r["weapon"] for r in records if r["weapon"]))

    # 통계 계산
    stats = {
        "total": len(records),
        "by_weapon": {},
        "by_year": {},
        "medals": {"gold": 0, "silver": 0, "bronze": 0, "top8": 0}
    }

    # 시즌별 시상대 기록
    podium_by_season = {}

    for r in records:
        w = r["weapon"]
        if w:
            stats["by_weapon"][w] = stats["by_weapon"].get(w, 0) + 1

        y = r["year"]
        if y:
            season = f"{y}"
            if season not in podium_by_season:
                podium_by_season[season] = {"gold": 0, "silver": 0, "bronze": 0, "top8": 0, "total": 0}
            podium_by_season[season]["total"] += 1

            rank = r.get("rank")
            if rank == 1:
                stats["medals"]["gold"] += 1
                podium_by_season[season]["gold"] += 1
            elif rank == 2:
                stats["medals"]["silver"] += 1
                podium_by_season[season]["silver"] += 1
            elif rank == 3:
                stats["medals"]["bronze"] += 1
                podium_by_season[season]["bronze"] += 1
            elif rank and rank <= 8:
                stats["medals"]["top8"] += 1
                podium_by_season[season]["top8"] += 1

    # 레이팅 계산 (간단한 버전)
    ratings = {}
    rating_history = []
    for w in weapons:
        weapon_records = [r for r in records if r["weapon"] == w]
        best_rank = min((r.get("rank") or 999 for r in weapon_records), default=999)

        if best_rank == 1:
            rating = "A"
        elif best_rank == 2:
            rating = "B"
        elif best_rank <= 4:
            rating = "C"
        elif best_rank <= 8:
            rating = "D"
        elif best_rank <= 16:
            rating = "E"
        else:
            rating = "U"

        if years:
            rating += str(years[0])[-2:]

        ratings[w] = {"current": rating}

        # 레이팅 히스토리 (최근 변화)
        for r in sorted(weapon_records, key=lambda x: x["competition_date"], reverse=True)[:5]:
            if r.get("rank") and r.get("rank") <= 8:
                rating_history.append({
                    "rating": rating,
                    "weapon": w,
                    "date": r["competition_date"]
                })

    # 경기 기록 정렬 (최신순)
    sorted_records = sorted(records, key=lambda x: x.get("competition_date", ""), reverse=True)

    # 상대 전적 계산 (동명이인 구분: profile_teams 전달)
    h2h_profile_teams = set(identity_profile.teams) if identity_profile and (id or profile_identified_by_team) else None
    head_to_head = calculate_head_to_head(player_name, records, h2h_profile_teams)

    # 경기 통계
    bout_stats = {"total": 0, "wins": 0, "losses": 0, "win_rate": 0}
    stage_stats = {
        "pool_wins": 0, "pool_losses": 0, "pool_rate": 0,
        "de_wins": 0, "de_losses": 0, "de_rate": 0,
        "final_wins": 0, "final_losses": 0, "final_rate": 0
    }

    # 예선 기록에서 통계 추출
    for r in records:
        if r.get("win_rate"):
            try:
                # win_rate가 "3/5" 형식일 경우
                parts = str(r["win_rate"]).split("/")
                if len(parts) == 2:
                    wins = int(parts[0])
                    total = int(parts[1])
                    stage_stats["pool_wins"] += wins
                    stage_stats["pool_losses"] += (total - wins)
            except:
                pass

    bout_stats["total"] = stage_stats["pool_wins"] + stage_stats["pool_losses"]
    bout_stats["wins"] = stage_stats["pool_wins"]
    bout_stats["losses"] = stage_stats["pool_losses"]
    if bout_stats["total"] > 0:
        bout_stats["win_rate"] = round(bout_stats["wins"] / bout_stats["total"] * 100, 1)

    if stage_stats["pool_wins"] + stage_stats["pool_losses"] > 0:
        stage_stats["pool_rate"] = round(stage_stats["pool_wins"] / (stage_stats["pool_wins"] + stage_stats["pool_losses"]) * 100, 1)

    # 동명이인 정보
    other_profiles = []
    if _identity_resolver and has_disambiguation:
        all_profiles = _identity_resolver.get_players_by_name(player_name)
        for p in all_profiles:
            if not identity_profile or p.player_id != identity_profile.player_id:
                other_profiles.append({
                    "player_id": p.player_id,
                    "current_team": p.current_team,
                    "teams": p.teams,
                    "competition_count": len(p.competition_ids)
                })

    player_data = {
        "name": player_name,
        "player_id": identity_profile.player_id if identity_profile else None,
        # 영문 이름 및 국제 데이터
        "name_en": identity_profile.name_en if identity_profile else None,
        "name_en_verified": identity_profile.name_en_verified if identity_profile else False,
        "fie_id": identity_profile.fie_id if identity_profile else None,
        "fencingtracker_id": identity_profile.fencingtracker_id if identity_profile else None,
        "teams": teams,
        "years": years,
        "weapons": weapons,
        "ratings": ratings,
        "rating_history": rating_history[:10],
        "podium_by_season": dict(sorted(podium_by_season.items(), reverse=True)),
        "stats": stats,
        "total_records": len(records),
        "records": sorted_records,
        "head_to_head": head_to_head,  # 모든 상대 전적 표시
        "bout_stats": bout_stats,
        "stage_stats": stage_stats,
        "upcoming_events": [],
        "has_disambiguation": has_disambiguation,
        "other_profiles": other_profiles,
        "team_history": [
            {
                "team": t.team,
                "team_id": t.team_id,
                "team_en": t.team_en,
                "first_seen": t.first_seen,
                "last_seen": t.last_seen,
                "count": t.competition_count
            }
            for t in identity_profile.team_history
        ] if identity_profile else []
    }

    return templates.TemplateResponse("player_profile.html", {
        "request": request,
        "player": player_data,
        "today": date.today().strftime("%b %d, %Y"),
        "title": f"{player_name} - Korean Fencing Tracker"
    })


def transform_de_bracket(event_data: Dict) -> Dict:
    """DE bracket 데이터를 템플릿 호환 형식으로 변환"""
    de_bracket = event_data.get("de_bracket", {})
    if not de_bracket:
        return event_data

    # seeding 데이터로 선수 정보 맵 생성
    seeding = de_bracket.get("seeding", [])
    seed_to_player = {}
    for player in seeding:
        seed = player.get("seed")
        if seed and seed not in seed_to_player:  # 첫 번째 등장만
            seed_to_player[seed] = {
                "name": player.get("name", ""),
                "team": player.get("team", "")
            }

    # results_by_round를 템플릿 형식으로 변환
    results_by_round = de_bracket.get("results_by_round", {})
    transformed_rounds = {}

    # 라운드명 매핑 (32강전 -> 32강)
    round_name_map = {
        "64강전": "64강", "32강전": "32강", "16강전": "16강",
        "8강전": "8강", "준결승": "준결승", "결승": "결승",
        "3-4위전": "3-4위전"
    }

    for round_name, matches in results_by_round.items():
        normalized_round = round_name_map.get(round_name, round_name)
        transformed_matches = []

        for match in matches:
            winner_seed = match.get("seed", 0)
            winner_name = match.get("name", "")
            score = match.get("score", {})
            winner_score = score.get("winner_score", 0) if score else 0
            loser_score = score.get("loser_score", 0) if score else 0

            # 승자 정보
            winner_info = seed_to_player.get(winner_seed, {"name": winner_name, "team": ""})

            # 패자 시드 추론 (토너먼트 대진 규칙: 1 vs 64, 2 vs 63, ...)
            bracket_size = max(seed_to_player.keys()) if seed_to_player else 64
            loser_seed = bracket_size - winner_seed + 1 if winner_seed <= bracket_size else 0
            loser_info = seed_to_player.get(loser_seed, {"name": "Unknown", "team": ""})

            transformed_matches.append({
                "player1_seed": winner_seed,
                "player1_name": winner_info.get("name", winner_name),
                "player1_team": winner_info.get("team", ""),
                "player1_score": winner_score,
                "player2_seed": loser_seed,
                "player2_name": loser_info.get("name", ""),
                "player2_team": loser_info.get("team", ""),
                "player2_score": loser_score,
                "winner_seed": winner_seed,
                "winner_name": winner_info.get("name", winner_name)
            })

        if transformed_matches:
            transformed_rounds[normalized_round] = transformed_matches

    # 원본 데이터 보존하면서 변환된 데이터 추가
    event_data["de_bracket"] = transformed_rounds
    event_data["de_seeding"] = seeding  # 시딩 데이터 별도 보존
    return event_data


@app.get("/competition/{event_cd}", response_class=HTMLResponse)
async def competition_detail_page(request: Request, event_cd: str, event: Optional[str] = None):
    """대회 상세 페이지"""
    comp = get_competition(event_cd)
    if not comp:
        raise HTTPException(status_code=404, detail="대회를 찾을 수 없습니다")

    # 특정 이벤트가 지정된 경우 이벤트 결과 페이지로
    if event:
        selected_event = None
        for e in comp.get("events", []):
            if e.get("sub_event_cd") == event:
                selected_event = e.copy()  # 복사본 사용
                break

        if selected_event:
            # DE 데이터 변환
            selected_event = transform_de_bracket(selected_event)

            return templates.TemplateResponse("event_result.html", {
                "request": request,
                "competition": comp,
                "event": selected_event
            })

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


# ==================== FencingLab API ====================

# FencingLab 분석기 (지연 로딩)
_fencinglab_analyzer = None

def get_fencinglab_analyzer():
    """FencingLab 분석기 싱글톤"""
    global _fencinglab_analyzer
    if _fencinglab_analyzer is None:
        from app.player_analytics import FencingLabAnalyzer
        _fencinglab_analyzer = FencingLabAnalyzer()
    return _fencinglab_analyzer


@app.get("/api/fencinglab/clubs/{club_name}/players")
async def fencinglab_club_players(club_name: str):
    """클럽별 선수 목록 (FencingLab 분석 대상)"""
    analyzer = get_fencinglab_analyzer()
    players = analyzer.get_club_players(club_name)
    return {
        "club": club_name,
        "players": players,
        "count": len(players)
    }


@app.get("/api/fencinglab/player/{player_name}")
async def fencinglab_player_analytics(
    player_name: str,
    team: str = Query(..., description="팀 이름 (필수 - 동명이인 구분)")
):
    """선수 분석 데이터 (FencingLab) - 이름+팀으로 동명이인 구분"""
    analyzer = get_fencinglab_analyzer()

    # 동명이인 확인
    if analyzer.has_homonym(player_name):
        teams = analyzer.get_teams_for_name(player_name)
        if team not in teams:
            raise HTTPException(
                status_code=400,
                detail=f"동명이인이 있습니다. 팀을 정확히 지정해주세요. 가능한 팀: {teams}"
            )

    # 허용된 클럽 소속인지 확인
    if not analyzer.is_allowed_player(player_name, team):
        raise HTTPException(
            status_code=403,
            detail="현재 최병철펜싱클럽 소속 선수만 분석 서비스를 이용할 수 있습니다."
        )

    analytics = analyzer.analyze_player(player_name, team)
    if not analytics:
        raise HTTPException(status_code=404, detail="선수 데이터를 찾을 수 없습니다.")

    return analytics.to_dict()


@app.get("/api/fencinglab/demo")
async def fencinglab_demo():
    """FencingLab 데모 데이터 (랜딩페이지용) - 실제 데이터 기반 v3"""
    analyzer = get_fencinglab_analyzer()

    # 데모용 선수 목록 (최병철펜싱클럽 대표 선수)
    demo_players = ["박소윤", "오주원", "구지효"]
    demo_team = "최병철펜싱클럽"
    demo_data = []

    for name in demo_players:
        analytics = analyzer.analyze_player(name, demo_team)
        if analytics:
            demo_data.append({
                "name": analytics.player_name,
                "team": analytics.team,
                "win_rate": analytics.win_rate,
                "total_matches": analytics.total_matches,
                "total_wins": analytics.total_wins,
                "total_losses": analytics.total_losses,
                "pool_win_rate": analytics.pool_win_rate,
                "de_win_rate": analytics.de_win_rate,
                "clutch_grade": analytics.clutch_grade,
                "clutch_rate": analytics.clutch_rate
            })

    return {
        "demo_players": demo_data,
        "club": "최병철펜싱클럽",
        "total_club_players": len(analyzer.get_club_players("최병철펜싱클럽"))
    }


@app.get("/fencinglab", response_class=HTMLResponse)
async def fencinglab_page(request: Request):
    """FencingLab 메인 페이지"""
    return templates.TemplateResponse("fencinglab.html", {
        "request": request,
        "title": "FencingLab - 선수 분석"
    })


@app.get("/fencinglab/player/{player_name}", response_class=HTMLResponse)
async def fencinglab_player_page(request: Request, player_name: str):
    """FencingLab 선수 분석 페이지"""
    return templates.TemplateResponse("fencinglab_player.html", {
        "request": request,
        "title": f"{player_name} - FencingLab",
        "player_name": player_name
    })


# ==================== 익산 국제대회 API ====================

@app.get("/api/iksan/data")
async def get_iksan_data():
    """익산 국제대회 데이터 조회"""
    iksan_file = DATA_DIR / "iksan_international_2025.json"

    if not iksan_file.exists():
        return {"status": "no_data", "message": "익산 대회 데이터가 없습니다"}

    try:
        with open(iksan_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return {
            "status": "ok",
            "scraped_at": data.get("scraped_at"),
            "competition_name": data.get("competition_name"),
            "event_count": len(data.get("events", [])),
            "result_count": len(data.get("results", [])),
            "events": data.get("events", []),
        }
    except Exception as e:
        logger.error(f"익산 데이터 로드 오류: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/iksan/event/{event_name}")
async def get_iksan_event(event_name: str):
    """익산 대회 특정 종목 결과 조회"""
    iksan_file = DATA_DIR / "iksan_international_2025.json"

    if not iksan_file.exists():
        raise HTTPException(status_code=404, detail="익산 대회 데이터가 없습니다")

    try:
        with open(iksan_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # event_name 검색 (부분 매칭)
        for result in data.get("results", []):
            if event_name in result.get("event_name", ""):
                return {
                    "status": "ok",
                    "event_name": result.get("event_name"),
                    "age_category": result.get("age_category"),
                    "mapped_age_group": result.get("mapped_age_group"),
                    "pools": result.get("pools", []),
                }

        raise HTTPException(status_code=404, detail=f"종목을 찾을 수 없습니다: {event_name}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"익산 종목 데이터 로드 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/iksan/update")
async def trigger_iksan_update():
    """익산 대회 업데이트 트리거 (수동)"""
    try:
        from scraper.iksan_international import check_iksan_updates
        await check_iksan_updates()
        return {"status": "ok", "message": "익산 대회 업데이트 완료"}
    except Exception as e:
        logger.error(f"익산 업데이트 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
