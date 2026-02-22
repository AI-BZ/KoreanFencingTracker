"""
독립 Supabase 클라이언트 (scraper 의존성 없음)

Club 마이크로서비스 전용 - database/supabase_client.py의 get_supabase_client()를 대체
"""
from typing import Optional
from supabase import create_client, Client
from loguru import logger

from . import config

_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Supabase 클라이언트 인스턴스 반환 (싱글톤)
    """
    global _supabase_client
    if _supabase_client is None:
        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            raise ValueError("SUPABASE_URL과 SUPABASE_KEY 환경변수를 설정해주세요")
        _supabase_client = create_client(
            config.SUPABASE_URL,
            config.SUPABASE_KEY
        )
        logger.info("Supabase client initialized")
    return _supabase_client
