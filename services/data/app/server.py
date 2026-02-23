"""
Korean Fencing Tracker - FastAPI 웹 서버
선수 중심 검색 + 필터 기반 UI
포트: 내부 71, 외부 7171

데이터 소스: Supabase (전용)
데이터 파이프라인: 4단계 검증 시스템
"""
import os
import json
import re
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import List, Optional, Dict, Any, Set
from pathlib import Path
from collections import defaultdict

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
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
    logger.error("supabase 패키지가 설치되지 않음. 서버 실행 불가.")

# 데이터 파이프라인 (품질 모니터링)
try:
    from data_pipeline import DataQualityMonitor, DataSynchronizer
    PIPELINE_AVAILABLE = True
except ImportError:
    PIPELINE_AVAILABLE = False
    logger.warning("data_pipeline 패키지를 찾을 수 없음. 품질 모니터링 비활성화.")

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

# DE 대진표 정규화 및 순위 계산
from app.bracket_utils import normalize_bracket_data, NormalizedBracket, compute_full_final_rankings

# i18n 다국어 지원 시스템
from app.i18n import (
    i18n,
    get_translator,
    LanguageMiddleware,
    create_language_context,
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES
)

# 다국어 번역 서비스 (DB 콘텐츠 번역)
from app.translation_service import get_translation_service


def _normalize_de_bracket_for_api(de_bracket: Dict) -> Dict:
    """
    API 응답용 DE 브라켓 정규화

    원본 구조를 유지하면서 bouts_by_round만 리매핑
    (bracket_size에 맞지 않는 라운드를 올바른 라운드로 변환)
    """
    if not de_bracket:
        return de_bracket

    # normalize_bracket_data 호출하여 리매핑 수행
    normalized = normalize_bracket_data(de_bracket)

    # 원본 구조 복사
    result = dict(de_bracket)

    # 정규화된 값으로 교체
    result['bracket_size'] = normalized.bracket_size
    result['participant_count'] = normalized.participant_count
    result['starting_round'] = normalized.starting_round
    result['rounds'] = normalized.rounds

    # bouts_by_round 교체 (리매핑된 버전)
    result['bouts_by_round'] = {
        round_name: [bout.to_dict() for bout in bouts]
        for round_name, bouts in normalized.bouts_by_round.items()
    }

    # bouts도 교체 (리매핑된 버전)
    result['bouts'] = [bout.to_dict() for bout in normalized.bouts]

    return result

# Auth - account 서비스로의 리다이렉트 shim + 로컬 JWT 검증
from shared_core.auth.jwt import get_current_member
from app.auth.router import router as auth_router

# Club Management 모듈 (SaaS)
from app.club import club_router

# 글로벌 연령 그룹 정렬 순서 (FIE 표준)
AGE_GROUP_ORDER = ["Y8", "Y10", "Y12", "Y14", "Cadet", "Junior", "Veteran", "National"]

# 레거시 → FIE 코드 변환 (DB에 E1/E2/E3/MS/HS/UNI/SR로 저장됨)
LEGACY_TO_FIE_MAP = {
    "E1": "Y8",    # 초등 1-2학년
    "E2": "Y10",   # 초등 3-4학년
    "E3": "Y12",   # 초등 5-6학년
    "MS": "Y14",   # 중등
    "HS": "Cadet", # 고등
    "UNI": "Junior", # 대학
    "SR": "Veteran", # 일반
    "U17": "Cadet",  # U17 → Cadet에 매핑 (Y14와 Cadet 양쪽에서 표시됨)
}

# FIE → 레거시 역방향 변환 (필터링용)
FIE_TO_LEGACY_MAP = {
    "Y8": ["E1"],
    "Y10": ["E2"],
    "Y12": ["E3"],
    "Y14": ["MS", "U17"],  # U17은 Y14 필터에서도 표시
    "Cadet": ["HS", "U17"], # U17은 Cadet 필터에서도 표시
    "Junior": ["UNI"],
    "Veteran": ["SR"],
}

def convert_to_fie_code(legacy_code: str) -> str:
    """레거시 코드를 FIE 코드로 변환"""
    return LEGACY_TO_FIE_MAP.get(legacy_code, legacy_code)

def get_matching_legacy_codes(fie_code: str) -> list:
    """FIE 코드에 매칭되는 레거시 코드 목록 반환"""
    return FIE_TO_LEGACY_MAP.get(fie_code, [fie_code])

# 환경변수 로드
load_dotenv()

# 프로젝트 루트
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATIC_DIR = PROJECT_ROOT / "static"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# Lifespan context manager (FastAPI 0.109+)
@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 실행되는 lifespan 이벤트

    Startup:
        - Supabase 데이터 로드
        - 선수 인덱스 구축
        - 랭킹 계산기 초기화

    Shutdown:
        - 정리 작업
    """
    # Startup
    load_data()
    logger.info("✅ 서버 시작 완료 - Supabase 데이터 소스 사용 중")

    yield

    # Shutdown
    logger.info("서버 종료됨")

# FastAPI 앱
app = FastAPI(
    title="Korean Fencing Tracker",
    description="KFF 대회 결과 기반 선수 기록 분석 플랫폼",
    version="2.0.0",
    lifespan=lifespan
)

# CORS 미들웨어 (서브도메인 간 API 호출 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://account.fencingmind.ai",
        "https://club.fencingmind.ai",
        "https://community.fencingmind.ai",
        "https://shop.fencingmind.ai",
        "https://blog.fencingmind.ai",
        "https://analytics.fencingmind.ai",
        "http://localhost:70",  # account dev
        "http://localhost:72",  # club dev
        "http://localhost:73",  # community dev
        "http://localhost:74",  # shop dev
        "http://localhost:75",  # blog dev
        "http://localhost:76",  # analytics dev
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 정적 파일 및 템플릿
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# i18n 미들웨어 추가
app.add_middleware(LanguageMiddleware)

# Auth 리다이렉트 shim (기존 템플릿 호환성)
app.include_router(auth_router)

# Club Management 라우터 등록 (SaaS)
app.include_router(club_router, prefix="/api")

# 데이터 저장소 (메모리 캐시)
_data_cache: Dict[str, Any] = {}
_player_index: Dict[str, List[Dict]] = {}  # 선수별 전적 인덱스
_filter_options: Dict[str, Set] = {}  # 필터 옵션 캐시
_ranking_calculator: Optional[RankingCalculator] = None  # 랭킹 계산기
_supabase_client: Optional["Client"] = None  # Supabase 클라이언트
_data_source: str = "supabase"  # 현재 데이터 소스 (Supabase 전용)
_identity_resolver: Optional[PlayerIdentityResolver] = None  # 선수 식별 시스템
_fencinglab_analyzer = None  # FencingLab 분석기 (지연 로딩)
_quality_monitor: Optional["DataQualityMonitor"] = None  # 데이터 품질 모니터


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
    display_name: str = ""  # 언어별 표시 이름
    teams: List[str]
    display_teams: List[str] = []  # 언어별 표시 팀명
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
    rank: Optional[int] = None
    competition_name: str
    competition_date: str
    event_name: str
    weapon: str
    gender: str
    age_group: str
    event_type: str = "개인"  # 기본값: 개인
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
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str
    location: str = ""
    event_count: int = 0
    year: int = 0


# ==================== i18n Helper Functions ====================

def get_i18n_template_context(request: Request, lang: str = None) -> Dict[str, Any]:
    """
    템플릿에 전달할 i18n 컨텍스트를 생성합니다.

    Args:
        request: FastAPI Request 객체
        lang: 언어 코드 (없으면 request.state에서 가져옴)

    Returns:
        템플릿 컨텍스트에 추가할 i18n 관련 딕셔너리
    """
    if lang is None:
        lang = getattr(request.state, 'lang', DEFAULT_LANGUAGE)

    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE

    return {
        'lang': lang,
        't': get_translator(lang),
        'supported_langs': SUPPORTED_LANGUAGES,
        'alternate_urls': getattr(request.state, 'alternate_urls', {}),
        'i18n': i18n.get_for_template(lang),
    }


def get_localized_name(record: Dict, lang: str, name_field: str = "name") -> str:
    """
    레코드에서 언어별 이름을 가져옵니다.

    Args:
        record: translations 필드가 있는 DB 레코드
        lang: 언어 코드 (ko/en)
        name_field: 원본 이름 필드명 (name, player_name, comp_name 등)

    Returns:
        해당 언어의 이름 또는 원본 이름 (fallback)
    """
    # 한국어는 항상 원본 반환
    if lang == 'ko':
        return record.get(name_field, '')

    # 다른 언어는 translations에서 검색
    translations = record.get('translations')
    if isinstance(translations, dict):
        lang_data = translations.get(lang, {})
        if isinstance(lang_data, dict) and lang_data.get('name'):
            return lang_data['name']

    # fallback: 원본 이름
    return record.get(name_field, '')


def localize_player_data(player: Dict, lang: str) -> Dict:
    """
    선수 데이터에 display_name 필드 추가.

    Args:
        player: 선수 데이터 (player_name, team_name, translations 포함)
        lang: 언어 코드

    Returns:
        display_name, display_team 필드가 추가된 선수 데이터
    """
    result = dict(player)
    result['display_name'] = get_localized_name(player, lang, 'player_name')

    # 팀명도 번역 (organization의 translations 사용)
    # team_name은 직접 번역하지 않고 원본 유지 (org는 별도 처리 필요)
    result['display_team'] = player.get('team_name', '')

    return result


async def get_localized_player_name(supabase: "Client", player_name: str, lang: str) -> str:
    """
    Supabase에서 선수 이름의 번역을 조회합니다.

    Args:
        supabase: Supabase 클라이언트
        player_name: 한국어 선수명
        lang: 언어 코드

    Returns:
        번역된 이름 또는 원본 이름
    """
    if lang == 'ko':
        return player_name

    try:
        result = supabase.table('players').select(
            'player_name', 'translations'
        ).eq('player_name', player_name).limit(1).execute()

        if result.data:
            return get_localized_name(result.data[0], lang, 'player_name')
    except Exception as e:
        logger.warning(f"Failed to get translation for {player_name}: {e}")

    return player_name


async def get_localized_org_name(supabase: "Client", org_name: str, lang: str) -> str:
    """
    Supabase에서 조직명의 번역을 조회합니다.

    Args:
        supabase: Supabase 클라이언트
        org_name: 한국어 조직명
        lang: 언어 코드

    Returns:
        번역된 이름 또는 원본 이름
    """
    if lang == 'ko':
        return org_name

    try:
        result = supabase.table('organizations').select(
            'name', 'translations'
        ).eq('name', org_name).limit(1).execute()

        if result.data:
            return get_localized_name(result.data[0], lang, 'name')
    except Exception as e:
        logger.warning(f"Failed to get translation for {org_name}: {e}")

    return org_name


# ==================== Data Loading & Indexing ====================

def extract_age_group(event_name: str) -> str:
    """
    종목명에서 연령대 추출 (FIE/US Fencing 글로벌 표준)

    글로벌 연령 구분:
    - Y8: 초등 1-2학년 (Under 9, 9세이하)
    - Y10: 초등 3-4학년 (Under 11, 11세이하)
    - Y12: 초등 5-6학년 (Under 13, 13세이하)
    - Y14: 중등부 (Under 15)
    - U17: 17세이하 (특수: Y14와 Cadet 양쪽에서 필터링됨)
    - Cadet: 고등부 (Under 17, 17세이하)
    - Junior: 대학부 (Under 20, 20세이하)
    - Veteran: 일반부 (Open/Senior)

    익산 국제대회 매핑:
    - U9 (9세이하) = Y8
    - U11 (11세이하) = Y10
    - U13 (13세이하) = Y12
    - U17 (17세이하) = U17 (특수 코드 - Y14 & Cadet 양쪽 필터)
    - U20 (20세이하) = Junior
    """
    # 초등부 세분화 패턴 (학년 기반)
    elem_patterns = [
        (r'초등.*1[-~]?2|초등부.*1[-~]?2|1[-~]?2학년', 'Y8'),
        (r'초등.*3[-~]?4|초등부.*3[-~]?4|3[-~]?4학년', 'Y10'),
        (r'초등.*5[-~]?6|초등부.*5[-~]?6|5[-~]?6학년', 'Y12'),
    ]

    # 익산 국제대회 U 코드 패턴 (우선 처리 - 더 구체적)
    # U17 (17세이하)는 특수 코드 'U17' 반환 → Y14와 Cadet 양쪽에서 필터링
    iksan_u_patterns = [
        (r'(?<!\d)9세이하|U9\b', 'Y8'),      # U9 = Y8
        (r'11세이하|U11\b', 'Y10'),           # U11 = Y10
        (r'13세이하|U13\b', 'Y12'),           # U13 = Y12
        (r'17세이하|U17\b', 'U17'),           # U17 = 특수 코드 (Y14 + Cadet)
        (r'20세이하|U20\b', 'Junior'),        # U20 = Junior
    ]

    # 나이 기반 패턴
    age_patterns = [
        (r'(?<!\d)8세이하|U8\b|Y8\b', 'Y8'),
        (r'(?<!\d)10세이하|U10\b|Y10\b', 'Y10'),
        (r'12세이하|U12\b|Y12\b', 'Y12'),
        (r'14세이하|U14\b|Y14\b', 'Y14'),
        (r'15세이하|16세이하|18세이하|U15\b|U16\b|U18\b', 'Cadet'),
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

    # 익산 U 코드 패턴 체크 (17세이하 특수 처리)
    for pattern, group in iksan_u_patterns:
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


def get_event_age_group_fie(event: dict) -> str:
    """
    이벤트의 연령대를 FIE 코드로 반환

    1. 데이터베이스의 age_group 필드 우선 사용
    2. 없으면 이벤트명에서 추출
    3. 레거시 코드는 FIE 코드로 변환

    Args:
        event: 이벤트 딕셔너리 (age_group, name 필드 포함)

    Returns:
        FIE 연령대 코드 (Y8, Y10, Y12, Y14, Cadet, Junior, Veteran, U17)
    """
    # 1. 데이터베이스의 age_group 필드 우선
    db_age_group = event.get("age_group", "")

    if db_age_group:
        # 이미 FIE 코드이면 그대로 반환
        if db_age_group in ("Y8", "Y10", "Y12", "Y14", "Cadet", "Junior", "Veteran"):
            return db_age_group
        # U17은 그대로 유지 (특수 케이스)
        if db_age_group == "U17":
            return "U17"
        # 레거시 코드면 FIE 코드로 변환
        fie_code = convert_to_fie_code(db_age_group)
        if fie_code != db_age_group:  # 변환 성공
            return fie_code

    # 2. 이벤트명에서 추출
    extracted = extract_age_group(event.get("name", ""))

    # 추출된 코드도 FIE로 변환
    if extracted:
        if extracted in ("Y8", "Y10", "Y12", "Y14", "Cadet", "Junior", "Veteran", "U17"):
            return extracted
        return convert_to_fie_code(extracted)

    return ""


def matches_age_group_filter(event_age: str, filter_age: str) -> bool:
    """
    이벤트 연령대가 필터 조건과 매칭되는지 확인

    특수 케이스:
    - U17 (17세이하): Y14 필터와 Cadet 필터 양쪽에서 매칭됨
    - 선수들은 Y14와 Cadet 카테고리에서 모두 경기 결과 반영

    Args:
        event_age: 이벤트의 연령대 코드 (FIE 코드)
        filter_age: 사용자가 선택한 필터 연령대 (FIE 코드)

    Returns:
        True if matches, False otherwise
    """
    # 정확히 일치하면 매칭
    if event_age == filter_age:
        return True

    # U17 특수 처리: Y14 또는 Cadet 필터에서 U17 이벤트 표시
    if event_age == 'U17':
        if filter_age in ('Y14', 'Cadet'):
            return True

    return False


def build_player_index():
    """선수별 전적 인덱스 구축 (v2 데이터 구조 지원)

    중요: 선수 랭킹/기록은 엘리미나시옹디렉트 (final_rankings) 결과만 사용
    Pool/DE 경기 통계는 별도 필드로 포함
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

            # 참가자 수 계산: pool_total_ranking > de_bracket > final_rankings 순서
            pool_ranking = event.get("pool_total_ranking", [])
            de_bracket = event.get("de_bracket", {})
            final_rankings = event.get("final_rankings", [])
            total_participants = (
                event.get("total_participants") or
                len(pool_ranking) or
                (de_bracket.get("participant_count", 0) if isinstance(de_bracket, dict) else 0) or
                len(final_rankings)
            )

            # Pool 통계 맵 구축 (player_name -> {wins, losses})
            pool_stats = {}
            pool_rounds = event.get("pool_rounds", [])
            for pool in pool_rounds:
                for result in pool.get("results", []):
                    pname = result.get("name", "").strip()
                    if pname:
                        wins = result.get("wins", 0) or 0
                        losses = result.get("losses", 0) or 0
                        if pname in pool_stats:
                            pool_stats[pname]["wins"] += wins
                            pool_stats[pname]["losses"] += losses
                        else:
                            pool_stats[pname] = {"wins": wins, "losses": losses}

            # DE 통계 맵 구축 (player_name -> {wins, losses})
            de_stats = {}
            if isinstance(de_bracket, dict):
                full_bouts = de_bracket.get("full_bouts", [])
                for bout in full_bouts:
                    if bout.get("is_bye"):
                        continue
                    winner = bout.get("winner_name") or bout.get("winner", {}).get("name", "")
                    loser = bout.get("loser_name") or bout.get("loser", {}).get("name", "")
                    if winner:
                        winner = winner.strip()
                        de_stats[winner] = de_stats.get(winner, {"wins": 0, "losses": 0})
                        de_stats[winner]["wins"] += 1
                    if loser:
                        loser = loser.strip()
                        de_stats[loser] = de_stats.get(loser, {"wins": 0, "losses": 0})
                        de_stats[loser]["losses"] += 1

            # 엘리미나시옹디렉트 (final_rankings)에서 선수 추출
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

                # Pool/DE 통계 가져오기
                player_pool = pool_stats.get(player_name, {"wins": 0, "losses": 0})
                player_de = de_stats.get(player_name, {"wins": 0, "losses": 0})

                # win_rate 형식: "wins/total" (Pool 기준)
                pool_total = player_pool["wins"] + player_pool["losses"]
                win_rate = f"{player_pool['wins']}/{pool_total}" if pool_total > 0 else ""

                record = {
                    "rank": final.get("rank"),
                    "competition_name": comp_name,
                    "competition_date": comp_date,
                    "event_name": event_name,
                    "weapon": event.get("weapon", ""),
                    "gender": event.get("gender", ""),
                    "age_group": age_group,
                    "event_type": event.get("event_type") or "개인",  # None 처리
                    "team": final.get("team", ""),
                    "win_rate": win_rate,
                    # Pool 상세 통계
                    "pool_wins": player_pool["wins"],
                    "pool_losses": player_pool["losses"],
                    # DE 상세 통계
                    "de_wins": player_de["wins"],
                    "de_losses": player_de["losses"],
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
                            "event_type": event.get("event_type") or "개인",  # None 처리
                            "team": final.get("team", ""),
                            "win_rate": "",
                            "pool_wins": 0,
                            "pool_losses": 0,
                            "de_wins": 0,
                            "de_losses": 0,
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

            # 데이터베이스 age_group 필드 우선, FIE 코드로 변환
            age_group = get_event_age_group_fie(event)
            if age_group:
                # U17은 드롭다운에 표시하지 않음 (Y14와 Cadet 양쪽 필터에서 표시됨)
                if age_group != "U17":
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
    """Supabase에서 데이터 로드 (타임아웃 방지 페이지네이션)"""
    global _data_cache, _data_source
    import time

    if not _supabase_client:
        return False

    try:
        # 대회 목록 조회 (132개로 작음 - 타임아웃 가능성 낮음)
        comp_result = _supabase_client.table("competitions").select("*").execute()
        if not comp_result.data:
            logger.warning("Supabase에 대회 데이터 없음")
            return False

        competitions_dict = {c["id"]: c for c in comp_result.data}
        logger.info(f"대회 {len(comp_result.data)}개 로드됨")

        # 종목 목록 조회 (페이지네이션 - 배치 크기 축소로 타임아웃 방지)
        all_events = []
        page_size = 200  # 1000 → 200 (타임아웃 방지)
        offset = 0
        max_retries = 3

        while True:
            # 재시도 로직
            for attempt in range(max_retries):
                try:
                    events_result = _supabase_client.table("events").select("*").range(offset, offset + page_size - 1).execute()
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2  # 2초, 4초, 6초
                        logger.warning(f"종목 로드 재시도 {attempt + 1}/{max_retries} ({wait_time}초 대기): {e}")
                        time.sleep(wait_time)
                    else:
                        raise

            if not events_result.data:
                break
            all_events.extend(events_result.data)
            logger.debug(f"종목 로드 진행: {len(all_events)}개")
            if len(events_result.data) < page_size:
                break
            offset += page_size
            time.sleep(0.1)  # API 부하 분산

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

                # 참가자 수 계산: pool_total_ranking > de_bracket > final_rankings 순서로 확인
                pool_ranking = raw.get("pool_total_ranking", [])
                de_bracket = raw.get("de_bracket", {})
                final_rankings = raw.get("final_rankings", [])

                total_participants = (
                    raw.get("total_participants") or  # 명시적으로 저장된 값
                    len(pool_ranking) or  # Pool 참가자 수 (가장 정확)
                    de_bracket.get("participant_count", 0) or  # DE 대진표 참가자 수
                    len(final_rankings)  # 최종 순위 (최소값, fallback)
                )

                event_data = {
                    "event_cd": e["event_cd"],
                    "sub_event_cd": e["sub_event_cd"],
                    "name": e["event_name"],
                    "weapon": e["weapon"],
                    "gender": e["gender"],
                    "event_type": e["category"],  # category -> event_type
                    "age_group": e["age_group"],
                    "total_participants": total_participants,
                    "pool_rounds": filtered_pools,
                    "pool_total_ranking": raw.get("pool_total_ranking", []),
                    "final_rankings": raw.get("final_rankings", []),
                    "de_bracket": _normalize_de_bracket_for_api(raw.get("de_bracket", {})),
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
    """데이터 로드 (Supabase 전용)

    🚨 CRITICAL: JSON 파일 사용 금지!
    모든 데이터는 Supabase에서 로드합니다.
    CLAUDE.md의 데이터 소스 규칙을 반드시 확인하세요.
    """
    global _data_cache, _ranking_calculator, _data_source, _fencinglab_analyzer

    # FencingLab 분석기 리셋
    _fencinglab_analyzer = None

    # Supabase 클라이언트 초기화
    init_supabase_client()

    # Supabase에서 데이터 로드 (유일한 데이터 소스)
    if _supabase_client and load_data_from_supabase():
        logger.info("✅ Supabase 데이터 소스 사용 중")
    else:
        logger.error("❌ Supabase 데이터 로드 실패 - 데이터 소스 없음")
        _data_cache = {"competitions": [], "meta": {}}
        _data_source = "none"
        return

    # 인덱스 구축
    build_filter_options()
    build_player_index()
    build_identity_resolver()

    # 랭킹 계산기 초기화 (Supabase 캐시 데이터 사용)
    try:
        _ranking_calculator = RankingCalculator()
        _ranking_calculator.load_from_data(_data_cache)
        logger.info(f"✅ 랭킹 계산기 초기화 완료: {len(_ranking_calculator.results)}개 결과")
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

@app.get("/", response_class=HTMLResponse)
async def home_redirect(request: Request):
    """메인 페이지 - 기본 언어로 리다이렉트

    첫 방문자는 항상 한국어(ko)로 리다이렉트.
    쿠키가 있으면 쿠키 언어를 사용.
    Accept-Language 헤더는 무시 (브라우저 기본값 문제 방지)
    """
    from fastapi.responses import RedirectResponse

    # Only use cookie for language detection on root path
    # This ensures first-time visitors always see Korean
    lang_cookie = request.cookies.get('lang')
    if lang_cookie in SUPPORTED_LANGUAGES:
        lang = lang_cookie
    else:
        lang = DEFAULT_LANGUAGE  # Always Korean for first-time visitors

    return RedirectResponse(url=f"/{lang}/", status_code=302)


@app.get("/{lang}/", response_class=HTMLResponse)
async def home(request: Request, lang: str = "ko"):
    """메인 페이지 - 필터 기반 검색 (다국어 지원)"""
    if lang not in SUPPORTED_LANGUAGES:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=f"/{DEFAULT_LANGUAGE}/", status_code=302)

    context = {
        "request": request,
        "title": "Korean Fencing Tracker",
        **get_i18n_template_context(request, lang)
    }
    return templates.TemplateResponse("index.html", context)


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
        "pipeline_available": PIPELINE_AVAILABLE,
        "meta": _data_cache.get("meta", {})
    }


@app.post("/api/data/reload")
async def api_data_reload():
    """데이터 새로고침 API

    Supabase에서 최신 데이터를 다시 로드합니다.
    """
    global _data_cache, _data_source, _player_index

    try:
        load_data()
        return {
            "success": True,
            "message": "데이터 새로고침 완료",
            "meta": _data_cache.get("meta", {})
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"새로고침 실패: {str(e)}"
        }


@app.get("/api/data/quality")
async def api_data_quality():
    """데이터 품질 모니터링 API

    데이터 파이프라인의 품질 메트릭 및 알림을 조회합니다.
    """
    global _quality_monitor

    if not PIPELINE_AVAILABLE:
        return {
            "available": False,
            "message": "데이터 파이프라인이 설치되지 않았습니다."
        }

    # 품질 모니터 초기화 (지연 로딩)
    if _quality_monitor is None and _supabase_client:
        _quality_monitor = DataQualityMonitor(db_client=_supabase_client)

    if _quality_monitor is None:
        return {
            "available": False,
            "message": "Supabase 연결이 필요합니다."
        }

    try:
        # 최근 메트릭 조회
        recent_metrics = _quality_monitor.get_recent_metrics(hours=24)

        # 활성 알림 조회
        active_alerts = _quality_monitor.get_active_alerts()

        # 건강 상태 계산
        health_status = _quality_monitor.get_health_status()

        return {
            "available": True,
            "health": health_status,
            "metrics": recent_metrics,
            "alerts": active_alerts,
            "last_updated": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"품질 모니터링 조회 오류: {e}")
        return {
            "available": True,
            "error": str(e),
            "health": {"status": "unknown", "message": "조회 중 오류 발생"}
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
            # 데이터베이스 age_group 필드 우선, FIE 코드로 변환
            # U17 (17세이하)는 Y14와 Cadet 양쪽 필터에서 표시됨
            event_age = get_event_age_group_fie(event)
            if age_group and not is_national_filter and not matches_age_group_filter(event_age, age_group):
                continue

            # 검색어 필터
            if search:
                search_lower = search.lower()
                if (search_lower not in event.get("name", "").lower() and
                    search_lower not in comp_name.lower()):
                    continue

            events.append(EventSummary(
                event_cd=event.get("event_cd", "") or "",
                sub_event_cd=event.get("sub_event_cd", "") or "",
                name=event.get("name", "") or "",
                weapon=event.get("weapon", "") or "",
                gender=event.get("gender", "") or "",
                age_group=event_age or "",
                event_type=event.get("event_type", "") or "개인",  # 기본값: 개인
                competition_name=comp_name or "",
                competition_date=comp_date or "",
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
async def api_player_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(30, ge=1, le=500),
    include_history: bool = Query(False, description="Include players who were previously at the team (alumni)")
):
    """선수 검색 API (자동완성용) - 동명이인 구분 지원

    Args:
        q: 검색어 (선수 이름 또는 소속명)
        limit: 최대 결과 수 (기본 30, 최대 500)
        include_history: True면 과거 소속 선수도 포함 (이적 선수 추적용)
    """
    q_lower = q.lower()
    matches = []

    # 선수 식별 시스템 사용
    if _identity_resolver:
        search_results = _identity_resolver.search_players(q, include_history=include_history)

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
                "disambiguation_warning": profile.disambiguation_warning if profile.has_disambiguation_warning else None,
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

    return {"results": matches[:limit], "total": len(matches)}


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


@app.get("/api/players/debug/{player_id}")
async def api_player_debug(player_id: str):
    """선수 디버그용 상세 정보 (records 포함)"""
    if not _identity_resolver:
        raise HTTPException(status_code=503, detail="선수 식별 시스템이 초기화되지 않았습니다")

    profile = _identity_resolver.get_player_by_id(player_id)
    if not profile:
        raise HTTPException(status_code=404, detail="선수를 찾을 수 없습니다")

    # Check age group warning
    warning = profile.check_age_group_validity()

    return {
        "player_id": profile.player_id,
        "name": profile.name,
        "age_groups": list(profile.age_groups),
        "disambiguation_warning": warning,
        "records": [
            {
                "comp_name": r.get("comp_name", ""),
                "comp_date": r.get("comp_date", ""),
                "event_name": r.get("event_name", ""),
                "age_group": r.get("age_group", ""),
                "team": r.get("team", ""),
                "weapon": r.get("weapon", "")
            }
            for r in profile.records
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
    age_group: str = Query(..., description="연령대 (E1/E2/E3/MS/HS/UNI/SR/NT)"),
    category: Optional[str] = Query(None, description="구분 (PRO/CLUB) - 중학교 이상만"),
    year: Optional[int] = Query(None, description="시즌 연도"),
    lang: str = Query("ko", description="언어 코드 (ko/en)"),
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
    - NT: 국가대표 (국가대표 선발대회만 집계)

    구분:
    - PRO: 전문 선수
    - CLUB: 동호인 (클럽, 생활체육)

    언어:
    - ko: 한국어 (기본)
    - en: 영어
    """
    if not _ranking_calculator:
        raise HTTPException(status_code=503, detail="랭킹 시스템이 초기화되지 않았습니다")

    # 국가대표(NT) 특수 처리
    is_national_team = (age_group == "NT")

    # 중학교 이상이면서 카테고리 미지정 시 기본값 PRO
    # NT는 항상 PRO (국가대표 선발대회는 전문 대회)
    if is_national_team:
        category = "PRO"
    elif age_group in CATEGORY_APPLICABLE_AGE_GROUPS and not category:
        category = "PRO"
    elif age_group not in CATEGORY_APPLICABLE_AGE_GROUPS:
        # 초등부는 카테고리 무시
        category = None

    rankings = _ranking_calculator.calculate_rankings(
        weapon=weapon,
        gender=gender,
        age_group=age_group if not is_national_team else None,  # NT는 모든 연령대 포함
        category=category,
        year=year,
        national_team_only=is_national_team  # 국가대표 선발대회만 필터
    )

    # 페이지네이션
    total = len(rankings)
    start = (page - 1) * per_page
    end = start + per_page
    page_rankings = rankings[start:end]

    # 언어별 연령대 표시명
    age_group_display_map = {
        "ko": {
            "NT": "국가대표",
            "Y8": "Y8 (초등1-2)",
            "Y10": "Y10 (초등3-4)",
            "Y12": "Y12 (초등5-6)",
            "Y14": "Y14 (중등)",
            "Cadet": "Cadet (고등)",
            "Junior": "Junior (대학)",
            "Veteran": "Veteran (일반)",
        },
        "en": {
            "NT": "National Team",
            "Y8": "Y8 (Under 9)",
            "Y10": "Y10 (Under 11)",
            "Y12": "Y12 (Under 13)",
            "Y14": "Y14 (Under 15)",
            "Cadet": "Cadet (Under 17)",
            "Junior": "Junior (Under 20)",
            "Veteran": "Veteran (Senior)",
        }
    }

    # 언어별 카테고리 표시명
    category_display_map = {
        "ko": {"PRO": "전문", "CLUB": "동호인"},
        "en": {"PRO": "Professional", "CLUB": "Club"}
    }

    lang_map = age_group_display_map.get(lang, age_group_display_map["ko"])
    age_group_display = lang_map.get(age_group, AGE_GROUP_CODES.get(age_group, age_group))

    cat_map = category_display_map.get(lang, category_display_map["ko"])
    category_display = cat_map.get(category) if category else None

    # 선수 이름과 팀명 번역 준비
    ranking_entries = []
    for r in page_rankings:
        # 선수 이름 번역
        display_name = await get_localized_player_name(_supabase_client, r.player_name, lang)

        # 팀 이름들 번역
        teams_to_use = r.teams

        # 팀 정보가 없으면 players 테이블에서 폴백 조회
        if not teams_to_use:
            try:
                result = _supabase_client.table("players").select("team_name").eq("player_name", r.player_name).limit(1).execute()
                if result.data and result.data[0].get("team_name"):
                    teams_to_use = [result.data[0]["team_name"]]
            except Exception as e:
                logger.debug(f"팀 폴백 조회 실패 ({r.player_name}): {e}")

        display_teams = []
        for team in teams_to_use:
            display_team = await get_localized_org_name(_supabase_client, team, lang)
            display_teams.append(display_team)

        ranking_entries.append(RankingEntry(
            rank=r.current_rank,
            name=r.player_name,
            display_name=display_name,
            teams=teams_to_use,
            display_teams=display_teams,
            points=r.total_points,
            competitions=r.competitions_count,
            gold=r.gold_count,
            silver=r.silver_count,
            bronze=r.bronze_count,
            best_results=r.best_results
        ))

    return RankingResponse(
        weapon=weapon,
        gender=gender,
        age_group=age_group,
        age_group_name=age_group_display,
        category=category,
        category_name=category_display,
        total=total,
        rankings=ranking_entries
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
            {"code": "NT", "name": "🇰🇷 국가대표", "has_category": True, "is_national": True},
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
                # final_rankings로 검증용 맵 생성 (순위가 높을수록 더 오래 생존 = 더 많이 이김)
                final_rankings = event.get("final_rankings", [])
                rankings_map = {}
                for r in final_rankings:
                    r_name = r.get("name", "")
                    r_rank = r.get("rank", 999)
                    if r_name:
                        rankings_map[r_name] = r_rank

                # 새로운 full_bouts 구조 처리 (2025년 스크래핑 데이터)
                full_bouts = de_bracket.get("full_bouts", [])
                if full_bouts and isinstance(full_bouts, list):
                    # table_index 높은 순으로 정렬 (최종 결과가 더 정확함)
                    sorted_bouts = sorted(
                        [b for b in full_bouts if isinstance(b, dict)],
                        key=lambda x: x.get("table_index", 0),
                        reverse=True
                    )

                    # 먼저 해당 선수가 관련된 경기들만 수집
                    player_bouts = []
                    for bout in sorted_bouts:
                        if not isinstance(bout, dict):
                            continue
                        winner = bout.get("winner", {})
                        loser = bout.get("loser", {})
                        w_name = winner.get("name", "")
                        l_name = loser.get("name", "")

                        if w_name == player_name or l_name == player_name:
                            player_bouts.append(bout)

                    # 같은 상대에 대해 여러 결과가 있으면 final_rankings로 검증
                    seen_de_opponents = set()
                    for bout in player_bouts:
                        winner = bout.get("winner", {})
                        loser = bout.get("loser", {})
                        round_name = bout.get("round", "DE")

                        opponent_name = None
                        my_score = 0
                        opponent_score = 0
                        result = None
                        opponent_team = ""

                        # 선수가 winner인 경우
                        if winner.get("name") == player_name:
                            if profile_teams and winner.get("team") not in profile_teams:
                                continue
                            opponent_name = loser.get("name")
                            opponent_team = loser.get("team", "")
                            my_score = winner.get("score") or 0
                            opponent_score = loser.get("score") or 0
                            result = "V"
                        # 선수가 loser인 경우
                        elif loser.get("name") == player_name:
                            if profile_teams and loser.get("team") not in profile_teams:
                                continue
                            opponent_name = winner.get("name")
                            opponent_team = winner.get("team", "")
                            my_score = loser.get("score") or 0
                            opponent_score = winner.get("score") or 0
                            result = "D"

                        if opponent_name and opponent_name != player_name:
                            # final_rankings로 결과 검증 (순위 높은 쪽이 이긴 것)
                            # 스크래퍼 버그: 점수 위치를 승자로 잘못 해석하는 문제 수정
                            if rankings_map and opponent_name in rankings_map and player_name in rankings_map:
                                my_rank = rankings_map.get(player_name, 999)
                                opp_rank = rankings_map.get(opponent_name, 999)
                                # 순위가 더 높은(숫자가 작은) 선수가 이긴 것
                                correct_result = "V" if my_rank < opp_rank else "D"
                                if result != correct_result:
                                    # 스크래퍼 데이터가 잘못됨 - 수정
                                    result = correct_result
                                    # 점수도 뒤바꿈
                                    my_score, opponent_score = opponent_score, my_score

                            # DE에서는 같은 대회/종목에서 같은 상대와 한 번만 만남 (single elimination)
                            de_match_key = f"{comp_name}|{event_name}|{opponent_name}"
                            if de_match_key in seen_matches:
                                continue
                            seen_matches.add(de_match_key)
                            seen_de_opponents.add(opponent_name)

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
                                "round": round_name,
                                "score": f"{my_score}-{opponent_score}",
                                "result": result
                            })
                else:
                    # 기존 구조 (round_name: [matches] 형태) 처리
                    for round_name, matches in de_bracket.items():
                        if not isinstance(matches, list):
                            continue
                        for match in matches:
                            if not isinstance(match, dict):
                                continue

                            opponent_name = None
                            my_score = 0
                            opponent_score = 0
                            result = None
                            opponent_team = ""

                            if match.get("player1_name") == player_name:
                                if profile_teams and match.get("player1_team") not in profile_teams:
                                    continue
                                opponent_name = match.get("player2_name")
                                opponent_team = match.get("player2_team", "")
                                my_score = match.get("player1_score", 0)
                                opponent_score = match.get("player2_score", 0)
                                result = "V" if match.get("winner_name") == player_name else "D"
                            elif match.get("player2_name") == player_name:
                                if profile_teams and match.get("player2_team") not in profile_teams:
                                    continue
                                opponent_name = match.get("player1_name")
                                opponent_team = match.get("player1_team", "")
                                my_score = match.get("player2_score", 0)
                                opponent_score = match.get("player1_score", 0)
                                result = "V" if match.get("winner_name") == player_name else "D"

                            if opponent_name and opponent_name != player_name:
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
                                    "round": round_name,
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

@app.get("/player/by-id/{player_id}", response_class=HTMLResponse)
async def player_page_by_id(request: Request, player_id: str):
    """선수 ID로 프로필 페이지 접근 (KOP00000 형식)"""
    if not _identity_resolver:
        raise HTTPException(status_code=503, detail="선수 식별 시스템이 초기화되지 않았습니다")

    profile = _identity_resolver.get_player_by_id(player_id)
    if not profile:
        raise HTTPException(status_code=404, detail="선수를 찾을 수 없습니다")

    from fastapi.responses import RedirectResponse
    return RedirectResponse(
        url=f"/player/{profile.name}?id={player_id}",
        status_code=302
    )


@app.get("/player/{player_name}/certificate", response_class=HTMLResponse)
async def player_certificate_page(
    request: Request,
    player_name: str,
    id: Optional[str] = None,
    team: Optional[str] = None,
    weapon: Optional[str] = None
):
    """선수 대회 기록 증명서 (인쇄용 영문 페이지)"""
    from datetime import datetime

    # Translation mappings
    competition_translations = {
        '코리아 익산 인터내셔널': 'Korea Iksan International',
        '대한펜싱협회장배': 'KFA President Cup',
        'FILA배': 'FILA Cup',
        '생활체육': 'Recreational',
        '클럽·동호인': 'Club',
        '전국남녀종별': 'National Championship',
        '회장배': 'President Cup',
        '펜싱 클럽 코리아 오픈': 'Club Korea Open',
        '전국남녀대학': 'National University',
        '한국중고펜싱연맹': 'KFA Middle/High School',
    }

    event_translations = {
        '플러레': 'Foil',
        '에뻬': 'Epee',
        '사브르': 'Sabre',
        '여자': 'Women\'s',
        '남자': 'Men\'s',
        '초등부(5-6학년)': 'Elem 5-6',
        '초등부(3-4학년)': 'Elem 3-4',
        '초등부(1-2학년)': 'Elem 1-2',
        '13세이하부': 'U13',
        '17세이하부': 'U17',
        '20세이하부': 'U20',
        '여중': 'MS Women\'s',
        '남중': 'MS Men\'s',
        '여고': 'HS Women\'s',
        '남고': 'HS Men\'s',
        '남대': 'Univ Men\'s',
        '여대': 'Univ Women\'s',
        '(개)': '(Ind)',
        '(단)': '(Team)',
    }

    team_translations = {
        '최병철펜싱클럽': 'Choi Byungchul Fencing Club',
        '송도펜싱클럽': 'Songdo Fencing Club',
        '덕원중학교': 'Dukwon Middle School',
    }

    def translate_text(text, mappings):
        result = text
        for kr, en in mappings.items():
            result = result.replace(kr, en)
        return result

    def ordinal(n):
        if 10 <= n % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
        return f"{n}{suffix}"

    # Get player data
    identity_profile = None
    if _identity_resolver:
        if id:
            identity_profile = _identity_resolver.get_player_by_id(id)
        if not identity_profile:
            profiles = _identity_resolver.get_players_by_name(player_name)
            if team:
                for p in profiles:
                    if team in p.teams:
                        identity_profile = p
                        break
            if not identity_profile and profiles:
                identity_profile = profiles[0]

    # Get records
    records_to_use = []
    if identity_profile:
        records_to_use = identity_profile.records
    else:
        # Fallback to search
        player_records = get_player_records(player_name, team)
        records_to_use = player_records

    # Filter by weapon if specified
    weapon_filter_display = None
    if weapon:
        records_to_use = [r for r in records_to_use if r.get('weapon') == weapon]
        weapon_filter_display = event_translations.get(weapon, weapon)

    # Calculate stats
    gold = sum(1 for r in records_to_use if r.get('rank') == 1)
    silver = sum(1 for r in records_to_use if r.get('rank') == 2)
    bronze = sum(1 for r in records_to_use if r.get('rank') == 3)
    top8 = sum(1 for r in records_to_use if r.get('rank', 99) <= 8)

    stats = {
        'total': len(records_to_use),
        'gold': gold,
        'silver': silver,
        'bronze': bronze,
        'top8': top8
    }

    # Prepare records for display
    display_records = []
    for r in records_to_use:
        comp_name = translate_text(r.get('competition_name', ''), competition_translations)
        event_name = translate_text(r.get('event_name', ''), event_translations)
        rank = r.get('rank', 0)

        display_records.append({
            'date': r.get('competition_date', ''),
            'competition': comp_name[:45] + '...' if len(comp_name) > 45 else comp_name,
            'event': event_name[:35] + '...' if len(event_name) > 35 else event_name,
            'rank': rank,
            'place': ordinal(rank) if rank else '-'
        })

    # Player info for template
    current_team = records_to_use[0].get('team', '') if records_to_use else ''
    player_info = {
        'name': player_name,
        'name_en': 'Park So-Yun' if player_name == '박소윤' else player_name,
        'player_id': id or (identity_profile.player_id if identity_profile else 'N/A'),
        'birth_date': 'Jul 24, 2013' if player_name == '박소윤' and (not weapon or weapon == '플러레') else 'N/A',
        'gender_en': 'Female' if any('여' in r.get('event_name', '') for r in records_to_use[:3]) else 'Male',
        'current_team': current_team,
        'club_en': team_translations.get(current_team, current_team),
    }

    return templates.TemplateResponse(
        "player_certificate.html",
        {
            "request": request,
            "player": player_info,
            "weapon_filter": weapon_filter_display,
            "stats": stats,
            "records": display_records,
            "issue_date": datetime.now().strftime('%B %d, %Y')
        }
    )


@app.get("/player/{player_name}", response_class=HTMLResponse)
async def player_page(request: Request, player_name: str, id: Optional[str] = None, team: Optional[str] = None):
    """선수 프로필 페이지 (fencingtracker 스타일)

    Args:
        player_name: 선수 이름 또는 선수 ID (KOP00000 형식)
        id: 선수 ID (동명이인 구분용, Optional)
        team: 소속팀 (동명이인 구분용, Optional)
    """
    # player_name이 실제로 player_id (KOP00000 형식)인 경우 처리
    if player_name.startswith("KOP") and _identity_resolver:
        profile = _identity_resolver.get_player_by_id(player_name)
        if profile:
            # 실제 이름으로 리다이렉트
            from fastapi.responses import RedirectResponse
            return RedirectResponse(
                url=f"/player/{profile.name}?id={player_name}",
                status_code=302
            )

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

    # 경기 통계 추출 (Pool + DE)
    for r in records:
        # Pool 통계 (새 형식)
        stage_stats["pool_wins"] += r.get("pool_wins", 0) or 0
        stage_stats["pool_losses"] += r.get("pool_losses", 0) or 0

        # DE 통계 (새 형식)
        stage_stats["de_wins"] += r.get("de_wins", 0) or 0
        stage_stats["de_losses"] += r.get("de_losses", 0) or 0

        # 레거시 win_rate 형식 지원 ("3/5")
        if r.get("win_rate") and not r.get("pool_wins"):
            try:
                parts = str(r["win_rate"]).split("/")
                if len(parts) == 2:
                    wins = int(parts[0])
                    total = int(parts[1])
                    stage_stats["pool_wins"] += wins
                    stage_stats["pool_losses"] += (total - wins)
            except:
                pass

    # 전체 통계 (Pool + DE)
    total_wins = stage_stats["pool_wins"] + stage_stats["de_wins"]
    total_losses = stage_stats["pool_losses"] + stage_stats["de_losses"]
    bout_stats["total"] = total_wins + total_losses
    bout_stats["wins"] = total_wins
    bout_stats["losses"] = total_losses
    if bout_stats["total"] > 0:
        bout_stats["win_rate"] = round(bout_stats["wins"] / bout_stats["total"] * 100, 1)

    # Pool 승률
    pool_total = stage_stats["pool_wins"] + stage_stats["pool_losses"]
    if pool_total > 0:
        stage_stats["pool_rate"] = round(stage_stats["pool_wins"] / pool_total * 100, 1)

    # DE 승률
    de_total = stage_stats["de_wins"] + stage_stats["de_losses"]
    if de_total > 0:
        stage_stats["de_rate"] = round(stage_stats["de_wins"] / de_total * 100, 1)

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
        # current_team: 가장 최근 소속팀 (FencingLab API에서 사용)
        "current_team": identity_profile.current_team if identity_profile else (teams[0] if teams else None),
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

    context = {
        "request": request,
        "player": player_data,
        "today": date.today().strftime("%b %d, %Y"),
        "title": f"{player_name} - Korean Fencing Tracker",
        **get_i18n_template_context(request)
    }
    return templates.TemplateResponse("player_profile.html", context)


@app.get("/{lang}/player/{player_name}", response_class=HTMLResponse)
async def player_page_i18n(request: Request, lang: str, player_name: str, id: Optional[str] = None, team: Optional[str] = None):
    """Language-prefixed player profile page - delegates to main player_page"""
    if lang not in ["ko", "en"]:
        raise HTTPException(status_code=404, detail="Not Found")
    return await player_page(request, player_name, id, team)


def transform_de_bracket(event_data: Dict) -> Dict:
    """DE bracket 데이터를 템플릿 호환 형식으로 변환 (bracket_utils 사용)"""
    de_bracket = event_data.get("de_bracket", {})
    if not de_bracket:
        return event_data

    # bracket_utils로 정규화
    normalized = normalize_bracket_data(de_bracket)

    # NormalizedBracket이 None인 경우 원본 반환
    if normalized is None:
        return event_data

    # NormalizedBracket 객체를 event_data에 추가
    event_data["normalized_bracket"] = normalized

    # 기존 템플릿 호환성을 위한 변환 (레거시 지원)
    # 속성명: bouts_by_round (matches_by_round 아님)
    transformed_rounds = {}
    if hasattr(normalized, 'bouts_by_round') and normalized.bouts_by_round:
        for round_name, bouts in normalized.bouts_by_round.items():
            transformed_rounds[round_name] = [b.to_dict() for b in bouts]

    event_data["de_bracket"] = transformed_rounds
    event_data["de_seeding"] = getattr(normalized, 'seeding', [])
    event_data["de_rounds"] = getattr(normalized, 'rounds', [])

    return event_data


# ==================== 익산 국제대회 리다이렉트 (레거시 URL 호환) ====================
# NOTE: 익산 대회 데이터는 Supabase에 통합됨 (COMPM00666, COMPM00673)
# 기존 URL을 위한 리다이렉트만 유지


@app.get("/competition/iksan-u17-u20")
async def iksan_u17_redirect():
    """익산 U17/U20 → Supabase 표준 대회 페이지로 리다이렉트"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/competition/COMPM00666", status_code=301)


@app.get("/competition/iksan-u13")
async def iksan_u13_redirect():
    """익산 U13/U11/U9 → Supabase 표준 대회 페이지로 리다이렉트"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/competition/COMPM00673", status_code=301)


@app.get("/competition/{event_cd}", response_class=HTMLResponse)
async def competition_detail_page(request: Request, event_cd: str, event: Optional[str] = None):
    """대회 상세 페이지"""
    from ranking.calculator import (
        calculate_points, classify_competition_tier, extract_age_group
    )

    comp = get_competition(event_cd)
    if not comp:
        raise HTTPException(status_code=404, detail="대회를 찾을 수 없습니다")

    # 특정 이벤트가 지정된 경우 이벤트 결과 페이지로
    if event:
        selected_event = None
        for e in comp.get("events", []):
            # sub_event_cd 또는 이벤트 이름으로 매칭
            if e.get("sub_event_cd") == event or e.get("name") == event:
                selected_event = e.copy()  # 복사본 사용
                break

        if selected_event:
            # 원본 DE 데이터 저장 (순위 계산에 필요)
            original_de_bracket = selected_event.get("de_bracket", {})
            pool_total_ranking = selected_event.get("pool_total_ranking", [])
            existing_rankings = selected_event.get("final_rankings", [])

            # DE 데이터 변환
            selected_event = transform_de_bracket(selected_event)

            # 전체 최종 순위 계산 - 기존 데이터가 불완전할 때만
            # 불완전 기준: 4등 이하만 있거나 (메달 순위만), 1등이 없는 경우
            needs_recompute = False
            if not existing_rankings:
                needs_recompute = True
            elif len(existing_rankings) <= 4:
                # 4명 이하면 불완전할 가능성 높음
                needs_recompute = True
            elif existing_rankings and existing_rankings[0].get("rank", 0) != 1:
                # 1등부터 시작하지 않으면 불완전
                needs_recompute = True

            if needs_recompute and (original_de_bracket or pool_total_ranking):
                computed_rankings = compute_full_final_rankings(
                    original_de_bracket,
                    pool_total_ranking
                )
                if computed_rankings:
                    selected_event["final_rankings"] = computed_rankings

            # 포인트 계산 및 추가
            comp_name = comp.get("competition", {}).get("name", "")
            tier = classify_competition_tier(comp_name)
            event_name = selected_event.get("name", "")
            age_group = extract_age_group(event_name)
            total_participants = selected_event.get("total_participants") or len(selected_event.get("final_rankings", []))

            # final_rankings에 포인트 추가 (v2: 참가자 수 기반 + 대회 권위 보정)
            for ranking in selected_event.get("final_rankings", []):
                rank = ranking.get("rank", 0)
                if rank > 0:
                    points = calculate_points(
                        tier=tier,
                        final_rank=rank,
                        total_participants=total_participants,
                        age_group=age_group,
                        competition_name=comp_name
                    )
                    ranking["points"] = points

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
async def rankings_redirect(request: Request):
    """Rankings 페이지 - 기본 언어로 리다이렉트 (쿠키 우선, Accept-Language 무시)"""
    from fastapi.responses import RedirectResponse
    lang_cookie = request.cookies.get('lang')
    lang = lang_cookie if lang_cookie in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    return RedirectResponse(url=f"/{lang}/rankings", status_code=302)


@app.get("/{lang}/rankings", response_class=HTMLResponse)
async def rankings_page(request: Request, lang: str = "ko"):
    """FencingLab Ranking 페이지 (다국어 지원)"""
    if lang not in SUPPORTED_LANGUAGES:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=f"/{DEFAULT_LANGUAGE}/rankings", status_code=302)

    context = {
        "request": request,
        "title": "FencingLab Ranking",
        **get_i18n_template_context(request, lang)
    }
    return templates.TemplateResponse("rankings.html", context)


# ==================== FencingLab API ====================

def get_fencinglab_analyzer():
    """FencingLab 분석기 싱글톤 (Supabase 캐시 사용)"""
    global _fencinglab_analyzer
    if _fencinglab_analyzer is None:
        from app.player_analytics import FencingLabAnalyzer
        # Supabase 캐시 데이터 전달 (JSON 파일 사용 안함)
        _fencinglab_analyzer = FencingLabAnalyzer(data=_data_cache)
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


@app.get("/api/fencinglab/tracked-players")
async def fencinglab_tracked_players(
    lang: str = Query("ko", description="언어 코드 (ko/en)")
):
    """모든 추적 대상 선수 목록 (최병철펜싱클럽 + 산하 관리 선수)"""
    analyzer = get_fencinglab_analyzer()
    all_players = analyzer.get_all_tracked_players()

    # 각 선수에 대해 기본 통계 추가
    result = {}
    for club_name, players in all_players.items():
        # 클럽명 번역
        display_club = await get_localized_org_name(_supabase_client, club_name, lang) if _supabase_client else club_name

        club_data = []
        for p in players:
            analytics = analyzer.analyze_player(p["name"], p["team"])

            # 선수명, 팀명 번역
            display_name = await get_localized_player_name(_supabase_client, p["name"], lang) if _supabase_client else p["name"]
            display_team = await get_localized_org_name(_supabase_client, p["team"], lang) if _supabase_client else p["team"]

            if analytics:
                club_data.append({
                    "name": p["name"],  # 원본 (링크용)
                    "display_name": display_name,  # 표시용
                    "team": p["team"],  # 원본 (링크용)
                    "display_team": display_team,  # 표시용
                    "total_matches": analytics.total_matches,
                    "win_rate": analytics.win_rate,
                    "recent_6_win_rate": analytics.recent_6_win_rate,
                    "recent_6_trend": analytics.recent_6_trend
                })
            else:
                no_data_text = "No data" if lang == "en" else "데이터 없음"
                club_data.append({
                    "name": p["name"],
                    "display_name": display_name,
                    "team": p["team"],
                    "display_team": display_team,
                    "total_matches": 0,
                    "win_rate": 0,
                    "recent_6_win_rate": 0,
                    "recent_6_trend": no_data_text
                })
        result[display_club] = club_data

    return {
        "tracked_clubs": result,
        "total_players": sum(len(v) for v in result.values())
    }


@app.get("/api/fencinglab/player/{player_name}")
async def fencinglab_player_analytics(
    player_name: str,
    team: str = Query(..., description="팀 이름 (필수 - 동명이인 구분)"),
    lang: str = Query("ko", description="언어 코드 (ko/en)")
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
            detail="현재 최병철펜싱클럽 소속 선수만 분석 서비스를 이용할 수 없습니다."
        )

    analytics = analyzer.analyze_player(player_name, team, lang)
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
async def fencinglab_redirect(request: Request):
    """FencingLab 페이지 - 기본 언어로 리다이렉트 (쿠키 우선, Accept-Language 무시)"""
    from fastapi.responses import RedirectResponse
    lang_cookie = request.cookies.get('lang')
    lang = lang_cookie if lang_cookie in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    return RedirectResponse(url=f"/{lang}/fencinglab", status_code=302)


@app.get("/{lang}/fencinglab", response_class=HTMLResponse)
async def fencinglab_page(request: Request, lang: str = "ko"):
    """FencingLab 메인 페이지 (다국어 지원)"""
    if lang not in SUPPORTED_LANGUAGES:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=f"/{DEFAULT_LANGUAGE}/fencinglab", status_code=302)

    context = {
        "request": request,
        "title": "FencingLab - Player Analysis",
        **get_i18n_template_context(request, lang)
    }
    return templates.TemplateResponse("fencinglab.html", context)


@app.get("/fencinglab/player/{player_name}", response_class=HTMLResponse)
async def fencinglab_player_page(request: Request, player_name: str):
    """FencingLab 선수 분석 페이지"""
    return templates.TemplateResponse("fencinglab_player.html", {
        "request": request,
        "title": f"{player_name} - FencingLab",
        "player_name": player_name
    })


# ==================== Club Management SaaS HTML 페이지 ====================

@app.get("/club", response_class=HTMLResponse)
@app.get("/club/", response_class=HTMLResponse)
async def club_dashboard_page(request: Request, test: Optional[str] = None, role: Optional[str] = None):
    """클럽 대시보드 페이지 - 역할별 뷰 제공

    역할별 대시보드:
    - student, parent: 내 출결, 레슨, 공지사항 (모바일 최적화)
    - coach, head_coach: 전체 회원/출결/레슨 관리
    - owner: 코치 기능 + 회계관리 + 감독 메세지
    """
    # 테스트 모드에서는 role 파라미터로 역할 지정 가능
    # 실제 운영시에는 JWT 토큰에서 역할 확인
    template_map = {
        "student": "club/dashboard_student.html",
        "parent": "club/dashboard_student.html",
        "coach": "club/dashboard_coach.html",
        "head_coach": "club/dashboard_coach.html",
        "owner": "club/dashboard_coach.html",  # owner는 coach와 동일 + 회계관리 버튼
        "staff": "club/dashboard_coach.html",
    }

    # 테스트 모드: role 파라미터 또는 기본값 (owner)
    if test:
        selected_role = role if role in template_map else "owner"
    else:
        # 실제 운영: JWT에서 역할 확인 (미구현시 기본 coach)
        selected_role = "coach"

    template_name = template_map.get(selected_role, "club/dashboard_coach.html")

    return templates.TemplateResponse(template_name, {
        "request": request,
        "title": "클럽 대시보드 - Korean Fencing Tracker",
        "user_role": selected_role
    })


@app.get("/club/checkin", response_class=HTMLResponse)
async def club_checkin_page(request: Request):
    """출석 체크인 페이지 (학생용 모바일 최적화)"""
    return templates.TemplateResponse("club/checkin.html", {
        "request": request,
        "title": "출석 체크인 - Korean Fencing Tracker"
    })


@app.get("/club/accounting", response_class=HTMLResponse)
async def club_accounting_page(request: Request):
    """회계관리 페이지 (owner/사장 전용)"""
    return templates.TemplateResponse("club/accounting.html", {
        "request": request,
        "title": "회계관리 - Korean Fencing Tracker"
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
