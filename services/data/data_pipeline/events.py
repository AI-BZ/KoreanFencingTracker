"""
이벤트 발행/구독 시스템

데이터 변경 시 관련 페이지들을 자동으로 업데이트하기 위한 이벤트 시스템
Supabase Realtime 또는 내부 이벤트 큐 사용
"""

from typing import Dict, Any, List, Callable, Optional
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
from loguru import logger
import json
import asyncio
from collections import defaultdict


class EventType(str, Enum):
    """이벤트 유형"""
    # 대회 관련
    COMPETITION_CREATED = "competition.created"
    COMPETITION_UPDATED = "competition.updated"
    COMPETITION_DELETED = "competition.deleted"
    
    # 종목 관련
    EVENT_CREATED = "event.created"
    EVENT_UPDATED = "event.updated"
    EVENT_DELETED = "event.deleted"
    
    # 경기 관련
    MATCH_CREATED = "match.created"
    MATCH_UPDATED = "match.updated"
    MATCH_DELETED = "match.deleted"
    
    # 선수 관련
    PLAYER_CREATED = "player.created"
    PLAYER_UPDATED = "player.updated"
    PLAYER_MERGED = "player.merged"     # 동명이인 병합
    PLAYER_SPLIT = "player.split"       # 동명이인 분리
    
    # 순위 관련
    RANKING_UPDATED = "ranking.updated"
    
    # 검증 관련
    VALIDATION_FAILED = "validation.failed"
    VALIDATION_WARNING = "validation.warning"
    
    # 파이프라인 관련
    PIPELINE_STARTED = "pipeline.started"
    PIPELINE_COMPLETED = "pipeline.completed"
    PIPELINE_FAILED = "pipeline.failed"


@dataclass
class DataChangeEvent:
    """데이터 변경 이벤트"""
    event_type: EventType
    entity_type: str                    # "player", "match", "event", "competition"
    entity_id: Optional[int] = None
    data: Dict[str, Any] = field(default_factory=dict)
    old_data: Optional[Dict[str, Any]] = None  # 업데이트 시 이전 데이터
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "data_pipeline"       # 이벤트 발생 소스
    correlation_id: Optional[str] = None  # 관련 이벤트 그룹 ID
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "data": self.data,
            "old_data": self.old_data,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "correlation_id": self.correlation_id,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


class EventPublisher:
    """이벤트 발행자"""
    
    def __init__(self, db_client=None):
        self.db = db_client
        self.local_subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._event_log: List[DataChangeEvent] = []
        self._max_log_size = 1000
    
    def publish(self, event: DataChangeEvent) -> None:
        """이벤트 발행"""
        logger.info(f"📢 Event published: {event.event_type.value} - {event.entity_type}:{event.entity_id}")
        
        # 이벤트 로그에 추가
        self._event_log.append(event)
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size:]
        
        # DB에 이벤트 저장 (선택적)
        if self.db:
            try:
                self.db.table("data_events").insert({
                    "event_type": event.event_type.value,
                    "entity_type": event.entity_type,
                    "entity_id": event.entity_id,
                    "data": event.data,
                    "old_data": event.old_data,
                    "source": event.source,
                    "correlation_id": event.correlation_id,
                    "created_at": event.timestamp.isoformat()
                }).execute()
            except Exception as e:
                logger.warning(f"이벤트 DB 저장 실패: {e}")
        
        # 로컬 구독자에게 알림
        for subscriber in self.local_subscribers.get(event.event_type, []):
            try:
                subscriber(event)
            except Exception as e:
                logger.error(f"구독자 호출 실패: {e}")
    
    async def publish_async(self, event: DataChangeEvent) -> None:
        """비동기 이벤트 발행"""
        logger.info(f"📢 Event published (async): {event.event_type.value}")
        
        self._event_log.append(event)
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size:]
        
        # 로컬 구독자에게 비동기 알림
        tasks = []
        for subscriber in self.local_subscribers.get(event.event_type, []):
            if asyncio.iscoroutinefunction(subscriber):
                tasks.append(subscriber(event))
            else:
                subscriber(event)
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def subscribe(self, event_type: EventType, callback: Callable) -> None:
        """이벤트 구독"""
        self.local_subscribers[event_type].append(callback)
        logger.debug(f"✅ Subscribed to {event_type.value}")
    
    def unsubscribe(self, event_type: EventType, callback: Callable) -> None:
        """이벤트 구독 해제"""
        if callback in self.local_subscribers[event_type]:
            self.local_subscribers[event_type].remove(callback)
            logger.debug(f"❌ Unsubscribed from {event_type.value}")
    
    def get_recent_events(self, limit: int = 100) -> List[DataChangeEvent]:
        """최근 이벤트 조회"""
        return self._event_log[-limit:]
    
    # 편의 메서드들
    def publish_player_created(self, player_id: int, data: Dict[str, Any]) -> None:
        self.publish(DataChangeEvent(
            event_type=EventType.PLAYER_CREATED,
            entity_type="player",
            entity_id=player_id,
            data=data
        ))
    
    def publish_player_updated(
        self,
        player_id: int,
        new_data: Dict[str, Any],
        old_data: Dict[str, Any]
    ) -> None:
        self.publish(DataChangeEvent(
            event_type=EventType.PLAYER_UPDATED,
            entity_type="player",
            entity_id=player_id,
            data=new_data,
            old_data=old_data
        ))
    
    def publish_match_created(self, match_id: int, data: Dict[str, Any]) -> None:
        self.publish(DataChangeEvent(
            event_type=EventType.MATCH_CREATED,
            entity_type="match",
            entity_id=match_id,
            data=data
        ))
    
    def publish_event_updated(
        self,
        event_id: int,
        new_data: Dict[str, Any],
        old_data: Optional[Dict[str, Any]] = None
    ) -> None:
        self.publish(DataChangeEvent(
            event_type=EventType.EVENT_UPDATED,
            entity_type="event",
            entity_id=event_id,
            data=new_data,
            old_data=old_data
        ))


class EventSubscriber:
    """이벤트 구독자 - 데이터 동기화 처리"""
    
    def __init__(self, db_client=None, publisher: Optional[EventPublisher] = None):
        self.db = db_client
        self.publisher = publisher
        self._handlers: Dict[EventType, Callable] = {}
        
        # 기본 핸들러 등록
        self._register_default_handlers()
    
    def _register_default_handlers(self) -> None:
        """기본 이벤트 핸들러 등록"""
        self._handlers[EventType.PLAYER_UPDATED] = self._handle_player_update
        self._handlers[EventType.MATCH_CREATED] = self._handle_match_created
        self._handlers[EventType.EVENT_UPDATED] = self._handle_event_update
        self._handlers[EventType.PLAYER_MERGED] = self._handle_player_merged
    
    def register_handler(self, event_type: EventType, handler: Callable) -> None:
        """커스텀 핸들러 등록"""
        self._handlers[event_type] = handler
    
    def handle_event(self, event: DataChangeEvent) -> None:
        """이벤트 처리"""
        handler = self._handlers.get(event.event_type)
        if handler:
            try:
                handler(event)
                logger.info(f"✅ Event handled: {event.event_type.value}")
            except Exception as e:
                logger.error(f"❌ Event handling failed: {event.event_type.value} - {e}")
        else:
            logger.debug(f"No handler for event: {event.event_type.value}")
    
    def start_listening(self, publisher: EventPublisher) -> None:
        """이벤트 리스닝 시작"""
        for event_type in self._handlers.keys():
            publisher.subscribe(event_type, self.handle_event)
        logger.info("🎧 Event subscriber started listening")
    
    # ==================== 핸들러 구현 ====================
    
    def _handle_player_update(self, event: DataChangeEvent) -> None:
        """
        선수 정보 업데이트 시:
        - members 테이블 동기화
        - 관련 경기 결과의 선수 정보 업데이트
        - 순위 정보 재계산
        """
        if not self.db:
            return
        
        player_id = event.entity_id
        new_data = event.data
        old_data = event.old_data or {}
        
        logger.info(f"🔄 Syncing player update: {player_id}")
        
        try:
            # 1. members 테이블에서 연결된 회원 업데이트
            if new_data.get("name") != old_data.get("name"):
                self.db.table("members").update({
                    "player_name": new_data.get("name")
                }).eq("player_id", player_id).execute()
            
            # 2. 경기 결과에서 선수명 업데이트 (비정규화 필드)
            if new_data.get("name") != old_data.get("name"):
                old_name = old_data.get("name")
                new_name = new_data.get("name")
                
                if old_name and new_name:
                    # player1_name 업데이트
                    self.db.table("matches").update({
                        "player1_name": new_name
                    }).eq("player1_id", player_id).execute()
                    
                    # player2_name 업데이트
                    self.db.table("matches").update({
                        "player2_name": new_name
                    }).eq("player2_id", player_id).execute()
            
            logger.info(f"✅ Player sync completed: {player_id}")
        
        except Exception as e:
            logger.error(f"❌ Player sync failed: {e}")
    
    def _handle_match_created(self, event: DataChangeEvent) -> None:
        """
        경기 생성 시:
        - 선수 통계 업데이트
        - 종목 참가자 수 업데이트
        """
        if not self.db:
            return
        
        match_data = event.data
        event_id = match_data.get("event_id")
        
        logger.info(f"🔄 Processing new match for event: {event_id}")
        
        try:
            # 종목의 경기 수 업데이트
            if event_id:
                # 현재 경기 수 조회
                result = self.db.table("matches").select(
                    "id", count="exact"
                ).eq("event_id", event_id).execute()
                
                match_count = result.count or 0
                
                # 종목 정보 업데이트
                self.db.table("events").update({
                    "match_count": match_count,
                    "updated_at": datetime.now().isoformat()
                }).eq("id", event_id).execute()
            
            logger.info(f"✅ Match processing completed")
        
        except Exception as e:
            logger.error(f"❌ Match processing failed: {e}")
    
    def _handle_event_update(self, event: DataChangeEvent) -> None:
        """
        종목 업데이트 시:
        - 대회 정보 집계 업데이트
        - 관련 순위 재계산
        """
        if not self.db:
            return
        
        event_id = event.entity_id
        event_data = event.data
        
        logger.info(f"🔄 Processing event update: {event_id}")
        
        try:
            comp_id = event_data.get("competition_id")
            
            if comp_id:
                # 대회의 종목 수 업데이트
                result = self.db.table("events").select(
                    "id", count="exact"
                ).eq("competition_id", comp_id).execute()
                
                event_count = result.count or 0
                
                self.db.table("competitions").update({
                    "event_count": event_count,
                    "updated_at": datetime.now().isoformat()
                }).eq("id", comp_id).execute()
            
            logger.info(f"✅ Event update processing completed")
        
        except Exception as e:
            logger.error(f"❌ Event update processing failed: {e}")
    
    def _handle_player_merged(self, event: DataChangeEvent) -> None:
        """
        동명이인 병합 시:
        - 모든 경기 기록 병합
        - 모든 순위 기록 병합
        - 회원 정보 업데이트
        """
        if not self.db:
            return
        
        data = event.data
        target_id = data.get("target_player_id")  # 병합 대상 (유지)
        source_id = data.get("source_player_id")  # 병합 소스 (삭제)
        
        logger.info(f"🔄 Merging players: {source_id} → {target_id}")
        
        try:
            # 1. 경기 기록 이전
            self.db.table("matches").update({
                "player1_id": target_id
            }).eq("player1_id", source_id).execute()
            
            self.db.table("matches").update({
                "player2_id": target_id
            }).eq("player2_id", source_id).execute()
            
            self.db.table("matches").update({
                "winner_id": target_id
            }).eq("winner_id", source_id).execute()
            
            # 2. 순위 기록 이전
            self.db.table("rankings").update({
                "player_id": target_id
            }).eq("player_id", source_id).execute()
            
            # 3. 회원 연결 업데이트
            self.db.table("members").update({
                "player_id": target_id
            }).eq("player_id", source_id).execute()
            
            # 4. 소스 선수 삭제 (soft delete 또는 hard delete)
            self.db.table("players").update({
                "merged_into": target_id,
                "is_active": False
            }).eq("id", source_id).execute()
            
            logger.info(f"✅ Player merge completed: {source_id} → {target_id}")
        
        except Exception as e:
            logger.error(f"❌ Player merge failed: {e}")
