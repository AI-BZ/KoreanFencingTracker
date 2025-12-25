"""
데이터 동기화 시스템

데이터 변경 시 관련 테이블들을 자동으로 동기화
CLAUDE.md 제1원칙: 데이터 파이프라인 연결 (DATA PIPELINE INTEGRITY)
"""

from typing import Dict, Any, List, Optional, Set
from datetime import datetime
from loguru import logger
from enum import Enum


class SyncAction(str, Enum):
    """동기화 액션"""
    UPDATE = "update"
    DELETE = "delete"
    INVALIDATE_CACHE = "invalidate_cache"
    RECALCULATE = "recalculate"


class DataSynchronizer:
    """
    데이터 동기화 관리자
    
    핵심 규칙:
    - 단일 진실 원천 (Single Source of Truth)
    - 파이프라인 전파 (Propagation)
    - 데이터 무결성 (Integrity)
    """
    
    # 데이터 의존성 그래프
    # key: 소스 테이블, value: 의존하는 테이블들과 동기화 액션
    DEPENDENCY_GRAPH = {
        "players": [
            ("members", "player_id", SyncAction.UPDATE),
            ("matches", "player1_id", SyncAction.UPDATE),
            ("matches", "player2_id", SyncAction.UPDATE),
            ("matches", "winner_id", SyncAction.UPDATE),
            ("rankings", "player_id", SyncAction.UPDATE),
            ("player_rankings", "player_id", SyncAction.UPDATE),
        ],
        "events": [
            ("matches", "event_id", SyncAction.UPDATE),
            ("rankings", "event_id", SyncAction.UPDATE),
            ("pool_results", "event_id", SyncAction.UPDATE),
            ("tournament_results", "event_id", SyncAction.UPDATE),
        ],
        "competitions": [
            ("events", "competition_id", SyncAction.UPDATE),
        ],
    }
    
    # 캐시 무효화 대상
    CACHE_INVALIDATION_MAP = {
        "players": ["player_profile", "player_stats", "team_roster"],
        "matches": ["player_profile", "event_results", "head_to_head"],
        "events": ["competition_detail", "event_results"],
        "competitions": ["competition_list", "competition_detail"],
        "rankings": ["player_profile", "event_results", "rankings_page"],
    }
    
    def __init__(self, db_client=None):
        self.db = db_client
        self._sync_log: List[Dict[str, Any]] = []
        self._pending_syncs: Set[str] = set()
    
    def sync_on_update(
        self,
        source_table: str,
        record_id: int,
        updated_fields: Dict[str, Any],
        old_values: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        레코드 업데이트 시 연관 데이터 동기화
        
        Args:
            source_table: 업데이트된 테이블
            record_id: 업데이트된 레코드 ID
            updated_fields: 업데이트된 필드들
            old_values: 이전 값들 (선택)
        
        Returns:
            동기화 결과
        """
        result = {
            "source": f"{source_table}#{record_id}",
            "synced_tables": [],
            "errors": [],
            "timestamp": datetime.now().isoformat(),
        }
        
        # 순환 동기화 방지
        sync_key = f"{source_table}:{record_id}"
        if sync_key in self._pending_syncs:
            logger.warning(f"순환 동기화 감지: {sync_key}")
            return result
        
        self._pending_syncs.add(sync_key)
        
        try:
            dependencies = self.DEPENDENCY_GRAPH.get(source_table, [])
            
            for target_table, fk_field, action in dependencies:
                try:
                    sync_result = self._sync_dependent_table(
                        source_table=source_table,
                        source_id=record_id,
                        target_table=target_table,
                        fk_field=fk_field,
                        action=action,
                        updated_fields=updated_fields,
                        old_values=old_values
                    )
                    
                    if sync_result:
                        result["synced_tables"].append({
                            "table": target_table,
                            "action": action.value,
                            "affected_count": sync_result.get("count", 0)
                        })
                
                except Exception as e:
                    result["errors"].append({
                        "table": target_table,
                        "error": str(e)
                    })
                    logger.error(f"동기화 실패: {target_table} - {e}")
            
            # 캐시 무효화
            self._invalidate_caches(source_table, record_id)
            
            # 동기화 로그 기록
            self._log_sync(result)
        
        finally:
            self._pending_syncs.discard(sync_key)
        
        return result
    
    def _sync_dependent_table(
        self,
        source_table: str,
        source_id: int,
        target_table: str,
        fk_field: str,
        action: SyncAction,
        updated_fields: Dict[str, Any],
        old_values: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """의존 테이블 동기화 실행"""
        if not self.db:
            return None
        
        if action == SyncAction.UPDATE:
            # 비정규화 필드 업데이트
            return self._update_denormalized_fields(
                source_table, source_id, target_table, fk_field, updated_fields
            )
        
        elif action == SyncAction.DELETE:
            # CASCADE DELETE (주의 필요)
            pass
        
        elif action == SyncAction.RECALCULATE:
            # 집계 필드 재계산
            return self._recalculate_aggregates(target_table, fk_field, source_id)
        
        return None
    
    def _update_denormalized_fields(
        self,
        source_table: str,
        source_id: int,
        target_table: str,
        fk_field: str,
        updated_fields: Dict[str, Any]
    ) -> Dict[str, Any]:
        """비정규화 필드 업데이트"""
        # 필드 매핑 정의
        field_mappings = {
            ("players", "matches"): {
                "name": ["player1_name", "player2_name"],
                "team": ["player1_team", "player2_team"],
            },
            ("players", "members"): {
                "name": ["player_name"],
            },
            ("players", "rankings"): {
                "name": ["player_name"],
                "team": ["team_name"],
            },
        }
        
        mapping = field_mappings.get((source_table, target_table), {})
        
        affected_count = 0
        
        for source_field, target_fields in mapping.items():
            if source_field in updated_fields:
                new_value = updated_fields[source_field]
                
                for target_field in target_fields:
                    try:
                        # FK 필드에 따라 조건 결정
                        if "player1" in fk_field or "player1" in target_field:
                            result = self.db.table(target_table).update({
                                target_field: new_value,
                                "updated_at": datetime.now().isoformat()
                            }).eq("player1_id", source_id).execute()
                        elif "player2" in fk_field or "player2" in target_field:
                            result = self.db.table(target_table).update({
                                target_field: new_value,
                                "updated_at": datetime.now().isoformat()
                            }).eq("player2_id", source_id).execute()
                        else:
                            result = self.db.table(target_table).update({
                                target_field: new_value,
                                "updated_at": datetime.now().isoformat()
                            }).eq(fk_field, source_id).execute()
                        
                        if result.data:
                            affected_count += len(result.data)
                    
                    except Exception as e:
                        logger.error(f"필드 업데이트 실패: {target_table}.{target_field} - {e}")
        
        return {"count": affected_count}
    
    def _recalculate_aggregates(
        self,
        table: str,
        group_field: str,
        group_id: int
    ) -> Dict[str, Any]:
        """집계 필드 재계산"""
        if not self.db:
            return {"count": 0}
        
        affected_count = 0
        
        # 예: 종목의 경기 수 재계산
        if table == "events":
            try:
                # 경기 수 조회
                result = self.db.table("matches").select(
                    "id", count="exact"
                ).eq("event_id", group_id).execute()
                
                match_count = result.count or 0
                
                # 종목 정보 업데이트
                self.db.table("events").update({
                    "match_count": match_count,
                    "updated_at": datetime.now().isoformat()
                }).eq("id", group_id).execute()
                
                affected_count = 1
            except Exception as e:
                logger.error(f"집계 재계산 실패: {table} - {e}")
        
        return {"count": affected_count}
    
    def _invalidate_caches(self, source_table: str, record_id: int) -> None:
        """관련 캐시 무효화"""
        cache_keys = self.CACHE_INVALIDATION_MAP.get(source_table, [])
        
        for cache_key in cache_keys:
            try:
                # 캐시 무효화 로직 (Redis 등 사용 시)
                logger.debug(f"캐시 무효화: {cache_key} (source: {source_table}#{record_id})")
                # redis.delete(f"{cache_key}:{record_id}")
            except Exception as e:
                logger.warning(f"캐시 무효화 실패: {cache_key} - {e}")
    
    def _log_sync(self, result: Dict[str, Any]) -> None:
        """동기화 로그 기록"""
        self._sync_log.append(result)
        
        # 로그 크기 제한
        if len(self._sync_log) > 1000:
            self._sync_log = self._sync_log[-500:]
        
        # DB에 로그 저장 (선택적)
        if self.db:
            try:
                self.db.table("sync_logs").insert({
                    "source": result["source"],
                    "synced_tables": result["synced_tables"],
                    "errors": result["errors"],
                    "created_at": result["timestamp"]
                }).execute()
            except Exception as e:
                logger.warning(f"동기화 로그 저장 실패: {e}")
    
    # ==================== 선수 동기화 특화 메서드 ====================
    
    def sync_player_update(
        self,
        player_id: int,
        updated_fields: Dict[str, Any],
        old_values: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        선수 정보 업데이트 시 전체 동기화
        
        CLAUDE.md 제1원칙 구현:
        - 선수 프로필 → members 테이블 동기화
        - 선수 프로필 → 모든 경기 결과 동기화
        - 선수 프로필 → 순위 정보 동기화
        """
        result = self.sync_on_update("players", player_id, updated_fields, old_values)
        
        logger.info(f"🔄 선수 동기화 완료: player#{player_id}, {len(result['synced_tables'])}개 테이블")
        
        return result
    
    def merge_players(
        self,
        target_player_id: int,
        source_player_ids: List[int]
    ) -> Dict[str, Any]:
        """
        동명이인 병합
        
        source_player_ids의 모든 기록을 target_player_id로 병합
        """
        result = {
            "target_player_id": target_player_id,
            "merged_player_ids": source_player_ids,
            "merged_records": [],
            "errors": [],
        }
        
        if not self.db:
            result["errors"].append("DB 연결 없음")
            return result
        
        for source_id in source_player_ids:
            try:
                # 경기 기록 이전
                tables_to_update = [
                    ("matches", "player1_id"),
                    ("matches", "player2_id"),
                    ("matches", "winner_id"),
                    ("rankings", "player_id"),
                    ("members", "player_id"),
                ]
                
                for table, field in tables_to_update:
                    update_result = self.db.table(table).update({
                        field: target_player_id,
                        "updated_at": datetime.now().isoformat()
                    }).eq(field, source_id).execute()
                    
                    if update_result.data:
                        result["merged_records"].append({
                            "table": table,
                            "field": field,
                            "count": len(update_result.data)
                        })
                
                # 소스 선수 비활성화
                self.db.table("players").update({
                    "is_active": False,
                    "merged_into": target_player_id,
                    "updated_at": datetime.now().isoformat()
                }).eq("id", source_id).execute()
                
                logger.info(f"✅ 선수 병합: {source_id} → {target_player_id}")
            
            except Exception as e:
                result["errors"].append({
                    "source_id": source_id,
                    "error": str(e)
                })
                logger.error(f"❌ 선수 병합 실패: {source_id} - {e}")
        
        return result
    
    def split_player(
        self,
        player_id: int,
        match_ids_to_split: List[int]
    ) -> Dict[str, Any]:
        """
        동명이인 분리
        
        특정 경기들을 새로운 선수로 분리
        """
        result = {
            "original_player_id": player_id,
            "new_player_id": None,
            "split_records": [],
            "errors": [],
        }
        
        if not self.db:
            result["errors"].append("DB 연결 없음")
            return result
        
        try:
            # 원본 선수 정보 조회
            player_result = self.db.table("players").select("*").eq(
                "id", player_id
            ).execute()
            
            if not player_result.data:
                result["errors"].append(f"선수를 찾을 수 없음: {player_id}")
                return result
            
            original_player = player_result.data[0]
            
            # 새 선수 생성 (이름에 접미사 추가)
            new_player_data = {
                "name": f"{original_player['name']} (2)",
                "team": original_player.get("team"),
                "birth_year": original_player.get("birth_year"),
                "nationality": original_player.get("nationality", "KOR"),
                "is_active": True,
                "split_from": player_id,
            }
            
            new_player_result = self.db.table("players").insert(new_player_data).execute()
            
            if new_player_result.data:
                new_player_id = new_player_result.data[0]["id"]
                result["new_player_id"] = new_player_id
                
                # 지정된 경기들을 새 선수로 이전
                for match_id in match_ids_to_split:
                    match_result = self.db.table("matches").select(
                        "player1_id", "player2_id", "winner_id"
                    ).eq("id", match_id).execute()
                    
                    if match_result.data:
                        match = match_result.data[0]
                        updates = {}
                        
                        if match["player1_id"] == player_id:
                            updates["player1_id"] = new_player_id
                        if match["player2_id"] == player_id:
                            updates["player2_id"] = new_player_id
                        if match["winner_id"] == player_id:
                            updates["winner_id"] = new_player_id
                        
                        if updates:
                            updates["updated_at"] = datetime.now().isoformat()
                            self.db.table("matches").update(updates).eq(
                                "id", match_id
                            ).execute()
                            
                            result["split_records"].append({
                                "match_id": match_id,
                                "fields_updated": list(updates.keys())
                            })
                
                logger.info(f"✅ 선수 분리: {player_id} → 신규 {new_player_id}")
        
        except Exception as e:
            result["errors"].append(str(e))
            logger.error(f"❌ 선수 분리 실패: {e}")
        
        return result
    
    def get_sync_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """최근 동기화 로그 조회"""
        return self._sync_log[-limit:]
