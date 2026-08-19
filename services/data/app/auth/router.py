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
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from shared_core.auth.jwt import get_current_member
from shared_core.auth.models import MemberResponse

router = APIRouter(prefix="/auth", tags=["auth-shim"])

ACCOUNT_URL = os.getenv("ACCOUNT_SERVICE_URL", "https://account.fencingmind.ai")


def _account_url(request: Request, path: str, **params: Optional[str]) -> str:
    """account 서비스 URL 조립.

    현재 요청의 언어(request.state.lang)를 lang 쿼리파라미터로 붙여서
    account 로그인/로그아웃 화면이 같은 언어로 뜨도록 한다.
    account 미들웨어는 ?lang= 를 최우선으로 인식한다.

    쿼리는 urlencode 로 조립한다 — redirect 값 자체에 ?/& 가 들어가면
    문자열 이어붙이기로는 파라미터 경계가 깨진다.
    lang 은 미들웨어가 request.state 를 채우지 않은 경로에서도 안전하도록
    getattr 폴백을 쓴다.
    """
    query = {key: value for key, value in params.items() if value}

    lang = getattr(request.state, "lang", None)
    if lang:
        query["lang"] = lang

    url = f"{ACCOUNT_URL}{path}"
    if query:
        url += "?" + urlencode(query)
    return url


@router.get("/login")
async def login_redirect(request: Request, redirect: Optional[str] = None):
    """로그인 → account 서비스로 리다이렉트"""
    return RedirectResponse(url=_account_url(request, "/auth/login", redirect=redirect))


@router.get("/me")
async def get_my_profile(request: Request):
    """내 정보 조회 (로컬 JWT 디코드 - account 서비스 호출 불필요)"""
    member = await get_current_member(request)
    if not member:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return MemberResponse(**member)


@router.get("/verification")
async def verification_redirect(request: Request):
    """인증 페이지 → account 서비스로 리다이렉트"""
    return RedirectResponse(url=_account_url(request, "/account/verification"))


@router.post("/logout")
async def logout_redirect(request: Request):
    """로그아웃 → account 서비스로 리다이렉트"""
    return RedirectResponse(url=_account_url(request, "/auth/logout"), status_code=303)


@router.get("/logout")
async def logout_redirect_get(request: Request):
    """로그아웃 (GET) → account 서비스로 리다이렉트"""
    return RedirectResponse(url=_account_url(request, "/auth/logout"))
