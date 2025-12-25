"""
데이터 파이프라인 스키마 정의

Pydantic 모델을 사용하여 데이터 유효성 검사 및 타입 강제
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import date, datetime
from enum import Enum
import re


class ValidationSeverity(str, Enum):
    """검증 오류 심각도"""
    CRITICAL = "critical"   # 저장 불가
    HIGH = "high"           # 저장 불가, 수동 검토 필요
    MEDIUM = "medium"       # 저장 가능, 경고 표시
    LOW = "low"             # 저장 가능, 로그만
    INFO = "info"           # 정보성


class ValidationError(BaseModel):
    """검증 오류"""
    error_type: str = Field(..., description="오류 유형")
    severity: ValidationSeverity = Field(..., description="심각도")
    message: str = Field(..., description="오류 메시지")
    field: Optional[str] = Field(None, description="관련 필드")
    value: Optional[Any] = Field(None, description="문제가 된 값")
    suggestion: Optional[str] = Field(None, description="해결 제안")


class ValidationResult(BaseModel):
    """검증 결과"""
    is_valid: bool = Field(default=True, description="최종 유효성")
    errors: List[ValidationError] = Field(default_factory=list)
    warnings: List[ValidationError] = Field(default_factory=list)
    pass_rate: float = Field(default=1.0, description="통과율 (0-1)")
    validated_at: datetime = Field(default_factory=datetime.now)
    
    @property
    def has_critical_errors(self) -> bool:
        return any(e.severity in [ValidationSeverity.CRITICAL, ValidationSeverity.HIGH] for e in self.errors)
    
    @property
    def can_save(self) -> bool:
        """저장 가능 여부"""
        return not self.has_critical_errors


# ==================== 무기/성별/상태 Enum ====================

class Weapon(str, Enum):
    """무기 종류"""
    FOIL = "플뢰레"
    EPEE = "에페"
    SABRE = "사브르"
    UNKNOWN = "unknown"
    
    @classmethod
    def from_string(cls, value: str) -> "Weapon":
        """문자열에서 무기 타입 추출"""
        value_lower = value.lower()
        if "플" in value or "foil" in value_lower or "플러레" in value:
            return cls.FOIL
        elif "에" in value or "epee" in value_lower or "에뻬" in value:
            return cls.EPEE
        elif "사" in value or "sabre" in value_lower or "사브르" in value:
            return cls.SABRE
        return cls.UNKNOWN


class Gender(str, Enum):
    """성별"""
    MALE = "남자"
    FEMALE = "여자"
    MIXED = "혼성"
    UNKNOWN = "unknown"
    
    @classmethod
    def from_string(cls, value: str) -> "Gender":
        """문자열에서 성별 추출"""
        if "남" in value:
            return cls.MALE
        elif "여" in value:
            return cls.FEMALE
        elif "혼" in value:
            return cls.MIXED
        return cls.UNKNOWN


class AgeGroup(str, Enum):
    """연령대"""
    ELEMENTARY_1_2 = "초등부(1-2학년)"
    ELEMENTARY_3_4 = "초등부(3-4학년)"
    ELEMENTARY_5_6 = "초등부(5-6학년)"
    MIDDLE_SCHOOL = "중등부"
    HIGH_SCHOOL = "고등부"
    UNIVERSITY = "대학부"
    GENERAL = "일반부"
    MASTERS = "시니어"
    U13 = "U13"
    U15 = "U15"
    U17 = "U17"
    U20 = "U20"
    UNKNOWN = "unknown"
    
    @classmethod
    def from_string(cls, value: str) -> "AgeGroup":
        """문자열에서 연령대 추출"""
        if "초등" in value:
            if "1-2" in value or "1,2" in value:
                return cls.ELEMENTARY_1_2
            elif "3-4" in value or "3,4" in value:
                return cls.ELEMENTARY_3_4
            elif "5-6" in value or "5,6" in value:
                return cls.ELEMENTARY_5_6
            return cls.ELEMENTARY_5_6  # 기본값
        elif "중등" in value or "중학" in value or "남중" in value or "여중" in value:
            return cls.MIDDLE_SCHOOL
        elif "고등" in value or "고교" in value or "남고" in value or "여고" in value:
            return cls.HIGH_SCHOOL
        elif "대학" in value or "남대" in value or "여대" in value:
            return cls.UNIVERSITY
        elif "일반" in value or "실업" in value or "남일" in value or "여일" in value:
            return cls.GENERAL
        elif "시니어" in value or "마스터" in value:
            return cls.MASTERS
        elif "U13" in value or "13세" in value:
            return cls.U13
        elif "U15" in value or "15세" in value:
            return cls.U15
        elif "U17" in value or "17세" in value:
            return cls.U17
        elif "U20" in value or "20세" in value:
            return cls.U20
        return cls.UNKNOWN


class MatchResult(str, Enum):
    """경기 결과"""
    VICTORY = "V"
    DEFEAT = "D"
    ABANDON = "A"       # 기권
    FORFEIT = "F"       # 기권패
    EXCLUSION = "E"     # 실격
    PENALTY = "P"       # 페널티
    UNKNOWN = "unknown"


# ==================== 핵심 스키마 ====================

class PlayerSchema(BaseModel):
    """선수 스키마 (강화된 검증)"""
    
    # 필수 필드
    player_name: str = Field(..., min_length=2, max_length=50, description="선수명")
    
    # 선택 필드
    player_id: Optional[str] = Field(None, description="선수 고유 ID (KOP00001 형식)")
    team_name: Optional[str] = Field(None, max_length=100, description="소속팀")
    birth_year: Optional[int] = Field(None, ge=1940, le=2020, description="출생년도")
    gender: Gender = Field(default=Gender.UNKNOWN, description="성별")
    primary_weapon: Weapon = Field(default=Weapon.UNKNOWN, description="주 무기")
    nationality: str = Field(default="KOR", max_length=3, description="국적 코드")
    
    # 메타데이터
    raw_data: Optional[Dict[str, Any]] = Field(None, description="원본 데이터")
    source_url: Optional[str] = Field(None, description="데이터 출처 URL")
    scraped_at: Optional[datetime] = Field(None, description="스크래핑 시간")
    
    @field_validator("player_name")
    @classmethod
    def validate_player_name(cls, v: str) -> str:
        """선수명 검증"""
        # 공백 정리
        v = " ".join(v.split())
        
        # 특수문자 제거 (한글, 영문, 공백만 허용)
        if not re.match(r"^[가-힣a-zA-Z\s]+$", v):
            # 괄호 안 내용은 팀명일 수 있으므로 제거
            v = re.sub(r"\([^)]*\)", "", v).strip()
        
        if len(v) < 2:
            raise ValueError("선수명은 최소 2자 이상이어야 합니다")
        
        return v
    
    @field_validator("player_id")
    @classmethod
    def validate_player_id(cls, v: Optional[str]) -> Optional[str]:
        """선수 ID 형식 검증"""
        if v is None:
            return v
        
        # KOP00001 형식 검증
        if not re.match(r"^[A-Z]{2}P\d{5}$", v):
            raise ValueError(f"선수 ID 형식이 올바르지 않습니다: {v} (예: KOP00001)")
        
        return v
    
    @field_validator("nationality")
    @classmethod
    def validate_nationality(cls, v: str) -> str:
        """국적 코드 검증"""
        return v.upper()[:3]
    
    class Config:
        use_enum_values = True


class MatchSchema(BaseModel):
    """경기 결과 스키마"""
    
    # 필수 필드
    event_id: int = Field(..., ge=1, description="종목 DB ID")
    
    # 라운드 정보
    round_name: str = Field(..., description="라운드명 (8강, 준결승 등)")
    match_number: Optional[int] = Field(None, ge=1, description="경기 번호")
    match_type: Literal["pool", "de"] = Field(default="de", description="경기 유형")
    
    # 선수 1 정보
    player1_name: str = Field(..., min_length=1, description="선수1 이름")
    player1_team: Optional[str] = Field(None, description="선수1 소속팀")
    player1_score: Optional[int] = Field(None, ge=0, le=45, description="선수1 점수")
    player1_id: Optional[int] = Field(None, description="선수1 DB ID")
    
    # 선수 2 정보
    player2_name: str = Field(..., min_length=1, description="선수2 이름")
    player2_team: Optional[str] = Field(None, description="선수2 소속팀")
    player2_score: Optional[int] = Field(None, ge=0, le=45, description="선수2 점수")
    player2_id: Optional[int] = Field(None, description="선수2 DB ID")
    
    # 결과 정보
    winner_name: Optional[str] = Field(None, description="승자 이름")
    winner_id: Optional[int] = Field(None, description="승자 DB ID")
    match_status: MatchResult = Field(default=MatchResult.UNKNOWN, description="경기 상태")
    
    # 메타데이터
    raw_data: Optional[Dict[str, Any]] = Field(None, description="원본 데이터")
    validated_at: Optional[datetime] = Field(None, description="검증 시간")
    
    @field_validator("round_name")
    @classmethod
    def validate_round_name(cls, v: str) -> str:
        """라운드명 정규화"""
        # 일반적인 라운드명 매핑
        round_mapping = {
            "64강전": "64강",
            "32강전": "32강",
            "16강전": "16강",
            "8강전": "8강",
            "4강전": "준결승",
            "반결승": "준결승",
            "결승전": "결승",
            "3-4위전": "3위결정전",
        }
        return round_mapping.get(v, v)
    
    @model_validator(mode="after")
    def validate_match_logic(self) -> "MatchSchema":
        """경기 논리 검증"""
        # 점수가 있으면 승자 결정
        if self.player1_score is not None and self.player2_score is not None:
            if self.player1_score > self.player2_score:
                if self.winner_name is None:
                    self.winner_name = self.player1_name
            elif self.player2_score > self.player1_score:
                if self.winner_name is None:
                    self.winner_name = self.player2_name
        
        return self
    
    class Config:
        use_enum_values = True


class EventSchema(BaseModel):
    """종목 스키마"""
    
    # 필수 필드
    competition_id: int = Field(..., ge=1, description="대회 DB ID")
    event_cd: str = Field(..., min_length=1, description="종목 코드")
    event_name: str = Field(..., min_length=1, description="종목명")
    
    # 분류 정보
    weapon: Weapon = Field(default=Weapon.UNKNOWN, description="무기")
    gender: Gender = Field(default=Gender.UNKNOWN, description="성별")
    age_group: AgeGroup = Field(default=AgeGroup.UNKNOWN, description="연령대")
    event_type: Literal["individual", "team"] = Field(default="individual", description="개인/단체")
    
    # 추가 정보
    sub_event_cd: Optional[str] = Field(None, description="세부 종목 코드")
    total_participants: int = Field(default=0, ge=0, description="총 참가자 수")
    
    # DE 대진표 데이터
    de_bracket: Optional[Dict[str, Any]] = Field(None, description="DE 대진표 데이터")
    
    # 메타데이터
    raw_data: Optional[Dict[str, Any]] = Field(None, description="원본 데이터")
    
    @model_validator(mode="after")
    def extract_event_info(self) -> "EventSchema":
        """종목명에서 정보 추출"""
        name = self.event_name
        
        # 무기 추출
        if self.weapon == Weapon.UNKNOWN:
            self.weapon = Weapon.from_string(name)
        
        # 성별 추출
        if self.gender == Gender.UNKNOWN:
            self.gender = Gender.from_string(name)
        
        # 연령대 추출
        if self.age_group == AgeGroup.UNKNOWN:
            self.age_group = AgeGroup.from_string(name)
        
        # 개인/단체 구분
        if "단)" in name or "단체" in name:
            self.event_type = "team"
        elif "개)" in name or "개인" in name:
            self.event_type = "individual"
        
        return self
    
    class Config:
        use_enum_values = True


class CompetitionSchema(BaseModel):
    """대회 스키마"""
    
    # 필수 필드
    comp_idx: str = Field(..., min_length=1, description="대회 고유 ID")
    comp_name: str = Field(..., min_length=1, description="대회명")
    
    # 일정 정보
    start_date: Optional[date] = Field(None, description="시작일")
    end_date: Optional[date] = Field(None, description="종료일")
    
    # 장소 및 상태
    venue: Optional[str] = Field(None, description="개최지")
    status: Literal["예정", "진행중", "종료", "취소", "unknown"] = Field(default="unknown", description="대회 상태")
    
    # 메타데이터
    raw_data: Optional[Dict[str, Any]] = Field(None, description="원본 데이터")
    source_url: Optional[str] = Field(None, description="데이터 출처 URL")
    
    @model_validator(mode="after")
    def validate_dates(self) -> "CompetitionSchema":
        """날짜 논리 검증"""
        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                raise ValueError("종료일이 시작일보다 앞설 수 없습니다")
        
        # 상태 자동 설정
        if self.start_date:
            today = date.today()
            if self.end_date and self.end_date < today:
                self.status = "종료"
            elif self.start_date <= today <= (self.end_date or today):
                self.status = "진행중"
            elif self.start_date > today:
                self.status = "예정"
        
        return self
    
    class Config:
        use_enum_values = True


class RankingSchema(BaseModel):
    """순위 스키마"""
    
    # 필수 필드
    event_id: int = Field(..., ge=1, description="종목 DB ID")
    rank_position: int = Field(..., ge=1, le=256, description="순위")
    player_name: str = Field(..., min_length=1, description="선수명")
    
    # 선택 필드
    player_id: Optional[int] = Field(None, description="선수 DB ID")
    team_name: Optional[str] = Field(None, description="소속팀")
    
    # 성적 정보
    match_count: int = Field(default=0, ge=0, description="경기 수")
    win_count: int = Field(default=0, ge=0, description="승리 수")
    loss_count: int = Field(default=0, ge=0, description="패배 수")
    points: int = Field(default=0, ge=0, description="포인트")
    
    # 메타데이터
    raw_data: Optional[Dict[str, Any]] = Field(None, description="원본 데이터")
    
    @model_validator(mode="after")
    def validate_match_counts(self) -> "RankingSchema":
        """경기 수 논리 검증"""
        if self.match_count > 0:
            if self.win_count + self.loss_count > self.match_count:
                # 경고만 (실제로는 부전승 등이 있을 수 있음)
                pass
        return self
    
    class Config:
        use_enum_values = True


# ==================== 파이프라인 데이터 컨테이너 ====================

class PipelineData(BaseModel):
    """파이프라인 처리용 데이터 컨테이너"""
    
    # 원본 데이터
    raw_html: Optional[str] = Field(None, description="원본 HTML")
    raw_json: Optional[Dict[str, Any]] = Field(None, description="원본 JSON")
    source_url: str = Field(..., description="데이터 출처 URL")
    
    # 스크래핑 정보
    scrape_id: str = Field(..., description="스크래핑 고유 ID")
    scraped_at: datetime = Field(default_factory=datetime.now)
    
    # 검증 결과
    technical_validation: Optional[ValidationResult] = Field(None)
    business_validation: Optional[ValidationResult] = Field(None)
    
    # 파싱된 데이터
    competitions: List[CompetitionSchema] = Field(default_factory=list)
    events: List[EventSchema] = Field(default_factory=list)
    matches: List[MatchSchema] = Field(default_factory=list)
    players: List[PlayerSchema] = Field(default_factory=list)
    rankings: List[RankingSchema] = Field(default_factory=list)
    
    # 처리 상태
    stage: Literal["raw", "parsed", "tech_validated", "biz_validated", "stored"] = Field(default="raw")
    
    @property
    def can_proceed(self) -> bool:
        """다음 단계 진행 가능 여부"""
        if self.stage == "tech_validated":
            return self.technical_validation is not None and self.technical_validation.can_save
        if self.stage == "biz_validated":
            return self.business_validation is not None and self.business_validation.can_save
        return True
    
    class Config:
        use_enum_values = True
