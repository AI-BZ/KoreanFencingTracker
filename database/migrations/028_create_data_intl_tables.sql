-- 028_create_data_intl_tables.sql
-- 국제 트랙: FIE 공식 랭킹 + 종합대회(아시안게임) 결과
--
-- 왜 별도 테이블인가: 협회 규정도 국내 4개 대회 점수와 FIE 랭킹 점수를 별도 축으로
-- 두고, 국제대회 파견은 FIE 랭킹만 쓴다. competitions/events 에 섞으면
-- ranking/calculator.py 가 국내 랭킹에 국제 결과를 집계할 위험이 있다.
-- 이 표들은 국내 랭킹 계산기가 읽지 않는다 (2026-09-27 확인).
--
-- 출처를 행마다 남긴다 (source_url, fetched_at). 저장하는 것은 순위·점수·스코어
-- 수치뿐이며 사진·텍스트·해설은 저장하지 않는다.

-- ─────────────────────────────────────────────────────────────
-- 1. FIE 공식 랭킹 (fie.org/athletes/detailed-ranking)
-- ─────────────────────────────────────────────────────────────
-- season 은 FIE 표기 그대로: 2027 = 2026/2027 시즌 (season_label 에 원문 보존).
-- 한 시즌·종목·성별 목록이 한 번에 갱신되므로, 갱신 시 같은 목록의 이전 행은
-- fetched_at 이 오래된 것을 지운다 (탈락한 선수가 남지 않게).
CREATE TABLE IF NOT EXISTS data_fie_rankings (
    id              BIGSERIAL PRIMARY KEY,
    season          INTEGER      NOT NULL,             -- FIE 시즌 표기 (2027 = 2026/27)
    season_label    VARCHAR(20),                       -- 페이지 원문 "2026/2027"
    category        VARCHAR(2)   NOT NULL DEFAULT 'S', -- S=시니어
    weapon          CHAR(1)      NOT NULL,             -- F/E/S
    gender          CHAR(1)      NOT NULL,             -- F/M
    fie_rank        INTEGER      NOT NULL,
    athlete_name    TEXT         NOT NULL,             -- FIE 표기 "OH Sanguk"
    country         CHAR(3)      NOT NULL,             -- IOC 코드
    points          NUMERIC(9,3),
    results         JSONB        NOT NULL DEFAULT '[]'::jsonb,
                    -- [{label:"05/10/25 Genève (SA)", points:26.0, discarded:false}] 점수가 있는 칸만
    total_ranked    INTEGER,                           -- 그 목록의 전체 인원
    player_name_ko  TEXT,                              -- players 매칭 결과 (없으면 NULL)
    player_id       INTEGER,                           -- 유일하게 특정될 때만
    fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    source_url      TEXT         NOT NULL,

    CONSTRAINT data_fie_rankings_unique
        UNIQUE (season, category, weapon, gender, athlete_name)
);

CREATE INDEX IF NOT EXISTS idx_data_fie_rankings_list
    ON data_fie_rankings (season, category, weapon, gender, fie_rank);
CREATE INDEX IF NOT EXISTS idx_data_fie_rankings_kor
    ON data_fie_rankings (country, season) WHERE country = 'KOR';
CREATE INDEX IF NOT EXISTS idx_data_fie_rankings_player
    ON data_fie_rankings (player_name_ko) WHERE player_name_ko IS NOT NULL;

COMMENT ON TABLE  data_fie_rankings IS 'FIE 공식 개인 랭킹 스냅샷 — 국내 랭킹과 별도 축. 국내 랭킹 계산기는 읽지 않는다';
COMMENT ON COLUMN data_fie_rankings.season IS 'FIE 시즌 표기. 2027 = 2026/2027 시즌';
COMMENT ON COLUMN data_fie_rankings.player_id IS 'players.id — 동명이인으로 특정 못 하면 NULL, player_name_ko 만 채움';

-- ─────────────────────────────────────────────────────────────
-- 2. 종합대회 종목 (아시안게임 등)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS data_intl_events (
    id              SERIAL PRIMARY KEY,
    games           VARCHAR(20)  NOT NULL,             -- 'AG2026'
    discipline      VARCHAR(10)  NOT NULL DEFAULT 'FEN',
    event_key       VARCHAR(40)  NOT NULL,             -- 'M.SABRE-------------'
    event_name      TEXT         NOT NULL,             -- "Men's Sabre Individual"
    event_name_ko   TEXT,                              -- '남자 사브르 개인'
    weapon          CHAR(1),                           -- F/E/S
    gender          CHAR(1),                           -- F/M
    is_team         BOOLEAN      NOT NULL DEFAULT FALSE,
    display_order   INTEGER,
    start_date      DATE,
    status          VARCHAR(20),                       -- 'official' | 'in_progress' | 'scheduled'
    source_url      TEXT         NOT NULL,
    fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT data_intl_events_unique UNIQUE (games, event_key)
);

COMMENT ON TABLE data_intl_events IS '종합대회(아시안게임 등) 펜싱 종목 — competitions/events 와 분리';

-- ─────────────────────────────────────────────────────────────
-- 3. 최종 순위 (개인은 선수, 단체는 팀 + 멤버 jsonb)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS data_intl_results (
    id              BIGSERIAL PRIMARY KEY,
    event_id        INTEGER      NOT NULL REFERENCES data_intl_events(id) ON DELETE CASCADE,
    reg_id          VARCHAR(40)  NOT NULL,             -- 결과 시스템의 참가자/팀 ID
    rank            INTEGER,
    rank_eq         BOOLEAN      NOT NULL DEFAULT FALSE, -- 동률 순위 (3T 등)
    athlete_name    TEXT         NOT NULL,             -- 단체전은 팀명(국가명)
    country         CHAR(3)      NOT NULL,
    birth_date      DATE,
    medal           VARCHAR(10),                       -- gold | silver | bronze | NULL
    is_team         BOOLEAN      NOT NULL DEFAULT FALSE,
    members         JSONB        NOT NULL DEFAULT '[]'::jsonb,
                    -- 단체전: [{name, reg_id, birth_date, player_name_ko, player_id}]
    irm             VARCHAR(10),                       -- 기권/실격 등 코드 (없으면 NULL)
    player_name_ko  TEXT,
    player_id       INTEGER,
    fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT data_intl_results_unique UNIQUE (event_id, reg_id)
);

CREATE INDEX IF NOT EXISTS idx_data_intl_results_event
    ON data_intl_results (event_id, rank);
CREATE INDEX IF NOT EXISTS idx_data_intl_results_kor
    ON data_intl_results (country) WHERE country = 'KOR';

-- ─────────────────────────────────────────────────────────────
-- 4. 경기(바우트): 풀 + 토너먼트
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS data_intl_bouts (
    id              BIGSERIAL PRIMARY KEY,
    event_id        INTEGER      NOT NULL REFERENCES data_intl_events(id) ON DELETE CASCADE,
    unit_key        VARCHAR(60)  NOT NULL,             -- 'W.EPEE--------------.R32-.000100--'
    phase_code      VARCHAR(40)  NOT NULL,             -- 'W.EPEE--------------.R32-' / '.GPA-'
    phase_desc      VARCHAR(80),                       -- 'Table of 32' / 'Round of Pool 1'
    phase_order     INTEGER,
    is_pool         BOOLEAN      NOT NULL DEFAULT FALSE,
    pool_no         INTEGER,
    home_name       TEXT,
    home_org        CHAR(3),
    home_score      INTEGER,
    away_name       TEXT,
    away_org        CHAR(3),
    away_score      INTEGER,
    winner          VARCHAR(4),                        -- 'home' | 'away' | NULL
    is_bye          BOOLEAN      NOT NULL DEFAULT FALSE,
    status          VARCHAR(20),
    bout_time       TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT data_intl_bouts_unique UNIQUE (event_id, unit_key)
);

CREATE INDEX IF NOT EXISTS idx_data_intl_bouts_event
    ON data_intl_bouts (event_id, phase_order, unit_key);
CREATE INDEX IF NOT EXISTS idx_data_intl_bouts_kor
    ON data_intl_bouts (event_id) WHERE home_org = 'KOR' OR away_org = 'KOR';

COMMENT ON TABLE data_intl_bouts IS '종합대회 경기 스코어 — 수치만 저장, 해설·사진 없음';
