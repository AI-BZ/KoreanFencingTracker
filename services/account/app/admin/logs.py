"""
관리자 - 감사 로그 라우터

admin_audit_logs 조회 및 필터링.
"""
import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from shared_core.db.client import get_supabase_client

from .dependencies import require_admin
from app.i18n.middleware import create_language_context

router = APIRouter(tags=["admin-logs"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def _get_pending_count() -> int:
    """승인 대기 건수"""
    supabase = get_supabase_client()
    try:
        v = supabase.table("verifications").select("id", count="exact").eq("status", "pending").execute()
        pc = supabase.table("player_claims").select("id", count="exact").eq("status", "pending").execute()
        oc = supabase.table("organization_claims").select("id", count="exact").in_("status", ["pending", "auto_verified"]).execute()
        return (v.count or 0) + (pc.count or 0) + (oc.count or 0)
    except Exception:
        return 0


@router.get("/logs", response_class=HTMLResponse)
async def list_logs(
    request: Request,
    action: str = "",
    target_type: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 100,
):
    """감사 로그 목록 조회"""
    admin = await require_admin(request)
    supabase = get_supabase_client()

    query = supabase.table("admin_audit_logs").select("*")

    if action:
        query = query.eq("action", action)

    if target_type:
        query = query.eq("target_type", target_type)

    if date_from:
        query = query.gte("created_at", f"{date_from}T00:00:00")

    if date_to:
        query = query.lte("created_at", f"{date_to}T23:59:59")

    query = query.order("created_at", desc=True).limit(limit)

    try:
        result = query.execute()
        logs = result.data or []
    except Exception as e:
        logger.error(f"audit logs fetch error: {e}")
        logs = []

    # Enrich with admin names
    admin_ids = list(set(log.get("admin_id") for log in logs if log.get("admin_id")))
    admin_names = {}
    if admin_ids:
        try:
            m_result = supabase.table("members").select("id, full_name").in_("id", admin_ids).execute()
            for m in (m_result.data or []):
                admin_names[m["id"]] = m["full_name"]
        except Exception:
            pass

    for log in logs:
        log["admin_name"] = admin_names.get(log.get("admin_id"), "")
        # Parse details JSON string if needed
        details = log.get("details")
        if isinstance(details, str):
            try:
                log["details"] = json.loads(details)
            except (json.JSONDecodeError, TypeError):
                log["details"] = {}

    return _templates.TemplateResponse("admin/logs.html", {
        "request": request,
        "admin": admin,
        "active_tab": "logs",
        "pending_count": _get_pending_count(),
        "logs": logs,
        "action_filter": action,
        "target_type_filter": target_type,
        "date_from": date_from,
        "date_to": date_to,
        **create_language_context(request),
    })
