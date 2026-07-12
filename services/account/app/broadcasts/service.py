"""배치 이메일 발송 비즈니스 로직

- create_broadcast: 배치 생성 + 마케팅 수신동의 회원 스냅샷
- send_broadcast: pending 수신자 발송 (재개 가능, 중복발송 방지, rate limit)
- unsubscribe 토큰 생성/처리 (marketing_consent FALSE + consent_logs)

수신거부는 별도 opt-out 컬럼 없이 members.marketing_consent 를 FALSE 로 뒤집고
consent_logs(consent_type='marketing', agreed=false) 이력을 남기는 방식으로 처리한다.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger

from shared_core.auth.jwt import create_access_token, decode_token
from shared_core.db.client import get_supabase_client
from shared_core.email.service import EmailService

# unsubscribe 토큰 정책
UNSUBSCRIBE_PURPOSE = "email_unsubscribe"
UNSUBSCRIBE_TOKEN_EXPIRE_DAYS = 365

# 발송 간 대기 (Resend 초당 한도 여유) — free tier 100/일 대응은 limit 파라미터로
SEND_INTERVAL_SECONDS = 0.5

# 배치 조회 시 넉넉한 상한 (한 번에 가져올 최대 pending 수)
MAX_BULK_INSERT = 1000


def _account_base_url() -> str:
    return os.getenv("ACCOUNT_SERVICE_URL", "https://account.fencingmind.ai").rstrip("/")


# 이메일 서비스 lazy init (테스트에서 patch 가능)
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service


def create_unsubscribe_token(member_id: str) -> str:
    """수신거부 토큰 생성 (긴 만료)"""
    return create_access_token(
        {"purpose": UNSUBSCRIBE_PURPOSE, "member_id": str(member_id)},
        expires_delta=timedelta(days=UNSUBSCRIBE_TOKEN_EXPIRE_DAYS),
    )


def build_unsubscribe_url(member_id: str) -> str:
    """수신거부 링크 URL"""
    token = create_unsubscribe_token(member_id)
    return f"{_account_base_url()}/auth/unsubscribe?token={token}"


def _recipient_lang(member: dict) -> str:
    """수신자 언어 결정 (없으면 ko)"""
    lang = member.get("preferred_language") or member.get("lang")
    if lang in ("ko", "en"):
        return lang
    return "ko"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_broadcast(subject: str, body_html: str, created_by: Optional[str]) -> dict:
    """배치 생성 + 수신자 스냅샷

    marketing_consent=TRUE 이고 email 이 있는 회원을 email_broadcast_recipients 에
    status=pending 으로 스냅샷한다. 발송 전 미리보기용 수신자 수를 함께 반환.

    Returns:
        {"id": <broadcast_id>, "recipient_count": <int>}
    """
    supabase = get_supabase_client()

    # 1) 배치 draft 생성
    broadcast_insert = (
        supabase.table("email_broadcasts")
        .insert({
            "subject": subject,
            "body_html": body_html,
            "created_by": str(created_by) if created_by else None,
            "status": "draft",
        })
        .execute()
    )
    if not broadcast_insert.data:
        raise RuntimeError("배치 생성에 실패했습니다")
    broadcast = broadcast_insert.data[0]
    broadcast_id = broadcast["id"]

    # 2) 마케팅 수신동의 회원 스냅샷 (email not null)
    members_result = (
        supabase.table("members")
        .select("id, email")
        .eq("marketing_consent", True)
        .not_.is_("email", "null")
        .execute()
    )
    members = members_result.data or []

    recipient_rows = [
        {
            "broadcast_id": broadcast_id,
            "member_id": m["id"],
            "email": m["email"],
            "status": "pending",
        }
        for m in members
        if m.get("email")
    ]

    if recipient_rows:
        # UNIQUE(broadcast_id, member_id) 로 중복 방지. 새 배치이므로 중복 없음.
        for i in range(0, len(recipient_rows), MAX_BULK_INSERT):
            supabase.table("email_broadcast_recipients").insert(
                recipient_rows[i:i + MAX_BULK_INSERT]
            ).execute()

    total = len(recipient_rows)

    # 3) total_recipients 갱신
    supabase.table("email_broadcasts").update(
        {"total_recipients": total}
    ).eq("id", broadcast_id).execute()

    return {"id": broadcast_id, "recipient_count": total}


def _member_marketing_consent(supabase, member_id: str) -> bool:
    """회원의 현재 marketing_consent 값을 재확인 (중간 수신거부 반영)"""
    try:
        res = (
            supabase.table("members")
            .select("marketing_consent")
            .eq("id", member_id)
            .single()
            .execute()
        )
        if res.data:
            return bool(res.data.get("marketing_consent"))
    except Exception as e:
        logger.warning(f"marketing_consent 재확인 실패 (member={member_id}): {e}")
    return False


async def send_broadcast(broadcast_id: str, limit: Optional[int] = None) -> dict:
    """pending 수신자에게 배치 발송

    - status=pending 인 recipient 만 처리 → 재실행 시 자동 재개 (중복발송 방지)
    - 각 건: (a) marketing_consent 재확인 → FALSE 면 skipped, (b) unsubscribe URL 생성,
      (c) send_broadcast_email, (d) 결과로 sent/failed 갱신
    - rate limit: 발송 사이 SEND_INTERVAL_SECONDS 대기, limit 으로 회당 발송량 제한
    - 발송 실패 시 해당 건 failed 기록 후 루프 안전 중단 (남은 pending 은 다음 실행에서 재개)

    Returns:
        {"broadcast_id", "sent", "failed", "skipped", "remaining", "status"}
    """
    supabase = get_supabase_client()

    # 배치 조회
    broadcast_res = (
        supabase.table("email_broadcasts")
        .select("*")
        .eq("id", broadcast_id)
        .single()
        .execute()
    )
    if not broadcast_res.data:
        raise ValueError(f"배치를 찾을 수 없습니다: {broadcast_id}")
    broadcast = broadcast_res.data

    subject = broadcast["subject"]
    body_html = broadcast["body_html"]

    # sending 상태로 전이
    supabase.table("email_broadcasts").update(
        {"status": "sending"}
    ).eq("id", broadcast_id).execute()

    # pending 수신자 조회 (재개 지점)
    query = (
        supabase.table("email_broadcast_recipients")
        .select("*")
        .eq("broadcast_id", broadcast_id)
        .eq("status", "pending")
        .order("id")
    )
    if limit is not None:
        query = query.limit(limit)
    pending_res = query.execute()
    pending = pending_res.data or []

    email_service = get_email_service()

    sent = 0
    failed = 0
    skipped = 0
    aborted = False

    for idx, recipient in enumerate(pending):
        member_id = recipient["member_id"]
        to_email = recipient["email"]

        # (a) marketing_consent 재확인 — 스냅샷 이후 수신거부 반영
        if not _member_marketing_consent(supabase, member_id):
            supabase.table("email_broadcast_recipients").update({
                "status": "skipped",
                "error": "marketing_consent=false",
            }).eq("id", recipient["id"]).execute()
            skipped += 1
            continue

        # 수신자 정보 (이름/언어)
        try:
            member_res = (
                supabase.table("members")
                .select("id, full_name, preferred_language, lang")
                .eq("id", member_id)
                .single()
                .execute()
            )
            member = member_res.data or {}
        except Exception:
            member = {}
        name = member.get("full_name") or ""
        lang = _recipient_lang(member)

        # (b) unsubscribe URL
        unsubscribe_url = build_unsubscribe_url(member_id)

        # rate limit: 첫 건 이후 대기
        if idx > 0:
            await asyncio.sleep(SEND_INTERVAL_SECONDS)

        # (c) 발송
        try:
            ok = await email_service.send_broadcast_email(
                to=to_email,
                name=name,
                subject=subject,
                body_html=body_html,
                unsubscribe_url=unsubscribe_url,
                lang=lang,
            )
        except Exception as e:
            ok = False
            logger.error(f"broadcast 발송 예외 (member={member_id}): {e}")

        # (d) 결과 반영
        if ok:
            supabase.table("email_broadcast_recipients").update({
                "status": "sent",
                "error": None,
                "sent_at": _now_iso(),
            }).eq("id", recipient["id"]).execute()
            sent += 1
        else:
            # 실패: 기록 후 배치 안전 중단 (rate limit/장애 시 quota 소진 방지)
            supabase.table("email_broadcast_recipients").update({
                "status": "failed",
                "error": "send failed",
            }).eq("id", recipient["id"]).execute()
            failed += 1
            aborted = True
            break

    # 배치 카운트 갱신 (누적)
    remaining = _count_recipients(supabase, broadcast_id, "pending")
    total_sent = _count_recipients(supabase, broadcast_id, "sent")
    total_failed = _count_recipients(supabase, broadcast_id, "failed")

    if aborted:
        new_status = "sending"  # 남은 pending 재개 가능 상태 유지
    elif remaining > 0:
        new_status = "sending"  # limit 으로 일부만 발송, 나머지 대기
    else:
        new_status = "sent"

    supabase.table("email_broadcasts").update({
        "status": new_status,
        "sent_count": total_sent,
        "failed_count": total_failed,
        "sent_at": _now_iso() if new_status == "sent" else broadcast.get("sent_at"),
    }).eq("id", broadcast_id).execute()

    return {
        "broadcast_id": broadcast_id,
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "remaining": remaining,
        "status": new_status,
    }


def _count_recipients(supabase, broadcast_id: str, status: str) -> int:
    """특정 status 수신자 수 조회"""
    try:
        res = (
            supabase.table("email_broadcast_recipients")
            .select("id", count="exact")
            .eq("broadcast_id", broadcast_id)
            .eq("status", status)
            .execute()
        )
        if res.count is not None:
            return res.count
        return len(res.data or [])
    except Exception as e:
        logger.warning(f"수신자 카운트 실패 ({status}): {e}")
        return 0


def process_unsubscribe(token: str) -> Optional[str]:
    """수신거부 처리

    토큰 decode + purpose 검증 → members.marketing_consent=FALSE +
    consent_logs(consent_type='marketing', agreed=false) 이력.

    Returns:
        member_id (성공) 또는 None (토큰 무효/만료/오류)
    """
    payload = decode_token(token)
    if not payload:
        return None
    if payload.get("purpose") != UNSUBSCRIBE_PURPOSE:
        return None
    member_id = payload.get("member_id")
    if not member_id:
        return None

    try:
        supabase = get_supabase_client()
        supabase.table("members").update(
            {"marketing_consent": False}
        ).eq("id", member_id).execute()

        try:
            supabase.table("consent_logs").insert({
                "member_id": member_id,
                "consent_type": "marketing",
                "agreed": False,
                "consent_version": "2.0",
            }).execute()
        except Exception as e:
            logger.warning(f"수신거부 consent_logs 기록 실패 (member={member_id}): {e}")

        return member_id
    except Exception as e:
        logger.error(f"수신거부 처리 실패 (member={member_id}): {e}")
        return None


def get_broadcast(broadcast_id: str) -> Optional[dict]:
    """배치 상태/카운트 조회"""
    supabase = get_supabase_client()
    try:
        res = (
            supabase.table("email_broadcasts")
            .select("*")
            .eq("id", broadcast_id)
            .single()
            .execute()
        )
        return res.data
    except Exception as e:
        logger.warning(f"배치 조회 실패 ({broadcast_id}): {e}")
        return None
