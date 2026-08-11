"""
Security Middleware - Rate Limiting & Request Validation

요청 속도 제한 및 보안 헤더 미들웨어.
"""

import time
from collections import defaultdict
from typing import Callable, Dict, List

from fastapi import Request, HTTPException
from loguru import logger


class RateLimiter:
    """IP 기반 요청 속도 제한

    기본: 분당 60회. 초과 시 429 Too Many Requests.
    """

    def __init__(self, calls_per_minute: int = 60):
        self.calls_per_minute = calls_per_minute
        self.requests: Dict[str, List[float]] = defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        """클라이언트 IP 추출 (프록시 헤더 고려)"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        if request.client:
            return request.client.host

        return "unknown"

    async def check(self, request: Request):
        """요청 속도 확인 - 초과 시 HTTPException(429) 발생"""
        client_ip = self._get_client_ip(request)
        now = time.time()

        # 60초 이상 된 기록 제거
        self.requests[client_ip] = [
            t for t in self.requests[client_ip] if now - t < 60
        ]

        if len(self.requests[client_ip]) >= self.calls_per_minute:
            logger.warning(f"Rate limit exceeded: {client_ip} ({len(self.requests[client_ip])} req/min)")
            raise HTTPException(
                status_code=429,
                detail="요청이 너무 많습니다. 잠시 후 다시 시도해주세요."
            )

        self.requests[client_ip].append(now)

    def cleanup(self):
        """오래된 기록 정리 (메모리 관리)"""
        now = time.time()
        expired_ips = []
        for ip, times in self.requests.items():
            self.requests[ip] = [t for t in times if now - t < 60]
            if not self.requests[ip]:
                expired_ips.append(ip)
        for ip in expired_ips:
            del self.requests[ip]


# 싱글톤 인스턴스
rate_limiter = RateLimiter(calls_per_minute=60)
