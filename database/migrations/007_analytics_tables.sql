-- Supabase Migration: Analytics Service Tables
-- Version: 007
-- Created: 2026-05-21
-- Description: AI 경기 분석 서비스 (analytics.fencingmind.ai) - 영상 업로드, 분석 작업, 결과, 크레딧 시스템

-- =============================================
-- 1. analytics_videos (업로드 영상)
-- =============================================
CREATE TABLE IF NOT EXISTS analytics_videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID REFERENCES members(id) ON DELETE SET NULL,

    -- 파일 정보
    filename TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    file_size BIGINT,
    duration_sec FLOAT,

    -- 영상 분류
    source_type TEXT CHECK (source_type IN ('coach', 'parent', 'player', 'tv_broadcast')),
    weapon TEXT CHECK (weapon IN ('foil', 'epee', 'sabre')),

    -- 상태
    status TEXT DEFAULT 'uploaded' CHECK (status IN (
        'uploaded',    -- 업로드 완료
        'analyzing',   -- 분석 중
        'completed',   -- 분석 완료
        'failed',      -- 분석 실패
        'deleted'      -- 삭제됨 (soft delete)
    )),

    -- 저장소
    storage_path TEXT NOT NULL,

    -- 타임스탬프
    uploaded_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_analytics_videos_member ON analytics_videos(member_id);
CREATE INDEX IF NOT EXISTS idx_analytics_videos_status ON analytics_videos(status);
CREATE INDEX IF NOT EXISTS idx_analytics_videos_uploaded ON analytics_videos(uploaded_at);
CREATE INDEX IF NOT EXISTS idx_analytics_videos_source_type ON analytics_videos(source_type);

-- =============================================
-- 2. analytics_analysis_jobs (분석 작업 큐)
-- =============================================
CREATE TABLE IF NOT EXISTS analytics_analysis_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id UUID NOT NULL REFERENCES analytics_videos(id) ON DELETE CASCADE,

    -- 작업 유형
    job_type TEXT DEFAULT 'standard' CHECK (job_type IN (
        'standard',    -- 일반 코치/선수 영상
        'broadcast',   -- TV 방송 영상
        'quick'        -- 빠른 분석 (하이라이트만)
    )),

    -- 상태
    status TEXT DEFAULT 'queued' CHECK (status IN (
        'queued',      -- 대기 중
        'processing',  -- 처리 중
        'completed',   -- 완료
        'failed',      -- 실패
        'cancelled'    -- 취소됨
    )),
    progress_pct FLOAT DEFAULT 0 CHECK (progress_pct >= 0 AND progress_pct <= 100),

    -- 설정
    config JSONB DEFAULT '{}',

    -- 실행 타임스탬프
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_jobs_video ON analytics_analysis_jobs(video_id);
CREATE INDEX IF NOT EXISTS idx_analytics_jobs_status ON analytics_analysis_jobs(status);
CREATE INDEX IF NOT EXISTS idx_analytics_jobs_created ON analytics_analysis_jobs(created_at);

-- =============================================
-- 3. analytics_analysis_results (분석 결과)
-- =============================================
CREATE TABLE IF NOT EXISTS analytics_analysis_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL UNIQUE REFERENCES analytics_analysis_jobs(id) ON DELETE CASCADE,

    -- 결과 데이터
    result_json JSONB NOT NULL,   -- raw EnrichedMatchEvent[]
    report_json JSONB,            -- MatchReport JSON

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_results_job ON analytics_analysis_results(job_id);

-- =============================================
-- 4. analytics_techniques (감지된 기술 - 비정규화, 쿼리 최적화)
-- =============================================
CREATE TABLE IF NOT EXISTS analytics_techniques (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id UUID NOT NULL REFERENCES analytics_analysis_results(id) ON DELETE CASCADE,

    -- 터치 정보
    touch_number INT,
    action TEXT NOT NULL,
    direction TEXT CHECK (direction IN ('left', 'right')),
    confidence FLOAT CHECK (confidence >= 0 AND confidence <= 1),

    -- 영상 위치
    frame INT,
    video_timestamp TEXT,

    -- 득점 정보
    scorer_side TEXT CHECK (scorer_side IN ('left', 'right')),
    score_after TEXT
);

CREATE INDEX IF NOT EXISTS idx_analytics_techniques_result ON analytics_techniques(result_id);
CREATE INDEX IF NOT EXISTS idx_analytics_techniques_action ON analytics_techniques(action);
CREATE INDEX IF NOT EXISTS idx_analytics_techniques_scorer ON analytics_techniques(scorer_side);

-- =============================================
-- 5. analytics_player_metrics (선수별 경기 지표)
-- =============================================
CREATE TABLE IF NOT EXISTS analytics_player_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id UUID NOT NULL REFERENCES analytics_analysis_results(id) ON DELETE CASCADE,
    player_id UUID REFERENCES players(id) ON DELETE SET NULL,  -- nullable: 미연결 선수

    -- 위치
    side TEXT NOT NULL CHECK (side IN ('left', 'right')),

    -- 통계
    total_scored INT DEFAULT 0,
    total_conceded INT DEFAULT 0,
    action_distribution JSONB DEFAULT '[]',
    insights JSONB DEFAULT '[]',
    avg_distance_at_touch FLOAT,

    UNIQUE(result_id, side)
);

CREATE INDEX IF NOT EXISTS idx_analytics_metrics_result ON analytics_player_metrics(result_id);
CREATE INDEX IF NOT EXISTS idx_analytics_metrics_player ON analytics_player_metrics(player_id);

-- =============================================
-- 6. analytics_bout_reports (공유 가능 경기 리포트)
-- =============================================
CREATE TABLE IF NOT EXISTS analytics_bout_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id UUID NOT NULL UNIQUE REFERENCES analytics_analysis_results(id) ON DELETE CASCADE,

    -- 리포트 데이터
    summary JSONB NOT NULL,
    meta JSONB DEFAULT '{}',

    -- 공유
    shared_url TEXT UNIQUE,
    is_public BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_reports_result ON analytics_bout_reports(result_id);
CREATE INDEX IF NOT EXISTS idx_analytics_reports_shared ON analytics_bout_reports(shared_url) WHERE shared_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_analytics_reports_public ON analytics_bout_reports(is_public) WHERE is_public = TRUE;

-- =============================================
-- 7. analytics_credits (회원별 크레딧 잔액)
-- =============================================
CREATE TABLE IF NOT EXISTS analytics_credits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL UNIQUE REFERENCES members(id) ON DELETE CASCADE,

    -- 잔액
    balance INT DEFAULT 0 CHECK (balance >= 0),
    total_earned INT DEFAULT 0,
    total_spent INT DEFAULT 0,

    -- 타임스탬프
    last_charged_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_credits_member ON analytics_credits(member_id);

-- Update trigger
DROP TRIGGER IF EXISTS update_analytics_credits_updated_at ON analytics_credits;
CREATE TRIGGER update_analytics_credits_updated_at
    BEFORE UPDATE ON analytics_credits
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================
-- 8. analytics_credit_transactions (크레딧 거래 내역)
-- =============================================
CREATE TABLE IF NOT EXISTS analytics_credit_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,

    -- 거래 정보
    amount INT NOT NULL,            -- 양수 = 충전, 음수 = 차감
    balance_after INT NOT NULL,     -- 거래 후 잔액
    transaction_type TEXT NOT NULL CHECK (transaction_type IN (
        'purchase',      -- 크레딧 구매
        'analysis',      -- 분석 차감
        'refund',        -- 환불
        'bonus',         -- 보너스 지급
        'subscription'   -- 구독 충전
    )),

    -- 참조
    reference_id UUID,              -- job_id 또는 subscription_id
    description TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_txn_member ON analytics_credit_transactions(member_id);
CREATE INDEX IF NOT EXISTS idx_analytics_txn_type ON analytics_credit_transactions(transaction_type);
CREATE INDEX IF NOT EXISTS idx_analytics_txn_created ON analytics_credit_transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_analytics_txn_reference ON analytics_credit_transactions(reference_id) WHERE reference_id IS NOT NULL;

-- =============================================
-- 9. RLS (Row Level Security) 정책
-- =============================================

-- analytics_videos RLS
ALTER TABLE analytics_videos ENABLE ROW LEVEL SECURITY;

CREATE POLICY "analytics_videos_select_own" ON analytics_videos
    FOR SELECT USING (
        member_id = (SELECT id FROM members WHERE supabase_auth_id = auth.uid())
    );

CREATE POLICY "analytics_videos_insert_own" ON analytics_videos
    FOR INSERT WITH CHECK (
        member_id = (SELECT id FROM members WHERE supabase_auth_id = auth.uid())
    );

CREATE POLICY "analytics_videos_update_own" ON analytics_videos
    FOR UPDATE USING (
        member_id = (SELECT id FROM members WHERE supabase_auth_id = auth.uid())
    );

-- analytics_analysis_jobs RLS
ALTER TABLE analytics_analysis_jobs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "analytics_jobs_select_own" ON analytics_analysis_jobs
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM analytics_videos v
            WHERE v.id = analytics_analysis_jobs.video_id
            AND v.member_id = (SELECT id FROM members WHERE supabase_auth_id = auth.uid())
        )
    );

CREATE POLICY "analytics_jobs_insert_own" ON analytics_analysis_jobs
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM analytics_videos v
            WHERE v.id = analytics_analysis_jobs.video_id
            AND v.member_id = (SELECT id FROM members WHERE supabase_auth_id = auth.uid())
        )
    );

-- analytics_analysis_results RLS
ALTER TABLE analytics_analysis_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY "analytics_results_select_own" ON analytics_analysis_results
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM analytics_analysis_jobs j
            JOIN analytics_videos v ON v.id = j.video_id
            WHERE j.id = analytics_analysis_results.job_id
            AND v.member_id = (SELECT id FROM members WHERE supabase_auth_id = auth.uid())
        )
    );

-- analytics_techniques RLS
ALTER TABLE analytics_techniques ENABLE ROW LEVEL SECURITY;

CREATE POLICY "analytics_techniques_select_own" ON analytics_techniques
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM analytics_analysis_results r
            JOIN analytics_analysis_jobs j ON j.id = r.job_id
            JOIN analytics_videos v ON v.id = j.video_id
            WHERE r.id = analytics_techniques.result_id
            AND v.member_id = (SELECT id FROM members WHERE supabase_auth_id = auth.uid())
        )
    );

-- analytics_player_metrics RLS
ALTER TABLE analytics_player_metrics ENABLE ROW LEVEL SECURITY;

CREATE POLICY "analytics_metrics_select_own" ON analytics_player_metrics
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM analytics_analysis_results r
            JOIN analytics_analysis_jobs j ON j.id = r.job_id
            JOIN analytics_videos v ON v.id = j.video_id
            WHERE r.id = analytics_player_metrics.result_id
            AND v.member_id = (SELECT id FROM members WHERE supabase_auth_id = auth.uid())
        )
    );

-- analytics_bout_reports RLS
ALTER TABLE analytics_bout_reports ENABLE ROW LEVEL SECURITY;

-- 본인 리포트 조회
CREATE POLICY "analytics_reports_select_own" ON analytics_bout_reports
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM analytics_analysis_results r
            JOIN analytics_analysis_jobs j ON j.id = r.job_id
            JOIN analytics_videos v ON v.id = j.video_id
            WHERE r.id = analytics_bout_reports.result_id
            AND v.member_id = (SELECT id FROM members WHERE supabase_auth_id = auth.uid())
        )
    );

-- 공개 리포트 누구나 조회
CREATE POLICY "analytics_reports_select_public" ON analytics_bout_reports
    FOR SELECT USING (is_public = TRUE);

-- analytics_credits RLS
ALTER TABLE analytics_credits ENABLE ROW LEVEL SECURITY;

CREATE POLICY "analytics_credits_select_own" ON analytics_credits
    FOR SELECT USING (
        member_id = (SELECT id FROM members WHERE supabase_auth_id = auth.uid())
    );

-- analytics_credit_transactions RLS
ALTER TABLE analytics_credit_transactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "analytics_txn_select_own" ON analytics_credit_transactions
    FOR SELECT USING (
        member_id = (SELECT id FROM members WHERE supabase_auth_id = auth.uid())
    );

-- =============================================
-- 10. 코멘트
-- =============================================
COMMENT ON TABLE analytics_videos IS '분석용 업로드 영상';
COMMENT ON TABLE analytics_analysis_jobs IS '영상 분석 작업 큐';
COMMENT ON TABLE analytics_analysis_results IS '분석 결과 (EnrichedMatchEvent[], MatchReport)';
COMMENT ON TABLE analytics_techniques IS '감지된 개별 기술 (비정규화 - 쿼리 최적화)';
COMMENT ON TABLE analytics_player_metrics IS '선수별 경기 지표';
COMMENT ON TABLE analytics_bout_reports IS '공유 가능 경기 리포트';
COMMENT ON TABLE analytics_credits IS '회원별 크레딧 잔액';
COMMENT ON TABLE analytics_credit_transactions IS '크레딧 거래 감사 내역';
