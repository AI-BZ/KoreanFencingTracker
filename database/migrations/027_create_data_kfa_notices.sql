-- 027_create_data_kfa_notices.sql
-- 대한펜싱협회 공지사항 아카이브 + 협회 발표 명단(국가대표·후보·교체·파견)
--
-- 배경: 국가대표 선발·교체·후보선수·합산 랭킹은 대회 결과 페이지가 아니라
-- 협회 공지사항 게시판(/board/list?code=notice)의 첨부(PDF/HWP)로만 공개된다.
-- 지금까지는 사람이 게시판을 보고 알아야 했고, 명단은 어디에도 구조화되어 있지
-- 않아 선수 프로필에 "국가대표" 배지를 달 근거가 없었다.
--
-- data_kfa_notices : 게시판 행 단위 아카이브. 첨부 원본은 data/kfa_notices/ 에
--                    파일로 보관하되 코드는 그 파일을 읽지 않는다 — 추출한 텍스트는
--                    attachments[].text 컬럼에 들어 있고 파서는 이 컬럼만 본다.
-- data_kfa_rosters : 첨부에서 구조화한 명단. 프로필 배지의 유일한 데이터 원천.
--                    협회 공지가 아닌 언론·SNS 확인분은 source_type='media' 로 구분.

CREATE TABLE IF NOT EXISTS data_kfa_notices (
    board_no        INTEGER      PRIMARY KEY,           -- 게시판 boardNo
    title           TEXT         NOT NULL,
    posted_at       DATE,                               -- 협회 표기 작성일
    url             TEXT         NOT NULL,
    body_text       TEXT,                               -- 본문 (태그 제거한 평문)
    is_pinned       BOOLEAN      NOT NULL DEFAULT FALSE, -- 목록 상단 고정 공지 여부

    -- 제목(+본문) 키워드 분류. 값 예:
    --   national_team | candidate_u25 | ranking_points | replacement | regulation
    --   dispatch | youth | kkumnamu | procurement | other
    tags            TEXT[]       NOT NULL DEFAULT '{}',

    -- [{name, url, local_path, kind(pdf|hwp|hwpx|image|other),
    --   text_extracted bool, text, extract_note}]
    -- text 는 PDF 페이지 경계를 \f(form feed) 로 구분해 저장한다 — 합산표처럼
    -- 페이지마다 머리글이 반복되는 문서는 페이지 단위로 파싱해야 한다.
    attachments     JSONB        NOT NULL DEFAULT '[]'::jsonb,

    first_seen_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    notified_at     TIMESTAMPTZ                          -- Discord 알림 발송 시각 (미발송 NULL)
);

CREATE INDEX IF NOT EXISTS idx_data_kfa_notices_posted
    ON data_kfa_notices (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_data_kfa_notices_tags
    ON data_kfa_notices USING GIN (tags);

COMMENT ON TABLE  data_kfa_notices IS '대한펜싱협회 공지사항 아카이브 (스케줄러 6시간 주기 수집)';
COMMENT ON COLUMN data_kfa_notices.tags IS '제목·본문 키워드 분류. 알림 허용목록은 scheduler/kfa_notice_monitor.py ALERT_TAGS';
COMMENT ON COLUMN data_kfa_notices.attachments IS '첨부 목록. text 는 추출 평문(페이지 구분 \f). local_path 는 보관용 — 코드는 읽지 않음';
COMMENT ON COLUMN data_kfa_notices.notified_at IS 'Discord 알림 발송 시각. 백필분·미알림 태그는 NULL';


CREATE TABLE IF NOT EXISTS data_kfa_rosters (
    id               BIGSERIAL    PRIMARY KEY,
    roster_type      TEXT         NOT NULL CHECK (roster_type IN (
                         'national_team',              -- 국가대표 선발 명단
                         'national_team_replacement',  -- 결원 교체 선발
                         'candidate_u25',              -- 국가대표 후보선수 (25세 이하)
                         'u23',                        -- 23세 이하 대표선수
                         'asian_games_dispatch',       -- 아시안게임 파견
                         'youth',                      -- 청소년 대표선수
                         'kkumnamu'                    -- 꿈나무
                     )),
    year             INTEGER      NOT NULL,   -- 명단의 기준 연도 (교체는 교체 대상 명단의 연도)
    weapon           TEXT         NOT NULL CHECK (weapon IN ('foil', 'epee', 'sabre')),
    gender           TEXT         NOT NULL CHECK (gender IN ('남', '여')),
    player_name      TEXT         NOT NULL,
    team             TEXT,                    -- 공지 시점 소속 (협회 표기 그대로)
    seed_rank        INTEGER,                 -- 협회 합산 랭킹 순위 (같은 해 합산표에서 대조)
    source_board_no  INTEGER      REFERENCES data_kfa_notices(board_no) ON DELETE SET NULL,
    source_url       TEXT,
    source_type      TEXT         NOT NULL DEFAULT 'kfa' CHECK (source_type IN ('kfa', 'media')),
    announced_at     DATE,                    -- 공지일 (media 는 확인일)
    note             TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT data_kfa_rosters_unique UNIQUE (roster_type, year, weapon, gender, player_name)
);

CREATE INDEX IF NOT EXISTS idx_data_kfa_rosters_player
    ON data_kfa_rosters (player_name, year DESC);
CREATE INDEX IF NOT EXISTS idx_data_kfa_rosters_type_year
    ON data_kfa_rosters (roster_type, year, weapon, gender);

COMMENT ON TABLE  data_kfa_rosters IS '협회 발표 명단 (국가대표/후보/교체/파견). 프로필 배지의 데이터 원천';
COMMENT ON COLUMN data_kfa_rosters.year IS '명단 기준 연도. 교체(national_team_replacement)는 교체되는 명단의 연도 — 공지 연도가 아님';
COMMENT ON COLUMN data_kfa_rosters.seed_rank IS '협회 합산 랭킹 순위. 같은 해 합산 최종표에서 이름·종목으로 대조, 없으면 NULL';
COMMENT ON COLUMN data_kfa_rosters.source_type IS 'kfa=협회 공지 첨부에서 파싱, media=언론·SNS 확인 (협회 공지 미게시)';
