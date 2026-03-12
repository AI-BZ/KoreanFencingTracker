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
from app.translation_service import get_translation_service, TranslationService

# 전역 번역 서비스 인스턴스
_translation_service: TranslationService = None

def get_ts() -> TranslationService:
    """Get or create translation service singleton."""
    global _translation_service
    if _translation_service is None:
        _translation_service = get_translation_service()
    return _translation_service


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

    # Dual DE 형식인 경우 to_dict() 반환
    if hasattr(normalized, 'format') and normalized.format == 'dual_de':
        # NormalizedDualDEBracket 객체 - to_dict()로 변환
        return normalized.to_dict()

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


def _reconstruct_bouts_from_duplicated_bbr(
    raw_bouts: list, bracket_size: int
) -> List[Dict]:
    """중복된 bouts_by_round에서 올바른 라운드명으로 bout 재배정.

    스크래퍼 버그로 전체 브래킷 경기가 모든 라운드 키에 복사된 경우,
    match_number 범위를 이용해 각 bout의 실제 라운드를 결정합니다.

    bracket_size=32일 때:
      match #1~#16: 32강 (16경기)
      match #17~#24: 16강 (8경기)
      match #25~#28: 8강 (4경기)
      match #29~#30: 준결승 (2경기)
      match #31: 결승 (1경기)
    """
    if not raw_bouts or bracket_size < 4:
        return []

    # 라운드별 match_number 범위 계산
    round_ranges = []  # [(start, end, round_name)]
    size = bracket_size
    start = 1
    while size >= 2:
        n_matches = size // 2
        round_name = f"{size}강" if size > 4 else ("준결승" if size == 4 else "결승")
        round_ranges.append((start, start + n_matches - 1, round_name))
        start += n_matches
        size //= 2

    def get_round_for_match(match_num: int) -> str:
        for rng_start, rng_end, rnd in round_ranges:
            if rng_start <= match_num <= rng_end:
                return rnd
        return "unknown"

    result = []
    for bout in raw_bouts:
        if not isinstance(bout, dict):
            continue
        nb = _normalize_bout_data(bout)
        mn = nb.get("match_number")
        if mn is not None:
            correct_round = get_round_for_match(int(mn))
            nb["round_name"] = correct_round
            nb["round"] = correct_round
        # self-bout 필터
        p1 = (nb.get("player1_name") or "").strip()
        p2 = (nb.get("player2_name") or "").strip()
        if p1 and p2 and p1 == p2:
            continue
        result.append(nb)
    return result


# 라운드 순서 (낮은 라운드 → 높은 라운드)
_ROUND_PROGRESSION = ["256강", "128강", "64강", "32강", "16강", "8강", "준결승", "결승"]
_ROUND_RANK = {r: i for i, r in enumerate(_ROUND_PROGRESSION)}


def _dedup_keep_highest_round(bouts: List[Dict]) -> List[Dict]:
    """동일 선수쌍 중복 제거: 가장 높은 라운드(진행이 늦은 라운드)의 bout만 유지.

    스크래퍼 버그로 같은 경기가 여러 라운드에 저장된 경우,
    예: 32강과 16강에 동일한 경기 → 16강(higher)만 유지.
    """
    best_bout: Dict[tuple, tuple] = {}

    for i, bout in enumerate(bouts):
        p1 = (bout.get("player1_name") or "").strip()
        p2 = (bout.get("player2_name") or "").strip()
        if not p1 or not p2:
            best_bout[("_nopair", i)] = (0, i, bout)
            continue

        pair_key = tuple(sorted([p1, p2]))
        rnd = (bout.get("round_name") or bout.get("round") or "").strip()
        rank = _ROUND_RANK.get(rnd, -1)

        if pair_key not in best_bout or rank > best_bout[pair_key][0]:
            best_bout[pair_key] = (rank, i, bout)

    return [bout for _, idx, bout in sorted(best_bout.values(), key=lambda x: x[1])]


def _get_full_bouts_from_de_bracket(de_bracket: Dict) -> List[Dict]:
    """
    DE bracket에서 full_bouts를 추출합니다.

    일부 이벤트는 full_bouts 필드 없이 bouts_by_round만 가지고 있습니다.
    이 함수는 full_bouts가 없거나 비어있으면 bouts_by_round에서 추출합니다.

    Args:
        de_bracket: DE bracket 데이터 딕셔너리

    Returns:
        bout 딕셔너리 리스트 (full_bouts 또는 bouts_by_round에서 추출)
    """
    if not de_bracket or not isinstance(de_bracket, dict):
        return []

    # dual_de 형식 처리: first_de와 second_de에서 재귀 추출 + de_phase 태깅
    if de_bracket.get("format") == "dual_de":
        all_bouts = []
        phase_map = {"first_de": "qualifying", "second_de": "main"}
        for sub_key in ("first_de", "second_de"):
            sub_bracket = de_bracket.get(sub_key, {})
            if isinstance(sub_bracket, dict):
                sub_bouts = _get_full_bouts_from_de_bracket(sub_bracket)
                phase = phase_map[sub_key]
                for bout in sub_bouts:
                    bout["de_phase"] = phase
                all_bouts.extend(sub_bouts)
        return all_bouts

    full_bouts = de_bracket.get("full_bouts", [])

    # full_bouts가 있고 비어있지 않으면 정규화 후 반환
    if full_bouts and isinstance(full_bouts, list) and len(full_bouts) > 0:
        # 각 bout 데이터 정규화 (중첩 형식 → flat 형식) + self-bout 필터
        normalized = []
        for bout in full_bouts:
            if not isinstance(bout, dict):
                continue
            nb = _normalize_bout_data(bout)
            p1 = (nb.get("player1_name") or "").strip()
            p2 = (nb.get("player2_name") or "").strip()
            if p1 and p2 and p1 == p2:
                continue  # self-bout 제외
            normalized.append(nb)
        # 중복 제거: 같은 선수쌍이 여러 라운드에 있으면 가장 높은 라운드만 유지
        return _dedup_keep_highest_round(normalized)

    # full_bouts가 없거나 비어있으면 bouts_by_round에서 추출
    bouts_by_round = de_bracket.get("bouts_by_round", {})
    if isinstance(bouts_by_round, dict):
        # 스크래퍼 버그 감지: 모든 라운드 키에 전체 브래킷 경기가 복사된 경우
        # (예: 8강=32, 16강=32, 32강=32 → 정상이면 8강=4, 16강=8, 32강=16)
        round_bout_counts = {k: len(v) for k, v in bouts_by_round.items() if isinstance(v, list)}
        counts = list(round_bout_counts.values())
        is_duplicated = False
        if len(counts) >= 2:
            max_count = max(counts)
            same_count = sum(1 for c in counts if c == max_count)
            # 절반 이상의 라운드가 같은 bout 수이고, 그 수가 4 초과면 중복 패턴
            if same_count >= len(counts) * 0.5 and max_count > 4:
                is_duplicated = True
                logger.warning(
                    f"⚠️ bouts_by_round 중복 감지: {round_bout_counts} → "
                    f"가장 많은 라운드 데이터만 사용"
                )

        if is_duplicated:
            # 가장 많은 bout을 가진 라운드 키 사용 (가장 완전한 데이터)
            best_key = max(round_bout_counts, key=round_bout_counts.get)
            raw_bouts = bouts_by_round[best_key]
            bracket_size = de_bracket.get("bracket_size", 0)
            full_bouts = _reconstruct_bouts_from_duplicated_bbr(
                raw_bouts, bracket_size
            )
        else:
            full_bouts = []
            for round_name, round_bouts in bouts_by_round.items():
                if isinstance(round_bouts, list):
                    for bout in round_bouts:
                        if isinstance(bout, dict):
                            # 정규화된 bout 생성
                            normalized_bout = _normalize_bout_data(bout)
                            # round_name 추가 (없으면)
                            if "round" not in normalized_bout and "round_name" not in normalized_bout:
                                normalized_bout["round"] = round_name
                                normalized_bout["round_name"] = round_name
                            # self-bout 필터 (p1==p2 스크래퍼 버그)
                            p1 = (normalized_bout.get("player1_name") or "").strip()
                            p2 = (normalized_bout.get("player2_name") or "").strip()
                            if p1 and p2 and p1 == p2:
                                continue
                            full_bouts.append(normalized_bout)
        return full_bouts

    return []


def _normalize_bout_data(bout: Dict) -> Dict:
    """
    bout 데이터를 정규화합니다.

    중첩 형식(player1.name)을 flat 형식(player1_name)으로 변환합니다.
    이를 통해 서버 코드 전체에서 일관된 데이터 형식을 사용할 수 있습니다.

    Args:
        bout: 원본 bout 딕셔너리

    Returns:
        정규화된 bout 딕셔너리
    """
    if not bout or not isinstance(bout, dict):
        return bout

    normalized = dict(bout)  # 원본 복사

    # player1 중첩 형식 → flat 형식
    player1 = bout.get("player1", {})
    if isinstance(player1, dict):
        if "player1_name" not in normalized or not normalized["player1_name"]:
            normalized["player1_name"] = player1.get("name", "")
        if "player1_team" not in normalized or not normalized["player1_team"]:
            normalized["player1_team"] = player1.get("team", "")
        if "player1_score" not in normalized:
            score = player1.get("score")
            if score is not None:
                normalized["player1_score"] = score

    # player2 중첩 형식 → flat 형식
    player2 = bout.get("player2", {})
    if isinstance(player2, dict):
        if "player2_name" not in normalized or not normalized["player2_name"]:
            normalized["player2_name"] = player2.get("name", "")
        if "player2_team" not in normalized or not normalized["player2_team"]:
            normalized["player2_team"] = player2.get("team", "")
        if "player2_score" not in normalized:
            score = player2.get("score")
            if score is not None:
                normalized["player2_score"] = score

    # winner 중첩 형식 → flat 형식
    winner = bout.get("winner", {})
    if isinstance(winner, dict):
        if "winner_name" not in normalized or not normalized["winner_name"]:
            normalized["winner_name"] = winner.get("name", "")
        if "winner_team" not in normalized or not normalized["winner_team"]:
            normalized["winner_team"] = winner.get("team", "")

    # loser 중첩 형식 → flat 형식
    loser = bout.get("loser", {})
    if isinstance(loser, dict):
        if "loser_name" not in normalized or not normalized["loser_name"]:
            normalized["loser_name"] = loser.get("name", "")
        if "loser_team" not in normalized or not normalized["loser_team"]:
            normalized["loser_team"] = loser.get("team", "")

    # round/round_name 정규화
    if "round" in normalized and "round_name" not in normalized:
        normalized["round_name"] = normalized["round"]
    elif "round_name" in normalized and "round" not in normalized:
        normalized["round"] = normalized["round_name"]

    # winner_name이 null인 경우 점수 기반으로 winner 결정
    # 결승 등에서 wingbn 속성이 설정되지 않은 경우를 처리
    if not normalized.get("winner_name"):
        p1_score = normalized.get("player1_score")
        p2_score = normalized.get("player2_score")
        p1_name = normalized.get("player1_name", "")
        p2_name = normalized.get("player2_name", "")

        # 점수가 모두 있고 유효한 경우에만 처리
        if p1_score is not None and p2_score is not None and p1_name and p2_name:
            try:
                p1_score_int = int(p1_score) if not isinstance(p1_score, int) else p1_score
                p2_score_int = int(p2_score) if not isinstance(p2_score, int) else p2_score

                if p1_score_int > p2_score_int:
                    normalized["winner_name"] = p1_name
                    normalized["loser_name"] = p2_name
                elif p2_score_int > p1_score_int:
                    normalized["winner_name"] = p2_name
                    normalized["loser_name"] = p1_name
            except (ValueError, TypeError):
                pass  # 점수 변환 실패 시 무시

    return normalized


# Auth 모듈
from app.auth.router import router as auth_router, get_current_member
from app.access_control import (
    get_access_level,
    filter_rankings_for_guest,
    blur_search_result_for_guest,
    can_access_fencinglab,
    apply_player_data_gate,
    RANKINGS_HIDDEN_TOP_N,
)

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

# 스케줄러 (자동 스크래핑)
try:
    from scheduler.scheduler import get_scheduler
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    logger.warning("scheduler 패키지를 찾을 수 없음. 자동 스크래핑 비활성화.")

# 스케줄러 활성화 여부 (환경변수로 제어)
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "false").lower() == "true"


# Lifespan context manager (FastAPI 0.109+)
@asynccontextmanager
async def lifespan(app: FastAPI):
    """서버 시작/종료 시 실행되는 lifespan 이벤트

    Startup:
        - Supabase 데이터 로드
        - 선수 인덱스 구축
        - 랭킹 계산기 초기화
        - 스케줄러 시작 (ENABLE_SCHEDULER=true 시)

    Shutdown:
        - 스케줄러 종료
        - 정리 작업
    """
    # Startup
    load_data()
    logger.info("✅ 서버 시작 완료 - Supabase 데이터 소스 사용 중")

    # 스케줄러 시작
    scheduler = None
    if SCHEDULER_AVAILABLE and ENABLE_SCHEDULER:
        try:
            scheduler = get_scheduler()
            scheduler.start()
            logger.info("📅 자동 스크래핑 스케줄러 시작됨")
        except Exception as e:
            logger.error(f"스케줄러 시작 실패: {e}")
    elif not ENABLE_SCHEDULER:
        logger.info("📅 스케줄러 비활성화 (ENABLE_SCHEDULER=true로 활성화)")

    yield

    # Shutdown
    if scheduler:
        try:
            scheduler.stop()
            logger.info("📅 스케줄러 종료됨")
        except Exception as e:
            logger.error(f"스케줄러 종료 오류: {e}")

    logger.info("서버 종료됨")

# FastAPI 앱
app = FastAPI(
    title="Korean Fencing Tracker",
    description="KFF 대회 결과 기반 선수 기록 분석 플랫폼",
    version="2.0.0",
    lifespan=lifespan
)

# 정적 파일 및 템플릿
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# i18n 미들웨어 추가
app.add_middleware(LanguageMiddleware)

# Auth 라우터 등록
app.include_router(auth_router)

# Club Management 라우터 등록 (SaaS)
app.include_router(club_router, prefix="/api")

# 데이터 저장소 (메모리 캐시)
_data_cache: Dict[str, Any] = {}
_player_index: Dict[str, List[Dict]] = {}  # 선수별 전적 인덱스
_competition_player_cache: Dict[str, List[Dict]] = {}  # 대회별 선수 인덱스 (자동완성용)
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
    hidden_top: int = 0  # guest에게 숨겨진 상위 N명 (0이면 전체 공개)


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
        FIE 연령대 코드 또는 국제 연령대 코드
        - FIE: Y8, Y10, Y12, Y14, Cadet, Junior, Veteran
        - 국제: U9, U11, U13, U17, U20
    """
    # 1. 데이터베이스의 age_group 필드 우선
    db_age_group = event.get("age_group", "")

    if db_age_group:
        # 이미 FIE 코드이면 그대로 반환
        if db_age_group in ("Y8", "Y10", "Y12", "Y14", "Cadet", "Junior", "Veteran"):
            return db_age_group
        # 국제 연령 코드도 그대로 유지 (익산 대회 등)
        if db_age_group in ("U9", "U11", "U13", "U17", "U20"):
            return db_age_group
        # 레거시 코드면 FIE 코드로 변환
        fie_code = convert_to_fie_code(db_age_group)
        if fie_code != db_age_group:  # 변환 성공
            return fie_code

    # 2. 이벤트명에서 추출
    extracted = extract_age_group(event.get("name", ""))

    # 추출된 코드도 FIE로 변환
    if extracted:
        if extracted in ("Y8", "Y10", "Y12", "Y14", "Cadet", "Junior", "Veteran", "U9", "U11", "U13", "U17", "U20"):
            return extracted
        return convert_to_fie_code(extracted)

    return ""


def matches_age_group_filter(event_age: str, filter_age: str) -> bool:
    """
    이벤트 연령대가 필터 조건과 매칭되는지 확인

    국제 연령 카테고리 매핑:
    - U9 (9세이하) → Y8 (초등1-2)
    - U11 (11세이하) → Y10 (초등3-4)
    - U13 (13세이하) → Y12 (초등5-6)
    - U17 (17세이하) → Y14, Cadet (중학생/고등학생)
    - U20 (20세이하) → Junior (고등학생/대학생)

    Args:
        event_age: 이벤트의 연령대 코드 (FIE 코드 또는 국제 코드)
        filter_age: 사용자가 선택한 필터 연령대 (FIE 코드)

    Returns:
        True if matches, False otherwise
    """
    # 정확히 일치하면 매칭
    if event_age == filter_age:
        return True

    # 국제 연령 카테고리 → 한국 연령 카테고리 매핑
    international_to_korean = {
        'U9': ['Y8'],           # 9세이하 → 초등1-2
        'U11': ['Y10'],         # 11세이하 → 초등3-4
        'U13': ['Y12'],         # 13세이하 → 초등5-6
        'U17': ['Y14', 'Cadet'], # 17세이하 → 중학생/고등학생
        'U20': ['Junior'],      # 20세이하 → 고등학생/대학생
    }

    # 이벤트가 국제 카테고리일 때, 해당하는 한국 필터와 매칭
    if event_age in international_to_korean:
        if filter_age in international_to_korean[event_age]:
            return True

    # 역방향: 한국 필터로 검색 시 국제 카테고리 이벤트도 포함
    korean_to_international = {
        'Y8': ['U9'],
        'Y10': ['U11'],
        'Y12': ['U13'],
        'Y14': ['U17'],
        'Cadet': ['U17'],
        'Junior': ['U20'],
    }

    if filter_age in korean_to_international:
        if event_age in korean_to_international[filter_age]:
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

            # 참가자 수 계산: Pool 참가자 합계 (가장 정확) > pool_total_ranking > final_rankings
            # ⚠️ pool_total_ranking은 DE 진출자만 포함하므로 정확한 총 참가자수가 아님
            pool_rounds = event.get("pool_rounds", [])
            pool_total_ranking = event.get("pool_total_ranking", [])
            de_bracket = event.get("de_bracket", {})
            final_rankings = event.get("final_rankings", [])

            # Pool 참가자 수 계산 (각 Pool의 선수 합계)
            pool_participants = set()
            for pool in pool_rounds:
                for result in pool.get("results", []):
                    name = result.get("name", "").strip()
                    if name:
                        pool_participants.add(name)
            pool_participant_count = len(pool_participants)

            total_participants = (
                event.get("total_participants") or  # 명시적 저장값
                pool_participant_count or  # Pool 참가자 합계 (가장 정확)
                len(pool_total_ranking) or  # DE 진출자 (부정확하지만 fallback)
                len(final_rankings)  # 최종 순위 (최소 fallback)
            )

            # Pool 통계 맵 구축 (player_name -> {wins, losses})
            # 대소문자 무시 매칭을 위해 소문자 키도 유지
            pool_stats = {}  # 원본 이름 -> {wins, losses}
            pool_stats_lower = {}  # 소문자 이름 -> {wins, losses}
            pool_rounds = event.get("pool_rounds", [])
            for pool in pool_rounds:
                for result in pool.get("results", []):
                    pname = result.get("name", "").strip()
                    if pname:
                        wins = result.get("wins", 0) or 0
                        losses = result.get("losses", 0) or 0
                        pname_lower = pname.lower()
                        if pname in pool_stats:
                            pool_stats[pname]["wins"] += wins
                            pool_stats[pname]["losses"] += losses
                        else:
                            pool_stats[pname] = {"wins": wins, "losses": losses}
                        if pname_lower in pool_stats_lower:
                            pool_stats_lower[pname_lower]["wins"] += wins
                            pool_stats_lower[pname_lower]["losses"] += losses
                        else:
                            pool_stats_lower[pname_lower] = {"wins": wins, "losses": losses}

            # DE 통계 맵 구축 (player_name -> {wins, losses})
            # 이름 정규화를 위해 소문자 키와 원본 이름 모두 저장
            de_stats = {}  # 원본 이름 -> {wins, losses}
            de_stats_lower = {}  # 소문자 이름 -> {wins, losses}
            if isinstance(de_bracket, dict):
                full_bouts = _get_full_bouts_from_de_bracket(de_bracket)
                for bout in full_bouts:
                    if bout.get("is_bye"):
                        continue

                    # 데이터 구조: winner_name, player1_name, player2_name 사용
                    # loser_name 필드가 없으므로 직접 계산해야 함
                    winner = bout.get("winner_name", "")
                    player1 = bout.get("player1_name", "")
                    player2 = bout.get("player2_name", "")

                    # winner/loser 중첩 객체 구조도 지원 (일부 데이터용)
                    if not winner:
                        winner_obj = bout.get("winner", {}) or {}
                        winner = winner_obj.get("name", "")

                    if not winner or not player1 or not player2:
                        continue

                    # 패자 계산: winner가 아닌 쪽이 loser
                    winner = winner.strip()
                    player1 = player1.strip()
                    player2 = player2.strip()

                    if winner == player1:
                        loser = player2
                    elif winner == player2:
                        loser = player1
                    else:
                        # winner_name이 player1/player2와 다른 경우 스킵
                        continue

                    # 승자 통계 추가
                    winner_lower = winner.lower()
                    de_stats[winner] = de_stats.get(winner, {"wins": 0, "losses": 0})
                    de_stats[winner]["wins"] += 1
                    de_stats_lower[winner_lower] = de_stats_lower.get(winner_lower, {"wins": 0, "losses": 0})
                    de_stats_lower[winner_lower]["wins"] += 1

                    # 패자 통계 추가
                    if loser:
                        loser_lower = loser.lower()
                        de_stats[loser] = de_stats.get(loser, {"wins": 0, "losses": 0})
                        de_stats[loser]["losses"] += 1
                        de_stats_lower[loser_lower] = de_stats_lower.get(loser_lower, {"wins": 0, "losses": 0})
                        de_stats_lower[loser_lower]["losses"] += 1

            # 엘리미나시옹디렉트 (final_rankings)에서 선수 추출
            for final in event.get("final_rankings", []):
                player_name = final.get("name", "").strip()
                if not player_name:
                    continue

                # 중복 체크 (같은 대회, 같은 종목) - 있으면 업데이트, 없으면 새로 추가
                existing_records = [r for r in _player_index[player_name]
                           if r["competition_name"] == comp_name
                           and r["event_name"] == event_name]

                # Pool/DE 통계 가져오기 (대소문자 무시 매칭)
                player_name_lower = player_name.lower()
                # 먼저 원본 이름으로 찾고, 없으면 소문자로 찾기
                player_pool = pool_stats.get(player_name) or pool_stats_lower.get(player_name_lower, {"wins": 0, "losses": 0})
                player_de = de_stats.get(player_name) or de_stats_lower.get(player_name_lower, {"wins": 0, "losses": 0})

                if existing_records:
                    # 이미 존재하면 DE 통계 업데이트
                    for existing in existing_records:
                        existing["de_wins"] = player_de["wins"]
                        existing["de_losses"] = player_de["losses"]
                    continue

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


def build_competition_player_cache():
    """대회별 선수 인덱스 구축 (자동완성 검색용)

    각 대회의 모든 선수를 미리 인덱싱하여 자동완성 검색 속도를 향상시킴
    """
    global _competition_player_cache
    _competition_player_cache = {}

    for comp in _data_cache.get("competitions", []):
        comp_info = comp.get("competition", {})
        event_cd = comp_info.get("event_cd", "")
        if not event_cd:
            continue

        players_seen = set()
        players_list = []

        for event in comp.get("events", []):
            sub_event_cd = event.get("sub_event_cd", "")
            event_name = event.get("name", "")

            # Pool에서 선수 추출
            for pool in event.get("pool_rounds", []):
                for result in pool.get("results", []):
                    name = result.get("name", "")
                    team = result.get("team", "")
                    if name:
                        key = f"{name}|{team}|{sub_event_cd}"
                        if key not in players_seen:
                            players_seen.add(key)
                            players_list.append({
                                "name": name,
                                "name_lower": name.lower(),
                                "team": team,
                                "sub_event_cd": sub_event_cd,
                                "event_name": event_name
                            })

            # Final rankings에서도 추출
            for ranking in event.get("final_rankings", []):
                name = ranking.get("name", "")
                team = ranking.get("team", "")
                if name:
                    key = f"{name}|{team}|{sub_event_cd}"
                    if key not in players_seen:
                        players_seen.add(key)
                        players_list.append({
                            "name": name,
                            "name_lower": name.lower(),
                            "team": team,
                            "sub_event_cd": sub_event_cd,
                            "event_name": event_name
                        })

        # 이름순 정렬
        players_list.sort(key=lambda x: x["name"])
        _competition_player_cache[event_cd] = players_list

    logger.info(f"대회별 선수 캐시 구축 완료: {len(_competition_player_cache)}개 대회")


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
            except (ValueError, TypeError, IndexError):
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

                # 참가자 수 계산: Pool 참가자 합계 (가장 정확) > pool_total_ranking > final_rankings
                # ⚠️ pool_total_ranking은 DE 진출자만 포함하므로 정확한 총 참가자수가 아님
                pool_total_ranking = raw.get("pool_total_ranking", [])
                final_rankings = raw.get("final_rankings", [])

                # Pool 참가자 수 계산 (각 Pool의 선수 합계)
                pool_participants_set = set()
                for pool in filtered_pools:
                    for result in pool.get("results", []):
                        name = result.get("name", "").strip()
                        if name:
                            pool_participants_set.add(name)
                pool_participant_count = len(pool_participants_set)

                total_participants = (
                    raw.get("total_participants") or  # 명시적으로 저장된 값
                    pool_participant_count or  # Pool 참가자 합계 (가장 정확)
                    len(pool_total_ranking) or  # DE 진출자 (부정확하지만 fallback)
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
                    "de_format": e.get("de_format"),
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
    build_competition_player_cache()  # 대회별 선수 캐시 (자동완성 최적화)
    build_identity_resolver()

    # 랭킹 계산기 초기화 (Supabase 캐시 데이터 사용)
    try:
        _ranking_calculator = RankingCalculator()
        _ranking_calculator.load_from_data(_data_cache)
        logger.info(f"✅ 랭킹 계산기 초기화 완료: {len(_ranking_calculator.results)}개 결과")
    except Exception as e:
        logger.error(f"랭킹 계산기 초기화 실패: {e}")
        _ranking_calculator = None

    # 데이터 무결성 검증 (백그라운드 스레드에서 실행 — 서버 시작을 블로킹하지 않음)
    import threading

    def _run_startup_validation():
        try:
            from app.data_validator import DataValidator
            logger.info("[DataValidator] 백그라운드 검증 시작...")
            validator = DataValidator(get_competitions())
            issues = validator.validate_all()
            errors = [i for i in issues if i.severity == "ERROR"]
            warnings = [i for i in issues if i.severity == "WARNING"]

            if errors:
                from collections import Counter
                rule_counts = Counter(e.rule_id for e in errors)
                logger.error(f"[DataValidator] 데이터 오류 {len(errors)}건 발견!")
                for rule_id, cnt in rule_counts.most_common():
                    logger.error(f"  {rule_id}: {cnt}건")
            if warnings:
                logger.warning(f"[DataValidator] 데이터 경고 {len(warnings)}건")
            if not errors and not warnings:
                logger.info("✅ [DataValidator] 데이터 무결성 검증 통과")
        except Exception as e:
            logger.warning(f"[DataValidator] 검증 실행 실패: {e}")

    threading.Thread(target=_run_startup_validation, daemon=True).start()


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
    request: Request,
    weapon: Optional[str] = None,
    gender: Optional[str] = None,
    age_group: Optional[str] = None,
    year: Optional[int] = None,
    event_type: Optional[str] = None,
    search: Optional[str] = None,
    lang: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200)
):
    """필터 기반 종목 검색 API (다국어 지원)"""
    events = []

    # 언어 결정: 파라미터 > request.state > 기본값
    if lang is None:
        lang = getattr(request.state, 'lang', DEFAULT_LANGUAGE)
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE

    # 번역 서비스
    ts = get_ts()

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

            # 종목 타입 필터 (None이면 기본값 "개인")
            if event_type and (event.get("event_type") or "개인") != event_type:
                continue

            # 연령대 필터 (National이 아닌 경우에만 적용)
            # 데이터베이스 age_group 필드 우선, FIE 코드로 변환
            # U17 (17세이하)는 Y14와 Cadet 양쪽 필터에서 표시됨
            event_age = get_event_age_group_fie(event)
            if age_group and not is_national_filter and not matches_age_group_filter(event_age, age_group):
                continue

            # 검색어 필터 (원본 한국어와 번역된 영어 모두 검색)
            if search:
                search_lower = search.lower()
                event_name_ko = event.get("name", "")
                event_name_en = ts.translate_event_name(event_name_ko) if lang != 'ko' else ""
                comp_name_en = ts.get_localized_competition_name(comp_info, 'en') if lang != 'ko' else ""

                if (search_lower not in event_name_ko.lower() and
                    search_lower not in comp_name.lower() and
                    search_lower not in event_name_en.lower() and
                    search_lower not in comp_name_en.lower()):
                    continue

            # 번역된 이름 사용
            display_event_name = ts.get_localized_event_name(event, lang)
            display_comp_name = ts.get_localized_competition_name(comp_info, lang)

            events.append(EventSummary(
                event_cd=event.get("event_cd", "") or "",
                sub_event_cd=event.get("sub_event_cd", "") or "",
                name=display_event_name or "",
                weapon=event.get("weapon", "") or "",
                gender=event.get("gender", "") or "",
                age_group=event_age or "",
                event_type=event.get("event_type", "") or "개인",  # 기본값: 개인
                competition_name=display_comp_name or "",
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
        "total_pages": (total + per_page - 1) // per_page,
        "lang": lang  # 현재 언어 반환
    }


@app.get("/api/player/{player_name}")
async def api_player_profile(
    request: Request,
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

    # 접근 등급별 데이터 필터링
    access_level, _ = await get_access_level(request)
    profile_data = {
        "name": player_name,
        "teams": teams,
        "total_records": len(records),
        "records": [PlayerRecord(**r) for r in filtered],
        "stats": stats,
    }
    profile_data = apply_player_data_gate(profile_data, access_level)

    return profile_data


@app.get("/api/players/search")
async def api_player_search(
    request: Request,
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

    # 접근 등급별 필터링: guest는 소속 정보 blur + 결과 수 제한
    access_level, _ = await get_access_level(request)
    total_count = len(matches)
    final_matches = matches[:limit]
    response = {"results": final_matches, "total": total_count, "access_level": access_level}

    if access_level == "guest":
        GUEST_SEARCH_LIMIT = 5
        final_matches = [blur_search_result_for_guest(m) for m in final_matches[:GUEST_SEARCH_LIMIT]]
        response["results"] = final_matches
        if total_count > GUEST_SEARCH_LIMIT:
            response["has_more"] = True
            response["requires_login"] = True

    return response


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


@app.get("/api/events/{sub_event_cd}/players/search")
async def api_event_player_search(
    sub_event_cd: str,
    q: str = Query(None, description="선수 이름 검색어")
):
    """종목 내 선수 검색 - Pool, DE, 최종순위 정보 반환

    Args:
        sub_event_cd: 종목 코드 (예: "1234_001")
        q: 선수 이름 검색어 (선택사항, 없으면 전체 선수 반환)

    Returns:
        - event_name: 종목명
        - total_players: 검색된 선수 수
        - players: 선수 정보 리스트
            - name: 선수명
            - team: 소속팀
            - pool_number: 풀 번호
            - pool_rank: 풀 내 순위
            - pool_wins: 풀 승수
            - pool_losses: 풀 패수
            - de_rounds: 참가한 DE 라운드 목록
            - final_rank: 최종 순위
    """
    competitions = get_competitions()

    # 1. 모든 대회에서 해당 종목 찾기
    target_event = None
    event_name = ""

    for comp in competitions:
        for event in comp.get("events", []):
            if event.get("sub_event_cd") == sub_event_cd:
                target_event = event
                event_name = event.get("name", "")
                break
        if target_event:
            break

    if not target_event:
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다")

    # 선수 정보를 담을 딕셔너리 (이름으로 중복 방지)
    players_dict = {}

    # 개별 Pool 결과 유효성 검증 함수 (per-pool 체크)
    def single_pool_has_valid_results(pool: dict) -> bool:
        """개별 Pool에 실제 경기 결과가 있는지 확인

        해당 Pool 내 선수들 중 누군가의 wins 또는 losses가 0보다 크면
        그 Pool은 실제 경기가 진행된 것으로 판단
        """
        results = pool.get("results", [])
        for result in results:
            wins = result.get("wins", 0) or 0
            losses = result.get("losses", 0) or 0
            if wins > 0 or losses > 0:
                return True
        return False

    # 2. Pool에서 선수 정보 추출 (per-pool 유효성 검증)
    pool_rounds = target_event.get("pool_rounds", [])

    for pool in pool_rounds:
        pool_num = pool.get("pool_number", 0)
        # 해당 Pool에 실제 경기 결과가 있는지 개별 체크
        this_pool_has_results = single_pool_has_valid_results(pool)

        for result in pool.get("results", []):
            player_name = result.get("name", "")
            if player_name and player_name not in players_dict:
                # pool_number(순서)는 항상 표시, pool_rank(순위)는 결과 있을 때만
                players_dict[player_name] = {
                    "name": player_name,
                    "team": result.get("team", ""),
                    "pool_number": pool_num,  # 항상 표시 (어느 풀에 배정됐는지)
                    "pool_rank": result.get("rank") if this_pool_has_results else None,
                    "pool_wins": result.get("wins", 0) if this_pool_has_results else None,
                    "pool_losses": result.get("losses", 0) if this_pool_has_results else None,
                    "de_matches": [],
                    "final_rank": None
                }

    # 3. pool_total_ranking에서도 선수 정보 보충
    # pool_total_ranking이 있으면 pool 결과가 유효한 것으로 간주
    pool_total_ranking = target_event.get("pool_total_ranking", [])
    pool_total_has_results = len(pool_total_ranking) > 0

    for ranking in pool_total_ranking:
        player_name = ranking.get("name", "")
        if player_name and player_name not in players_dict:
            players_dict[player_name] = {
                "name": player_name,
                "team": ranking.get("team", ""),
                "pool_number": None,
                "pool_rank": ranking.get("pool_rank"),
                "pool_wins": ranking.get("wins", 0),
                "pool_losses": ranking.get("losses", 0),
                "de_matches": [],
                "final_rank": None
            }

    # 4. DE 정보 추가 (full_bouts 배열 사용) - 상세 매치 정보 포함
    de_bracket = target_event.get("de_bracket", {})
    if not isinstance(de_bracket, dict):
        de_bracket = {}

    # full_bouts에서 선수 DE 정보 추출 (데이터 구조: winner_name, player1_name, player2_name)
    # _get_full_bouts_from_de_bracket 사용으로 bouts_by_round 폴백 지원
    full_bouts = _get_full_bouts_from_de_bracket(de_bracket)
    if isinstance(full_bouts, list):
        for bout in full_bouts:
            if not isinstance(bout, dict):
                continue

            round_name = bout.get("round_name") or bout.get("round", "")
            winner_name = bout.get("winner_name", "")
            player1 = bout.get("player1_name", "")
            player2 = bout.get("player2_name", "")
            p1_score = bout.get("player1_score")
            p2_score = bout.get("player2_score")
            p1_team = bout.get("player1_team", "")
            p2_team = bout.get("player2_team", "")
            is_bye = bout.get("is_bye", False)

            if is_bye or not winner_name or not player1 or not player2:
                continue

            # 패자 계산
            winner_name = winner_name.strip()
            player1 = player1.strip()
            player2 = player2.strip()

            if winner_name == player1:
                loser_name = player2
                winner_score = p1_score
                loser_score = p2_score
                winner_team = p1_team
                loser_team = p2_team
            elif winner_name == player2:
                loser_name = player1
                winner_score = p2_score
                loser_score = p1_score
                winner_team = p2_team
                loser_team = p1_team
            else:
                continue

            # 승자와 패자 모두 처리
            for player_name, is_winner in [(winner_name, True), (loser_name, False)]:
                if not player_name:
                    continue

                # 상대 선수 결정
                opponent = loser_name if is_winner else winner_name
                my_score = winner_score if is_winner else loser_score
                opp_score = loser_score if is_winner else winner_score
                player_team = winner_team if is_winner else loser_team

                # 결과 판정
                if not opponent:
                    continue

                result = "win" if is_winner else "lose"
                score_str = f"{my_score}-{opp_score}" if my_score is not None and opp_score is not None else None

                match_info = {
                    "round": round_name,
                    "opponent": opponent,
                    "result": result,
                    "score": score_str
                }

                if player_name in players_dict:
                    existing_rounds = [m["round"] for m in players_dict[player_name]["de_matches"]]
                    if round_name and round_name not in existing_rounds:
                        players_dict[player_name]["de_matches"].append(match_info)
                else:
                    # DE에만 있는 선수 (Pool 정보 없음)
                    players_dict[player_name] = {
                        "name": player_name,
                        "team": player_team or "",
                        "pool_number": None,
                        "pool_rank": None,
                        "pool_wins": None,
                        "pool_losses": None,
                        "de_matches": [match_info] if round_name else [],
                        "final_rank": None
                    }

    # 5. 최종 순위 추가
    final_rankings = target_event.get("final_rankings", [])
    for ranking in final_rankings:
        player_name = ranking.get("name", "")
        if player_name:
            if player_name in players_dict:
                players_dict[player_name]["final_rank"] = ranking.get("rank")
            else:
                # 최종 순위에만 있는 선수
                players_dict[player_name] = {
                    "name": player_name,
                    "team": ranking.get("team", ""),
                    "pool_number": None,
                    "pool_rank": None,
                    "pool_wins": None,
                    "pool_losses": None,
                    "de_matches": [],
                    "final_rank": ranking.get("rank")
                }

    # 6. 리스트로 변환
    players_info = list(players_dict.values())

    # 7. 검색 필터 적용
    if q:
        q_lower = q.lower()
        players_info = [p for p in players_info if q_lower in p["name"].lower()]

    # 8. 정렬: 최종순위 > 풀순위 > 이름순
    def sort_key(p):
        final_rank = p.get("final_rank") or 9999
        pool_rank = p.get("pool_rank") or 9999
        return (final_rank, pool_rank, p.get("name", ""))

    players_info.sort(key=sort_key)

    # 결과 유효성 메타데이터 계산
    de_bracket = target_event.get("de_bracket", {})
    final_rankings = target_event.get("final_rankings", [])
    has_de_results = bool(de_bracket.get("rounds")) or any(isinstance(v, list) and len(v) > 0 for k, v in de_bracket.items() if k != "rounds")
    has_final_rankings = len(final_rankings) > 0

    # 전체 이벤트에 pool 결과가 있는지 확인 (메타데이터용)
    any_pool_has_results = any(single_pool_has_valid_results(p) for p in pool_rounds)

    return {
        "event_name": event_name,
        "sub_event_cd": sub_event_cd,
        "total_players": len(players_info),
        "has_pool_results": any_pool_has_results or pool_total_has_results,
        "has_de_results": has_de_results,
        "has_final_rankings": has_final_rankings,
        "players": players_info
    }


@app.get("/api/competitions")
async def api_competitions(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    year: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    lang: Optional[str] = None
):
    """대회 목록 API (다국어 지원)"""
    competitions = get_competitions()

    # 언어 결정
    if lang is None:
        lang = getattr(request.state, 'lang', DEFAULT_LANGUAGE)
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE

    ts = get_ts()

    filtered = []
    for comp in competitions:
        comp_info = comp.get("competition", {})
        comp_name_ko = comp_info.get("name", "")
        comp_date = comp_info.get("start_date", "")
        comp_year = int(comp_date[:4]) if comp_date else 0

        # 연도 필터
        if year and comp_year != year:
            continue

        # 상태 필터
        if status and comp_info.get("status") != status:
            continue

        # 검색어 필터 (한국어 + 영어 모두 검색)
        if search:
            search_lower = search.lower()
            comp_name_en = ts.get_localized_competition_name(comp_info, 'en') if lang != 'ko' else ""
            if (search_lower not in comp_name_ko.lower() and
                search_lower not in comp_name_en.lower()):
                continue

        # 번역된 이름 사용
        display_name = ts.get_localized_competition_name(comp_info, lang)

        filtered.append(CompetitionSummary(
            event_cd=comp_info.get("event_cd", ""),
            name=display_name,
            start_date=comp_info.get("start_date"),
            end_date=comp_info.get("end_date"),
            status=comp_info.get("status", "") or "",
            location=comp_info.get("location", "") or "",  # None 방지
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
        "per_page": per_page,
        "lang": lang
    }


@app.get("/api/competition/{event_cd}")
async def api_competition_detail(event_cd: str):
    """대회 상세 정보 API"""
    comp = get_competition(event_cd)
    if not comp:
        raise HTTPException(status_code=404, detail="대회를 찾을 수 없습니다")
    return comp


@app.get("/api/competition/{event_cd}/players/search")
async def api_competition_player_search(
    event_cd: str,
    q: str = Query(..., min_length=1, description="선수 이름 또는 소속 검색어"),
    search_type: str = Query("both", regex="^(name|team|both)$", description="검색 타입: name(이름만), team(소속만), both(모두)")
):
    """대회 내 전체 종목에서 선수 검색

    Args:
        event_cd: 대회 코드
        q: 선수 이름 또는 소속 검색어
        search_type: 검색 타입 (name: 이름만, team: 소속만, both: 모두)

    Returns:
        - competition_name: 대회명
        - total_results: 검색된 결과 수
        - results: 종목별 선수 정보 리스트
            - event_name: 종목명
            - sub_event_cd: 종목 코드
            - player: 선수 정보
                - name: 선수명
                - team: 소속팀
                - pool_number: 풀 번호
                - pool_rank: 풀 내 순위 (확정된 경우만)
                - de_rounds: 참가한 DE 라운드 목록
                - final_rank: 최종 순위
                - match_type: 일치 타입 (name/team)
    """
    comp = get_competition(event_cd)
    if not comp:
        raise HTTPException(status_code=404, detail="대회를 찾을 수 없습니다")

    comp_info = comp.get("competition", {})
    competition_name = comp_info.get("name", "")
    events = comp.get("events", [])

    q_lower = q.lower()
    results = []

    for event in events:
        event_name = event.get("name", "")
        sub_event_cd = event.get("sub_event_cd", "")

        # 이 종목에서 선수 찾기
        players_found = []

        # 1. Pool에서 선수 정보 추출 (per-pool 유효성 검증)
        pool_rounds = event.get("pool_rounds", [])
        players_dict = {}

        # 개별 Pool 결과 유효성 검증 함수
        def single_pool_has_valid_results(pool: dict) -> bool:
            """해당 Pool에 실제 경기 결과가 있는지 확인"""
            results = pool.get("results", [])
            for result in results:
                wins = result.get("wins", 0) or 0
                losses = result.get("losses", 0) or 0
                if wins > 0 or losses > 0:
                    return True
            return False

        for pool in pool_rounds:
            pool_num = pool.get("pool_number", 0)
            # 해당 Pool에 실제 결과가 있는지 개별 체크
            this_pool_has_results = single_pool_has_valid_results(pool)

            for result in pool.get("results", []):
                player_name = result.get("name", "")
                player_team = result.get("team", "")

                # 검색 타입에 따른 필터링
                name_match = player_name and q_lower in player_name.lower()
                team_match = player_team and q_lower in player_team.lower()

                should_include = False
                match_type = None
                if search_type == "name" and name_match:
                    should_include = True
                    match_type = "name"
                elif search_type == "team" and team_match:
                    should_include = True
                    match_type = "team"
                elif search_type == "both" and (name_match or team_match):
                    should_include = True
                    match_type = "name" if name_match else "team"

                if should_include and player_name not in players_dict:
                    players_dict[player_name] = {
                        "name": player_name,
                        "team": player_team,
                        "pool_number": pool_num,  # 항상 표시 (어느 풀에 배정됐는지)
                        "pool_rank": result.get("rank") if this_pool_has_results else None,
                        "de_matches": [],
                        "final_rank": None,
                        "match_type": match_type
                    }

        # 2. pool_total_ranking에서도 보충 (있으면 pool 결과가 유효한 것)
        pool_total_ranking = event.get("pool_total_ranking", [])
        pool_total_has_results = len(pool_total_ranking) > 0

        for ranking in pool_total_ranking:
            player_name = ranking.get("name", "")
            player_team = ranking.get("team", "")

            # 검색 타입에 따른 필터링
            name_match = player_name and q_lower in player_name.lower()
            team_match = player_team and q_lower in player_team.lower()

            should_include = False
            match_type = None
            if search_type == "name" and name_match:
                should_include = True
                match_type = "name"
            elif search_type == "team" and team_match:
                should_include = True
                match_type = "team"
            elif search_type == "both" and (name_match or team_match):
                should_include = True
                match_type = "name" if name_match else "team"

            if should_include and player_name not in players_dict:
                players_dict[player_name] = {
                    "name": player_name,
                    "team": player_team,
                    "pool_number": None,
                    "pool_rank": ranking.get("pool_rank"),
                    "de_matches": [],
                    "final_rank": None,
                    "match_type": match_type
                }

        # 3. DE 정보 추가 (full_bouts 배열 사용) - 상세 매치 정보 포함
        de_bracket = event.get("de_bracket", {})
        if not isinstance(de_bracket, dict):
            de_bracket = {}

        # full_bouts에서 선수 DE 정보 추출 (데이터 구조: winner_name, player1_name, player2_name)
        # _get_full_bouts_from_de_bracket 사용으로 bouts_by_round 폴백 지원
        full_bouts = _get_full_bouts_from_de_bracket(de_bracket)
        if isinstance(full_bouts, list):
            for bout in full_bouts:
                if not isinstance(bout, dict):
                    continue

                round_name = bout.get("round_name") or bout.get("round", "")
                winner_name = bout.get("winner_name", "")
                player1 = bout.get("player1_name", "")
                player2 = bout.get("player2_name", "")
                p1_score = bout.get("player1_score")
                p2_score = bout.get("player2_score")
                p1_team = bout.get("player1_team", "")
                p2_team = bout.get("player2_team", "")
                is_bye = bout.get("is_bye", False)

                if is_bye or not winner_name or not player1 or not player2:
                    continue

                # 패자 계산
                winner_name = winner_name.strip()
                player1 = player1.strip()
                player2 = player2.strip()

                if winner_name == player1:
                    loser_name = player2
                    winner_score = p1_score
                    loser_score = p2_score
                    winner_team = p1_team
                    loser_team = p2_team
                elif winner_name == player2:
                    loser_name = player1
                    winner_score = p2_score
                    loser_score = p1_score
                    winner_team = p2_team
                    loser_team = p1_team
                else:
                    continue

                # 승자와 패자 모두 검색 대상으로 처리
                for player_name, is_winner in [(winner_name, True), (loser_name, False)]:
                    if not player_name or player_name.lower().find(q_lower) == -1:
                        continue

                    # 상대 선수 결정
                    opponent = loser_name if is_winner else winner_name
                    opponent_team = loser_team if is_winner else winner_team
                    my_score = winner_score if is_winner else loser_score
                    opp_score = loser_score if is_winner else winner_score
                    player_team = winner_team if is_winner else loser_team

                    # 결과 판정
                    if not opponent:
                        continue

                    result = "win" if is_winner else "lose"
                    score_str = f"{my_score}-{opp_score}" if my_score is not None and opp_score is not None else None

                    match_info = {
                        "round": round_name,
                        "opponent": opponent,
                        "result": result,
                        "score": score_str
                    }

                    if player_name in players_dict:
                        # 중복 라운드 체크
                        existing_rounds = [m["round"] for m in players_dict[player_name]["de_matches"]]
                        if round_name and round_name not in existing_rounds:
                            players_dict[player_name]["de_matches"].append(match_info)
                    else:
                        players_dict[player_name] = {
                            "name": player_name,
                            "team": player_team or "",
                            "pool_number": None,
                            "pool_rank": None,
                            "de_matches": [match_info] if round_name else [],
                            "final_rank": None
                        }

        # 4. 최종 순위 추가
        final_rankings = event.get("final_rankings", [])
        for ranking in final_rankings:
            player_name = ranking.get("name", "")
            if player_name and player_name.lower().find(q_lower) != -1:
                if player_name in players_dict:
                    players_dict[player_name]["final_rank"] = ranking.get("rank")
                else:
                    players_dict[player_name] = {
                        "name": player_name,
                        "team": ranking.get("team", ""),
                        "pool_number": None,
                        "pool_rank": None,
                        "de_matches": [],
                        "final_rank": ranking.get("rank")
                    }

        # 결과에 추가
        for player_info in players_dict.values():
            results.append({
                "event_name": event_name,
                "sub_event_cd": sub_event_cd,
                "player": player_info
            })

    # 정렬: 종목명 > 최종순위 > 풀순위 > 이름
    def sort_key(r):
        p = r["player"]
        final_rank = p.get("final_rank") or 9999
        pool_rank = p.get("pool_rank") or 9999
        return (r["event_name"], final_rank, pool_rank, p.get("name", ""))

    results.sort(key=sort_key)

    return {
        "competition_name": competition_name,
        "event_cd": event_cd,
        "query": q,
        "total_results": len(results),
        "results": results
    }


# ==================== Player Autocomplete & Head-to-Head APIs ====================

@app.get("/api/players/autocomplete")
async def api_players_autocomplete(
    request: Request,
    q: str = Query(..., min_length=1, description="검색어 (선수 이름 또는 소속)"),
    limit: int = Query(10, ge=1, le=50, description="결과 수 제한"),
    event_cd: Optional[str] = Query(None, description="대회 코드 (선택 - 대회 내 선수만 검색)"),
    sub_event_cd: Optional[str] = Query(None, description="종목 코드 (선택 - 해당 종목 참가 선수만 검색)")
):
    """선수 자동완성 API - 드롭다운용

    타이핑하면서 실시간으로 선수 목록을 보여주는 자동완성 기능.
    "오" 입력 시 "오주원 최병철펜싱클럽", "오지훈 세종펜싱클럽" 등 표시.
    "최병철" 입력 시 "최병철펜싱클럽" 소속 선수들 표시.

    Args:
        q: 검색어 (선수 이름 또는 소속)
        limit: 최대 결과 수 (기본 10)
        event_cd: 특정 대회 내 선수만 검색 (선택사항)
        sub_event_cd: 특정 종목 내 선수만 검색 (선택사항 - 소속 검색 시 해당 이벤트 참가자만)

    Returns:
        - suggestions: 자동완성 제안 목록
            - name: 선수명
            - team: 현재 소속
            - display: "선수명 소속" 형태 표시용 문자열
            - player_id: 선수 고유 ID (있는 경우)
    """
    q_lower = q.lower().strip()
    suggestions = []

    if event_cd:
        # 특정 대회 내 선수만 검색 (캐시 사용 - 최적화됨)
        cached_players = _competition_player_cache.get(event_cd, [])
        if cached_players:
            # 캐시에서 빠르게 검색 (name_lower 필드 사용)
            players_seen = set()

            for player in cached_players:
                # sub_event_cd가 지정된 경우 해당 종목 선수만 필터링
                if sub_event_cd and player.get("sub_event_cd") != sub_event_cd:
                    continue

                # 이름 또는 소속으로 검색
                name_match = player["name_lower"].startswith(q_lower)
                team_match = q_lower in player.get("team", "").lower()

                if name_match or team_match:
                    key = f"{player['name']}|{player['team']}"
                    if key not in players_seen:
                        players_seen.add(key)
                        suggestions.append({
                            "name": player["name"],
                            "team": player["team"],
                            "display": f"{player['name']} {player['team']}" if player["team"] else player["name"],
                            "player_id": None,
                            "sub_event_cd": player["sub_event_cd"],
                            "event_name": player["event_name"]
                        })
                        if len(suggestions) >= limit:
                            break
    else:
        # 전체 선수 검색 (선수 식별 시스템 사용)
        if _identity_resolver:
            search_results = _identity_resolver.search_players(q, include_history=False)
            for profile in search_results[:limit * 2]:  # 더 많이 가져와서 필터링
                current_team = profile.current_team or (profile.teams[0] if profile.teams else "")

                # 이름 또는 소속으로 검색
                name_match = profile.name.lower().startswith(q_lower)
                team_match = q_lower in current_team.lower()

                if name_match or team_match:
                    suggestions.append({
                        "name": profile.name,
                        "team": current_team,
                        "display": f"{profile.name} {current_team}" if current_team else profile.name,
                        "player_id": profile.player_id
                    })
        else:
            # Fallback: 인덱스 검색
            for name in _player_index.keys():
                records = _player_index[name]
                sorted_records = sorted(records, key=lambda x: x.get("competition_date", ""), reverse=True)
                current_team = sorted_records[0].get("team", "") if sorted_records else ""

                # 이름 또는 소속으로 검색
                name_match = name.lower().startswith(q_lower)
                team_match = q_lower in current_team.lower()

                if name_match or team_match:
                    suggestions.append({
                        "name": name,
                        "team": current_team,
                        "display": f"{name} {current_team}" if current_team else name,
                        "player_id": None
                    })

    # 중복 제거 및 정렬 (이름 순)
    seen = set()
    unique_suggestions = []
    for s in suggestions:
        key = s["display"]
        if key not in seen:
            seen.add(key)
            unique_suggestions.append(s)

    unique_suggestions.sort(key=lambda x: x["name"])

    # Guest: 소속 정보 blur
    access_level, _ = await get_access_level(request)
    final_suggestions = unique_suggestions[:limit]
    if access_level == "guest":
        for s in final_suggestions:
            s["team"] = None
            s["display"] = s["name"]  # 이름만 표시
            s["blurred"] = True

    return {
        "query": q,
        "suggestions": final_suggestions
    }


@app.get("/api/players/{player_name}/head-to-head/{opponent_name}")
async def api_head_to_head(
    player_name: str,
    opponent_name: str,
    weapon: Optional[str] = Query(None, description="무기 필터"),
    age_group: Optional[str] = Query(None, description="연령대 필터")
):
    """두 선수 간 상대 전적 조회

    Args:
        player_name: 선수 이름
        opponent_name: 상대 선수 이름
        weapon: 무기 필터 (선택)
        age_group: 연령대 필터 (선택)

    Returns:
        - player: 선수 정보
        - opponent: 상대 선수 정보
        - record: 상대 전적
            - wins: 승리 횟수
            - losses: 패배 횟수
            - total: 총 경기 수
        - matches: 개별 경기 목록
    """
    competitions = get_competitions()

    matches = []
    wins = 0
    losses = 0

    player_lower = player_name.lower().strip()
    opponent_lower = opponent_name.lower().strip()

    for comp in competitions:
        comp_info = comp.get("competition", {})
        comp_name = comp_info.get("name", "")
        comp_date = comp_info.get("start_date", "")

        for event in comp.get("events", []):
            event_name = event.get("name", "")
            event_weapon = event.get("weapon", "")
            event_age_group = event.get("age_group", "")

            # 필터 적용
            if weapon and weapon != event_weapon:
                continue
            if age_group and age_group != event_age_group:
                continue

            # Pool에서 경기 찾기
            for pool in event.get("pool_rounds", []):
                for bout in pool.get("bouts", []):
                    p1 = bout.get("player1_name", "").lower()
                    p2 = bout.get("player2_name", "").lower()
                    winner = bout.get("winner_name", "").lower()

                    if (p1 == player_lower and p2 == opponent_lower) or \
                       (p1 == opponent_lower and p2 == player_lower):
                        is_win = winner == player_lower
                        if is_win:
                            wins += 1
                        else:
                            losses += 1

                        matches.append({
                            "competition": comp_name,
                            "date": comp_date,
                            "event": event_name,
                            "round": f"Pool {pool.get('pool_number', '')}",
                            "player_score": bout.get("player1_score") if p1 == player_lower else bout.get("player2_score"),
                            "opponent_score": bout.get("player2_score") if p1 == player_lower else bout.get("player1_score"),
                            "result": "win" if is_win else "loss"
                        })

            # DE에서 경기 찾기 (데이터 구조: winner_name, player1_name, player2_name)
            # _get_full_bouts_from_de_bracket 사용으로 bouts_by_round 폴백 지원
            de_bracket = event.get("de_bracket", {})
            full_bouts = _get_full_bouts_from_de_bracket(de_bracket) if isinstance(de_bracket, dict) else []

            for bout in full_bouts:
                if not isinstance(bout, dict):
                    continue

                winner_name_raw = bout.get("winner_name", "")
                player1 = bout.get("player1_name", "")
                player2 = bout.get("player2_name", "")
                p1_score = bout.get("player1_score")
                p2_score = bout.get("player2_score")
                round_name = bout.get("round_name") or bout.get("round", "")
                is_bye = bout.get("is_bye", False)

                if is_bye or not winner_name_raw or not player1 or not player2:
                    continue

                # 패자 계산
                winner_name_raw = winner_name_raw.strip()
                player1 = player1.strip()
                player2 = player2.strip()

                if winner_name_raw == player1:
                    loser_name_raw = player2
                    winner_score = p1_score
                    loser_score = p2_score
                elif winner_name_raw == player2:
                    loser_name_raw = player1
                    winner_score = p2_score
                    loser_score = p1_score
                else:
                    continue

                winner_name = winner_name_raw.lower()
                loser_name = loser_name_raw.lower()

                # 승자 vs 패자로 비교
                if (winner_name == player_lower and loser_name == opponent_lower):
                    # 플레이어가 이김
                    wins += 1
                    matches.append({
                        "competition": comp_name,
                        "date": comp_date,
                        "event": event_name,
                        "round": round_name,
                        "player_score": winner_score,
                        "opponent_score": loser_score,
                        "result": "win"
                    })
                elif (winner_name == opponent_lower and loser_name == player_lower):
                    # 플레이어가 짐
                    losses += 1
                    matches.append({
                        "competition": comp_name,
                        "date": comp_date,
                        "event": event_name,
                        "round": round_name,
                        "player_score": loser_score,
                        "opponent_score": winner_score,
                        "result": "loss"
                    })

    # 날짜 역순 정렬
    matches.sort(key=lambda x: x.get("date", ""), reverse=True)

    return {
        "player": {"name": player_name},
        "opponent": {"name": opponent_name},
        "record": {
            "wins": wins,
            "losses": losses,
            "total": wins + losses
        },
        "matches": matches
    }


@app.get("/api/events/{sub_event_cd}/de-prediction/{player_name}")
async def api_de_prediction(
    sub_event_cd: str,
    player_name: str
):
    """DE 예측 대진표 - 선수가 만날 수 있는 잠재적 상대 목록

    각 라운드에서 만날 수 있는 상대와 상대 전적을 제공.

    Args:
        sub_event_cd: 종목 코드
        player_name: 선수 이름

    Returns:
        - player: 선수 정보
        - current_round: 현재 진행 중인 라운드
        - predictions: 라운드별 예측 상대
            - round: 라운드명 (64강, 32강, 16강, 8강, 4강, 결승)
            - potential_opponents: 잠재적 상대 목록
                - name: 상대 이름
                - team: 상대 소속
                - seed: 시드 순위
                - head_to_head: 상대 전적 {wins, losses, total}
    """
    # 종목 찾기
    competitions = get_competitions()
    target_event = None

    for comp in competitions:
        for event in comp.get("events", []):
            if event.get("sub_event_cd") == sub_event_cd:
                target_event = event
                break
        if target_event:
            break

    if not target_event:
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다")

    de_bracket = target_event.get("de_bracket", {})
    if not isinstance(de_bracket, dict):
        return {
            "player": {"name": player_name},
            "current_round": None,
            "predictions": [],
            "message": "DE 대진표가 없습니다"
        }

    # normalized_bracket 사용 (있으면)
    normalized = target_event.get("normalized_bracket")
    if normalized:
        bouts_by_round = normalized.get("bouts_by_round", {})
    else:
        bouts_by_round = de_bracket.get("bouts_by_round", {})

    # 선수 시드 찾기
    seeding = de_bracket.get("seeding", [])
    player_seed = None
    player_team = ""
    player_name_lower = player_name.lower() if player_name else ""

    for s in seeding:
        if not isinstance(s, dict):
            continue
        s_name = s.get("name")
        if s_name and s_name.lower() == player_name_lower:
            player_seed = s.get("seed")
            player_team = s.get("team", "")
            break

    if player_seed is None:
        # Pool ranking에서 찾기
        pool_total = target_event.get("pool_total_ranking", [])
        for r in pool_total:
            if not isinstance(r, dict):
                continue
            r_name = r.get("name")
            if r_name and r_name.lower() == player_name_lower:
                player_seed = r.get("rank")
                player_team = r.get("team", "")
                break

    # 라운드 정의
    round_order = ["128강", "64강", "32강", "16강", "8강", "4강", "결승"]
    bracket_size = de_bracket.get("bracket_size", 64)

    # full_bouts에서 가장 이른 라운드 (이벤트 최초 라운드) 찾기
    # _get_full_bouts_from_de_bracket 사용으로 bouts_by_round 폴백 지원
    full_bouts = _get_full_bouts_from_de_bracket(de_bracket)
    earliest_round_idx = len(round_order)  # 최대값으로 초기화
    for bout in full_bouts:
        if isinstance(bout, dict):
            round_name = bout.get("round_name") or bout.get("round", "")
            if round_name and round_name in round_order:
                idx = round_order.index(round_name)
                if idx < earliest_round_idx:
                    earliest_round_idx = idx

    # bracket_size로부터 참가자 수 추정
    if earliest_round_idx < len(round_order):
        # 라운드명에서 bracket_size 추정
        first_round_name = round_order[earliest_round_idx]
        if first_round_name == "128강":
            participant_count = 128
        elif first_round_name == "64강":
            participant_count = 64
        elif first_round_name == "32강":
            participant_count = 32
        elif first_round_name == "16강":
            participant_count = 16
        elif first_round_name == "8강":
            participant_count = 8
        elif first_round_name == "4강":
            participant_count = 4
        else:
            participant_count = 2
    else:
        participant_count = de_bracket.get("participant_count", bracket_size)

    # 현재 라운드 확인 및 완료된 라운드 추적
    current_round = None
    player_eliminated = False
    completed_rounds = set()  # 선수가 완료한 라운드들
    elimination_round = None  # 탈락한 라운드

    # full_bouts에서 선수의 경기 기록 확인
    # _get_full_bouts_from_de_bracket 사용으로 bouts_by_round 폴백 지원
    full_bouts = _get_full_bouts_from_de_bracket(de_bracket)
    for bout in full_bouts:
        if not isinstance(bout, dict) or bout.get("is_bye"):
            continue

        winner_name_val = bout.get("winner_name", "")
        player1 = bout.get("player1_name", "")
        player2 = bout.get("player2_name", "")
        round_name = bout.get("round_name") or bout.get("round", "")

        if not winner_name_val or not player1 or not player2:
            continue

        player1 = player1.strip()
        player2 = player2.strip()
        winner_name_val = winner_name_val.strip()

        # 선수가 이 경기에 참가했는지 확인
        player_in_bout = (player1.lower() == player_name_lower or
                         player2.lower() == player_name_lower)

        if player_in_bout and round_name:
            completed_rounds.add(round_name)
            if winner_name_val.lower() != player_name_lower:
                player_eliminated = True
                elimination_round = round_name

    # bouts_by_round에서도 확인 (fallback)
    for round_name in round_order:
        bouts = bouts_by_round.get(round_name, [])
        for bout in bouts:
            if isinstance(bout, dict):
                p1 = bout.get("player1_name", "")
                p2 = bout.get("player2_name", "")
                winner = bout.get("winner_name", "")

                if p1.lower() == player_name_lower or p2.lower() == player_name_lower:
                    if winner:
                        completed_rounds.add(round_name)
                        if winner.lower() != player_name_lower:
                            player_eliminated = True
                            elimination_round = round_name
                    else:
                        current_round = round_name
        if player_eliminated:
            break

    # 선수가 특정 라운드에 참가했다면, 그 이전 모든 라운드는 통과한 것
    # 예: 16강 경기가 있으면 32강, 64강 등은 완료된 것으로 추정
    if completed_rounds:
        highest_round_idx = -1
        for r in completed_rounds:
            try:
                idx = round_order.index(r)
                if idx > highest_round_idx:
                    highest_round_idx = idx
            except ValueError:
                pass

        # 이벤트 최초 라운드부터 highest_round까지 모두 완료 처리
        def get_first_round_idx(count: int) -> int:
            if count > 64:
                return round_order.index("128강")
            elif count > 32:
                return round_order.index("64강")
            elif count > 16:
                return round_order.index("32강")
            elif count > 8:
                return round_order.index("16강")
            elif count > 4:
                return round_order.index("8강")
            elif count > 2:
                return round_order.index("4강")
            else:
                return round_order.index("결승")

        first_round_idx = get_first_round_idx(participant_count)
        for i in range(first_round_idx, highest_round_idx + 1):
            completed_rounds.add(round_order[i])

    # 현재 라운드 결정: 완료된 라운드 다음 라운드
    if not player_eliminated and completed_rounds:
        for i, r in enumerate(round_order):
            if r in completed_rounds:
                continue
            # 이전 라운드가 완료되었고, 이 라운드가 완료되지 않았으면 현재 라운드
            if i > 0 and round_order[i-1] in completed_rounds:
                current_round = r
                break

    # 예측 대진표 생성
    predictions = []

    def generate_bracket_matches(bracket_size: int) -> list:
        """표준 토너먼트 대진표 생성 (재귀적)

        Returns:
            List of (seed_high, seed_low) tuples for first round
            예: 64강에서 [(1,64), (32,33), (16,49), (17,48), ...]
        """
        if bracket_size == 2:
            return [(1, 2)]

        half = bracket_size // 2
        half_matches = generate_bracket_matches(half)

        result = []
        for seed1, seed2 in half_matches:
            # seed1의 상대: bracket_size + 1 - seed1
            # seed2의 상대: bracket_size + 1 - seed2
            result.append((seed1, bracket_size + 1 - seed1))
            result.append((seed2, bracket_size + 1 - seed2))

        return result

    def get_match_index_for_seed(seed: int, matches: list) -> int:
        """시드의 1라운드 매치 인덱스 반환 (0-indexed)"""
        for i, (s1, s2) in enumerate(matches):
            if seed == s1 or seed == s2:
                return i
        return -1

    def get_potential_opponents(round_name: str, seed: int, bracket_size: int) -> List[int]:
        """특정 라운드에서 만날 수 있는 상대 시드 목록 계산

        표준 단식 토너먼트 대진표 기반 정확한 계산.
        128-bracket과 64-bracket 모두 지원.

        예시 (Seed 4, 128강 브라켓):
        - 128강: [125] (직접 상대)
        - 64강: [61, 68] (인접 매치)
        - 32강: [29, 36, 100, 93] → 실제 참가자만 필터링
        """
        if seed is None or seed < 1 or seed > bracket_size:
            return []

        matches = generate_bracket_matches(bracket_size)
        match_idx = get_match_index_for_seed(seed, matches)

        if match_idx == -1:
            return []

        num_matches = len(matches)  # bracket_size // 2

        # 1라운드 (64강/128강): 직접 상대만
        first_round = "128강" if bracket_size == 128 else "64강"
        if round_name == first_round:
            s1, s2 = matches[match_idx]
            opponent = s2 if s1 == seed else s1
            return [opponent]

        # 각 라운드별 그룹 크기 (매치 수 기준)
        # 128-bracket: 64강=2, 32강=4, 16강=8, 8강=16, 4강=32, 결승=64
        # 64-bracket: 32강=2, 16강=4, 8강=8, 4강=16, 결승=32
        if bracket_size == 128:
            round_group_sizes = {
                "64강": 2,
                "32강": 4,
                "16강": 8,
                "8강": 16,
                "4강": 32,
                "결승": 64,
            }
        else:  # 64-bracket
            round_group_sizes = {
                "32강": 2,
                "16강": 4,
                "8강": 8,
                "4강": 16,
                "결승": 32,
            }

        group_size = round_group_sizes.get(round_name)
        if group_size is None:
            return []

        # 결승: 반대편 절반 전체
        if round_name == "결승":
            half = num_matches // 2
            if match_idx < half:
                start_idx, end_idx = half, num_matches
            else:
                start_idx, end_idx = 0, half
        else:
            # 그룹 시작/끝 인덱스 계산
            group_idx = match_idx // group_size
            start_idx = group_idx * group_size
            end_idx = min(start_idx + group_size, num_matches)

        # 해당 그룹의 시드 수집 (자기 매치 제외)
        opponents = []
        for i in range(start_idx, end_idx):
            if i < len(matches) and i != match_idx:  # 자기 매치 제외
                s1, s2 = matches[i]
                opponents.append(s1)
                opponents.append(s2)

        return sorted(opponents)

    # 시드 -> 선수 매핑
    seed_to_player = {}
    for s in seeding:
        seed_to_player[s.get("seed")] = {
            "name": s.get("name", ""),
            "team": s.get("team", "")
        }

    # Pool total ranking에서도 시드 매핑 보충
    pool_total = target_event.get("pool_total_ranking", [])
    for i, r in enumerate(pool_total):
        seed_num = r.get("rank", i + 1)
        if seed_num not in seed_to_player or not seed_to_player[seed_num].get("name"):
            seed_to_player[seed_num] = {
                "name": r.get("name", ""),
                "team": r.get("team", "")
            }

    # 이벤트 최초 라운드 결정 (참가자 수 기반)
    # 참가자 수에 따라 시작 라운드가 달라짐
    def get_first_round_for_count(count: int) -> str:
        if count > 64:
            return "128강"
        elif count > 32:
            return "64강"
        elif count > 16:
            return "32강"
        elif count > 8:
            return "16강"
        elif count > 4:
            return "8강"
        elif count > 2:
            return "4강"
        else:
            return "결승"

    event_first_round = get_first_round_for_count(participant_count)

    # 선수의 128강 상대가 부전승인지 확인 (seed가 participant_count 초과)
    first_round_opponent = bracket_size + 1 - player_seed if player_seed else None
    has_bye_in_128 = first_round_opponent and first_round_opponent > participant_count

    # 라운드 이름 결정 (부전승이면 64강부터 시작)
    if bracket_size >= 128 and has_bye_in_128:
        # 128강에서 부전승이면 64강부터 예측 시작
        all_round_names = ["64강", "32강", "16강", "8강", "4강", "결승"]
    elif bracket_size >= 128:
        all_round_names = ["128강", "64강", "32강", "16강", "8강", "4강", "결승"]
    else:
        all_round_names = ["64강", "32강", "16강", "8강", "4강", "결승"]

    # full_bouts에서 탈락한 시드 추출 (완료된 라운드의 패자)
    eliminated_seeds = set()

    # 🔥 헬퍼 함수: 선수 이름으로 시드 찾기
    def find_seed_by_name(name: str) -> Optional[int]:
        if not name:
            return None
        name_lower = name.lower()
        for seed_num, pinfo in seed_to_player.items():
            pname = pinfo.get("name", "") or ""
            if pname.lower() == name_lower:
                return seed_num
        return None

    # 1. bouts_by_round에서 패자 추출
    for round_name in round_order:
        bouts = bouts_by_round.get(round_name, [])
        for bout in bouts:
            if isinstance(bout, dict):
                winner_name = bout.get("winner_name", "")
                if winner_name:
                    # 패자 시드 찾기
                    p1_name = bout.get("player1_name", "") or ""
                    p2_name = bout.get("player2_name", "") or ""
                    loser_name = p1_name if winner_name.lower() == p2_name.lower() else p2_name
                    loser_seed = find_seed_by_name(loser_name)
                    if loser_seed:
                        eliminated_seeds.add(loser_seed)

                # 🔥 기권 처리: is_forfeit, forfeit_player 필드 확인
                if bout.get("is_forfeit") and bout.get("forfeit_player"):
                    forfeit_seed = find_seed_by_name(bout.get("forfeit_player"))
                    if forfeit_seed:
                        eliminated_seeds.add(forfeit_seed)

    # 2. 🔥 full_bouts에서도 패자/기권자 추출 (더 정확한 데이터)
    for fb in full_bouts:
        if isinstance(fb, dict):
            # loser 정보가 있으면 탈락자로 추가
            loser_info = fb.get("loser", {})
            if loser_info:
                loser_seed = loser_info.get("seed")
                if loser_seed:
                    eliminated_seeds.add(loser_seed)
                else:
                    # seed가 없으면 이름으로 찾기
                    loser_name = loser_info.get("name")
                    loser_seed = find_seed_by_name(loser_name)
                    if loser_seed:
                        eliminated_seeds.add(loser_seed)

            # 🔥 기권 처리
            if fb.get("is_forfeit") and fb.get("forfeit_player"):
                forfeit_seed = find_seed_by_name(fb.get("forfeit_player"))
                if forfeit_seed:
                    eliminated_seeds.add(forfeit_seed)

    # 3. 🔥 다음 라운드 진출자 기반 탈락자 추론 (winner_name이 null인 경기 처리)
    # 각 라운드에서 다음 라운드에 나타나지 않는 선수를 탈락자로 추정
    # ⚠️ 동명이인 문제 해결: 이름 대신 시드(seed) 기반으로 추적
    def get_seeds_in_round(r_name: str) -> set:
        """특정 라운드에 참가한 선수 시드 집합 (동명이인 구분)"""
        seeds = set()
        for fb in full_bouts:
            if isinstance(fb, dict) and (fb.get("round_name") or fb.get("round", "")) == r_name:
                p1_seed = fb.get("player1_seed")
                p2_seed = fb.get("player2_seed")
                if p1_seed and isinstance(p1_seed, int) and p1_seed <= participant_count:
                    seeds.add(p1_seed)
                if p2_seed and isinstance(p2_seed, int) and p2_seed <= participant_count:
                    seeds.add(p2_seed)
        return seeds

    # 라운드 순서대로 탈락자 추론 (시드 기반)
    for i, r_name in enumerate(round_order[:-1]):  # 결승 제외
        next_round = round_order[i + 1]
        current_seeds = get_seeds_in_round(r_name)
        next_seeds = get_seeds_in_round(next_round)

        if current_seeds and next_seeds:
            # 현재 라운드에 있었지만 다음 라운드에 없는 시드 = 탈락자
            eliminated_in_round = current_seeds - next_seeds
            eliminated_seeds.update(eliminated_in_round)

    # 이벤트 최초 라운드부터 시작하도록 필터링
    try:
        first_round_idx = all_round_names.index(event_first_round)
        round_names = all_round_names[first_round_idx:]
    except ValueError:
        round_names = all_round_names

    # 각 라운드별 예측 생성 (이전 라운드 상대 누적 추적)
    previous_opponents = set()  # 이전 라운드에서 이미 표시된 상대들

    for round_name in round_names:
        # 이미 완료된 라운드는 예측에서 제외 (결과에만 표시)
        if round_name in completed_rounds:
            # 완료된 라운드의 상대는 previous_opponents에 추가하여 다음 라운드에서 제외
            potential_seeds = get_potential_opponents(round_name, player_seed, bracket_size)
            # participant_count 초과 시드 필터링 (부전승)
            valid_seeds = [s for s in potential_seeds if s <= participant_count]
            previous_opponents.update(valid_seeds)
            continue

        # 선수가 탈락했으면 미래 라운드 예측 중단
        if player_eliminated and elimination_round:
            try:
                elim_idx = round_order.index(elimination_round)
                curr_idx = round_order.index(round_name)
                if curr_idx > elim_idx:
                    break  # 탈락 라운드 이후는 예측하지 않음
            except ValueError:
                pass
        potential_seeds = get_potential_opponents(round_name, player_seed, bracket_size)

        # 1. 부전승 필터링: participant_count를 초과하는 시드는 존재하지 않음
        valid_seeds = [s for s in potential_seeds if s <= participant_count]

        # 2. 탈락자 필터링: 이미 경기에서 진 시드 제외
        valid_seeds = [s for s in valid_seeds if s not in eliminated_seeds]

        # 3. 이전 라운드에서 이미 표시된 상대 제외 (NEW 상대만 표시)
        new_seeds = [s for s in valid_seeds if s not in previous_opponents]

        opponents = []
        for seed in new_seeds:
            player_info = seed_to_player.get(seed, {})
            opp_name = player_info.get("name")
            opp_team = player_info.get("team", "")

            # 실제 선수 정보가 없으면 스킵 (추가 bye 체크)
            if not opp_name:
                continue

            # 상대 전적 조회 (간소화)
            h2h = {"wins": 0, "losses": 0, "total": 0}
            if opp_name and opp_name != f"Seed {seed}":
                # 전적 검색 (간소화된 버전)
                for comp in competitions:
                    for evt in comp.get("events", []):
                        for pool in evt.get("pool_rounds", []):
                            for bout in pool.get("bouts", []):
                                p1 = bout.get("player1_name", "").lower()
                                p2 = bout.get("player2_name", "").lower()
                                winner = bout.get("winner_name", "").lower()

                                if (p1 == player_name_lower and p2 == opp_name.lower()) or \
                                   (p1 == opp_name.lower() and p2 == player_name_lower):
                                    h2h["total"] += 1
                                    if winner == player_name_lower:
                                        h2h["wins"] += 1
                                    else:
                                        h2h["losses"] += 1

            opponents.append({
                "name": opp_name,
                "team": opp_team,
                "seed": seed,
                "head_to_head": h2h
            })

        predictions.append({
            "round": round_name,
            "potential_opponents": opponents,
            "expanded_default": round_name in ["64강", "32강"]  # 32강까지 기본 펼침
        })

        # 이번 라운드의 모든 잠재적 상대를 이전 상대 목록에 추가 (다음 라운드에서 제외하기 위해)
        # new_seeds가 아닌 valid_seeds(부전승 제외)를 추가해야 다음 라운드에서 중복 방지
        previous_opponents.update(valid_seeds)

    return {
        "player": {
            "name": player_name,
            "team": player_team,
            "seed": player_seed
        },
        "event_first_round": event_first_round,  # 이벤트 최초 라운드
        "completed_rounds": list(completed_rounds),  # 완료된 라운드 목록
        "current_round": current_round,
        "elimination_round": elimination_round,  # 탈락한 라운드
        "eliminated": player_eliminated,
        "predictions": predictions
    }


@app.get("/api/events/{sub_event_cd}/de-results/{player_name}")
async def api_de_results(
    sub_event_cd: str,
    player_name: str
):
    """DE 라운드별 실제 경기 결과 - 선수의 DE 경기 결과 표시

    Args:
        sub_event_cd: 종목 코드
        player_name: 선수 이름

    Returns:
        - player: 선수 정보
        - results: 라운드별 실제 결과
            - round: 라운드명 (128강, 64강, 32강 등)
            - opponent: 상대 정보 {name, team, seed}
            - score: 점수 (예: "15-10")
            - result: 결과 ("win" / "lose")
    """
    # 종목 찾기
    competitions = get_competitions()
    target_event = None
    target_comp = None

    for comp in competitions:
        for event in comp.get("events", []):
            if event.get("sub_event_cd") == sub_event_cd:
                target_event = event
                target_comp = comp
                break
        if target_event:
            break

    if not target_event:
        raise HTTPException(status_code=404, detail="종목을 찾을 수 없습니다")

    de_bracket = target_event.get("de_bracket", {})
    if not isinstance(de_bracket, dict):
        return {
            "player": {"name": player_name},
            "results": [],
            "message": "DE 대진표가 없습니다"
        }

    # 선수 시드 및 팀 찾기
    seeding = de_bracket.get("seeding", [])
    player_seed = None
    player_team = ""
    player_name_lower = player_name.lower() if player_name else ""

    for s in seeding:
        if not isinstance(s, dict):
            continue
        s_name = s.get("name")
        if s_name and s_name.lower() == player_name_lower:
            player_seed = s.get("seed")
            player_team = s.get("team", "")
            break

    # Pool ranking에서 찾기
    if player_seed is None:
        pool_total = target_event.get("pool_total_ranking", [])
        for r in pool_total:
            if not isinstance(r, dict):
                continue
            r_name = r.get("name")
            if r_name and r_name.lower() == player_name_lower:
                player_seed = r.get("rank")
                player_team = r.get("team", "")
                break

    # normalized_bracket 또는 bouts_by_round 사용
    normalized = target_event.get("normalized_bracket")
    if normalized:
        bouts_by_round = normalized.get("bouts_by_round", {})
    else:
        bouts_by_round = de_bracket.get("bouts_by_round", {})

    # full_bouts에서도 라운드별 경기 추출
    # _get_full_bouts_from_de_bracket 사용으로 bouts_by_round 폴백 지원
    full_bouts = _get_full_bouts_from_de_bracket(de_bracket)

    # 라운드 순서 정의
    round_order_results = ["128강", "64강", "32강", "16강", "8강", "4강", "결승"]

    # full_bouts에서 가장 이른 라운드 (이벤트 최초 라운드) 찾기
    earliest_round_idx = len(round_order_results)
    for bout in full_bouts:
        if isinstance(bout, dict):
            round_name = bout.get("round_name") or bout.get("round", "")
            if round_name and round_name in round_order_results:
                idx = round_order_results.index(round_name)
                if idx < earliest_round_idx:
                    earliest_round_idx = idx

    # 최초 라운드에서 참가자 수 추정
    if earliest_round_idx < len(round_order_results):
        first_round_name = round_order_results[earliest_round_idx]
        if first_round_name == "128강":
            participant_count = 128
        elif first_round_name == "64강":
            participant_count = 64
        elif first_round_name == "32강":
            participant_count = 32
        elif first_round_name == "16강":
            participant_count = 16
        elif first_round_name == "8강":
            participant_count = 8
        elif first_round_name == "4강":
            participant_count = 4
        else:
            participant_count = 2
    else:
        participant_count = de_bracket.get("participant_count", 16)

    def get_first_round_for_count(count: int) -> str:
        """참가자 수에 따른 이벤트 최초 라운드 결정"""
        if count > 64:
            return "128강"
        elif count > 32:
            return "64강"
        elif count > 16:
            return "32강"
        elif count > 8:
            return "16강"
        elif count > 4:
            return "8강"
        elif count > 2:
            return "4강"
        else:
            return "결승"

    event_first_round = get_first_round_for_count(participant_count)

    # 라운드 순서
    round_order = ["128강", "64강", "32강", "16강", "8강", "4강", "결승"]

    results = []

    # 먼저 full_bouts에서 검색
    # 데이터 구조: winner_name, player1_name, player2_name, player1_score, player2_score
    # loser_name 필드가 없으므로 직접 계산해야 함
    # player_name_lower는 이미 위에서 정의됨

    for bout in full_bouts:
        if not isinstance(bout, dict):
            continue

        is_bye = bout.get("is_bye", False)
        if is_bye:
            continue

        # 데이터 구조: winner_name, player1_name, player2_name 사용
        bout_winner = bout.get("winner_name", "")
        player1 = bout.get("player1_name", "")
        player2 = bout.get("player2_name", "")
        p1_score = bout.get("player1_score")
        p2_score = bout.get("player2_score")
        p1_team = bout.get("player1_team", "")
        p2_team = bout.get("player2_team", "")
        round_name = bout.get("round_name") or bout.get("round", "")

        # winner/loser 중첩 객체 구조도 폴백으로 지원
        if not bout_winner:
            winner_obj = bout.get("winner", {}) or {}
            bout_winner = winner_obj.get("name", "")

        if not bout_winner or not player1 or not player2:
            continue

        # 패자 계산: winner가 아닌 쪽이 loser
        bout_winner = bout_winner.strip()
        player1 = player1.strip()
        player2 = player2.strip()

        if bout_winner == player1:
            bout_loser = player2
            winner_score = p1_score
            loser_score = p2_score
            winner_team = p1_team
            loser_team = p2_team
        elif bout_winner == player2:
            bout_loser = player1
            winner_score = p2_score
            loser_score = p1_score
            winner_team = p2_team
            loser_team = p1_team
        else:
            continue

        winner_lower = bout_winner.lower()
        loser_lower = bout_loser.lower() if bout_loser else ""

        # 선수가 승자인 경우
        if winner_lower == player_name_lower:
            opponent_name = bout_loser
            opponent_team_val = loser_team
            score = f"{winner_score}-{loser_score}" if winner_score is not None and loser_score is not None else "-"
            result_type = "win"
        # 선수가 패자인 경우
        elif loser_lower == player_name_lower:
            opponent_name = bout_winner
            opponent_team_val = winner_team
            score = f"{loser_score}-{winner_score}" if loser_score is not None and winner_score is not None else "-"
            result_type = "lose"
        else:
            continue

        # BYE 처리
        if not opponent_name:
            continue

        # 상대 시드 찾기
        opponent_seed = None
        opponent_name_lower = opponent_name.lower() if opponent_name else ""
        for s in seeding:
            if not isinstance(s, dict):
                continue
            s_name = s.get("name")
            if s_name and s_name.lower() == opponent_name_lower:
                opponent_seed = s.get("seed")
                if not opponent_team_val:
                    opponent_team_val = s.get("team", "")
                break

        results.append({
            "round": round_name,
            "opponent": {
                "name": opponent_name,
                "team": opponent_team_val,
                "seed": opponent_seed
            },
            "score": score,
            "result": result_type
        })

    # full_bouts에서 못 찾으면 bouts_by_round에서 검색
    if not results:
        for round_name in round_order:
            bouts = bouts_by_round.get(round_name, [])
            for bout in bouts:
                if not isinstance(bout, dict):
                    continue

                p1 = bout.get("player1_name", "")
                p2 = bout.get("player2_name", "")
                winner = bout.get("winner_name", "")

                p1_lower = p1.lower() if p1 else ""
                p2_lower = p2.lower() if p2 else ""
                winner_lower = winner.lower() if winner else ""

                if p1_lower == player_name_lower or p2_lower == player_name_lower:
                    # 상대 찾기
                    opponent_name = p2 if p1_lower == player_name_lower else p1
                    opponent_team = bout.get("player2_team", "") if p1_lower == player_name_lower else bout.get("player1_team", "")

                    # 점수 구성
                    score1 = bout.get("player1_score")
                    score2 = bout.get("player2_score")

                    if p1_lower == player_name_lower:
                        score = f"{score1}-{score2}" if score1 is not None and score2 is not None else "-"
                        result_type = "win" if winner_lower == player_name_lower else "lose"
                    else:
                        score = f"{score2}-{score1}" if score1 is not None and score2 is not None else "-"
                        result_type = "win" if winner_lower == player_name_lower else "lose"

                    # 상대 시드 찾기
                    opponent_seed = None
                    opponent_name_lower = opponent_name.lower() if opponent_name else ""
                    for s in seeding:
                        if not isinstance(s, dict):
                            continue
                        s_name = s.get("name")
                        if s_name and s_name.lower() == opponent_name_lower:
                            opponent_seed = s.get("seed")
                            if not opponent_team:
                                opponent_team = s.get("team", "")
                            break

                    results.append({
                        "round": round_name,
                        "opponent": {
                            "name": opponent_name,
                            "team": opponent_team,
                            "seed": opponent_seed
                        },
                        "score": score,
                        "result": result_type
                    })

    # 라운드 순서대로 정렬
    def round_sort_key(r):
        try:
            return round_order.index(r["round"])
        except ValueError:
            return 999

    results.sort(key=round_sort_key)

    return {
        "player": {
            "name": player_name,
            "team": player_team,
            "seed": player_seed
        },
        "event_first_round": event_first_round,  # 이벤트 최초 라운드
        "participant_count": participant_count,  # 참가자 수
        "results": results
    }


@app.get("/api/stats")
async def api_stats():
    """통계 API"""
    competitions = get_competitions()

    stats = {
        "total_competitions": len(competitions),
        "total_events": sum(len(c.get("events", [])) for c in competitions),
        "total_players": len(_player_index),
        "by_year": {},
        "by_weapon": {"foil": 0, "epee": 0, "sabre": 0}
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
    request: Request,
    weapon: str = Query(..., description="무기 (foil/epee/sabre)"),
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

    # 접근 등급별 필터링: guest는 상위 10명 숨김
    access_level, _ = await get_access_level(request)
    if access_level == "guest":
        rankings = filter_rankings_for_guest(rankings)

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
        rankings=ranking_entries,
        hidden_top=RANKINGS_HIDDEN_TOP_N if access_level == "guest" else 0,
    )


@app.get("/api/rankings/options")
async def api_ranking_options():
    """랭킹 필터 옵션 API"""
    return {
        "weapons": ["foil", "epee", "sabre"],
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
async def api_player_rankings(request: Request, player_name: str):
    """선수의 모든 카테고리 랭킹 조회"""
    access_level, _ = await get_access_level(request)
    if access_level == "guest":
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

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
                        # Update team if current one is empty but new one has a value
                        elif opponent_team and not opponent_stats[opponent_name].get("team"):
                            opponent_stats[opponent_name]["team"] = opponent_team

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
                # 데이터 구조: winner_name, player1_name, player2_name, player1_score, player2_score
                # loser_name 필드가 없으므로 직접 계산해야 함
                # _get_full_bouts_from_de_bracket 사용으로 bouts_by_round 폴백 지원
                full_bouts = _get_full_bouts_from_de_bracket(de_bracket)
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
                        if not isinstance(bout, dict) or bout.get("is_bye"):
                            continue

                        # 실제 데이터 구조 사용
                        winner_name_val = bout.get("winner_name", "")
                        player1 = bout.get("player1_name", "")
                        player2 = bout.get("player2_name", "")

                        if not winner_name_val or not player1 or not player2:
                            continue

                        # 패자 계산
                        winner_name_val = winner_name_val.strip()
                        player1 = player1.strip()
                        player2 = player2.strip()

                        if winner_name_val == player1:
                            loser_name_val = player2
                        elif winner_name_val == player2:
                            loser_name_val = player1
                        else:
                            continue

                        if winner_name_val == player_name or loser_name_val == player_name:
                            # 파싱된 정보 추가
                            bout["_winner_name"] = winner_name_val
                            bout["_loser_name"] = loser_name_val
                            player_bouts.append(bout)

                    # 같은 상대에 대해 여러 결과가 있으면 final_rankings로 검증
                    seen_de_opponents = set()
                    for bout in player_bouts:
                        round_name = bout.get("round_name") or bout.get("round", "DE")

                        opponent_name = None
                        my_score = 0
                        opponent_score = 0
                        result = None
                        opponent_team = ""

                        w_name = bout.get("_winner_name", "")
                        l_name = bout.get("_loser_name", "")
                        p1_score = bout.get("player1_score")
                        p2_score = bout.get("player2_score")
                        p1_team = bout.get("player1_team", "")
                        p2_team = bout.get("player2_team", "")

                        # 승자/패자 점수 및 팀 결정
                        if w_name == bout.get("player1_name", "").strip():
                            w_score = p1_score
                            l_score = p2_score
                            w_team = p1_team
                            l_team = p2_team
                        else:
                            w_score = p2_score
                            l_score = p1_score
                            w_team = p2_team
                            l_team = p1_team

                        # 선수가 winner인 경우
                        if w_name == player_name:
                            if profile_teams and w_team and w_team not in profile_teams:
                                continue
                            opponent_name = l_name
                            opponent_team = l_team
                            my_score = w_score or 0
                            opponent_score = l_score or 0
                            result = "V"
                        # 선수가 loser인 경우
                        elif l_name == player_name:
                            if profile_teams and l_team and l_team not in profile_teams:
                                continue
                            opponent_name = w_name
                            opponent_team = w_team
                            my_score = l_score or 0
                            opponent_score = w_score or 0
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
                            # Update team if current one is empty but new one has a value
                            elif opponent_team and not opponent_stats[opponent_name].get("team"):
                                opponent_stats[opponent_name]["team"] = opponent_team

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
                                # Update team if current one is empty but new one has a value
                                elif opponent_team and not opponent_stats[opponent_name].get("team"):
                                    opponent_stats[opponent_name]["team"] = opponent_team

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
        'foil': 'Foil',
        'epee': 'Epee',
        'sabre': 'Sabre',
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
        'birth_date': 'Jul 24, 2013' if player_name == '박소윤' and (not weapon or weapon == 'foil') else 'N/A',
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


def enrich_records_with_match_details(records: list, player_name: str) -> list:
    """History 섹션용 상세 매치 데이터 추가

    각 record에 pool_bouts, tournament_bouts, tournament_path 추가
    """
    player_name_lower = player_name.lower()
    enriched = []

    for record in records:
        # 기본 record 복사
        enriched_record = dict(record)
        enriched_record["pool_bouts"] = []
        enriched_record["tournament_bouts"] = []
        enriched_record["tournament_path"] = []

        # 이벤트 데이터 찾기
        sub_event_cd = record.get("sub_event_cd", "")
        if not sub_event_cd:
            enriched.append(enriched_record)
            continue

        event_data = None
        for comp in _data_cache.get("competitions", []):
            for event in comp.get("events", []):
                if event.get("sub_event_cd") == sub_event_cd:
                    event_data = event
                    break
            if event_data:
                break

        if not event_data:
            enriched.append(enriched_record)
            continue

        # Pool 경기 추출
        pool_rounds = event_data.get("pool_rounds", [])
        pool_wins = 0
        pool_losses = 0
        touches_scored = 0
        touches_received = 0
        pool_rank = None
        pool_total = None
        pool_number_found = None

        for pool in pool_rounds:
            pool_number = pool.get("pool_number", 1)
            pool_results = pool.get("results", [])

            # 해당 선수의 Pool 결과 찾기
            player_result = None
            for result in pool_results:
                if result.get("name", "").lower() == player_name_lower:
                    player_result = result
                    break

            if not player_result:
                continue

            # Pool 순위 및 총 인원 정보 추출
            pool_rank = player_result.get("rank")
            pool_total = len(pool_results)
            pool_number_found = pool_number

            # Pool 개별 매치 - 두 가지 데이터 형식 지원
            # 형식 1: bouts/matches 배열 (직접 상대 정보 포함)
            # 형식 2: scores 배열 (위치 기반, 상대 정보는 pool_results에서 매칭 필요)
            player_bouts = player_result.get("bouts", []) or player_result.get("matches", [])
            player_scores = player_result.get("scores", [])

            if player_bouts:
                # 형식 1: bouts/matches 배열 처리
                for bout in player_bouts:
                    if not isinstance(bout, dict):
                        continue

                    opponent = bout.get("opponent", "")
                    my_score = bout.get("score", 0) or bout.get("my_score", 0)
                    opp_score = bout.get("opponent_score", 0) or bout.get("opp_score", 0)
                    result_code = bout.get("result", "")

                    # 결과 판정
                    if result_code == "V" or (my_score and opp_score and my_score > opp_score):
                        result_str = "win"
                        pool_wins += 1
                    elif result_code == "D" or (my_score and opp_score and my_score < opp_score):
                        result_str = "lose"
                        pool_losses += 1
                    else:
                        result_str = "draw" if my_score == opp_score else "pending"

                    # 상대 팀 정보 찾기
                    opponent_team = ""
                    for result in pool_results:
                        if result.get("name", "").lower() == opponent.lower():
                            opponent_team = result.get("team", "")
                            break

                    enriched_record["pool_bouts"].append({
                        "pool_number": pool_number,
                        "opponent_name": opponent,
                        "opponent_team": opponent_team,
                        "my_score": my_score,
                        "opponent_score": opp_score,
                        "result": "V" if result_str == "win" else "D"
                    })

                    touches_scored += my_score if isinstance(my_score, int) else 0
                    touches_received += opp_score if isinstance(opp_score, int) else 0

            elif player_scores:
                # 형식 2: scores 배열 처리 (위치 기반)
                # pool_results를 position으로 정렬하여 상대 매칭
                sorted_pool_results = sorted(pool_results, key=lambda x: x.get("position", 999))
                player_position = player_result.get("position", 0)

                for idx, score_entry in enumerate(player_scores):
                    if score_entry is None:
                        continue  # 자기 자신 위치 (null)
                    if not isinstance(score_entry, dict):
                        continue

                    # 상대 선수 찾기 (position 기반)
                    opponent_idx = idx + 1  # scores 배열은 1-indexed position과 매칭
                    opponent_result = None
                    for pr in sorted_pool_results:
                        if pr.get("position") == opponent_idx:
                            opponent_result = pr
                            break

                    if not opponent_result:
                        continue

                    opponent_name = opponent_result.get("name", "")
                    opponent_team = opponent_result.get("team", "")

                    # 내 점수와 결과 추출
                    my_score = score_entry.get("score", 0)
                    result_type = score_entry.get("type", "")  # "V" or "L"

                    # 상대 점수 찾기 (상대의 scores 배열에서 내 position에 해당하는 값)
                    opp_score = 0
                    opponent_scores = opponent_result.get("scores", [])
                    if player_position and player_position <= len(opponent_scores):
                        opp_score_entry = opponent_scores[player_position - 1]
                        if isinstance(opp_score_entry, dict):
                            opp_score = opp_score_entry.get("score", 0)

                    # 결과 판정
                    if result_type == "V":
                        result_str = "win"
                        pool_wins += 1
                    elif result_type == "L":
                        result_str = "lose"
                        pool_losses += 1
                    else:
                        result_str = "pending"

                    enriched_record["pool_bouts"].append({
                        "pool_number": pool_number,
                        "opponent_name": opponent_name,
                        "opponent_team": opponent_team,
                        "my_score": my_score,
                        "opponent_score": opp_score,
                        "result": "V" if result_str == "win" else "D"
                    })

                    touches_scored += my_score if isinstance(my_score, int) else 0
                    touches_received += opp_score if isinstance(opp_score, int) else 0

        # Pool 통계 추가
        enriched_record["pool_record"] = f"{pool_wins}승 {pool_losses}패" if pool_wins or pool_losses else ""
        enriched_record["pool_wins"] = pool_wins
        enriched_record["pool_losses"] = pool_losses
        enriched_record["indicator"] = touches_scored - touches_received
        enriched_record["touches_scored"] = touches_scored
        enriched_record["touches_received"] = touches_received
        enriched_record["pool_rank"] = pool_rank
        enriched_record["pool_total"] = pool_total
        enriched_record["pool_number"] = pool_number_found
        # Calculate V/M (win rate) as percentage
        if pool_wins + pool_losses > 0:
            enriched_record["pool_vm"] = round(pool_wins / (pool_wins + pool_losses) * 100, 1)
        else:
            enriched_record["pool_vm"] = None

        # DE 경기 추출
        # _get_full_bouts_from_de_bracket 사용으로 bouts_by_round 폴백 지원
        de_bracket = event_data.get("de_bracket", {})
        # dual_de 감지: de_bracket JSON 내 format 또는 events 테이블 de_format 컬럼
        is_dual_de = isinstance(de_bracket, dict) and (
            de_bracket.get("format") == "dual_de" or
            event_data.get("de_format") == "dual_de"
        )
        # flat dual_de: de_format은 dual_de이지만 de_bracket에 first_de/second_de가 없는 경우
        is_flat_dual_de = is_dual_de and isinstance(de_bracket, dict) and "first_de" not in de_bracket
        if isinstance(de_bracket, dict):
            full_bouts = _get_full_bouts_from_de_bracket(de_bracket)

            # 이벤트의 실제 시작 라운드 가져오기 (데이터 파이프라인 원칙: 근본 데이터 사용)
            if is_dual_de and not is_flat_dual_de:
                # 구조화된 dual_de: second_de(본선)의 starting_round 사용
                second_de = de_bracket.get("second_de", {})
                first_de = de_bracket.get("first_de", {})
                starting_round = second_de.get("starting_round") or first_de.get("starting_round") or "32강"
                bracket_size = second_de.get("bracket_size") or first_de.get("bracket_size") or 32
            else:
                starting_round = de_bracket.get("starting_round", "32강")
                bracket_size = de_bracket.get("bracket_size", 32)

            # flat dual_de: 라운드 이름 기반으로 de_phase 추론 태깅
            # 128강 이상에서 시작하면 본선은 보통 32강부터 (가장 일반적 패턴)
            if is_flat_dual_de:
                _flat_round_order = ["256강", "128강", "64강", "32강", "16강", "8강", "4강", "결승"]
                # 본선 시작 라운드 추론: bracket_size가 128이면 본선은 32강, 64이면 16강
                _main_start = "32강" if int(bracket_size) >= 128 else "16강"
                if _main_start in _flat_round_order:
                    _main_idx = _flat_round_order.index(_main_start)
                    _qualifying_rounds = set(_flat_round_order[:_main_idx])  # 본선 이전 라운드
                else:
                    _qualifying_rounds = set()
                for bout in full_bouts:
                    if isinstance(bout, dict):
                        r = bout.get("round_name") or bout.get("round", "")
                        bout["de_phase"] = "qualifying" if r in _qualifying_rounds else "main"

            # 표준 라운드 순서 (256강 포함)
            full_round_order = ["256강", "128강", "64강", "32강", "16강", "8강", "4강", "결승"]

            # 이벤트 시작 라운드부터만 포함 (첫 라운드가 정확하게 표시됨)
            if starting_round in full_round_order:
                start_idx = full_round_order.index(starting_round)
                round_order = full_round_order[start_idx:]
            else:
                round_order = ["32강", "16강", "8강", "4강", "결승"]

            player_de_rounds = {}
            seen_de_bouts = set()  # tournament_bouts 중복 방지

            for bout in full_bouts:
                if not isinstance(bout, dict):
                    continue

                # 데이터 구조: winner_name, player1_name, player2_name, player1_score, player2_score
                winner_name = bout.get("winner_name", "")
                player1 = bout.get("player1_name", "")
                player2 = bout.get("player2_name", "")
                p1_score = bout.get("player1_score")
                p2_score = bout.get("player2_score")
                round_name = bout.get("round_name") or bout.get("round", "")
                is_bye = bout.get("is_bye", False)

                # 부전승(BYE) 경기 처리 - 첫 라운드 부전승도 표시
                if is_bye:
                    if winner_name and winner_name.strip().lower() == player_name_lower:
                        # 부전승으로 진출
                        enriched_record["tournament_bouts"].append({
                            "round_name": round_name,
                            "opponent_name": "(부전승)",
                            "opponent_team": "",
                            "my_score": None,
                            "opponent_score": None,
                            "result": "BYE",
                            "is_bye": True,
                            "de_phase": bout.get("de_phase", "main")
                        })
                        player_de_rounds[round_name] = "bye"
                    continue

                if not winner_name or not player1 or not player2:
                    continue

                # 패자 계산
                winner_name = winner_name.strip()
                player1 = player1.strip()
                player2 = player2.strip()

                if winner_name == player1:
                    loser_name = player2
                    winner_score = p1_score
                    loser_score = p2_score
                elif winner_name == player2:
                    loser_name = player1
                    winner_score = p2_score
                    loser_score = p1_score
                else:
                    continue

                winner_lower = winner_name.lower()
                loser_lower = loser_name.lower() if loser_name else ""

                # 선수가 승자인 경우
                if winner_lower == player_name_lower:
                    opponent = loser_name
                    my_score = winner_score
                    opp_score = loser_score
                    result_str = "win"
                # 선수가 패자인 경우
                elif loser_lower == player_name_lower:
                    opponent = winner_name
                    my_score = loser_score
                    opp_score = winner_score
                    result_str = "lose"
                else:
                    continue

                if not opponent or opponent is None:
                    continue

                # 상대 팀 정보 찾기 (seeding 또는 pool_total_ranking에서)
                opponent_team = ""
                opponent_lower = opponent.lower() if opponent else ""
                seeding = de_bracket.get("seeding", [])
                for s in seeding:
                    s_name = s.get("name", "") if s else ""
                    if s_name and s_name.lower() == opponent_lower:
                        opponent_team = s.get("team", "")
                        break
                if not opponent_team:
                    pool_total = event_data.get("pool_total_ranking", [])
                    for r in pool_total:
                        r_name = r.get("name", "") if r else ""
                        if r_name and r_name.lower() == opponent_lower:
                            opponent_team = r.get("team", "")
                            break

                # 중복 bout 방지 (같은 라운드+상대 조합)
                bout_key = f"{round_name}|{opponent}"
                if bout_key in seen_de_bouts:
                    continue
                seen_de_bouts.add(bout_key)

                de_phase = bout.get("de_phase", "main")
                enriched_record["tournament_bouts"].append({
                    "round_name": round_name,
                    "opponent_name": opponent,
                    "opponent_team": opponent_team,
                    "my_score": my_score,
                    "opponent_score": opp_score,
                    "result": "V" if result_str == "win" else "D",
                    "de_phase": de_phase
                })

                player_de_rounds[round_name] = result_str

            # Tournament path 생성 (이벤트 시작 라운드부터만 표시)
            # round_order는 이미 이벤트의 starting_round부터 시작하도록 필터링됨
            final_rank = record.get("rank")
            for round_name in round_order:
                if round_name in player_de_rounds:
                    result = player_de_rounds[round_name]
                    enriched_record["tournament_path"].append({
                        "name": round_name,
                        "completed": True,
                        "current": result == "lose",  # 패배한 라운드가 마지막
                        "is_bye": result == "bye"  # 부전승 표시
                    })

            # tournament_bouts를 라운드 순서대로 정렬 (BYE 포함)
            # round_order에 따라 정렬하여 첫 라운드 부전승이 맨 위에 오도록 함
            round_order_map = {r: i for i, r in enumerate(round_order)}
            # "준결승" = "4강" 동일 순서 (DB에서 두 표현 혼용)
            if "4강" in round_order_map and "준결승" not in round_order_map:
                round_order_map["준결승"] = round_order_map["4강"]
            enriched_record["tournament_bouts"].sort(
                key=lambda b: round_order_map.get(b.get("round_name", ""), 999)
            )

        # 템플릿용 플래그 설정
        enriched_record["pool_results"] = len(enriched_record["pool_bouts"]) > 0
        enriched_record["tournament_results"] = len(enriched_record["tournament_bouts"]) > 0

        enriched.append(enriched_record)

    return enriched


@app.get("/player/{player_name}", response_class=HTMLResponse)
async def player_page(
    request: Request,
    player_name: str,
    id: Optional[str] = None,
    team: Optional[str] = None,
    strength_start: Optional[str] = None,  # 기간 필터 시작 (YYYY-MM)
    strength_end: Optional[str] = None,    # 기간 필터 종료 (YYYY-MM)
):
    """선수 프로필 페이지 (fencingtracker 스타일)

    Args:
        player_name: 선수 이름 또는 선수 ID (KOP00000 형식)
        id: 선수 ID (동명이인 구분용, Optional)
        team: 소속팀 (동명이인 구분용, Optional)
        strength_start: 단계별 승률 필터 시작 기간 (YYYY-MM 형식, Optional)
        strength_end: 단계별 승률 필터 종료 기간 (YYYY-MM 형식, Optional)
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

    # History 섹션용 상세 매치 데이터 추가
    enriched_records = enrich_records_with_match_details(sorted_records, player_name)

    # 상대 전적 계산 (동명이인 구분: profile_teams 전달)
    # has_disambiguation이 True면 항상 필터링 (records 필터링과 동일 조건)
    h2h_profile_teams = set(identity_profile.teams) if identity_profile and (id or profile_identified_by_team or has_disambiguation) else None
    head_to_head = calculate_head_to_head(player_name, records, h2h_profile_teams)

    # 경기 통계
    bout_stats = {"total": 0, "wins": 0, "losses": 0, "win_rate": 0}
    stage_stats = {
        "pool_wins": 0, "pool_losses": 0, "pool_rate": 0,
        "de_wins": 0, "de_losses": 0, "de_rate": 0,
        "final_wins": 0, "final_losses": 0, "final_rate": 0
    }

    # 단계별 승률 (Stage-wise win rate)
    round_stats = {
        "pool": {"wins": 0, "losses": 0, "rate": 0},
        "t32_and_below": {"wins": 0, "losses": 0, "rate": 0},  # 32강 이하 (~32강)
        "t16": {"wins": 0, "losses": 0, "rate": 0},  # 16강
        "t8": {"wins": 0, "losses": 0, "rate": 0},   # 8강
        "semifinal": {"wins": 0, "losses": 0, "rate": 0},  # 4강 (준결승)
        "final": {"wins": 0, "losses": 0, "rate": 0}  # 결승
    }

    # 라운드 이름 → 카테고리 매핑
    def get_round_category(round_name: str) -> str:
        if not round_name:
            return "t32_and_below"
        # 정확한 라운드 매칭 (substring 충돌 방지: "64강"에 "4강"이 포함되는 문제)
        # 숫자+강 패턴 추출로 정확한 라운드 식별
        num_match = re.search(r'(\d+)강', round_name)
        if num_match:
            round_num = int(num_match.group(1))
            if round_num == 4:
                return "semifinal"
            elif round_num == 8:
                return "t8"
            elif round_num == 16:
                return "t16"
            else:
                return "t32_and_below"  # 32강, 64강, 128강, 256강
        # 숫자+강 패턴이 아닌 경우 키워드 매칭
        if "결승" in round_name and "준결승" not in round_name:
            return "final"
        elif "준결승" in round_name:
            return "semifinal"
        else:
            return "t32_and_below"

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
            except (ValueError, TypeError, IndexError):
                pass

    # 기간 필터링: strength_start/strength_end가 주어진 경우 해당 기간 기록만 필터링
    def is_in_date_range(record_date: str, start: str, end: str) -> bool:
        """날짜가 기간 내에 있는지 확인 (YYYY-MM-DD 또는 YYYY-MM 형식 지원)"""
        if not record_date:
            return True  # 날짜 없으면 포함
        try:
            # record_date: YYYY-MM-DD 형식
            rec_ym = record_date[:7]  # YYYY-MM
            return start <= rec_ym <= end
        except (TypeError, ValueError):
            return True

    # 기간 필터링 적용된 enriched_records
    if strength_start and strength_end:
        strength_filtered_records = [
            r for r in enriched_records
            if is_in_date_range(r.get("competition_date", ""), strength_start, strength_end)
        ]
    else:
        strength_filtered_records = enriched_records

    # enriched_records에서 단계별 통계 추출 헬퍼
    def _compute_round_stats_from_records(target_records, de_phase_filter=None):
        """주어진 records에서 라운드별 승/패 통계를 계산

        Args:
            target_records: enriched record 리스트
            de_phase_filter: None=전체, "main"=본선DE만, "qualifying"=예선DE만
        """
        rs = {
            "pool": {"wins": 0, "losses": 0, "rate": 0},
            "t32_and_below": {"wins": 0, "losses": 0, "rate": 0},
            "t16": {"wins": 0, "losses": 0, "rate": 0},
            "t8": {"wins": 0, "losses": 0, "rate": 0},
            "semifinal": {"wins": 0, "losses": 0, "rate": 0},
            "final": {"wins": 0, "losses": 0, "rate": 0}
        }
        for r in target_records:
            for bout in r.get("pool_bouts", []):
                if bout.get("result") == "V":
                    rs["pool"]["wins"] += 1
                elif bout.get("result") == "D":
                    rs["pool"]["losses"] += 1
            for bout in r.get("tournament_bouts", []):
                if bout.get("is_bye"):
                    continue
                # dual_de 예선(qualifying) 경기는 본선 통계에서 제외
                if de_phase_filter and bout.get("de_phase", "main") != de_phase_filter:
                    continue
                category = get_round_category(bout.get("round_name", ""))
                if bout.get("result") == "V":
                    rs[category]["wins"] += 1
                elif bout.get("result") == "D":
                    rs[category]["losses"] += 1
        for cat in rs:
            total = rs[cat]["wins"] + rs[cat]["losses"]
            if total > 0:
                rs[cat]["rate"] = round(rs[cat]["wins"] / total * 100, 1)
        return rs

    # Strength 탭용: 기간 필터링 적용된 round_stats (전체 또는 사용자 지정 기간)
    round_stats = _compute_round_stats_from_records(strength_filtered_records, de_phase_filter="main")

    # Pool 통계가 없으면 stage_stats에서 가져오기
    if round_stats["pool"]["wins"] == 0 and round_stats["pool"]["losses"] == 0:
        round_stats["pool"]["wins"] = stage_stats["pool_wins"]
        round_stats["pool"]["losses"] = stage_stats["pool_losses"]
        pool_total = round_stats["pool"]["wins"] + round_stats["pool"]["losses"]
        if pool_total > 0:
            round_stats["pool"]["rate"] = round(round_stats["pool"]["wins"] / pool_total * 100, 1)

    # Summary 탭용: 최근 기간 round_stats (직전년도 + 올해)
    from datetime import date as _date_cls
    _current_year = _date_cls.today().year
    _prev_year = _current_year - 1
    recent_records = [
        r for r in enriched_records
        if r.get("year") and int(r.get("year", 0)) >= _prev_year
    ]
    recent_round_stats = _compute_round_stats_from_records(recent_records, de_phase_filter="main")
    recent_period_label = f"{_prev_year}~{_current_year}"
    recent_event_count = len(recent_records)

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

    # Summary 탭용 경량 records_summary (메달 클릭 시 대회 목록 표시용)
    records_summary = []
    for r in sorted_records:
        records_summary.append({
            "year": r.get("year"),
            "rank": r.get("rank"),
            "competition_name": r.get("competition_name", ""),
            "event_name": r.get("event_name", ""),
            "weapon": r.get("weapon", ""),
            "event_cd": r.get("event_cd", ""),
            "sub_event_cd": r.get("sub_event_cd", ""),
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
        "available_years": sorted(years),  # 오름차순 (필터 드롭다운용)
        "filter_start_year": strength_start[:4] if strength_start else None,
        "filter_end_year": strength_end[:4] if strength_end else None,
        "weapons": weapons,
        "ratings": ratings,
        "rating_history": rating_history[:10],
        "podium_by_season": dict(sorted(podium_by_season.items(), reverse=True)),
        "stats": stats,
        "total_records": len(records),
        "records": enriched_records,  # 상세 매치 데이터 포함된 records
        "head_to_head": head_to_head,  # 모든 상대 전적 표시
        "tough_opponents": sorted(
            [o for o in head_to_head if (o["wins"] + o["losses"]) >= 2 and o["win_rate"] < 50],
            key=lambda x: (x["win_rate"], -(x["wins"] + x["losses"]))
        )[:3],  # 2회 이상 대전 & 승률 50% 미만, 승률 낮은 순 → 대전 횟수 많은 순
        "bout_stats": bout_stats,
        "stage_stats": stage_stats,
        "round_stats": round_stats,  # 단계별 승률 - Strength 탭용 (기간 필터 또는 전체)
        "recent_round_stats": recent_round_stats,  # Summary 탭용 (직전년도+올해)
        "recent_period_label": recent_period_label,  # "2025~2026"
        "recent_event_count": recent_event_count,  # 최근 기간 대회 수
        "records_summary": records_summary,  # Summary 탭 메달 클릭용 경량 데이터
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

    # 접근 등급 확인
    access_level, _ = await get_access_level(request)

    context = {
        "request": request,
        "player": player_data,
        "today": date.today().strftime("%b %d, %Y"),
        "title": f"{player_name} - Korean Fencing Tracker",
        "access_level": access_level,
        "login_url": "/auth/login",
        "verify_url": "/auth/verification",
        **get_i18n_template_context(request)
    }
    return templates.TemplateResponse("player_profile.html", context)


@app.get("/{lang}/player/{player_name}", response_class=HTMLResponse)
async def player_page_i18n(
    request: Request,
    lang: str,
    player_name: str,
    id: Optional[str] = None,
    team: Optional[str] = None,
    strength_start: Optional[str] = None,
    strength_end: Optional[str] = None,
):
    """Language-prefixed player profile page - delegates to main player_page"""
    if lang not in ["ko", "en"]:
        raise HTTPException(status_code=404, detail="Not Found")
    return await player_page(request, player_name, id, team, strength_start, strength_end)


def transform_de_bracket(event_data: Dict) -> Dict:
    """DE bracket 데이터를 템플릿 호환 형식으로 변환 (bracket_utils 사용)"""
    de_bracket = event_data.get("de_bracket", {})
    if not de_bracket:
        return event_data

    # bracket_utils로 정규화 (Dual DE 형식도 자동 감지)
    normalized = normalize_bracket_data(de_bracket)

    # NormalizedBracket이 None인 경우 원본 반환
    if normalized is None:
        return event_data

    # Dual DE 형식인 경우 dict로 변환하여 Jinja2 템플릿 호환성 확보
    if hasattr(normalized, 'format') and normalized.format == 'dual_de':
        # dataclass를 dict로 변환 (Jinja2에서 속성 접근 가능하도록)
        normalized_dict = normalized.to_dict()
        event_data["normalized_bracket"] = normalized_dict
        print(f"[DEBUG transform_de_bracket] Dual DE converted to dict: format={normalized_dict.get('format')}")
        return event_data

    # 단일 DE: NormalizedBracket 객체를 event_data에 추가
    event_data["normalized_bracket"] = normalized

    # 기존 템플릿 호환성을 위한 변환 (레거시 지원 - 단일 DE만)
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

            # 언어 감지: request.state에서 가져옴 (미들웨어에서 설정)
            lang = getattr(request.state, 'lang', DEFAULT_LANGUAGE)
            return templates.TemplateResponse("event_result.html", {
                "request": request,
                "competition": comp,
                "event": selected_event,
                **get_i18n_template_context(request, lang)
            })

    # 언어 감지: request.state에서 가져옴 (미들웨어에서 설정)
    lang = getattr(request.state, 'lang', DEFAULT_LANGUAGE)
    return templates.TemplateResponse("competition.html", {
        "request": request,
        "competition": comp,
        **get_i18n_template_context(request, lang)
    })


@app.get("/{lang}/competition/{event_cd}", response_class=HTMLResponse)
async def competition_detail_page_i18n(request: Request, lang: str, event_cd: str, event: Optional[str] = None):
    """Language-prefixed competition detail page - delegates to main competition_detail_page"""
    if lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=404, detail="Not Found")
    return await competition_detail_page(request, event_cd, event)


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = ""):
    """검색 페이지"""
    return templates.TemplateResponse("search.html", {
        "request": request,
        "query": q,
        **get_i18n_template_context(request, "ko")
    })


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """AI 채팅 페이지"""
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "title": "AI 검색",
        **get_i18n_template_context(request, "ko")
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
    request: Request,
    player_name: str,
    team: str = Query(..., description="팀 이름 (필수 - 동명이인 구분)"),
    lang: str = Query("ko", description="언어 코드 (ko/en)")
):
    """선수 분석 데이터 (FencingLab) - 이름+팀으로 동명이인 구분"""
    access_level, _ = await get_access_level(request)
    if not can_access_fencinglab(access_level):
        raise HTTPException(status_code=403, detail="선수인증이 필요합니다")

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
        "player_name": player_name,
        **get_i18n_template_context(request, "ko")
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
        "user_role": selected_role,
        **get_i18n_template_context(request, "ko")
    })


@app.get("/club/checkin", response_class=HTMLResponse)
async def club_checkin_page(request: Request):
    """출석 체크인 페이지 (학생용 모바일 최적화)"""
    return templates.TemplateResponse("club/checkin.html", {
        "request": request,
        "title": "출석 체크인 - Korean Fencing Tracker",
        **get_i18n_template_context(request, "ko")
    })


@app.get("/club/accounting", response_class=HTMLResponse)
async def club_accounting_page(request: Request):
    """회계관리 페이지 (owner/사장 전용)"""
    return templates.TemplateResponse("club/accounting.html", {
        "request": request,
        "title": "회계관리 - Korean Fencing Tracker",
        **get_i18n_template_context(request, "ko")
    })


# ==================== 예정/진행 대회 API ====================

@app.get("/api/competitions/upcoming")
async def get_upcoming_competitions(
    days: int = Query(30, ge=1, le=90, description="조회할 일수 (기본 30일)"),
    limit: int = Query(10, ge=1, le=50),
    lang: str = Query("ko", description="언어 코드")
):
    """다가오는 예정 대회 조회

    Returns:
        upcoming: 예정 대회 목록 (날짜순)
        total: 전체 예정 대회 수
    """
    from datetime import date, timedelta
    from app.translation_service import VERIFIED_COMPETITION_MAPPINGS

    competitions = get_competitions()
    today = date.today()
    end_date = today + timedelta(days=days)
    upcoming = []

    for comp in competitions:
        comp_info = comp.get("competition", {})
        start_date_str = comp_info.get("start_date", "")
        if not start_date_str:
            continue

        try:
            start_date = date.fromisoformat(start_date_str[:10])
            days_until = (start_date - today).days

            # 대회명 번역
            comp_name = comp_info.get("name", "")
            if lang != "ko" and comp_name in VERIFIED_COMPETITION_MAPPINGS:
                comp_name = VERIFIED_COMPETITION_MAPPINGS[comp_name]

            # 오늘 이후 ~ days일 이내
            if 0 <= days_until <= days:
                upcoming.append({
                    "event_cd": comp_info.get("event_cd"),
                    "comp_idx": comp_info.get("comp_idx"),
                    "name": comp_name,
                    "start_date": comp_info.get("start_date"),
                    "end_date": comp_info.get("end_date"),
                    "venue": comp_info.get("venue"),
                    "status": comp_info.get("status"),
                    "days_until": days_until,
                    "event_count": len(comp.get("events", []))
                })
        except (ValueError, TypeError):
            continue

    upcoming.sort(key=lambda x: x.get("days_until", 999))
    return {
        "upcoming": upcoming[:limit],
        "total": len(upcoming),
        "query_days": days,
        "today": today.isoformat()
    }


@app.get("/api/competitions/ongoing")
async def get_ongoing_competitions():
    """현재 진행 중인 대회 조회

    Returns:
        ongoing: 진행 중인 대회 목록
        total: 진행 중인 대회 수
    """
    from datetime import date

    competitions = get_competitions()
    today = date.today()
    ongoing = []

    for comp in competitions:
        comp_info = comp.get("competition", {})
        start_date_str = comp_info.get("start_date", "")
        end_date_str = comp_info.get("end_date", "")

        if not start_date_str:
            continue

        try:
            start_date = date.fromisoformat(start_date_str[:10])
            end_date = date.fromisoformat(end_date_str[:10]) if end_date_str else start_date

            # 오늘이 시작일과 종료일 사이에 있으면 진행 중
            if start_date <= today <= end_date:
                # 진행 일수 계산
                day_number = (today - start_date).days + 1
                total_days = (end_date - start_date).days + 1

                ongoing.append({
                    "event_cd": comp_info.get("event_cd"),
                    "comp_idx": comp_info.get("comp_idx"),
                    "name": comp_info.get("name"),
                    "start_date": comp_info.get("start_date"),
                    "end_date": comp_info.get("end_date"),
                    "venue": comp_info.get("venue"),
                    "day_number": day_number,
                    "total_days": total_days,
                    "event_count": len(comp.get("events", []))
                })
        except (ValueError, TypeError):
            continue

    return {
        "ongoing": ongoing,
        "total": len(ongoing),
        "today": today.isoformat()
    }


@app.get("/api/competitions/live")
async def get_live_competitions(lang: str = "ko"):
    """실시간 대회 정보 (진행 중 + 예정)

    프론트엔드 NOW 배너용 통합 API
    """
    from datetime import date, timedelta
    from app.translation_service import VERIFIED_COMPETITION_MAPPINGS

    competitions = get_competitions()
    today = date.today()
    result = {
        "ongoing": [],
        "upcoming": [],  # 7일 이내 예정
        "today": today.isoformat()
    }

    for comp in competitions:
        comp_info = comp.get("competition", {})
        start_date_str = comp_info.get("start_date", "")
        end_date_str = comp_info.get("end_date", "")

        if not start_date_str:
            continue

        try:
            start_date = date.fromisoformat(start_date_str[:10])
            end_date = date.fromisoformat(end_date_str[:10]) if end_date_str else start_date
            days_until = (start_date - today).days

            # 대회명 번역
            comp_name = comp_info.get("name", "")
            if lang != "ko" and comp_name in VERIFIED_COMPETITION_MAPPINGS:
                comp_name = VERIFIED_COMPETITION_MAPPINGS[comp_name]

            comp_data = {
                "event_cd": comp_info.get("event_cd"),
                "comp_idx": comp_info.get("comp_idx"),
                "name": comp_name,
                "start_date": comp_info.get("start_date"),
                "end_date": comp_info.get("end_date"),
                "venue": comp_info.get("venue"),
                "event_count": len(comp.get("events", []))
            }

            # 진행 중
            if start_date <= today <= end_date:
                comp_data["status"] = "live"
                comp_data["day_number"] = (today - start_date).days + 1
                comp_data["total_days"] = (end_date - start_date).days + 1
                result["ongoing"].append(comp_data)
            # 7일 이내 예정
            elif 0 < days_until <= 7:
                comp_data["status"] = "upcoming"
                comp_data["days_until"] = days_until
                result["upcoming"].append(comp_data)

        except (ValueError, TypeError):
            continue

    # 예정 대회는 날짜순 정렬
    result["upcoming"].sort(key=lambda x: x.get("days_until", 999))

    return result


# ==================== 데이터 새로고침 API ====================

@app.post("/api/refresh-data")
async def refresh_data_cache():
    """서버 데이터 캐시 새로고침 API

    스크래핑/선수 데이터 업데이트 완료 후 호출하여 DB의 최신 데이터를 서버 메모리에 로드
    identity_resolver도 재구축하여 current_team 등이 올바르게 반영됨
    """
    try:
        logger.info("🔄 데이터 캐시 새로고침 시작...")

        # 1. Supabase에서 최신 데이터 로드
        success = load_data_from_supabase()
        if not success:
            return {"success": False, "message": "데이터 로드 실패"}

        # 2. 선수 인덱스 및 캐시 재구축
        build_player_index()
        build_competition_player_cache()

        # 3. identity_resolver 재구축 (핵심 - current_team 올바르게 반영)
        build_identity_resolver()

        logger.info("✅ 데이터 캐시 및 identity_resolver 새로고침 완료")
        return {
            "success": True,
            "message": "데이터 캐시가 새로고침되었습니다 (identity_resolver 포함)",
            "competitions": len(_data_cache.get("competitions", [])),
            "events": len(_data_cache.get("events", [])),
            "profiles": len(_identity_resolver.profiles) if _identity_resolver else 0
        }
    except Exception as e:
        logger.error(f"데이터 새로고침 오류: {e}")
        return {"success": False, "error": str(e)}


# ==================== 스케줄러 API ====================

@app.get("/api/scheduler/status")
async def get_scheduler_status():
    """스케줄러 상태 조회 API"""
    if not SCHEDULER_AVAILABLE:
        return {"error": "스케줄러를 사용할 수 없습니다", "available": False}

    if not ENABLE_SCHEDULER:
        return {
            "available": True,
            "enabled": False,
            "message": "스케줄러가 비활성화되어 있습니다. ENABLE_SCHEDULER=true로 활성화하세요."
        }

    try:
        scheduler = get_scheduler()
        status = scheduler.get_status()
        return {
            "available": True,
            "enabled": True,
            **status
        }
    except Exception as e:
        return {"error": str(e), "available": True, "enabled": True}


@app.post("/api/scheduler/run")
async def run_scheduler_now(task_type: str = "detect"):
    """스케줄러 즉시 실행 API

    Args:
        task_type:
            - "detect": 대회 공고 감지 (새 대회 찾기)
            - "scrape": 이벤트 기반 스크래핑 (진행 중 대회)
            - "final": 최종 결과 수집 (종료된 대회)
            - "all": 전체 실행
    """
    if not SCHEDULER_AVAILABLE or not ENABLE_SCHEDULER:
        raise HTTPException(status_code=503, detail="스케줄러가 활성화되지 않았습니다")

    try:
        scheduler = get_scheduler()
        result = await scheduler.run_now(task_type)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 데이터 무결성 검증 API ====================

@app.get("/api/admin/validate")
async def api_validate_data():
    """전체 데이터 무결성 검증"""
    from app.data_validator import DataValidator
    validator = DataValidator(get_competitions())
    issues = validator.validate_all()

    errors = [i.to_dict() for i in issues if i.severity == "ERROR"]
    warnings = [i.to_dict() for i in issues if i.severity == "WARNING"]

    # 규칙별 통계
    by_rule = {}
    for issue in issues:
        by_rule[issue.rule_id] = by_rule.get(issue.rule_id, 0) + 1

    return {
        "total_issues": len(issues),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "by_rule": by_rule,
        "errors": errors[:100],      # 최대 100건
        "warnings": warnings[:100],
    }


@app.get("/api/admin/validate/{player_name}")
async def api_validate_player(player_name: str):
    """특정 선수 데이터 검증"""
    from app.data_validator import DataValidator
    validator = DataValidator(get_competitions())
    issues = validator.validate_player(player_name)

    return {
        "player": player_name,
        "total_issues": len(issues),
        "issues": [i.to_dict() for i in issues],
    }


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
