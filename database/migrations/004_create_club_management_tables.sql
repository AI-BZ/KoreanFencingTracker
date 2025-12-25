-- Supabase Migration: Club Management System
-- Version: 004
-- Created: 2025-12-22
-- Description: 클럽 관리 SaaS (출결, 레슨, 비용, 대회 관리)

-- =============================================
-- 1. members 테이블 확장 (클럽 역할)
-- =============================================
ALTER TABLE members ADD COLUMN IF NOT EXISTS club_role VARCHAR(30) CHECK (club_role IN (
    'owner',          -- 클럽 소유자/대표
    'head_coach',     -- 수석 코치
    'coach',          -- 코치
    'assistant',      -- 보조 코치
    'student',        -- 수강생 (선수)
    'parent',         -- 학부모
    'staff'           -- 행정 스태프
));

ALTER TABLE members ADD COLUMN IF NOT EXISTS enrollment_date DATE;
ALTER TABLE members ADD COLUMN IF NOT EXISTS member_status VARCHAR(20) DEFAULT 'active' CHECK (member_status IN (
    'active',         -- 활성
    'inactive',       -- 휴회
    'suspended',      -- 정지
    'graduated'       -- 졸업/퇴회
));
ALTER TABLE members ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(20);
ALTER TABLE members ADD COLUMN IF NOT EXISTS notes TEXT;

CREATE INDEX IF NOT EXISTS idx_members_club_role ON members(club_role);
CREATE INDEX IF NOT EXISTS idx_members_member_status ON members(member_status);

-- =============================================
-- 2. club_settings 테이블 (클럽별 설정)
-- =============================================
CREATE TABLE IF NOT EXISTS club_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id BIGINT NOT NULL UNIQUE REFERENCES organizations(id) ON DELETE CASCADE,

    -- 기본 정보
    club_name VARCHAR(100),
    club_logo_url TEXT,

    -- 자동 체크인 설정
    auto_checkin_enabled BOOLEAN DEFAULT FALSE,
    allowed_ips TEXT[],  -- 허용 IP 목록 (공인 IP)
    allowed_wifi_ssids TEXT[],  -- 허용 WiFi SSID 목록
    geofence_enabled BOOLEAN DEFAULT FALSE,
    geofence_latitude DECIMAL(10, 7),
    geofence_longitude DECIMAL(10, 7),
    geofence_radius_meters INTEGER DEFAULT 100,

    -- 비용 설정 (기본값)
    default_monthly_fee INTEGER DEFAULT 0,  -- 월회비 기본값
    default_lesson_fee INTEGER DEFAULT 0,   -- 레슨비 기본값
    fee_due_day INTEGER DEFAULT 10,  -- 납부 기한일 (매월 N일)

    -- 운영 시간
    operating_hours JSONB,  -- {"mon": {"start": "09:00", "end": "21:00"}, ...}

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_club_settings_org ON club_settings(organization_id);

-- Update trigger
DROP TRIGGER IF EXISTS update_club_settings_updated_at ON club_settings;
CREATE TRIGGER update_club_settings_updated_at
    BEFORE UPDATE ON club_settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================
-- 3. attendance 테이블 (출석 기록)
-- =============================================
CREATE TABLE IF NOT EXISTS attendance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,

    -- 출석 정보
    check_in_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    check_out_at TIMESTAMPTZ,
    attendance_type VARCHAR(20) NOT NULL DEFAULT 'regular' CHECK (attendance_type IN (
        'regular',        -- 정규 훈련
        'lesson',         -- 개인/그룹 레슨
        'competition',    -- 대회 참가
        'makeup',         -- 보강
        'trial'           -- 체험
    )),

    -- 체크인 방식
    checkin_method VARCHAR(20) DEFAULT 'manual' CHECK (checkin_method IN (
        'manual',         -- 수동 버튼
        'auto_ip',        -- IP 기반 자동
        'auto_wifi',      -- WiFi 기반 자동
        'auto_geo',       -- GPS 기반 자동
        'coach'           -- 코치가 대신 체크인
    )),

    -- 메타
    client_ip INET,       -- 체크인 시 IP
    device_info TEXT,     -- 기기 정보
    verified_by UUID REFERENCES members(id),  -- 확인한 코치
    notes TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attendance_org ON attendance(organization_id);
CREATE INDEX IF NOT EXISTS idx_attendance_member ON attendance(member_id);
CREATE INDEX IF NOT EXISTS idx_attendance_check_in ON attendance(check_in_at);
CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(DATE(check_in_at));
CREATE INDEX IF NOT EXISTS idx_attendance_type ON attendance(attendance_type);

-- =============================================
-- 4. lessons 테이블 (레슨 일정)
-- =============================================
CREATE TABLE IF NOT EXISTS lessons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- 레슨 정보
    lesson_type VARCHAR(20) NOT NULL CHECK (lesson_type IN (
        'individual',     -- 개인 레슨
        'group',          -- 그룹 레슨 (2-4명)
        'team',           -- 팀 훈련
        'special'         -- 특별 레슨 (집중/캠프)
    )),
    title VARCHAR(100) NOT NULL,
    description TEXT,

    -- 일정
    scheduled_at TIMESTAMPTZ NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    recurring_rule JSONB,  -- 반복 규칙 (iCalendar RRULE 형식)

    -- 담당
    coach_id UUID NOT NULL REFERENCES members(id),
    max_students INTEGER DEFAULT 1,

    -- 비용
    fee_per_session INTEGER DEFAULT 0,  -- 원 단위

    -- 상태
    status VARCHAR(20) DEFAULT 'scheduled' CHECK (status IN (
        'scheduled',      -- 예정
        'in_progress',    -- 진행중
        'completed',      -- 완료
        'cancelled'       -- 취소
    )),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lessons_org ON lessons(organization_id);
CREATE INDEX IF NOT EXISTS idx_lessons_coach ON lessons(coach_id);
CREATE INDEX IF NOT EXISTS idx_lessons_scheduled ON lessons(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_lessons_status ON lessons(status);

-- Update trigger
DROP TRIGGER IF EXISTS update_lessons_updated_at ON lessons;
CREATE TRIGGER update_lessons_updated_at
    BEFORE UPDATE ON lessons
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================
-- 5. lesson_participants 테이블 (레슨 참가자)
-- =============================================
CREATE TABLE IF NOT EXISTS lesson_participants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lesson_id UUID NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,

    attendance_status VARCHAR(20) DEFAULT 'registered' CHECK (attendance_status IN (
        'registered',     -- 등록됨
        'attended',       -- 출석
        'absent',         -- 결석
        'cancelled'       -- 취소
    )),
    attended_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(lesson_id, member_id)
);

CREATE INDEX IF NOT EXISTS idx_lesson_participants_lesson ON lesson_participants(lesson_id);
CREATE INDEX IF NOT EXISTS idx_lesson_participants_member ON lesson_participants(member_id);

-- =============================================
-- 6. fees 테이블 (비용 관리)
-- =============================================
CREATE TABLE IF NOT EXISTS fees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,

    -- 비용 정보
    fee_type VARCHAR(30) NOT NULL CHECK (fee_type IN (
        'membership',     -- 월회비
        'lesson',         -- 레슨비
        'competition',    -- 대회비 (참가비+출장비)
        'equipment',      -- 장비비
        'uniform',        -- 유니폼비
        'registration',   -- 등록비
        'other'           -- 기타
    )),

    -- 금액
    amount INTEGER NOT NULL,  -- 원 단위
    description TEXT,

    -- 기간 (월회비용)
    period_start DATE,
    period_end DATE,

    -- 연결
    lesson_id UUID REFERENCES lessons(id) ON DELETE SET NULL,
    competition_entry_id UUID,  -- 대회 참가 연결 (후에 FK 추가)

    -- 납부 상태
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN (
        'pending',        -- 대기
        'paid',           -- 납부완료
        'overdue',        -- 연체
        'waived',         -- 면제
        'refunded'        -- 환불
    )),

    -- 결제 정보
    payment_method VARCHAR(20),  -- 'cash', 'bank_transfer', 'card', 'pg'
    payment_reference VARCHAR(100),  -- 결제 참조번호
    paid_at TIMESTAMPTZ,
    confirmed_by UUID REFERENCES members(id),  -- 확인한 코치

    -- 기한
    due_date DATE,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fees_org ON fees(organization_id);
CREATE INDEX IF NOT EXISTS idx_fees_member ON fees(member_id);
CREATE INDEX IF NOT EXISTS idx_fees_type ON fees(fee_type);
CREATE INDEX IF NOT EXISTS idx_fees_status ON fees(status);
CREATE INDEX IF NOT EXISTS idx_fees_due_date ON fees(due_date);
CREATE INDEX IF NOT EXISTS idx_fees_period ON fees(period_start, period_end);

-- Update trigger
DROP TRIGGER IF EXISTS update_fees_updated_at ON fees;
CREATE TRIGGER update_fees_updated_at
    BEFORE UPDATE ON fees
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================
-- 7. competition_entries 테이블 (대회 참가 관리)
-- =============================================
CREATE TABLE IF NOT EXISTS competition_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id BIGINT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    competition_id BIGINT REFERENCES competitions(id),  -- 기존 대회 테이블 연결

    -- 대회 정보 (외부 대회용)
    competition_name VARCHAR(255),
    competition_date DATE NOT NULL,
    competition_location VARCHAR(255),

    -- 참가 상태
    status VARCHAR(20) DEFAULT 'planning' CHECK (status IN (
        'planning',       -- 계획중
        'registered',     -- 등록완료
        'in_progress',    -- 진행중
        'completed',      -- 완료
        'cancelled'       -- 취소
    )),

    -- 비용 (전체)
    entry_fee_total INTEGER DEFAULT 0,      -- 참가비 총액
    travel_expense_total INTEGER DEFAULT 0, -- 출장비 총액
    accommodation_total INTEGER DEFAULT 0,  -- 숙박비 총액
    other_expense_total INTEGER DEFAULT 0,  -- 기타 비용

    -- 메모
    notes TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_comp_entries_org ON competition_entries(organization_id);
CREATE INDEX IF NOT EXISTS idx_comp_entries_date ON competition_entries(competition_date);
CREATE INDEX IF NOT EXISTS idx_comp_entries_status ON competition_entries(status);

-- Update trigger
DROP TRIGGER IF EXISTS update_comp_entries_updated_at ON competition_entries;
CREATE TRIGGER update_comp_entries_updated_at
    BEFORE UPDATE ON competition_entries
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- FK for fees table
ALTER TABLE fees ADD CONSTRAINT fk_fees_competition_entry
    FOREIGN KEY (competition_entry_id) REFERENCES competition_entries(id) ON DELETE SET NULL;

-- =============================================
-- 8. competition_participants 테이블 (대회 참가자)
-- =============================================
CREATE TABLE IF NOT EXISTS competition_participants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    competition_entry_id UUID NOT NULL REFERENCES competition_entries(id) ON DELETE CASCADE,
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,

    -- 참가 정보
    event_name VARCHAR(100),  -- 참가 종목 (예: 남자 플뢰레)

    -- 개인별 비용 분담
    entry_fee INTEGER DEFAULT 0,       -- 개인 참가비
    travel_expense INTEGER DEFAULT 0,  -- 개인 출장비
    accommodation INTEGER DEFAULT 0,   -- 개인 숙박비
    other_expense INTEGER DEFAULT 0,   -- 기타

    -- 결과 (대회 후 입력)
    final_rank INTEGER,
    notes TEXT,

    -- 결제 상태
    payment_status VARCHAR(20) DEFAULT 'pending' CHECK (payment_status IN (
        'pending', 'paid', 'waived'
    )),

    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(competition_entry_id, member_id, event_name)
);

CREATE INDEX IF NOT EXISTS idx_comp_participants_entry ON competition_participants(competition_entry_id);
CREATE INDEX IF NOT EXISTS idx_comp_participants_member ON competition_participants(member_id);

-- =============================================
-- 9. 유틸리티 함수
-- =============================================

-- 월간 출석 통계
CREATE OR REPLACE FUNCTION get_monthly_attendance_stats(
    p_org_id BIGINT,
    p_year INTEGER,
    p_month INTEGER
)
RETURNS TABLE (
    member_id UUID,
    member_name TEXT,
    total_days INTEGER,
    regular_count INTEGER,
    lesson_count INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        a.member_id,
        m.full_name,
        COUNT(DISTINCT DATE(a.check_in_at))::INTEGER as total_days,
        COUNT(CASE WHEN a.attendance_type = 'regular' THEN 1 END)::INTEGER as regular_count,
        COUNT(CASE WHEN a.attendance_type = 'lesson' THEN 1 END)::INTEGER as lesson_count
    FROM attendance a
    JOIN members m ON m.id = a.member_id
    WHERE a.organization_id = p_org_id
    AND EXTRACT(YEAR FROM a.check_in_at) = p_year
    AND EXTRACT(MONTH FROM a.check_in_at) = p_month
    GROUP BY a.member_id, m.full_name
    ORDER BY total_days DESC;
END;
$$ LANGUAGE plpgsql;

-- 미납 비용 조회
CREATE OR REPLACE FUNCTION get_overdue_fees(p_org_id BIGINT)
RETURNS TABLE (
    fee_id UUID,
    member_id UUID,
    member_name TEXT,
    fee_type TEXT,
    amount INTEGER,
    due_date DATE,
    days_overdue INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        f.id,
        f.member_id,
        m.full_name,
        f.fee_type,
        f.amount,
        f.due_date,
        (CURRENT_DATE - f.due_date)::INTEGER as days_overdue
    FROM fees f
    JOIN members m ON m.id = f.member_id
    WHERE f.organization_id = p_org_id
    AND f.status = 'pending'
    AND f.due_date < CURRENT_DATE
    ORDER BY f.due_date ASC;
END;
$$ LANGUAGE plpgsql;

-- IP 기반 자동 체크인 가능 여부 확인
CREATE OR REPLACE FUNCTION check_auto_checkin_allowed(
    p_org_id BIGINT,
    p_client_ip INET
)
RETURNS BOOLEAN AS $$
DECLARE
    v_allowed BOOLEAN := FALSE;
    v_settings club_settings%ROWTYPE;
BEGIN
    SELECT * INTO v_settings FROM club_settings WHERE organization_id = p_org_id;

    IF v_settings.auto_checkin_enabled = TRUE AND v_settings.allowed_ips IS NOT NULL THEN
        -- IP가 허용 목록에 있는지 확인
        SELECT TRUE INTO v_allowed
        FROM unnest(v_settings.allowed_ips) AS ip
        WHERE p_client_ip::TEXT = ip OR p_client_ip::TEXT LIKE ip || '%';
    END IF;

    RETURN v_allowed;
END;
$$ LANGUAGE plpgsql;

-- =============================================
-- 10. RLS (Row Level Security) 정책
-- =============================================

-- club_settings RLS
ALTER TABLE club_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "club_settings_select_org_members" ON club_settings
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.supabase_auth_id = auth.uid()
            AND m.organization_id = club_settings.organization_id
        )
    );

CREATE POLICY "club_settings_manage_admin" ON club_settings
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.supabase_auth_id = auth.uid()
            AND m.organization_id = club_settings.organization_id
            AND m.club_role IN ('owner', 'head_coach')
        )
    );

-- attendance RLS
ALTER TABLE attendance ENABLE ROW LEVEL SECURITY;

-- 같은 조직 회원만 조회 가능
CREATE POLICY "attendance_select_org_members" ON attendance
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.supabase_auth_id = auth.uid()
            AND m.organization_id = attendance.organization_id
        )
    );

-- 코치만 출석 생성 가능 (또는 본인 체크인)
CREATE POLICY "attendance_insert_coach_or_self" ON attendance
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.supabase_auth_id = auth.uid()
            AND m.organization_id = attendance.organization_id
            AND (
                m.club_role IN ('owner', 'head_coach', 'coach', 'staff')
                OR m.id = attendance.member_id  -- 본인 체크인
            )
        )
    );

-- 코치만 출석 수정 가능
CREATE POLICY "attendance_update_coach" ON attendance
    FOR UPDATE USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.supabase_auth_id = auth.uid()
            AND m.organization_id = attendance.organization_id
            AND m.club_role IN ('owner', 'head_coach', 'coach', 'staff')
        )
    );

-- lessons RLS
ALTER TABLE lessons ENABLE ROW LEVEL SECURITY;

CREATE POLICY "lessons_select_org_members" ON lessons
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.supabase_auth_id = auth.uid()
            AND m.organization_id = lessons.organization_id
        )
    );

CREATE POLICY "lessons_manage_coach" ON lessons
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.supabase_auth_id = auth.uid()
            AND m.organization_id = lessons.organization_id
            AND m.club_role IN ('owner', 'head_coach', 'coach')
        )
    );

-- lesson_participants RLS
ALTER TABLE lesson_participants ENABLE ROW LEVEL SECURITY;

CREATE POLICY "lesson_participants_select" ON lesson_participants
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM lessons l
            JOIN members m ON m.organization_id = l.organization_id
            WHERE l.id = lesson_participants.lesson_id
            AND m.supabase_auth_id = auth.uid()
        )
    );

CREATE POLICY "lesson_participants_manage" ON lesson_participants
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM lessons l
            JOIN members m ON m.organization_id = l.organization_id
            WHERE l.id = lesson_participants.lesson_id
            AND m.supabase_auth_id = auth.uid()
            AND m.club_role IN ('owner', 'head_coach', 'coach')
        )
    );

-- fees RLS
ALTER TABLE fees ENABLE ROW LEVEL SECURITY;

-- 본인 또는 코치/보호자만 비용 조회 가능
CREATE POLICY "fees_select_authorized" ON fees
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.supabase_auth_id = auth.uid()
            AND (
                -- 코치/관리자
                (m.organization_id = fees.organization_id
                 AND m.club_role IN ('owner', 'head_coach', 'coach', 'staff'))
                OR
                -- 본인
                m.id = fees.member_id
                OR
                -- 보호자
                EXISTS (
                    SELECT 1 FROM members child
                    WHERE child.id = fees.member_id
                    AND child.guardian_member_id = m.id
                )
            )
        )
    );

CREATE POLICY "fees_manage_staff" ON fees
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.supabase_auth_id = auth.uid()
            AND m.organization_id = fees.organization_id
            AND m.club_role IN ('owner', 'head_coach', 'coach', 'staff')
        )
    );

-- competition_entries RLS
ALTER TABLE competition_entries ENABLE ROW LEVEL SECURITY;

CREATE POLICY "competition_entries_select_org" ON competition_entries
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.supabase_auth_id = auth.uid()
            AND m.organization_id = competition_entries.organization_id
        )
    );

CREATE POLICY "competition_entries_manage_staff" ON competition_entries
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.supabase_auth_id = auth.uid()
            AND m.organization_id = competition_entries.organization_id
            AND m.club_role IN ('owner', 'head_coach', 'coach', 'staff')
        )
    );

-- competition_participants RLS
ALTER TABLE competition_participants ENABLE ROW LEVEL SECURITY;

CREATE POLICY "competition_participants_select" ON competition_participants
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM competition_entries ce
            JOIN members m ON m.organization_id = ce.organization_id
            WHERE ce.id = competition_participants.competition_entry_id
            AND m.supabase_auth_id = auth.uid()
        )
    );

CREATE POLICY "competition_participants_manage" ON competition_participants
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM competition_entries ce
            JOIN members m ON m.organization_id = ce.organization_id
            WHERE ce.id = competition_participants.competition_entry_id
            AND m.supabase_auth_id = auth.uid()
            AND m.club_role IN ('owner', 'head_coach', 'coach', 'staff')
        )
    );
