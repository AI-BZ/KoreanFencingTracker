"""
Sync Module - 데이터 서비스 동기화

- app_player_cache 테이블에 선수 데이터 배치 동기화
- N+1 HTTP 호출 문제 해결 (로스터 조회 시 캐시 활용)
- data 서비스(포트 71) webhook 연동
- 동기화 로그 관리
"""

from .router import router as sync_router

__all__ = ["sync_router"]
