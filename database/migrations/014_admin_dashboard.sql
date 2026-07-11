-- Migration 014: Admin Dashboard Infrastructure
-- RBAC 기반 관리자 시스템, 감사 로그, 관리 노트
-- Created: 2026-02-25

-- ============================================================
-- 1. members 테이블에 admin_role 컬럼 추가
-- ============================================================
ALTER TABLE members ADD COLUMN IF NOT EXISTS admin_role VARCHAR(20)
    CHECK (admin_role IN ('super_admin', 'service_admin', 'moderator', 'support'));

CREATE INDEX IF NOT EXISTS idx_members_admin_role ON members(admin_role)
    WHERE admin_role IS NOT NULL;

-- ============================================================
-- 2. admin_service_assignments: 서비스 관리자 배정
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_service_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    service_id VARCHAR(20) NOT NULL CHECK (service_id IN (
        'account', 'data', 'club', 'community', 'shop', 'blog', 'analytics'
    )),
    assigned_by UUID REFERENCES members(id),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(member_id, service_id)
);

CREATE INDEX IF NOT EXISTS idx_admin_svc_member ON admin_service_assignments(member_id);
CREATE INDEX IF NOT EXISTS idx_admin_svc_service ON admin_service_assignments(service_id);

-- ============================================================
-- 3. admin_audit_logs: 관리자 감사 로그 (append-only)
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id UUID NOT NULL REFERENCES members(id),
    action VARCHAR(50) NOT NULL,
    target_type VARCHAR(30) NOT NULL,
    target_id VARCHAR(100),
    details JSONB DEFAULT '{}',
    ip_address INET,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_admin ON admin_audit_logs(admin_id);
CREATE INDEX IF NOT EXISTS idx_audit_target ON admin_audit_logs(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON admin_audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON admin_audit_logs(action);

-- ============================================================
-- 4. admin_notes: 관리 노트 (회원/조직별)
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id UUID NOT NULL REFERENCES members(id),
    target_type VARCHAR(30) NOT NULL CHECK (target_type IN (
        'member', 'organization', 'verification', 'player_claim', 'organization_claim'
    )),
    target_id VARCHAR(100) NOT NULL,
    content TEXT NOT NULL,
    is_pinned BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notes_target ON admin_notes(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_notes_admin ON admin_notes(admin_id);
