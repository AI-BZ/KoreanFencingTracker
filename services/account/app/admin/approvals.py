"""
관리자 - 통합 승인 큐 라우터

본인인증(verification), 선수Claim(player_claim), 조직Claim(org_claim),
학부모Claim(parent_claim) 통합 관리.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from shared_core.db.client import get_supabase_client

from .dependencies import require_admin, log_admin_action, get_client_ip
from app.i18n.middleware import create_language_context
from app.verification.notification_service import VerificationNotificationService

router = APIRouter(tags=["admin-approvals"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


# =============================================
# 승인 대기 상태값 (마이그레이션 CHECK 제약과 일치)
# =============================================
# 각 테이블은 서로 다른 "검토 대기" 상태를 쓴다. 한 곳이라도 누락되면
# 신청은 생성되는데 관리자 큐에 영영 뜨지 않는다.
#   verifications        (003): pending/processing/approved/rejected/error
#   player_claims        (013): pending/approved/rejected/expired/superseded
#   organization_claims  (013): pending/auto_verified/approved/rejected/expired
#   parent_claims        (018): pending/ai_reviewed/approved/rejected
# parent_claims 는 두 경로로 생성된다:
#   - 가입 폼(auth/router.py)          → status='pending'   (AI 리포트 없음)
#   - /verification/parent-claim 제출  → status='ai_reviewed'
# 따라서 둘 다 큐에 포함해야 한다.
QUEUE_STATUSES = {
    "verification": ["pending"],
    "player_claim": ["pending"],
    "org_claim": ["pending", "auto_verified"],
    "parent_claim": ["pending", "ai_reviewed"],
}

_COUNT_TABLES = {
    "verification": "verifications",
    "player_claim": "player_claims",
    "org_claim": "organization_claims",
    "parent_claim": "parent_claims",
}


def _get_pending_counts(supabase) -> dict:
    """유형별 대기 건수 조회

    테이블별로 개별 try 를 둔다. 하나가 실패해도 나머지 건수는 살아남아야
    관리자가 최소한 어떤 큐에 일이 쌓였는지 볼 수 있다.
    """
    counts = {}
    for key, table in _COUNT_TABLES.items():
        try:
            res = (
                supabase.table(table)
                .select("id", count="exact")
                .in_("status", QUEUE_STATUSES[key])
                .execute()
            )
            counts[key] = res.count or 0
        except Exception as e:
            logger.warning(f"pending count failed for {table}: {e}")
            counts[key] = 0

    counts["total"] = sum(counts[k] for k in _COUNT_TABLES)
    return counts


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
                .in_("status", QUEUE_STATUSES["verification"])
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
                .in_("status", QUEUE_STATUSES["player_claim"])
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
                .in_("status", QUEUE_STATUSES["org_claim"])
                .order("created_at", desc=False)
                .limit(50)
                .execute()
            )
            for oc in (oc_result.data or []):
                oc["type"] = "org_claim"
                items.append(oc)
        except Exception as e:
            logger.debug(f"organization_claims fetch: {e}")

    # Fetch parent claims
    if not type or type == "parent_claim":
        try:
            prc_result = (
                supabase.table("parent_claims")
                .select(
                    "id, member_id, child_name, child_birth_year, child_team_name, "
                    "child_gender, relationship_type, matched_player_id, "
                    "ai_confidence, ai_report, status, created_at"
                )
                .in_("status", QUEUE_STATUSES["parent_claim"])
                .order("created_at", desc=False)
                .limit(50)
                .execute()
            )
            for prc in (prc_result.data or []):
                prc["type"] = "parent_claim"
                # Parse ai_report if it's a string
                if isinstance(prc.get("ai_report"), str):
                    try:
                        prc["ai_report"] = json.loads(prc["ai_report"])
                    except (json.JSONDecodeError, TypeError):
                        prc["ai_report"] = {}
                items.append(prc)
        except Exception as e:
            logger.debug(f"parent_claims fetch: {e}")

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

    # Enrich player claims and parent claims with player names
    player_ids = [item.get("player_id") for item in items if item.get("type") == "player_claim" and item.get("player_id")]
    player_ids += [item.get("matched_player_id") for item in items if item.get("type") == "parent_claim" and item.get("matched_player_id")]
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
        if item.get("type") == "parent_claim":
            item["matched_player_name"] = player_names.get(item.get("matched_player_id"), "")

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
        **create_language_context(request),
    })


@router.post("/approvals/{item_type}/{item_id}/approve")
async def approve_item(request: Request, item_type: str, item_id: str, reason: str = Form("")):
    """승인 처리

    승인은 여러 단계(claim 상태 갱신 → 소속 등록 → 권한 부여 → 등급 갱신)로
    이루어진다. 각 단계는 독립적으로 실패할 수 있으므로 예외를 삼키지 않고
    실패한 단계 이름을 모아 로그 + 감사기록 + 리다이렉트 URL 로 노출한다.
    """
    admin = await require_admin(request)
    supabase = get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()

    if item_type == "verification":
        failures = await _approve_verification(supabase, item_id, admin, now, reason)
    elif item_type == "player_claim":
        failures = await _approve_player_claim(supabase, item_id, admin, now, reason)
    elif item_type == "org_claim":
        failures = await _approve_org_claim(supabase, item_id, admin, now, reason)
    elif item_type == "parent_claim":
        failures = await _approve_parent_claim(supabase, item_id, admin, now, reason)
    else:
        raise HTTPException(status_code=400, detail="유효하지 않은 유형입니다")

    failures = failures or []

    await log_admin_action(
        admin_id=admin.get("id"),
        action="approve",
        target_type=item_type,
        target_id=item_id,
        details={"reason": reason, "failed_steps": failures},
        ip_address=get_client_ip(request),
    )

    if failures:
        logger.error(
            f"승인 부분 실패: type={item_type}, id={item_id}, "
            f"admin={admin.get('email')}, failed_steps={failures}"
        )
        query = urlencode({
            "warn": f"승인은 기록됐지만 다음 단계가 실패했습니다: {', '.join(failures)}",
            "warn_id": item_id,
        })
        return RedirectResponse(url=f"/account/admin/approvals?{query}", status_code=303)

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
    elif item_type == "parent_claim":
        await _reject_parent_claim(supabase, item_id, admin, now, reason)
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
# club_role 매핑 / 등급 가드
# =============================================

# 조직 대표급으로 가입한 회원 유형
_DIRECTOR_MEMBER_TYPES = {"club_director", "school_director"}
# 지도자로 가입한 회원 유형
_COACH_MEMBER_TYPES = {"club_coach", "school_coach"}

# member_organizations.role CHECK (migration 013) == ClubRole enum
# ('owner','head_coach','coach','assistant','student','parent','staff')
# claim_type 은 organization_claims CHECK 상 director/head_coach/representative 뿐이므로
# 그대로 role 에 넣으면 'representative' 에서 CHECK 위반이 난다. 반드시 매핑을 거친다.
_CLUB_ROLE_RANK = {
    "owner": 4,
    "head_coach": 3,
    "coach": 2,
    "assistant": 1,
    "staff": 1,
    "parent": 0,
    "student": 0,
}


def resolve_club_role(claim_type: str, member_type: str) -> str:
    """조직 Claim 승인 시 부여할 club_role 결정 (최소권한 원칙).

    owner 는 "claim 종류"와 "가입 시 선언한 회원 유형"이 **둘 다** 조직 대표를
    가리킬 때만 부여한다. 코치로 가입한 사람이 director/representative 로
    claim 했다고 해서 클럽 전체 소유권을 주지 않는다.

    | claim_type      | member_type        | club_role   |
    |-----------------|--------------------|-------------|
    | director        | *_director         | owner       |
    | representative  | *_director         | owner       |
    | director        | *_coach / 기타      | head_coach  |
    | representative  | *_coach / 기타      | head_coach  |
    | head_coach      | *_director/*_coach | head_coach  |
    | head_coach      | 기타                | coach       |
    | (알 수 없음)      | *                  | coach       |
    """
    ct = (claim_type or "").strip()
    mt = (member_type or "").strip()

    if ct in ("director", "representative"):
        return "owner" if mt in _DIRECTOR_MEMBER_TYPES else "head_coach"
    if ct == "head_coach":
        if mt in _DIRECTOR_MEMBER_TYPES or mt in _COACH_MEMBER_TYPES:
            return "head_coach"
        return "coach"
    return "coach"


def _higher_club_role(current: str, granted: str) -> str:
    """같은 조직에서 이미 더 높은 역할을 갖고 있으면 강등하지 않는다."""
    if not current:
        return granted
    if _CLUB_ROLE_RANK.get(current, -1) > _CLUB_ROLE_RANK.get(granted, -1):
        return current
    return granted


def _raise_tier(current, minimum: int) -> int:
    """verification_tier 를 최소값까지만 끌어올린다 (강등 금지).

    기존 코드의 `max(2, 0)` 은 항상 2 라서 tier 3/4 회원을 2 로 강등시켰다.
    반드시 **현재 값**과 비교해야 한다.
    """
    try:
        current_int = int(current)
    except (TypeError, ValueError):
        current_int = 0
    return max(minimum, current_int)


def _fetch_member_state(supabase, member_id: str) -> dict:
    """승인 시 참고할 회원의 현재 상태 조회 (실패 시 빈 dict)."""
    result = (
        supabase.table("members")
        .select("id, member_type, club_role, organization_id, verification_tier")
        .eq("id", member_id)
        .limit(1)
        .execute()
    )
    return (result.data or [{}])[0]


# =============================================
# Type-Specific Approve/Reject Handlers
#
# 모든 _approve_* 는 실패한 단계 이름 리스트를 반환한다 (빈 리스트 = 완전 성공).
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

    failures = []
    member_id = result.data[0].get("member_id")
    if member_id:
        try:
            supabase.table("members").update({
                "verification_status": "verified",
                "verified_at": now,
            }).eq("id", member_id).execute()
        except Exception as e:
            logger.error(f"[verification] members 상태 갱신 실패 member={member_id}: {e}")
            failures.append("회원 인증상태 갱신")

        try:
            notifier = VerificationNotificationService()
            await notifier.notify_member_status_change(
                member_id=member_id, request_type="verification", status="approved",
            )
        except Exception as e:
            logger.error(f"[verification] 승인 알림 실패 member={member_id}: {e}")
            failures.append("회원 알림 발송")

    return failures


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

        notifier = VerificationNotificationService()
        await notifier.notify_member_status_change(
            member_id=member_id, request_type="verification", status="rejected", details=reason,
        )


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

    failures = []
    claim = result.data[0]
    member_id = claim.get("member_id")
    player_id = claim.get("player_id")

    if member_id and player_id:
        current_tier = 0
        try:
            current_tier = _fetch_member_state(supabase, member_id).get("verification_tier") or 0
        except Exception as e:
            logger.error(f"[player_claim] 회원 조회 실패 member={member_id}: {e}")
            failures.append("회원 정보 조회")

        try:
            supabase.table("members").update({
                "player_id": player_id,
                "data_linked_at": now,
                "verification_tier": _raise_tier(current_tier, 3),
            }).eq("id", member_id).execute()
        except Exception as e:
            logger.error(f"[player_claim] 선수 연결 실패 member={member_id}, player={player_id}: {e}")
            failures.append("선수 프로필 연결(members.player_id)")

    if member_id:
        try:
            notifier = VerificationNotificationService()
            await notifier.notify_member_status_change(
                member_id=member_id, request_type="player_claim", status="approved",
            )
        except Exception as e:
            logger.error(f"[player_claim] 승인 알림 실패 member={member_id}: {e}")
            failures.append("회원 알림 발송")

    return failures


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

    member_id = result.data[0].get("member_id")
    if member_id:
        notifier = VerificationNotificationService()
        await notifier.notify_member_status_change(
            member_id=member_id, request_type="player_claim", status="rejected", details=reason,
        )


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

    failures = []
    claim = result.data[0]
    member_id = claim.get("member_id")
    org_id = claim.get("organization_id")
    claim_type = claim.get("claim_type")

    if member_id and org_id:
        # --- Step 0: 회원 현재 상태 조회 (매핑/강등 방지에 필요) ---
        member_state = {}
        try:
            member_state = _fetch_member_state(supabase, member_id)
        except Exception as e:
            logger.error(f"[org_claim] 회원 조회 실패 member={member_id}: {e}")
            failures.append("회원 정보 조회")

        club_role = resolve_club_role(claim_type, member_state.get("member_type"))

        # 같은 조직에서 이미 더 높은 역할이면 유지 (재승인으로 인한 강등 방지)
        if member_state.get("organization_id") == org_id:
            club_role = _higher_club_role(member_state.get("club_role"), club_role)

        logger.info(
            f"[org_claim] role 매핑: claim_type={claim_type}, "
            f"member_type={member_state.get('member_type')} → club_role={club_role}"
        )

        # --- Step 1: member_organizations (다중 소속 기록) ---
        try:
            supabase.table("member_organizations").upsert({
                "member_id": member_id,
                "organization_id": org_id,
                "role": club_role,
                "status": "active",
            }).execute()
        except Exception as e:
            logger.error(
                f"[org_claim] member_organizations upsert 실패 "
                f"member={member_id}, org={org_id}, role={club_role}: {e}"
            )
            failures.append("소속 등록(member_organizations)")

        # --- Step 2: club_settings (조직 소유권을 부여할 때만) ---
        if club_role == "owner":
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
                logger.error(f"[org_claim] club_settings upsert 실패 org={org_id}: {e}")
                failures.append("클럽 설정 생성(club_settings)")

        # NOTE: 이전 구현은 organizations.owner_member_id 를 UPDATE 했으나
        # 해당 컬럼은 어떤 마이그레이션에도 정의돼 있지 않고 실제 DB 에도 없다.
        # 항상 실패하면서 뒤따르는 단계를 통째로 건너뛰게 만들던 원인이라 제거했다.
        # 조직 소유권은 member_organizations.role='owner' + members.club_role 로 표현한다.

        # --- Step 3: members 권한 부여 (클럽 서비스 게이트가 보는 값) ---
        # shared_core.auth.dependencies.get_current_club_member 는
        # members.organization_id 와 members.club_role 을 읽는다. 이 단계가 빠지면
        # 승인해도 club.fencingmind.ai 에서 403 이 난다.
        try:
            supabase.table("members").update({
                "club_role": club_role,
                "organization_id": org_id,
                "verification_tier": _raise_tier(member_state.get("verification_tier"), 3),
                "data_linked_at": now,
            }).eq("id", member_id).execute()
        except Exception as e:
            logger.error(
                f"[org_claim] members 권한 갱신 실패 "
                f"member={member_id}, org={org_id}, club_role={club_role}: {e}"
            )
            failures.append("클럽 권한 부여(members.club_role)")

    if member_id:
        try:
            notifier = VerificationNotificationService()
            await notifier.notify_member_status_change(
                member_id=member_id, request_type="org_claim", status="approved",
            )
        except Exception as e:
            logger.error(f"[org_claim] 승인 알림 실패 member={member_id}: {e}")
            failures.append("회원 알림 발송")

    return failures


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

    member_id = result.data[0].get("member_id")
    if member_id:
        notifier = VerificationNotificationService()
        await notifier.notify_member_status_change(
            member_id=member_id, request_type="org_claim", status="rejected", details=reason,
        )


async def _approve_parent_claim(supabase, claim_id: str, admin: dict, now: str, reason: str):
    """학부모 Claim 승인"""
    update_data = {
        "status": "approved",
        "reviewer_notes": reason or None,
        "reviewed_at": now,
    }
    if admin.get("id"):
        update_data["reviewer_id"] = admin["id"]

    result = supabase.table("parent_claims").update(update_data).eq("id", claim_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Claim을 찾을 수 없습니다")

    failures = []
    claim = result.data[0]
    member_id = claim.get("member_id")
    matched_player_id = claim.get("matched_player_id")

    if member_id:
        # --- Step 0: 현재 등급 조회 ---
        current_tier = 0
        try:
            current_tier = _fetch_member_state(supabase, member_id).get("verification_tier") or 0
        except Exception as e:
            logger.error(f"[parent_claim] 회원 조회 실패 member={member_id}: {e}")
            failures.append("회원 정보 조회")

        # --- Step 1: 자녀(선수) 계정에 보호자 연결 ---
        if matched_player_id:
            try:
                player_member = supabase.table("members").select("id").eq(
                    "player_id", matched_player_id
                ).limit(1).execute()
                if player_member.data:
                    supabase.table("members").update({
                        "guardian_member_id": member_id,
                    }).eq("id", player_member.data[0]["id"]).execute()
            except Exception as e:
                logger.error(
                    f"[parent_claim] 보호자 연결 실패 "
                    f"member={member_id}, player={matched_player_id}: {e}"
                )
                failures.append("자녀 계정 보호자 연결")

        # --- Step 2: 학부모 등급 상향 (강등 금지) ---
        # 기존 코드는 `max(2, 0)` 이라 항상 2 → tier 3(선수 연결 완료) 회원이
        # 학부모 승인 한 번으로 2 로 강등됐다. 현재 값과 비교해야 한다.
        try:
            supabase.table("members").update({
                "verification_tier": _raise_tier(current_tier, 2),
            }).eq("id", member_id).execute()
        except Exception as e:
            logger.error(f"[parent_claim] 등급 갱신 실패 member={member_id}: {e}")
            failures.append("회원 등급 갱신")

        # --- Step 3: 알림 ---
        try:
            notifier = VerificationNotificationService()
            await notifier.notify_member_status_change(
                member_id=member_id,
                request_type="parent_claim",
                status="approved",
            )
        except Exception as e:
            logger.error(f"[parent_claim] 승인 알림 실패 member={member_id}: {e}")
            failures.append("회원 알림 발송")

    return failures


async def _reject_parent_claim(supabase, claim_id: str, admin: dict, now: str, reason: str):
    """학부모 Claim 거부"""
    update_data = {
        "status": "rejected",
        "reviewer_notes": reason,
        "reviewed_at": now,
    }
    if admin.get("id"):
        update_data["reviewer_id"] = admin["id"]

    result = supabase.table("parent_claims").update(update_data).eq("id", claim_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Claim을 찾을 수 없습니다")

    member_id = result.data[0].get("member_id")

    # Notify the member
    notifier = VerificationNotificationService()
    if member_id:
        await notifier.notify_member_status_change(
            member_id=member_id,
            request_type="parent_claim",
            status="rejected",
            details=reason,
        )
