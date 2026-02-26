"""
Settings Module - 클럽 프로필 관리 + 회원 승인 플로우

- 클럽 프로필 (이름, 주소, 연락처, 로고)
- 체크인 설정 (IP, WiFi, QR, Geofence)
- 비용 기본값
- 회원 승인/거절 관리
- 회원 통계
"""

from .router import router as settings_router

__all__ = ["settings_router"]
