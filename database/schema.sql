-- Korean Fencing Tracker - Supabase Schema
-- 대화형 AI 검색을 위한 데이터베이스 스키마

-- ==================== 기본 테이블 ====================

-- 대회 테이블
CREATE TABLE IF NOT EXISTS competitions (
    id SERIAL PRIMARY KEY,
    event_cd VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(500) NOT NULL,
    start_date DATE,
    end_date DATE,
    status VARCHAR(50),
    location VARCHAR(200),
    category VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 종목 테이블
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    competition_id INTEGER REFERENCES competitions(id) ON DELETE CASCADE,
    event_cd VARCHAR(50) NOT NULL,
    sub_event_cd VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    weapon VARCHAR(20),  -- 플러레, 에뻬, 사브르
    gender VARCHAR(10),  -- 남, 여, 혼성
    event_type VARCHAR(20),  -- 개인, 단체
    created_at TIMESTAMP DEFAULT NOW()
);

-- 선수 테이블 (정규화된 선수 정보)
CREATE TABLE IF NOT EXISTS players (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    team VARCHAR(200),
    birth_year INTEGER,
    main_weapon VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(name, team)  -- 동명이인 구분을 위해 소속팀 포함
);

-- 풀 라운드 결과
CREATE TABLE IF NOT EXISTS pool_results (
    id SERIAL PRIMARY KEY,
    event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
    player_id INTEGER REFERENCES players(id),
    pool_number INTEGER,
    rank INTEGER,
    win_rate DECIMAL(5,2),
    index_score INTEGER,
    touches_scored INTEGER,
    touches_received INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 본선(DE) 경기 결과
CREATE TABLE IF NOT EXISTS de_matches (
    id SERIAL PRIMARY KEY,
    event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
    round_name VARCHAR(50),  -- 64강, 32강, 16강, 8강, 준결승, 결승
    player1_id INTEGER REFERENCES players(id),
    player2_id INTEGER REFERENCES players(id),
    player1_score INTEGER,
    player2_score INTEGER,
    winner_id INTEGER REFERENCES players(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 최종 순위
CREATE TABLE IF NOT EXISTS final_rankings (
    id SERIAL PRIMARY KEY,
    event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
    player_id INTEGER REFERENCES players(id),
    rank INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ==================== 통계 뷰 ====================

-- 선수별 상대 전적 (라이벌 분석용)
CREATE OR REPLACE VIEW player_head_to_head AS
SELECT
    p1.id AS player_id,
    p1.name AS player_name,
    p1.team AS player_team,
    p2.id AS opponent_id,
    p2.name AS opponent_name,
    p2.team AS opponent_team,
    COUNT(*) AS total_matches,
    SUM(CASE WHEN m.winner_id = p1.id THEN 1 ELSE 0 END) AS wins,
    SUM(CASE WHEN m.winner_id = p2.id THEN 1 ELSE 0 END) AS losses,
    ROUND(
        SUM(CASE WHEN m.winner_id = p1.id THEN 1 ELSE 0 END)::DECIMAL /
        NULLIF(COUNT(*), 0) * 100, 1
    ) AS win_rate
FROM de_matches m
JOIN players p1 ON m.player1_id = p1.id OR m.player2_id = p1.id
JOIN players p2 ON (m.player1_id = p2.id OR m.player2_id = p2.id) AND p1.id != p2.id
WHERE m.winner_id IS NOT NULL
GROUP BY p1.id, p1.name, p1.team, p2.id, p2.name, p2.team
HAVING COUNT(*) >= 1;

-- 선수별 종합 통계
CREATE OR REPLACE VIEW player_stats AS
SELECT
    p.id,
    p.name,
    p.team,
    p.main_weapon,
    COUNT(DISTINCT fr.event_id) AS total_events,
    COUNT(CASE WHEN fr.rank = 1 THEN 1 END) AS gold_medals,
    COUNT(CASE WHEN fr.rank = 2 THEN 1 END) AS silver_medals,
    COUNT(CASE WHEN fr.rank = 3 THEN 1 END) AS bronze_medals,
    MIN(fr.rank) AS best_rank,
    ROUND(AVG(fr.rank), 1) AS avg_rank
FROM players p
LEFT JOIN final_rankings fr ON p.id = fr.player_id
GROUP BY p.id, p.name, p.team, p.main_weapon;

-- 선수별 무기별 성적
CREATE OR REPLACE VIEW player_weapon_stats AS
SELECT
    p.id AS player_id,
    p.name,
    e.weapon,
    COUNT(DISTINCT fr.event_id) AS events_count,
    MIN(fr.rank) AS best_rank,
    ROUND(AVG(fr.rank), 1) AS avg_rank,
    COUNT(CASE WHEN fr.rank <= 3 THEN 1 END) AS medal_count
FROM players p
JOIN final_rankings fr ON p.id = fr.player_id
JOIN events e ON fr.event_id = e.id
GROUP BY p.id, p.name, e.weapon;

-- ==================== 검색용 함수 ====================

-- 선수 검색 (이름 또는 소속팀)
CREATE OR REPLACE FUNCTION search_players(search_query TEXT)
RETURNS TABLE (
    id INTEGER,
    name VARCHAR,
    team VARCHAR,
    main_weapon VARCHAR,
    total_events BIGINT,
    medals BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id,
        p.name,
        p.team,
        p.main_weapon,
        COUNT(DISTINCT fr.event_id) AS total_events,
        COUNT(CASE WHEN fr.rank <= 3 THEN 1 END) AS medals
    FROM players p
    LEFT JOIN final_rankings fr ON p.id = fr.player_id
    WHERE p.name ILIKE '%' || search_query || '%'
       OR p.team ILIKE '%' || search_query || '%'
    GROUP BY p.id, p.name, p.team, p.main_weapon
    ORDER BY total_events DESC, medals DESC
    LIMIT 20;
END;
$$ LANGUAGE plpgsql;

-- 라이벌 찾기 (가장 많이 진 상대)
CREATE OR REPLACE FUNCTION find_rivals(target_player_id INTEGER, min_matches INTEGER DEFAULT 2)
RETURNS TABLE (
    opponent_id INTEGER,
    opponent_name VARCHAR,
    opponent_team VARCHAR,
    total_matches BIGINT,
    wins BIGINT,
    losses BIGINT,
    win_rate NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        h2h.opponent_id::INTEGER,
        h2h.opponent_name::VARCHAR,
        h2h.opponent_team::VARCHAR,
        h2h.total_matches,
        h2h.wins,
        h2h.losses,
        h2h.win_rate
    FROM player_head_to_head h2h
    WHERE h2h.player_id = target_player_id
      AND h2h.total_matches >= min_matches
    ORDER BY h2h.losses DESC, h2h.total_matches DESC
    LIMIT 10;
END;
$$ LANGUAGE plpgsql;

-- 동명이인 찾기
CREATE OR REPLACE FUNCTION find_same_name_players(player_name TEXT)
RETURNS TABLE (
    id INTEGER,
    name VARCHAR,
    team VARCHAR,
    main_weapon VARCHAR,
    recent_competition VARCHAR,
    total_events BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id,
        p.name,
        p.team,
        p.main_weapon,
        (
            SELECT c.name
            FROM final_rankings fr2
            JOIN events e2 ON fr2.event_id = e2.id
            JOIN competitions c ON e2.competition_id = c.id
            WHERE fr2.player_id = p.id
            ORDER BY c.start_date DESC
            LIMIT 1
        )::VARCHAR AS recent_competition,
        COUNT(DISTINCT fr.event_id) AS total_events
    FROM players p
    LEFT JOIN final_rankings fr ON p.id = fr.player_id
    WHERE p.name = player_name
    GROUP BY p.id, p.name, p.team, p.main_weapon
    ORDER BY total_events DESC;
END;
$$ LANGUAGE plpgsql;

-- ==================== 인덱스 ====================

CREATE INDEX IF NOT EXISTS idx_competitions_date ON competitions(start_date DESC);
CREATE INDEX IF NOT EXISTS idx_competitions_name ON competitions USING gin(to_tsvector('korean', name));
CREATE INDEX IF NOT EXISTS idx_events_weapon ON events(weapon);
CREATE INDEX IF NOT EXISTS idx_events_gender ON events(gender);
CREATE INDEX IF NOT EXISTS idx_players_name ON players(name);
CREATE INDEX IF NOT EXISTS idx_players_team ON players(team);
CREATE INDEX IF NOT EXISTS idx_final_rankings_player ON final_rankings(player_id);
CREATE INDEX IF NOT EXISTS idx_de_matches_players ON de_matches(player1_id, player2_id);
