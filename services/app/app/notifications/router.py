"""알림 설정 라우터 (Phase 2).

페이지:
    GET    /notifications/settings        → 설정 UI (로그인 필수)
API:
    GET    /api/notifications/prefs        → 현재 설정 조회
    PATCH  /api/notifications/prefs        → 카테고리별 설정 변경
    POST   /api/notifications/subscribe    → 웹 푸시 구독 등록
    DELETE /api/notifications/subscribe    → 웹 푸시 구독 해제

인증: shared_core.auth.jwt.get_current_member (로컬 JWT 디코드).
미로그인 HTML 요청은 server.py의 401 핸들러가 /auth/login으로 리다이렉트.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from shared_core.auth.jwt import get_current_member
from shared_core.i18n import create_language_context

from ..config import settings
from . import service

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["notifications"])


async def _require_member(request: Request) -> dict:
    """로그인 필수. 미인증 시 401 (server.py 핸들러가 HTML이면 로그인 리다이렉트)."""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return member


# ---------------------------------------------------------------- 페이지


@router.get("/notifications/settings")
async def settings_page(request: Request):
    member = await _require_member(request)
    preferences = service.get_preferences(str(member["id"]))
    return templates.TemplateResponse(
        "notifications/settings.html",
        {
            "request": request,
            "member": member,
            "preferences": preferences,
            "vapid_public_key": settings.FCM_VAPID_PUBLIC_KEY,
            **create_language_context(request),
        },
    )


# ---------------------------------------------------------------- 설정 API


@router.get("/api/notifications/prefs")
async def get_prefs(request: Request):
    member = await _require_member(request)
    return {"preferences": service.get_preferences(str(member["id"]))}


class PrefUpdate(BaseModel):
    category: str
    web_push: bool
    kakao_alimtalk: bool
    in_app: bool


@router.patch("/api/notifications/prefs")
async def patch_prefs(request: Request, body: PrefUpdate):
    member = await _require_member(request)
    try:
        updated = service.update_preference(
            str(member["id"]),
            body.category,
            {
                "web_push": body.web_push,
                "kakao_alimtalk": body.kakao_alimtalk,
                "in_app": body.in_app,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "preference": updated}


# ---------------------------------------------------------------- 구독 API


class PushSubscribe(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    fcm_token: Optional[str] = None


@router.post("/api/notifications/subscribe")
async def subscribe(request: Request, body: PushSubscribe):
    member = await _require_member(request)
    sub = service.save_push_subscription(
        str(member["id"]),
        endpoint=body.endpoint,
        p256dh=body.p256dh,
        auth=body.auth,
        fcm_token=body.fcm_token,
        user_agent=request.headers.get("user-agent"),
    )
    return {"ok": True, "subscription_id": sub.get("id")}


class PushUnsubscribe(BaseModel):
    endpoint: str


@router.delete("/api/notifications/subscribe")
async def unsubscribe(request: Request, body: PushUnsubscribe):
    member = await _require_member(request)
    ok = service.remove_push_subscription(str(member["id"]), body.endpoint)
    return {"ok": ok}
