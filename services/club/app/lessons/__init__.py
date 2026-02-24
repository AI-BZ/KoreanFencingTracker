"""
Lessons Module - 레슨 패키지 & 예약 시스템

- 레슨 패키지 구매/차감/잔여 관리
- 레슨 신청/승인/거절/시간변경
- 코치 빈 시간 조회 (개인정보 마스킹)
- 공강 알림 구독
"""

from .router import router as lessons_router

__all__ = ["lessons_router"]
