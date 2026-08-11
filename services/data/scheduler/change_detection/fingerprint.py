"""
종목 상태 지문 (Event Fingerprint)

협회 사이트에서 추출한 종목 상태를 경량화된 지문으로 표현합니다.
이 지문을 비교하여 변경 여부를 빠르게 판단합니다.
"""

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List


@dataclass
class EventFingerprint:
    """
    종목 상태 지문

    협회 사이트에서 추출한 경량 지표:
    - Pool: 그룹 수, 행 수, V/D 결과 수
    - DE: 완료된 경기 수
    - 최종순위: 행 수

    이 값들로 해시를 생성하여 변경 여부를 판단합니다.
    """
    # 식별 정보
    sub_event_cd: str
    event_name: str

    # Pool 지표
    pool_groups: int = 0          # Pool 그룹 수
    pool_rows: int = 0            # Pool 테이블 총 행 수
    pool_vd_count: int = 0        # V/D 결과 수 (실제 경기 완료 수)

    # DE 지표
    de_completed: int = 0         # DE 완료된 경기 수
    de_cells: int = 0             # DE 대진표 셀 수 (구조 확인용)

    # 최종 순위 지표
    final_ranking_rows: int = 0   # 최종 순위 테이블 행 수

    # 메타데이터
    captured_at: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None   # 추출 실패 시 에러 메시지

    @property
    def state_tuple(self) -> tuple:
        """상태를 튜플로 반환 (해시 생성용)"""
        return (
            self.pool_groups,
            self.pool_rows,
            self.pool_vd_count,
            self.de_completed,
            self.final_ranking_rows
        )

    @property
    def state_hash(self) -> str:
        """상태 해시 생성 (8자리)"""
        state_str = "-".join(map(str, self.state_tuple))
        return hashlib.md5(state_str.encode()).hexdigest()[:8]

    @property
    def is_valid(self) -> bool:
        """유효한 지문인지 확인"""
        return self.error is None

    @property
    def has_pool_data(self) -> bool:
        """Pool 데이터 존재 여부"""
        return self.pool_groups > 0 or self.pool_vd_count > 0

    @property
    def has_de_data(self) -> bool:
        """DE 데이터 존재 여부"""
        return self.de_completed > 0 or self.de_cells > 0

    @property
    def has_final_ranking(self) -> bool:
        """최종 순위 존재 여부 (종목 완료)"""
        return self.final_ranking_rows > 2  # 헤더 제외 실제 순위 있음

    @property
    def event_status(self) -> str:
        """종목 진행 상태 추정"""
        if self.has_final_ranking:
            return "completed"  # 종료됨
        elif self.has_de_data:
            return "de_in_progress"  # DE 진행 중
        elif self.has_pool_data:
            return "pool_in_progress"  # Pool 진행 중
        else:
            return "not_started"  # 시작 전

    def diff(self, other: 'EventFingerprint') -> Dict[str, Any]:
        """다른 지문과의 차이 계산"""
        if not isinstance(other, EventFingerprint):
            raise ValueError("EventFingerprint와만 비교 가능")

        changes = {}

        # Pool 변경
        if self.pool_vd_count != other.pool_vd_count:
            changes['pool_vd'] = {
                'old': other.pool_vd_count,
                'new': self.pool_vd_count,
                'diff': self.pool_vd_count - other.pool_vd_count
            }

        # DE 변경
        if self.de_completed != other.de_completed:
            changes['de_completed'] = {
                'old': other.de_completed,
                'new': self.de_completed,
                'diff': self.de_completed - other.de_completed
            }

        # 최종 순위 변경
        if self.final_ranking_rows != other.final_ranking_rows:
            changes['final_ranking'] = {
                'old': other.final_ranking_rows,
                'new': self.final_ranking_rows,
                'diff': self.final_ranking_rows - other.final_ranking_rows
            }

        return changes

    def has_changed(self, other: 'EventFingerprint') -> bool:
        """변경 여부 확인"""
        return self.state_hash != other.state_hash

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        data = asdict(self)
        data['captured_at'] = self.captured_at.isoformat()
        data['state_hash'] = self.state_hash
        data['event_status'] = self.event_status
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EventFingerprint':
        """딕셔너리에서 생성"""
        # captured_at 변환
        if 'captured_at' in data and isinstance(data['captured_at'], str):
            data['captured_at'] = datetime.fromisoformat(data['captured_at'])

        # 불필요한 필드 제거
        data.pop('state_hash', None)
        data.pop('event_status', None)

        return cls(**data)

    def __str__(self) -> str:
        return (
            f"{self.event_name} [{self.state_hash}] "
            f"Pool:{self.pool_vd_count} DE:{self.de_completed} "
            f"Final:{self.final_ranking_rows} ({self.event_status})"
        )


@dataclass
class CompetitionFingerprint:
    """
    대회 상태 지문

    대회 내 모든 종목의 지문을 포함합니다.
    """
    # 식별 정보
    comp_cd: str
    comp_name: str

    # 종목별 지문
    events: Dict[str, EventFingerprint] = field(default_factory=dict)

    # 메타데이터
    captured_at: datetime = field(default_factory=datetime.now)
    detection_duration_ms: int = 0  # 감지 소요 시간 (밀리초)
    error: Optional[str] = None

    @property
    def event_count(self) -> int:
        """종목 수"""
        return len(self.events)

    @property
    def valid_event_count(self) -> int:
        """유효한 종목 수"""
        return sum(1 for e in self.events.values() if e.is_valid)

    @property
    def combined_hash(self) -> str:
        """모든 종목 해시를 결합한 대회 해시"""
        hashes = sorted([e.state_hash for e in self.events.values()])
        combined = "-".join(hashes)
        return hashlib.md5(combined.encode()).hexdigest()[:12]

    def get_changed_events(self, other: 'CompetitionFingerprint') -> List[str]:
        """변경된 종목 코드 목록 반환"""
        changed = []

        for sub_event_cd, fingerprint in self.events.items():
            if sub_event_cd not in other.events:
                # 새로운 종목
                changed.append(sub_event_cd)
            elif fingerprint.has_changed(other.events[sub_event_cd]):
                # 변경된 종목
                changed.append(sub_event_cd)

        return changed

    def get_event_changes_summary(self, other: 'CompetitionFingerprint') -> Dict[str, Any]:
        """종목별 변경 요약"""
        summary = {
            'new_events': [],
            'changed_events': [],
            'unchanged_events': [],
            'removed_events': []
        }

        for sub_event_cd, fingerprint in self.events.items():
            if sub_event_cd not in other.events:
                summary['new_events'].append({
                    'sub_event_cd': sub_event_cd,
                    'name': fingerprint.event_name
                })
            elif fingerprint.has_changed(other.events[sub_event_cd]):
                diff = fingerprint.diff(other.events[sub_event_cd])
                summary['changed_events'].append({
                    'sub_event_cd': sub_event_cd,
                    'name': fingerprint.event_name,
                    'changes': diff,
                    'old_hash': other.events[sub_event_cd].state_hash,
                    'new_hash': fingerprint.state_hash
                })
            else:
                summary['unchanged_events'].append(sub_event_cd)

        # 삭제된 종목 (현재는 없지만 이전에 있던 것)
        for sub_event_cd in other.events:
            if sub_event_cd not in self.events:
                summary['removed_events'].append(sub_event_cd)

        return summary

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'comp_cd': self.comp_cd,
            'comp_name': self.comp_name,
            'events': {k: v.to_dict() for k, v in self.events.items()},
            'captured_at': self.captured_at.isoformat(),
            'detection_duration_ms': self.detection_duration_ms,
            'combined_hash': self.combined_hash,
            'error': self.error
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CompetitionFingerprint':
        """딕셔너리에서 생성"""
        events = {
            k: EventFingerprint.from_dict(v)
            for k, v in data.get('events', {}).items()
        }

        captured_at = data.get('captured_at')
        if isinstance(captured_at, str):
            captured_at = datetime.fromisoformat(captured_at)

        return cls(
            comp_cd=data['comp_cd'],
            comp_name=data['comp_name'],
            events=events,
            captured_at=captured_at or datetime.now(),
            detection_duration_ms=data.get('detection_duration_ms', 0),
            error=data.get('error')
        )

    def __str__(self) -> str:
        return (
            f"{self.comp_name} [{self.combined_hash}] "
            f"{self.valid_event_count}/{self.event_count} events"
        )
