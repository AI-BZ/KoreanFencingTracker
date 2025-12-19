-- Supabase Migration: Members System Tables
-- Version: 003
-- Created: 2025-12-18
-- Description: 회원 시스템 (members, verifications, oauth_connections)

-- =============================================
-- members 테이블 (회원 정보)
-- =============================================
CREATE TABLE IF NOT EXISTS members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    supabase_auth_id UUID UNIQUE,  -- Supabase Auth 연동

    -- 기본 정보
    full_name VARCHAR(100) NOT NULL,
    display_name VARCHAR(100),  -- 공개용 이름 (영어 이니셜: H.G.D.)
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(20),
    birth_date DATE,

    -- 회원 유형
    member_type VARCHAR(30) NOT NULL CHECK (member_type IN (
        'player',           -- 선수회원
        'player_parent',    -- 선수 부모회원
        'club_coach',       -- 클럽 코치
        'school_coach',     -- 학교 코치
        'general'           -- 일반 회원
    )),

    -- 연결
    player_id BIGINT REFERENCES players(id),
    organization_id BIGINT REFERENCES organizations(id),
    guardian_member_id UUID REFERENCES members(id),  -- 미성년자의 보호자

    -- 인증 상태
    verification_status VARCHAR(20) DEFAULT 'pending' CHECK (verification_status IN (
        'pending',      -- 인증 대기
        'submitted',    -- 인증 제출됨
        'verified',     -- 인증 완료
        'rejected',     -- 인증 거부
        'expired'       -- 인증 만료
    )),
    verified_at TIMESTAMPTZ,

    -- 개인정보 설정
    privacy_public BOOLEAN DEFAULT FALSE,  -- 대중 공개 여부
    marketing_consent BOOLEAN DEFAULT FALSE,
    promotional_consent BOOLEAN DEFAULT FALSE,  -- X 등 홍보 계정 연동 동의

    -- 메타
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_members_email ON members(email);
CREATE INDEX IF NOT EXISTS idx_members_member_type ON members(member_type);
CREATE INDEX IF NOT EXISTS idx_members_player_id ON members(player_id);
CREATE INDEX IF NOT EXISTS idx_members_organization_id ON members(organization_id);
CREATE INDEX IF NOT EXISTS idx_members_verification_status ON members(verification_status);
CREATE INDEX IF NOT EXISTS idx_members_guardian ON members(guardian_member_id);

-- Update trigger
DROP TRIGGER IF EXISTS update_members_updated_at ON members;
CREATE TRIGGER update_members_updated_at
    BEFORE UPDATE ON members
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================
-- verifications 테이블 (인증 기록)
-- =============================================
CREATE TABLE IF NOT EXISTS verifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,

    -- 인증 유형
    verification_type VARCHAR(30) NOT NULL CHECK (verification_type IN (
        'association_card',  -- 협회 등록증
        'mask_photo',        -- 마스크 + 이름 + 날짜 종이
        'uniform_photo'      -- 도복 + 이름 + 날짜 종이
    )),

    -- 파일 정보
    image_url TEXT NOT NULL,
    image_storage_path TEXT NOT NULL,

    -- Gemini API 결과
    gemini_response JSONB,
    gemini_confidence DECIMAL(3,2),  -- 0.00 ~ 1.00
    extracted_name TEXT,
    extracted_date DATE,
    extracted_organization TEXT,

    -- 상태
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN (
        'pending',      -- 처리 대기
        'processing',   -- 처리 중
        'approved',     -- 승인
        'rejected',     -- 거부
        'error'         -- 오류
    )),
    rejection_reason TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_verifications_member_id ON verifications(member_id);
CREATE INDEX IF NOT EXISTS idx_verifications_status ON verifications(status);
CREATE INDEX IF NOT EXISTS idx_verifications_type ON verifications(verification_type);

-- =============================================
-- oauth_connections 테이블 (OAuth 연결)
-- =============================================
CREATE TABLE IF NOT EXISTS oauth_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,

    provider VARCHAR(20) NOT NULL CHECK (provider IN ('kakao', 'google', 'x')),
    provider_user_id TEXT NOT NULL,
    provider_email TEXT,
    provider_name TEXT,

    -- 용도
    is_primary BOOLEAN DEFAULT FALSE,
    for_promotional BOOLEAN DEFAULT FALSE,  -- X 홍보용

    -- 토큰 (암호화 저장)
    access_token_encrypted TEXT,
    refresh_token_encrypted TEXT,
    token_expires_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(provider, provider_user_id)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_oauth_member_id ON oauth_connections(member_id);
CREATE INDEX IF NOT EXISTS idx_oauth_provider ON oauth_connections(provider);

-- Update trigger
DROP TRIGGER IF EXISTS update_oauth_updated_at ON oauth_connections;
CREATE TRIGGER update_oauth_updated_at
    BEFORE UPDATE ON oauth_connections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================
-- 미성년자 보호 함수 (14세 미만은 보호자 필수)
-- =============================================
CREATE OR REPLACE FUNCTION check_minor_guardian()
RETURNS TRIGGER AS $$
BEGIN
    -- 14세 미만 선수는 보호자 필수
    IF NEW.birth_date IS NOT NULL AND
       DATE_PART('year', AGE(NEW.birth_date)) < 14 AND
       NEW.guardian_member_id IS NULL AND
       NEW.member_type = 'player' THEN
        RAISE EXCEPTION '14세 미만 선수는 보호자 등록이 필수입니다 (Under 14 players require a guardian)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_minor_guardian ON members;
CREATE TRIGGER enforce_minor_guardian
    BEFORE INSERT OR UPDATE ON members
    FOR EACH ROW EXECUTE FUNCTION check_minor_guardian();

-- =============================================
-- 이름 마스킹 함수 (홍길동 → H.G.D.)
-- =============================================
CREATE OR REPLACE FUNCTION mask_korean_name(full_name TEXT)
RETURNS TEXT AS $$
DECLARE
    char_code INTEGER;
    cho_index INTEGER;
    result TEXT := '';
    i INTEGER;
    char_val TEXT;
    -- 초성 → 영어 매핑
    chosung_en TEXT[] := ARRAY['G','KK','N','D','DD','R','M','B','BB','S','SS','','J','JJ','CH','K','T','P','H'];
BEGIN
    IF full_name IS NULL OR full_name = '' THEN
        RETURN '';
    END IF;

    FOR i IN 1..LENGTH(full_name) LOOP
        char_val := SUBSTRING(full_name FROM i FOR 1);
        char_code := ASCII(char_val);

        -- 한글 범위 (가=44032, 힣=55203)
        IF char_code >= 44032 AND char_code <= 55203 THEN
            cho_index := ((char_code - 44032) / 588) + 1;
            IF cho_index >= 1 AND cho_index <= 19 THEN
                IF chosung_en[cho_index] != '' THEN
                    result := result || SUBSTRING(chosung_en[cho_index] FROM 1 FOR 1) || '.';
                END IF;
            END IF;
        ELSIF char_val ~ '[A-Za-z]' THEN
            -- 영문은 첫 글자만
            result := result || UPPER(SUBSTRING(char_val FROM 1 FOR 1)) || '.';
        END IF;
    END LOOP;

    RETURN result;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- =============================================
-- 소속 익명화 함수 (최병철펜싱클럽 → 서울(클럽))
-- =============================================
CREATE OR REPLACE FUNCTION anonymize_team(
    org_type TEXT,
    province TEXT
)
RETURNS TEXT AS $$
DECLARE
    type_label TEXT;
BEGIN
    -- 유형 라벨
    type_label := CASE org_type
        WHEN 'club' THEN '클럽'
        WHEN 'elementary' THEN '초등학교'
        WHEN 'middle' THEN '중학교'
        WHEN 'high' THEN '고등학교'
        WHEN 'university' THEN '대학교'
        WHEN 'professional' THEN '실업팀'
        ELSE '기타'
    END;

    RETURN COALESCE(province, '전국') || '(' || type_label || ')';
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- =============================================
-- 공개용 선수 뷰 (개인정보 마스킹 적용)
-- =============================================
CREATE OR REPLACE VIEW public_player_view AS
SELECT
    p.id,
    p.name AS original_name,
    CASE
        WHEN m.privacy_public = TRUE THEN p.name
        ELSE mask_korean_name(p.name)
    END AS display_name,
    CASE
        WHEN m.privacy_public = TRUE THEN p.team
        ELSE anonymize_team(o.org_type, o.province)
    END AS display_team,
    p.weapon,
    p.created_at,
    m.id AS member_id,
    m.privacy_public
FROM players p
LEFT JOIN members m ON m.player_id = p.id
LEFT JOIN organizations o ON p.organization_id = o.id;

-- =============================================
-- RLS (Row Level Security) 정책
-- =============================================

-- members 테이블 RLS 활성화
ALTER TABLE members ENABLE ROW LEVEL SECURITY;

-- 본인 정보 조회 정책
CREATE POLICY "members_select_self" ON members
    FOR SELECT USING (
        auth.uid() = supabase_auth_id OR
        privacy_public = TRUE
    );

-- 본인 정보 수정 정책
CREATE POLICY "members_update_self" ON members
    FOR UPDATE USING (auth.uid() = supabase_auth_id);

-- 회원가입 정책 (인증된 사용자)
CREATE POLICY "members_insert_authenticated" ON members
    FOR INSERT WITH CHECK (auth.uid() IS NOT NULL);

-- verifications 테이블 RLS 활성화
ALTER TABLE verifications ENABLE ROW LEVEL SECURITY;

-- 본인 인증 조회 정책
CREATE POLICY "verifications_select_self" ON verifications
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.id = verifications.member_id
            AND m.supabase_auth_id = auth.uid()
        )
    );

-- 본인 인증 생성 정책
CREATE POLICY "verifications_insert_self" ON verifications
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.id = verifications.member_id
            AND m.supabase_auth_id = auth.uid()
        )
    );

-- oauth_connections 테이블 RLS 활성화
ALTER TABLE oauth_connections ENABLE ROW LEVEL SECURITY;

-- 본인 OAuth 조회 정책
CREATE POLICY "oauth_select_self" ON oauth_connections
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.id = oauth_connections.member_id
            AND m.supabase_auth_id = auth.uid()
        )
    );

-- 본인 OAuth 관리 정책
CREATE POLICY "oauth_manage_self" ON oauth_connections
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM members m
            WHERE m.id = oauth_connections.member_id
            AND m.supabase_auth_id = auth.uid()
        )
    );
