"""
Privacy Module Tests - 개인정보 마스킹 및 익명화 테스트
"""
import pytest
from datetime import date, timedelta
from app.auth.privacy import (
    mask_korean_name,
    anonymize_team,
    is_minor,
    get_age,
    mask_email,
    mask_phone,
)


class TestMaskKoreanName:
    """이름 마스킹 테스트"""

    def test_basic_korean_name(self):
        """기본 한글 이름 마스킹"""
        assert mask_korean_name("홍길동") == "H.G.D."
        assert mask_korean_name("김철수") == "G.C.S."  # ㅊ → C
        assert mask_korean_name("박소윤") == "B.S."  # ㅇ은 무음

    def test_korean_name_with_ieung(self):
        """ㅇ 초성 처리 - ㅇ은 스킵됨"""
        assert mask_korean_name("이영희") == "H."  # ㅇㅇㅎ → H만 남음
        assert mask_korean_name("안철수") == "C.S."  # ㅇㅊㅅ → C.S.

    def test_english_name(self):
        """영어 이름 처리"""
        assert mask_korean_name("John") == "J.O.H.N."
        assert mask_korean_name("Park") == "P.A.R.K."

    def test_mixed_name(self):
        """한영 혼합 이름"""
        assert mask_korean_name("박Soyun") == "B.S.O.Y.U.N."

    def test_empty_name(self):
        """빈 이름 처리"""
        assert mask_korean_name("") == ""
        assert mask_korean_name(None) == ""

    def test_special_characters(self):
        """특수문자 포함 이름"""
        assert mask_korean_name("홍 길동") == "H.G.D."  # 공백 무시
        assert mask_korean_name("홍-길동") == "H.G.D."  # 하이픈 무시


class TestAnonymizeTeam:
    """소속 익명화 테스트"""

    def test_club(self):
        """클럽 익명화"""
        assert anonymize_team("최병철펜싱클럽", "club", "서울") == "서울(클럽)"

    def test_school_types(self):
        """학교 유형별 익명화"""
        assert anonymize_team("펜싱초등학교", "elementary", "경기") == "경기(초등학교)"
        assert anonymize_team("펜싱중학교", "middle", "부산") == "부산(중학교)"
        assert anonymize_team("펜싱고등학교", "high", "대구") == "대구(고등학교)"

    def test_university(self):
        """대학교 익명화"""
        assert anonymize_team("한국체육대학교", "university", "경기") == "경기(대학교)"

    def test_professional(self):
        """실업팀 익명화"""
        assert anonymize_team("삼성전자", "professional", "서울") == "서울(실업팀)"

    def test_unknown_type(self):
        """알 수 없는 유형"""
        assert anonymize_team("기타팀", "unknown", "서울") == "서울(기타)"
        assert anonymize_team("기타팀", None, "서울") == "서울(기타)"

    def test_no_province(self):
        """시도 없음"""
        assert anonymize_team("팀명", "club", None) == "전국(클럽)"
        assert anonymize_team("팀명", "club", "") == "전국(클럽)"  # 빈 문자열도 전국


class TestIsMinor:
    """미성년자 확인 테스트"""

    def test_under_14(self):
        """14세 미만"""
        today = date.today()
        birth_13 = date(today.year - 13, today.month, today.day)
        birth_10 = date(today.year - 10, 1, 1)

        assert is_minor(birth_13) is True
        assert is_minor(birth_10) is True

    def test_exactly_14(self):
        """정확히 14세"""
        today = date.today()
        birth_14 = date(today.year - 14, today.month, today.day)

        assert is_minor(birth_14) is False

    def test_over_14(self):
        """14세 이상"""
        today = date.today()
        birth_15 = date(today.year - 15, 1, 1)
        birth_20 = date(today.year - 20, 1, 1)

        assert is_minor(birth_15) is False
        assert is_minor(birth_20) is False

    def test_no_birth_date(self):
        """생년월일 없음"""
        assert is_minor(None) is False

    def test_birthday_not_passed(self):
        """생일 안 지남"""
        today = date.today()
        # 올해 생일 아직 안 지남 (다음 달)
        next_month = (today.month % 12) + 1
        year_adjustment = 1 if next_month < today.month else 0
        birth = date(today.year - 14 + year_adjustment, next_month, 1)

        # 14세가 안 됐으면 True
        if get_age(birth) < 14:
            assert is_minor(birth) is True


class TestGetAge:
    """나이 계산 테스트"""

    def test_basic_age(self):
        """기본 나이 계산"""
        today = date.today()
        birth = date(today.year - 20, 1, 1)

        age = get_age(birth)
        assert age == 20 or age == 19  # 생일 지났는지에 따라

    def test_no_birth_date(self):
        """생년월일 없음"""
        assert get_age(None) is None


class TestMaskEmail:
    """이메일 마스킹 테스트"""

    def test_basic_email(self):
        """기본 이메일 마스킹"""
        assert mask_email("example@gmail.com") == "e*****e@gmail.com"
        assert mask_email("test@naver.com") == "t**t@naver.com"

    def test_short_local(self):
        """짧은 로컬 파트"""
        assert mask_email("ab@gmail.com") == "a*@gmail.com"
        assert mask_email("a@gmail.com") == "a@gmail.com"

    def test_invalid_email(self):
        """잘못된 이메일"""
        assert mask_email("notanemail") == "notanemail"
        assert mask_email("") == ""


class TestMaskPhone:
    """전화번호 마스킹 테스트"""

    def test_mobile_with_dash(self):
        """모바일 번호 (하이픈 포함)"""
        assert mask_phone("010-1234-5678") == "010-****-5678"

    def test_mobile_without_dash(self):
        """모바일 번호 (하이픈 없음)"""
        result = mask_phone("01012345678")
        assert "****" in result
        assert result.endswith("5678")

    def test_short_number(self):
        """짧은 번호"""
        assert mask_phone("1234567") == "1234567"

    def test_empty_phone(self):
        """빈 전화번호"""
        assert mask_phone("") == ""
        assert mask_phone(None) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
