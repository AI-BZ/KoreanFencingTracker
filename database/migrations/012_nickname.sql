-- Migration 012: Nickname (unique handle)
-- 서비스 전체에서 사용하는 고유 닉네임 (@handle)

ALTER TABLE members ADD COLUMN IF NOT EXISTS nickname VARCHAR(20);

-- 고유 인덱스 (대소문자 구분 없이 unique)
CREATE UNIQUE INDEX IF NOT EXISTS idx_members_nickname_unique
    ON members (LOWER(nickname))
    WHERE nickname IS NOT NULL;
