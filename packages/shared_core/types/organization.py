"""
조직 관련 타입 정의
"""
from enum import Enum


class OrganizationType(str, Enum):
    """조직 유형"""
    CLUB = "club"                  # 펜싱 클럽
    ELEMENTARY = "elementary"      # 초등학교
    MIDDLE = "middle"              # 중학교
    HIGH = "high"                  # 고등학교
    UNIVERSITY = "university"      # 대학교
    PROFESSIONAL = "professional"  # 실업팀


# 소속 유형 → 한국어 라벨 매핑
ORG_TYPE_LABELS = {
    "club": "클럽",
    "elementary": "초등학교",
    "middle": "중학교",
    "high": "고등학교",
    "university": "대학교",
    "professional": "실업팀",
}
