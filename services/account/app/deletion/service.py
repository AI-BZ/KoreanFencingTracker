"""
탈퇴 회원 개인정보 파기 실행기.

약속된 내용 (이 모듈이 이행하는 대상):
  - 이용약관 제13조 2항: "탈퇴 요청 시 즉시 처리되며, 개인정보는 30일간
    보관 후 파기됩니다. 단, 관련 법령에 따른 보존 의무가 있는 경우 해당
    기간 동안 보관합니다."
  - 개인정보처리방침 제6조: 보유 기간 만료 시 지체 없이 파기하되,
    법령상 보존이 필요한 정보는 분리 보관.
  - templates/auth/profile.html 탈퇴 안내:
      · "이름·이메일·연락처 등 회원 정보와 로그인 연동이 파기됩니다"
      · "관련 법령상 보존 의무가 있는 기록은 해당 기간 동안 별도로 보관됩니다"
      · "대회 기록은 ... 삭제되지 않고, 계정과의 연결만 해제됩니다"

파기 = 하드 삭제(row DELETE)가 아니라 **익명화 + 자식 레코드 삭제**다.
근거는 022_account_deletion_purge.sql 주석 참조 (요약):
  1) consent_logs FK 가 ON DELETE CASCADE 라서 members 를 하드 삭제하면
     "동의 기록: 회원 자격 유지 기간 + 5년"(방침 제2조) 보존 약속이 깨진다.
  2) admin_audit_logs.admin_id 등 ON DELETE 절이 없는 FK 가 다수라
     하드 삭제는 FK 위반으로 실패한다.
  3) 결제 정보는 전자상거래법상 5년 보존 대상(방침 제2조)이며
     stripe_* / payment_events 는 members 를 참조한다.

안전장치:
  - dry_run 기본 True (읽기 전용, 감사 로그도 쓰지 않는다)
  - 배치 상한 (limit)
  - 회원별 재확인 (취소 경합 방지)
  - anonymized_at 가드로 멱등
  - 필수 테이블(oauth_connections) 삭제 실패 시 해당 회원 익명화 중단
    → 재로그인 가능한 상태로 셸 계정이 남는 것을 방지
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from loguru import logger

# 익명화된 계정 이메일 도메인. RFC 2606 이 예약한 .invalid 를 쓴다 (실존 불가).
ANONYMIZED_EMAIL_DOMAIN = "deleted.invalid"

# 익명화 후 남는 표시용 이름 (members.full_name 은 NOT NULL 이라 비울 수 없다)
ANONYMIZED_FULL_NAME = "탈퇴한 회원"


@dataclass(frozen=True)
class ChildTable:
    """파기 시 행 자체를 삭제하는 자식 테이블."""

    table: str
    column: str
    #: True 면 삭제 실패 시 해당 회원의 익명화를 중단한다(재시도로 넘김).
    required: bool = False
    #: 삭제된 행의 id 를 모아 verification_ai_reports.target_id 청소에 사용한다.
    collect_ids_for_ai_reports: bool = False
    note: str = ""


# ---------------------------------------------------------------------------
# 파기 대상 (행 삭제)
# ---------------------------------------------------------------------------
CHILD_TABLES: tuple[ChildTable, ...] = (
    # 로그인 수단 — 가장 먼저, 그리고 반드시 성공해야 한다.
    # 남아 있으면 익명화된 셸 계정에 OAuth 로 다시 로그인할 수 있다.
    ChildTable("oauth_connections", "member_id", required=True,
               note="provider 이메일/이름 + 암호화 토큰"),
    # 알림 식별자 (FCM 토큰 등)
    ChildTable("app_push_subscriptions", "member_id", note="FCM 토큰/카카오 사용자 ID"),
    ChildTable("app_notification_preferences", "member_id"),
    ChildTable("app_notification_log", "member_id", note="발송 이력(본문 포함 가능)"),
    ChildTable("notifications", "recipient_id", note="수신 알림 본문"),
    # 인증 제출물 — 사진 URL, 추출된 이름/소속 등 PII 덩어리
    ChildTable("verifications", "member_id", collect_ids_for_ai_reports=True),
    ChildTable("player_claims", "member_id", collect_ids_for_ai_reports=True),
    ChildTable("organization_claims", "member_id", collect_ids_for_ai_reports=True),
    ChildTable("parent_claims", "member_id", collect_ids_for_ai_reports=True),
    # 소속/구독 연결
    ChildTable("member_organizations", "member_id", note="소속 이력(약관 제9조 5항)"),
    ChildTable("member_services", "member_id"),
    # 권한 회수 — 익명화된 계정이 관리자 배정을 유지해서는 안 된다.
    ChildTable("admin_service_assignments", "member_id"),
)

# ---------------------------------------------------------------------------
# 보존 대상 (건드리지 않음) — 문서화 목적으로 코드에 남긴다.
# ---------------------------------------------------------------------------
RETAINED_TABLES: dict[str, str] = {
    "consent_logs":
        "개인정보처리방침 제2조 — 동의 기록: 회원 자격 유지 기간 + 5년 (입증 목적)",
    "stripe_customers":
        "개인정보처리방침 제2조 — 결제 정보: 거래 완료 후 5년 (전자상거래법)",
    "stripe_subscriptions":
        "개인정보처리방침 제2조 — 결제 정보: 거래 완료 후 5년 (전자상거래법)",
    "payment_events":
        "개인정보처리방침 제2조 — 결제 정보: 거래 완료 후 5년 (전자상거래법)",
    "admin_audit_logs":
        "관리자 행위 감사 로그(append-only). 대상 회원이 관리자였던 경우에도 보존.",
    "admin_notes":
        "관리자 작성 기록. 삭제 정책은 account 서비스 단독으로 결정하지 않는다.",
    "attendance / lessons / lesson_participants / fees / competition_*":
        "club 서비스 소유 운영·정산 기록. 삭제 여부는 club 워크트리 정책 결정 사항이며 "
        "account 파기 잡이 임의로 지우지 않는다(회원 연결만 남고 PII 는 members 에서 제거됨).",
    "rankings / matches / events / players":
        "대한펜싱협회 공개 데이터. 약관 제8조 5항 및 방침 제11조에 따라 삭제 대상이 아니며 "
        "members.player_id 연결만 해제한다.",
}

# 폴리모픽 참조(FK 없음)라 위 자식 행 삭제 후 별도로 청소해야 한다.
AI_REPORT_TABLE = "verification_ai_reports"


def build_anonymized_payload(member_id: str, now: datetime) -> dict[str, Any]:
    """members 행에서 개인 식별 정보를 제거하는 UPDATE 페이로드.

    - full_name / email 은 NOT NULL 이라 비울 수 없어 대체값을 넣는다.
    - email 은 member_id 로부터 결정론적으로 생성되므로 재실행해도 동일하고
      UNIQUE 제약과 충돌하지 않는다.
    - birth_date 를 NULL 로 만드는 것은 PII 제거 목적이자,
      003 의 enforce_minor_guardian 트리거(14세 미만 + guardian NULL 이면 예외)
      를 우회하기 위해서도 필요하다. guardian_member_id 를 NULL 로 만들기 때문.
    """
    return {
        # 식별 정보
        "full_name": ANONYMIZED_FULL_NAME,
        "display_name": None,
        "nickname": None,
        "email": f"deleted-{member_id}@{ANONYMIZED_EMAIL_DOMAIN}",
        "phone": None,
        "phone_country_code": None,
        "contact_phone": None,
        "birth_date": None,
        "notes": None,
        "rejection_reason": None,
        # 로그인 수단 / 자격증명
        "password_hash": None,
        "supabase_auth_id": None,
        "kakao_id": None,
        "kakao_nickname": None,
        "kakao_profile_image": None,
        "email_verified": False,
        "email_verified_at": None,
        "email_verification_token": None,
        "email_verification_expires_at": None,
        # 연결 해제 (대회 기록 자체는 보존 — 약관 제8조 5항)
        "player_id": None,
        "organization_id": None,
        "guardian_member_id": None,
        "data_linked_at": None,
        # 권한 회수
        "admin_role": None,
        "club_role": None,
        # 인증 상태 초기화
        "verification_status": "expired",
        "verification_tier": 0,
        "verified_at": None,
        # 동의 철회
        "privacy_public": False,
        "marketing_consent": False,
        "promotional_consent": False,
        "optional_privacy_consent": False,
        "overseas_transfer_consent": False,
        "interested_services": [],
        # 파기 완료 표시 (멱등성 가드)
        "anonymized_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------
@dataclass
class MemberPurgeResult:
    member_id: str
    outcome: str                      # anonymized | skipped | failed
    skip_reason: str | None = None    # cancelled | rescheduled | already_anonymized | missing
    deleted_counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None

    def as_audit_row(self, member: dict[str, Any], now: datetime, actor: str) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "deletion_requested_at": member.get("deletion_requested_at"),
            "deletion_scheduled_at": member.get("deletion_scheduled_at"),
            "executed_at": now.isoformat(),
            "actor": actor,
            "outcome": self.outcome,
            "skip_reason": self.skip_reason,
            "deleted_counts": self.deleted_counts,
            "error": self.error,
        }


@dataclass
class PurgeReport:
    dry_run: bool
    due: int = 0
    anonymized: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[MemberPurgeResult] = field(default_factory=list)

    def summary(self) -> str:
        mode = "DRY-RUN" if self.dry_run else "EXECUTE"
        return (
            f"[{mode}] 파기 대상 {self.due}건 · 익명화 {self.anonymized} · "
            f"건너뜀 {self.skipped} · 실패 {self.failed}"
        )


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------
_MEMBER_FIELDS = (
    "id, email, deletion_requested_at, deletion_scheduled_at, anonymized_at"
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    """ISO 문자열/ datetime 을 aware UTC datetime 으로. 실패하면 None.

    주의: /account/me/delete-request 는 datetime.utcnow().isoformat() 으로
    tz 없는 문자열을 저장한다. 이런 naive 값은 UTC 로 간주한다.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _rows(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    return list(data) if data else []


def _is_missing_table(exc: Exception) -> bool:
    """PostgREST 가 테이블 없음을 알릴 때(PGRST205 / 42P01) True."""
    text = str(exc)
    return "PGRST205" in text or "42P01" in text or "schema cache" in text


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------
def find_due_members(
    supabase: Any,
    *,
    now: datetime | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """파기 예정일이 지났고 아직 파기되지 않은 회원 목록 (오래된 순, 최대 limit 건)."""
    now = now or _utcnow()
    response = (
        supabase.table("members")
        .select(_MEMBER_FIELDS)
        .not_.is_("deletion_scheduled_at", "null")
        .lte("deletion_scheduled_at", now.isoformat())
        .is_("anonymized_at", "null")
        .order("deletion_scheduled_at")
        .limit(limit)
        .execute()
    )
    return _rows(response)


def _recheck(supabase: Any, member_id: str, now: datetime) -> tuple[dict[str, Any] | None, str | None]:
    """파기 직전 재확인. (fresh_row, skip_reason) 을 돌려준다.

    탈퇴 취소(POST /account/me/cancel-deletion)는 deletion_scheduled_at 을
    NULL 로 만든다. 조회 시점과 실행 시점 사이에 취소했을 수 있으므로
    회원 단위로 다시 읽어 확인한다.
    """
    response = (
        supabase.table("members")
        .select(_MEMBER_FIELDS)
        .eq("id", member_id)
        .execute()
    )
    rows = _rows(response)
    if not rows:
        return None, "missing"

    fresh = rows[0]
    if fresh.get("anonymized_at"):
        return fresh, "already_anonymized"
    if not fresh.get("deletion_scheduled_at"):
        return fresh, "cancelled"

    scheduled = _parse_ts(fresh.get("deletion_scheduled_at"))
    if scheduled is None:
        return fresh, "cancelled"
    if scheduled > now:
        return fresh, "rescheduled"
    return fresh, None


# ---------------------------------------------------------------------------
# 자식 레코드 삭제
# ---------------------------------------------------------------------------
def _count_rows(supabase: Any, table: str, column: str, value: str) -> int:
    response = (
        supabase.table(table)
        .select("id", count="exact")
        .eq(column, value)
        .limit(1)
        .execute()
    )
    count = getattr(response, "count", None)
    return int(count) if count is not None else len(_rows(response))


def _select_ids(supabase: Any, table: str, column: str, value: str) -> list[str]:
    response = supabase.table(table).select("id").eq(column, value).execute()
    return [str(row["id"]) for row in _rows(response) if row.get("id") is not None]


def _delete_rows(supabase: Any, table: str, column: str, value: str) -> int:
    response = supabase.table(table).delete().eq(column, value).execute()
    return len(_rows(response))


def _purge_child_tables(
    supabase: Any,
    member_id: str,
    *,
    dry_run: bool,
) -> tuple[dict[str, int], list[str], str | None]:
    """자식 테이블 정리.

    반환: (테이블별 건수, ai_report 로 청소할 target_id 목록, 치명적 오류 메시지)
    """
    counts: dict[str, int] = {}
    ai_target_ids: list[str] = []

    for spec in CHILD_TABLES:
        try:
            if spec.collect_ids_for_ai_reports:
                ids = _select_ids(supabase, spec.table, spec.column, member_id)
                ai_target_ids.extend(ids)
                if dry_run:
                    count = len(ids)
                else:
                    count = _delete_rows(supabase, spec.table, spec.column, member_id)
            elif dry_run:
                count = _count_rows(supabase, spec.table, spec.column, member_id)
            else:
                count = _delete_rows(supabase, spec.table, spec.column, member_id)
        except Exception as exc:  # noqa: BLE001 - 테이블별로 격리해서 처리
            if _is_missing_table(exc) and not spec.required:
                logger.debug(f"[deletion] {spec.table} 테이블 없음 - 건너뜀")
                continue
            message = f"{spec.table} 처리 실패: {exc}"
            if spec.required:
                # 로그인 수단이 남으면 익명화된 셸 계정에 재로그인이 가능해진다.
                return counts, ai_target_ids, message
            logger.warning(f"[deletion] member={member_id} {message}")
            counts[f"{spec.table}:error"] = -1
            continue

        if count:
            counts[spec.table] = count

    return counts, ai_target_ids, None


def _purge_ai_reports(
    supabase: Any,
    target_ids: Iterable[str],
    *,
    dry_run: bool,
) -> int:
    """verification_ai_reports 는 FK 없는 폴리모픽 참조라 별도로 지운다.

    reasoning / raw_response 에 이름·소속 등 PII 가 들어 있다.
    """
    ids = [tid for tid in target_ids if tid]
    if not ids:
        return 0
    try:
        if dry_run:
            response = (
                supabase.table(AI_REPORT_TABLE)
                .select("id", count="exact")
                .in_("target_id", ids)
                .limit(1)
                .execute()
            )
            count = getattr(response, "count", None)
            return int(count) if count is not None else len(_rows(response))
        response = supabase.table(AI_REPORT_TABLE).delete().in_("target_id", ids).execute()
        return len(_rows(response))
    except Exception as exc:  # noqa: BLE001
        if _is_missing_table(exc):
            return 0
        logger.warning(f"[deletion] {AI_REPORT_TABLE} 정리 실패: {exc}")
        return 0


def _purge_pending_registrations(
    supabase: Any,
    email: str | None,
    *,
    dry_run: bool,
) -> int:
    """미완료 가입 토큰(provider_email 보유)도 함께 정리. member_id 컬럼이 없어 이메일로 매칭."""
    if not email or email.endswith(f"@{ANONYMIZED_EMAIL_DOMAIN}"):
        return 0
    try:
        if dry_run:
            response = (
                supabase.table("pending_registrations")
                .select("token", count="exact")
                .eq("provider_email", email)
                .limit(1)
                .execute()
            )
            count = getattr(response, "count", None)
            return int(count) if count is not None else len(_rows(response))
        response = (
            supabase.table("pending_registrations")
            .delete()
            .eq("provider_email", email)
            .execute()
        )
        return len(_rows(response))
    except Exception as exc:  # noqa: BLE001
        if _is_missing_table(exc):
            return 0
        logger.warning(f"[deletion] pending_registrations 정리 실패: {exc}")
        return 0


def _detach_dependents(supabase: Any, member_id: str, *, dry_run: bool) -> int:
    """이 회원을 보호자로 지정한 다른 회원의 guardian_member_id 를 해제."""
    try:
        if dry_run:
            return _count_rows(supabase, "members", "guardian_member_id", member_id)
        response = (
            supabase.table("members")
            .update({"guardian_member_id": None})
            .eq("guardian_member_id", member_id)
            .execute()
        )
        return len(_rows(response))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[deletion] guardian 연결 해제 실패 (member={member_id}): {exc}")
        return 0


# ---------------------------------------------------------------------------
# 회원 단위 파기
# ---------------------------------------------------------------------------
def purge_member(
    supabase: Any,
    member: dict[str, Any],
    *,
    now: datetime | None = None,
    dry_run: bool = True,
) -> MemberPurgeResult:
    """회원 1명 파기. 멱등하며, 취소 경합을 실행 직전에 재확인한다."""
    now = now or _utcnow()
    member_id = str(member["id"])

    fresh, skip_reason = _recheck(supabase, member_id, now)
    if skip_reason:
        logger.info(f"[deletion] member={member_id} 건너뜀 ({skip_reason})")
        return MemberPurgeResult(member_id=member_id, outcome="skipped", skip_reason=skip_reason)

    assert fresh is not None  # skip_reason 이 None 이면 fresh 는 존재한다
    email = fresh.get("email")

    counts, ai_target_ids, fatal = _purge_child_tables(supabase, member_id, dry_run=dry_run)
    if fatal:
        logger.error(f"[deletion] member={member_id} 파기 중단: {fatal}")
        return MemberPurgeResult(
            member_id=member_id, outcome="failed", deleted_counts=counts, error=fatal
        )

    ai_count = _purge_ai_reports(supabase, ai_target_ids, dry_run=dry_run)
    if ai_count:
        counts[AI_REPORT_TABLE] = ai_count

    pending_count = _purge_pending_registrations(supabase, email, dry_run=dry_run)
    if pending_count:
        counts["pending_registrations"] = pending_count

    detached = _detach_dependents(supabase, member_id, dry_run=dry_run)
    if detached:
        counts["members:guardian_detached"] = detached

    if dry_run:
        logger.info(
            f"[deletion][DRY-RUN] member={member_id} 익명화 예정 · 삭제 예정 {counts or '없음'}"
        )
        return MemberPurgeResult(
            member_id=member_id, outcome="anonymized", deleted_counts=counts
        )

    try:
        payload = build_anonymized_payload(member_id, now)
        supabase.table("members").update(payload).eq("id", member_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[deletion] member={member_id} 익명화 실패: {exc}")
        return MemberPurgeResult(
            member_id=member_id,
            outcome="failed",
            deleted_counts=counts,
            error=f"members 익명화 실패: {exc}",
        )

    logger.info(f"[deletion] member={member_id} 익명화 완료 · 삭제 {counts or '없음'}")
    return MemberPurgeResult(member_id=member_id, outcome="anonymized", deleted_counts=counts)


def _write_audit(
    supabase: Any,
    result: MemberPurgeResult,
    member: dict[str, Any],
    now: datetime,
    actor: str,
) -> None:
    try:
        supabase.table("member_deletion_audit").insert(
            result.as_audit_row(member, now, actor)
        ).execute()
    except Exception as exc:  # noqa: BLE001
        # 파기는 이미 끝났다. 감사 로그 유실은 즉시 알아야 할 사고다.
        logger.critical(
            f"[deletion] 감사 로그 기록 실패 (member={result.member_id}, "
            f"outcome={result.outcome}): {exc}"
        )


# ---------------------------------------------------------------------------
# 배치 실행
# ---------------------------------------------------------------------------
def purge_due_members(
    supabase: Any,
    *,
    now: datetime | None = None,
    limit: int = 50,
    dry_run: bool = True,
    actor: str = "scheduler",
) -> PurgeReport:
    """파기 예정일이 지난 회원을 최대 limit 건 처리한다.

    dry_run=True 면 어떤 쓰기도 하지 않는다(감사 로그도 남기지 않는다).
    """
    now = now or _utcnow()
    report = PurgeReport(dry_run=dry_run)

    due = find_due_members(supabase, now=now, limit=limit)
    report.due = len(due)
    if not due:
        logger.info(f"[deletion] {report.summary()}")
        return report

    logger.info(
        f"[deletion] 파기 대상 {len(due)}건 발견 "
        f"(mode={'DRY-RUN' if dry_run else 'EXECUTE'}, limit={limit})"
    )

    for member in due:
        result = purge_member(supabase, member, now=now, dry_run=dry_run)
        report.results.append(result)

        if result.outcome == "anonymized":
            report.anonymized += 1
        elif result.outcome == "skipped":
            report.skipped += 1
        else:
            report.failed += 1

        if not dry_run:
            _write_audit(supabase, result, member, now, actor)

    logger.info(f"[deletion] {report.summary()}")
    return report


# ---------------------------------------------------------------------------
# 수동 실행 (기본은 드라이런)
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="탈퇴 회원 개인정보 파기 (기본: 드라이런, 읽기 전용)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제로 파기한다. 지정하지 않으면 무엇이 지워질지 출력만 한다.",
    )
    parser.add_argument("--limit", type=int, default=50, help="한 번에 처리할 최대 건수")
    args = parser.parse_args(argv)

    from shared_core.db.client import get_supabase_client

    report = purge_due_members(
        get_supabase_client(),
        limit=args.limit,
        dry_run=not args.execute,
        actor="manual",
    )
    print(report.summary())
    for result in report.results:
        detail = result.skip_reason or result.error or result.deleted_counts or "-"
        print(f"  {result.member_id}  {result.outcome:<11} {detail}")
    return 1 if report.failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
