-- ====================================================
-- App 서비스: app_* 테이블 RLS 잠금 (service_role 전용)
-- Migration: 025
-- Date: 2026-07-10
-- Description: migration 021이 app_* 4개 테이블의 RLS 정책을 anon에 전면 개방
--              (FOR ALL USING(true) WITH CHECK(true))했다. anon 키만 있으면 전 회원의
--              푸시 구독(엔드포인트/암호화 키)·알림 설정·발송 이력을 열람/조작할 수 있어,
--              anon 키 유출 시 전 회원 알림 인프라가 노출된다(EVAL P1-5).
--              이 마이그레이션은 그 광범위 정책을 제거해 app_* 테이블을 service_role
--              전용으로 잠근다. service_role은 RLS를 우회하므로 서버는 정책이 없어도
--              정상 동작하고, anon/authenticated의 직접 접근은 차단된다.
-- ====================================================
--
-- 🔴🔴🔴 적용 전 필수 선행조건 (런북) 🔴🔴🔴
--   이 마이그레이션은 **Part A(서버의 service_role 전환 코드)가 배포·확인된 뒤에만**
--   적용해야 한다. 순서를 뒤집으면 anon 키로 동작하던 서버가 app_* 테이블 접근에
--   실패해 알림 파이프라인(폴러/디스패처/설정 API)이 전부 죽는다.
--
--   1. Part A 배포 확인:
--      - 프로덕션 env에 SUPABASE_SERVICE_KEY가 설정돼 있는가.
--      - 서버 로그에 "app DB가 anon 키로 폴백합니다" warning이 **없는가**
--        (= get_app_db()가 service_role 클라이언트를 쓰고 있다는 뜻).
--        경고가 보이면 아직 anon 폴백 상태 → 025 적용 금지.
--   2. 위 2가지를 만족한 뒤 이 파일을 적용한다.
--
--   ⚠️ 왜 안전한가: service_role 키는 RLS를 우회한다. 따라서 정책을 모두 제거해도
--      service_role로 접근하는 서버는 영향이 없고, anon/authenticated만 차단된다.
--      이 서비스의 app_* 접근은 100% 서버 경유(브라우저→Supabase 직접 접근 없음)이므로
--      전면 잠금이 가장 단순·안전하다.
--
-- 🔁 롤백 (아래 "ROLLBACK" 섹션 참고):
--      021의 4개 개방 정책을 그대로 복원한다. 서버가 anon으로 되돌아가도 동작하도록.
-- ====================================================

-- 4개 테이블 모두 RLS는 이미 활성(021에서 ENABLE). 여기서는 정책만 교체한다.

-- 1) app_push_subscriptions: anon 전면 개방 정책 제거 → service_role 전용.
--    푸시 엔드포인트/p256dh/auth는 민감 정보 → anon 열람 차단이 핵심.
DROP POLICY IF EXISTS app_push_subs_all ON app_push_subscriptions;

-- 2) app_notification_preferences: 회원별 알림 설정 → service_role 전용.
DROP POLICY IF EXISTS app_notif_prefs_all ON app_notification_preferences;

-- 3) app_notification_log: 발송 이력(누구에게 무엇을 보냈는지) → service_role 전용.
DROP POLICY IF EXISTS app_notif_log_all ON app_notification_log;

-- 4) app_event_cursor: 순수 서버 내부 워터마크(싱글턴) → service_role 전용.
DROP POLICY IF EXISTS app_event_cursor_all ON app_event_cursor;

-- 정책을 남기지 않는다: RLS가 켜진 테이블에 정책이 하나도 없으면 anon/authenticated는
-- 모든 접근이 거부되고, RLS를 우회하는 service_role만 접근 가능하다(의도된 잠금).
-- 브라우저→Supabase 직접 접근이 없는 서비스이므로 authenticated 본인행 SELECT 정책도
-- 두지 않는다(불필요한 접근면 최소화). 향후 클라이언트 직접 조회가 필요해지면 그때
-- member_id = auth.uid() 매핑 기반 SELECT 정책을 별도 마이그레이션으로 추가한다.

-- 코멘트 갱신
COMMENT ON TABLE app_push_subscriptions IS
    'FCM 웹 푸시 토큰 + 카카오 사용자 ID 저장 (RLS: service_role 전용 — migration 025)';
COMMENT ON TABLE app_notification_preferences IS
    '회원별 알림 카테고리/채널 설정 (RLS: service_role 전용 — migration 025)';
COMMENT ON TABLE app_notification_log IS
    '알림 발송 이력 (RLS: service_role 전용 — migration 025)';
COMMENT ON TABLE app_event_cursor IS
    'data_events 폴링 워터마크 (싱글턴, RLS: service_role 전용 — migration 025)';

-- ====================================================
-- ROLLBACK (수동 실행용 — 서버를 anon 폴백으로 되돌릴 때)
--   Part A를 롤백해 서버가 다시 anon 키로 app_* 테이블에 접근해야 하는 경우,
--   아래 4개 정책을 복원하면 021 상태(anon 전면 개방)로 돌아간다.
-- ====================================================
-- ALTER TABLE app_push_subscriptions ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE app_notification_preferences ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE app_notification_log ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE app_event_cursor ENABLE ROW LEVEL SECURITY;
--
-- CREATE POLICY app_push_subs_all ON app_push_subscriptions
--     FOR ALL USING (true) WITH CHECK (true);
-- CREATE POLICY app_notif_prefs_all ON app_notification_preferences
--     FOR ALL USING (true) WITH CHECK (true);
-- CREATE POLICY app_notif_log_all ON app_notification_log
--     FOR ALL USING (true) WITH CHECK (true);
-- CREATE POLICY app_event_cursor_all ON app_event_cursor
--     FOR ALL USING (true) WITH CHECK (true);
