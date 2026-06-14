"""
App Service 설정
"""
import os


class AppSettings:
    """App 서비스 설정"""

    # 서비스 기본 정보
    SERVICE_NAME: str = "app"
    SERVICE_PORT: int = 77
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Account 서비스 URL (인증 리다이렉트용)
    ACCOUNT_SERVICE_URL: str = os.getenv(
        "ACCOUNT_SERVICE_URL", "https://account.fencingmind.ai"
    )

    # Supabase
    SUPABASE_URL: str = os.getenv(
        "SUPABASE_URL", "https://tjfjuasvjzjawyckengv.supabase.co"
    )
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

    # FCM (Phase 4에서 사용)
    FCM_VAPID_PUBLIC_KEY: str = os.getenv("FCM_VAPID_PUBLIC_KEY", "")
    FCM_VAPID_PRIVATE_KEY: str = os.getenv("FCM_VAPID_PRIVATE_KEY", "")

    # 카카오 알림톡 (Phase 6에서 사용)
    KAKAO_ALIMTALK_SENDER_KEY: str = os.getenv("KAKAO_ALIMTALK_SENDER_KEY", "")

    # 이벤트 폴링 간격 (초)
    EVENT_POLL_INTERVAL: int = int(os.getenv("EVENT_POLL_INTERVAL", "30"))

    # 이벤트 폴러 활성화 (Phase 3). 테스트/로컬에서 끄려면 APP_ENABLE_POLLER=false
    ENABLE_POLLER: bool = os.getenv("APP_ENABLE_POLLER", "true").lower() == "true"


settings = AppSettings()
