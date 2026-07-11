"""App 서비스 전용 Supabase 클라이언트 (service_role 우선, anon 폴백).

app_* 테이블(app_push_subscriptions / app_notification_preferences /
app_notification_log / app_event_cursor)은 서버만 접근하는 내부 알림 인프라다.
migration 021의 RLS 정책은 anon에 전면 개방(USING(true))이라 anon 키가 유출되면
전 회원의 푸시 구독·설정·발송 이력이 노출/조작 가능하다(EVAL P1-5).

이를 잠그기 위해(migration 025) 서버는 RLS를 **우회**하는 service_role 키로 접근한다.
shared_core.db.client(anon 단일 클라이언트)는 공유 패키지라 수정할 수 없으므로,
app 내부에 service_role 전용 로컬 클라이언트를 신설한다.

동작:
- SUPABASE_SERVICE_KEY가 설정돼 있으면 그 키로 create_client(service_role) 싱글턴 반환.
- 없으면 shared_core의 anon 클라이언트로 폴백 → 키 발급 전에도 서버가 현재처럼 동작
  (하위호환). 폴백 시 warning을 1회만 남긴다(모듈 레벨 캐시로 반복 로그 방지).
- service_role 클라이언트 생성 자체가 실패하면 안전측으로 anon 폴백.

🔴 배포 순서(불변): 이 코드(A)를 먼저 배포해 service_role로 동작함을 확인한 뒤에만
   migration 025(B, RLS 잠금)를 적용한다. 폴백(anon) 상태에서 025를 적용하면
   anon 서버가 app_* 테이블에 접근하지 못해 죽는다.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from supabase import create_client

from shared_core.db.client import get_supabase_client

from .config import settings

logger = logging.getLogger("app.db")

# service_role 클라이언트 싱글턴. 폴백(anon)은 캐시하지 않는다 —
# 그래야 같은 프로세스에서 키가 나중에 주입돼도(테스트/재설정) service_role 경로를 탄다.
_app_client: Optional[Any] = None
# anon 폴백 경고를 1회만 남기기 위한 플래그(반복 로그 방지).
_fallback_warned = False


def _warn_fallback_once(reason: str) -> None:
    global _fallback_warned
    if _fallback_warned:
        return
    logger.warning(
        "app DB가 anon 키로 폴백합니다 (%s). service_role 미사용 상태 — "
        "migration 025(RLS 잠금)를 적용하면 서버가 app_* 테이블 접근에 실패한다. "
        "SUPABASE_SERVICE_KEY를 설정하고 이 경고가 사라진 것을 확인한 뒤에만 025를 적용할 것.",
        reason,
    )
    _fallback_warned = True


def get_app_db() -> Any:
    """app_* 테이블 접근용 Supabase 클라이언트를 반환한다.

    SUPABASE_SERVICE_KEY가 있으면 RLS를 우회하는 service_role 클라이언트(싱글턴),
    없으면 anon 클라이언트(shared_core 싱글턴)로 폴백한다.
    """
    global _app_client
    if _app_client is not None:
        return _app_client

    service_key = settings.SUPABASE_SERVICE_KEY
    url = settings.SUPABASE_URL
    if service_key and url:
        try:
            _app_client = create_client(url, service_key)
            logger.info("app DB: service_role 클라이언트 초기화 완료")
            return _app_client
        except Exception as exc:  # noqa: BLE001 - 생성 실패해도 서버는 살아야 함
            _warn_fallback_once(f"service_role 클라이언트 생성 실패: {exc}")
            return get_supabase_client()

    _warn_fallback_once("SUPABASE_SERVICE_KEY 미설정")
    return get_supabase_client()


def reset_app_db() -> None:
    """싱글턴/경고 상태 리셋 (테스트용)."""
    global _app_client, _fallback_warned
    _app_client = None
    _fallback_warned = False
