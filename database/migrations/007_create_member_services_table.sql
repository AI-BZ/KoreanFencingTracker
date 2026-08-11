-- 007_create_member_services_table.sql
-- 회원별 서비스 구독 관리 테이블

-- member_services 테이블
CREATE TABLE IF NOT EXISTS member_services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    service_id VARCHAR(20) NOT NULL CHECK (service_id IN (
        'data', 'club', 'community', 'shop', 'blog', 'analytics'
    )),
    tier VARCHAR(20) NOT NULL DEFAULT 'free' CHECK (tier IN (
        'free', 'basic', 'premium', 'enterprise'
    )),
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN (
        'active', 'inactive', 'suspended', 'cancelled', 'expired'
    )),
    settings JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(member_id, service_id)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_member_services_member_id ON member_services(member_id);
CREATE INDEX IF NOT EXISTS idx_member_services_service_id ON member_services(service_id);
CREATE INDEX IF NOT EXISTS idx_member_services_status ON member_services(status);
CREATE INDEX IF NOT EXISTS idx_member_services_tier ON member_services(tier);

-- updated_at 자동 트리거
CREATE OR REPLACE FUNCTION update_member_services_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_member_services_updated_at ON member_services;
CREATE TRIGGER trg_member_services_updated_at
    BEFORE UPDATE ON member_services
    FOR EACH ROW
    EXECUTE FUNCTION update_member_services_updated_at();

-- 회원 가입 시 data 서비스 free 자동 생성 트리거
CREATE OR REPLACE FUNCTION auto_create_data_service()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO member_services (member_id, service_id, tier, status)
    VALUES (NEW.id, 'data', 'free', 'active')
    ON CONFLICT (member_id, service_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_auto_create_data_service ON members;
CREATE TRIGGER trg_auto_create_data_service
    AFTER INSERT ON members
    FOR EACH ROW
    EXECUTE FUNCTION auto_create_data_service();

-- RLS 정책
ALTER TABLE member_services ENABLE ROW LEVEL SECURITY;

-- 본인 구독 조회
CREATE POLICY member_services_select_own ON member_services
    FOR SELECT
    USING (member_id = auth.uid() OR auth.role() = 'service_role');

-- 본인 구독 수정 (status, settings만)
CREATE POLICY member_services_update_own ON member_services
    FOR UPDATE
    USING (member_id = auth.uid() OR auth.role() = 'service_role')
    WITH CHECK (member_id = auth.uid() OR auth.role() = 'service_role');

-- 서비스 역할만 삽입 가능
CREATE POLICY member_services_insert ON member_services
    FOR INSERT
    WITH CHECK (auth.role() = 'service_role' OR auth.uid() IS NOT NULL);

-- 코멘트
COMMENT ON TABLE member_services IS '회원별 서비스 구독 관리 (SSO 기반)';
COMMENT ON COLUMN member_services.service_id IS '서비스 유형: data, club, community, shop, blog, analytics';
COMMENT ON COLUMN member_services.tier IS '구독 등급: free, basic, premium, enterprise';
COMMENT ON COLUMN member_services.status IS '구독 상태: active, inactive, suspended, cancelled, expired';
COMMENT ON COLUMN member_services.settings IS '서비스별 개인 설정 (JSON)';
