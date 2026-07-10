-- ====================================================
-- App 서비스 테이블 (PWA/알림 허브)
-- Migration: 021
-- Date: 2026-06-04
-- Description: app.fencingmind.ai 알림 인프라 테이블
-- ====================================================

-- 1. 푸시 구독 테이블 (FCM 토큰 + 카카오 사용자 ID)
CREATE TABLE IF NOT EXISTS app_push_subscriptions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    -- FCM Web Push
    fcm_token TEXT,
    fcm_endpoint TEXT,
    fcm_p256dh TEXT,
    fcm_auth TEXT,
    -- 카카오 알림톡
    kakao_user_id VARCHAR(50),
    -- 메타
    device_type VARCHAR(20) DEFAULT 'web',  -- 'web', 'android', 'ios'
    user_agent TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_app_push_subs_member
    ON app_push_subscriptions(member_id, is_active);

CREATE INDEX IF NOT EXISTS idx_app_push_subs_fcm
    ON app_push_subscriptions(fcm_token)
    WHERE fcm_token IS NOT NULL AND is_active = TRUE;

-- 2. 알림 설정 테이블 (카테고리별 채널 opt-in/opt-out)
CREATE TABLE IF NOT EXISTS app_notification_preferences (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    -- 알림 카테고리 (예: 'competition_result', 'ranking_change', 'club_notice')
    category VARCHAR(50) NOT NULL,
    -- 채널별 on/off
    web_push BOOLEAN DEFAULT TRUE,
    kakao_alimtalk BOOLEAN DEFAULT FALSE,
    in_app BOOLEAN DEFAULT TRUE,
    -- 메타
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(member_id, category)
);

CREATE INDEX IF NOT EXISTS idx_app_notif_prefs_member
    ON app_notification_preferences(member_id);

-- 3. 알림 발송 로그 (채널별 상태 추적)
CREATE TABLE IF NOT EXISTS app_notification_log (
    id BIGSERIAL PRIMARY KEY,
    notification_id UUID REFERENCES notifications(id) ON DELETE SET NULL,
    member_id UUID NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    -- 발송 채널
    channel VARCHAR(20) NOT NULL,  -- 'web_push', 'kakao_alimtalk', 'in_app'
    -- 상태
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- 'pending', 'sent', 'delivered', 'failed', 'clicked'
    error_message TEXT,
    -- 원본 이벤트 참조
    event_type VARCHAR(100),
    event_id BIGINT,
    -- 타임스탬프
    sent_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    clicked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_app_notif_log_member
    ON app_notification_log(member_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_app_notif_log_status
    ON app_notification_log(status, channel);

CREATE INDEX IF NOT EXISTS idx_app_notif_log_event
    ON app_notification_log(event_type, event_id);

-- 4. 이벤트 폴링 커서 (data_events 워터마크)
CREATE TABLE IF NOT EXISTS app_event_cursor (
    id INTEGER PRIMARY KEY DEFAULT 1,  -- 싱글턴 행
    last_event_id BIGINT NOT NULL DEFAULT 0,
    last_polled_at TIMESTAMPTZ DEFAULT NOW(),
    events_processed BIGINT DEFAULT 0,
    CONSTRAINT single_row CHECK (id = 1)
);

-- 초기 커서 행 삽입
INSERT INTO app_event_cursor (id, last_event_id)
VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;

-- 5. notifications 테이블 확장 (link_url, metadata 컬럼)
ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS link_url TEXT,
    ADD COLUMN IF NOT EXISTS metadata JSONB;

-- RLS 정책
ALTER TABLE app_push_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_notification_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_notification_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_event_cursor ENABLE ROW LEVEL SECURITY;

-- app_push_subscriptions: 서버(anon)에서 CRUD
CREATE POLICY app_push_subs_all ON app_push_subscriptions
    FOR ALL USING (true) WITH CHECK (true);

-- app_notification_preferences: 서버(anon)에서 CRUD
CREATE POLICY app_notif_prefs_all ON app_notification_preferences
    FOR ALL USING (true) WITH CHECK (true);

-- app_notification_log: 서버에서 insert/select
CREATE POLICY app_notif_log_all ON app_notification_log
    FOR ALL USING (true) WITH CHECK (true);

-- app_event_cursor: 서버에서만 사용 (싱글턴)
CREATE POLICY app_event_cursor_all ON app_event_cursor
    FOR ALL USING (true) WITH CHECK (true);

-- 코멘트
COMMENT ON TABLE app_push_subscriptions IS 'FCM 웹 푸시 토큰 + 카카오 사용자 ID 저장';
COMMENT ON TABLE app_notification_preferences IS '회원별 알림 카테고리/채널 설정';
COMMENT ON TABLE app_notification_log IS '알림 발송 이력 (채널별 상태 추적)';
COMMENT ON TABLE app_event_cursor IS 'data_events 폴링 워터마크 (싱글턴)';
