"""
회원 관련 공유 타입 정의

모든 서브도메인에서 공유하는 회원, 인증, 역할 관련 Enum
"""
from enum import Enum


class MemberType(str, Enum):
    """회원 유형"""
    PLAYER = "player"                # 선수회원
    PLAYER_PARENT = "player_parent"  # 선수 부모회원
    CLUB_COACH = "club_coach"        # 클럽 코치
    SCHOOL_COACH = "school_coach"    # 학교 코치
    GENERAL = "general"              # 일반 회원


class VerificationType(str, Enum):
    """인증 유형"""
    ASSOCIATION_CARD = "association_card"  # 협회 등록증
    MASK_PHOTO = "mask_photo"              # 마스크 + 이름 + 날짜 종이
    UNIFORM_PHOTO = "uniform_photo"        # 도복 + 이름 + 날짜 종이


class VerificationStatus(str, Enum):
    """인증 상태"""
    PENDING = "pending"        # 처리 대기
    PROCESSING = "processing"  # 처리 중
    APPROVED = "approved"      # 승인
    REJECTED = "rejected"      # 거부
    ERROR = "error"            # 오류


class MemberVerificationStatus(str, Enum):
    """회원 인증 상태"""
    PENDING = "pending"      # 인증 대기
    SUBMITTED = "submitted"  # 인증 제출됨
    VERIFIED = "verified"    # 인증 완료
    REJECTED = "rejected"    # 인증 거부
    EXPIRED = "expired"      # 인증 만료


class OAuthProvider(str, Enum):
    """OAuth 제공자"""
    KAKAO = "kakao"
    GOOGLE = "google"
    X = "x"


class ClubRole(str, Enum):
    """클럽 내 역할"""
    owner = "owner"           # 클럽 소유자/대표
    head_coach = "head_coach" # 수석 코치
    coach = "coach"           # 코치
    assistant = "assistant"   # 보조 코치
    student = "student"       # 수강생
    parent = "parent"         # 학부모
    staff = "staff"           # 행정 스태프


class MemberStatus(str, Enum):
    """회원 상태"""
    active = "active"         # 활성
    inactive = "inactive"     # 휴회
    suspended = "suspended"   # 정지
    graduated = "graduated"   # 졸업/퇴회
