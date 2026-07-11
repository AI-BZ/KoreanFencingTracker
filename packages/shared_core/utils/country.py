"""
국가 코드 유틸리티

phone_country_code ("+82") → ISO 국가 코드 ("KR") 변환
"""
from typing import Optional

PHONE_TO_COUNTRY = {
    "+82": "KR",   # 한국
    "+81": "JP",   # 일본
    "+886": "TW",  # 대만
    "+852": "HK",  # 홍콩
    "+65": "SG",   # 싱가포르
    "+86": "CN",   # 중국
    "+1": "US",    # 미국/캐나다
    "+44": "GB",   # 영국
    "+33": "FR",   # 프랑스
    "+49": "DE",   # 독일
    "+39": "IT",   # 이탈리아
    "+34": "ES",   # 스페인
    "+61": "AU",   # 호주
}


def phone_to_country(phone_country_code: str) -> Optional[str]:
    """전화 국가코드 → ISO 국가코드 변환"""
    return PHONE_TO_COUNTRY.get(phone_country_code)


def get_country_from_member(member: dict) -> Optional[str]:
    """회원 정보에서 ISO 국가코드 추출"""
    return phone_to_country(member.get("phone_country_code", "+82"))
