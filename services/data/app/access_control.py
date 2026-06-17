"""
접근 등급 제어 유틸리티

등급:
- guest: 비로그인
- member: 로그인 (일반 회원)
- verified: 선수인증 완료 (선수, 부모, 클럽/학교 감독·코치 포함)

접근 제한 요약:
- 검색 자동완성: guest → 소속 blur / member+ → 전체 공개
- 선수 프로필: guest → 기본정보만+blur / member → 통계O, H2H·Lab blur / verified → 전체
- 랭킹: guest → 상위10명 블러(이름·소속 마스킹) / member+ → 전체 공개
- FencingLab: verified만 접근 가능
"""
from typing import Optional, Tuple

from fastapi import Request


# 선수인증과 동일 등급 부여 대상 (사용자 요구사항)
VERIFIED_MEMBER_TYPES = frozenset({
    "player",           # 선수
    "player_parent",    # 선수 부모
    "club_director",    # 클럽 감독
    "club_coach",       # 클럽 코치
    "school_director",  # 학교 감독
    "school_coach",     # 학교 코치
})


async def get_access_level(request: Request) -> Tuple[str, Optional[dict]]:
    """
    현재 요청의 접근 등급 판별.

    Returns:
        ("guest"|"member"|"verified", member_dict_or_None)
    """
    from app.auth.router import get_current_member

    member = await get_current_member(request)

    if member is None:
        return "guest", None

    member_type = member.get("member_type", "general")
    verification_status = member.get("verification_status", "pending")
    player_id = member.get("player_id")

    if member_type in VERIFIED_MEMBER_TYPES and (
        verification_status == "verified" or player_id is not None
    ):
        return "verified", member

    return "member", member


# =============================================
# 랭킹 접근 제어
# =============================================

RANKINGS_HIDDEN_TOP_N = 10  # guest에게 숨기는 상위 N명


def filter_rankings_for_guest(rankings: list) -> list:
    """guest용: 상위 10명은 이름·소속 마스킹, 순위·점수·메달은 유지 (전체 반환)"""
    return rankings  # 전체 반환, 블러 처리는 RankingEntry 생성 후 적용


def blur_ranking_entries(entries: list, count: int = RANKINGS_HIDDEN_TOP_N) -> list:
    """RankingEntry 리스트에서 상위 N개의 이름·소속을 마스킹"""
    for i, entry in enumerate(entries):
        if i < count:
            entry.name = "????"
            entry.display_name = "????"
            entry.teams = ["????"]
            entry.display_teams = ["????"]
            entry.blurred = True
    return entries


# =============================================
# 검색 자동완성 접근 제어
# =============================================

def blur_search_result_for_guest(result: dict) -> dict:
    """guest용: 소속(팀) 정보 블러 처리"""
    blurred = {**result}
    blurred["teams"] = None
    blurred["current_team"] = None
    blurred["team_history"] = None
    blurred["blurred"] = True
    return blurred


# =============================================
# 선수 프로필 접근 제어
# =============================================

def can_access_fencinglab(access_level: str) -> bool:
    return access_level == "verified"


def apply_player_data_gate(data: dict, access_level: str) -> dict:
    """선수 프로필 데이터를 등급에 따라 필터링 (JSON API용)"""
    if access_level == "verified":
        return data

    result = {**data}

    if access_level == "guest":
        # 기본 정보만 (이름, 대회수 정도)
        result["stats"] = None
        result["head_to_head"] = None
        result["fencinglab"] = None
        result["bout_stats"] = None
        result["round_stats"] = None
        result["records"] = None
        result["requires_login"] = True

    elif access_level == "member":
        # 통계는 공개, H2H와 FencingLab은 인증 필요
        result["head_to_head"] = None
        result["fencinglab"] = None
        result["requires_verification"] = True

    return result
