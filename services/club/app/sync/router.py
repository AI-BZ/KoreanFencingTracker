"""
Sync Router - 데이터 동기화 API

POST /sync/players          - 수동 동기화 트리거 (코치+)
GET  /sync/status           - 최근 동기화 상태
GET  /sync/history          - 동기화 이력
GET  /sync/cached-roster    - 캐시된 로스터 (즉시 응답)
POST /sync/webhook          - data 서비스 웹훅 (인증 불필요)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from ..club.dependencies import (
    ClubMemberContext,
    get_current_club_member,
    require_coach,
)
from ..database import get_supabase_client
from .models import SyncResult, SyncLogResponse, CachedRosterResponse
from .service import sync_service

router = APIRouter(prefix="/sync", tags=["Sync"])


# =============================================
# 수동 동기화
# =============================================

@router.post("/players", response_model=SyncResult)
async def trigger_player_sync(
    member: ClubMemberContext = Depends(require_coach),
):
    """
    선수 데이터 수동 동기화 (코치 이상)

    클럽 학생 회원의 선수 데이터를 data 서비스에서 일괄 조회하여
    app_player_cache 테이블에 동기화합니다.

    - 1회 HTTP 호출로 클럽 전체 선수 검색 (N+1 문제 해결)
    - 매칭된 선수의 프로필을 배치 조회 (최대 5개 동시)
    - 결과를 app_player_cache에 upsert
    """
    org_id = member.organization_id

    # 조직 이름 조회
    supabase = get_supabase_client()
    org_response = supabase.table("organizations").select(
        "name"
    ).eq("id", org_id).single().execute()

    if not org_response.data:
        raise HTTPException(404, "조직을 찾을 수 없습니다")

    org_name = org_response.data["name"]

    logger.info(
        "수동 동기화 요청: org_id={}, org_name={}, by={}",
        org_id, org_name, member.member_id,
    )

    result = await sync_service.sync_club_players(org_id, org_name)
    return result


# =============================================
# 동기화 상태 조회
# =============================================

@router.get("/status")
async def get_sync_status(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    최근 동기화 상태 조회

    가장 최근의 동기화 로그를 반환합니다.
    동기화가 진행 중인지, 마지막 동기화가 언제였는지 확인합니다.
    """
    status = await sync_service.get_sync_status(member.organization_id)

    if not status:
        return {
            "message": "동기화 기록이 없습니다. POST /api/sync/players로 첫 동기화를 실행하세요.",
            "last_sync": None,
        }

    return {
        "last_sync": status,
    }


@router.get("/history")
async def get_sync_history(
    limit: int = Query(10, ge=1, le=50, description="조회 개수"),
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    동기화 이력 조회

    최근 동기화 로그 목록을 반환합니다.
    """
    history = await sync_service.get_sync_history(
        member.organization_id, limit
    )

    return {
        "items": history,
        "total": len(history),
    }


# =============================================
# 캐시된 로스터
# =============================================

@router.get("/cached-roster", response_model=CachedRosterResponse)
async def get_cached_roster(
    member: ClubMemberContext = Depends(get_current_club_member),
):
    """
    캐시된 로스터 조회 (즉시 응답)

    app_player_cache에서 사전 동기화된 선수 데이터를 조회합니다.
    HTTP 호출 없이 DB 조회만으로 즉시 응답합니다.

    데이터가 없으면 먼저 POST /api/sync/players로 동기화하세요.
    """
    org_id = member.organization_id
    roster = await sync_service.get_cached_roster(org_id)

    # 마지막 동기화 시간 (가장 최근 last_synced_at)
    last_synced_at = None
    if roster:
        synced_times = [
            r.get("last_synced_at") for r in roster if r.get("last_synced_at")
        ]
        if synced_times:
            last_synced_at = max(synced_times)

    return {
        "organization_id": org_id,
        "total_members": len(roster),
        "last_synced_at": last_synced_at,
        "players": roster,
    }


# =============================================
# Webhook (data 서비스 → club 서비스)
# =============================================

@router.post("/webhook")
async def sync_webhook(payload: dict):
    """
    data 서비스 웹훅 - 선수 데이터 변경 시 자동 동기화

    data 서비스에서 선수 데이터가 업데이트되면 이 엔드포인트를 호출합니다.
    인증 불필요 (서비스 간 내부 통신).

    payload: {
        "event": "player_updated" | "competition_scraped",
        "organization_id": int (optional),
        "organization_name": str (optional),
    }
    """
    event = payload.get("event", "unknown")
    org_id = payload.get("organization_id")
    org_name = payload.get("organization_name")

    logger.info("동기화 웹훅 수신: event={}, org_id={}", event, org_id)

    # organization_id가 없으면 전체 동기화 불가
    if not org_id:
        # org_name으로 조직 검색
        if org_name:
            try:
                supabase = get_supabase_client()
                org_response = supabase.table("organizations").select(
                    "id, name"
                ).ilike("name", f"%{org_name}%").limit(1).execute()

                if org_response.data:
                    org_id = org_response.data[0]["id"]
                    org_name = org_response.data[0]["name"]
            except Exception as e:
                logger.error("웹훅: 조직 검색 실패: {}", e)
                raise HTTPException(400, "organization_id 또는 organization_name이 필요합니다")

        if not org_id:
            raise HTTPException(400, "organization_id 또는 organization_name이 필요합니다")

    # org_name이 없으면 DB에서 조회
    if not org_name:
        try:
            supabase = get_supabase_client()
            org_response = supabase.table("organizations").select(
                "name"
            ).eq("id", org_id).single().execute()

            if org_response.data:
                org_name = org_response.data["name"]
            else:
                raise HTTPException(404, f"조직 ID {org_id}를 찾을 수 없습니다")
        except HTTPException:
            raise
        except Exception as e:
            logger.error("웹훅: 조직 조회 실패: {}", e)
            raise HTTPException(500, f"조직 조회 실패: {str(e)}")

    # 동기화 실행
    result = await sync_service.sync_club_players(org_id, org_name)

    return {
        "success": result.get("status") != "failed",
        "event": event,
        "sync_result": result,
    }
