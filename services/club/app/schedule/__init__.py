"""
Schedule Module - 클럽/코치/개인 일정 관리

- 클럽 전체 일정 (훈련, 대회, 행사, 휴일)
- 코치별 레슨/미팅 일정
- 개인 일정
- 반복 일정 지원
- FullCalendar.js 연동 API
"""

from .router import router as schedule_router

__all__ = ["schedule_router"]
