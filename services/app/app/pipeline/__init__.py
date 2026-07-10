"""이벤트 파이프라인 (Phase 3).

data 서비스의 `data_events` 테이블을 폴링하여 알림을 생성/디스패치한다.

- event_types.py : data_events.event_type → 알림 카테고리 매핑 + 메시지 빌더
- dispatcher.py  : NotificationDispatcher (대상 결정 → 설정 확인 → 채널 발송/기록)
- poller.py      : EventPoller (워터마크 기반 30초 폴링 루프)

발송 채널:
- in_app        : Phase 3 활성 (notifications 테이블 insert)
- web_push      : Phase 4 (FCM) — 현재 graceful no-op (키 없으면 pending 기록)
- kakao_alimtalk: Phase 6 — 현재 graceful no-op
"""
from .dispatcher import NotificationDispatcher
from .poller import EventPoller

__all__ = ["NotificationDispatcher", "EventPoller"]
