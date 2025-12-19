-- Supabase Migration: Create tables for Korean Fencing Tracker
-- Version: 001
-- Created: 2025-12-16

-- Enable Row Level Security (optional)
-- ALTER TABLE table_name ENABLE ROW LEVEL SECURITY;

-- =============================================
-- 1. 대회 테이블 (competitions)
-- =============================================
CREATE TABLE IF NOT EXISTS competitions (
    id BIGSERIAL PRIMARY KEY,
    event_cd VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    start_date DATE,
    end_date DATE,
    status VARCHAR(50),
    location VARCHAR(255),
    category VARCHAR(100),
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_competitions_event_cd ON competitions(event_cd);
CREATE INDEX IF NOT EXISTS idx_competitions_start_date ON competitions(start_date);
CREATE INDEX IF NOT EXISTS idx_competitions_status ON competitions(status);

-- =============================================
-- 2. 종목 테이블 (events)
-- =============================================
CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    competition_id BIGINT REFERENCES competitions(id) ON DELETE CASCADE,
    event_cd VARCHAR(50) NOT NULL,
    sub_event_cd VARCHAR(50),
    name VARCHAR(255) NOT NULL,
    weapon VARCHAR(50),
    gender VARCHAR(20),
    event_type VARCHAR(50),
    age_group VARCHAR(50),
    total_participants INTEGER DEFAULT 0,
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(competition_id, event_cd, sub_event_cd)
);

CREATE INDEX IF NOT EXISTS idx_events_competition_id ON events(competition_id);
CREATE INDEX IF NOT EXISTS idx_events_sub_event_cd ON events(sub_event_cd);
CREATE INDEX IF NOT EXISTS idx_events_weapon ON events(weapon);
CREATE INDEX IF NOT EXISTS idx_events_gender ON events(gender);
CREATE INDEX IF NOT EXISTS idx_events_age_group ON events(age_group);

-- =============================================
-- 3. 선수 테이블 (players)
-- =============================================
CREATE TABLE IF NOT EXISTS players (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    team VARCHAR(255),
    birth_year INTEGER,
    nationality VARCHAR(50),
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name, team)
);

CREATE INDEX IF NOT EXISTS idx_players_name ON players(name);
CREATE INDEX IF NOT EXISTS idx_players_team ON players(team);

-- =============================================
-- 4. 풀 라운드 결과 테이블 (pool_results)
-- =============================================
CREATE TABLE IF NOT EXISTS pool_results (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT REFERENCES events(id) ON DELETE CASCADE,
    round_number INTEGER NOT NULL DEFAULT 1,
    pool_number INTEGER NOT NULL,
    piste VARCHAR(50),
    time VARCHAR(50),
    referee VARCHAR(255),
    results JSONB NOT NULL,  -- array of player results
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pool_results_event_id ON pool_results(event_id);

-- =============================================
-- 5. 토너먼트 결과 테이블 (tournament_results)
-- =============================================
CREATE TABLE IF NOT EXISTS tournament_results (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT REFERENCES events(id) ON DELETE CASCADE,
    round_name VARCHAR(100),  -- 64강, 32강, 16강, 8강, 준결승, 결승
    match_number INTEGER,
    player1_name VARCHAR(100),
    player1_team VARCHAR(255),
    player1_score INTEGER,
    player2_name VARCHAR(100),
    player2_team VARCHAR(255),
    player2_score INTEGER,
    winner_name VARCHAR(100),
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tournament_results_event_id ON tournament_results(event_id);

-- =============================================
-- 6. 최종 순위 테이블 (final_rankings)
-- =============================================
CREATE TABLE IF NOT EXISTS final_rankings (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT REFERENCES events(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    name VARCHAR(100) NOT NULL,
    team VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(event_id, rank, name)
);

CREATE INDEX IF NOT EXISTS idx_final_rankings_event_id ON final_rankings(event_id);
CREATE INDEX IF NOT EXISTS idx_final_rankings_name ON final_rankings(name);

-- =============================================
-- 7. 선수 랭킹 포인트 테이블 (player_rankings)
-- =============================================
CREATE TABLE IF NOT EXISTS player_rankings (
    id BIGSERIAL PRIMARY KEY,
    player_id BIGINT REFERENCES players(id) ON DELETE CASCADE,
    weapon VARCHAR(50) NOT NULL,
    gender VARCHAR(20) NOT NULL,
    age_group VARCHAR(50) NOT NULL,
    year INTEGER NOT NULL,
    points INTEGER DEFAULT 0,
    gold_count INTEGER DEFAULT 0,
    silver_count INTEGER DEFAULT 0,
    bronze_count INTEGER DEFAULT 0,
    competition_count INTEGER DEFAULT 0,
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(player_id, weapon, gender, age_group, year)
);

CREATE INDEX IF NOT EXISTS idx_player_rankings_composite ON player_rankings(weapon, gender, age_group, year);

-- =============================================
-- 8. 스크래핑 로그 테이블 (scrape_logs)
-- =============================================
CREATE TABLE IF NOT EXISTS scrape_logs (
    id BIGSERIAL PRIMARY KEY,
    scrape_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'running',
    competitions_processed INTEGER DEFAULT 0,
    events_processed INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- =============================================
-- Update trigger function
-- =============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply update triggers
DROP TRIGGER IF EXISTS update_competitions_updated_at ON competitions;
CREATE TRIGGER update_competitions_updated_at
    BEFORE UPDATE ON competitions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_events_updated_at ON events;
CREATE TRIGGER update_events_updated_at
    BEFORE UPDATE ON events
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_players_updated_at ON players;
CREATE TRIGGER update_players_updated_at
    BEFORE UPDATE ON players
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_player_rankings_updated_at ON player_rankings;
CREATE TRIGGER update_player_rankings_updated_at
    BEFORE UPDATE ON player_rankings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
