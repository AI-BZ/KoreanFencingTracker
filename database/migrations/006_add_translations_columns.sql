-- Migration 006: Add translations JSONB columns for multi-language support
-- Created: 2025-01-09
-- Purpose: Support multi-language content for players, organizations, and competitions

-- 1. Players table
ALTER TABLE players ADD COLUMN IF NOT EXISTS translations JSONB DEFAULT '{}';
COMMENT ON COLUMN players.translations IS 'Multi-language translations: {"en": {"name": "Soyun Park", "verified": false}}';

-- 2. Organizations table
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS translations JSONB DEFAULT '{}';
COMMENT ON COLUMN organizations.translations IS 'Multi-language translations: {"en": {"name": "Choibyungchul Fencing Club", "verified": false}}';

-- 3. Competitions table
ALTER TABLE competitions ADD COLUMN IF NOT EXISTS translations JSONB DEFAULT '{}';
COMMENT ON COLUMN competitions.translations IS 'Multi-language translations: {"en": {"name": "President Cup National Championship", "verified": false}}';

-- 4. Create GIN indexes for efficient JSONB queries
CREATE INDEX IF NOT EXISTS idx_players_translations ON players USING gin (translations);
CREATE INDEX IF NOT EXISTS idx_organizations_translations ON organizations USING gin (translations);
CREATE INDEX IF NOT EXISTS idx_competitions_translations ON competitions USING gin (translations);
