-- 020_email_verification_code.sql
-- 이메일 인증코드 로그인을 위한 pending_registrations 컬럼 추가
-- Created: 2026-05-26

ALTER TABLE pending_registrations
ADD COLUMN IF NOT EXISTS verification_code VARCHAR(6),
ADD COLUMN IF NOT EXISTS code_attempts INT DEFAULT 0;

-- 이메일 인증코드용 조회 인덱스
CREATE INDEX IF NOT EXISTS idx_pending_registrations_email
    ON pending_registrations(provider_email)
    WHERE provider = 'email';
