"""
관리자 - 회원 관리 라우터

회원 목록 조회, 상세, 수정, 정지/해제 기능.
모든 쓰기 작업은 admin_audit_logs에 기록.
"""
import math
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from shared_core.db.client import get_supabase_client
from shared_core.privacy.masking import mask_email, mask_phone

from .dependencies import require_admin, log_admin_action, get_client_ip

router = APIRouter(tags=["admin-members"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def _get_pending_count() -> int:
    """승인 대기 건수 합계"""
    supabase = get_supabase_client()
    try:
        v = supabase.table("verifications").select("id", count="exact").eq("status", "pending").execute()
        pc = supabase.table("player_claims").select("id", count="exact").eq("status", "pending").execute()
        oc = supabase.table("organization_claims").select("id", count="exact").in_("status", ["pending", "auto_verified"]).execute()
        return (v.count or 0) + (pc.count or 0) + (oc.count or 0)
    except Exception:
        return 0


@router.get("/members", response_class=HTMLResponse)
async def list_members(
    request: Request,
    q: str = "",
    status: str = "",
    type: str = "",
    page: int = 1,
    limit: int = 30,
):
    """회원 목록 조회 (HTML)"""
    admin = await require_admin(request)
    supabase = get_supabase_client()

    # Build query
    query = supabase.table("members").select(
        "id, full_name, nickname, email, phone, member_type, "
        "verification_status, member_status, admin_role, "
        "email_verified, created_at",
        count="exact",
    )

    if q:
        # Search by name, email, or nickname
        query = query.or_(
            f"full_name.ilike.%{q}%,"
            f"email.ilike.%{q}%,"
            f"nickname.ilike.%{q}%"
        )

    if status:
        query = query.eq("member_status", status)

    if type:
        query = query.eq("member_type", type)

    offset = (page - 1) * limit
    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

    result = query.execute()

    total = result.count or 0
    total_pages = max(1, math.ceil(total / limit))

    # Mask sensitive data
    members = []
    for m in (result.data or []):
        m["masked_email"] = mask_email(m.get("email", ""))
        members.append(m)

    return _templates.TemplateResponse("admin/members/list.html", {
        "request": request,
        "admin": admin,
        "active_tab": "members",
        "pending_count": _get_pending_count(),
        "members": members,
        "total": total,
        "total_pages": total_pages,
        "page": page,
        "limit": limit,
        "q": q,
        "status_filter": status,
        "type_filter": type,
    })


@router.get("/members/{member_id}", response_class=HTMLResponse)
async def member_detail(request: Request, member_id: str):
    """회원 상세 조회 (HTML)"""
    admin = await require_admin(request)
    supabase = get_supabase_client()

    # Fetch member
    try:
        member_result = supabase.table("members").select("*").eq("id", member_id).single().execute()
    except Exception:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다")

    if not member_result.data:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다")

    member = member_result.data
    member["masked_email"] = mask_email(member.get("email", ""))
    member["masked_phone"] = mask_phone(member.get("phone", ""))

    # Fetch related data in parallel-style
    verifications = []
    subscriptions = []
    player_claims = []
    org_claims = []
    notes = []

    try:
        v_result = supabase.table("verifications").select("*").eq("member_id", member_id).order("created_at", desc=True).limit(10).execute()
        verifications = v_result.data or []
    except Exception as e:
        logger.debug(f"verifications fetch: {e}")

    try:
        s_result = supabase.table("member_services").select("*").eq("member_id", member_id).order("created_at", desc=True).execute()
        subscriptions = s_result.data or []
    except Exception as e:
        logger.debug(f"member_services fetch: {e}")

    try:
        pc_result = supabase.table("player_claims").select("*").eq("member_id", member_id).order("created_at", desc=True).execute()
        player_claims = pc_result.data or []
    except Exception as e:
        logger.debug(f"player_claims fetch: {e}")

    try:
        oc_result = supabase.table("organization_claims").select("*").eq("member_id", member_id).order("created_at", desc=True).execute()
        org_claims = oc_result.data or []
    except Exception as e:
        logger.debug(f"organization_claims fetch: {e}")

    try:
        n_result = supabase.table("admin_notes").select("*").eq("target_type", "member").eq("target_id", member_id).order("created_at", desc=True).limit(50).execute()
        notes_raw = n_result.data or []
        # Enrich with admin names
        admin_ids = list(set(n["admin_id"] for n in notes_raw))
        admin_names = {}
        if admin_ids:
            an_result = supabase.table("members").select("id, full_name").in_("id", admin_ids).execute()
            for a in (an_result.data or []):
                admin_names[a["id"]] = a["full_name"]
        for n in notes_raw:
            n["admin_name"] = admin_names.get(n["admin_id"], "")
        notes = notes_raw
    except Exception as e:
        logger.debug(f"admin_notes fetch: {e}")

    return _templates.TemplateResponse("admin/members/detail.html", {
        "request": request,
        "admin": admin,
        "active_tab": "members",
        "pending_count": _get_pending_count(),
        "member": member,
        "verifications": verifications,
        "subscriptions": subscriptions,
        "player_claims": player_claims,
        "org_claims": org_claims,
        "notes": notes,
    })


@router.post("/members/{member_id}", response_class=HTMLResponse)
async def update_member(
    request: Request,
    member_id: str,
    admin_role: str = Form(""),
    member_type: str = Form(""),
    verification_tier: int = Form(0),
):
    """회원 정보 수정 (PATCH via POST)"""
    admin = await require_admin(request)
    supabase = get_supabase_client()

    # Build update data
    update_data = {}
    changes = {}

    # Fetch current member data for diff
    try:
        current = supabase.table("members").select(
            "admin_role, member_type, verification_tier"
        ).eq("id", member_id).single().execute()
    except Exception:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다")

    if not current.data:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다")

    old = current.data

    # admin_role
    new_admin_role = admin_role if admin_role else None
    if new_admin_role != old.get("admin_role"):
        update_data["admin_role"] = new_admin_role
        changes["admin_role"] = {"old": old.get("admin_role"), "new": new_admin_role}

    # member_type
    if member_type and member_type != old.get("member_type"):
        update_data["member_type"] = member_type
        changes["member_type"] = {"old": old.get("member_type"), "new": member_type}

    # verification_tier
    if verification_tier != (old.get("verification_tier") or 0):
        update_data["verification_tier"] = verification_tier
        changes["verification_tier"] = {"old": old.get("verification_tier"), "new": verification_tier}

    if update_data:
        supabase.table("members").update(update_data).eq("id", member_id).execute()

        await log_admin_action(
            admin_id=admin.get("id"),
            action="update_member",
            target_type="member",
            target_id=member_id,
            details=changes,
            ip_address=get_client_ip(request),
        )
        logger.info(f"회원 수정: member={member_id}, changes={changes}, admin={admin.get('email')}")

    return RedirectResponse(url=f"/account/admin/members/{member_id}", status_code=303)


@router.post("/members/{member_id}/suspend")
async def suspend_member(request: Request, member_id: str, reason: str = Form("")):
    """회원 정지"""
    admin = await require_admin(request)
    supabase = get_supabase_client()

    supabase.table("members").update({
        "member_status": "suspended",
    }).eq("id", member_id).execute()

    await log_admin_action(
        admin_id=admin.get("id"),
        action="suspend_member",
        target_type="member",
        target_id=member_id,
        details={"reason": reason},
        ip_address=get_client_ip(request),
    )
    logger.info(f"회원 정지: member={member_id}, reason={reason}, admin={admin.get('email')}")

    return RedirectResponse(url=f"/account/admin/members/{member_id}", status_code=303)


@router.post("/members/{member_id}/unsuspend")
async def unsuspend_member(request: Request, member_id: str):
    """회원 정지 해제"""
    admin = await require_admin(request)
    supabase = get_supabase_client()

    supabase.table("members").update({
        "member_status": "active",
    }).eq("id", member_id).execute()

    await log_admin_action(
        admin_id=admin.get("id"),
        action="unsuspend_member",
        target_type="member",
        target_id=member_id,
        details={},
        ip_address=get_client_ip(request),
    )
    logger.info(f"회원 정지 해제: member={member_id}, admin={admin.get('email')}")

    return RedirectResponse(url=f"/account/admin/members/{member_id}", status_code=303)


@router.post("/members/{member_id}/notes")
async def add_member_note(request: Request, member_id: str, content: str = Form(...)):
    """회원에 관리 노트 추가"""
    admin = await require_admin(request)
    supabase = get_supabase_client()

    note_data = {
        "target_type": "member",
        "target_id": member_id,
        "content": content,
    }
    if admin.get("id"):
        note_data["admin_id"] = admin["id"]

    supabase.table("admin_notes").insert(note_data).execute()

    await log_admin_action(
        admin_id=admin.get("id"),
        action="add_note",
        target_type="member",
        target_id=member_id,
        details={"content_preview": content[:100]},
        ip_address=get_client_ip(request),
    )

    return RedirectResponse(url=f"/account/admin/members/{member_id}#notes", status_code=303)
