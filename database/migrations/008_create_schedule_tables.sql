-- Migration 008: Schedule System Tables
-- 스케줄러 시스템 - 클럽/코치/개인 일정 관리

-- app_schedules: 통합 일정 테이블
CREATE TABLE IF NOT EXISTS app_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id BIGINT NOT NULL,

    -- Event basics
    title VARCHAR(200) NOT NULL,
    description TEXT,
    event_type VARCHAR(50) NOT NULL,  -- training, lesson, competition, club_event, holiday, personal, meeting
    color VARCHAR(7) DEFAULT '#667eea',

    -- Time
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    all_day BOOLEAN DEFAULT FALSE,

    -- Recurrence
    is_recurring BOOLEAN DEFAULT FALSE,
    recurrence_rule JSONB,
    recurrence_parent_id UUID REFERENCES app_schedules(id) ON DELETE CASCADE,

    -- Ownership & visibility
    created_by UUID NOT NULL,
    visibility VARCHAR(20) DEFAULT 'club',  -- club, coaches, personal

    -- Participants
    assigned_coach_id UUID,
    participant_ids UUID[] DEFAULT '{}',
    max_participants INT,

    -- Links
    lesson_id UUID,
    competition_id BIGINT,

    -- Location & status
    location VARCHAR(200),
    status VARCHAR(20) DEFAULT 'scheduled',

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_schedules_org_date ON app_schedules(organization_id, start_at);
CREATE INDEX IF NOT EXISTS idx_schedules_created_by ON app_schedules(created_by);
CREATE INDEX IF NOT EXISTS idx_schedules_type ON app_schedules(organization_id, event_type);
CREATE INDEX IF NOT EXISTS idx_schedules_visibility ON app_schedules(organization_id, visibility);
CREATE INDEX IF NOT EXISTS idx_schedules_coach ON app_schedules(assigned_coach_id) WHERE assigned_coach_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_schedules_parent ON app_schedules(recurrence_parent_id) WHERE recurrence_parent_id IS NOT NULL;

-- Updated_at trigger
CREATE OR REPLACE FUNCTION update_app_schedules_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_app_schedules_updated_at ON app_schedules;
CREATE TRIGGER trigger_app_schedules_updated_at
    BEFORE UPDATE ON app_schedules
    FOR EACH ROW
    EXECUTE FUNCTION update_app_schedules_updated_at();
