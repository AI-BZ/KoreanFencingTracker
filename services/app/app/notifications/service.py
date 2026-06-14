"""알림 설정 / 푸시 구독 비즈니스 로직 (Supabase CRUD).

소유 테이블 (Migration 021):
- app_notification_preferences : 회원별 카테고리/채널 on·off
    (member_id, category, web_push, kakao_alimtalk, in_app), UNIQUE(member_id, category)
- app_push_subscriptions       : FCM 웹 푸시 구독 + 카카오 사용자 ID

채널 발송 자체는 후속 Phase에서 구현된다.
이 모듈은 "설정 저장"과 "구독 등록"만 담당한다.
- in_app        : Phase 2 (notifications 테이블)
- web_push      : Phase 4 (FCM)
- kakao_alimtalk: Phase 6 (카카오 알림톡)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from shared_core.db.client import get_supabase_client

logger = logging.getLogger(__name__)

CHANNELS: tuple[str, ...] = ("web_push", "kakao_alimtalk", "in_app")

# 알림 카테고리 정의 + 기본값.
# locked=True 카테고리는 인앱 알림을 해제할 수 없다 (보안/시스템 공지).
NOTIFICATION_CATEGORIES: list[dict[str, Any]] = [
    {
        "category": "competition_result",
        "locked": False,
        "default": {"web_push": True, "kakao_alimtalk": False, "in_app": True},
    },
    {
        "category": "ranking_change",
        "locked": False,
        "default": {"web_push": True, "kakao_alimtalk": False, "in_app": True},
    },
    {
        "category": "club_notice",
        "locked": False,
        "default": {"web_push": True, "kakao_alimtalk": False, "in_app": True},
    },
    {
        "category": "attendance_reminder",
        "locked": False,
        "default": {"web_push": True, "kakao_alimtalk": False, "in_app": True},
    },
    {
        "category": "system",
        "locked": True,
        "default": {"web_push": True, "kakao_alimtalk": False, "in_app": True},
    },
]

CATEGORY_KEYS: set[str] = {c["category"] for c in NOTIFICATION_CATEGORIES}
LOCKED_CATEGORIES: set[str] = {c["category"] for c in NOTIFICATION_CATEGORIES if c["locked"]}
_DEFAULTS: dict[str, dict[str, bool]] = {c["category"]: c["default"] for c in NOTIFICATION_CATEGORIES}
_LOCKED_MAP: dict[str, bool] = {c["category"]: c["locked"] for c in NOTIFICATION_CATEGORIES}


def get_preferences(member_id: str) -> list[dict[str, Any]]:
    """회원의 모든 카테고리 설정을 기본값과 병합해 반환.

    저장된 행이 없는 카테고리는 기본값으로 채워 항상 전체 카테고리를 돌려준다.
    """
    supabase = get_supabase_client()
    rows = (
        supabase.table("app_notification_preferences")
        .select("category, web_push, kakao_alimtalk, in_app")
        .eq("member_id", member_id)
        .execute()
    )
    saved = {r["category"]: r for r in (rows.data or [])}

    result: list[dict[str, Any]] = []
    for category in CATEGORY_KEYS_ORDERED():
        row = saved.get(category)
        defaults = _DEFAULTS[category]
        channels = {
            ch: (bool(row[ch]) if row is not None and row.get(ch) is not None else defaults[ch])
            for ch in CHANNELS
        }
        if _LOCKED_MAP[category]:
            channels["in_app"] = True  # locked 카테고리는 인앱 강제
        result.append({"category": category, "locked": _LOCKED_MAP[category], **channels})
    return result


def CATEGORY_KEYS_ORDERED() -> list[str]:
    """정의 순서를 유지한 카테고리 키 목록."""
    return [c["category"] for c in NOTIFICATION_CATEGORIES]


def update_preference(member_id: str, category: str, channels: dict[str, bool]) -> dict[str, Any]:
    """단일 카테고리의 채널 설정을 upsert.

    Args:
        channels: {"web_push": bool, "kakao_alimtalk": bool, "in_app": bool} (전체 채널 전달).
    Raises:
        ValueError: 알 수 없는 카테고리/채널.
    """
    if category not in CATEGORY_KEYS:
        raise ValueError(f"알 수 없는 카테고리: {category}")

    payload: dict[str, Any] = {"member_id": member_id, "category": category}
    for ch in CHANNELS:
        if ch in channels:
            payload[ch] = bool(channels[ch])
    for ch in channels:
        if ch not in CHANNELS:
            raise ValueError(f"알 수 없는 채널: {ch}")

    # locked 카테고리는 인앱 알림 해제 불가
    if category in LOCKED_CATEGORIES:
        payload["in_app"] = True

    supabase = get_supabase_client()
    res = (
        supabase.table("app_notification_preferences")
        .upsert(payload, on_conflict="member_id,category")
        .execute()
    )
    return res.data[0] if res.data else payload


def save_push_subscription(
    member_id: str,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    fcm_token: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> dict[str, Any]:
    """웹 푸시 구독 등록/재활성화 (endpoint 기준 dedup).

    실제 발송은 Phase 4(FCM)에서 이 구독 정보를 사용한다.
    """
    supabase = get_supabase_client()
    payload: dict[str, Any] = {
        "member_id": member_id,
        "fcm_token": fcm_token,
        "fcm_endpoint": endpoint,
        "fcm_p256dh": p256dh,
        "fcm_auth": auth,
        "device_type": "web",
        "user_agent": user_agent,
        "is_active": True,
    }

    existing = (
        supabase.table("app_push_subscriptions")
        .select("id")
        .eq("member_id", member_id)
        .eq("fcm_endpoint", endpoint)
        .limit(1)
        .execute()
    )
    if existing.data:
        sub_id = existing.data[0]["id"]
        res = (
            supabase.table("app_push_subscriptions")
            .update(payload)
            .eq("id", sub_id)
            .execute()
        )
        return res.data[0] if res.data else {"id": sub_id, **payload}

    res = supabase.table("app_push_subscriptions").insert(payload).execute()
    return res.data[0] if res.data else payload


def remove_push_subscription(member_id: str, endpoint: str) -> bool:
    """endpoint에 해당하는 구독을 비활성화 (soft delete)."""
    supabase = get_supabase_client()
    res = (
        supabase.table("app_push_subscriptions")
        .update({"is_active": False})
        .eq("member_id", member_id)
        .eq("fcm_endpoint", endpoint)
        .execute()
    )
    return bool(res.data)
