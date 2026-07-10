-- Migration 011: Messenger Providers
-- 국가별 메신저 프로바이더 설정 테이블
-- 한국=카카오톡, 일본=LINE 등 국가별 메신저를 DB config로 관리

-- 1. messenger_providers 테이블
CREATE TABLE IF NOT EXISTS messenger_providers (
    country_code VARCHAR(2) PRIMARY KEY,        -- ISO 국가코드: "KR", "JP", "TW"
    provider VARCHAR(20) NOT NULL,              -- oauth_connections.provider와 동일값
    display_name_ko VARCHAR(50) NOT NULL,
    display_name_en VARCHAR(50) NOT NULL,
    icon VARCHAR(10) DEFAULT '',
    required_scopes TEXT[] NOT NULL DEFAULT '{}', -- 메시징에 필요한 추가 OAuth scope
    daily_limit_sender INTEGER DEFAULT 100,      -- 발신자 일일 한도
    daily_limit_pair INTEGER DEFAULT 20,         -- 1:1 쌍 일일 한도
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. 시드 데이터
INSERT INTO messenger_providers (country_code, provider, display_name_ko, display_name_en, icon, required_scopes, daily_limit_sender, daily_limit_pair, is_active)
VALUES
    ('KR', 'kakao', '카카오톡', 'KakaoTalk', '💬', ARRAY['talk_message'], 100, 20, true),
    ('JP', 'line', 'LINE', 'LINE', '💚', ARRAY['message.write'], 500, 50, false),
    ('TW', 'line', 'LINE', 'LINE', '💚', ARRAY['message.write'], 500, 50, false)
ON CONFLICT (country_code) DO NOTHING;

-- 3. oauth_states에 purpose 컬럼 추가 (login vs messaging 구분)
ALTER TABLE oauth_states ADD COLUMN IF NOT EXISTS purpose VARCHAR(20) DEFAULT 'login';
