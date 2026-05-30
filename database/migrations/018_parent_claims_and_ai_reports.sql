-- 018: 학부모 Claim 및 AI 인증 리포트 시스템
-- parent_claims: 학부모-선수 관계 인증 요청
-- verification_ai_reports: 통합 AI 추론 리포트
-- notifications 확장: link_url, metadata 컬럼

-- =============================================
-- 1) parent_claims 테이블
-- =============================================
CREATE TABLE IF NOT EXISTS parent_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    child_name VARCHAR(100) NOT NULL,
    child_birth_year INT,
    child_team_name VARCHAR(200),
    child_gender VARCHAR(10),
    relationship_type VARCHAR(20) NOT NULL,  -- father/mother/legal_guardian/grandparent/other
    matched_player_id BIGINT REFERENCES players(id),
    ai_confidence DECIMAL(3,2),
    ai_report JSONB DEFAULT '{}',
    ai_processed_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending/ai_reviewed/approved/rejected
    reviewer_id UUID REFERENCES members(id),
    reviewer_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    UNIQUE(member_id, child_name, child_birth_year)
);

CREATE INDEX IF NOT EXISTS idx_parent_claims_member
    ON parent_claims(member_id);

CREATE INDEX IF NOT EXISTS idx_parent_claims_status
    ON parent_claims(status, created_at);

CREATE INDEX IF NOT EXISTS idx_parent_claims_player
    ON parent_claims(matched_player_id)
    WHERE matched_player_id IS NOT NULL;

-- RLS
ALTER TABLE parent_claims ENABLE ROW LEVEL SECURITY;

CREATE POLICY parent_claims_select ON parent_claims
    FOR SELECT USING (true);

CREATE POLICY parent_claims_insert ON parent_claims
    FOR INSERT WITH CHECK (true);

CREATE POLICY parent_claims_update ON parent_claims
    FOR UPDATE USING (true);


-- =============================================
-- 2) verification_ai_reports 테이블
-- =============================================
CREATE TABLE IF NOT EXISTS verification_ai_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_type VARCHAR(30) NOT NULL,  -- verification/player_claim/parent_claim/org_claim
    target_id UUID NOT NULL,
    ai_model VARCHAR(50) NOT NULL DEFAULT 'gemini-2.0-flash-exp',
    confidence DECIMAL(3,2) NOT NULL,
    recommendation VARCHAR(20) NOT NULL,  -- approve/reject/manual_review
    evidence JSONB NOT NULL DEFAULT '[]',
    flags JSONB NOT NULL DEFAULT '[]',
    reasoning TEXT,
    raw_response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_reports_target
    ON verification_ai_reports(target_type, target_id);

CREATE INDEX IF NOT EXISTS idx_ai_reports_created
    ON verification_ai_reports(created_at DESC);

-- RLS
ALTER TABLE verification_ai_reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY ai_reports_select ON verification_ai_reports
    FOR SELECT USING (true);

CREATE POLICY ai_reports_insert ON verification_ai_reports
    FOR INSERT WITH CHECK (true);


-- =============================================
-- 3) notifications 확장
-- =============================================
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS link_url TEXT;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';
