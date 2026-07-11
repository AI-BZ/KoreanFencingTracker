"""
메신저 연결 서비스

국가별 메신저 프로바이더 조회, 연결 상태 빌드
"""
from typing import List, Optional

from loguru import logger

from shared_core.db.client import get_supabase_client
from shared_core.utils.country import get_country_from_member


def get_messenger_for_member(member: dict) -> Optional[dict]:
    """회원의 국가에 맞는 메신저 프로바이더 조회

    Returns:
        messenger_providers row dict or None (해당 국가에 active 메신저 없음)
    """
    country = get_country_from_member(member)
    if not country:
        return None

    supabase = get_supabase_client()
    try:
        result = (
            supabase.table("messenger_providers")
            .select("*")
            .eq("country_code", country)
            .eq("is_active", True)
            .execute()
        )
        if result.data:
            return result.data[0]
    except Exception as e:
        logger.error(f"messenger_providers 조회 실패: {e}")

    return None


def get_messenger_connection_status(member_id: str, provider: str) -> Optional[dict]:
    """해당 provider의 oauth_connections에서 messaging 상태 조회

    Returns:
        oauth_connections row dict or None
    """
    supabase = get_supabase_client()
    try:
        result = (
            supabase.table("oauth_connections")
            .select("provider, messaging_enabled, messaging_role, scopes, provider_email")
            .eq("member_id", member_id)
            .eq("provider", provider)
            .execute()
        )
        if result.data:
            return result.data[0]
    except Exception as e:
        logger.error(f"oauth_connections messaging 조회 실패: {e}")

    return None


def build_messenger_context(member: dict) -> Optional[dict]:
    """대시보드 렌더링용 메신저 context 빌드

    Returns:
        dict with keys: provider_info, ui_state, connection
        or None if no active messenger for member's country
    """
    provider_info = get_messenger_for_member(member)
    if not provider_info:
        return None

    member_id = str(member["id"])
    provider = provider_info["provider"]
    required_scopes = provider_info.get("required_scopes") or []

    conn = get_messenger_connection_status(member_id, provider)

    if conn and conn.get("messaging_enabled"):
        ui_state = "connected"
    elif conn and _has_messaging_scopes(conn, required_scopes):
        # scope는 있지만 messaging_enabled=false
        ui_state = "enable"
    elif conn:
        # OAuth 연결은 있지만 messaging scope 없음
        ui_state = "upgrade"
    else:
        # 해당 provider로 OAuth 연결 자체가 없음
        ui_state = "connect"

    return {
        "provider_info": provider_info,
        "ui_state": ui_state,
        "connection": conn,
    }


def _has_messaging_scopes(conn: dict, required_scopes: List[str]) -> bool:
    """OAuth 연결에 메시징 scope가 있는지 확인"""
    granted = conn.get("scopes") or []
    if isinstance(granted, str):
        granted = granted.split()
    return all(s in granted for s in required_scopes)
