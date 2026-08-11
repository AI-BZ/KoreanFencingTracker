"""
Player Data Module

선수 데이터 연동 - 클럽 관리 SaaS의 핵심 기능
- 선수 검색 및 회원 연결
- 대회 히스토리 조회
- 랭킹 추적
- 상대 전적
- 성과 분석
"""

from .router import router as players_router
from .service import player_service

__all__ = ["players_router", "player_service"]
