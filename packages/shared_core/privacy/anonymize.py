"""
익명화 모듈

소속 정보 익명화, 미성년자 판별 함수 제공
"""
from typing import Optional

from shared_core.types.organization import ORG_TYPE_LABELS


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
