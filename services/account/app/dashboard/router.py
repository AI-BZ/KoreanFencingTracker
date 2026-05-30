"""
대시보드 라우터

통합 계정 대시보드 - 프로필, 인증 상태, 구독 관리, 결제 수단
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from shared_core.auth.jwt import get_current_member
from shared_core.auth.subscription import get_all_member_tiers, get_service_info
from shared_core.db.client import get_supabase_client
from app.messenger.service import build_messenger_context
from app.i18n.middleware import create_language_context

router = APIRouter(prefix="/account", tags=["dashboard"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """통합 계정 대시보드"""
    member = await get_current_member(request)
    if not member:
        return HTMLResponse(
            content='<script>window.location.href="/auth/login?redirect=/account/dashboard";</script>',
            status_code=200,
        )

    member_id = str(member["id"])
    supabase = get_supabase_client()

    # 서비스 정의 + 구독 등급 조회
    services = get_service_info()
    tiers = await get_all_member_tiers(member_id)

    # 전체 구독 목록 (settings, expires_at 포함)
    subs_result = (
        supabase.table("member_services")
        .select("*")
        .eq("member_id", member_id)
        .execute()
    )
    subscriptions = {s["service_id"]: s for s in (subs_result.data or [])}

    # Stripe 고객 정보 (결제수단)
    stripe_customer = None
    try:
        sc_result = (
            supabase.table("stripe_customers")
            .select("stripe_customer_id, default_payment_method_id")
            .eq("member_id", member_id)
            .execute()
        )
        if sc_result.data:
            stripe_customer = sc_result.data[0]
    except Exception:
        pass

    # OAuth 연결 목록
    oauth_result = (
        supabase.table("oauth_connections")
        .select("provider, provider_email, is_primary, created_at")
        .eq("member_id", member_id)
        .execute()
    )
    oauth_connections = oauth_result.data or []

    # 메신저 연결 상태
    messenger = build_messenger_context(member)

    return _templates.TemplateResponse("account/dashboard.html", {
        "request": request,
        "member": member,
        "services": services,
        "tiers": tiers,
        "subscriptions": subscriptions,
        "stripe_customer": stripe_customer,
        "oauth_connections": oauth_connections,
        "messenger": messenger,
        **create_language_context(request),
    })
