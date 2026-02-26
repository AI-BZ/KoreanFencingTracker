"""
Global Error Handlers - 전역 예외 처리

프로덕션 환경에서 상세 에러 정보 노출을 방지하고
일관된 에러 응답 형식을 제공합니다.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger


async def global_exception_handler(request: Request, exc: Exception):
    """처리되지 않은 예외를 위한 전역 핸들러

    - 에러 로그 기록
    - 클라이언트에게는 최소한의 정보만 반환
    """
    logger.error(
        "Unhandled error on {method} {path}: {error}",
        method=request.method,
        path=request.url.path,
        error=str(exc),
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "서버 내부 오류가 발생했습니다",
            "type": type(exc).__name__,
        },
    )


async def value_error_handler(request: Request, exc: ValueError):
    """ValueError 전역 핸들러 (잘못된 입력값)"""
    logger.warning(
        "ValueError on {method} {path}: {error}",
        method=request.method,
        path=request.url.path,
        error=str(exc),
    )

    return JSONResponse(
        status_code=400,
        content={
            "detail": str(exc),
            "type": "ValueError",
        },
    )
