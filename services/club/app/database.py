"""
Supabase 클라이언트 - shared_core 래퍼

shared_core.db.client의 싱글톤 클라이언트를 재수출합니다.
기존 import 호환성 유지: from ..database import get_supabase_client
"""
from shared_core.db.client import get_supabase_client

__all__ = ["get_supabase_client"]
