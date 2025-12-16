"""
데이터 모델 정의 (Pydantic)
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import date, datetime
from enum import Enum


class CompetitionStatus(str, Enum):
    """대회 상태"""
    SCHEDULED = "예정"
    IN_PROGRESS = "진행중"
    COMPLETED = "종료"
    UNKNOWN = "unknown"


class Weapon(str, Enum):
    """무기 종류"""
    FOIL = "플뢰레"
    EPEE = "에페"
    SABRE = "사브르"
    UNKNOWN = "unknown"


class Gender(str, Enum):
    """성별"""
    MALE = "남자"
    FEMALE = "여자"
    MIXED = "혼성"
    UNKNOWN = "unknown"


class MatchStatus(str, Enum):
    """경기 결과 상태"""
    VICTORY = "V"      # 정상 승리
    ABANDON = "A"      # 기권
    FORFEIT = "F"      # 기권패
    EXCLUSION = "E"    # 실격
    PENALTY = "P"      # 페널티
    UNKNOWN = "unknown"


class Competition(BaseModel):
    """대회 정보"""
    comp_idx: str = Field(..., description="대회 고유 ID")
    comp_name: str = Field(..., description="대회명")
    start_date: Optional[date] = Field(None, description="시작일")
    end_date: Optional[date] = Field(None, description="종료일")
    venue: Optional[str] = Field(None, description="개최지")
    status: CompetitionStatus = Field(default=CompetitionStatus.UNKNOWN, description="대회 상태")
    raw_data: Optional[Dict[str, Any]] = Field(None, description="원본 데이터")

    class Config:
        use_enum_values = True


class Event(BaseModel):
    """종목 정보"""
    competition_id: Optional[int] = Field(None, description="대회 DB ID")
    event_cd: str = Field(..., description="종목 코드")
    sub_event_cd: Optional[str] = Field(None, description="세부 종목 코드")
    event_name: Optional[str] = Field(None, description="종목명")
    weapon: Weapon = Field(default=Weapon.UNKNOWN, description="무기")
    gender: Gender = Field(default=Gender.UNKNOWN, description="성별")
    category: Optional[str] = Field(None, description="개인/단체")
    age_group: Optional[str] = Field(None, description="연령대")
    raw_data: Optional[Dict[str, Any]] = Field(None, description="원본 데이터")

    class Config:
        use_enum_values = True


class Player(BaseModel):
    """선수 정보"""
    player_name: str = Field(..., description="선수명")
    team_name: Optional[str] = Field(None, description="소속팀")
    birth_year: Optional[int] = Field(None, description="출생년도")
    nationality: str = Field(default="KOR", description="국적")
    raw_data: Optional[Dict[str, Any]] = Field(None, description="원본 데이터")


class Match(BaseModel):
    """경기 결과"""
    event_id: Optional[int] = Field(None, description="종목 DB ID")
    round_name: Optional[str] = Field(None, description="라운드명 (8강, 4강 등)")
    group_name: Optional[str] = Field(None, description="조 이름")
    match_number: Optional[int] = Field(None, description="경기 번호")

    player1_id: Optional[int] = Field(None, description="선수1 DB ID")
    player1_name: Optional[str] = Field(None, description="선수1 이름")
    player1_score: Optional[int] = Field(None, description="선수1 점수")

    player2_id: Optional[int] = Field(None, description="선수2 DB ID")
    player2_name: Optional[str] = Field(None, description="선수2 이름")
    player2_score: Optional[int] = Field(None, description="선수2 점수")

    winner_id: Optional[int] = Field(None, description="승자 DB ID")
    match_status: MatchStatus = Field(default=MatchStatus.UNKNOWN, description="경기 상태")
    match_time: Optional[datetime] = Field(None, description="경기 시간")
    raw_data: Optional[Dict[str, Any]] = Field(None, description="원본 데이터")

    class Config:
        use_enum_values = True


class Ranking(BaseModel):
    """최종 순위"""
    event_id: Optional[int] = Field(None, description="종목 DB ID")
    player_id: Optional[int] = Field(None, description="선수 DB ID")
    player_name: Optional[str] = Field(None, description="선수명")
    team_name: Optional[str] = Field(None, description="소속팀")
    rank_position: int = Field(..., description="순위")
    match_count: int = Field(default=0, description="경기 수")
    win_count: int = Field(default=0, description="승리 수")
    loss_count: int = Field(default=0, description="패배 수")
    points: int = Field(default=0, description="포인트")
    raw_data: Optional[Dict[str, Any]] = Field(None, description="원본 데이터")


class CompetitionListResponse(BaseModel):
    """대회 목록 응답"""
    competitions: List[Competition] = Field(default_factory=list)
    total_count: int = Field(default=0)
    current_page: int = Field(default=1)
    total_pages: int = Field(default=1)


class EventListResponse(BaseModel):
    """종목 목록 응답"""
    events: List[Event] = Field(default_factory=list)
    competition_id: Optional[int] = None


class MatchListResponse(BaseModel):
    """경기 결과 목록 응답"""
    matches: List[Match] = Field(default_factory=list)
    event_id: Optional[int] = None


class RankingListResponse(BaseModel):
    """순위 목록 응답"""
    rankings: List[Ranking] = Field(default_factory=list)
    event_id: Optional[int] = None


class ScrapeResult(BaseModel):
    """스크래핑 결과"""
    success: bool = Field(default=True)
    competitions_count: int = Field(default=0)
    events_count: int = Field(default=0)
    matches_count: int = Field(default=0)
    rankings_count: int = Field(default=0)
    players_count: int = Field(default=0)
    errors: List[str] = Field(default_factory=list)
    duration_seconds: float = Field(default=0.0)
