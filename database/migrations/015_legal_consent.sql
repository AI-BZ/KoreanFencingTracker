-- Migration 015: Legal Documents & Consent System
-- PRD: PRD_legal_documents.md
-- Date: 2026-02-25

-- 1. consent_logs 테이블
CREATE TABLE IF NOT EXISTS consent_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    consent_type VARCHAR(30) NOT NULL CHECK (consent_type IN (
        'terms_of_service',     -- 이용약관
        'required_privacy',     -- 필수 개인정보 수집/이용
        'overseas_transfer',    -- 국외이전
        'optional_privacy',     -- 선택 개인정보 수집/이용
        'marketing',            -- 마케팅 수신
        'promotional',          -- 홍보용 SNS
        'player_claim',         -- 선수 연결 동의
        'guardian_consent',     -- 보호자 동의
        'minor_claim_consent'   -- 미성년 선수 연결 보호자 동의
    )),
    agreed BOOLEAN NOT NULL,
    consent_version VARCHAR(10) NOT NULL DEFAULT '1.0',
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_consent_logs_member ON consent_logs(member_id);
CREATE INDEX IF NOT EXISTS idx_consent_logs_type ON consent_logs(consent_type, agreed);

-- 2. legal_documents 테이블 (버전 관리)
CREATE TABLE IF NOT EXISTS legal_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_type VARCHAR(20) NOT NULL CHECK (doc_type IN (
        'terms',      -- 이용약관
        'privacy'     -- 개인정보처리방침
    )),
    version VARCHAR(10) NOT NULL,
    content_ko TEXT NOT NULL,
    content_en TEXT,
    effective_date DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by UUID REFERENCES members(id),
    UNIQUE(doc_type, version)
);

-- 3. members 테이블에 overseas_consent 컬럼 추가
ALTER TABLE members ADD COLUMN IF NOT EXISTS overseas_transfer_consent BOOLEAN DEFAULT FALSE;
ALTER TABLE members ADD COLUMN IF NOT EXISTS optional_privacy_consent BOOLEAN DEFAULT FALSE;
