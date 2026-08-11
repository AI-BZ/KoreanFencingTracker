"""
Notifications Module - FCM Push + Kakao Alimtalk

- FCM Web Push (PWA, 무료, iOS 16.4+ 지원)
- Kakao Alimtalk (유료, 구독 등급별 한도 관리)
- 앱 내 알림 기록
"""

from .router import router as notifications_router

__all__ = ["notifications_router"]
