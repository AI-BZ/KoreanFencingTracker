"""EventPoller — data_events 워터마크 기반 폴링 루프.

app_event_cursor.last_event_id 이후의 새 data_events 행을 가져와
NotificationDispatcher로 처리하고, 워터마크를 전진시킨다.

설계:
- supabase-py는 동기 클라이언트 → poll_once()는 동기, run()에서 asyncio.to_thread로 호출
  (이벤트 루프 블로킹 방지).
- 배치 내 개별 dispatch 실패는 로그만 남기고 계속 → "poison event"가 큐를 막지 않음.
  워터마크는 배치의 최대 id로 전진 (한 번 본 이벤트는 다시 보지 않음).
- run()은 asyncio.CancelledError로 graceful shutdown.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shared_core.db.client import get_supabase_client

from ..config import settings
from .dispatcher import NotificationDispatcher

logger = logging.getLogger("app.pipeline.poller")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventPoller:
    def __init__(
        self,
        interval: int = 30,
        batch_size: int = 100,
        dispatcher: Optional[NotificationDispatcher] = None,
        supabase: Any = None,
    ):
        self.interval = interval
        self.batch_size = batch_size
        self._dispatcher = dispatcher
        self._db = supabase

    @property
    def db(self) -> Any:
        if self._db is None:
            self._db = get_supabase_client()
        return self._db

    @property
    def dispatcher(self) -> NotificationDispatcher:
        if self._dispatcher is None:
            self._dispatcher = NotificationDispatcher(self.db)
        return self._dispatcher

    # ------------------------------------------------------------- cursor

    def _read_cursor(self) -> tuple[int, int]:
        """(last_event_id, events_processed). 커서 행 없으면 생성."""
        res = (
            self.db.table("app_event_cursor")
            .select("last_event_id, events_processed")
            .eq("id", 1)
            .limit(1)
            .execute()
        )
        if res.data:
            row = res.data[0]
            return int(row.get("last_event_id") or 0), int(row.get("events_processed") or 0)
        self.db.table("app_event_cursor").upsert({"id": 1, "last_event_id": 0}).execute()
        return 0, 0

    def _advance_cursor(self, last_event_id: int, events_processed: int) -> None:
        self.db.table("app_event_cursor").update(
            {
                "last_event_id": last_event_id,
                "events_processed": events_processed,
                "last_polled_at": _now_iso(),
            }
        ).eq("id", 1).execute()

    def _touch_cursor(self) -> None:
        self.db.table("app_event_cursor").update({"last_polled_at": _now_iso()}).eq("id", 1).execute()

    # ------------------------------------------------------------- polling

    def poll_once(self) -> dict:
        """한 배치 폴링 + 디스패치. (동기 — to_thread로 호출)."""
        last_id, processed_total = self._read_cursor()
        # 안전 지연: created_at이 (now - safety_lag) 이하인 이벤트만 처리한다.
        # BIGSERIAL id의 커밋 순서 무보장으로 늦게 커밋된 낮은 id가 누락되는 것을 방지 (P1-2).
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=settings.EVENT_SAFETY_LAG_SECONDS)
        ).isoformat()
        res = (
            self.db.table("data_events")
            .select("*")
            .gt("id", last_id)
            .lte("created_at", cutoff)
            .order("id")
            .limit(self.batch_size)
            .execute()
        )
        events = res.data or []
        if not events:
            self._touch_cursor()
            return {"polled": 0, "dispatched": 0, "last_id": last_id}

        dispatched = 0
        new_last = last_id
        for ev in events:
            try:
                summary = self.dispatcher.dispatch(ev)
                dispatched += summary.get("in_app", 0)
            except Exception as exc:  # noqa: BLE001 - 한 이벤트 실패가 루프를 막지 않음
                logger.error("디스패치 실패 event=%s: %s", ev.get("id"), exc)
            try:
                new_last = max(new_last, int(ev["id"]))
            except (KeyError, TypeError, ValueError):
                pass

        self._advance_cursor(new_last, processed_total + len(events))
        return {"polled": len(events), "dispatched": dispatched, "last_id": new_last}

    # ------------------------------------------------------------- loop

    async def run(self) -> None:
        """30초 간격 폴링 루프. 서버 lifespan에서 create_task로 기동."""
        logger.info("EventPoller 시작 (interval=%ss, batch=%s)", self.interval, self.batch_size)
        try:
            while True:
                try:
                    result = await asyncio.to_thread(self.poll_once)
                    if result.get("polled"):
                        logger.info(
                            "polled=%s dispatched=%s last_id=%s",
                            result["polled"], result["dispatched"], result["last_id"],
                        )
                except Exception as exc:  # noqa: BLE001 - 루프는 계속 살아있어야 함
                    logger.error("폴 루프 오류: %s", exc)
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            logger.info("EventPoller 중지 (shutdown)")
            raise
