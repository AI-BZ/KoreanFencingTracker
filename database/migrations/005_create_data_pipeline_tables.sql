-- ====================================================
-- 데이터 파이프라인 테이블
-- Migration: 005
-- Date: 2025-12-25
-- Description: 4단계 데이터 파이프라인 지원 테이블
-- ====================================================

-- 1. 데이터 이벤트 테이블 (Event-Driven Architecture)
CREATE TABLE IF NOT EXISTS data_events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id INTEGER,
    data JSONB,
    old_data JSONB,
    source VARCHAR(100) DEFAULT 'data_pipeline',
    correlation_id UUID,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_data_events_event_type ON data_events(event_type);
CREATE INDEX IF NOT EXISTS idx_data_events_entity ON data_events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_data_events_correlation ON data_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_data_events_created ON data_events(created_at);

-- 2. 검증 로그 테이블 (Validation Logs)
CREATE TABLE IF NOT EXISTS validation_logs (
    id BIGSERIAL PRIMARY KEY,
    data_type VARCHAR(50) NOT NULL,
    data JSONB NOT NULL,
    errors JSONB,
    warnings JSONB,
    is_valid BOOLEAN DEFAULT FALSE,
    stage VARCHAR(20),  -- 'technical' or 'business'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_validation_logs_type ON validation_logs(data_type);
CREATE INDEX IF NOT EXISTS idx_validation_logs_valid ON validation_logs(is_valid);
CREATE INDEX IF NOT EXISTS idx_validation_logs_created ON validation_logs(created_at);

-- 3. 동기화 로그 테이블 (Sync Logs)
CREATE TABLE IF NOT EXISTS sync_logs (
    id BIGSERIAL PRIMARY KEY,
    source VARCHAR(100) NOT NULL,
    synced_tables JSONB,
    errors JSONB,
    affected_count INTEGER DEFAULT 0,
    duration_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_sync_logs_source ON sync_logs(source);
CREATE INDEX IF NOT EXISTS idx_sync_logs_created ON sync_logs(created_at);

-- 4. 품질 메트릭 테이블 (Quality Metrics)
CREATE TABLE IF NOT EXISTS quality_metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_type VARCHAR(100) NOT NULL,
    value DECIMAL(10, 4) NOT NULL,
    threshold DECIMAL(10, 4),
    is_healthy BOOLEAN DEFAULT TRUE,
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_quality_metrics_type ON quality_metrics(metric_type);
CREATE INDEX IF NOT EXISTS idx_quality_metrics_healthy ON quality_metrics(is_healthy);
CREATE INDEX IF NOT EXISTS idx_quality_metrics_created ON quality_metrics(created_at);

-- 5. 품질 알림 테이블 (Quality Alerts)
CREATE TABLE IF NOT EXISTS quality_alerts (
    id BIGSERIAL PRIMARY KEY,
    severity VARCHAR(20) NOT NULL,  -- info, warning, error, critical
    title VARCHAR(200) NOT NULL,
    message TEXT,
    metric_type VARCHAR(100),
    metric_value DECIMAL(10, 4),
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by VARCHAR(100),
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_quality_alerts_severity ON quality_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_quality_alerts_ack ON quality_alerts(acknowledged);
CREATE INDEX IF NOT EXISTS idx_quality_alerts_created ON quality_alerts(created_at);

-- 6. 파이프라인 실행 로그 (Pipeline Runs)
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL UNIQUE,
    data_type VARCHAR(50) NOT NULL,
    source_url TEXT,
    status VARCHAR(20) NOT NULL,  -- running, completed, failed
    total_processed INTEGER DEFAULT 0,
    total_passed INTEGER DEFAULT 0,
    total_failed INTEGER DEFAULT 0,
    total_warnings INTEGER DEFAULT 0,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_type ON pipeline_runs(data_type);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started ON pipeline_runs(started_at);

-- 7. 원본 데이터 메타데이터 테이블 (Raw Data Metadata)
CREATE TABLE IF NOT EXISTS raw_data_metadata (
    id BIGSERIAL PRIMARY KEY,
    scrape_id UUID NOT NULL UNIQUE,
    source_url TEXT NOT NULL,
    content_type VARCHAR(20) NOT NULL,
    content_length INTEGER,
    file_path TEXT,
    processed BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMP WITH TIME ZONE,
    scraped_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_raw_data_scrape_id ON raw_data_metadata(scrape_id);
CREATE INDEX IF NOT EXISTS idx_raw_data_processed ON raw_data_metadata(processed);
CREATE INDEX IF NOT EXISTS idx_raw_data_scraped ON raw_data_metadata(scraped_at);

-- 8. players 테이블에 검증 관련 컬럼 추가
ALTER TABLE players 
    ADD COLUMN IF NOT EXISTS validated_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS validation_version VARCHAR(20),
    ADD COLUMN IF NOT EXISTS has_warnings BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS warnings JSONB,
    ADD COLUMN IF NOT EXISTS merged_into INTEGER REFERENCES players(id),
    ADD COLUMN IF NOT EXISTS split_from INTEGER REFERENCES players(id),
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_players_active ON players(is_active);
CREATE INDEX IF NOT EXISTS idx_players_merged ON players(merged_into);

-- 9. matches 테이블에 검증 관련 컬럼 추가
ALTER TABLE matches 
    ADD COLUMN IF NOT EXISTS validated_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS validation_version VARCHAR(20),
    ADD COLUMN IF NOT EXISTS has_warnings BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS warnings JSONB;

-- 10. events 테이블에 집계 컬럼 추가
ALTER TABLE events 
    ADD COLUMN IF NOT EXISTS match_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS validated_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS validation_version VARCHAR(20);

-- 11. competitions 테이블에 집계 컬럼 추가
ALTER TABLE competitions 
    ADD COLUMN IF NOT EXISTS event_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS validated_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS validation_version VARCHAR(20);

-- 12. 데이터 정리를 위한 함수: 오래된 로그 정리
CREATE OR REPLACE FUNCTION cleanup_old_logs(days_to_keep INTEGER DEFAULT 30)
RETURNS TABLE(
    deleted_events BIGINT,
    deleted_validation_logs BIGINT,
    deleted_sync_logs BIGINT,
    deleted_metrics BIGINT
) AS $$
DECLARE
    cutoff_date TIMESTAMP WITH TIME ZONE;
    d_events BIGINT;
    d_validation BIGINT;
    d_sync BIGINT;
    d_metrics BIGINT;
BEGIN
    cutoff_date := NOW() - (days_to_keep || ' days')::INTERVAL;
    
    DELETE FROM data_events WHERE created_at < cutoff_date;
    GET DIAGNOSTICS d_events = ROW_COUNT;
    
    DELETE FROM validation_logs WHERE created_at < cutoff_date;
    GET DIAGNOSTICS d_validation = ROW_COUNT;
    
    DELETE FROM sync_logs WHERE created_at < cutoff_date;
    GET DIAGNOSTICS d_sync = ROW_COUNT;
    
    DELETE FROM quality_metrics WHERE created_at < cutoff_date;
    GET DIAGNOSTICS d_metrics = ROW_COUNT;
    
    RETURN QUERY SELECT d_events, d_validation, d_sync, d_metrics;
END;
$$ LANGUAGE plpgsql;

-- 13. 참조 무결성 점검 함수
CREATE OR REPLACE FUNCTION check_referential_integrity()
RETURNS TABLE(
    check_name TEXT,
    source_table TEXT,
    target_table TEXT,
    orphan_count BIGINT
) AS $$
BEGIN
    -- matches.player1_id → players.id
    RETURN QUERY
    SELECT 
        'player1_reference'::TEXT,
        'matches'::TEXT,
        'players'::TEXT,
        COUNT(*)::BIGINT
    FROM matches m
    LEFT JOIN players p ON m.player1_id = p.id
    WHERE m.player1_id IS NOT NULL AND p.id IS NULL;
    
    -- matches.player2_id → players.id
    RETURN QUERY
    SELECT 
        'player2_reference'::TEXT,
        'matches'::TEXT,
        'players'::TEXT,
        COUNT(*)::BIGINT
    FROM matches m
    LEFT JOIN players p ON m.player2_id = p.id
    WHERE m.player2_id IS NOT NULL AND p.id IS NULL;
    
    -- matches.event_id → events.id
    RETURN QUERY
    SELECT 
        'event_reference'::TEXT,
        'matches'::TEXT,
        'events'::TEXT,
        COUNT(*)::BIGINT
    FROM matches m
    LEFT JOIN events e ON m.event_id = e.id
    WHERE m.event_id IS NOT NULL AND e.id IS NULL;
    
    -- events.competition_id → competitions.id
    RETURN QUERY
    SELECT 
        'competition_reference'::TEXT,
        'events'::TEXT,
        'competitions'::TEXT,
        COUNT(*)::BIGINT
    FROM events e
    LEFT JOIN competitions c ON e.competition_id = c.id
    WHERE e.competition_id IS NOT NULL AND c.id IS NULL;
    
    -- rankings.player_id → players.id
    RETURN QUERY
    SELECT 
        'ranking_player_reference'::TEXT,
        'rankings'::TEXT,
        'players'::TEXT,
        COUNT(*)::BIGINT
    FROM rankings r
    LEFT JOIN players p ON r.player_id = p.id
    WHERE r.player_id IS NOT NULL AND p.id IS NULL;
END;
$$ LANGUAGE plpgsql;

-- 코멘트 추가
COMMENT ON TABLE data_events IS '데이터 변경 이벤트 로그 - Event-Driven Architecture';
COMMENT ON TABLE validation_logs IS '데이터 검증 실패/경고 로그';
COMMENT ON TABLE sync_logs IS '데이터 동기화 로그';
COMMENT ON TABLE quality_metrics IS '데이터 품질 메트릭';
COMMENT ON TABLE quality_alerts IS '데이터 품질 알림';
COMMENT ON TABLE pipeline_runs IS '파이프라인 실행 이력';
COMMENT ON TABLE raw_data_metadata IS '원본 스크래핑 데이터 메타데이터';
COMMENT ON FUNCTION cleanup_old_logs IS '오래된 로그 데이터 정리 (기본 30일)';
COMMENT ON FUNCTION check_referential_integrity IS '참조 무결성 점검';

