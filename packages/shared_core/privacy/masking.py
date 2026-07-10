"""
개인정보 마스킹 모듈

이름, 이메일, 전화번호 마스킹 함수 제공
"""

# 한글 초성 → 영어 매핑
CHOSUNG_LIST = [
    "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"
]

CHOSUNG_EN = [
    "G", "KK", "N", "D", "DD", "R", "M", "B", "BB", "S",
    "SS", "", "J", "JJ", "CH", "K", "T", "P", "H"
]


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
