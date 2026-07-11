-- Migration 013: Verification System Tables
-- 회원 유형별 인증 및 선수 데이터 매칭
-- Created: 2026-02-25

-- ============================================================
-- 1. verifications 테이블 확장 (기존 테이블에 컬럼 추가)
-- ============================================================
-- 기존 verifications 테이블에 ai_result, reviewer 관련 컬럼 추가
ALTER TABLE verifications ADD COLUMN IF NOT EXISTS ai_result JSONB;
ALTER TABLE verifications ADD COLUMN IF NOT EXISTS ai_confidence DECIMAL(3,2);
ALTER TABLE verifications ADD COLUMN IF NOT EXISTS reviewer_id UUID REFERENCES members(id);
ALTER TABLE verifications ADD COLUMN IF NOT EXISTS reviewer_notes TEXT;
ALTER TABLE verifications ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE verifications ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

-- ============================================================
-- 2. player_claims: 선수 데이터 Claim
-- ============================================================
CREATE TABLE IF NOT EXISTS player_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    player_id BIGINT NOT NULL REFERENCES players(id),

    -- 매칭 점수 및 근거
    confidence_score DECIMAL(3,2),
    evidence JSONB DEFAULT '{}',

    -- 처리 상태
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'approved', 'rejected', 'expired', 'superseded'
    )),
    reviewer_id UUID REFERENCES members(id),
    reviewer_notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,

    UNIQUE(member_id, player_id)
);

-- 하나의 player에 대해 하나의 approved claim만 허용
CREATE UNIQUE INDEX IF NOT EXISTS idx_player_claims_approved_player
    ON player_claims(player_id) WHERE status = 'approved';

-- 하나의 member는 하나의 approved claim만 허용
CREATE UNIQUE INDEX IF NOT EXISTS idx_player_claims_approved_member
    ON player_claims(member_id) WHERE status = 'approved';

CREATE INDEX IF NOT EXISTS idx_player_claims_status ON player_claims(status);
CREATE INDEX IF NOT EXISTS idx_player_claims_member ON player_claims(member_id);

-- ============================================================
-- 3. organization_claims: 조직 소유권 인증
-- ============================================================
CREATE TABLE IF NOT EXISTS organization_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),

    claim_type VARCHAR(20) NOT NULL CHECK (claim_type IN (
        'director', 'head_coach', 'representative'
    )),

    -- 사업자등록증 3-Layer 자동 검증 결과
    brn_number VARCHAR(12),
    brn_business_name VARCHAR(100),
    brn_representative_name VARCHAR(50),
    brn_opening_date VARCHAR(8),
    brn_ocr_confidence DECIMAL(3,2),
    brn_checkdigit_valid BOOLEAN,
    brn_nts_valid BOOLEAN,
    brn_nts_status VARCHAR(20),
    brn_auto_verified BOOLEAN DEFAULT false,

    -- 문서 업로드
    document_url TEXT,

    -- 처리 상태
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'auto_verified', 'approved', 'rejected', 'expired'
    )),
    reviewer_id UUID REFERENCES members(id),
    reviewer_notes TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,

    UNIQUE(member_id, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_org_claims_status ON organization_claims(status);
CREATE INDEX IF NOT EXISTS idx_org_claims_org ON organization_claims(organization_id);

-- ============================================================
-- 4. member_organizations: 다중 조직 소속
-- ============================================================
CREATE TABLE IF NOT EXISTS member_organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    organization_id BIGINT NOT NULL REFERENCES organizations(id),
    role VARCHAR(20) NOT NULL CHECK (role IN (
        'owner', 'head_coach', 'coach', 'assistant',
        'student', 'parent', 'staff'
    )),
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN (
        'active', 'inactive', 'pending_approval', 'rejected'
    )),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(member_id, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_member_orgs_org ON member_organizations(organization_id);
CREATE INDEX IF NOT EXISTS idx_member_orgs_member ON member_organizations(member_id);

-- ============================================================
-- 5. members 테이블 확장 (verification_tier 추가)
-- ============================================================
ALTER TABLE members ADD COLUMN IF NOT EXISTS verification_tier SMALLINT DEFAULT 0
    CHECK (verification_tier BETWEEN 0 AND 4);
ALTER TABLE members ADD COLUMN IF NOT EXISTS data_linked_at TIMESTAMPTZ;
