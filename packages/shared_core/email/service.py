"""
이메일 발송 서비스 (Resend API)

Resend free tier: 100건/일, 3000건/월
"""
import os
import httpx
from typing import Optional
from loguru import logger

from shared_core.email.templates import (
    get_verification_email_html,
    get_welcome_email_html,
)


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

    async def send_verification_email(self, to: str, name: str, token: str) -> bool:
        """인증 메일 발송"""
        verify_url = f"https://account.fencingmind.ai/auth/verify-email?token={token}"
        html = get_verification_email_html(name, verify_url)
        return await self._send(to, "[FencingMind] 이메일 인증을 완료해주세요", html)

    async def send_welcome_email(self, to: str, name: str) -> bool:
        """환영 메일 발송"""
        html = get_welcome_email_html(name)
        return await self._send(to, "[FencingMind] 가입을 환영합니다!", html)
