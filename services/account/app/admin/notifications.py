"""
관리자 - 알림 관리 라우터

회원용 알림 목록 조회, 읽음 처리, 개수 API.
알림 발송은 members.py에서 처리.
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from loguru import logger
from pathlib import Path

from shared_core.auth.jwt import get_current_member
from shared_core.db.client import get_supabase_client
from app.i18n.middleware import create_language_context

router = APIRouter(tags=["notifications"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


@router.get("/account/notifications", response_class=HTMLResponse)
async def list_notifications(request: Request, page: int = 1, limit: int = 20):
    """회원용 알림 목록 페이지"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    supabase = get_supabase_client()
    member_id = str(member["id"])

    offset = (page - 1) * limit
    result = (
        supabase.table("notifications")
        .select("*", count="exact")
        .eq("recipient_id", member_id)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    notifications = result.data or []
    total = result.count or 0

    return _templates.TemplateResponse("notifications/list.html", {
        "request": request,
        "member": member,
        "notifications": notifications,
        "total": total,
        "page": page,
        "limit": limit,
        **create_language_context(request),
    })


@router.post("/account/notifications/{notification_id}/read")
async def mark_notification_read(request: Request, notification_id: str):
    """알림 읽음 처리"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    supabase = get_supabase_client()
    member_id = str(member["id"])

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    result = (
        supabase.table("notifications")
        .update({"is_read": True, "read_at": now})
        .eq("id", notification_id)
        .eq("recipient_id", member_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다")

    return {"detail": "읽음 처리 완료"}


@router.get("/account/notifications/unread-count")
async def unread_count(request: Request):
    """읽지 않은 알림 개수 API (헤더 벨 아이콘용)"""
    member = await get_current_member(request)
    if not member:
        return JSONResponse({"count": 0})

    supabase = get_supabase_client()
    member_id = str(member["id"])

    result = (
        supabase.table("notifications")
        .select("id", count="exact")
        .eq("recipient_id", member_id)
        .eq("is_read", False)
        .execute()
    )

    return {"count": result.count or 0}
