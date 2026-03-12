"""
PortOne (한국 결제) 클라이언트 스텁

한국 회원(phone_country_code=+82)용 카카오페이/네이버페이/한국카드 결제.
Phase 4에서 전체 구현 예정.
"""
from loguru import logger


async def create_payment_session(
    member_id: str,
    service_id: str,
    tier: str,
    amount_krw: int,
) -> dict:
    """
    PortOne 결제 세션 생성 (스텁).
    Phase 4에서 구현 예정.
    """
    logger.warning("PortOne 결제는 아직 구현되지 않았습니다 (Phase 4 예정)")
    raise NotImplementedError("PortOne 한국 결제는 Phase 4에서 구현 예정입니다")


def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
    """PortOne 웹훅 서명 검증 (스텁)"""
    logger.warning("PortOne 웹훅은 아직 구현되지 않았습니다 (Phase 4 예정)")
    raise NotImplementedError("PortOne 웹훅은 Phase 4에서 구현 예정입니다")
