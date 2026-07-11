"""
OAuth 핸들러

OAuth 로그인 URL 생성, 토큰 교환 처리
pending_registrations는 Supabase에 저장 (서버 재시작에도 유지)
oauth_states도 Supabase에 저장 (서버 재시작에도 유지)
"""
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx
from fastapi import HTTPException
from loguru import logger

from shared_core.auth.config import get_shared_auth_settings
from shared_core.db.client import get_supabase_client
from .providers import OAUTH_PROVIDERS


class OAuthHandler:
    """OAuth 인증 핸들러"""

    def __init__(self):
        self._pending_redirects = {}

    def _store_state(self, state: str, provider: str, promotional: bool = False,
                     code_verifier: str = None, redirect_url: str = None,
                     purpose: str = "login"):
        """OAuth state를 DB에 저장"""
        supabase = get_supabase_client()
        row = {
            "state": state,
            "provider": provider,
            "promotional": promotional,
            "code_verifier": code_verifier,
            "redirect_url": redirect_url,
            "purpose": purpose,
        }
        try:
            supabase.table("oauth_states").upsert(row).execute()
        except Exception as e:
            logger.error(f"oauth_states 저장 실패: {e}")
            raise HTTPException(status_code=500, detail="인증 상태 저장 실패")

    def _pop_state(self, state: str) -> Optional[dict]:
        """OAuth state를 DB에서 조회 후 삭제"""
        supabase = get_supabase_client()
        try:
            result = (
                supabase.table("oauth_states")
                .select("*")
                .eq("state", state)
                .gte("expires_at", datetime.now(timezone.utc).isoformat())
                .execute()
            )
            if not result.data:
                return None
            row = result.data[0]
            # 사용 후 삭제 (1회용)
            supabase.table("oauth_states").delete().eq("state", state).execute()
            return row
        except Exception as e:
            logger.error(f"oauth_states 조회 실패: {e}")
            return None

    def build_auth_url(self, provider: str, promotional: bool = False,
                       extra_scopes: List[str] = None, purpose: str = "login") -> str:
        """OAuth 인증 URL 생성 (하위호환: auth_url 문자열만 반환)

        state가 필요하면 build_auth_url_with_state를 사용할 것.

        Args:
            provider: OAuth 프로바이더 이름
            promotional: 홍보용 연동 여부
            extra_scopes: 기본 scope 외 추가 scope (예: 메시징용 talk_message)
            purpose: 인증 목적 ("login" | "messaging")
        """
        auth_url, _ = self.build_auth_url_with_state(
            provider, promotional, extra_scopes, purpose
        )
        return auth_url

    def build_auth_url_with_state(self, provider: str, promotional: bool = False,
                                  extra_scopes: List[str] = None,
                                  purpose: str = "login") -> tuple[str, str]:
        """OAuth 인증 URL과 생성된 state를 함께 반환

        auth_url 문자열을 되파싱하지 않고 state를 직접 얻기 위한 메서드.

        Args:
            provider: OAuth 프로바이더 이름
            promotional: 홍보용 연동 여부
            extra_scopes: 기본 scope 외 추가 scope (예: 메시징용 talk_message)
            purpose: 인증 목적 ("login" | "messaging")

        Returns:
            (auth_url, state) 튜플
        """
        if provider not in OAUTH_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 제공자: {provider}")

        config = OAUTH_PROVIDERS[provider]
        if not config.get("enabled", False):
            raise HTTPException(status_code=400, detail=f"{provider}는 현재 사용할 수 없습니다")

        settings = get_shared_auth_settings()

        state = secrets.token_urlsafe(32)

        # scope 구성: 기본 + 추가
        all_scopes = list(config["scopes"])
        if extra_scopes:
            all_scopes.extend(s for s in extra_scopes if s not in all_scopes)

        code_verifier = None

        if provider == "kakao":
            redirect_uri = settings.KAKAO_REDIRECT_URI
            client_id = settings.KAKAO_CLIENT_ID
            scope = " ".join(all_scopes)
            auth_url = (
                f"{config['authorize_url']}?"
                f"client_id={client_id}&"
                f"redirect_uri={redirect_uri}&"
                f"response_type=code&"
                f"scope={scope}&"
                f"state={state}"
            )

        elif provider == "google":
            redirect_uri = settings.GOOGLE_REDIRECT_URI
            client_id = settings.GOOGLE_CLIENT_ID
            scope = " ".join(all_scopes)
            auth_url = (
                f"{config['authorize_url']}?"
                f"client_id={client_id}&"
                f"redirect_uri={redirect_uri}&"
                f"response_type=code&"
                f"scope={scope}&"
                f"state={state}&"
                f"access_type=offline"
            )

        elif provider == "x":
            redirect_uri = settings.X_REDIRECT_URI
            client_id = settings.X_CLIENT_ID
            scope = " ".join(all_scopes)
            code_verifier = secrets.token_urlsafe(64)
            code_challenge = base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("ascii")).digest()
            ).rstrip(b"=").decode("ascii")
            auth_url = (
                f"{config['authorize_url']}?"
                f"client_id={client_id}&"
                f"redirect_uri={redirect_uri}&"
                f"response_type=code&"
                f"scope={scope}&"
                f"state={state}&"
                f"code_challenge={code_challenge}&"
                f"code_challenge_method=S256"
            )
        else:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 제공자: {provider}")

        # State를 DB에 저장 (서버 재시작에도 유지)
        self._store_state(state, provider, promotional, code_verifier, purpose=purpose)

        return auth_url, state

    def validate_state(self, state: str, provider: str) -> dict:
        """OAuth state 토큰 검증 및 반환 (DB에서 조회 후 삭제)"""
        state_data = self._pop_state(state)
        if not state_data or state_data["provider"] != provider:
            raise HTTPException(status_code=400, detail="잘못된 상태 토큰")

        return state_data

    async def exchange_token(self, provider: str, code: str, state_data: dict) -> dict:
        """OAuth 토큰 교환"""
        settings = get_shared_auth_settings()
        config = OAUTH_PROVIDERS[provider]

        if provider == "kakao":
            data = {
                "grant_type": "authorization_code",
                "client_id": settings.KAKAO_CLIENT_ID,
                "client_secret": settings.KAKAO_CLIENT_SECRET,
                "redirect_uri": settings.KAKAO_REDIRECT_URI,
                "code": code,
            }
        elif provider == "google":
            data = {
                "grant_type": "authorization_code",
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "code": code,
            }
        elif provider == "x":
            data = {
                "grant_type": "authorization_code",
                "client_id": settings.X_CLIENT_ID,
                "redirect_uri": settings.X_REDIRECT_URI,
                "code": code,
                "code_verifier": state_data.get("code_verifier"),
            }
        else:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 제공자: {provider}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                config["token_url"],
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )

            if response.status_code != 200:
                logger.error(f"토큰 교환 실패: {response.status_code} - {response.text}")
                raise HTTPException(status_code=400, detail="토큰 교환 실패")

            return response.json()

    def store_pending_registration(self, provider: str, user_info: dict, token_data: dict, promotional: bool = False) -> str:
        """회원가입 대기 정보를 Supabase에 저장, 등록 토큰 반환"""
        registration_token = secrets.token_urlsafe(32)
        supabase = get_supabase_client()

        row = {
            "token": registration_token,
            "provider": provider,
            "provider_user_id": str(user_info["id"]),
            "provider_email": user_info.get("email"),
            "provider_name": user_info.get("name"),
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "promotional": promotional,
        }
        try:
            supabase.table("pending_registrations").insert(row).execute()
        except Exception as e:
            logger.error(f"pending_registrations 저장 실패: {e}")
            raise HTTPException(status_code=500, detail="등록 정보 저장 실패")

        return registration_token

    def get_pending_registration(self, token: str) -> Optional[dict]:
        """대기 중 등록 정보 조회 (만료 확인 포함)"""
        supabase = get_supabase_client()
        result = supabase.table("pending_registrations").select("*").eq(
            "token", token
        ).gte("expires_at", datetime.utcnow().isoformat()).execute()

        if not result.data:
            return None

        row = result.data[0]
        return {
            "provider": row["provider"],
            "provider_user_id": row["provider_user_id"],
            "email": row["provider_email"],
            "name": row["provider_name"],
            "access_token": row["access_token"],
            "refresh_token": row["refresh_token"],
            "promotional": row["promotional"],
        }

    def pop_pending_registration(self, token: str) -> Optional[dict]:
        """대기 중 등록 정보 꺼내기 (1회용, 조회 후 삭제)"""
        data = self.get_pending_registration(token)
        if data:
            supabase = get_supabase_client()
            supabase.table("pending_registrations").delete().eq(
                "token", token
            ).execute()
        return data
