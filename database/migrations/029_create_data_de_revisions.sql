-- 029_create_data_de_revisions.sql
-- DE(대진표) 개정 이력 — 스키마 드리프트 정리 (2026-09-28)
--
-- 배경: 이 테이블은 이미 프로덕션 Supabase 에 존재한다(app/de_revisions.py 가
-- 실제로 쓰고 있음) 그런데 그것을 만든 마이그레이션 파일이 저장소 어디에도
-- 없었다 — 026_create_data_pool_revisions.sql 과 함께 만들었어야 할 짝이
-- 빠진 채로 직접 DB 에 적용된 것으로 보인다. 이 파일은 새 스키마를 만드는
-- 것이 아니라 **이미 존재하는 실제 스키마를 그대로 옮겨 적어 마이그레이션
-- 이력을 실제 상태와 일치시킨다**(CREATE TABLE IF NOT EXISTS 이므로 기존
-- 테이블에 안전하게 재적용된다. 컬럼 삭제/타입 변경 없음).
--
-- 설계는 026(data_pool_revisions)과 같다 — 풀이 아니라 DE(직결선) 대진표의
-- 개정을 추적한다는 점만 다르다:
--   roster_hash   누가 대진에 있는가 (선수 집합)
--   pairing_hash  누가 누구와, 어느 위상(de_phase)·라운드·경기번호에서 붙는가
-- 점수·승자는 어느 해시에도 넣지 않는다 — 경기 진행 중 점수는 계속 변하는데
-- 그건 대진 변경이 아니다.
--
-- de_phase(예선/본선)는 반드시 pairings/bracket_summary 안에 포함되어야 한다.
-- 예선 64강과 본선 64강은 다른 경기다(services/data/CLAUDE.md
-- "Dual DE: 예선 64강 ≠ 본선 64강" 참조) — 이 테이블 자체는 그 규약을 강제하지
-- 않으므로 기록하는 쪽(app/de_revisions.py)이 지켜야 한다.

CREATE TABLE IF NOT EXISTS data_de_revisions (
    id               BIGSERIAL PRIMARY KEY,
    event_id         INTEGER REFERENCES events(id) ON DELETE CASCADE,
    competition_id   INTEGER,
    sub_event_cd     VARCHAR(50)  NOT NULL,
    revision_no      INTEGER      NOT NULL,

    de_format        VARCHAR(20),                       -- 'single' | 'dual_de' 등
    bracket_summary  JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- {bracket_size, starting_round, ...}
    entrant_count    INTEGER      NOT NULL DEFAULT 0,    -- 대진표에 이름이 실린 선수 수
    bout_count       INTEGER      NOT NULL DEFAULT 0,    -- 실제 경기 수 (부전승 제외)

    roster_hash      VARCHAR(64)  NOT NULL,
    pairing_hash     VARCHAR(64)  NOT NULL,

    -- 이 개정 시점의 대진 스냅샷 — 다음 개정의 diff 기준 (data_pool_revisions.layout과 같은 역할)
    pairings         JSONB,

    -- 직전 개정 대비 차이 (revision_no = 1 이면 전부 비어 있음). 표본 상한이 있으므로
    -- 실제 인원수는 *_count 컬럼을 쓸 것 — 목록 길이를 개수로 읽지 말 것
    -- (data_pool_revisions 에서 실제로 겪은 사고, 026 참조).
    added_players    JSONB        NOT NULL DEFAULT '[]'::jsonb,  -- [{name, team, seed}]
    removed_players  JSONB        NOT NULL DEFAULT '[]'::jsonb,
    repaired         JSONB        NOT NULL DEFAULT '[]'::jsonb,  -- 대진은 그대로, 결과만 바뀐 bout
    added_count      INTEGER      NOT NULL DEFAULT 0,
    removed_count    INTEGER      NOT NULL DEFAULT 0,
    repaired_count   INTEGER      NOT NULL DEFAULT 0,
    roster_changed   BOOLEAN      NOT NULL DEFAULT FALSE,
    pairing_changed  BOOLEAN      NOT NULL DEFAULT FALSE,

    detected_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    source           VARCHAR(30)  NOT NULL DEFAULT 'scheduler',
    -- 'scheduler' = 자동 감지, 'backfill' = 도입 시점 스냅샷(최초 게시 시각 아님)
    note             TEXT,

    CONSTRAINT data_de_revisions_unique UNIQUE (sub_event_cd, revision_no)
);

CREATE INDEX IF NOT EXISTS idx_data_de_revisions_event
    ON data_de_revisions (sub_event_cd, revision_no DESC);
CREATE INDEX IF NOT EXISTS idx_data_de_revisions_comp
    ON data_de_revisions (competition_id, detected_at DESC);

COMMENT ON TABLE  data_de_revisions IS 'DE(직결선) 대진표 개정 이력 — 대진이 실제로 달라진 시점만 기록. 이 파일 자체는 026 직후 프로덕션에 직접 적용되고 마이그레이션 파일이 누락되어 있던 것을 2026-09-28 스키마 드리프트 점검으로 복원함';
COMMENT ON COLUMN data_de_revisions.roster_hash IS '대진 참가 선수 집합 해시 (점수 무관)';
COMMENT ON COLUMN data_de_revisions.pairing_hash IS '대진(누가 누구와, 어느 위상·라운드·경기번호) 해시 — 점수 무관';
COMMENT ON COLUMN data_de_revisions.source IS 'scheduler=자동감지, backfill=도입 시점 스냅샷(최초 게시 시각 아님)';
