"""카카오 알림톡 발송기 (Phase 6) — 프로바이더 비종속 인터페이스.

카카오 알림톡의 현실(중요, 환상 금지):
    알림톡은 다음 3가지가 모두 갖춰져야 발송 가능하다.
      1) 카카오 비즈니스 채널 (플러스친구) — 발신 프로필 등록
      2) 사전 검수 통과한 메시지 템플릿 (각 템플릿마다 template_code 발급)
      3) 발송 대행사(릴레이 프로바이더)와의 계약 + API 자격증명
    대행사마다 REST 엔드포인트/인증 서명 방식이 전부 다르다.

설계:
    - `KakaoAlimtalkSender`는 프로바이더 비종속 인터페이스를 제공한다.
    - 자격증명/템플릿코드가 하나라도 없으면 실제 HTTP 호출을 하지 않고
      `not_configured` 결과를 반환한다(호출자는 'pending'으로 로그).
    - 실제 발송은 모든 설정이 채워졌을 때만 시도한다. `httpx`는 지연 import이며
      미설치면 'pending'으로 degrade.
    - 어떤 경우에도 호출자에게 예외를 던지지 않는다(try/except로 포장) → 폴러 보호.

레퍼런스 구현 대상: **Solapi (구 CoolSMS)** 알림톡 REST API.
    - 인증: API Key + Secret 기반 HMAC-SHA256 서명 헤더
      (Solapi 문서의 `HMAC-SHA256 apiKey=..., date=..., salt=..., signature=...` 형식).
    - 엔드포인트: POST {base}/messages/v4/send  (단건 발송)
    - body: {"message": {"to","from","kakaoOptions":{"pfId","templateId","variables"}}}
    ⚠️ 이 레퍼런스 구현은 Solapi 공개 문서의 계약을 따른 것이며 **라이브 API로
       검증되지 않았다(untested)**. 운영 전 실제 응답 스키마/서명 규칙을 반드시
       대행사 문서로 재확인해야 한다. 다른 대행사를 쓸 경우 `_send_via_solapi`에
       대응하는 어댑터를 추가하고 PROVIDER 값으로 분기한다.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from ..config import settings
from . import event_types as et

logger = logging.getLogger("app.pipeline.kakao")

# Solapi 기본 베이스 URL (BASE_URL 미지정 시 사용)
_SOLAPI_DEFAULT_BASE = "https://api.solapi.com"

# 발송 결과 상태
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_PENDING = "pending"
STATUS_NOT_CONFIGURED = "not_configured"


class KakaoAlimtalkSender:
    """카카오 알림톡 발송기. 설정이 없으면 안전한 no-op."""

    def __init__(self) -> None:
        self.provider = (settings.KAKAO_ALIMTALK_PROVIDER or "").strip().lower()
        self.api_key = settings.KAKAO_ALIMTALK_API_KEY
        self.api_secret = settings.KAKAO_ALIMTALK_API_SECRET
        self.sender_key = settings.KAKAO_ALIMTALK_SENDER_KEY
        self.pfid = settings.KAKAO_ALIMTALK_PFID
        self.base_url = (settings.KAKAO_ALIMTALK_BASE_URL or _SOLAPI_DEFAULT_BASE).rstrip("/")
        self.template_map = settings.kakao_template_map

    # ------------------------------------------------------------------ public

    def is_configured(self) -> bool:
        """공통(템플릿 제외) 자격증명이 모두 있는지."""
        return bool(
            self.provider
            and self.api_key
            and self.api_secret
            and self.sender_key
            and self.pfid
        )

    def template_code_for(self, category: str) -> str:
        return (self.template_map.get(category) or "").strip()

    def send(self, *, to_phone: str, event: dict) -> dict:
        """알림톡 발송 시도. 절대 예외를 던지지 않는다.

        Returns:
            {"status": 'sent'|'failed'|'pending'|'not_configured', "error": Optional[str]}
        """
        try:
            return self._send(to_phone=to_phone, event=event)
        except Exception as exc:  # noqa: BLE001 - 폴러 보호: 어떤 예외도 흡수
            logger.error("alimtalk 발송 중 예외 (흡수): %s", exc)
            return {"status": STATUS_FAILED, "error": f"unexpected: {exc}"}

    # ----------------------------------------------------------------- internal

    def _send(self, *, to_phone: str, event: dict) -> dict:
        # 1) 공통 자격증명 확인
        if not self.is_configured():
            return {
                "status": STATUS_NOT_CONFIGURED,
                "error": "카카오 알림톡 자격증명 미설정",
            }

        # 2) 카테고리 → 템플릿 코드
        category = et.category_for_event(event.get("event_type", "")) or ""
        template_code = self.template_code_for(category)
        if not template_code:
            return {
                "status": STATUS_NOT_CONFIGURED,
                "error": f"승인된 템플릿 코드 없음 (category={category})",
            }

        # 3) 수신번호 정규화
        normalized = _normalize_phone(to_phone)
        if not normalized:
            return {"status": STATUS_FAILED, "error": "유효하지 않은 전화번호"}

        # 4) 템플릿 변수 구성 (title/body 재사용)
        title, body, link = et.build_message(event)
        variables = {
            "#{title}": title,
            "#{body}": body,
            "#{url}": link or "",
        }

        # 5) httpx 지연 import (미설치 → pending)
        try:
            import httpx  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("alimtalk pending: httpx 미설치 (%s)", exc)
            return {"status": STATUS_PENDING, "error": "httpx 미설치"}

        # 6) 프로바이더별 어댑터
        if self.provider == "solapi":
            return self._send_via_solapi(
                httpx_mod=httpx,
                to_phone=normalized,
                template_code=template_code,
                variables=variables,
            )

        # 알 수 없는 프로바이더 → 안전하게 pending (구현 어댑터 없음)
        logger.warning("alimtalk pending: 미지원 프로바이더 '%s'", self.provider)
        return {
            "status": STATUS_PENDING,
            "error": f"미지원 프로바이더: {self.provider}",
        }

    # -------------------------------------------------------- Solapi reference

    def _send_via_solapi(
        self,
        *,
        httpx_mod,
        to_phone: str,
        template_code: str,
        variables: dict,
    ) -> dict:
        """Solapi(구 CoolSMS) 알림톡 단건 발송 — 레퍼런스 구현 (라이브 미검증).

        Solapi 문서 기준:
          - 인증 헤더:
              Authorization: HMAC-SHA256 apiKey=<KEY>, date=<ISO8601>,
                             salt=<random>, signature=<hex(hmac_sha256(secret, date+salt))>
          - 엔드포인트: POST {base}/messages/v4/send
          - 알림톡 옵션은 message.kakaoOptions 에 pfId/templateId/variables 포함.
        """
        date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        salt = secrets.token_hex(16)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            (date + salt).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        auth_header = (
            f"HMAC-SHA256 apiKey={self.api_key}, date={date}, "
            f"salt={salt}, signature={signature}"
        )

        # Solapi는 발신번호(from)를 사전 등록해야 한다. 알림톡은 발신번호가
        # 실패 시 SMS 대체발송에 쓰이며, 미사용 시에도 형식상 요구될 수 있어
        # sender_key가 없으면 위 is_configured에서 이미 걸러진다.
        payload = {
            "message": {
                "to": to_phone,
                "from": _digits_only(self.sender_key),
                "type": "ATA",  # ATA = 알림톡 (Alimtalk)
                "kakaoOptions": {
                    "pfId": self.pfid,
                    "templateId": template_code,
                    "variables": variables,
                    # 알림톡 실패 시 SMS 대체발송 비활성 (대체발송은 운영정책에 따름)
                    "disableSms": True,
                },
            }
        }

        url = f"{self.base_url}/messages/v4/send"
        try:
            resp = httpx_mod.post(
                url,
                json=payload,
                headers={
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )
        except Exception as exc:  # noqa: BLE001 - 네트워크 오류 등
            logger.warning("solapi 요청 실패: %s", exc)
            return {"status": STATUS_FAILED, "error": f"network: {exc}"}

        if 200 <= resp.status_code < 300:
            # Solapi는 2xx여도 본문 statusCode로 부분 실패를 줄 수 있어 보수적으로 확인.
            ok, detail = _solapi_body_ok(resp)
            if ok:
                return {"status": STATUS_SENT, "error": None}
            return {"status": STATUS_FAILED, "error": detail}

        return {
            "status": STATUS_FAILED,
            "error": f"http {resp.status_code}: {_safe_text(resp)}",
        }


def _solapi_body_ok(resp) -> tuple[bool, Optional[str]]:
    """Solapi 응답 본문 해석. 성공 코드면 (True, None)."""
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001 - JSON 아님
        return True, None  # 2xx인데 본문 파싱 불가 → 성공으로 간주(보수적이지만 차선)
    if not isinstance(data, dict):
        return True, None
    # 단건 send 응답은 statusCode '2000'(성공) 형태. groupId만 오는 경우도 성공으로 봄.
    status_code = str(data.get("statusCode", "")) if data.get("statusCode") is not None else ""
    if status_code and not status_code.startswith("2"):
        return False, f"solapi statusCode={status_code} msg={data.get('statusMessage')}"
    return True, None


def _safe_text(resp) -> str:
    try:
        return (resp.text or "")[:300]
    except Exception:  # noqa: BLE001
        return "<no body>"


def _digits_only(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _normalize_phone(raw: str) -> Optional[str]:
    """전화번호를 국내 발송용으로 정규화.

    - 하이픈/공백 제거.
    - +82 / 82 국가코드를 0 으로 치환 (국내 대행사는 010... 형식을 기대).
    - 최소 길이 검증.
    """
    if not raw:
        return None
    s = raw.strip().replace(" ", "").replace("-", "")
    if s.startswith("+82"):
        s = "0" + s[3:]
    elif s.startswith("82") and not s.startswith("820"):
        # '82' 국가코드 접두 (예: 821012345678) → 0 치환
        s = "0" + s[2:]
    s = _digits_only(s)
    if len(s) < 9:
        return None
    return s


def build_recipient_phone(member_row: dict) -> Optional[str]:
    """members 행에서 알림톡 수신 번호 결정.

    우선순위: phone(+phone_country_code) → contact_phone.
    """
    if not member_row:
        return None
    phone = (member_row.get("phone") or "").strip()
    if phone:
        cc = (member_row.get("phone_country_code") or "").strip()
        if cc and not phone.startswith("+") and not phone.startswith("0"):
            # 국가코드가 따로 저장된 경우 합쳐서 정규화에 넘김
            return f"+{_digits_only(cc)}{_digits_only(phone)}"
        return phone
    contact = (member_row.get("contact_phone") or "").strip()
    return contact or None
