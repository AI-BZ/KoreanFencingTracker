-- 009_pending_registrations_table.sql
-- OAuth 회원가입 대기 데이터를 DB에 저장 (서버 재시작에도 유지)
-- Created: 2026-02-23

CREATE TABLE IF NOT EXISTS pending_registrations (
    token VARCHAR(64) PRIMARY KEY,
    provider VARCHAR(20) NOT NULL,
    provider_user_id TEXT NOT NULL,
    provider_email TEXT,
    provider_name TEXT,
    access_token TEXT,
    refresh_token TEXT,
    promotional BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '30 minutes')
);

-- 만료된 레코드 자동 정리용 인덱스
CREATE INDEX IF NOT EXISTS idx_pending_registrations_expires_at
    ON pending_registrations(expires_at);
