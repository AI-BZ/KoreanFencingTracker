-- 017: 회원 관심 서비스 컬럼 추가
-- 가입 시 선택한 관심 서비스 목록 (예: ["data","club"])

ALTER TABLE members ADD COLUMN IF NOT EXISTS interested_services JSONB DEFAULT '[]';

COMMENT ON COLUMN members.interested_services IS '가입 시 선택한 관심 서비스 목록 (예: ["data","club"])';
