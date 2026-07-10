"""
Supabase 클라이언트 싱글톤

모든 서브도메인에서 공유하는 Supabase 클라이언트.
scraper 모델에 의존하지 않는 독립 싱글톤.
"""
from typing import Optional
from supabase import create_client, Client

from .config import get_db_config


# 싱글톤 클라이언트
_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Supabase 클라이언트 인스턴스 반환 (싱글톤)

    모든 서브도메인 서비스에서 사용.
    환경변수 SUPABASE_URL, SUPABASE_KEY 필요.
    """
    global _supabase_client
    if _supabase_client is None:
        config = get_db_config()
        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            raise ValueError("SUPABASE_URL과 SUPABASE_KEY 환경변수를 설정해주세요")
        _supabase_client = create_client(
            config.SUPABASE_URL,
            config.SUPABASE_KEY
        )
    return _supabase_client


def reset_client() -> None:
    """클라이언트 리셋 (테스트용)"""
    global _supabase_client
    _supabase_client = None
