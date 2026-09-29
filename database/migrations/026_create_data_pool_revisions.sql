-- 026_create_data_pool_revisions.sql
-- 풀(예선 조편성) 개정 이력
--
-- 배경: KFA 는 대회 직전 풀을 여러 차례 다시 올린다. 우리는 events.raw_data 를
-- 덮어쓰기만 해서 "몇 번 바뀌었는지"를 알 수 없었다(2026-08-27 확인:
-- data_events 0건, StateManager(use_db=False) 로 지문은 메모리에만 존재).
-- 이 표는 풀이 실제로 달라진 순간마다 한 행을 남긴다.
--
-- 왜 해시를 둘로 나누는가:
--   roster_hash  = 누가 참가하는가 (선수 집합)
--   layout_hash  = 누가 몇 번 풀인가 (배정)
-- 둘을 나눠야 "참가자가 빠져서 다시 돌린 것"과 "같은 인원인데 재추첨한 것"을
-- 구분할 수 있다. 점수(V/D)는 두 해시 어디에도 넣지 않는다 — 경기가 시작되면
-- 점수는 계속 변하는데 그건 조편성 변경이 아니다.

CREATE TABLE IF NOT EXISTS data_pool_revisions (
    id              BIGSERIAL PRIMARY KEY,
    event_id        INTEGER REFERENCES events(id) ON DELETE CASCADE,
    competition_id  INTEGER,
    sub_event_cd    VARCHAR(50)  NOT NULL,
    revision_no     INTEGER      NOT NULL,

    -- 이 개정 시점의 규모
    pool_count      INTEGER      NOT NULL DEFAULT 0,  -- 고유 풀 번호 수
    fencer_count    INTEGER      NOT NULL DEFAULT 0,  -- 풀에 배정된 선수 수
    entry_count     INTEGER,                          -- 같은 시점의 엔트리(신청) 수

    roster_hash     VARCHAR(64)  NOT NULL,
    layout_hash     VARCHAR(64)  NOT NULL,

    -- 직전 개정 대비 차이 (revision_no = 1 이면 전부 비어 있음)
    added_players   JSONB        NOT NULL DEFAULT '[]'::jsonb,  -- [{name, team, pool}]
    removed_players JSONB        NOT NULL DEFAULT '[]'::jsonb,
    moved_players   JSONB        NOT NULL DEFAULT '[]'::jsonb,  -- [{name, team, from, to}]
    roster_changed  BOOLEAN      NOT NULL DEFAULT FALSE,
    layout_changed  BOOLEAN      NOT NULL DEFAULT FALSE,

    detected_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    source          VARCHAR(30)  NOT NULL DEFAULT 'scheduler',
    -- 'scheduler' = 자동 감지, 'backfill' = 도입 시점 스냅샷(최초 게시 시각 아님)
    note            TEXT,

    CONSTRAINT data_pool_revisions_unique UNIQUE (sub_event_cd, revision_no)
);

CREATE INDEX IF NOT EXISTS idx_data_pool_revisions_event
    ON data_pool_revisions (sub_event_cd, revision_no DESC);
CREATE INDEX IF NOT EXISTS idx_data_pool_revisions_comp
    ON data_pool_revisions (competition_id, detected_at DESC);

COMMENT ON TABLE  data_pool_revisions IS '풀 조편성 개정 이력 — 조편성이 실제로 달라진 시점만 기록';
COMMENT ON COLUMN data_pool_revisions.roster_hash IS '참가 선수 집합 해시 (점수 무관)';
COMMENT ON COLUMN data_pool_revisions.layout_hash IS '풀 배정 해시 — 누가 몇 번 풀인지 (점수 무관)';
COMMENT ON COLUMN data_pool_revisions.source IS 'scheduler=자동감지, backfill=도입 시점 스냅샷(최초 게시 시각 아님)';

-- 2026-08-27 (같은 날 추가): 배정 스냅샷 컬럼
--
-- 도입 당일 김창환배 여자 플러레가 재추첨됐는데, 그 diff 를 캐시된 HTML 에서
-- 겨우 복원했다. 직전 조편성을 표에 들고 있지 않으면, raw_data 가 덮어써진 뒤에는
-- '누가 어디로 옮겼는지'를 영영 알 수 없다. 스케줄러 경로는 저장 직전 DB 값을
-- 갖고 있어 diff 가 되지만, 그 경로 밖에서 데이터가 바뀌면 그대로 유실된다.
ALTER TABLE data_pool_revisions
  ADD COLUMN IF NOT EXISTS layout JSONB;
COMMENT ON COLUMN data_pool_revisions.layout IS
  '이 개정 시점의 배정 스냅샷 [{n,t,p,s}] — 다음 개정의 diff 기준';

-- 2026-08-27 (같은 날 추가): 실제 변경 인원 컬럼
--
-- added/removed/moved_players 는 표본이다(상한 60). 첫 실기록인 여자 플러레
-- 재추첨에서 실제 78명이 움직였는데 목록 길이를 개수로 읽어 60으로 표시됐다.
-- 개수는 목록과 분리해서 들고 있어야 한다.
ALTER TABLE data_pool_revisions
  ADD COLUMN IF NOT EXISTS added_count   INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS removed_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS moved_count   INTEGER NOT NULL DEFAULT 0;
COMMENT ON COLUMN data_pool_revisions.moved_count IS
  '실제 이동 인원. moved_players 는 표본(상한 60)이라 길이를 개수로 쓰면 안 된다.';
