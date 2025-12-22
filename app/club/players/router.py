"""
Player Data API Router

선수 데이터 연동 API - 클럽 관리 SaaS의 핵심 기능
코치가 소속 선수들의 대회 성적, 랭킹, 상대 전적을 모두 활용
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import (
    ClubMemberContext,
    get_current_club_member,
    require_coach,
    require_staff
)
from ..models import (
    PlayerSearchResult,
    PlayerProfile,
    CompetitionHistory,
    HeadToHeadRecord,
    PlayerStats,
    TeamRoster
)
from .service import player_service

router = APIRouter(prefix="/players", tags=["Player Data"])


# =============================================
# 선수 검색 및 연결
# =============================================

@router.get("/search", response_model=List[PlayerSearchResult])
async def search_players(
    q: str = Query(..., min_length=2, description="검색어 (이름 또는 소속팀)"),
    weapon: Optional[str] = Query(None, description="무기 필터 (foil, epee, sabre)"),
    limit: int = Query(20, ge=1, le=100),
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    선수 검색

    기존 players 테이블에서 선수를 검색합니다.
    클럽 회원과 연결하기 위한 선수를 찾을 때 사용합니다.
    """
    results = await player_service.search_players(q, weapon, limit)
    return results


@router.post("/link/{member_id}/{player_id}")
async def link_player_to_member(
    member_id: str,
    player_id: int,
    member: ClubMemberContext = Depends(require_staff)
):
    """
    회원-선수 연결

    클럽 회원을 players 테이블의 선수와 연결합니다.
    연결 후 해당 회원의 대회 성적, 랭킹 등을 조회할 수 있습니다.

    - staff 이상 권한 필요
    - 같은 조직의 회원만 연결 가능
    """
    try:
        success = await player_service.link_player_to_member(
            member_id, player_id, member.organization_id
        )
        if success:
            return {"message": "선수가 연결되었습니다", "player_id": player_id}
        raise HTTPException(status_code=400, detail="연결에 실패했습니다")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/link/{member_id}")
async def unlink_player_from_member(
    member_id: str,
    member: ClubMemberContext = Depends(require_staff)
):
    """
    회원-선수 연결 해제

    클럽 회원과 선수의 연결을 해제합니다.
    """
    success = await player_service.unlink_player_from_member(
        member_id, member.organization_id
    )
    if success:
        return {"message": "선수 연결이 해제되었습니다"}
    raise HTTPException(status_code=400, detail="연결 해제에 실패했습니다")


# =============================================
# 선수 프로필 및 통계
# =============================================

@router.get("/{player_id}/profile", response_model=PlayerProfile)
async def get_player_profile(
    player_id: int,
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    선수 전체 프로필

    선수의 기본 정보, 통계, 메달 수, 최근 랭킹을 조회합니다.
    """
    profile = await player_service.get_player_profile(player_id)
    if not profile:
        raise HTTPException(status_code=404, detail="선수를 찾을 수 없습니다")
    return profile


@router.get("/{player_id}/stats", response_model=PlayerStats)
async def get_player_stats(
    player_id: int,
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    선수 성과 지표

    Pool 승률, DE 진출률, 평균 라운드 진출 등 상세 통계를 조회합니다.
    """
    stats = await player_service.get_player_stats(player_id)
    return {
        "player_id": player_id,
        "player_name": "",  # 서비스에서 추가 필요
        **stats
    }


# =============================================
# 대회 히스토리
# =============================================

@router.get("/{player_id}/competitions", response_model=List[CompetitionHistory])
async def get_competition_history(
    player_id: int,
    year: Optional[int] = Query(None, description="연도 필터"),
    weapon: Optional[str] = Query(None, description="무기 필터"),
    limit: int = Query(50, ge=1, le=200),
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    대회 출전 히스토리

    선수의 모든 대회 출전 기록을 조회합니다.
    종목별 Pool 성적, DE 진출 라운드, 최종 순위 포함.
    """
    history = await player_service.get_competition_history(
        player_id, year, weapon, limit
    )
    return history


@router.get("/{player_id}/rankings")
async def get_ranking_history(
    player_id: int,
    weapon: Optional[str] = Query(None, description="무기 필터"),
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    랭킹 변동 히스토리

    선수의 연도별 랭킹 변동을 조회합니다.
    그래프 시각화용 데이터를 제공합니다.
    """
    profile = await player_service.get_player_profile(player_id)
    if not profile:
        raise HTTPException(status_code=404, detail="선수를 찾을 수 없습니다")

    rankings = profile.get("current_rankings", [])

    if weapon:
        rankings = [r for r in rankings if r.get("weapon") == weapon]

    return {
        "player_id": player_id,
        "rankings": rankings
    }


# =============================================
# 상대 전적
# =============================================

@router.get("/{player_id}/head-to-head/{opponent_id}", response_model=HeadToHeadRecord)
async def get_head_to_head(
    player_id: int,
    opponent_id: int,
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    특정 상대와의 전적

    특정 상대와의 모든 대결 기록을 조회합니다.
    승패, 점수, 대회/라운드 정보 포함.
    """
    try:
        h2h = await player_service.get_head_to_head(player_id, opponent_id)
        return h2h
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{player_id}/opponents")
async def get_all_opponents(
    player_id: int,
    min_bouts: int = Query(2, ge=1, description="최소 대결 횟수"),
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    전체 상대 전적 목록

    해당 선수와 n번 이상 대결한 모든 상대의 전적을 조회합니다.
    라이벌 분석, 취약 상대 파악에 활용.
    """
    opponents = await player_service.get_all_opponents(player_id, min_bouts)
    return {
        "player_id": player_id,
        "total_opponents": len(opponents),
        "opponents": opponents
    }


# =============================================
# 팀 로스터 및 비교
# =============================================

@router.get("/team/roster", response_model=TeamRoster)
async def get_team_roster(
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    소속 선수 전체 현황

    클럽에 등록된 모든 회원과 연결된 선수 정보를 조회합니다.
    대회 참가 수, 최근 결과, 랭킹 포함.
    """
    try:
        roster = await player_service.get_team_roster(member.organization_id)
        return roster
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/team/compare")
async def compare_team_members(
    player_ids: str = Query(..., description="비교할 선수 ID (콤마 구분)"),
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    소속 선수 성적 비교

    여러 선수의 성적을 비교합니다.
    Pool 승률, DE 진출률, 메달 수 등 비교.
    """
    ids = [int(pid.strip()) for pid in player_ids.split(",") if pid.strip()]

    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="2명 이상의 선수를 선택하세요")

    if len(ids) > 10:
        raise HTTPException(status_code=400, detail="최대 10명까지 비교 가능합니다")

    comparisons = []
    for player_id in ids:
        profile = await player_service.get_player_profile(player_id)
        stats = await player_service.get_player_stats(player_id)

        if profile:
            comparisons.append({
                "player_id": player_id,
                "name": profile.get("name"),
                "team": profile.get("team"),
                "weapon": profile.get("weapon"),
                "total_competitions": profile.get("total_competitions", 0),
                "gold_medals": profile.get("gold_medals", 0),
                "silver_medals": profile.get("silver_medals", 0),
                "bronze_medals": profile.get("bronze_medals", 0),
                "pool_win_rate": stats.get("pool_win_rate", 0),
                "pool_indicator": stats.get("pool_indicator", 0),
                "de_avg_rounds_won": stats.get("de_avg_rounds_won", 0)
            })

    return {
        "total": len(comparisons),
        "players": comparisons
    }


@router.get("/team/upcoming")
async def get_upcoming_competitions(
    member: ClubMemberContext = Depends(get_current_club_member)
):
    """
    예정 대회 + 참가 선수

    다가오는 대회 목록과 클럽 소속 선수들의 예상 참가 현황.
    대회비/출장비 정산 연동용.
    """
    # TODO: 대회 일정 + 참가자 관리 기능 연동
    return {
        "message": "대회 참가 관리 기능과 연동 예정",
        "upcoming": []
    }


@router.get("/team/analytics")
async def get_team_analytics(
    year: Optional[int] = Query(None, description="연도 필터"),
    member: ClubMemberContext = Depends(require_coach)
):
    """
    클럽 전체 성과 분석

    클럽 소속 선수 전체의 집계 통계.
    평균 Pool 승률, 메달 분포, 성장 추이 등.

    - 코치 이상 권한 필요
    """
    roster = await player_service.get_team_roster(member.organization_id)

    # 연결된 선수만 분석
    linked_members = [m for m in roster.get("players", []) if m.get("player_id")]

    total_competitions = 0
    total_gold = 0
    total_silver = 0
    total_bronze = 0
    pool_win_rates = []

    for m in linked_members:
        player_id = m["player_id"]
        profile = await player_service.get_player_profile(player_id)
        stats = await player_service.get_player_stats(player_id)

        if profile:
            total_competitions += profile.get("total_competitions", 0)
            total_gold += profile.get("gold_medals", 0)
            total_silver += profile.get("silver_medals", 0)
            total_bronze += profile.get("bronze_medals", 0)

        if stats and stats.get("pool_total_bouts", 0) > 0:
            pool_win_rates.append(stats.get("pool_win_rate", 0))

    avg_pool_win_rate = (
        sum(pool_win_rates) / len(pool_win_rates)
        if pool_win_rates else 0
    )

    return {
        "organization_id": member.organization_id,
        "year": year,
        "total_linked_players": len(linked_members),
        "total_competitions": total_competitions,
        "medals": {
            "gold": total_gold,
            "silver": total_silver,
            "bronze": total_bronze,
            "total": total_gold + total_silver + total_bronze
        },
        "avg_pool_win_rate": round(avg_pool_win_rate, 1),
        "top_performers": sorted(
            linked_members,
            key=lambda x: x.get("competition_count", 0),
            reverse=True
        )[:5]
    }
