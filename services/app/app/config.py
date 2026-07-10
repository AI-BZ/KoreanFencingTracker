"""
App Service 설정
"""
import os
from pathlib import Path


def _load_dotenv() -> None:
    """services/app/.env 를 읽어 환경변수로 로드 (의존성 없는 경량 로더).

    - 형식: `KEY=value` (선택적으로 `export ` 접두사, 따옴표 허용)
    - `setdefault` 사용 → 이미 설정된 실제 환경변수(.zshrc export 등)가 우선.
    - 파일이 없거나 파싱 실패해도 앱을 막지 않는다.
    """
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, sep, val = line.partition("=")
            if not sep:
                continue
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, val)
    except Exception:
        pass


# 클래스 정의(=os.getenv 평가) 전에 .env 를 먼저 로드해야 한다.
_load_dotenv()


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

    # 워터마크 안전 지연 (초). data_events.id는 BIGSERIAL이라 커밋 순서를 보장하지 않는다.
    # (트랜잭션 A가 id=100을 먼저 채번하고 B가 id=101을 나중에 채번해도, B가 먼저 커밋될 수 있음.)
    # 방금 만들어진(=아직 in-flight일 수 있는) 이벤트를 이 시간만큼 건너뛰고 폴링해,
    # 늦게 커밋된 낮은 id가 워터마크에 추월당해 영구 누락되는 것을 막는다 (EVAL P1-2 최소 처방).
    # 대가는 알림이 최대 이 시간만큼 지연되는 것뿐(대회 결과/랭킹 특성상 무해).
    EVENT_SAFETY_LAG_SECONDS: int = int(os.getenv("EVENT_SAFETY_LAG_SECONDS", "15"))

    # 이벤트 폴러 활성화 (Phase 3). 테스트/로컬에서 끄려면 APP_ENABLE_POLLER=false
    ENABLE_POLLER: bool = os.getenv("APP_ENABLE_POLLER", "true").lower() == "true"

    # 알림 재시도 스윕 (EVAL P1-1). 폴러 커서가 지나간 failed/pending 로그를 재발송한다.
    #   - MAX_ATTEMPTS: 로그 행당 재시도 상한. 도달하면 스윕 대상에서 제외(무한 재시도 방지).
    #   - WINDOW_HOURS: created_at이 이 시간 이내인 로그만 재시도(오래된 실패는 포기).
    NOTIFY_RETRY_MAX_ATTEMPTS: int = int(os.getenv("NOTIFY_RETRY_MAX_ATTEMPTS", "3"))
    NOTIFY_RETRY_WINDOW_HOURS: int = int(os.getenv("NOTIFY_RETRY_WINDOW_HOURS", "24"))

    # 재정정 알림 스팸 억제 쿨다운 (EVAL P1-4). 대회 결과를 재스크래핑/정정하면 매번
    # 새 data_events 행(새 id)이 생겨 참가 선수 전원에게 알림이 재발송된다(스팸).
    # 같은 논리 엔티티(dedup_key = "{category}:{entity_type}:{entity_id}")에 대해 이
    # 시간 이내에 이미 발송(sent)한 회원에게는 재알림을 억제한다. 0 이하면 억제 비활성화.
    #   대가: 이 시간 안의 실제 정정 알림도 묶여 지연/생략될 수 있으나, 대회 결과/랭킹
    #   특성상 정정이 짧은 시간에 여러 번 일어나는 게 스팸의 원인이므로 이득이 크다.
    NOTIFY_DEDUP_COOLDOWN_HOURS: int = int(os.getenv("NOTIFY_DEDUP_COOLDOWN_HOURS", "6"))


settings = AppSettings()
