"""
Profile Router - 프로필 관리 엔드포인트

/account 접두사는 server.py에서 추가됨.
"""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from shared_core.auth.jwt import get_current_member
from shared_core.auth.models import (
    MemberResponse,
    MemberUpdate,
    PrivacySettings,
    GuardianLink,
)
from shared_core.db.client import get_supabase_client
from shared_core.privacy.masking import mask_korean_name
from app.i18n.middleware import create_language_context

router = APIRouter(tags=["profile"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))


def get_supabase():
    return get_supabase_client()


def _as_date(value) -> str | None:
    """타임스탬프(ISO 문자열/ datetime)를 YYYY-MM-DD 로 변환. 실패하면 None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        # Supabase가 예상 밖 포맷을 주더라도 앞 10자가 날짜인 경우가 대부분
        head = text[:10]
        return head if len(head) == 10 and head.count("-") == 2 else None


@router.get("/me", response_class=HTMLResponse)
async def get_my_profile(request: Request):
    """내 프로필 페이지 (HTML)"""
    member = await get_current_member(request)
    if not member:
        return HTMLResponse(
            content='<script>window.location.href="/auth/login?redirect=/account/me";</script>',
            status_code=200,
        )

    member_id = str(member["id"])
    supabase = get_supabase()

    # OAuth 연결 목록
    oauth_result = (
        supabase.table("oauth_connections")
        .select("provider, provider_email, provider_name, is_primary, created_at")
        .eq("member_id", member_id)
        .execute()
    )
    oauth_connections = oauth_result.data or []
    has_x_connection = any(c["provider"] == "x" for c in oauth_connections)

    # 소속 조직명
    team_name = None
    anonymous_team = None
    org_id = member.get("organization_id")
    if org_id:
        try:
            org_result = (
                supabase.table("organizations")
                .select("name, region, org_type")
                .eq("id", org_id)
                .single()
                .execute()
            )
            if org_result.data:
                team_name = org_result.data["name"]
                region = org_result.data.get("region", "")
                org_type = org_result.data.get("org_type", "클럽")
                anonymous_team = f"{region}({org_type})" if region else f"({org_type})"
        except Exception:
            logger.warning(f"조직 조회 실패 (member_id={member_id}, org_id={org_id})")

    # 공개 프로필 미리보기 — 실제 회원 데이터만 사용한다(더미 값 금지).
    # 비공개일 때 다른 사용자에게 보이는 값은 members.display_name 이며,
    # 아직 비어 있으면 실제 마스킹 함수로 동일하게 계산해서 보여준다.
    full_name = member.get("full_name") or ""
    if member.get("privacy_public"):
        preview_name = full_name or None
        preview_team = team_name
    else:
        preview_name = member.get("display_name") or (
            mask_korean_name(full_name) if full_name else None
        )
        preview_team = anonymous_team

    # 탈퇴 예약 상태 — members.deletion_* 컬럼은 get_current_member의 select("*")로 이미 로드됨.
    from app.config import get_account_settings

    deletion_scheduled_date = _as_date(member.get("deletion_scheduled_at"))
    deletion_requested_date = _as_date(member.get("deletion_requested_at"))
    deletion_requested = bool(
        member.get("deletion_requested_at") or member.get("deletion_scheduled_at")
    )

    return _templates.TemplateResponse("auth/profile.html", {
        "request": request,
        "member": member,
        "oauth_connections": oauth_connections,
        "has_x_connection": has_x_connection,
        "team_name": team_name,
        "anonymous_team": anonymous_team,
        "preview_name": preview_name,
        "preview_team": preview_team,
        "joined_date": _as_date(member.get("created_at")),
        "deletion_requested": deletion_requested,
        "deletion_requested_date": deletion_requested_date,
        "deletion_scheduled_date": deletion_scheduled_date,
        "deletion_grace_days": get_account_settings().ACCOUNT_DELETION_GRACE_DAYS,
        **create_language_context(request),
    })


@router.get("/me/json")
async def get_my_profile_json(request: Request):
    """내 정보 조회 (JSON API)"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    return MemberResponse(**member)


@router.patch("/me")
async def update_my_profile(request: Request, data: MemberUpdate):
    """내 프로필 수정"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="수정할 항목이 없습니다")

    if "full_name" in update_data:
        update_data["display_name"] = mask_korean_name(update_data["full_name"])

    supabase = get_supabase()
    result = supabase.table("members").update(update_data).eq("id", member["id"]).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="프로필 수정 중 오류")

    return MemberResponse(**result.data[0])


@router.patch("/me/privacy")
async def update_privacy_settings(
    request: Request,
    settings: PrivacySettings,
):
    """개인정보 설정 변경"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    supabase = get_supabase()

    update_data = {"privacy_public": settings.privacy_public}
    if settings.marketing_consent is not None:
        update_data["marketing_consent"] = settings.marketing_consent
    if settings.promotional_consent is not None:
        update_data["promotional_consent"] = settings.promotional_consent

    supabase.table("members").update(update_data).eq(
        "id", member["id"]
    ).execute()

    return {"success": True, "message": "설정이 저장되었습니다"}


@router.post("/guardian/link")
async def link_guardian(
    request: Request,
    data: GuardianLink,
):
    """보호자-미성년자 연결"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    # 보호자는 player_parent여야 함
    if member["member_type"] != "player_parent":
        raise HTTPException(status_code=400, detail="보호자 회원만 미성년자를 연결할 수 있습니다")

    supabase = get_supabase()

    # 미성년자 확인
    minor = supabase.table("members").select("*").eq(
        "id", str(data.minor_member_id)
    ).single().execute()

    if not minor.data:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다")

    # 이미 보호자가 있는지 확인
    if minor.data.get("guardian_member_id"):
        raise HTTPException(status_code=400, detail="이미 보호자가 등록되어 있습니다")

    # 연결
    supabase.table("members").update({
        "guardian_member_id": member["id"]
    }).eq("id", str(data.minor_member_id)).execute()

    return {"success": True, "message": "보호자 연결이 완료되었습니다"}


@router.post("/me/delete-request")
async def request_account_deletion(request: Request):
    """계정 삭제 요청 (30일 유예)"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    from datetime import datetime, timedelta
    from app.config import get_account_settings

    settings = get_account_settings()
    now = datetime.utcnow()
    scheduled = now + timedelta(days=settings.ACCOUNT_DELETION_GRACE_DAYS)

    supabase = get_supabase()
    supabase.table("members").update({
        "deletion_requested_at": now.isoformat(),
        "deletion_scheduled_at": scheduled.isoformat(),
    }).eq("id", member["id"]).execute()

    return {
        "success": True,
        "message": f"계정 삭제가 예약되었습니다. {settings.ACCOUNT_DELETION_GRACE_DAYS}일 이내에 취소할 수 있습니다.",
        "deletion_scheduled_at": scheduled.isoformat(),
    }


@router.post("/me/cancel-deletion")
async def cancel_account_deletion(request: Request):
    """계정 삭제 취소"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    supabase = get_supabase()
    supabase.table("members").update({
        "deletion_requested_at": None,
        "deletion_scheduled_at": None,
    }).eq("id", member["id"]).execute()

    return {"success": True, "message": "계정 삭제가 취소되었습니다."}
