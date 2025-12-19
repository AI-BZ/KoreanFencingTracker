"""
스크래퍼 설정
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()


class ScraperConfig(BaseSettings):
    """스크래퍼 설정"""

    # 대한펜싱협회 웹사이트
    base_url: str = "https://fencing.sports.or.kr"

    # 요청 설정
    scrape_delay: float = Field(default=1.0, description="요청 간 딜레이 (초)")
    max_concurrent_requests: int = Field(default=3, description="최대 동시 요청 수")
    max_retries: int = Field(default=3, description="최대 재시도 횟수")
    request_timeout: int = Field(default=30, description="요청 타임아웃 (초)")

    # User-Agent
    user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

    # 페이지네이션
    items_per_page: int = 10

    class Config:
        env_prefix = ""
        case_sensitive = False


class SupabaseConfig(BaseSettings):
    """Supabase 설정"""

    supabase_url: str = Field(default="", description="Supabase Project URL")
    supabase_key: str = Field(default="", description="Supabase anon key")

    class Config:
        env_prefix = ""
        case_sensitive = False


class SchedulerConfig(BaseSettings):
    """스케줄러 설정"""

    daily_sync_hour: int = Field(default=6, description="매일 전체 동기화 시간")
    hourly_update_enabled: bool = Field(default=True, description="시간별 업데이트 활성화")

    class Config:
        env_prefix = ""
        case_sensitive = False


class IksanConfig(BaseSettings):
    """익산 국제대회 스텔스 스크래핑 설정"""

    # 스텔스 딜레이 (봇 탐지 회피)
    stealth_delay_min: float = Field(default=5.0, description="최소 딜레이 (초)")
    stealth_delay_max: float = Field(default=10.0, description="최대 딜레이 (초)")
    page_load_delay: float = Field(default=3.0, description="페이지 로드 대기 (초)")

    # 대회 코드 (KFF 사이트)
    comp_u17_u20: str = Field(default="COMPM00666", description="U17/U20 대회 코드")
    comp_u13_u11_u9: str = Field(default="COMPM00673", description="U13/U11/U9 대회 코드")

    # 스케줄 설정
    update_interval_minutes: int = Field(default=45, description="업데이트 체크 간격 (분)")
    active_hours_start: int = Field(default=8, description="대회 시작 시간")
    active_hours_end: int = Field(default=20, description="대회 종료 시간")

    # 대회 기간
    u17_u20_start: str = Field(default="2025-12-16", description="U17/U20 시작일")
    u17_u20_end: str = Field(default="2025-12-21", description="U17/U20 종료일")
    u13_start: str = Field(default="2025-12-20", description="U13/U11/U9 시작일")
    u13_end: str = Field(default="2025-12-21", description="U13/U11/U9 종료일")

    class Config:
        env_prefix = "IKSAN_"
        case_sensitive = False


# 전역 설정 인스턴스
scraper_config = ScraperConfig()
supabase_config = SupabaseConfig()
scheduler_config = SchedulerConfig()
iksan_config = IksanConfig()


# API 엔드포인트 정의
class Endpoints:
    """대한펜싱협회 API 엔드포인트"""

    # 대회 관련
    COMP_LIST = "/game/compList"
    COMP_LIST_VIEW = "/game/compListView"
    SUB_EVENT_LIST_CNT = "/game/subEventListCnt"

    # 경기 결과 관련
    TABLEAU_GRP_DTL_LIST = "/game/getTableauGrpDtlList"
    MATCH_DTL_INFO_LIST = "/game/getMatchDtlInfoList"
    ENTER_PLAYER_LIST = "/game/enterPlayerJsonSelectList"
    FINISH_RANK = "/game/finishRank"

    # 코드 조회
    SIBLINGS_JSON = "/code/siblingsJson.do"
