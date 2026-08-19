-- Migration 022: Account Deletion Purge (탈퇴 회원 개인정보 파기 실행)
-- Created: 2026-08-19
--
-- 배경
--   008_registration_overhaul.sql 이 members.deletion_requested_at /
--   deletion_scheduled_at 컬럼을 추가했으나, 이 값을 읽어 실제로 파기를
--   수행하는 코드가 없어 이용약관 제13조 2항("30일간 보관 후 파기")과
--   개인정보처리방침 제6조(파기 절차)가 이행되지 않고 있었다.
--
--   본 마이그레이션은 파기 잡(services/account/app/deletion/)이 필요로 하는
--   두 가지를 추가한다:
--     1) members.anonymized_at  — 멱등성 가드 (이미 파기된 회원 재처리 방지)
--     2) member_deletion_audit  — 파기 감사 로그 (PII 저장 금지)
--
-- 파기 방식: 하드 삭제(row DELETE)가 아니라 "익명화 + 자식 레코드 삭제".
--   근거:
--     - 개인정보처리방침 제2조: 동의 기록은 "회원 자격 유지 기간 + 5년",
--       결제 정보는 "거래 완료 후 5년(전자상거래법)" 보존해야 한다.
--       consent_logs 의 FK 는 ON DELETE CASCADE 이므로 members 행을 하드
--       삭제하면 이 동의 기록이 함께 소멸되어 방침을 위반한다.
--     - admin_audit_logs.admin_id / admin_notes.admin_id / lessons.coach_id 등은
--       ON DELETE 절이 없어(NO ACTION) 하드 삭제 시 FK 위반으로 실패한다.
--     - 프로필 화면(templates/auth/profile.html) 이 이미 사용자에게
--       "대회 기록은 삭제되지 않고 계정과의 연결만 해제됩니다" 라고 고지했다.

-- ============================================================
-- 1. members.anonymized_at : 파기 완료 시각 (멱등성 가드)
-- ============================================================
ALTER TABLE members ADD COLUMN IF NOT EXISTS anonymized_at TIMESTAMPTZ;

COMMENT ON COLUMN members.anonymized_at IS
    '개인정보 파기(익명화) 완료 시각. NOT NULL 이면 이미 파기된 셸 계정이며 재처리하지 않는다.';

-- 파기 대상 조회용 부분 인덱스 (deletion_scheduled_at <= now() AND anonymized_at IS NULL)
CREATE INDEX IF NOT EXISTS idx_members_deletion_due
    ON members(deletion_scheduled_at)
    WHERE deletion_scheduled_at IS NOT NULL AND anonymized_at IS NULL;

-- ============================================================
-- 2. member_deletion_audit : 파기 감사 로그 (append-only)
-- ============================================================
-- admin_audit_logs 를 재사용하지 않는 이유:
--   admin_audit_logs.admin_id 는 NOT NULL REFERENCES members(id) 이다.
--   스케줄러가 자동 실행하는 파기에는 행위 주체인 관리자가 존재하지 않고,
--   파기 대상 회원 본인을 admin_id 로 넣는 것은 감사 기록으로서 부적절하다.
CREATE TABLE IF NOT EXISTS member_deletion_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- FK 를 걸지 않는다: 감사 로그는 대상 행의 생명주기와 무관하게 남아야 한다.
    member_id UUID NOT NULL,

    deletion_requested_at TIMESTAMPTZ,
    deletion_scheduled_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    actor VARCHAR(30) NOT NULL DEFAULT 'scheduler',   -- scheduler | manual | test
    outcome VARCHAR(20) NOT NULL CHECK (outcome IN ('anonymized', 'skipped', 'failed')),
    skip_reason VARCHAR(40),                          -- cancelled | rescheduled | already_anonymized | missing

    -- {"oauth_connections": 2, "notifications": 5, ...} 형태의 건수만 저장한다.
    deleted_counts JSONB NOT NULL DEFAULT '{}',
    error TEXT
);

COMMENT ON TABLE member_deletion_audit IS
    '탈퇴 회원 개인정보 파기 감사 로그. 개인정보(이름/이메일/연락처)를 저장하지 않는다 - member_id 와 건수만 기록.';

CREATE INDEX IF NOT EXISTS idx_member_deletion_audit_member
    ON member_deletion_audit(member_id);
CREATE INDEX IF NOT EXISTS idx_member_deletion_audit_executed
    ON member_deletion_audit(executed_at DESC);
CREATE INDEX IF NOT EXISTS idx_member_deletion_audit_outcome
    ON member_deletion_audit(outcome);
