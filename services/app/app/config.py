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

    # 카카오 알림톡 (현재 계획 보류 — hidden)
    # ─────────────────────────────────────────────────────────────────────
    # 🔕 2026-06: 비즈니스 채널 알림톡은 현재 계획에서 제외. 앱 알림(in_app)+웹 푸시
    #   +이메일로 충분하다고 판단. 코드/설정/DB 컬럼은 재활성화 대비 보존만 한다.
    #   재활성화: ENABLE_KAKAO_ALIMTALK=true + 아래 자격증명 + settings.html 토글 복원.
    #   (참고: 코치→회원 개인 카카오 메시지 기능은 club 서비스에서 별도 진행 — 알림톡 아님)
    #
    # 카카오 알림톡은 (1) 카카오 비즈니스 채널, (2) 사전 승인된 템플릿(코드),
    # (3) 중계 발송 대행사(릴레이 프로바이더)를 모두 갖춰야 동작한다.
    # 아래 값이 모두 채워지기 전까지 발송 경로는 안전하게 no-op('pending')으로 동작.
    #
    # 디스패처 게이트: 기본 False → kakao 발송 경로 자체를 호출하지 않음.
    ENABLE_KAKAO_ALIMTALK: bool = os.getenv("ENABLE_KAKAO_ALIMTALK", "false").lower() == "true"
    #
    # 레퍼런스 구현 대상 프로바이더: Solapi (구 CoolSMS).
    #   - 다른 프로바이더(NHN Cloud Toast, Bizm, Aligo 등)는 BASE_URL/PROVIDER만
    #     바꿔 kakao.py에 어댑터를 추가하는 식으로 확장한다.
    KAKAO_ALIMTALK_SENDER_KEY: str = os.getenv("KAKAO_ALIMTALK_SENDER_KEY", "")

    # 발송 대행사 식별자 (예: 'solapi'). 비어있으면 not_configured.
    KAKAO_ALIMTALK_PROVIDER: str = os.getenv("KAKAO_ALIMTALK_PROVIDER", "")
    # 대행사 API 자격증명
    KAKAO_ALIMTALK_API_KEY: str = os.getenv("KAKAO_ALIMTALK_API_KEY", "")
    KAKAO_ALIMTALK_API_SECRET: str = os.getenv("KAKAO_ALIMTALK_API_SECRET", "")
    # 대행사 REST API 베이스 URL (프로바이더별 기본값은 kakao.py에서 보정)
    KAKAO_ALIMTALK_BASE_URL: str = os.getenv("KAKAO_ALIMTALK_BASE_URL", "")
    # 카카오 비즈니스 채널 ID (플러스친구 ID, '@'로 시작하는 검색용 ID 또는 PFID)
    KAKAO_ALIMTALK_PFID: str = os.getenv("KAKAO_ALIMTALK_PFID", "")

    # 카테고리 → 사전 승인된 템플릿 코드 매핑.
    #   env로 카테고리별 개별 주입 (없으면 빈 문자열 → 해당 카테고리 발송 skip).
    #   템플릿은 카카오 검수 통과 후 발급된 코드여야 한다.
    KAKAO_ALIMTALK_TEMPLATE_COMPETITION_RESULT: str = os.getenv(
        "KAKAO_ALIMTALK_TEMPLATE_COMPETITION_RESULT", ""
    )
    KAKAO_ALIMTALK_TEMPLATE_RANKING_CHANGE: str = os.getenv(
        "KAKAO_ALIMTALK_TEMPLATE_RANKING_CHANGE", ""
    )

    @property
    def kakao_template_map(self) -> dict[str, str]:
        """카테고리 → 템플릿 코드. 빈 값은 그대로 둠(발송 시 누락 처리)."""
        return {
            "competition_result": self.KAKAO_ALIMTALK_TEMPLATE_COMPETITION_RESULT,
            "ranking_change": self.KAKAO_ALIMTALK_TEMPLATE_RANKING_CHANGE,
        }

    # 이벤트 폴링 간격 (초)
    EVENT_POLL_INTERVAL: int = int(os.getenv("EVENT_POLL_INTERVAL", "30"))

    # 이벤트 폴러 활성화 (Phase 3). 테스트/로컬에서 끄려면 APP_ENABLE_POLLER=false
    ENABLE_POLLER: bool = os.getenv("APP_ENABLE_POLLER", "true").lower() == "true"


settings = AppSettings()
