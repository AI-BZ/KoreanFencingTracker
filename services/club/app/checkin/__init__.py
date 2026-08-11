"""
Checkin Module

멀티 체크인/체크아웃 시스템
- IP 기반 자동 체크인
- WiFi 기반 체크인
- QR 코드 체크인
- GPS 위치 체크인
- 코치 대리 체크인
"""

from .router import router as checkin_router

__all__ = ["checkin_router"]
