"""
Sync Models - 동기화 Pydantic 모델
"""

from datetime import date, datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


# =============================================
# Enums
# =============================================

class SyncStatus(str, Enum):
    """동기화 상태"""
    started = "started"
    running = "running"
    completed = "completed"
    failed = "failed"


class SyncType(str, Enum):
    """동기화 유형"""
    player_cache = "player_cache"
    full = "full"


# =============================================
# Response Models
# =============================================

class SyncResult(BaseModel):
    """동기화 결과 응답"""
    sync_id: str
    organization_id: int
    sync_type: SyncType
    status: SyncStatus
    total_processed: int = 0
    total_updated: int = 0
    total_errors: int = 0
    error_details: Optional[List[str]] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None


class SyncLogResponse(BaseModel):
    """동기화 로그 응답"""
    id: str
    organization_id: int
    sync_type: str
    status: str
    total_processed: int = 0
    total_updated: int = 0
    total_errors: int = 0
    error_details: Optional[Any] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class PlayerCacheEntry(BaseModel):
    """선수 캐시 항목"""
    id: Optional[str] = None
    organization_id: int
    member_id: str
    player_id: Optional[str] = None
    player_name: str
    current_team: Optional[str] = None
    weapons: Optional[List[str]] = None
    age_group: Optional[str] = None
    competition_count: int = 0
    last_competition_date: Optional[date] = None
    recent_result: Optional[str] = None
    medals: Dict[str, int] = Field(default_factory=lambda: {"gold": 0, "silver": 0, "bronze": 0})
    last_synced_at: Optional[datetime] = None


class CachedRosterResponse(BaseModel):
    """캐시된 로스터 응답"""
    organization_id: int
    total_members: int
    last_synced_at: Optional[datetime] = None
    players: List[PlayerCacheEntry]
