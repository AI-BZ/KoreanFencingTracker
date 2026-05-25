-- Supabase Migration: Add Kakao OAuth columns to members
-- Version: 009
-- Created: 2026-05-21
-- Description: members 테이블에 카카오 로그인 관련 컬럼 추가

-- 카카오 ID (카카오 계정 고유 식별자)
ALTER TABLE members ADD COLUMN IF NOT EXISTS kakao_id VARCHAR(50);

-- 카카오 닉네임
ALTER TABLE members ADD COLUMN IF NOT EXISTS kakao_nickname VARCHAR(100);

-- 카카오 프로필 이미지 URL
ALTER TABLE members ADD COLUMN IF NOT EXISTS kakao_profile_image TEXT;

-- 카카오 ID 유니크 인덱스 (NULL 제외)
CREATE UNIQUE INDEX IF NOT EXISTS idx_members_kakao_id
    ON members(kakao_id) WHERE kakao_id IS NOT NULL;
