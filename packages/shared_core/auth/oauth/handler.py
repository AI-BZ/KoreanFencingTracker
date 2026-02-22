"""
OAuth 핸들러

OAuth 로그인 URL 생성, 토큰 교환 처리
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import HTTPException
from loguru import logger

from shared_core.auth.config import get_shared_auth_settings
from .providers import OAUTH_PROVIDERS


class OAuthHandler:
    """OAuth 인증 핸들러"""

    def __init__(self):
        self._oauth_states = {}
        self._pending_registrations = {}

    def build_auth_url(self, provider: str, promotional: bool = False) -> str:
        """OAuth 인증 URL 생성"""
        if provider not in OAUTH_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 제공자: {provider}")

        config = OAUTH_PROVIDERS[provider]
        if not config.get("enabled", False):
            raise HTTPException(status_code=400, detail=f"{provider}는 현재 사용할 수 없습니다")

        settings = get_shared_auth_settings()

        state = secrets.token_urlsafe(32)
        self._oauth_states[state] = {
            "provider": provider,
            "promotional": promotional,
            "created_at": datetime.utcnow(),
        }

        if provider == "kakao":
            redirect_uri = settings.KAKAO_REDIRECT_URI
            client_id = settings.KAKAO_CLIENT_ID
            scope = " ".join(config["scopes"])
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
            scope = " ".join(config["scopes"])
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
            scope = " ".join(config["scopes"])
            code_verifier = secrets.token_urlsafe(64)
            self._oauth_states[state]["code_verifier"] = code_verifier
            auth_url = (
                f"{config['authorize_url']}?"
                f"client_id={client_id}&"
                f"redirect_uri={redirect_uri}&"
                f"response_type=code&"
                f"scope={scope}&"
                f"state={state}&"
                f"code_challenge={code_verifier}&"
                f"code_challenge_method=plain"
            )
        else:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 제공자: {provider}")

        return auth_url

    def validate_state(self, state: str, provider: str) -> dict:
        """OAuth state 토큰 검증 및 반환"""
        state_data = self._oauth_states.pop(state, None)
        if not state_data or state_data["provider"] != provider:
            raise HTTPException(status_code=400, detail="잘못된 상태 토큰")

        if datetime.utcnow() - state_data["created_at"] > timedelta(minutes=10):
            raise HTTPException(status_code=400, detail="상태 토큰이 만료되었습니다")

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
        """회원가입 대기 정보 저장, 등록 토큰 반환"""
        registration_token = secrets.token_urlsafe(32)
        self._pending_registrations[registration_token] = {
            "provider": provider,
            "provider_user_id": user_info["id"],
            "email": user_info.get("email"),
            "name": user_info.get("name"),
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "promotional": promotional,
            "created_at": datetime.utcnow(),
        }
        return registration_token

    def get_pending_registration(self, token: str) -> Optional[dict]:
        """대기 중 등록 정보 조회"""
        return self._pending_registrations.get(token)

    def pop_pending_registration(self, token: str) -> Optional[dict]:
        """대기 중 등록 정보 꺼내기 (1회용)"""
        return self._pending_registrations.pop(token, None)
