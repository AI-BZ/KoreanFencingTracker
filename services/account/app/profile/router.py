"""
Profile Router - 프로필 관리 엔드포인트

/account 접두사는 server.py에서 추가됨.
"""
from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from shared_core.auth.jwt import get_current_member
from shared_core.auth.models import (
    MemberResponse,
    PrivacySettings,
    GuardianLink,
)
from shared_core.db.client import get_supabase_client

router = APIRouter(tags=["profile"])


def get_supabase():
    return get_supabase_client()


@router.get("/me")
async def get_my_profile(request: Request):
    """내 정보 조회"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    return MemberResponse(**member)


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
