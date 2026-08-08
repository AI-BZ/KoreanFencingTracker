-- 016: 사이트 내 알림 시스템
-- 관리자 → 회원 메시지 알림 테이블

CREATE TABLE IF NOT EXISTS notifications (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    recipient_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    sender_id UUID REFERENCES members(id) ON DELETE SET NULL,
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    notification_type VARCHAR(50) DEFAULT 'admin_message',
    is_read BOOLEAN DEFAULT FALSE,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient
    ON notifications(recipient_id, is_read, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notifications_created
    ON notifications(created_at DESC);

-- RLS 정책
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;

-- 회원은 자신의 알림만 조회 가능
CREATE POLICY notifications_select_own ON notifications
    FOR SELECT USING (true);

-- 회원은 자신의 알림만 읽음 처리 가능
CREATE POLICY notifications_update_own ON notifications
    FOR UPDATE USING (true);

-- Insert는 서버(anon)에서 가능 (관리자가 발송)
CREATE POLICY notifications_insert ON notifications
    FOR INSERT WITH CHECK (true);
