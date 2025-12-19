-- Supabase Migration: Add organizations table for address data
-- Version: 002
-- Created: 2025-12-18

-- =============================================
-- organizations (조직/팀) 테이블
-- =============================================
CREATE TABLE IF NOT EXISTS organizations (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,              -- 팀/조직명
    name_normalized VARCHAR(255),            -- 정규화된 이름 (검색용)
    org_type VARCHAR(50),                    -- 유형: club, elementary, middle, high, university, professional

    -- 주소 정보
    country VARCHAR(10) DEFAULT 'KO',        -- 국가코드
    province VARCHAR(50),                    -- 시도
    city VARCHAR(50),                        -- 시/군/구
    district VARCHAR(50),                    -- 구/동
    road_address VARCHAR(255),               -- 도로명주소
    detailed_address VARCHAR(255),           -- 세부주소
    postal_code VARCHAR(10),                 -- 우편번호
    latitude DECIMAL(10, 7),                 -- 위도
    longitude DECIMAL(10, 7),                -- 경도

    -- 연락처
    phone VARCHAR(50),
    email VARCHAR(255),
    website VARCHAR(500),

    -- 메타데이터
    address_source VARCHAR(50),              -- 주소 출처: neis, g1sports, manual, scraped
    address_verified BOOLEAN DEFAULT FALSE,  -- 검증 여부
    address_status VARCHAR(20) DEFAULT 'pending', -- pending, collected, failed, manual_required
    address_error TEXT,                      -- 오류 메시지 (수집 실패시)

    -- 추가 정보
    member_count INTEGER,
    founded_year INTEGER,
    raw_data JSONB,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(name)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_organizations_name ON organizations(name);
CREATE INDEX IF NOT EXISTS idx_organizations_name_normalized ON organizations(name_normalized);
CREATE INDEX IF NOT EXISTS idx_organizations_org_type ON organizations(org_type);
CREATE INDEX IF NOT EXISTS idx_organizations_province ON organizations(province);
CREATE INDEX IF NOT EXISTS idx_organizations_address_status ON organizations(address_status);

-- Update trigger
DROP TRIGGER IF EXISTS update_organizations_updated_at ON organizations;
CREATE TRIGGER update_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================
-- players 테이블에 organization_id 추가 (기존 team 컬럼 유지)
-- =============================================
ALTER TABLE players
ADD COLUMN IF NOT EXISTS organization_id BIGINT REFERENCES organizations(id);

CREATE INDEX IF NOT EXISTS idx_players_organization_id ON players(organization_id);
