"""
데이터 파이프라인 메인 클래스

4단계 ETL 파이프라인:
1. Extract: 원본 데이터 수집 및 저장
2. Transform: 파싱 및 정규화
3. Validate: 기술적/비즈니스 검증
4. Load: 검증된 데이터 저장
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from loguru import logger
import uuid
import json
import os

from .schemas import (
    PipelineData,
    PlayerSchema,
    MatchSchema,
    EventSchema,
    CompetitionSchema,
    RankingSchema,
    ValidationResult,
    ValidationError,
    ValidationSeverity,
)
from .validators import TechnicalValidator, BusinessValidator
from .events import EventPublisher, EventType, DataChangeEvent


class DataPipeline:
    """
    4단계 데이터 파이프라인
    
    Stage 1: Raw Storage (원본 저장)
    Stage 2: Technical Validation (기술적 검증)
    Stage 3: Business Logic Validation (비즈니스 로직 검증)
    Stage 4: Validated Storage (검증된 데이터 저장)
    """
    
    def __init__(self, db_client=None, raw_storage_path: str = "data/raw"):
        self.db = db_client
        self.raw_storage_path = raw_storage_path
        
        # 검증기 초기화
        self.tech_validator = TechnicalValidator(db_client)
        self.biz_validator = BusinessValidator(db_client)
        
        # 이벤트 발행자 초기화
        self.publisher = EventPublisher(db_client)
        
        # 통계
        self.stats = {
            "total_processed": 0,
            "total_passed": 0,
            "total_failed": 0,
            "total_warnings": 0,
        }
        
        # 원본 저장소 디렉토리 생성
        os.makedirs(raw_storage_path, exist_ok=True)
    
    # ==================== Stage 1: Raw Storage ====================
    
    def save_raw_data(
        self,
        source_url: str,
        content: str,
        content_type: str = "html"
    ) -> str:
        """
        원본 데이터 저장 (검증 없이)
        
        Args:
            source_url: 데이터 출처 URL
            content: 원본 콘텐츠 (HTML 또는 JSON)
            content_type: 콘텐츠 타입 ("html" 또는 "json")
        
        Returns:
            scrape_id: 스크래핑 고유 ID
        """
        scrape_id = str(uuid.uuid4())
        timestamp = datetime.now()
        
        # 날짜별 디렉토리 생성
        date_dir = os.path.join(
            self.raw_storage_path,
            timestamp.strftime("%Y/%m/%d")
        )
        os.makedirs(date_dir, exist_ok=True)
        
        # 메타데이터
        metadata = {
            "scrape_id": scrape_id,
            "source_url": source_url,
            "content_type": content_type,
            "scraped_at": timestamp.isoformat(),
            "content_length": len(content),
        }
        
        # 파일 저장
        content_file = os.path.join(date_dir, f"{scrape_id}.{content_type}")
        meta_file = os.path.join(date_dir, f"{scrape_id}.meta.json")
        
        with open(content_file, "w", encoding="utf-8") as f:
            f.write(content)
        
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        logger.info(f"📦 Raw data saved: {scrape_id}")
        
        return scrape_id
    
    def load_raw_data(self, scrape_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        저장된 원본 데이터 로드
        
        Returns:
            (content, metadata) 또는 None
        """
        # 모든 날짜 디렉토리 검색
        for root, dirs, files in os.walk(self.raw_storage_path):
            meta_file = os.path.join(root, f"{scrape_id}.meta.json")
            if os.path.exists(meta_file):
                with open(meta_file, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                
                content_type = metadata.get("content_type", "html")
                content_file = os.path.join(root, f"{scrape_id}.{content_type}")
                
                if os.path.exists(content_file):
                    with open(content_file, "r", encoding="utf-8") as f:
                        content = f.read()
                    return content, metadata
        
        return None
    
    # ==================== Stage 2 & 3: Validation ====================
    
    def validate_data(
        self,
        data: Dict[str, Any],
        data_type: str,
        existing_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[ValidationResult, ValidationResult]:
        """
        데이터 검증 (기술적 + 비즈니스)
        
        Args:
            data: 검증할 데이터
            data_type: 데이터 타입 ("player", "match", "event", "competition", "ranking")
            existing_data: 기존 데이터 (업데이트 시)
        
        Returns:
            (기술적 검증 결과, 비즈니스 검증 결과)
        """
        # Stage 2: 기술적 검증
        if data_type == "player":
            tech_result = self.tech_validator.validate_player(data)
        elif data_type == "match":
            tech_result = self.tech_validator.validate_match(data)
        elif data_type == "event":
            tech_result = self.tech_validator.validate_event(data)
        elif data_type == "competition":
            tech_result = self.tech_validator.validate_competition(data)
        elif data_type == "ranking":
            tech_result = self.tech_validator.validate_ranking(data)
        else:
            tech_result = ValidationResult(
                is_valid=False,
                errors=[ValidationError(
                    error_type="UNKNOWN_DATA_TYPE",
                    severity=ValidationSeverity.CRITICAL,
                    message=f"알 수 없는 데이터 타입: {data_type}"
                )]
            )
        
        # 기술적 검증 실패 시 비즈니스 검증 건너뛰기
        if not tech_result.can_save:
            return tech_result, ValidationResult(is_valid=False)
        
        # Stage 3: 비즈니스 로직 검증
        biz_result = self.biz_validator.validate_full(data, data_type, existing_data)
        
        return tech_result, biz_result
    
    # ==================== Stage 4: Validated Storage ====================
    
    def save_validated_data(
        self,
        data: Dict[str, Any],
        data_type: str,
        tech_result: ValidationResult,
        biz_result: ValidationResult
    ) -> Optional[int]:
        """
        검증된 데이터 저장
        
        Returns:
            저장된 레코드 ID 또는 None
        """
        if not self.db:
            logger.error("DB 클라이언트가 없습니다")
            return None
        
        # 검증 통과 확인
        if not tech_result.can_save:
            logger.warning(f"기술적 검증 실패: {data_type}")
            self._log_validation_failure(data, data_type, tech_result)
            return None
        
        if not biz_result.can_save:
            logger.warning(f"비즈니스 검증 실패: {data_type}")
            self._log_validation_failure(data, data_type, biz_result)
            return None
        
        # 메타데이터 추가
        data["validated_at"] = datetime.now().isoformat()
        data["validation_version"] = "1.0"
        
        if biz_result.warnings:
            data["has_warnings"] = True
            data["warnings"] = [w.message for w in biz_result.warnings]
        
        try:
            # 테이블 이름 결정
            table_map = {
                "player": "players",
                "match": "matches",
                "event": "events",
                "competition": "competitions",
                "ranking": "rankings",
            }
            table_name = table_map.get(data_type)
            
            if not table_name:
                logger.error(f"알 수 없는 테이블: {data_type}")
                return None
            
            # Upsert 실행
            result = self.db.table(table_name).upsert(data).execute()
            
            if result.data:
                record_id = result.data[0].get("id")
                
                # 이벤트 발행
                event_type_map = {
                    "player": EventType.PLAYER_CREATED,
                    "match": EventType.MATCH_CREATED,
                    "event": EventType.EVENT_CREATED,
                    "competition": EventType.COMPETITION_CREATED,
                }
                
                event_type = event_type_map.get(data_type)
                if event_type:
                    self.publisher.publish(DataChangeEvent(
                        event_type=event_type,
                        entity_type=data_type,
                        entity_id=record_id,
                        data=data
                    ))
                
                self.stats["total_passed"] += 1
                logger.info(f"✅ Data saved: {data_type}#{record_id}")
                return record_id
            
            return None
        
        except Exception as e:
            logger.error(f"데이터 저장 실패: {e}")
            self.stats["total_failed"] += 1
            return None
    
    def _log_validation_failure(
        self,
        data: Dict[str, Any],
        data_type: str,
        result: ValidationResult
    ) -> None:
        """검증 실패 로깅"""
        self.stats["total_failed"] += 1
        
        # 검증 실패 이벤트 발행
        self.publisher.publish(DataChangeEvent(
            event_type=EventType.VALIDATION_FAILED,
            entity_type=data_type,
            data={
                "original_data": data,
                "errors": [e.message for e in result.errors],
            }
        ))
        
        # DB에 실패 로그 저장
        if self.db:
            try:
                self.db.table("validation_logs").insert({
                    "data_type": data_type,
                    "data": data,
                    "errors": [e.to_dict() if hasattr(e, 'to_dict') else {"message": e.message, "severity": e.severity.value} for e in result.errors],
                    "warnings": [w.to_dict() if hasattr(w, 'to_dict') else {"message": w.message, "severity": w.severity.value} for w in result.warnings],
                    "created_at": datetime.now().isoformat()
                }).execute()
            except Exception as e:
                logger.warning(f"검증 로그 저장 실패: {e}")
    
    # ==================== 전체 파이프라인 실행 ====================
    
    def process(
        self,
        data: Dict[str, Any],
        data_type: str,
        source_url: str = "",
        existing_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[int], ValidationResult, ValidationResult]:
        """
        전체 파이프라인 실행
        
        Args:
            data: 처리할 데이터
            data_type: 데이터 타입
            source_url: 데이터 출처 URL
            existing_data: 기존 데이터 (업데이트 시)
        
        Returns:
            (저장된 ID, 기술적 검증 결과, 비즈니스 검증 결과)
        """
        self.stats["total_processed"] += 1
        
        # Stage 1: 원본 저장 (선택적)
        if source_url:
            self.save_raw_data(source_url, json.dumps(data), "json")
        
        # Stage 2 & 3: 검증
        tech_result, biz_result = self.validate_data(data, data_type, existing_data)
        
        # Stage 4: 저장
        record_id = None
        if tech_result.can_save and biz_result.can_save:
            record_id = self.save_validated_data(data, data_type, tech_result, biz_result)
        
        # 경고 카운트
        self.stats["total_warnings"] += len(tech_result.warnings) + len(biz_result.warnings)
        
        return record_id, tech_result, biz_result
    
    def process_batch(
        self,
        records: List[Dict[str, Any]],
        data_type: str,
        source_url: str = ""
    ) -> Dict[str, Any]:
        """
        배치 처리
        
        Returns:
            처리 결과 통계
        """
        results = {
            "total": len(records),
            "success": 0,
            "failed": 0,
            "warnings": 0,
            "errors": [],
        }
        
        for i, record in enumerate(records):
            try:
                record_id, tech_result, biz_result = self.process(
                    record, data_type, source_url
                )
                
                if record_id:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    # 오류 수집
                    for error in tech_result.errors + biz_result.errors:
                        results["errors"].append({
                            "record_index": i,
                            "error": error.message,
                            "severity": error.severity.value
                        })
                
                results["warnings"] += len(tech_result.warnings) + len(biz_result.warnings)
            
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({
                    "record_index": i,
                    "error": str(e),
                    "severity": "critical"
                })
        
        logger.info(f"📊 Batch processing completed: {results['success']}/{results['total']} success")
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """파이프라인 통계 조회"""
        return {
            **self.stats,
            "pass_rate": (
                self.stats["total_passed"] / self.stats["total_processed"]
                if self.stats["total_processed"] > 0 else 0
            )
        }
    
    def reset_stats(self) -> None:
        """통계 초기화"""
        self.stats = {
            "total_processed": 0,
            "total_passed": 0,
            "total_failed": 0,
            "total_warnings": 0,
        }
