"""
Verification Processor - Gemini API를 통한 자동 인증

이 모듈은 인증 이미지의 스토리지 접근 계층도 함께 제공한다.
인증 이미지(미성년자 얼굴/도복/마스크 사진, 협회 등록증, 사업자등록증)는
**비공개 버킷**에만 저장하고, DB에는 공개 URL이 아니라 **객체 경로**만 남긴다.
읽어야 할 때마다 짧은 수명의 서명 URL을 새로 발급한다.
"""
import json
import re
import base64
import uuid as _uuid
from datetime import datetime
from typing import Optional
from uuid import UUID
import httpx
from loguru import logger
from supabase import create_client

from ..config import get_account_settings, VERIFICATION_PROMPTS
from shared_core.types.member import VerificationType, VerificationStatus
from shared_core.auth.models import GeminiVerificationResult


# =============================================================================
# 인증 이미지 스토리지 (비공개 버킷 + 서명 URL)
# =============================================================================
#
# 설계 근거
# ---------
# 이전 구현은 업로드 후 get_public_url()로 얻은 **영구 공개 URL**을 DB에 저장했다.
# 그 URL을 아는 사람은 누구나 인증 없이 이미지를 열 수 있었고, 파이프라인이
# 동작하려면 버킷 자체가 공개여야 했다. 담기는 내용물(미성년자 얼굴 사진,
# 사업자등록증의 대표자 성명·주소·사업자번호)을 생각하면 허용할 수 없는 구조다.
#
# 바뀐 구조:
#   1. 버킷은 비공개(private). 공개 URL 개념 자체를 쓰지 않는다.
#   2. DB에는 객체 경로("{member_id}/{uuid}.jpg")만 저장한다.
#   3. 읽을 때마다 VERIFICATION_SIGNED_URL_TTL_SECONDS 동안만 유효한
#      서명 URL을 발급한다.
#
# 왜 service key가 필요한가
# ------------------------
# 비공개 버킷의 객체에 대한 업로드/서명 URL 발급은 storage.objects RLS를 통과해야
# 한다. anon 키는 기본 상태에서 아무 정책도 부여받지 못하므로(실측: 버킷 목록
# 조회가 200 + 빈 배열로 돌아온다 = RLS가 전부 걸러냄) 이 작업을 수행할 수 없다.
# 따라서 이 모듈은 SUPABASE_SERVICE_KEY를 요구하고, 없으면 **명시적으로 실패**한다.
# 공개 URL이나 공개 버킷으로 조용히 되돌아가는 폴백은 두지 않는다 — 그 폴백이
# 바로 이 취약점의 원인이었다.

# 매직바이트 → MIME. 클라이언트가 보낸 Content-Type은 조작 가능하므로 신뢰하지 않고
# 실제 바이트를 검사한다. 여기 없는 형식은 업로드를 거부한다.
_IMAGE_MAGIC_BYTES = (
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
)

# 허용 MIME 화이트리스트. Gemini inline_data가 처리할 수 있는 형식으로 한정한다.
ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

# MIME → 저장 시 사용할 확장자. 사용자가 보낸 파일명은 쓰지 않는다
# (경로 탈출·이중확장자 방지). 확장자는 전적으로 스니핑 결과에서 파생시킨다.
_MIME_TO_EXTENSION = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}


class VerificationStorageError(RuntimeError):
    """스토리지 설정 누락/업로드 실패 등 인증 이미지 저장 계층 오류."""


class VerificationUploadRejected(ValueError):
    """업로드된 파일이 검증(크기/형식)을 통과하지 못했다. 사용자에게 보여줄 사유를 담는다."""


def sniff_image_mime(data: bytes) -> Optional[str]:
    """
    실제 바이트에서 이미지 MIME을 판별한다. 이미지가 아니면 None.

    선언된 Content-Type이나 파일 확장자는 전혀 참고하지 않는다 — 둘 다 공격자가
    제어할 수 있다. 판별 불가 시 기본값으로 뭉개지 않고 None을 돌려주어
    호출부가 거부할 수 있게 한다.
    """
    if not data:
        return None
    for magic, mime, _ext in _IMAGE_MAGIC_BYTES:
        if data.startswith(magic):
            return mime
    # WEBP: "RIFF" + 4바이트 크기 + "WEBP"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_verification_image(content: bytes, declared_content_type: Optional[str]) -> tuple[str, str]:
    """
    업로드된 인증 이미지를 검증한다.

    Returns:
        (실제 MIME, 저장에 쓸 확장자)

    Raises:
        VerificationUploadRejected: 비어있음/크기초과/이미지아님/화이트리스트 밖 형식.
    """
    settings = get_account_settings()

    if not content:
        raise VerificationUploadRejected("빈 파일은 업로드할 수 없습니다.")

    max_bytes = settings.VERIFICATION_MAX_UPLOAD_BYTES
    if len(content) > max_bytes:
        raise VerificationUploadRejected(
            f"파일 크기는 {max_bytes // (1024 * 1024)}MB 이하여야 합니다."
        )

    # 1차: 선언된 타입이 애초에 이미지가 아니라고 말하면 즉시 거부.
    if declared_content_type and not declared_content_type.split(";")[0].strip().startswith("image/"):
        raise VerificationUploadRejected("이미지 파일만 업로드 가능합니다.")

    # 2차(실질 방어): 실제 바이트 스니핑. 선언 타입과 무관하게 이게 최종 판단이다.
    actual_mime = sniff_image_mime(content)
    if actual_mime is None:
        raise VerificationUploadRejected(
            "이미지 파일만 업로드 가능합니다. (파일 내용이 이미지 형식이 아닙니다)"
        )

    if actual_mime not in ALLOWED_IMAGE_MIME_TYPES:
        raise VerificationUploadRejected(
            f"지원하지 않는 이미지 형식입니다: {actual_mime}. "
            "JPEG, PNG, WEBP, GIF만 업로드할 수 있습니다."
        )

    # 3차: 선언 타입이 실제와 다르면 거부. 조작된 업로드를 조용히 통과시키지 않는다.
    if declared_content_type:
        declared = declared_content_type.split(";")[0].strip().lower()
        # image/jpg 는 image/jpeg 의 흔한 오기이므로 동일 취급.
        if declared == "image/jpg":
            declared = "image/jpeg"
        if declared != actual_mime:
            raise VerificationUploadRejected(
                f"파일 내용({actual_mime})과 선언된 형식({declared})이 일치하지 않습니다."
            )

    return actual_mime, _MIME_TO_EXTENSION[actual_mime]


# 비공개 버킷 접근 전용 클라이언트(싱글톤).
# shared_core의 anon 클라이언트와 의도적으로 분리한다 — 이 자격증명은
# 인증 이미지 스토리지에만 쓰이고 요청 컨텍스트로 새어나가면 안 된다.
_storage_client = None


def reset_storage_client() -> None:
    """테스트용 캐시 리셋."""
    global _storage_client
    _storage_client = None


def get_storage_client():
    """
    인증 이미지 비공개 버킷에 접근할 Supabase 클라이언트를 반환한다.

    Raises:
        VerificationStorageError: SUPABASE_SERVICE_KEY / SUPABASE_URL 미설정.
            공개 버킷으로 폴백하지 않고 명시적으로 실패한다.
    """
    global _storage_client
    if _storage_client is not None:
        return _storage_client

    settings = get_account_settings()
    url = (settings.SUPABASE_URL or "").strip()
    service_key = (settings.SUPABASE_SERVICE_KEY or "").strip()

    if not url:
        raise VerificationStorageError(
            "SUPABASE_URL이 설정되지 않아 인증 이미지 스토리지를 사용할 수 없습니다."
        )
    if not service_key:
        raise VerificationStorageError(
            "SUPABASE_SERVICE_KEY가 설정되지 않았습니다. 인증 이미지는 비공개 버킷에 "
            "저장되어야 하며, anon 키로는 업로드·서명 URL 발급이 불가능합니다. "
            "공개 버킷으로 폴백하지 않고 업로드를 거부합니다."
        )

    _storage_client = create_client(url, service_key)
    return _storage_client


def build_verification_object_path(member_id, extension: str) -> str:
    """
    인증 이미지 객체 경로 생성: "{member_id}/{uuid}.{ext}"

    member_id를 최상위 폴더로 두면 나중에 storage.objects RLS를
    (storage.foldername(name))[1] = auth.uid()::text 형태로 걸어
    "본인 것만 접근" 정책을 만들 수 있다.

    확장자는 스니핑 결과에서만 파생되므로 사용자 파일명이 경로에 섞이지 않는다.
    """
    return f"{member_id}/{_uuid.uuid4()}.{extension}"


def upload_verification_image(object_path: str, content: bytes, content_type: str) -> str:
    """
    검증된 이미지를 비공개 버킷에 업로드한다.

    Returns:
        저장된 객체 경로 (DB에 저장할 값).

    Raises:
        VerificationStorageError: 설정 누락 또는 업로드 실패.
            실패 시 절대 공개 URL/로컬 경로로 폴백하지 않는다.
    """
    settings = get_account_settings()
    client = get_storage_client()
    bucket = settings.VERIFICATION_STORAGE_BUCKET

    try:
        client.storage.from_(bucket).upload(
            object_path,
            content,
            {"content-type": content_type},
        )
    except Exception as e:
        logger.error(f"인증 이미지 업로드 실패 (bucket={bucket}, path={object_path}): {e}")
        raise VerificationStorageError(f"인증 이미지 업로드에 실패했습니다: {e}") from e

    return object_path


def create_verification_signed_url(object_path: str, expires_in: Optional[int] = None) -> str:
    """
    객체 경로에 대해 짧은 수명의 서명 URL을 발급한다.

    공개 URL을 저장해두는 대신, 필요한 시점에 매번 새로 발급해서 즉시 소비한다.
    반환된 URL은 로그에 남기지 말 것 — 유효기간 동안은 그 자체가 접근 자격이다.

    Raises:
        VerificationStorageError: 설정 누락 또는 발급 실패.
    """
    settings = get_account_settings()
    client = get_storage_client()
    bucket = settings.VERIFICATION_STORAGE_BUCKET
    ttl = expires_in if expires_in is not None else settings.VERIFICATION_SIGNED_URL_TTL_SECONDS

    try:
        result = client.storage.from_(bucket).create_signed_url(object_path, ttl)
    except Exception as e:
        logger.error(f"서명 URL 발급 실패 (bucket={bucket}, path={object_path}): {e}")
        raise VerificationStorageError(f"서명 URL 발급에 실패했습니다: {e}") from e

    # storage3 버전에 따라 키 표기가 다르다(signedURL / signedUrl / signed_url).
    signed_url = None
    if isinstance(result, dict):
        for key in ("signedURL", "signedUrl", "signed_url"):
            if result.get(key):
                signed_url = result[key]
                break

    if not signed_url:
        raise VerificationStorageError(
            f"서명 URL 응답에서 URL을 찾지 못했습니다 (path={object_path})"
        )

    # 상대 경로로 오는 경우 절대 URL로 보정.
    if signed_url.startswith("/"):
        signed_url = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1{signed_url}"

    return signed_url


class GeminiVerifier:
    """Gemini API를 이용한 이미지 인증"""

    def __init__(self):
        self.settings = get_account_settings()
        self.api_key = self.settings.GEMINI_API_KEY
        self.model = self.settings.GEMINI_MODEL
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    async def verify_image(
        self,
        image_data: bytes,
        verification_type: VerificationType,
        expected_name: Optional[str] = None,
    ) -> GeminiVerificationResult:
        """
        이미지를 Gemini API로 분석하여 인증 결과 반환
        """
        if not self.api_key:
            logger.error("GEMINI_API_KEY가 설정되지 않았습니다")
            return GeminiVerificationResult(
                is_valid=False,
                confidence=0.0,
                rejection_reason="서버 설정 오류: Gemini API 키 없음"
            )

        try:
            image_base64 = base64.b64encode(image_data).decode("utf-8")
            mime_type = self._detect_mime_type(image_data)

            prompt = VERIFICATION_PROMPTS.get(verification_type.value)
            if not prompt:
                return GeminiVerificationResult(
                    is_valid=False,
                    confidence=0.0,
                    rejection_reason=f"지원하지 않는 인증 유형: {verification_type}"
                )

            if expected_name:
                prompt += f"\n\n참고: 확인해야 할 이름은 '{expected_name}'입니다. 추출된 이름과 일치하는지 확인하세요."

            result = await self._call_gemini_api(image_base64, mime_type, prompt)
            return result

        except Exception as e:
            logger.exception(f"Gemini 인증 중 오류: {e}")
            return GeminiVerificationResult(
                is_valid=False,
                confidence=0.0,
                rejection_reason=f"인증 처리 중 오류 발생: {str(e)}"
            )

    async def _call_gemini_api(
        self,
        image_base64: str,
        mime_type: str,
        prompt: str
    ) -> GeminiVerificationResult:
        """Gemini API 호출"""
        url = f"{self.base_url}/models/{self.model}:generateContent"

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": image_base64
                            }
                        },
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "topK": 1,
                "topP": 1,
                "maxOutputTokens": 1024,
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                json=payload,
                params={"key": self.api_key}
            )

            if response.status_code != 200:
                logger.error(f"Gemini API 오류: {response.status_code} - {response.text}")
                return GeminiVerificationResult(
                    is_valid=False,
                    confidence=0.0,
                    rejection_reason=f"API 호출 실패: {response.status_code}"
                )

            data = response.json()

            try:
                text_response = data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as e:
                logger.error(f"Gemini 응답 파싱 오류: {e}, 응답: {data}")
                return GeminiVerificationResult(
                    is_valid=False,
                    confidence=0.0,
                    rejection_reason="API 응답 형식 오류"
                )

            return self._parse_gemini_response(text_response)

    def _parse_gemini_response(self, text: str) -> GeminiVerificationResult:
        """Gemini 응답 텍스트를 파싱"""
        try:
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                json_str = text.strip()

            data = json.loads(json_str)

            return GeminiVerificationResult(
                is_valid=data.get("is_valid", False),
                confidence=float(data.get("confidence", 0.0)),
                extracted_name=data.get("extracted_name"),
                extracted_date=data.get("extracted_date"),
                extracted_organization=data.get("organization"),
                rejection_reason=data.get("rejection_reason"),
                is_mask_visible=data.get("is_mask_visible"),
                is_uniform_visible=data.get("is_uniform_visible"),
                is_name_paper_visible=data.get("is_name_paper_visible"),
                is_date_paper_visible=data.get("is_date_paper_visible"),
                mask_name=data.get("mask_name"),
                uniform_name=data.get("uniform_name"),
                is_association_logo=data.get("is_association_logo"),
                is_membership_card=data.get("is_membership_card"),
                registration_number=data.get("registration_number"),
                valid_until=data.get("valid_until"),
            )

        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 오류: {e}, 원본: {text[:500]}")
            return GeminiVerificationResult(
                is_valid=False,
                confidence=0.0,
                rejection_reason=f"응답 파싱 오류: {str(e)}"
            )

    async def verify_brn_image(self, image_data: bytes) -> Optional[dict]:
        """
        사업자등록증 이미지를 Gemini API로 분석하여 정보 추출

        Returns:
            dict: {
                "business_registration_number": "XXX-XX-XXXXX",
                "business_name": "...",
                "representative_name": "...",
                "opening_date": "YYYYMMDD",
                "confidence": 0.0-1.0,
                ...
            }
        """
        if not self.api_key:
            logger.error("GEMINI_API_KEY가 설정되지 않았습니다")
            return None

        try:
            image_base64 = base64.b64encode(image_data).decode("utf-8")
            mime_type = self._detect_mime_type(image_data)

            prompt = VERIFICATION_PROMPTS.get("business_registration")
            if not prompt:
                logger.error("business_registration prompt not found")
                return None

            result = await self._call_gemini_api(image_base64, mime_type, prompt)

            # Parse the result - for BRN we need the raw dict, not GeminiVerificationResult
            if result and result.confidence > 0:
                # Re-parse from the original text to get BRN-specific fields
                # The _call_gemini_api returns GeminiVerificationResult which doesn't have BRN fields
                # So we call directly and parse JSON
                return await self._call_gemini_brn(image_base64, mime_type, prompt)

            return None

        except Exception as e:
            logger.exception(f"BRN OCR 오류: {e}")
            return None

    async def _call_gemini_brn(
        self, image_base64: str, mime_type: str, prompt: str
    ) -> Optional[dict]:
        """Gemini API를 호출하여 BRN 정보 추출"""
        url = f"{self.base_url}/models/{self.model}:generateContent"

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": image_base64
                            }
                        },
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "topK": 1,
                "topP": 1,
                "maxOutputTokens": 1024,
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url, json=payload, params={"key": self.api_key}
            )

            if response.status_code != 200:
                logger.error(f"Gemini BRN API 오류: {response.status_code}")
                return None

            data = response.json()

            try:
                text_response = data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                logger.error("Gemini BRN 응답 파싱 오류")
                return None

            # Parse JSON from response
            try:
                json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text_response)
                if json_match:
                    json_str = json_match.group(1).strip()
                else:
                    json_str = text_response.strip()

                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.error(f"BRN JSON 파싱 오류: {e}")
                return None

    def _detect_mime_type(self, image_data: bytes) -> str:
        """
        이미지 데이터에서 MIME 타입 추측 (Gemini 요청용).

        여기 도달하는 데이터는 업로드 시점에 validate_verification_image()로 이미
        검증된 이미지다. 판별 실패 시 jpeg으로 두는 것은 Gemini 호출을 위한
        관용적 기본값일 뿐, 업로드 게이트 역할은 하지 않는다.
        """
        return sniff_image_mime(image_data) or "image/jpeg"


class VerificationProcessor:
    """인증 처리 로직"""

    def __init__(self, supabase_client):
        self.supabase = supabase_client
        self.verifier = GeminiVerifier()
        self.settings = get_account_settings()

    async def process_verification(
        self,
        verification_id: UUID,
        member_id: UUID,
    ) -> dict:
        """인증 요청 처리"""
        # 1. 인증 정보 조회
        verification = await self._get_verification(verification_id)
        if not verification:
            return {"success": False, "error": "인증 정보를 찾을 수 없습니다"}

        # 2. 회원 정보 조회 (예상 이름 가져오기)
        member = await self._get_member(member_id)
        expected_name = member.get("full_name") if member else None

        # 3. 이미지 다운로드
        # 저장된 공개 URL을 그대로 GET 하던 방식을 폐기하고, 객체 경로로부터
        # 짧은 수명의 서명 URL을 즉석에서 발급해 내려받는다.
        storage_path = verification.get("image_storage_path")
        if not storage_path:
            logger.error(
                f"인증 {verification_id}: image_storage_path가 없어 이미지를 가져올 수 없습니다"
            )
            await self._update_verification_status(
                verification_id,
                VerificationStatus.ERROR,
                "이미지 경로 정보 없음"
            )
            return {"success": False, "error": "이미지 경로 정보 없음"}

        image_data = await self._download_image(storage_path)
        if not image_data:
            await self._update_verification_status(
                verification_id,
                VerificationStatus.ERROR,
                "이미지 다운로드 실패"
            )
            return {"success": False, "error": "이미지 다운로드 실패"}

        # 4. 상태를 처리 중으로 변경
        await self._update_verification_status(verification_id, VerificationStatus.PROCESSING)

        # 5. Gemini API로 분석
        result = await self.verifier.verify_image(
            image_data,
            VerificationType(verification["verification_type"]),
            expected_name
        )

        # 6. 결과 저장
        await self._save_gemini_result(verification_id, result)

        # 7. 자동 승인/거부 결정
        final_status = await self._decide_verification(
            verification_id,
            member_id,
            result,
            expected_name
        )

        return {
            "success": True,
            "status": final_status,
            "confidence": result.confidence,
            "extracted_name": result.extracted_name,
        }

    async def _decide_verification(
        self,
        verification_id: UUID,
        member_id: UUID,
        result: GeminiVerificationResult,
        expected_name: Optional[str],
    ) -> str:
        """자동 승인/거부 결정"""
        if result.is_valid and result.confidence >= self.settings.VERIFICATION_AUTO_APPROVE_THRESHOLD:
            name_match = self._check_name_match(result.extracted_name, expected_name)

            if name_match or not expected_name:
                await self._update_verification_status(
                    verification_id,
                    VerificationStatus.APPROVED
                )
                await self._update_member_verification(member_id, "verified")
                return "approved"

        if result.confidence < self.settings.VERIFICATION_AUTO_REJECT_THRESHOLD or not result.is_valid:
            await self._update_verification_status(
                verification_id,
                VerificationStatus.REJECTED,
                result.rejection_reason or "인증 조건을 충족하지 않습니다"
            )
            return "rejected"

        logger.info(f"인증 {verification_id}: 중간 신뢰도 ({result.confidence}), 추가 검토 필요")
        return "pending"

    def _check_name_match(
        self,
        extracted_name: Optional[str],
        expected_name: Optional[str]
    ) -> bool:
        """이름 매칭 확인"""
        if not extracted_name or not expected_name:
            return False

        extracted = extracted_name.strip().lower().replace(" ", "")
        expected = expected_name.strip().lower().replace(" ", "")

        if extracted == expected:
            return True

        if extracted in expected or expected in extracted:
            return True

        common = set(extracted) & set(expected)
        similarity = len(common) / max(len(extracted), len(expected))

        return similarity >= 0.7

    async def _get_verification(self, verification_id: UUID) -> Optional[dict]:
        """인증 정보 조회"""
        try:
            result = self.supabase.table("verifications").select("*").eq("id", str(verification_id)).single().execute()
            return result.data
        except Exception as e:
            logger.error(f"인증 조회 오류: {e}")
            return None

    async def _get_member(self, member_id: UUID) -> Optional[dict]:
        """회원 정보 조회"""
        try:
            result = self.supabase.table("members").select("*").eq("id", str(member_id)).single().execute()
            return result.data
        except Exception as e:
            logger.error(f"회원 조회 오류: {e}")
            return None

    async def _download_image(self, storage_path: str) -> Optional[bytes]:
        """
        객체 경로로부터 서명 URL을 발급해 이미지를 내려받는다.

        인자는 **객체 경로**이지 URL이 아니다. 절대 URL이 들어오면 거부한다:
        - 과거의 공개 URL이 남아있다면 그걸 그대로 fetch 하는 순간 공개 접근에
          다시 의존하게 된다.
        - 임의 URL을 그대로 GET 하면 SSRF 통로가 된다.
        서명 URL은 로그에 남기지 않는다(유효기간 동안 그 자체가 접근 자격).
        """
        if "://" in storage_path or storage_path.startswith("//"):
            logger.error(
                "이미지 다운로드 거부: 객체 경로가 아닌 절대 URL이 저장되어 있습니다. "
                "공개 URL 기반 접근은 더 이상 지원하지 않습니다."
            )
            return None

        try:
            signed_url = create_verification_signed_url(storage_path)
        except VerificationStorageError as e:
            logger.error(f"이미지 서명 URL 발급 실패 (path={storage_path}): {e}")
            return None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(signed_url)
                if response.status_code == 200:
                    return response.content
                logger.error(
                    f"이미지 다운로드 실패 (path={storage_path}): HTTP {response.status_code}"
                )
                return None
        except Exception as e:
            logger.error(f"이미지 다운로드 오류 (path={storage_path}): {e}")
            return None

    async def _update_verification_status(
        self,
        verification_id: UUID,
        status: VerificationStatus,
        rejection_reason: Optional[str] = None
    ):
        """인증 상태 업데이트"""
        try:
            update_data = {
                "status": status.value,
                "processed_at": datetime.utcnow().isoformat(),
            }
            if rejection_reason:
                update_data["rejection_reason"] = rejection_reason

            self.supabase.table("verifications").update(update_data).eq("id", str(verification_id)).execute()
        except Exception as e:
            logger.error(f"인증 상태 업데이트 오류: {e}")

    async def _save_gemini_result(
        self,
        verification_id: UUID,
        result: GeminiVerificationResult
    ):
        """Gemini 결과 저장"""
        try:
            update_data = {
                "gemini_response": result.model_dump(),
                "gemini_confidence": result.confidence,
                "extracted_name": result.extracted_name,
            }

            if result.extracted_date:
                try:
                    parsed_date = datetime.strptime(result.extracted_date, "%Y-%m-%d").date()
                    update_data["extracted_date"] = parsed_date.isoformat()
                except ValueError:
                    pass

            if result.extracted_organization:
                update_data["extracted_organization"] = result.extracted_organization

            self.supabase.table("verifications").update(update_data).eq("id", str(verification_id)).execute()
        except Exception as e:
            logger.error(f"Gemini 결과 저장 오류: {e}")

    async def _update_member_verification(self, member_id: UUID, status: str):
        """회원 인증 상태 업데이트"""
        try:
            update_data = {
                "verification_status": status,
                "verified_at": datetime.utcnow().isoformat() if status == "verified" else None,
            }
            self.supabase.table("members").update(update_data).eq("id", str(member_id)).execute()
        except Exception as e:
            logger.error(f"회원 인증 상태 업데이트 오류: {e}")
