"""Auth Module - Account 서비스 리다이렉트 shim"""
from .router import router as auth_router

__all__ = ["auth_router"]
