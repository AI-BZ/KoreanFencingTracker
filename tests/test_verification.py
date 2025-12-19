"""
Verification Module Tests - Gemini API 인증 테스트
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json

from app.auth.verification import GeminiVerifier
from app.auth.models import VerificationType, GeminiVerificationResult


class TestGeminiVerifier:
    """GeminiVerifier 테스트"""

    @pytest.fixture
    def verifier(self):
        """테스트용 verifier"""
        with patch.object(GeminiVerifier, '__init__', lambda self: None):
            v = GeminiVerifier()
            v.api_key = "test-api-key"
            v.model = "gemini-2.0-flash-exp"
            v.base_url = "https://generativelanguage.googleapis.com/v1beta"
            v.settings = MagicMock()
            v.settings.GEMINI_API_KEY = "test-api-key"
            return v

    def test_detect_mime_type_png(self, verifier):
        """PNG MIME 타입 감지"""
        png_header = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        assert verifier._detect_mime_type(png_header) == "image/png"

    def test_detect_mime_type_jpeg(self, verifier):
        """JPEG MIME 타입 감지"""
        jpeg_header = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        assert verifier._detect_mime_type(jpeg_header) == "image/jpeg"

    def test_detect_mime_type_webp(self, verifier):
        """WEBP MIME 타입 감지"""
        webp_header = b'RIFF' + b'\x00\x00\x00\x00' + b'WEBP' + b'\x00' * 100
        assert verifier._detect_mime_type(webp_header) == "image/webp"

    def test_detect_mime_type_unknown(self, verifier):
        """알 수 없는 타입은 기본값 JPEG"""
        unknown_data = b'\x00\x01\x02\x03'
        assert verifier._detect_mime_type(unknown_data) == "image/jpeg"

    def test_parse_gemini_response_valid_json(self, verifier):
        """유효한 JSON 응답 파싱"""
        response_text = '''
        {
            "is_valid": true,
            "confidence": 0.95,
            "extracted_name": "홍길동",
            "is_mask_visible": true,
            "is_name_paper_visible": true,
            "rejection_reason": null
        }
        '''
        result = verifier._parse_gemini_response(response_text)

        assert result.is_valid is True
        assert result.confidence == 0.95
        assert result.extracted_name == "홍길동"
        assert result.is_mask_visible is True

    def test_parse_gemini_response_markdown_code_block(self, verifier):
        """마크다운 코드 블록 응답 파싱"""
        response_text = '''
        Here is the analysis:
        ```json
        {
            "is_valid": true,
            "confidence": 0.85,
            "extracted_name": "김철수"
        }
        ```
        '''
        result = verifier._parse_gemini_response(response_text)

        assert result.is_valid is True
        assert result.confidence == 0.85
        assert result.extracted_name == "김철수"

    def test_parse_gemini_response_invalid_json(self, verifier):
        """잘못된 JSON 응답 처리"""
        response_text = "This is not valid JSON"
        result = verifier._parse_gemini_response(response_text)

        assert result.is_valid is False
        assert result.confidence == 0.0
        assert "파싱 오류" in result.rejection_reason

    def test_parse_gemini_response_association_card(self, verifier):
        """협회 등록증 응답 파싱"""
        response_text = '''
        {
            "is_valid": true,
            "confidence": 0.90,
            "extracted_name": "박소윤",
            "is_association_logo": true,
            "is_membership_card": true,
            "registration_number": "2024-12345",
            "organization": "최병철펜싱클럽"
        }
        '''
        result = verifier._parse_gemini_response(response_text)

        assert result.is_valid is True
        assert result.is_association_logo is True
        assert result.registration_number == "2024-12345"
        assert result.extracted_organization == "최병철펜싱클럽"


class TestVerificationResult:
    """GeminiVerificationResult 모델 테스트"""

    def test_valid_result(self):
        """유효한 결과 생성"""
        result = GeminiVerificationResult(
            is_valid=True,
            confidence=0.9,
            extracted_name="홍길동",
        )
        assert result.is_valid is True
        assert result.confidence == 0.9

    def test_invalid_confidence_range(self):
        """신뢰도 범위 검증"""
        with pytest.raises(ValueError):
            GeminiVerificationResult(
                is_valid=True,
                confidence=1.5,  # 범위 초과
            )

    def test_default_values(self):
        """기본값 확인"""
        result = GeminiVerificationResult(
            is_valid=False,
            confidence=0.5,
        )
        assert result.extracted_name is None
        assert result.rejection_reason is None
        assert result.is_mask_visible is None


class TestVerificationTypes:
    """인증 유형 테스트"""

    def test_verification_type_values(self):
        """인증 유형 값 확인"""
        assert VerificationType.ASSOCIATION_CARD.value == "association_card"
        assert VerificationType.MASK_PHOTO.value == "mask_photo"
        assert VerificationType.UNIFORM_PHOTO.value == "uniform_photo"


@pytest.mark.asyncio
class TestVerifyImage:
    """이미지 인증 통합 테스트"""

    @pytest.fixture
    def mock_verifier(self):
        """모킹된 verifier"""
        with patch.object(GeminiVerifier, '__init__', lambda self: None):
            v = GeminiVerifier()
            v.api_key = "test-api-key"
            v.model = "gemini-2.0-flash-exp"
            v.base_url = "https://generativelanguage.googleapis.com/v1beta"
            v.settings = MagicMock()
            v.settings.GEMINI_API_KEY = "test-api-key"
            return v

    async def test_verify_without_api_key(self):
        """API 키 없이 인증 시도"""
        with patch.object(GeminiVerifier, '__init__', lambda self: None):
            verifier = GeminiVerifier()
            verifier.api_key = ""
            verifier.settings = MagicMock()
            verifier.settings.GEMINI_API_KEY = ""

            result = await verifier.verify_image(
                b"fake-image-data",
                VerificationType.MASK_PHOTO
            )

            assert result.is_valid is False
            assert "API 키" in result.rejection_reason

    async def test_verify_with_mock_response(self, mock_verifier):
        """모킹된 API 응답으로 인증"""
        mock_response = GeminiVerificationResult(
            is_valid=True,
            confidence=0.95,
            extracted_name="테스트",
        )

        mock_verifier._call_gemini_api = AsyncMock(return_value=mock_response)
        mock_verifier._detect_mime_type = MagicMock(return_value="image/png")

        result = await mock_verifier.verify_image(
            b'\x89PNG\r\n\x1a\n' + b'\x00' * 100,
            VerificationType.MASK_PHOTO,
            expected_name="테스트"
        )

        assert result.is_valid is True
        assert result.confidence == 0.95


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
