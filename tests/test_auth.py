"""
Auth Router Tests - 인증 라우터 테스트
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, date
from uuid import uuid4

from fastapi.testclient import TestClient
from jose import jwt

from app.auth.models import (
    MemberType,
    MemberCreate,
    PrivacySettings,
    MemberVerificationStatus,
)
from app.auth.config import (
    get_auth_settings,
    get_available_providers,
    get_promotional_providers,
    OAUTH_PROVIDERS,
)


class TestOAuthProviders:
    """OAuth 제공자 테스트"""

    def test_get_available_providers_korea(self):
        """한국 IP - 카카오 우선"""
        providers = get_available_providers("KR")
        assert "kakao" in providers
        assert "google" in providers
        assert providers[0] == "kakao"  # 카카오 우선

    def test_get_available_providers_international(self):
        """해외 IP - 구글만"""
        providers = get_available_providers("US")
        assert "google" in providers
        assert "kakao" not in providers  # 카카오는 한국만

    def test_get_promotional_providers(self):
        """홍보용 제공자"""
        providers = get_promotional_providers()
        assert "x" in providers


class TestAuthSettings:
    """인증 설정 테스트"""

    def test_settings_defaults(self):
        """기본 설정값"""
        settings = get_auth_settings()
        assert settings.JWT_ALGORITHM == "HS256"
        assert settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES > 0
        assert settings.VERIFICATION_AUTO_APPROVE_THRESHOLD == 0.85
        assert settings.VERIFICATION_AUTO_REJECT_THRESHOLD == 0.60


class TestMemberModels:
    """회원 모델 테스트"""

    def test_member_create_valid(self):
        """유효한 회원 생성"""
        member = MemberCreate(
            full_name="홍길동",
            email="test@example.com",
            member_type=MemberType.PLAYER,
        )
        assert member.full_name == "홍길동"
        assert member.member_type == MemberType.PLAYER

    def test_member_create_with_all_fields(self):
        """모든 필드로 회원 생성"""
        member = MemberCreate(
            full_name="홍길동",
            email="test@example.com",
            phone="010-1234-5678",
            birth_date=date(2000, 1, 1),
            member_type=MemberType.PLAYER,
            organization_id=1,
            marketing_consent=True,
            promotional_consent=True,
        )
        assert member.phone == "010-1234-5678"
        assert member.birth_date == date(2000, 1, 1)

    def test_member_create_invalid_name(self):
        """이름 길이 제한"""
        with pytest.raises(ValueError):
            MemberCreate(
                full_name="홍",  # 너무 짧음
                email="test@example.com",
                member_type=MemberType.PLAYER,
            )

    def test_member_create_future_birth_date(self):
        """미래 생년월일 거부"""
        from datetime import timedelta
        future_date = date.today() + timedelta(days=1)

        with pytest.raises(ValueError):
            MemberCreate(
                full_name="홍길동",
                email="test@example.com",
                birth_date=future_date,
                member_type=MemberType.PLAYER,
            )

    def test_privacy_settings(self):
        """개인정보 설정"""
        settings = PrivacySettings(privacy_public=True)
        assert settings.privacy_public is True
        assert settings.marketing_consent is None


class TestMemberTypes:
    """회원 유형 테스트"""

    def test_all_member_types(self):
        """모든 회원 유형 확인"""
        assert MemberType.PLAYER.value == "player"
        assert MemberType.PLAYER_PARENT.value == "player_parent"
        assert MemberType.CLUB_COACH.value == "club_coach"
        assert MemberType.SCHOOL_COACH.value == "school_coach"
        assert MemberType.GENERAL.value == "general"


class TestJWTToken:
    """JWT 토큰 테스트"""

    def test_create_token(self):
        """토큰 생성"""
        from app.auth.router import create_access_token

        token = create_access_token({
            "member_id": str(uuid4()),
            "email": "test@example.com",
            "member_type": "player",
        })

        assert token is not None
        assert len(token) > 0

    def test_decode_token(self):
        """토큰 디코딩"""
        from app.auth.router import create_access_token

        member_id = str(uuid4())
        token = create_access_token({
            "member_id": member_id,
            "email": "test@example.com",
            "member_type": "player",
        })

        settings = get_auth_settings()
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )

        assert payload["member_id"] == member_id
        assert payload["email"] == "test@example.com"


class TestVerificationStatus:
    """인증 상태 테스트"""

    def test_all_statuses(self):
        """모든 인증 상태"""
        assert MemberVerificationStatus.PENDING.value == "pending"
        assert MemberVerificationStatus.SUBMITTED.value == "submitted"
        assert MemberVerificationStatus.VERIFIED.value == "verified"
        assert MemberVerificationStatus.REJECTED.value == "rejected"
        assert MemberVerificationStatus.EXPIRED.value == "expired"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
