-- 010: Create member_favorites table
-- 즐겨찾기 선수 관리 (member 레벨 이상)

CREATE TABLE IF NOT EXISTS member_favorites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    player_name VARCHAR(100) NOT NULL,
    display_order INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(member_id, player_name)
);

CREATE INDEX IF NOT EXISTS idx_member_favorites_member ON member_favorites(member_id);

-- RLS 정책
ALTER TABLE member_favorites ENABLE ROW LEVEL SECURITY;

-- 자신의 즐겨찾기만 조회 가능
CREATE POLICY member_favorites_select ON member_favorites
    FOR SELECT USING (member_id = auth.uid());

-- 자신의 즐겨찾기만 추가 가능
CREATE POLICY member_favorites_insert ON member_favorites
    FOR INSERT WITH CHECK (member_id = auth.uid());

-- 자신의 즐겨찾기만 삭제 가능
CREATE POLICY member_favorites_delete ON member_favorites
    FOR DELETE USING (member_id = auth.uid());
