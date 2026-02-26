"""
Auth Router - Account 서비스 리다이렉트 shim

인증 엔드포인트를 account 서비스(account.fencingmind.ai:70)로 리다이렉트.
- /auth/login -> account 서비스 로그인 페이지
- /auth/me -> 로컬 JWT 디코드 (현재 회원 정보 반환)
- /auth/logout -> account 서비스 로그아웃 + 쿠키 삭제
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from shared_core.auth.jwt import get_current_member

from .. import config

router = APIRouter(prefix="/auth", tags=["auth-shim"])

ACCOUNT_URL = config.ACCOUNT_SERVICE_URL


@router.get("/login")
async def login_redirect(request: Request, redirect: Optional[str] = None):
    """로그인 -> account 서비스로 리다이렉트"""
    url = f"{ACCOUNT_URL}/auth/login"
    if redirect:
        url += f"?redirect={redirect}"
    return RedirectResponse(url=url)


@router.get("/me")
async def get_my_profile(request: Request):
    """
    내 정보 조회 (로컬 JWT 디코드 - account 서비스 호출 불필요)

    organization_id가 null인 경우도 정상 응답 (has_club: false 플래그 포함).
    flat JSON 응답으로 프론트엔드에서 바로 사용 가능.
    """
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")

    return {
        "member_id": str(member.get("id", "")),
        "full_name": member.get("full_name", ""),
        "email": member.get("email", ""),
        "organization_id": member.get("organization_id"),
        "club_role": member.get("club_role"),
        "member_type": member.get("member_type"),
        "has_club": member.get("organization_id") is not None,
    }


@router.post("/logout")
async def logout_redirect():
    """로그아웃 -> account 서비스로 리다이렉트"""
    return RedirectResponse(url=f"{ACCOUNT_URL}/auth/logout", status_code=303)


@router.get("/logout")
async def logout_redirect_get():
    """로그아웃 (GET) -> account 서비스로 리다이렉트"""
    return RedirectResponse(url=f"{ACCOUNT_URL}/auth/logout")
