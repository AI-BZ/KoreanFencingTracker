-- 대한펜싱협회 경기결과 스크래핑 DB 스키마
-- Supabase SQL Editor에서 실행

-- 대회 테이블
CREATE TABLE IF NOT EXISTS competitions (
    id SERIAL PRIMARY KEY,
    comp_idx VARCHAR(50) UNIQUE NOT NULL,
    comp_name VARCHAR(255) NOT NULL,
    start_date DATE,
    end_date DATE,
    venue VARCHAR(255),
    status VARCHAR(20) DEFAULT 'unknown',  -- 예정/진행중/종료
    raw_data JSONB,  -- 원본 데이터 보관
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 종목 테이블
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    competition_id INT REFERENCES competitions(id) ON DELETE CASCADE,
    event_cd VARCHAR(50) NOT NULL,
    sub_event_cd VARCHAR(50),
    event_name VARCHAR(255),
    weapon VARCHAR(20),      -- 플뢰레/에페/사브르
    gender VARCHAR(10),      -- 남자/여자/혼성
    category VARCHAR(50),    -- 개인/단체
    age_group VARCHAR(50),   -- 시니어/주니어/카뎃 등
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(competition_id, event_cd, sub_event_cd)
);

-- 선수 테이블
CREATE TABLE IF NOT EXISTS players (
    id SERIAL PRIMARY KEY,
    player_name VARCHAR(100) NOT NULL,
    team_name VARCHAR(100),
    birth_year INT,
    nationality VARCHAR(50) DEFAULT 'KOR',
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(player_name, team_name)
);

-- 경기 결과 테이블
CREATE TABLE IF NOT EXISTS matches (
    id SERIAL PRIMARY KEY,
    event_id INT REFERENCES events(id) ON DELETE CASCADE,
    round_name VARCHAR(50),    -- 예선/32강/16강/8강/4강/결승 등
    group_name VARCHAR(50),    -- 조별리그 조 이름
    match_number INT,
    player1_id INT REFERENCES players(id),
    player1_name VARCHAR(100), -- 비정규화 (조회 편의)
    player1_score INT,
    player2_id INT REFERENCES players(id),
    player2_name VARCHAR(100), -- 비정규화
    player2_score INT,
    winner_id INT REFERENCES players(id),
    match_status VARCHAR(20),  -- V(승리)/A(기권)/F(기권패)/E(실격)/P(페널티)
    match_time TIMESTAMPTZ,
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 최종 순위 테이블
CREATE TABLE IF NOT EXISTS rankings (
    id SERIAL PRIMARY KEY,
    event_id INT REFERENCES events(id) ON DELETE CASCADE,
    player_id INT REFERENCES players(id),
    player_name VARCHAR(100), -- 비정규화
    team_name VARCHAR(100),   -- 비정규화
    rank_position INT NOT NULL,
    match_count INT DEFAULT 0,
    win_count INT DEFAULT 0,
    loss_count INT DEFAULT 0,
    points INT DEFAULT 0,
    raw_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(event_id, player_id)
);

-- 스크래핑 로그 테이블
CREATE TABLE IF NOT EXISTS scrape_logs (
    id SERIAL PRIMARY KEY,
    scrape_type VARCHAR(50) NOT NULL,  -- full_sync/incremental/manual
    status VARCHAR(20) NOT NULL,        -- running/completed/failed
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    competitions_processed INT DEFAULT 0,
    events_processed INT DEFAULT 0,
    matches_processed INT DEFAULT 0,
    error_message TEXT,
    raw_data JSONB
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_competitions_date ON competitions(start_date DESC);
CREATE INDEX IF NOT EXISTS idx_competitions_status ON competitions(status);
CREATE INDEX IF NOT EXISTS idx_events_competition ON events(competition_id);
CREATE INDEX IF NOT EXISTS idx_events_weapon ON events(weapon);
CREATE INDEX IF NOT EXISTS idx_matches_event ON matches(event_id);
CREATE INDEX IF NOT EXISTS idx_matches_player1 ON matches(player1_id);
CREATE INDEX IF NOT EXISTS idx_matches_player2 ON matches(player2_id);
CREATE INDEX IF NOT EXISTS idx_rankings_event ON rankings(event_id);
CREATE INDEX IF NOT EXISTS idx_rankings_position ON rankings(rank_position);
CREATE INDEX IF NOT EXISTS idx_players_name ON players(player_name);
CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_name);

-- updated_at 자동 업데이트 트리거 함수
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 각 테이블에 트리거 적용
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

DROP TRIGGER IF EXISTS update_matches_updated_at ON matches;
CREATE TRIGGER update_matches_updated_at
    BEFORE UPDATE ON matches
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_rankings_updated_at ON rankings;
CREATE TRIGGER update_rankings_updated_at
    BEFORE UPDATE ON rankings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Row Level Security (RLS) 활성화 (선택사항)
-- ALTER TABLE competitions ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE events ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE players ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE matches ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE rankings ENABLE ROW LEVEL SECURITY;

-- 공개 읽기 정책 (선택사항)
-- CREATE POLICY "Public read access" ON competitions FOR SELECT USING (true);
-- CREATE POLICY "Public read access" ON events FOR SELECT USING (true);
-- CREATE POLICY "Public read access" ON players FOR SELECT USING (true);
-- CREATE POLICY "Public read access" ON matches FOR SELECT USING (true);
-- CREATE POLICY "Public read access" ON rankings FOR SELECT USING (true);

COMMENT ON TABLE competitions IS '대한펜싱협회 대회 정보';
COMMENT ON TABLE events IS '대회 내 종목 정보 (무기, 성별, 연령대별)';
COMMENT ON TABLE players IS '선수 정보';
COMMENT ON TABLE matches IS '개별 경기 결과';
COMMENT ON TABLE rankings IS '종목별 최종 순위';
COMMENT ON TABLE scrape_logs IS '스크래핑 실행 로그';
