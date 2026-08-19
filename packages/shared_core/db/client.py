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

    SUPABASE_SERVICE_KEY 가 있으면 그것을, 없으면 SUPABASE_KEY(anon)를 쓴다.

    서버 코드는 service key 로 도는 것이 맞다. anon key 는 공개돼도 안전하다는
    전제(RLS 가 데이터를 지킨다) 위에 설계된 키인데, 현재 이 프로젝트의 RLS 는
    사실상 열려 있어서 anon key 하나로 members·oauth_connections·consent_logs 가
    전부 읽힌다. service key 로 서버를 돌려야 RLS 를 anon 거부로 조일 수 있다.

    지금은 service key 가 어느 환경에도 없어서 anon 으로 떨어진다 — 즉 이 변경
    자체로는 동작이 달라지지 않는다. 키를 넣는 순간 서버가 RLS 를 우회하게 되고,
    그때 비로소 RLS 잠금 마이그레이션을 적용할 수 있다. 순서가 반대면 서비스가
    통째로 멈춘다.

    service key 는 RLS 를 무시하므로 **서버 환경변수로만** 두어야 한다.
    템플릿·클라이언트 번들에 절대 실어 보내지 마라.
    """
    global _supabase_client
    if _supabase_client is None:
        config = get_db_config()
        if not config.SUPABASE_URL:
            raise ValueError("SUPABASE_URL 환경변수를 설정해주세요")

        key = getattr(config, "SUPABASE_SERVICE_KEY", "") or config.SUPABASE_KEY
        if not key:
            raise ValueError(
                "SUPABASE_SERVICE_KEY 또는 SUPABASE_KEY 환경변수를 설정해주세요"
            )
        _supabase_client = create_client(config.SUPABASE_URL, key)
    return _supabase_client


def reset_client() -> None:
    """클라이언트 리셋 (테스트용)"""
    global _supabase_client
    _supabase_client = None
