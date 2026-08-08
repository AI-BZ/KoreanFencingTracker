-- Migration 010: Account Management Infrastructure
-- OAuth states (DB persistence), services definition, Stripe/payment integration, password support
-- Created: 2026-02-24

-- ============================================================
-- 1. OAuth States (in-memory → DB, survives server restarts)
-- ============================================================
CREATE TABLE IF NOT EXISTS oauth_states (
    state VARCHAR(64) PRIMARY KEY,
    provider VARCHAR(20) NOT NULL,
    promotional BOOLEAN DEFAULT FALSE,
    code_verifier TEXT,
    redirect_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '10 minutes')
);

-- Auto-cleanup expired states
CREATE INDEX IF NOT EXISTS idx_oauth_states_expires_at ON oauth_states(expires_at);

-- ============================================================
-- 2. Services Definition Table
-- ============================================================
CREATE TABLE IF NOT EXISTS services (
    id VARCHAR(20) PRIMARY KEY,
    name_ko VARCHAR(100) NOT NULL,
    name_en VARCHAR(100) NOT NULL,
    description_ko TEXT,
    description_en TEXT,
    icon VARCHAR(10),
    pricing JSONB NOT NULL DEFAULT '{}',
    features JSONB NOT NULL DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Seed data
INSERT INTO services (id, name_ko, name_en, description_ko, description_en, icon, pricing, features, is_active, sort_order) VALUES
    ('data', '데이터', 'Data', '대회/선수/랭킹 데이터', 'Competition/Player/Ranking Data', '📊',
     '{"free":0,"basic_monthly":29,"basic_yearly":249,"premium_monthly":99,"premium_yearly":849,"enterprise_monthly":499}',
     '{"free":["대회 목록(30일)","선수 검색(이름만)","Top-10 랭킹"],"basic":["고급 필터","500 API/일","CSV 내보내기","알림(10명)"],"premium":["5000 API/일","무제한 내보내기","선수 비교","트렌드 분석"],"enterprise":["무제한 API","벌크 다운로드","웹훅","화이트라벨"]}',
     true, 1),
    ('club', '클럽관리', 'Club', '클럽 SaaS 관리', 'Club SaaS Management', '🏫',
     '{"free":0,"basic_monthly":29,"premium_monthly":99,"enterprise_monthly":299,"family_monthly":9.99}',
     '{"free":["10명 이하","출석(IP)","기본 대시보드"],"basic":["50명","출석(IP+GPS+QR)","레슨관리","비용관리"],"premium":["200명","고급 분석","멀티코치","API"],"enterprise":["무제한","멀티지점","커스텀 브랜딩"]}',
     true, 2),
    ('community', '커뮤니티', 'Community', '포럼/Q&A', 'Forum/Q&A', '💬',
     '{"free":0,"premium_monthly":4.99}',
     '{"free":["글 작성","댓글","리액션(5/일)"],"premium":["광고 제거","무제한 글","인증 배지","Pro 포럼","DM(20/일)"]}',
     false, 3),
    ('shop', '쇼핑', 'Shop', '펜싱 용품', 'Fencing Equipment', '🛒',
     '{}',
     '{"free":["구매","주문이력","위시리스트","리뷰"]}',
     false, 4),
    ('blog', '블로그', 'Blog', '콘텐츠/기술 가이드', 'Content/Technical Guides', '📝',
     '{}',
     '{"free":["읽기","댓글","북마크"]}',
     false, 5),
    ('analytics', 'AI분석', 'Analytics', 'AI 경기 분석', 'AI Match Analysis', '🎯',
     '{"per_use":19.99,"pro_monthly":99,"team_monthly":499}',
     '{"per_use":["영상 1개 분석","PDF 리포트"],"pro":["30건/월","시즌 추적","상대 인텔리전스"],"team":["Pro 5계정","팀 대시보드","코치 주석"]}',
     false, 6)
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- 3. Stripe Integration Tables
-- ============================================================

-- Stripe customer mapping (1:1 with members)
CREATE TABLE IF NOT EXISTS stripe_customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE UNIQUE,
    stripe_customer_id VARCHAR(50) NOT NULL UNIQUE,
    default_payment_method_id VARCHAR(50),
    currency VARCHAR(3) DEFAULT 'USD',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stripe_customers_member ON stripe_customers(member_id);
CREATE INDEX IF NOT EXISTS idx_stripe_customers_stripe ON stripe_customers(stripe_customer_id);

-- Stripe subscription tracking
CREATE TABLE IF NOT EXISTS stripe_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    service_id VARCHAR(20) NOT NULL,
    stripe_subscription_id VARCHAR(50) UNIQUE,
    stripe_price_id VARCHAR(50),
    tier VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    cancel_at_period_end BOOLEAN DEFAULT FALSE,
    canceled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stripe_subs_member ON stripe_subscriptions(member_id);
CREATE INDEX IF NOT EXISTS idx_stripe_subs_stripe ON stripe_subscriptions(stripe_subscription_id);
CREATE INDEX IF NOT EXISTS idx_stripe_subs_service ON stripe_subscriptions(member_id, service_id);

-- ============================================================
-- 4. Payment Events Log (Stripe + PortOne unified)
-- ============================================================
CREATE TABLE IF NOT EXISTS payment_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID REFERENCES members(id) ON DELETE SET NULL,
    event_source VARCHAR(20) NOT NULL,  -- 'stripe' or 'portone'
    event_id VARCHAR(100) NOT NULL UNIQUE,
    event_type VARCHAR(60) NOT NULL,
    service_id VARCHAR(20),
    amount INTEGER,
    currency VARCHAR(3) DEFAULT 'KRW',
    payload JSONB,
    processed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payment_events_member ON payment_events(member_id);
CREATE INDEX IF NOT EXISTS idx_payment_events_type ON payment_events(event_type);

-- ============================================================
-- 5. Password Hash Column (email+password registration)
-- ============================================================
ALTER TABLE members ADD COLUMN IF NOT EXISTS password_hash VARCHAR(128);

-- ============================================================
-- 6. Cleanup function for expired oauth_states (call via cron or pg_cron)
-- ============================================================
CREATE OR REPLACE FUNCTION cleanup_expired_oauth_states()
RETURNS void AS $$
BEGIN
    DELETE FROM oauth_states WHERE expires_at < NOW();
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 7. OAuth Messaging Columns (카카오/LINE 개인 메시지 발송 지원)
-- ============================================================
-- 카카오 한도: 보내는 사람 100건/일, 같은 쌍 20건/일, 앱 전체 30,000건/일 (상향 불가)
ALTER TABLE oauth_connections ADD COLUMN IF NOT EXISTS scopes TEXT[] DEFAULT '{}';
ALTER TABLE oauth_connections ADD COLUMN IF NOT EXISTS messaging_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE oauth_connections ADD COLUMN IF NOT EXISTS messaging_role VARCHAR(10) DEFAULT 'receiver';
ALTER TABLE oauth_connections ADD COLUMN IF NOT EXISTS messaging_daily_used INTEGER DEFAULT 0;
ALTER TABLE oauth_connections ADD COLUMN IF NOT EXISTS messaging_daily_reset_at TIMESTAMPTZ DEFAULT NOW();
