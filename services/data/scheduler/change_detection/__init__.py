"""
변경 감지 시스템 (Change Detection System)

협회 사이트의 대회 결과 변경을 실시간으로 감지하여
변경된 종목만 선택적으로 스크래핑합니다.

주요 컴포넌트:
- EventFingerprint: 종목 상태 지문 (Pool/DE/순위 정보)
- ChangeDetector: 변경 감지 로직
- StateManager: 상태 저장 및 비교
"""

from .fingerprint import EventFingerprint, CompetitionFingerprint
from .detector import ChangeDetector
from .state_manager import StateManager

__all__ = [
    'EventFingerprint',
    'CompetitionFingerprint',
    'ChangeDetector',
    'StateManager',
]
