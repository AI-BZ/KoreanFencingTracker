-- ============================================================
-- Migration 007: Billing, Payment, Notification System
-- FencingMind Club SaaS - 청구/결제/알림 시스템
-- ============================================================

-- ============================================
-- 1. 구독 관리 (클럽별 SaaS 구독)
-- ============================================
CREATE TABLE IF NOT EXISTS app_subscriptions (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id) UNIQUE,

    tier VARCHAR(20) NOT NULL DEFAULT 'free',  -- free/basic/premium/enterprise
    alimtalk_limit INTEGER NOT NULL DEFAULT 0, -- 월 알림톡 한도 (0=비활성)
    alimtalk_used INTEGER NOT NULL DEFAULT 0,  -- 이번 달 사용량
    alimtalk_reset_at DATE,                    -- 다음 리셋 날짜

    started_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- 2. 청구서 (코치가 생성)
-- ============================================
CREATE TABLE IF NOT EXISTS app_invoices (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id),
    created_by UUID NOT NULL REFERENCES members(id),

    title VARCHAR(200) NOT NULL,
    description TEXT,
    invoice_type VARCHAR(30) NOT NULL,
    -- invoice_type: monthly_dues, lesson, competition_entry,
    --              coach_travel, transportation, equipment_repair,
    --              equipment_purchase, other

    total_amount INTEGER NOT NULL,
    due_date DATE,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    -- status: draft, sent, partial, paid, overdue, cancelled

    -- 대회 연관
    competition_id BIGINT,

    -- 분할 설정
    split_type VARCHAR(10) DEFAULT 'none',  -- none/equal/custom
    target_count INTEGER,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- 3. 청구 대상 (멤버별)
-- ============================================
CREATE TABLE IF NOT EXISTS app_invoice_members (
    id BIGSERIAL PRIMARY KEY,
    invoice_id BIGINT NOT NULL REFERENCES app_invoices(id) ON DELETE CASCADE,
    member_id UUID NOT NULL REFERENCES members(id),

    amount INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- status: pending, paid, partial, overdue, waived
    paid_amount INTEGER DEFAULT 0,

    notified_at TIMESTAMPTZ,
    reminder_count INTEGER DEFAULT 0,
    paid_at TIMESTAMPTZ,
    memo TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(invoice_id, member_id)
);

-- ============================================
-- 4. 수납 기록
-- ============================================
CREATE TABLE IF NOT EXISTS app_payments (
    id BIGSERIAL PRIMARY KEY,
    invoice_member_id BIGINT NOT NULL REFERENCES app_invoice_members(id),
    org_id BIGINT NOT NULL REFERENCES organizations(id),

    amount INTEGER NOT NULL,
    payment_method VARCHAR(20) NOT NULL,
    -- payment_method: card, cash, bank_transfer, billing_key
    payment_status VARCHAR(20) NOT NULL DEFAULT 'success',
    -- payment_status: success, failed, refunded, pending

    -- PortOne 연동
    portone_payment_id VARCHAR(100),
    portone_tx_id VARCHAR(100),

    -- 현금/이체 확인
    confirmed_by UUID REFERENCES members(id),

    memo TEXT,
    paid_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- 5. 빌링키 (학부모 카드 등록)
-- ============================================
CREATE TABLE IF NOT EXISTS app_billing_keys (
    id BIGSERIAL PRIMARY KEY,
    member_id UUID NOT NULL REFERENCES members(id),
    org_id BIGINT NOT NULL REFERENCES organizations(id),

    billing_key VARCHAR(200) NOT NULL,
    card_name VARCHAR(50),
    card_number_masked VARCHAR(20),

    is_active BOOLEAN DEFAULT true,
    registered_at TIMESTAMPTZ DEFAULT NOW(),
    deactivated_at TIMESTAMPTZ,

    UNIQUE(member_id, org_id)
);

-- ============================================
-- 6. 정기 청구 설정
-- ============================================
CREATE TABLE IF NOT EXISTS app_recurring_bills (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id),
    member_id UUID NOT NULL REFERENCES members(id),

    bill_type VARCHAR(30) NOT NULL,  -- monthly_dues, lesson
    amount INTEGER NOT NULL,
    billing_day INTEGER DEFAULT 1 CHECK (billing_day BETWEEN 1 AND 28),

    auto_pay BOOLEAN DEFAULT false,
    billing_key_id BIGINT REFERENCES app_billing_keys(id),

    is_active BOOLEAN DEFAULT true,
    next_bill_date DATE,
    last_billed_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(org_id, member_id, bill_type)
);

-- ============================================
-- 7. 비용 템플릿
-- ============================================
CREATE TABLE IF NOT EXISTS app_fee_templates (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id),

    name VARCHAR(100) NOT NULL,
    fee_type VARCHAR(30) NOT NULL,
    default_amount INTEGER NOT NULL,
    description TEXT,

    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- 8. 클럽 PG 설정 (PortOne 멀티스토어)
-- ============================================
CREATE TABLE IF NOT EXISTS app_club_pg_settings (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id) UNIQUE,

    portone_store_id VARCHAR(100),
    pg_provider VARCHAR(50),

    is_active BOOLEAN DEFAULT false,
    settings JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- 9. 알림 기록
-- ============================================
CREATE TABLE IF NOT EXISTS app_notifications (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id),
    member_id UUID NOT NULL REFERENCES members(id),

    notification_type VARCHAR(30) NOT NULL,
    -- notification_type: invoice, reminder, payment_confirm, checkin, system
    channel VARCHAR(20) NOT NULL,
    -- channel: fcm, alimtalk, sms, app

    title VARCHAR(200),
    message TEXT,

    reference_type VARCHAR(30),  -- invoice, payment
    reference_id BIGINT,

    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- status: pending, sent, failed, read
    sent_at TIMESTAMPTZ,
    read_at TIMESTAMPTZ,
    error_message TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- 10. FCM 푸시 토큰
-- ============================================
CREATE TABLE IF NOT EXISTS app_push_tokens (
    id BIGSERIAL PRIMARY KEY,
    member_id UUID NOT NULL REFERENCES members(id),

    token TEXT NOT NULL,
    device_type VARCHAR(20),  -- ios, android, web
    device_name VARCHAR(100),

    is_active BOOLEAN DEFAULT true,
    last_used_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(member_id, token)
);

-- ============================================
-- Indexes
-- ============================================
CREATE INDEX IF NOT EXISTS idx_invoices_org_status ON app_invoices(org_id, status);
CREATE INDEX IF NOT EXISTS idx_invoices_created ON app_invoices(org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_invoices_type ON app_invoices(org_id, invoice_type);

CREATE INDEX IF NOT EXISTS idx_invoice_members_member ON app_invoice_members(member_id, status);
CREATE INDEX IF NOT EXISTS idx_invoice_members_invoice ON app_invoice_members(invoice_id, status);

CREATE INDEX IF NOT EXISTS idx_payments_org ON app_payments(org_id, paid_at DESC);
CREATE INDEX IF NOT EXISTS idx_payments_invoice_member ON app_payments(invoice_member_id);

CREATE INDEX IF NOT EXISTS idx_recurring_next ON app_recurring_bills(next_bill_date)
    WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_recurring_org ON app_recurring_bills(org_id, is_active);

CREATE INDEX IF NOT EXISTS idx_notifications_member ON app_notifications(member_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON app_notifications(member_id, status)
    WHERE status IN ('pending', 'sent');
CREATE INDEX IF NOT EXISTS idx_notifications_org ON app_notifications(org_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_push_tokens_member ON app_push_tokens(member_id)
    WHERE is_active = true;

-- ============================================
-- RLS (Row Level Security) Policies
-- ============================================
ALTER TABLE app_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_invoice_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_billing_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_recurring_bills ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_push_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_fee_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_club_pg_settings ENABLE ROW LEVEL SECURITY;

-- Service role can do everything (API server uses service role key)
CREATE POLICY "service_role_all" ON app_invoices FOR ALL TO service_role USING (true);
CREATE POLICY "service_role_all" ON app_invoice_members FOR ALL TO service_role USING (true);
CREATE POLICY "service_role_all" ON app_payments FOR ALL TO service_role USING (true);
CREATE POLICY "service_role_all" ON app_billing_keys FOR ALL TO service_role USING (true);
CREATE POLICY "service_role_all" ON app_recurring_bills FOR ALL TO service_role USING (true);
CREATE POLICY "service_role_all" ON app_notifications FOR ALL TO service_role USING (true);
CREATE POLICY "service_role_all" ON app_push_tokens FOR ALL TO service_role USING (true);
CREATE POLICY "service_role_all" ON app_subscriptions FOR ALL TO service_role USING (true);
CREATE POLICY "service_role_all" ON app_fee_templates FOR ALL TO service_role USING (true);
CREATE POLICY "service_role_all" ON app_club_pg_settings FOR ALL TO service_role USING (true);
