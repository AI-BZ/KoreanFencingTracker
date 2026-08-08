-- ====================================================
-- App 서비스: 알림 로그 중복 발송 차단 (UNIQUE 제약)
-- Migration: 022
-- Date: 2026-07-10
-- Description: app_notification_log에 (member_id, channel, event_type, event_id)
--              UNIQUE 제약 추가. 다중 폴러/인스턴스가 같은 이벤트 배치를 동시
--              처리할 때 발생하는 SELECT-then-INSERT 경쟁(중복 발송)을 DB 레벨에서
--              최종 차단한다. (EVAL P1-3: 다중 폴러 중복 발송 차단)
-- ====================================================
--
-- ⚠️ 적용 전 권장: 프로덕션 중복 건수를 먼저 조회하여 (a) 정리 규모를 파악할 것.
--     SELECT member_id, channel, event_type, event_id, COUNT(*)
--       FROM app_notification_log
--      WHERE event_id IS NOT NULL
--      GROUP BY member_id, channel, event_type, event_id
--     HAVING COUNT(*) > 1;
--
-- 🔁 롤백:
--     ALTER TABLE app_notification_log
--         DROP CONSTRAINT uq_app_notif_log_member_channel_event;
--
-- 📌 event_id NULL 처리 (의도된 동작):
--     PostgreSQL의 UNIQUE 제약은 NULL을 서로 다른 값으로 취급하므로, event_id가
--     NULL인 로그 행은 이 제약에 걸리지 않는다(무제한 중복 허용). 이는 의도된 설계다 —
--     dispatcher._already_sent()는 event_id가 None이면 멱등성 검사를 건너뛰기 때문에
--     (event_id 없는 항목은 순수 로그 전용 엔트리로 취급), NULL 행의 중복은 무해하다.
--     따라서 아래 (a) 중복 정리도 event_id IS NOT NULL 행만 대상으로 한다.
-- ====================================================

-- (a) 기존 중복 정리 — 그룹별 최소 id 행 1개만 남기고 삭제.
--     event_id IS NOT NULL 행만 대상 (NULL은 멱등성 대상이 아님, 위 주석 참고).
--     idempotent: 재실행해도 남는 것은 그룹당 1행뿐이므로 안전.
DELETE FROM app_notification_log a
USING app_notification_log b
WHERE a.event_id IS NOT NULL
  AND b.event_id IS NOT NULL
  AND a.member_id  = b.member_id
  AND a.channel    = b.channel
  AND a.event_type = b.event_type
  AND a.event_id   = b.event_id
  AND a.id > b.id;

-- (b) UNIQUE 제약 추가.
ALTER TABLE app_notification_log
    ADD CONSTRAINT uq_app_notif_log_member_channel_event
    UNIQUE (member_id, channel, event_type, event_id);

COMMENT ON CONSTRAINT uq_app_notif_log_member_channel_event ON app_notification_log
    IS '다중 폴러 중복 발송 차단 (P1-3). event_id NULL 행은 제약 대상 아님(의도).';
