"""
Privacy Module - 개인정보 마스킹 및 익명화
"""
from typing import Optional

# 한글 초성 → 영어 매핑
CHOSUNG_LIST = [
    "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"
]

CHOSUNG_EN = [
    "G", "KK", "N", "D", "DD", "R", "M", "B", "BB", "S",
    "SS", "", "J", "JJ", "CH", "K", "T", "P", "H"
]

# 소속 유형 라벨
ORG_TYPE_LABELS = {
    "club": "클럽",
    "elementary": "초등학교",
    "middle": "중학교",
    "high": "고등학교",
    "university": "대학교",
    "professional": "실업팀",
}


def mask_korean_name(full_name: str) -> str:
    """
    한국어 이름을 영어 이니셜로 마스킹

    홍길동 → H.G.D.
    김철수 → G.CH.S.
    Park Soyun → P.S.

    Args:
        full_name: 전체 이름

    Returns:
        마스킹된 이름 (영어 이니셜)
    """
    if not full_name:
        return ""

    initials = []

    for char in full_name:
        # 한글 범위 체크 (가=0xAC00, 힣=0xD7A3)
        if '\uac00' <= char <= '\ud7a3':
            # 초성 인덱스 추출
            cho_index = (ord(char) - 0xAC00) // 588
            if 0 <= cho_index < len(CHOSUNG_EN):
                en_chosung = CHOSUNG_EN[cho_index]
                if en_chosung:  # 'ㅇ'은 빈 문자열
                    initials.append(en_chosung[0])
        elif char.isalpha():
            # 영문은 첫 글자만
            initials.append(char.upper())

    if not initials:
        return ""

    return '.'.join(initials) + '.'


def anonymize_team(
    team_name: Optional[str] = None,
    org_type: Optional[str] = None,
    province: Optional[str] = None
) -> str:
    """
    소속 정보를 익명화

    최병철펜싱클럽 + club + 서울 → 서울(클럽)
    한국체육대학교 + university + 경기 → 경기(대학교)

    Args:
        team_name: 원본 팀 이름 (사용하지 않음, 호환성용)
        org_type: 조직 유형 (club, middle, high, university, professional)
        province: 시/도

    Returns:
        익명화된 소속 정보
    """
    type_label = ORG_TYPE_LABELS.get(org_type, "기타") if org_type else "기타"
    region = province if province else "전국"

    return f"{region}({type_label})"


def is_minor(birth_date) -> bool:
    """
    미성년자(14세 미만) 여부 확인

    Args:
        birth_date: 생년월일 (date 객체)

    Returns:
        14세 미만이면 True
    """
    if not birth_date:
        return False

    from datetime import date
    today = date.today()
    age = today.year - birth_date.year

    # 생일 지났는지 확인
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1

    return age < 14


def get_age(birth_date) -> Optional[int]:
    """
    나이 계산

    Args:
        birth_date: 생년월일 (date 객체)

    Returns:
        만 나이
    """
    if not birth_date:
        return None

    from datetime import date
    today = date.today()
    age = today.year - birth_date.year

    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1

    return age


def mask_email(email: str) -> str:
    """
    이메일 마스킹

    example@gmail.com → e*****e@gmail.com

    Args:
        email: 원본 이메일

    Returns:
        마스킹된 이메일
    """
    if not email or '@' not in email:
        return email

    local, domain = email.split('@', 1)

    if len(local) <= 2:
        masked_local = local[0] + '*' * (len(local) - 1)
    else:
        masked_local = local[0] + '*' * (len(local) - 2) + local[-1]

    return f"{masked_local}@{domain}"


def mask_phone(phone: str) -> str:
    """
    전화번호 마스킹

    010-1234-5678 → 010-****-5678

    Args:
        phone: 원본 전화번호

    Returns:
        마스킹된 전화번호
    """
    if not phone:
        return phone

    # 숫자만 추출
    digits = ''.join(c for c in phone if c.isdigit())

    if len(digits) < 8:
        return phone

    # 마지막 4자리 제외하고 마스킹
    masked = digits[:-4] + '****' + digits[-4:]

    # 원본 형식 유지
    if '-' in phone:
        if len(digits) == 11:
            return f"{masked[:3]}-****-{masked[-4:]}"
        elif len(digits) == 10:
            return f"{masked[:3]}-***-{masked[-4:]}"

    return masked


# =============================================
# 테스트용 함수
# =============================================
if __name__ == "__main__":
    # 이름 마스킹 테스트
    test_names = ["홍길동", "김철수", "박소윤", "이영희", "Park Soyun", "John Doe"]
    print("=== 이름 마스킹 테스트 ===")
    for name in test_names:
        print(f"{name} → {mask_korean_name(name)}")

    # 소속 익명화 테스트
    print("\n=== 소속 익명화 테스트 ===")
    test_teams = [
        ("최병철펜싱클럽", "club", "서울"),
        ("한국체육대학교", "university", "경기"),
        ("경기고등학교", "high", "경기"),
        ("삼성전자", "professional", "서울"),
    ]
    for team, org_type, province in test_teams:
        print(f"{team} → {anonymize_team(team, org_type, province)}")
