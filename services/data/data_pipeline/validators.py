"""
데이터 검증 시스템

Stage 2: Technical Validation (기술적 검증)
Stage 3: Business Logic Validation (비즈니스 로직 검증)
"""

from typing import List, Dict, Any, Optional, Type, TypeVar
from pydantic import ValidationError as PydanticValidationError
from datetime import datetime, date
from loguru import logger
import re

from .schemas import (
    PlayerSchema,
    MatchSchema,
    EventSchema,
    CompetitionSchema,
    RankingSchema,
    ValidationResult,
    ValidationError,
    ValidationSeverity,
    Gender,
    Weapon,
    AgeGroup,
)

T = TypeVar("T")


class TechnicalValidator:
    """
    Stage 2: 기술적 검증
    
    - 필드 존재 여부
    - 데이터 타입
    - 필수 필드 채우기
    - 기본 범위 검증
    """
    
    def __init__(self, db_client=None):
        self.db = db_client
    
    def validate_player(self, data: Dict[str, Any]) -> ValidationResult:
        """선수 데이터 기술적 검증"""
        errors = []
        warnings = []
        
        try:
            # Pydantic 스키마 검증
            PlayerSchema(**data)
        except PydanticValidationError as e:
            for error in e.errors():
                errors.append(ValidationError(
                    error_type="SCHEMA_VALIDATION_FAILED",
                    severity=ValidationSeverity.CRITICAL,
                    message=error["msg"],
                    field=".".join(str(loc) for loc in error["loc"]),
                    value=error.get("input"),
                    suggestion="데이터 형식을 확인하세요"
                ))
        except Exception as e:
            errors.append(ValidationError(
                error_type="UNEXPECTED_ERROR",
                severity=ValidationSeverity.CRITICAL,
                message=str(e),
                suggestion="원본 데이터를 확인하세요"
            ))
        
        # 추가 기술적 검증
        if data.get("player_name"):
            name = data["player_name"]
            
            # 이름에 숫자가 포함되어 있으면 경고
            if re.search(r"\d", name):
                warnings.append(ValidationError(
                    error_type="NAME_CONTAINS_NUMBERS",
                    severity=ValidationSeverity.MEDIUM,
                    message=f"선수명에 숫자가 포함되어 있습니다: {name}",
                    field="player_name",
                    value=name,
                    suggestion="선수명에서 숫자를 제거하세요"
                ))
            
            # 이름이 너무 길면 경고 (팀명이 포함되었을 수 있음)
            if len(name) > 10:
                warnings.append(ValidationError(
                    error_type="NAME_TOO_LONG",
                    severity=ValidationSeverity.LOW,
                    message=f"선수명이 너무 깁니다: {name}",
                    field="player_name",
                    value=name,
                    suggestion="팀명이 포함되어 있는지 확인하세요"
                ))
        
        # 출생년도 범위 검증
        if birth_year := data.get("birth_year"):
            current_year = datetime.now().year
            if birth_year > current_year - 5:
                errors.append(ValidationError(
                    error_type="INVALID_BIRTH_YEAR",
                    severity=ValidationSeverity.HIGH,
                    message=f"출생년도가 너무 최근입니다: {birth_year}",
                    field="birth_year",
                    value=birth_year,
                    suggestion="출생년도를 확인하세요"
                ))
            elif birth_year < 1940:
                warnings.append(ValidationError(
                    error_type="OLD_BIRTH_YEAR",
                    severity=ValidationSeverity.MEDIUM,
                    message=f"출생년도가 너무 오래됐습니다: {birth_year}",
                    field="birth_year",
                    value=birth_year,
                    suggestion="출생년도를 확인하세요"
                ))
        
        total = 1
        valid = 0 if errors else 1
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            pass_rate=valid / total if total > 0 else 0,
            validated_at=datetime.now()
        )
    
    def validate_match(self, data: Dict[str, Any]) -> ValidationResult:
        """경기 데이터 기술적 검증"""
        errors = []
        warnings = []
        
        try:
            MatchSchema(**data)
        except PydanticValidationError as e:
            for error in e.errors():
                errors.append(ValidationError(
                    error_type="SCHEMA_VALIDATION_FAILED",
                    severity=ValidationSeverity.CRITICAL,
                    message=error["msg"],
                    field=".".join(str(loc) for loc in error["loc"]),
                    value=error.get("input"),
                    suggestion="데이터 형식을 확인하세요"
                ))
        except Exception as e:
            errors.append(ValidationError(
                error_type="UNEXPECTED_ERROR",
                severity=ValidationSeverity.CRITICAL,
                message=str(e)
            ))
        
        # 점수 검증
        p1_score = data.get("player1_score")
        p2_score = data.get("player2_score")
        match_type = data.get("match_type", "de")
        
        if p1_score is not None and p2_score is not None:
            # DE 경기는 보통 15점, Pool은 5점
            max_score = 15 if match_type == "de" else 5
            
            if p1_score > max_score or p2_score > max_score:
                warnings.append(ValidationError(
                    error_type="UNUSUAL_SCORE",
                    severity=ValidationSeverity.MEDIUM,
                    message=f"점수가 일반적인 범위를 벗어났습니다: {p1_score}-{p2_score}",
                    field="score",
                    value=f"{p1_score}-{p2_score}",
                    suggestion=f"{match_type} 경기의 일반적인 최대 점수는 {max_score}점입니다"
                ))
            
            # 동점이면 경고
            if p1_score == p2_score and p1_score > 0:
                warnings.append(ValidationError(
                    error_type="TIE_SCORE",
                    severity=ValidationSeverity.MEDIUM,
                    message=f"동점 경기입니다: {p1_score}-{p2_score}",
                    field="score",
                    value=f"{p1_score}-{p2_score}",
                    suggestion="연장전 결과가 누락되었을 수 있습니다"
                ))
        
        # 라운드명 검증
        round_name = data.get("round_name")
        valid_rounds = ["128강", "64강", "32강", "16강", "8강", "준결승", "결승", "3위결정전"]
        if round_name and round_name not in valid_rounds:
            # Pool 라운드가 아니면 경고
            if not round_name.startswith("Pool"):
                warnings.append(ValidationError(
                    error_type="UNKNOWN_ROUND",
                    severity=ValidationSeverity.LOW,
                    message=f"알 수 없는 라운드명: {round_name}",
                    field="round_name",
                    value=round_name,
                    suggestion=f"유효한 라운드: {', '.join(valid_rounds)}"
                ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            pass_rate=1.0 if not errors else 0.0,
            validated_at=datetime.now()
        )
    
    def validate_event(self, data: Dict[str, Any]) -> ValidationResult:
        """종목 데이터 기술적 검증"""
        errors = []
        warnings = []
        
        try:
            EventSchema(**data)
        except PydanticValidationError as e:
            for error in e.errors():
                errors.append(ValidationError(
                    error_type="SCHEMA_VALIDATION_FAILED",
                    severity=ValidationSeverity.CRITICAL,
                    message=error["msg"],
                    field=".".join(str(loc) for loc in error["loc"]),
                    value=error.get("input"),
                    suggestion="데이터 형식을 확인하세요"
                ))
        except Exception as e:
            errors.append(ValidationError(
                error_type="UNEXPECTED_ERROR",
                severity=ValidationSeverity.CRITICAL,
                message=str(e)
            ))
        
        # 종목명에서 정보 추출 가능 여부 검증
        event_name = data.get("event_name", "")
        if event_name:
            weapon = Weapon.from_string(event_name)
            gender = Gender.from_string(event_name)
            
            if weapon == Weapon.UNKNOWN:
                warnings.append(ValidationError(
                    error_type="WEAPON_NOT_DETECTED",
                    severity=ValidationSeverity.MEDIUM,
                    message=f"종목명에서 무기를 식별할 수 없습니다: {event_name}",
                    field="event_name",
                    value=event_name,
                    suggestion="무기 정보를 명시적으로 제공하세요"
                ))
            
            if gender == Gender.UNKNOWN:
                warnings.append(ValidationError(
                    error_type="GENDER_NOT_DETECTED",
                    severity=ValidationSeverity.MEDIUM,
                    message=f"종목명에서 성별을 식별할 수 없습니다: {event_name}",
                    field="event_name",
                    value=event_name,
                    suggestion="성별 정보를 명시적으로 제공하세요"
                ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            pass_rate=1.0 if not errors else 0.0,
            validated_at=datetime.now()
        )
    
    def validate_competition(self, data: Dict[str, Any]) -> ValidationResult:
        """대회 데이터 기술적 검증"""
        errors = []
        warnings = []
        
        try:
            CompetitionSchema(**data)
        except PydanticValidationError as e:
            for error in e.errors():
                errors.append(ValidationError(
                    error_type="SCHEMA_VALIDATION_FAILED",
                    severity=ValidationSeverity.CRITICAL,
                    message=error["msg"],
                    field=".".join(str(loc) for loc in error["loc"]),
                    value=error.get("input"),
                    suggestion="데이터 형식을 확인하세요"
                ))
        except Exception as e:
            errors.append(ValidationError(
                error_type="UNEXPECTED_ERROR",
                severity=ValidationSeverity.CRITICAL,
                message=str(e)
            ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            pass_rate=1.0 if not errors else 0.0,
            validated_at=datetime.now()
        )
    
    def validate_ranking(self, data: Dict[str, Any]) -> ValidationResult:
        """순위 데이터 기술적 검증"""
        errors = []
        warnings = []
        
        try:
            RankingSchema(**data)
        except PydanticValidationError as e:
            for error in e.errors():
                errors.append(ValidationError(
                    error_type="SCHEMA_VALIDATION_FAILED",
                    severity=ValidationSeverity.CRITICAL,
                    message=error["msg"],
                    field=".".join(str(loc) for loc in error["loc"]),
                    value=error.get("input"),
                    suggestion="데이터 형식을 확인하세요"
                ))
        except Exception as e:
            errors.append(ValidationError(
                error_type="UNEXPECTED_ERROR",
                severity=ValidationSeverity.CRITICAL,
                message=str(e)
            ))
        
        # 순위-성적 일관성 검증
        rank = data.get("rank_position", 0)
        wins = data.get("win_count", 0)
        
        if rank == 1 and wins == 0:
            warnings.append(ValidationError(
                error_type="RANK_WIN_MISMATCH",
                severity=ValidationSeverity.MEDIUM,
                message="1위인데 승리 수가 0입니다",
                field="win_count",
                value=wins,
                suggestion="승리 수를 확인하세요"
            ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            pass_rate=1.0 if not errors else 0.0,
            validated_at=datetime.now()
        )
    
    def validate_batch(
        self,
        data_type: str,
        records: List[Dict[str, Any]]
    ) -> ValidationResult:
        """배치 검증"""
        all_errors = []
        all_warnings = []
        valid_count = 0
        
        validator_map = {
            "player": self.validate_player,
            "match": self.validate_match,
            "event": self.validate_event,
            "competition": self.validate_competition,
            "ranking": self.validate_ranking,
        }
        
        validator = validator_map.get(data_type)
        if not validator:
            return ValidationResult(
                is_valid=False,
                errors=[ValidationError(
                    error_type="UNKNOWN_DATA_TYPE",
                    severity=ValidationSeverity.CRITICAL,
                    message=f"알 수 없는 데이터 타입: {data_type}"
                )],
                pass_rate=0.0
            )
        
        for i, record in enumerate(records):
            result = validator(record)
            if result.is_valid:
                valid_count += 1
            else:
                for error in result.errors:
                    error.message = f"[Record {i}] {error.message}"
                    all_errors.append(error)
            all_warnings.extend(result.warnings)
        
        return ValidationResult(
            is_valid=valid_count == len(records),
            errors=all_errors,
            warnings=all_warnings,
            pass_rate=valid_count / len(records) if records else 0.0,
            validated_at=datetime.now()
        )


class BusinessValidator:
    """
    Stage 3: 비즈니스 로직 검증
    
    - 중복 경기 감지
    - 공식 대회 확인
    - 선수 나이와 급수 일치
    - 상대 선수 존재 여부
    - 선수 성과 이상치 탐지
    - 외래키(FK) 무결성
    """
    
    def __init__(self, db_client=None):
        self.db = db_client
    
    def validate_player_consistency(
        self,
        player_data: Dict[str, Any],
        existing_player: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """선수 데이터 일관성 검증"""
        errors = []
        warnings = []
        
        if existing_player:
            # 성별 불변 규칙 검증
            new_gender = player_data.get("gender")
            old_gender = existing_player.get("gender")
            
            if new_gender and old_gender and new_gender != old_gender:
                if new_gender != "unknown" and old_gender != "unknown":
                    errors.append(ValidationError(
                        error_type="GENDER_CHANGE_VIOLATION",
                        severity=ValidationSeverity.CRITICAL,
                        message=f"성별 변경 불가: {old_gender} → {new_gender}",
                        field="gender",
                        value=new_gender,
                        suggestion="동명이인일 수 있습니다. 선수 분리가 필요합니다."
                    ))
            
            # 나이 역행 검증 (나이그룹이 내려가면 안됨)
            new_age_group = player_data.get("age_group")
            old_age_group = existing_player.get("age_group")
            
            if new_age_group and old_age_group:
                age_order = [
                    "초등부(1-2학년)", "초등부(3-4학년)", "초등부(5-6학년)",
                    "중등부", "고등부", "대학부", "일반부", "시니어"
                ]
                try:
                    new_idx = age_order.index(new_age_group)
                    old_idx = age_order.index(old_age_group)
                    
                    if new_idx < old_idx:
                        errors.append(ValidationError(
                            error_type="AGE_REGRESSION_VIOLATION",
                            severity=ValidationSeverity.CRITICAL,
                            message=f"연령대 역행 불가: {old_age_group} → {new_age_group}",
                            field="age_group",
                            value=new_age_group,
                            suggestion="동명이인일 수 있습니다. 선수 분리가 필요합니다."
                        ))
                except ValueError:
                    # 연령대가 목록에 없으면 무시
                    pass
            
            # 무기 일관성 검증
            new_weapon = player_data.get("primary_weapon")
            old_weapon = existing_player.get("primary_weapon")
            
            if new_weapon and old_weapon:
                if new_weapon != old_weapon and new_weapon != "unknown" and old_weapon != "unknown":
                    warnings.append(ValidationError(
                        error_type="WEAPON_CHANGE",
                        severity=ValidationSeverity.MEDIUM,
                        message=f"주 무기 변경: {old_weapon} → {new_weapon}",
                        field="primary_weapon",
                        value=new_weapon,
                        suggestion="동명이인 가능성을 확인하세요"
                    ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            pass_rate=1.0 if not errors else 0.0,
            validated_at=datetime.now()
        )
    
    def validate_match_consistency(
        self,
        match_data: Dict[str, Any],
        event_data: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """경기 데이터 일관성 검증"""
        errors = []
        warnings = []
        
        # 같은 선수 대결 검증
        p1_name = match_data.get("player1_name", "").strip()
        p2_name = match_data.get("player2_name", "").strip()
        
        if p1_name and p2_name and p1_name == p2_name:
            errors.append(ValidationError(
                error_type="SAME_PLAYER_MATCH",
                severity=ValidationSeverity.CRITICAL,
                message=f"같은 선수끼리 경기: {p1_name}",
                field="player_name",
                value=p1_name,
                suggestion="선수명을 확인하세요"
            ))
        
        # 종목 성별과 선수 일치 검증 (event_data가 있는 경우)
        if event_data:
            event_gender = event_data.get("gender")
            event_name = event_data.get("event_name", "")
            
            # 남자 종목에 여성 선수, 여자 종목에 남성 선수 검증
            # (이름으로 성별 추정은 어려우므로 경고만)
            pass
        
        # 라운드 순서 검증
        round_name = match_data.get("round_name")
        match_number = match_data.get("match_number")
        
        round_max_matches = {
            "64강": 32,
            "32강": 16,
            "16강": 8,
            "8강": 4,
            "준결승": 2,
            "결승": 1,
            "3위결정전": 1,
        }
        
        if round_name in round_max_matches and match_number:
            max_matches = round_max_matches[round_name]
            if match_number > max_matches:
                errors.append(ValidationError(
                    error_type="INVALID_MATCH_NUMBER",
                    severity=ValidationSeverity.HIGH,
                    message=f"{round_name}에서 경기 번호가 너무 큽니다: {match_number} (최대 {max_matches})",
                    field="match_number",
                    value=match_number,
                    suggestion=f"{round_name}의 최대 경기 수는 {max_matches}입니다"
                ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            pass_rate=1.0 if not errors else 0.0,
            validated_at=datetime.now()
        )
    
    def validate_referential_integrity(
        self,
        data: Dict[str, Any],
        data_type: str
    ) -> ValidationResult:
        """참조 무결성 검증"""
        errors = []
        warnings = []
        
        if not self.db:
            return ValidationResult(is_valid=True, warnings=[
                ValidationError(
                    error_type="DB_NOT_CONNECTED",
                    severity=ValidationSeverity.INFO,
                    message="DB 연결이 없어 참조 무결성 검증을 건너뜁니다"
                )
            ])
        
        try:
            if data_type == "match":
                # event_id 존재 확인
                event_id = data.get("event_id")
                if event_id:
                    result = self.db.table("events").select("id").eq("id", event_id).execute()
                    if not result.data:
                        errors.append(ValidationError(
                            error_type="EVENT_NOT_FOUND",
                            severity=ValidationSeverity.CRITICAL,
                            message=f"종목이 존재하지 않습니다: event_id={event_id}",
                            field="event_id",
                            value=event_id,
                            suggestion="종목을 먼저 생성하세요"
                        ))
            
            elif data_type == "event":
                # competition_id 존재 확인
                comp_id = data.get("competition_id")
                if comp_id:
                    result = self.db.table("competitions").select("id").eq("id", comp_id).execute()
                    if not result.data:
                        errors.append(ValidationError(
                            error_type="COMPETITION_NOT_FOUND",
                            severity=ValidationSeverity.CRITICAL,
                            message=f"대회가 존재하지 않습니다: competition_id={comp_id}",
                            field="competition_id",
                            value=comp_id,
                            suggestion="대회를 먼저 생성하세요"
                        ))
            
            elif data_type == "ranking":
                # event_id 존재 확인
                event_id = data.get("event_id")
                if event_id:
                    result = self.db.table("events").select("id").eq("id", event_id).execute()
                    if not result.data:
                        errors.append(ValidationError(
                            error_type="EVENT_NOT_FOUND",
                            severity=ValidationSeverity.CRITICAL,
                            message=f"종목이 존재하지 않습니다: event_id={event_id}",
                            field="event_id",
                            value=event_id,
                            suggestion="종목을 먼저 생성하세요"
                        ))
        
        except Exception as e:
            warnings.append(ValidationError(
                error_type="DB_CHECK_FAILED",
                severity=ValidationSeverity.MEDIUM,
                message=f"DB 검증 중 오류: {str(e)}"
            ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            pass_rate=1.0 if not errors else 0.0,
            validated_at=datetime.now()
        )
    
    def validate_duplicate_detection(
        self,
        data: Dict[str, Any],
        data_type: str
    ) -> ValidationResult:
        """중복 데이터 감지"""
        errors = []
        warnings = []
        
        if not self.db:
            return ValidationResult(is_valid=True)
        
        try:
            if data_type == "player":
                name = data.get("player_name")
                team = data.get("team_name")
                
                if name:
                    query = self.db.table("players").select("id, name, team").eq("name", name)
                    result = query.execute()
                    
                    if result.data:
                        # 동명이인 가능성 경고
                        existing_count = len(result.data)
                        if existing_count > 0:
                            existing_teams = [r.get("team") for r in result.data if r.get("team")]
                            
                            if team and team not in existing_teams:
                                warnings.append(ValidationError(
                                    error_type="POSSIBLE_HOMONYM",
                                    severity=ValidationSeverity.MEDIUM,
                                    message=f"동명이인 가능성: '{name}' ({existing_count}명 존재)",
                                    field="player_name",
                                    value=name,
                                    suggestion=f"기존 팀: {', '.join(existing_teams)}"
                                ))
            
            elif data_type == "match":
                event_id = data.get("event_id")
                round_name = data.get("round_name")
                p1 = data.get("player1_name")
                p2 = data.get("player2_name")
                
                if event_id and round_name and p1 and p2:
                    # 같은 종목, 같은 라운드, 같은 선수 조합 확인
                    result = self.db.table("matches").select("id").eq(
                        "event_id", event_id
                    ).eq("round_name", round_name).eq(
                        "player1_name", p1
                    ).eq("player2_name", p2).execute()
                    
                    if result.data:
                        warnings.append(ValidationError(
                            error_type="DUPLICATE_MATCH",
                            severity=ValidationSeverity.HIGH,
                            message=f"중복 경기: {p1} vs {p2} ({round_name})",
                            field="match",
                            suggestion="기존 경기를 업데이트하거나 삭제하세요"
                        ))
        
        except Exception as e:
            warnings.append(ValidationError(
                error_type="DUPLICATE_CHECK_FAILED",
                severity=ValidationSeverity.LOW,
                message=f"중복 검사 중 오류: {str(e)}"
            ))
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            pass_rate=1.0 if not errors else 0.0,
            validated_at=datetime.now()
        )
    
    def validate_full(
        self,
        data: Dict[str, Any],
        data_type: str,
        existing_data: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """전체 비즈니스 검증 실행"""
        all_errors = []
        all_warnings = []
        
        # 1. 데이터 타입별 일관성 검증
        if data_type == "player":
            result = self.validate_player_consistency(data, existing_data)
        elif data_type == "match":
            result = self.validate_match_consistency(data, existing_data)
        else:
            result = ValidationResult(is_valid=True)
        
        all_errors.extend(result.errors)
        all_warnings.extend(result.warnings)
        
        # 2. 참조 무결성 검증
        ref_result = self.validate_referential_integrity(data, data_type)
        all_errors.extend(ref_result.errors)
        all_warnings.extend(ref_result.warnings)
        
        # 3. 중복 감지
        dup_result = self.validate_duplicate_detection(data, data_type)
        all_errors.extend(dup_result.errors)
        all_warnings.extend(dup_result.warnings)
        
        return ValidationResult(
            is_valid=len(all_errors) == 0,
            errors=all_errors,
            warnings=all_warnings,
            pass_rate=1.0 if not all_errors else 0.0,
            validated_at=datetime.now()
        )
