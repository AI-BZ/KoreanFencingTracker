"""
이메일 발송 서비스 (Resend API)

Resend free tier: 100건/일, 3000건/월
"""
import os
import httpx
from typing import Optional, List
from loguru import logger

from shared_core.email.templates import (
    get_verification_email_html,
    get_verification_code_email_html,
    get_welcome_email_html,
    get_admin_email_html,
)


EMAIL_SUBJECTS = {
    "ko": {
        "verification": "[FencingMind] 이메일 인증을 완료해주세요",
        "verification_code": "[FencingMind] 인증코드: {code}",
        "welcome": "[FencingMind] 가입을 환영합니다!",
    },
    "en": {
        "verification": "[FencingMind] Please verify your email",
        "verification_code": "[FencingMind] Verification code: {code}",
        "welcome": "[FencingMind] Welcome to FencingMind!",
    },
}


class EmailService:
    """Resend 기반 이메일 발송 서비스"""

    RESEND_API_URL = "https://api.resend.com/emails"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("RESEND_API_KEY", "")
        self.from_address = "FencingMind <noreply@fencingmind.ai>"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def _send(self, to: str, subject: str, html: str) -> bool:
        """Resend API로 이메일 발송"""
        if not self.is_configured:
            logger.warning(f"RESEND_API_KEY not configured. Skipping email to {to}")
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.RESEND_API_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": self.from_address,
                        "to": [to],
                        "subject": subject,
                        "html": html,
                    },
                    timeout=10.0,
                )

                if response.status_code == 200:
                    logger.info(f"Email sent to {to}: {subject}")
                    return True
                else:
                    logger.error(f"Email send failed ({response.status_code}): {response.text}")
                    return False
        except Exception as e:
            logger.error(f"Email send error: {e}")
            return False

    async def send_verification_email(
        self, to: str, name: str, token: str, verify_url: Optional[str] = None,
        lang: str = "ko",
    ) -> bool:
        """인증 메일 발송

        Args:
            to: 수신자 이메일
            name: 수신자 이름
            token: 인증 토큰
            verify_url: 인증 URL (None이면 기본 URL 사용)
            lang: 언어 코드 ("ko" 또는 "en")
        """
        if not verify_url:
            verify_url = f"https://account.fencingmind.ai/auth/verify-email?token={token}"
        html = get_verification_email_html(name, verify_url, lang=lang)
        subjects = EMAIL_SUBJECTS.get(lang, EMAIL_SUBJECTS["ko"])
        return await self._send(to, subjects["verification"], html)

    async def send_verification_code_email(
        self, to: str, name: str, code: str, lang: str = "ko",
    ) -> bool:
        """인증코드 메일 발송

        Args:
            to: 수신자 이메일
            name: 수신자 이름 (없으면 빈 문자열)
            code: 6자리 인증코드
            lang: 언어 코드 ("ko" 또는 "en")
        """
        html = get_verification_code_email_html(name, code, lang=lang)
        subjects = EMAIL_SUBJECTS.get(lang, EMAIL_SUBJECTS["ko"])
        return await self._send(to, subjects["verification_code"].format(code=code), html)

    async def send_welcome_email(
        self, to: str, name: str, services: Optional[List[str]] = None,
        lang: str = "ko",
    ) -> bool:
        """환영 메일 발송

        Args:
            to: 수신자 이메일
            name: 수신자 이름
            services: 선택한 관심 서비스 목록 (None이면 기존 고정 내용)
            lang: 언어 코드 ("ko" 또는 "en")
        """
        html = get_welcome_email_html(name, services=services, lang=lang)
        subjects = EMAIL_SUBJECTS.get(lang, EMAIL_SUBJECTS["ko"])
        return await self._send(to, subjects["welcome"], html)

    async def send_admin_email(
        self, to: str, recipient_name: str, subject: str, body: str,
        lang: str = "ko",
    ) -> bool:
        """관리자가 회원에게 이메일 발송

        Args:
            to: 수신자 이메일
            recipient_name: 수신자 이름
            subject: 제목
            body: 본문 텍스트
            lang: 언어 코드 ("ko" 또는 "en")
        """
        html = get_admin_email_html(recipient_name, subject, body, lang=lang)
        return await self._send(to, f"[FencingMind] {subject}", html)
