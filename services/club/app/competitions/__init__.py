"""
Competitions Module - 대회 참가 관리

- 대회 이벤트 등록/관리 (수동 + 자동 동기화)
- RSVP 참석 응답 (attending/not_attending/maybe)
- 비용 정산 (참가비, 코치 교통비, 교통비 1/N)
- data 서비스 webhook 연동
"""

from .router import router as competitions_router

__all__ = ["competitions_router"]
