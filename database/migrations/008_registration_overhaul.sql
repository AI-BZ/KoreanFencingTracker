-- 008_registration_overhaul.sql
-- 회원가입 시스템 전면 개편: member_type 확장, 이메일 인증, 국제 전화번호, GDPR 동의, 계정 삭제
-- Created: 2026-02-23

-- ============================================
-- 1. member_type 확장 (club_director, school_director 추가)
-- ============================================
ALTER TABLE members DROP CONSTRAINT IF EXISTS members_member_type_check;
ALTER TABLE members ADD CONSTRAINT members_member_type_check
    CHECK (member_type IN (
        'player', 'player_parent', 'club_coach', 'club_director',
        'school_coach', 'school_director', 'general'
    ));

-- ============================================
-- 2. 이메일 인증 컬럼
-- ============================================
ALTER TABLE members ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE members ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;
ALTER TABLE members ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(128);
ALTER TABLE members ADD COLUMN IF NOT EXISTS email_verification_expires_at TIMESTAMPTZ;

-- ============================================
-- 3. 전화 국가코드
-- ============================================
ALTER TABLE members ADD COLUMN IF NOT EXISTS phone_country_code VARCHAR(5) DEFAULT '+82';

-- ============================================
-- 4. 동의 추적 (GDPR)
-- ============================================
ALTER TABLE members ADD COLUMN IF NOT EXISTS terms_agreed_at TIMESTAMPTZ;
ALTER TABLE members ADD COLUMN IF NOT EXISTS privacy_agreed_at TIMESTAMPTZ;
ALTER TABLE members ADD COLUMN IF NOT EXISTS consent_version VARCHAR(10) DEFAULT '1.0';

-- ============================================
-- 5. 계정 삭제 지원
-- ============================================
ALTER TABLE members ADD COLUMN IF NOT EXISTS deletion_requested_at TIMESTAMPTZ;
ALTER TABLE members ADD COLUMN IF NOT EXISTS deletion_scheduled_at TIMESTAMPTZ;

-- ============================================
-- 6. 인덱스
-- ============================================
CREATE INDEX IF NOT EXISTS idx_members_email_verification_token
    ON members(email_verification_token)
    WHERE email_verification_token IS NOT NULL;

-- ============================================
-- 7. 기존 OAuth 회원 백필 (이메일이 있는 OAuth 연결 = 이메일 인증 완료로 간주)
-- ============================================
UPDATE members SET email_verified = TRUE
WHERE id IN (
    SELECT DISTINCT member_id
    FROM oauth_connections
    WHERE provider_email IS NOT NULL
);
