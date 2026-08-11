"""
Videos Module - 영상 코멘트

- YouTube 영상 공유 및 코멘트
- 타임스탬프 코멘트 (코치 전용)
- 댓글 스레딩
- 카테고리별 분류 (훈련, 대회, 드릴)
"""

from .router import router as videos_router

__all__ = ["videos_router"]
