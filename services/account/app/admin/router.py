"""
관리자 라우터 (메인)

RBAC 기반 관리자 권한 시스템으로 전환.
sub-routers: members, approvals, logs
기존 API 엔드포인트는 하위 호환성 유지.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from shared_core.auth.jwt import get_current_member, create_access_token
from shared_core.db.client import get_supabase_client

from .dependencies import require_admin as rbac_require_admin, log_admin_action, get_client_ip, _try_cf_access_auth
from .members import router as members_router
from .approvals import router as approvals_router
from .logs import router as logs_router
from app.i18n.middleware import create_language_context

router = APIRouter(prefix="/account/admin", tags=["admin"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))

# 하위 호환성: 기존 email 기반 fallback (RBAC 전환 완료 후 제거 가능)
ADMIN_EMAILS = ["admin@fencingmind.ai"]


async def _require_admin_compat(request: Request) -> dict:
    """
    관리자 확인 (Cloudflare Access + RBAC + email fallback)

    0) Cf-Access-Authenticated-User-Email 헤더 → 통과 (CF Access OTP)
    1) admin_role IS NOT NULL → 통과
    2) email in ADMIN_EMAILS → 통과 (하위 호환)
    3) member_type in (club_director, school_director) → 통과 (하위 호환)
    """
    # Cloudflare Access 인증 우선
    cf_admin = await _try_cf_access_auth(request)
    if cf_admin:
        return cf_admin

    # JWT 기반 인증
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    # RBAC 기반 확인
    if member.get("admin_role"):
        return member

    # 하위 호환: email 기반
    if member.get("email") in ADMIN_EMAILS:
        return member

    # 하위 호환: 감독급
    if member.get("member_type") in ("club_director", "school_director"):
        return member

    raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다")


# =============================================
# Sub-routers 등록
# =============================================
router.include_router(members_router)
router.include_router(approvals_router)
router.include_router(logs_router)


# =============================================
# 대시보드 (메인)
# =============================================

def _get_pending_count(supabase) -> int:
    """승인 대기 건수 합계"""
    try:
        v = supabase.table("verifications").select("id", count="exact").eq("status", "pending").execute()
        pc = supabase.table("player_claims").select("id", count="exact").eq("status", "pending").execute()
        oc = supabase.table("organization_claims").select("id", count="exact").in_("status", ["pending", "auto_verified"]).execute()
        return (v.count or 0) + (pc.count or 0) + (oc.count or 0)
    except Exception:
        return 0


@router.get("", include_in_schema=False)
async def admin_root():
    """/ → /dashboard 리다이렉트"""
    return RedirectResponse(url="/account/admin/dashboard", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """관리자 대시보드 - KPI, 승인 큐, 서비스 현황"""
    admin = await _require_admin_compat(request)
    supabase = get_supabase_client()

    # === KPI Stats ===
    total_members = supabase.table("members").select("id", count="exact").execute()

    # Today signups
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_signups = (
        supabase.table("members")
        .select("id", count="exact")
        .gte("created_at", f"{today_str}T00:00:00")
        .execute()
    )

    # Paid subscriptions
    paid_subs = (
        supabase.table("member_services")
        .select("id", count="exact")
        .eq("status", "active")
        .neq("tier", "free")
        .execute()
    )

    # Pending approvals breakdown
    pending_verifications = supabase.table("verifications").select("id", count="exact").eq("status", "pending").execute()
    pending_player_claims = supabase.table("player_claims").select("id", count="exact").eq("status", "pending").execute()
    pending_org_claims = supabase.table("organization_claims").select("id", count="exact").in_("status", ["pending", "auto_verified"]).execute()

    v_count = pending_verifications.count or 0
    pc_count = pending_player_claims.count or 0
    oc_count = pending_org_claims.count or 0
    total_pending = v_count + pc_count + oc_count

    # === Service Stats ===
    service_stats = []
    try:
        svc_result = supabase.table("member_services").select("service_id, tier, status").execute()
        svc_map = {}
        for sub in (svc_result.data or []):
            sid = sub["service_id"]
            if sid not in svc_map:
                svc_map[sid] = {"name": sid, "total": 0, "paid": 0}
            svc_map[sid]["total"] += 1
            if sub["status"] == "active" and sub["tier"] != "free":
                svc_map[sid]["paid"] += 1
        service_stats = sorted(svc_map.values(), key=lambda x: x["total"], reverse=True)
    except Exception as e:
        logger.debug(f"service_stats fetch: {e}")

    # === Recent Activity ===
    recent_activity = []
    try:
        log_result = (
            supabase.table("admin_audit_logs")
            .select("*")
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        logs_raw = log_result.data or []

        # Enrich with admin names
        admin_ids = list(set(log.get("admin_id") for log in logs_raw if log.get("admin_id")))
        admin_names = {}
        if admin_ids:
            m_result = supabase.table("members").select("id, full_name").in_("id", admin_ids).execute()
            for m in (m_result.data or []):
                admin_names[m["id"]] = m["full_name"]

        for log in logs_raw:
            log["admin_name"] = admin_names.get(log.get("admin_id"), "")
        recent_activity = logs_raw
    except Exception as e:
        logger.debug(f"recent_activity fetch: {e}")

    response = _templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "admin": admin,
        "active_tab": "home",
        "pending_count": total_pending,
        "stats": {
            "total_members": total_members.count or 0,
            "today_signups": today_signups.count or 0,
            "paid_subscriptions": paid_subs.count or 0,
            "pending_approvals": total_pending,
        },
        "approval_summary": {
            "verification": v_count,
            "player_claim": pc_count,
            "org_claim": oc_count,
        },
        "service_stats": service_stats,
        "recent_activity": recent_activity,
        **create_language_context(request),
    })

    # CF Access admin에게 크로스 서비스 JWT 쿠키 발급
    # .fencingmind.ai 도메인 → data, club 등 모든 서브도메인에서 인식
    if admin.get("id"):
        _set_admin_jwt_cookie(response, admin)

    return response


def _set_admin_jwt_cookie(response, admin: dict):
    """관리자용 JWT 쿠키 설정 (크로스 서비스 인증)"""
    cookie_domain = os.getenv("COOKIE_DOMAIN", ".fencingmind.ai")

    access_token = create_access_token({
        "member_id": str(admin["id"]),
        "email": admin.get("email", ""),
        "member_type": admin.get("member_type", "general"),
    })

    # JWT - httpOnly (보안)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=True,
        max_age=60 * 60 * 24,  # 24시간
        samesite="lax",
        domain=cookie_domain,
    )

    # UI 표시용
    email = admin.get("email", "")
    display_info = quote(json.dumps({"email": email}, ensure_ascii=False))
    response.set_cookie(
        key="user_display",
        value=display_info,
        httponly=False,
        secure=True,
        max_age=60 * 60 * 24,
        samesite="lax",
        domain=cookie_domain,
    )


# =============================================
# 기존 API 엔드포인트 (하위 호환성 유지)
# =============================================

@router.get("/verifications")
async def list_pending_verifications(request: Request, status: str = "pending"):
    """인증 대기 건 목록 조회 (API - 하위 호환)"""
    await _require_admin_compat(request)
    supabase = get_supabase_client()

    result = (
        supabase.table("verifications")
        .select("*, members!inner(full_name, email, member_type)")
        .eq("status", status)
        .order("created_at", desc=False)
        .limit(50)
        .execute()
    )

    return result.data or []


@router.post("/verifications/{verification_id}/approve")
async def approve_verification(verification_id: str, request: Request):
    """인증 승인 (API - 하위 호환)"""
    admin = await _require_admin_compat(request)
    supabase = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()

    update_data = {
        "status": "approved",
        "admin_review": True,
        "processed_at": now,
    }
    if admin.get("id"):
        update_data["reviewed_by"] = str(admin["id"])

    result = supabase.table("verifications").update(update_data).eq("id", verification_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="인증 건을 찾을 수 없습니다")

    member_id = result.data[0].get("member_id")
    if member_id:
        supabase.table("members").update({
            "verification_status": "verified",
            "verified_at": now,
        }).eq("id", member_id).execute()

    # Audit log
    await log_admin_action(
        admin_id=admin.get("id"),
        action="approve",
        target_type="verification",
        target_id=verification_id,
        ip_address=get_client_ip(request),
    )

    logger.info(f"인증 승인: verification={verification_id}, admin={admin.get('email')}")
    return {"detail": "인증이 승인되었습니다"}


@router.post("/verifications/{verification_id}/reject")
async def reject_verification(verification_id: str, request: Request, reason: str = ""):
    """인증 거부 (API - 하위 호환)"""
    admin = await _require_admin_compat(request)
    supabase = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()

    update_data = {
        "status": "rejected",
        "admin_review": True,
        "rejection_reason": reason or "관리자에 의해 거부됨",
        "processed_at": now,
    }
    if admin.get("id"):
        update_data["reviewed_by"] = str(admin["id"])

    result = supabase.table("verifications").update(update_data).eq("id", verification_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="인증 건을 찾을 수 없습니다")

    member_id = result.data[0].get("member_id")
    if member_id:
        supabase.table("members").update({
            "verification_status": "rejected",
        }).eq("id", member_id).execute()

    # Audit log
    await log_admin_action(
        admin_id=admin.get("id"),
        action="reject",
        target_type="verification",
        target_id=verification_id,
        details={"reason": reason},
        ip_address=get_client_ip(request),
    )

    logger.info(f"인증 거부: verification={verification_id}, admin={admin.get('email')}, reason={reason}")
    return {"detail": "인증이 거부되었습니다"}


@router.get("/subscriptions/stats")
async def subscription_stats(request: Request):
    """구독 현황 통계 (API - 하위 호환)"""
    await _require_admin_compat(request)
    supabase = get_supabase_client()

    result = (
        supabase.table("member_services")
        .select("service_id, tier, status")
        .execute()
    )

    stats = {}
    for sub in (result.data or []):
        svc = sub["service_id"]
        if svc not in stats:
            stats[svc] = {"total": 0, "active": 0, "paid": 0, "tiers": {}}
        stats[svc]["total"] += 1
        if sub["status"] == "active":
            stats[svc]["active"] += 1
            if sub["tier"] != "free":
                stats[svc]["paid"] += 1
        tier = sub["tier"]
        stats[svc]["tiers"][tier] = stats[svc]["tiers"].get(tier, 0) + 1

    return stats
