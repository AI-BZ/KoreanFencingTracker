-- ====================================================
-- App 서비스: 알림 재시도 스윕 지원 컬럼
-- Migration: 023
-- Date: 2026-07-10
-- Description: app_notification_log에 재시도 추적 컬럼(attempt_count, last_attempt_at)
--              추가. 폴러 커서가 이미 지나간 실패/보류(failed/pending) 알림을 별도
--              스윕으로 재발송할 수 있게 한다. (EVAL P1-1: 전송 실패 시 영구 유실 복구)
-- ====================================================
--
-- 배경 (P1-1):
--   폴러 워터마크는 배치 max(id)로 무조건 전진하고 디스패처는 전송 실패를 흡수해
--   app_notification_log에 status='failed'(또는 'pending')만 남긴다. 재시도 경로가
--   없어 일시적 오류로 실패한 알림은 커서가 지나가 영원히 재발송되지 않았다.
--   (예: VAPID 키가 나중에 설정돼도 그 전 'pending' 웹푸시는 발송 안 됨.)
--
--   이 마이그레이션은 재시도 스윕(dispatcher.retry_failed)이 사용할 상태 컬럼만
--   추가한다. 스윕은 기존 로그 행을 UPDATE하므로 migration 022의
--   UNIQUE(member_id, channel, event_type, event_id) 제약과 정합한다(신규 INSERT 아님).
--
-- 🔁 롤백:
--     ALTER TABLE app_notification_log DROP COLUMN IF EXISTS attempt_count;
--     ALTER TABLE app_notification_log DROP COLUMN IF EXISTS last_attempt_at;
--     DROP INDEX IF EXISTS idx_app_notif_log_retry;
-- ====================================================

-- 재시도 횟수 (0 = 최초 발송만 시도됨, 아직 스윕 재시도 없음).
ALTER TABLE app_notification_log
    ADD COLUMN IF NOT EXISTS attempt_count INT NOT NULL DEFAULT 0;

-- 마지막 재시도 시각 (스윕이 이 행을 마지막으로 건드린 시점).
ALTER TABLE app_notification_log
    ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ;

-- 재시도 스윕 조회 성능용 부분 인덱스.
--   스윕 쿼리: status IN ('failed','pending') AND attempt_count < N AND created_at >= window
--   → status='failed'/'pending' 행만 인덱싱 (전체 로그의 소수)해 스윕 비용을 낮춘다.
CREATE INDEX IF NOT EXISTS idx_app_notif_log_retry
    ON app_notification_log(created_at, attempt_count)
    WHERE status IN ('failed', 'pending');

COMMENT ON COLUMN app_notification_log.attempt_count
    IS '재시도 스윕 시도 횟수 (P1-1). NOTIFY_RETRY_MAX_ATTEMPTS 도달 시 스윕 대상 제외.';
COMMENT ON COLUMN app_notification_log.last_attempt_at
    IS '재시도 스윕이 이 행을 마지막으로 처리한 시각 (P1-1).';
