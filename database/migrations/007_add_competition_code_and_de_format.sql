-- Migration 007: Add competition_code and DE format columns
-- Created: 2026-01-20
-- Purpose:
--   1. Add competition_code column to competitions table for new code system (e.g., KoNaB1Ya26Ja1422)
--   2. Add de_format column to events table to distinguish DE formats (normal, dual_de)
--   3. Add has_first_de and has_second_de boolean columns for Dual DE data tracking

-- ============================================================================
-- 1. competitions 테이블에 competition_code 컬럼 추가
-- ============================================================================
ALTER TABLE competitions
ADD COLUMN IF NOT EXISTS competition_code VARCHAR(20);

-- competition_code 컬럼 설명
COMMENT ON COLUMN competitions.competition_code IS 'New competition code system (e.g., KoNaB1Ya26Ja1422). Format: Country(2) + Level(2) + Type(2) + AgeGroup(2) + Year(2) + Month(2) + StartDay(2) + CompetitionNumber(2)';

-- competition_code 인덱스 생성 (유니크)
CREATE UNIQUE INDEX IF NOT EXISTS idx_competitions_competition_code
ON competitions(competition_code)
WHERE competition_code IS NOT NULL;

-- ============================================================================
-- 2. events 테이블에 de_format 컬럼 추가
-- ============================================================================
ALTER TABLE events
ADD COLUMN IF NOT EXISTS de_format VARCHAR(20) DEFAULT 'normal';

-- de_format 컬럼 설명
COMMENT ON COLUMN events.de_format IS 'DE format type: normal (standard single DE), dual_de (two-stage DE like Iksan International)';

-- ============================================================================
-- 3. events 테이블에 has_first_de, has_second_de 컬럼 추가
-- ============================================================================
ALTER TABLE events
ADD COLUMN IF NOT EXISTS has_first_de BOOLEAN DEFAULT FALSE;

ALTER TABLE events
ADD COLUMN IF NOT EXISTS has_second_de BOOLEAN DEFAULT FALSE;

-- 컬럼 설명
COMMENT ON COLUMN events.has_first_de IS 'Whether first DE bracket data exists (for dual_de format)';
COMMENT ON COLUMN events.has_second_de IS 'Whether second DE bracket data exists (for dual_de format)';

-- ============================================================================
-- 4. de_format 인덱스 생성 (필터링용)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_events_de_format
ON events(de_format);

-- ============================================================================
-- 5. Dual DE 이벤트 조회용 복합 인덱스
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_events_dual_de_status
ON events(de_format, has_first_de, has_second_de)
WHERE de_format = 'dual_de';
