"""
PortOne V2 API Client - 결제 연동

PortOne V2 REST API: https://api.portone.io
인증: Authorization: PortOne {API_SECRET}
"""

from typing import Optional, Dict, Any
import httpx
from loguru import logger

from ..config import PORTONE_API_SECRET, PORTONE_STORE_ID


class PortOneError(Exception):
    """PortOne API 오류"""

    def __init__(self, message: str, status_code: Optional[int] = None, detail: Optional[Dict] = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(self.message)


class PortOneClient:
    """PortOne V2 API 클라이언트"""

    BASE_URL = "https://api.portone.io"

    def __init__(self):
        self._api_secret = PORTONE_API_SECRET
        self._store_id = PORTONE_STORE_ID

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"PortOne {self._api_secret}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """공통 HTTP 요청 처리"""
        url = f"{self.BASE_URL}{path}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self._headers,
                    json=json_data,
                )

            if response.status_code >= 400:
                try:
                    error_body = response.json()
                except Exception:
                    error_body = {"message": response.text}

                error_msg = error_body.get("message", f"PortOne API 오류 ({response.status_code})")
                logger.error(
                    "PortOne API error: {} {} -> {} {}",
                    method, path, response.status_code, error_msg,
                )
                raise PortOneError(
                    message=error_msg,
                    status_code=response.status_code,
                    detail=error_body,
                )

            if response.status_code == 204:
                return {}

            return response.json()

        except httpx.RequestError as e:
            logger.error("PortOne API request failed: {} {} -> {}", method, path, str(e))
            raise PortOneError(
                message=f"PortOne API 연결 실패: {str(e)}",
                status_code=None,
            )

    # ─────────────────────────────────────────
    # 결제 조회/검증
    # ─────────────────────────────────────────

    async def verify_payment(self, payment_id: str) -> Dict[str, Any]:
        """결제 검증 (조회)

        GET /payments/{payment_id}
        결제 완료 후 프론트에서 전달받은 payment_id로 실제 결제 상태 확인
        """
        logger.info("PortOne 결제 검증: payment_id={}", payment_id)
        return await self._request("GET", f"/payments/{payment_id}")

    # ─────────────────────────────────────────
    # 빌링키 발급
    # ─────────────────────────────────────────

    async def issue_billing_key(
        self,
        customer_id: str,
        card_number: str,
        expiry: str,
        birth_or_business: str,
        password_two_digits: str,
    ) -> Dict[str, Any]:
        """빌링키 발급

        POST /billing-keys
        카드 정보로 빌링키를 발급하여 정기결제에 사용
        """
        logger.info("PortOne 빌링키 발급: customer_id={}", customer_id)
        body = {
            "storeId": self._store_id,
            "method": {
                "card": {
                    "credential": {
                        "number": card_number,
                        "expiryYear": expiry[:4] if len(expiry) >= 4 else expiry,
                        "expiryMonth": expiry[4:6] if len(expiry) >= 6 else expiry[-2:],
                        "birthOrBusinessRegistrationNumber": birth_or_business,
                        "passwordTwoDigits": password_two_digits,
                    }
                }
            },
            "customer": {
                "id": customer_id,
            },
        }
        return await self._request("POST", "/billing-keys", json_data=body)

    # ─────────────────────────────────────────
    # 빌링키 결제
    # ─────────────────────────────────────────

    async def pay_with_billing_key(
        self,
        billing_key: str,
        payment_id: str,
        order_name: str,
        amount: int,
        currency: str = "KRW",
    ) -> Dict[str, Any]:
        """빌링키로 결제 요청

        POST /payments/{payment_id}/billing-key
        정기결제 등 빌링키를 이용한 자동 결제
        """
        logger.info(
            "PortOne 빌링키 결제: billing_key={}, payment_id={}, amount={}",
            billing_key[:8] + "...", payment_id, amount,
        )
        body = {
            "storeId": self._store_id,
            "billingKey": billing_key,
            "orderName": order_name,
            "amount": {
                "total": amount,
                "currency": currency,
            },
        }
        return await self._request("POST", f"/payments/{payment_id}/billing-key", json_data=body)

    # ─────────────────────────────────────────
    # 결제 취소
    # ─────────────────────────────────────────

    async def cancel_payment(
        self,
        payment_id: str,
        reason: str,
        amount: Optional[int] = None,
    ) -> Dict[str, Any]:
        """결제 취소 (전체/부분)

        POST /payments/{payment_id}/cancel
        amount 미지정 시 전액 취소
        """
        logger.info(
            "PortOne 결제 취소: payment_id={}, reason={}, amount={}",
            payment_id, reason, amount,
        )
        body = {
            "reason": reason,
        }  # type: Dict[str, Any]
        if amount is not None:
            body["amount"] = amount

        return await self._request("POST", f"/payments/{payment_id}/cancel", json_data=body)

    # ─────────────────────────────────────────
    # 빌링키 조회
    # ─────────────────────────────────────────

    async def get_billing_key_info(self, billing_key: str) -> Dict[str, Any]:
        """빌링키 정보 조회

        GET /billing-keys/{billing_key}
        """
        logger.info("PortOne 빌링키 조회: billing_key={}", billing_key[:8] + "...")
        return await self._request("GET", f"/billing-keys/{billing_key}")


# 싱글톤
portone_client = PortOneClient()
