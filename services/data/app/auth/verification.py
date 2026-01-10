"""
Verification Module - Gemini API를 통한 자동 인증
"""
import json
import re
import base64
from datetime import date, datetime
from typing import Optional
from uuid import UUID
import httpx
from loguru import logger

from .config import get_auth_settings, VERIFICATION_PROMPTS
from .models import (
    VerificationType,
    VerificationStatus,
    GeminiVerificationResult,
)


class GeminiVerifier:
    """Gemini API를 이용한 이미지 인증"""

    def __init__(self):
        self.settings = get_auth_settings()
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

        Args:
            image_data: 이미지 바이너리 데이터
            verification_type: 인증 유형
            expected_name: 예상 이름 (선수 DB에서 가져온 이름)

        Returns:
            GeminiVerificationResult
        """
        if not self.api_key:
            logger.error("GEMINI_API_KEY가 설정되지 않았습니다")
            return GeminiVerificationResult(
                is_valid=False,
                confidence=0.0,
                rejection_reason="서버 설정 오류: Gemini API 키 없음"
            )

        try:
            # 이미지를 base64로 인코딩
            image_base64 = base64.b64encode(image_data).decode("utf-8")

            # 이미지 MIME 타입 추측
            mime_type = self._detect_mime_type(image_data)

            # 프롬프트 선택
            prompt = VERIFICATION_PROMPTS.get(verification_type.value)
            if not prompt:
                return GeminiVerificationResult(
                    is_valid=False,
                    confidence=0.0,
                    rejection_reason=f"지원하지 않는 인증 유형: {verification_type}"
                )

            # 예상 이름이 있으면 프롬프트에 추가
            if expected_name:
                prompt += f"\n\n참고: 확인해야 할 이름은 '{expected_name}'입니다. 추출된 이름과 일치하는지 확인하세요."

            # Gemini API 호출
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
                "temperature": 0.1,  # 낮은 온도로 일관된 결과
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

            # 응답에서 텍스트 추출
            try:
                text_response = data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as e:
                logger.error(f"Gemini 응답 파싱 오류: {e}, 응답: {data}")
                return GeminiVerificationResult(
                    is_valid=False,
                    confidence=0.0,
                    rejection_reason="API 응답 형식 오류"
                )

            # JSON 파싱
            return self._parse_gemini_response(text_response)

    def _parse_gemini_response(self, text: str) -> GeminiVerificationResult:
        """Gemini 응답 텍스트를 파싱"""

        try:
            # JSON 블록 추출 (마크다운 코드 블록 처리)
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                # 코드 블록이 없으면 전체 텍스트를 JSON으로 파싱 시도
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

    def _detect_mime_type(self, image_data: bytes) -> str:
        """이미지 데이터에서 MIME 타입 추측"""

        # 매직 바이트로 확인
        if image_data[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        elif image_data[:2] == b'\xff\xd8':
            return "image/jpeg"
        elif image_data[:6] in (b'GIF87a', b'GIF89a'):
            return "image/gif"
        elif image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
            return "image/webp"
        else:
            # 기본값
            return "image/jpeg"


class VerificationProcessor:
    """인증 처리 로직"""

    def __init__(self, supabase_client):
        self.supabase = supabase_client
        self.verifier = GeminiVerifier()
        self.settings = get_auth_settings()

    async def process_verification(
        self,
        verification_id: UUID,
        member_id: UUID,
    ) -> dict:
        """
        인증 요청 처리

        Args:
            verification_id: 인증 ID
            member_id: 회원 ID

        Returns:
            처리 결과
        """
        # 1. 인증 정보 조회
        verification = await self._get_verification(verification_id)
        if not verification:
            return {"success": False, "error": "인증 정보를 찾을 수 없습니다"}

        # 2. 회원 정보 조회 (예상 이름 가져오기)
        member = await self._get_member(member_id)
        expected_name = member.get("full_name") if member else None

        # 3. 이미지 다운로드
        image_data = await self._download_image(verification["image_url"])
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

        # 자동 승인 조건
        if result.is_valid and result.confidence >= self.settings.VERIFICATION_AUTO_APPROVE_THRESHOLD:
            # 이름 매칭 확인 (선택사항)
            name_match = self._check_name_match(result.extracted_name, expected_name)

            if name_match or not expected_name:
                await self._update_verification_status(
                    verification_id,
                    VerificationStatus.APPROVED
                )
                # 회원 인증 상태 업데이트
                await self._update_member_verification(member_id, "verified")
                return "approved"

        # 자동 거부 조건
        if result.confidence < self.settings.VERIFICATION_AUTO_REJECT_THRESHOLD or not result.is_valid:
            await self._update_verification_status(
                verification_id,
                VerificationStatus.REJECTED,
                result.rejection_reason or "인증 조건을 충족하지 않습니다"
            )
            return "rejected"

        # 중간 신뢰도 - 추가 검토 필요 (pending 유지)
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

        # 공백 및 대소문자 정규화
        extracted = extracted_name.strip().lower().replace(" ", "")
        expected = expected_name.strip().lower().replace(" ", "")

        # 완전 일치
        if extracted == expected:
            return True

        # 부분 일치 (extracted가 expected를 포함하거나 그 반대)
        if extracted in expected or expected in extracted:
            return True

        # 유사도 계산 (간단한 방식)
        # TODO: 더 정교한 유사도 알고리즘 적용 가능
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

    async def _download_image(self, image_url: str) -> Optional[bytes]:
        """이미지 다운로드"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(image_url)
                if response.status_code == 200:
                    return response.content
                return None
        except Exception as e:
            logger.error(f"이미지 다운로드 오류: {e}")
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

            # 날짜 파싱
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
