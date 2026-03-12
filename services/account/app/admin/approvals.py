"""
관리자 - 통합 승인 큐 라우터

본인인증(verification), 선수Claim(player_claim), 조직Claim(org_claim) 통합 관리.
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from shared_core.db.client import get_supabase_client

from .dependencies import require_admin, log_admin_action, get_client_ip

router = APIRouter(tags=["admin-approvals"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def _get_pending_counts(supabase) -> dict:
    """유형별 대기 건수 조회"""
    try:
        v = supabase.table("verifications").select("id", count="exact").eq("status", "pending").execute()
        pc = supabase.table("player_claims").select("id", count="exact").eq("status", "pending").execute()
        oc = supabase.table("organization_claims").select("id", count="exact").in_("status", ["pending", "auto_verified"]).execute()
        v_count = v.count or 0
        pc_count = pc.count or 0
        oc_count = oc.count or 0
        return {
            "verification": v_count,
            "player_claim": pc_count,
            "org_claim": oc_count,
            "total": v_count + pc_count + oc_count,
        }
    except Exception:
        return {"verification": 0, "player_claim": 0, "org_claim": 0, "total": 0}


@router.get("/approvals", response_class=HTMLResponse)
async def list_approvals(request: Request, type: str = ""):
    """통합 승인 큐 조회"""
    admin = await require_admin(request)
    supabase = get_supabase_client()

    counts = _get_pending_counts(supabase)
    items = []

    # Fetch verifications
    if not type or type == "verification":
        try:
            v_result = (
                supabase.table("verifications")
                .select("id, member_id, verification_type, status, ai_confidence, ai_result, created_at")
                .eq("status", "pending")
                .order("created_at", desc=False)
                .limit(50)
                .execute()
            )
            for v in (v_result.data or []):
                v["type"] = "verification"
                items.append(v)
        except Exception as e:
            logger.debug(f"verifications fetch: {e}")

    # Fetch player claims
    if not type or type == "player_claim":
        try:
            pc_result = (
                supabase.table("player_claims")
                .select("id, member_id, player_id, confidence_score, evidence, status, created_at")
                .eq("status", "pending")
                .order("created_at", desc=False)
                .limit(50)
                .execute()
            )
            for pc in (pc_result.data or []):
                pc["type"] = "player_claim"
                items.append(pc)
        except Exception as e:
            logger.debug(f"player_claims fetch: {e}")

    # Fetch organization claims
    if not type or type == "org_claim":
        try:
            oc_result = (
                supabase.table("organization_claims")
                .select(
                    "id, member_id, organization_id, claim_type, status, "
                    "brn_number, brn_business_name, brn_representative_name, "
                    "brn_ocr_confidence, brn_checkdigit_valid, brn_nts_valid, "
                    "brn_auto_verified, document_url, created_at"
                )
                .in_("status", ["pending", "auto_verified"])
                .order("created_at", desc=False)
                .limit(50)
                .execute()
            )
            for oc in (oc_result.data or []):
                oc["type"] = "org_claim"
                items.append(oc)
        except Exception as e:
            logger.debug(f"organization_claims fetch: {e}")

    # Enrich with member names and related data
    member_ids = list(set(item.get("member_id") for item in items if item.get("member_id")))
    member_names = {}
    if member_ids:
        try:
            m_result = supabase.table("members").select("id, full_name").in_("id", member_ids).execute()
            for m in (m_result.data or []):
                member_names[m["id"]] = m["full_name"]
        except Exception:
            pass

    # Enrich player claims with player names
    player_ids = [item.get("player_id") for item in items if item.get("type") == "player_claim" and item.get("player_id")]
    player_names = {}
    if player_ids:
        try:
            p_result = supabase.table("players").select("id, name").in_("id", player_ids).execute()
            for p in (p_result.data or []):
                player_names[p["id"]] = p["name"]
        except Exception:
            pass

    # Enrich org claims with org names
    org_ids = [item.get("organization_id") for item in items if item.get("type") == "org_claim" and item.get("organization_id")]
    org_names_map = {}
    if org_ids:
        try:
            o_result = supabase.table("organizations").select("id, name").in_("id", org_ids).execute()
            for o in (o_result.data or []):
                org_names_map[o["id"]] = o["name"]
        except Exception:
            pass

    for item in items:
        item["member_name"] = member_names.get(item.get("member_id"), "")
        if item.get("type") == "player_claim":
            item["player_name"] = player_names.get(item.get("player_id"), "")
        if item.get("type") == "org_claim":
            item["org_name"] = org_names_map.get(item.get("organization_id"), "")

    # Sort by created_at
    items.sort(key=lambda x: x.get("created_at", ""), reverse=False)

    return _templates.TemplateResponse("admin/approvals/list.html", {
        "request": request,
        "admin": admin,
        "active_tab": "approvals",
        "pending_count": counts["total"],
        "items": items,
        "counts": counts,
        "type_filter": type,
    })


@router.post("/approvals/{item_type}/{item_id}/approve")
async def approve_item(request: Request, item_type: str, item_id: str, reason: str = Form("")):
    """승인 처리"""
    admin = await require_admin(request)
    supabase = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()

    if item_type == "verification":
        await _approve_verification(supabase, item_id, admin, now, reason)
    elif item_type == "player_claim":
        await _approve_player_claim(supabase, item_id, admin, now, reason)
    elif item_type == "org_claim":
        await _approve_org_claim(supabase, item_id, admin, now, reason)
    else:
        raise HTTPException(status_code=400, detail="유효하지 않은 유형입니다")

    await log_admin_action(
        admin_id=admin.get("id"),
        action="approve",
        target_type=item_type,
        target_id=item_id,
        details={"reason": reason},
        ip_address=get_client_ip(request),
    )
    logger.info(f"승인: type={item_type}, id={item_id}, admin={admin.get('email')}")

    return RedirectResponse(url="/account/admin/approvals", status_code=303)


@router.post("/approvals/{item_type}/{item_id}/reject")
async def reject_item(request: Request, item_type: str, item_id: str, reason: str = Form("")):
    """거부 처리"""
    admin = await require_admin(request)
    supabase = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()

    if not reason:
        reason = "관리자에 의해 거부됨"

    if item_type == "verification":
        await _reject_verification(supabase, item_id, admin, now, reason)
    elif item_type == "player_claim":
        await _reject_player_claim(supabase, item_id, admin, now, reason)
    elif item_type == "org_claim":
        await _reject_org_claim(supabase, item_id, admin, now, reason)
    else:
        raise HTTPException(status_code=400, detail="유효하지 않은 유형입니다")

    await log_admin_action(
        admin_id=admin.get("id"),
        action="reject",
        target_type=item_type,
        target_id=item_id,
        details={"reason": reason},
        ip_address=get_client_ip(request),
    )
    logger.info(f"거부: type={item_type}, id={item_id}, reason={reason}, admin={admin.get('email')}")

    return RedirectResponse(url="/account/admin/approvals", status_code=303)


# =============================================
# Type-Specific Approve/Reject Handlers
# =============================================

async def _approve_verification(supabase, verification_id: str, admin: dict, now: str, reason: str):
    """본인인증 승인"""
    update_data = {
        "status": "approved",
        "admin_review": True,
        "reviewer_notes": reason or None,
        "processed_at": now,
        "reviewed_at": now,
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


async def _reject_verification(supabase, verification_id: str, admin: dict, now: str, reason: str):
    """본인인증 거부"""
    update_data = {
        "status": "rejected",
        "admin_review": True,
        "rejection_reason": reason,
        "reviewer_notes": reason,
        "processed_at": now,
        "reviewed_at": now,
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


async def _approve_player_claim(supabase, claim_id: str, admin: dict, now: str, reason: str):
    """선수 Claim 승인"""
    update_data = {
        "status": "approved",
        "reviewer_notes": reason or None,
        "reviewed_at": now,
    }
    if admin.get("id"):
        update_data["reviewer_id"] = admin["id"]

    result = supabase.table("player_claims").update(update_data).eq("id", claim_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Claim을 찾을 수 없습니다")

    claim = result.data[0]
    member_id = claim.get("member_id")
    player_id = claim.get("player_id")

    if member_id and player_id:
        supabase.table("members").update({
            "player_id": player_id,
            "data_linked_at": now,
            "verification_tier": 3,
        }).eq("id", member_id).execute()


async def _reject_player_claim(supabase, claim_id: str, admin: dict, now: str, reason: str):
    """선수 Claim 거부"""
    update_data = {
        "status": "rejected",
        "reviewer_notes": reason,
        "reviewed_at": now,
    }
    if admin.get("id"):
        update_data["reviewer_id"] = admin["id"]

    result = supabase.table("player_claims").update(update_data).eq("id", claim_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Claim을 찾을 수 없습니다")


async def _approve_org_claim(supabase, claim_id: str, admin: dict, now: str, reason: str):
    """조직 Claim 승인"""
    update_data = {
        "status": "approved",
        "reviewer_notes": reason or None,
        "reviewed_at": now,
    }
    if admin.get("id"):
        update_data["reviewer_id"] = admin["id"]

    result = supabase.table("organization_claims").update(update_data).eq("id", claim_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Claim을 찾을 수 없습니다")

    claim = result.data[0]
    member_id = claim.get("member_id")
    org_id = claim.get("organization_id")
    claim_type = claim.get("claim_type")

    if member_id and org_id:
        # Create member_organizations record
        role = "owner" if claim_type == "director" else claim_type
        try:
            supabase.table("member_organizations").upsert({
                "member_id": member_id,
                "organization_id": org_id,
                "role": role,
                "status": "active",
            }).execute()
        except Exception as e:
            logger.warning(f"member_organizations upsert: {e}")

        # Create club_settings if director
        if claim_type == "director":
            try:
                supabase.table("club_settings").upsert(
                    {
                        "organization_id": org_id,
                        "status": "active",
                        "onboarding_completed": False,
                        "created_by": member_id,
                    },
                    on_conflict="organization_id",
                ).execute()
            except Exception as e:
                logger.warning(f"club_settings upsert skipped: {e}")

            # Update organizations owner
            try:
                supabase.table("organizations").update({
                    "owner_member_id": member_id,
                }).eq("id", org_id).execute()
            except Exception as e:
                logger.warning(f"organizations owner update: {e}")

        # Update member verification tier
        supabase.table("members").update({
            "verification_tier": 3,
            "data_linked_at": now,
        }).eq("id", member_id).execute()


async def _reject_org_claim(supabase, claim_id: str, admin: dict, now: str, reason: str):
    """조직 Claim 거부"""
    update_data = {
        "status": "rejected",
        "reviewer_notes": reason,
        "reviewed_at": now,
    }
    if admin.get("id"):
        update_data["reviewer_id"] = admin["id"]

    result = supabase.table("organization_claims").update(update_data).eq("id", claim_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Claim을 찾을 수 없습니다")
