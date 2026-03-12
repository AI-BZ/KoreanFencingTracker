"""
상태 관리자 (State Manager)

종목 지문을 저장하고 비교하여 변경 여부를 판단합니다.

저장소:
- 메모리 (기본): 세션 내에서 빠른 비교
- Supabase (선택): 영구 저장 및 감사 로그
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from loguru import logger

from .fingerprint import EventFingerprint, CompetitionFingerprint


@dataclass
class ChangeRecord:
    """변경 기록"""
    comp_cd: str
    sub_event_cd: str
    event_name: str
    change_type: str  # "pool_update", "de_update", "ranking_update", "new_event"
    old_fingerprint: Optional[EventFingerprint]
    new_fingerprint: EventFingerprint
    detected_at: datetime = field(default_factory=datetime.now)

    @property
    def changes_summary(self) -> Dict[str, Any]:
        """변경 요약"""
        if self.old_fingerprint is None:
            return {"type": "new_event", "event": self.event_name}

        return self.new_fingerprint.diff(self.old_fingerprint)

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'comp_cd': self.comp_cd,
            'sub_event_cd': self.sub_event_cd,
            'event_name': self.event_name,
            'change_type': self.change_type,
            'old_hash': self.old_fingerprint.state_hash if self.old_fingerprint else None,
            'new_hash': self.new_fingerprint.state_hash,
            'changes': self.changes_summary,
            'detected_at': self.detected_at.isoformat()
        }


class StateManager:
    """
    상태 관리자

    메모리와 선택적으로 Supabase에 상태를 저장합니다.
    """

    def __init__(self, use_db: bool = False):
        """
        Args:
            use_db: Supabase에 저장할지 여부
        """
        self.use_db = use_db

        # 메모리 저장소
        self._fingerprints: Dict[str, CompetitionFingerprint] = {}
        self._change_history: List[ChangeRecord] = []

        # DB 클라이언트 (지연 초기화)
        self._supabase = None

    def _get_supabase(self):
        """Supabase 클라이언트 지연 초기화"""
        if self._supabase is None and self.use_db:
            try:
                from supabase import create_client
                url = os.getenv("SUPABASE_URL")
                key = os.getenv("SUPABASE_KEY")
                if url and key:
                    self._supabase = create_client(url, key)
            except Exception as e:
                logger.warning(f"Supabase 연결 실패: {e}")
        return self._supabase

    def get_fingerprint(self, comp_cd: str) -> Optional[CompetitionFingerprint]:
        """저장된 대회 지문 조회"""
        return self._fingerprints.get(comp_cd)

    def save_fingerprint(self, fingerprint: CompetitionFingerprint) -> None:
        """대회 지문 저장"""
        self._fingerprints[fingerprint.comp_cd] = fingerprint
        logger.debug(
            f"지문 저장: {fingerprint.comp_cd} "
            f"({fingerprint.event_count}개 종목)"
        )

        # DB 저장 (선택적)
        if self.use_db:
            self._save_to_db(fingerprint)

    def compare_and_update(
        self,
        new_fingerprint: CompetitionFingerprint
    ) -> List[ChangeRecord]:
        """
        새 지문을 이전 지문과 비교하고 업데이트

        Returns:
            변경 기록 목록
        """
        comp_cd = new_fingerprint.comp_cd
        old_fingerprint = self._fingerprints.get(comp_cd)

        changes: List[ChangeRecord] = []

        if old_fingerprint is None:
            # 첫 번째 캡처: 모든 종목을 "신규"로 기록
            for sub_event_cd, event_fp in new_fingerprint.events.items():
                record = ChangeRecord(
                    comp_cd=comp_cd,
                    sub_event_cd=sub_event_cd,
                    event_name=event_fp.event_name,
                    change_type="new_event",
                    old_fingerprint=None,
                    new_fingerprint=event_fp
                )
                changes.append(record)
                self._change_history.append(record)

        else:
            # 기존 지문과 비교
            for sub_event_cd, new_event_fp in new_fingerprint.events.items():
                old_event_fp = old_fingerprint.events.get(sub_event_cd)

                if old_event_fp is None:
                    # 새로운 종목
                    record = ChangeRecord(
                        comp_cd=comp_cd,
                        sub_event_cd=sub_event_cd,
                        event_name=new_event_fp.event_name,
                        change_type="new_event",
                        old_fingerprint=None,
                        new_fingerprint=new_event_fp
                    )
                    changes.append(record)
                    self._change_history.append(record)

                elif new_event_fp.has_changed(old_event_fp):
                    # 변경된 종목
                    change_type = self._determine_change_type(
                        old_event_fp, new_event_fp
                    )
                    record = ChangeRecord(
                        comp_cd=comp_cd,
                        sub_event_cd=sub_event_cd,
                        event_name=new_event_fp.event_name,
                        change_type=change_type,
                        old_fingerprint=old_event_fp,
                        new_fingerprint=new_event_fp
                    )
                    changes.append(record)
                    self._change_history.append(record)

        # 새 지문 저장
        self.save_fingerprint(new_fingerprint)

        if changes:
            logger.info(
                f"변경 감지: {comp_cd} - {len(changes)}개 종목 변경"
            )
            for change in changes:
                logger.info(
                    f"  {change.event_name}: {change.change_type} "
                    f"[{change.old_fingerprint.state_hash if change.old_fingerprint else 'NEW'}"
                    f" → {change.new_fingerprint.state_hash}]"
                )

        return changes

    def _determine_change_type(
        self,
        old: EventFingerprint,
        new: EventFingerprint
    ) -> str:
        """변경 유형 결정"""
        # 최종 순위 변경 (우선)
        if new.final_ranking_rows != old.final_ranking_rows:
            if new.final_ranking_rows > 2 and old.final_ranking_rows <= 2:
                return "event_completed"  # 종목 종료
            return "ranking_update"

        # DE 변경
        if new.de_completed != old.de_completed:
            return "de_update"

        # Pool 변경
        if new.pool_vd_count != old.pool_vd_count:
            return "pool_update"

        # 기타 변경
        return "unknown_update"

    def get_changed_event_codes(
        self,
        new_fingerprint: CompetitionFingerprint
    ) -> List[str]:
        """
        변경된 종목 코드만 반환 (스크래핑 트리거용)
        """
        old_fingerprint = self._fingerprints.get(new_fingerprint.comp_cd)

        if old_fingerprint is None:
            # 첫 번째 캡처: 모든 종목 반환
            return list(new_fingerprint.events.keys())

        return new_fingerprint.get_changed_events(old_fingerprint)

    def get_recent_changes(
        self,
        hours: int = 24,
        comp_cd: Optional[str] = None
    ) -> List[ChangeRecord]:
        """최근 변경 기록 조회"""
        cutoff = datetime.now() - timedelta(hours=hours)

        records = [
            r for r in self._change_history
            if r.detected_at >= cutoff
        ]

        if comp_cd:
            records = [r for r in records if r.comp_cd == comp_cd]

        return records

    def get_statistics(self) -> Dict[str, Any]:
        """통계 정보"""
        total_changes = len(self._change_history)
        changes_by_type: Dict[str, int] = {}

        for record in self._change_history:
            changes_by_type[record.change_type] = (
                changes_by_type.get(record.change_type, 0) + 1
            )

        return {
            'competitions_tracked': len(self._fingerprints),
            'total_events_tracked': sum(
                fp.event_count for fp in self._fingerprints.values()
            ),
            'total_changes_detected': total_changes,
            'changes_by_type': changes_by_type,
            'recent_changes_24h': len(self.get_recent_changes(24))
        }

    def clear(self, comp_cd: Optional[str] = None) -> None:
        """상태 초기화"""
        if comp_cd:
            self._fingerprints.pop(comp_cd, None)
            self._change_history = [
                r for r in self._change_history
                if r.comp_cd != comp_cd
            ]
        else:
            self._fingerprints.clear()
            self._change_history.clear()

    def _save_to_db(self, fingerprint: CompetitionFingerprint) -> None:
        """Supabase에 저장"""
        supabase = self._get_supabase()
        if not supabase:
            return

        try:
            # event_fingerprints 테이블에 upsert
            for sub_event_cd, event_fp in fingerprint.events.items():
                data = {
                    'comp_cd': fingerprint.comp_cd,
                    'sub_event_cd': sub_event_cd,
                    'event_name': event_fp.event_name,
                    'pool_groups': event_fp.pool_groups,
                    'pool_rows': event_fp.pool_rows,
                    'pool_vd_count': event_fp.pool_vd_count,
                    'de_completed': event_fp.de_completed,
                    'de_cells': event_fp.de_cells,
                    'final_ranking_rows': event_fp.final_ranking_rows,
                    'state_hash': event_fp.state_hash,
                    'event_status': event_fp.event_status,
                    'captured_at': event_fp.captured_at.isoformat(),
                    'error': event_fp.error
                }

                supabase.table('event_fingerprints').upsert(
                    data,
                    on_conflict='comp_cd,sub_event_cd'
                ).execute()

        except Exception as e:
            logger.error(f"DB 저장 실패: {e}")

    def export_state(self) -> Dict[str, Any]:
        """전체 상태를 딕셔너리로 내보내기"""
        return {
            'fingerprints': {
                k: v.to_dict() for k, v in self._fingerprints.items()
            },
            'change_history': [r.to_dict() for r in self._change_history],
            'exported_at': datetime.now().isoformat()
        }

    def import_state(self, data: Dict[str, Any]) -> None:
        """딕셔너리에서 상태 가져오기"""
        self._fingerprints = {
            k: CompetitionFingerprint.from_dict(v)
            for k, v in data.get('fingerprints', {}).items()
        }
        # change_history는 import하지 않음 (새로 시작)
        logger.info(f"상태 가져오기 완료: {len(self._fingerprints)}개 대회")
