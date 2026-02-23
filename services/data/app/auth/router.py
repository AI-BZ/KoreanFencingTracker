"""
Auth Router - Account 서비스 리다이렉트 shim

인증 엔드포인트가 account 서비스(account.fencingmind.ai:70)로 이동됨.
이 라우터는 기존 템플릿의 /auth/* 경로 호환성을 위한 리다이렉트 shim.
- /auth/login → account 서비스로 리다이렉트
- /auth/me → 로컬 JWT 디코드 (shared_core 사용)
- /auth/verification → account 서비스로 리다이렉트
- /auth/logout → account 서비스로 리다이렉트
"""
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from shared_core.auth.jwt import get_current_member
from shared_core.auth.models import MemberResponse

router = APIRouter(prefix="/auth", tags=["auth-shim"])

ACCOUNT_URL = os.getenv("ACCOUNT_SERVICE_URL", "http://localhost:70")


@router.get("/login")
async def login_redirect(request: Request, redirect: Optional[str] = None):
    """로그인 → account 서비스로 리다이렉트"""
    url = f"{ACCOUNT_URL}/auth/login"
    if redirect:
        url += f"?redirect={redirect}"
    return RedirectResponse(url=url)


@router.get("/me")
async def get_my_profile(request: Request):
    """내 정보 조회 (로컬 JWT 디코드 - account 서비스 호출 불필요)"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return MemberResponse(**member)


@router.get("/verification")
async def verification_redirect():
    """인증 페이지 → account 서비스로 리다이렉트"""
    return RedirectResponse(url=f"{ACCOUNT_URL}/account/verification")


@router.post("/logout")
async def logout_redirect():
    """로그아웃 → account 서비스로 리다이렉트"""
    return RedirectResponse(url=f"{ACCOUNT_URL}/auth/logout", status_code=303)


@router.get("/logout")
async def logout_redirect_get():
    """로그아웃 (GET) → account 서비스로 리다이렉트"""
    return RedirectResponse(url=f"{ACCOUNT_URL}/auth/logout")
