"""
JWT 토큰 생성 및 검증

모든 서브도메인에서 공유하는 커스텀 JWT 인증.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Request
from jose import jwt, JWTError
from loguru import logger

from .config import get_shared_auth_settings
from shared_core.db.client import get_supabase_client


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    JWT 토큰 생성

    Args:
        data: 토큰에 포함할 데이터 (member_id, email, member_type 등)
        expires_delta: 만료 시간 (기본: 24시간)

    Returns:
        JWT 토큰 문자열
    """
    settings = get_shared_auth_settings()
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """
    JWT 토큰 디코딩

    Args:
        token: JWT 토큰 문자열

    Returns:
        디코딩된 payload 딕셔너리 또는 None
    """
    settings = get_shared_auth_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        return None


def extract_token(request: Request) -> Optional[str]:
    """
    요청에서 JWT 토큰 추출

    Authorization 헤더 (Bearer) 또는 쿠키에서 토큰을 가져옵니다.

    Args:
        request: FastAPI Request 객체

    Returns:
        토큰 문자열 또는 None
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]

    return request.cookies.get("access_token")


async def get_current_member(request: Request) -> Optional[dict]:
    """
    현재 로그인한 회원 정보 가져오기

    JWT 토큰을 검증하고 DB에서 회원 정보를 조회합니다.

    Args:
        request: FastAPI Request 객체

    Returns:
        회원 정보 딕셔너리 또는 None
    """
    token = extract_token(request)
    if not token:
        return None

    payload = decode_token(token)
    if not payload:
        return None

    member_id = payload.get("member_id")
    if not member_id:
        return None

    try:
        supabase = get_supabase_client()
        result = supabase.table("members").select("*").eq("id", member_id).single().execute()
        return result.data
    except Exception as e:
        logger.error(f"회원 조회 오류: {e}")
        return None


def require_auth(request: Request):
    """인증 필수 의존성"""
    member = request.state.member if hasattr(request.state, 'member') else None
    if not member:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return member
