"""data_events.event_type → 알림 카테고리 매핑 + 메시지 빌더.

data 서비스의 EventPublisher가 발행하는 event_type
(services/data/data_pipeline/events.py 의 EventType) 중
사용자 알림으로 의미가 있는 것만 카테고리로 매핑한다.
나머지(pipeline.*, validation.*, *.deleted 등)는 None → 디스패치 건너뜀.
"""
from __future__ import annotations

from typing import Optional

# 알림 카테고리 (app_notification_preferences.category 와 일치)
CATEGORY_COMPETITION_RESULT = "competition_result"
CATEGORY_RANKING_CHANGE = "ranking_change"

# data_events.event_type → 카테고리
#
# 매핑 비대칭 주의 (의도된 설계):
#   - `event.created`는 의도적으로 미매핑한다. 종목(event) 생성 시점엔 아직 결과가 없어
#     알림 대상이 아니다. 결과가 채워지는 `event.updated`에서만 competition_result 알림을 보낸다.
#   - 반면 `competition.created`는 매핑한다. 대회(competition) 생성은 일정 공지 성격이라
#     생성 시점에도 사용자에게 알릴 가치가 있다 (개별 종목 결과와는 다른 레벨).
EVENT_TYPE_TO_CATEGORY: dict[str, str] = {
    "ranking.updated": CATEGORY_RANKING_CHANGE,
    "competition.created": CATEGORY_COMPETITION_RESULT,
    "competition.updated": CATEGORY_COMPETITION_RESULT,
    "event.updated": CATEGORY_COMPETITION_RESULT,
}

# 데이터 도메인 (알림 링크용)
DATA_BASE_URL = "https://data.fencingmind.ai"


def category_for_event(event_type: str) -> Optional[str]:
    """event_type에 해당하는 알림 카테고리. 매핑 없으면 None."""
    return EVENT_TYPE_TO_CATEGORY.get(event_type or "")


def build_message(event: dict) -> tuple[str, str, Optional[str]]:
    """(title, body, link_url) 생성.

    payload(`data`)가 불완전해도 안전한 기본 문구를 반환한다 (KeyError 없음).
    """
    event_type = event.get("event_type", "")
    data = event.get("data") or {}
    category = category_for_event(event_type)

    if category == CATEGORY_RANKING_CHANGE:
        name = data.get("player_name") or data.get("name") or "선수"
        title = "랭킹이 변동되었습니다"
        body = f"{name}님의 랭킹 정보가 업데이트되었습니다."
        return title, body, f"{DATA_BASE_URL}/rankings"

    if category == CATEGORY_COMPETITION_RESULT:
        comp = data.get("competition_name") or data.get("name") or "대회"
        title = "대회 결과가 업데이트되었습니다"
        body = f"{comp} 결과가 업데이트되었습니다."
        entity_id = event.get("entity_id")
        link = f"{DATA_BASE_URL}/competition/{entity_id}" if entity_id else DATA_BASE_URL
        return title, body, link

    return "FencingMind 알림", "새로운 소식이 있습니다.", DATA_BASE_URL
