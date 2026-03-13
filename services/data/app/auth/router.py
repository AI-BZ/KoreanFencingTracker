"""Auth Router - Account 서비스 리다이렉트 shim"""
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from shared_core.auth.jwt import get_current_member
from shared_core.auth.models import MemberResponse

router = APIRouter(prefix="/auth", tags=["auth-shim"])
ACCOUNT_URL = os.getenv("ACCOUNT_SERVICE_URL", "https://account.fencingmind.ai")


@router.get("/login")
async def login_redirect(request: Request, redirect: Optional[str] = None):
    url = f"{ACCOUNT_URL}/auth/login"
    if redirect:
        url += f"?redirect={redirect}"
    return RedirectResponse(url=url)


@router.get("/me")
async def get_my_profile(request: Request):
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return MemberResponse(**member)


@router.post("/logout")
async def logout_redirect():
    return RedirectResponse(url=f"{ACCOUNT_URL}/auth/logout", status_code=303)


@router.get("/logout")
async def logout_redirect_get():
    return RedirectResponse(url=f"{ACCOUNT_URL}/auth/logout")
