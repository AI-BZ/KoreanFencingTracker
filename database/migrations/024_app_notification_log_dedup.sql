-- ====================================================
-- App 서비스: 재정정 알림 스팸 억제 (엔티티 단위 쿨다운)
-- Migration: 024
-- Date: 2026-07-10
-- Description: app_notification_log에 dedup_key(논리 엔티티 식별자) 컬럼과
--              쿨다운 조회용 인덱스를 추가한다. 멱등키가 data_events.id(행 id)
--              기준이라, 대회 결과를 재스크래핑/정정할 때마다 새 data_events 행
--              (새 id)이 생겨 참가 선수 전원에게 매번 새 알림이 발송됐다(스팸).
--              정정 1회 = 전원 스팸 1회. dedup_key로 "같은 논리 엔티티"를 묶어,
--              디스패처가 쿨다운(NOTIFY_DEDUP_COOLDOWN_HOURS) 이내 재알림을 억제한다.
--              (EVAL P1-4: 재정정 알림 스팸 억제)
-- ====================================================
--
-- 배경 (P1-4):
--   대회 결과 정정 → EventPublisher가 competition.updated를 새 data_events 행으로
--   발행 → 새 event_id → dispatcher._already_sent(member, channel, event_type,
--   event_id) 검사를 통과(다른 event_id) → 참가 선수 전원 재발송. 정정을 반복하면
--   그때마다 전원에게 알림이 쏟아진다.
--
--   dedup_key는 event_id가 아니라 "논리 엔티티"를 식별한다. 디스패처가 최초 발송 시
--   로그 행에 dedup_key를 채워두면, 다음 정정 이벤트는 최근 쿨다운 창 안에서 같은
--   dedup_key로 이미 'sent'된 로그가 있는지 확인하고 있으면 발송을 건너뛴다.
--   (기존 022 UNIQUE 멱등성/023 재시도 스윕과 독립적으로 동작 — 컬럼만 추가.)
--
-- 📌 dedup_key 포맷 (dispatcher._dedup_key):
--     "{category}:{entity_type}:{entity_id}"
--     예: "competition_result:competition:132", "ranking_change:player:5"
--   entity_type/entity_id 중 하나라도 없으면 디스패처는 dedup_key를 NULL로 기록하고
--   억제도 하지 않는다(키가 불완전하면 안전측으로 정상 발송 — 억제 실패 < 알림 유실).
--
-- 🔁 롤백:
--     ALTER TABLE app_notification_log DROP COLUMN IF EXISTS dedup_key;
--     DROP INDEX IF EXISTS idx_app_notif_log_dedup;
-- ====================================================

-- 논리 엔티티 식별자 (event_id가 아니라 category+entity 기준). NULL 허용:
--   불완전한 이벤트(entity_type/entity_id 없음)는 억제 대상이 아니므로 NULL로 기록된다.
ALTER TABLE app_notification_log
    ADD COLUMN IF NOT EXISTS dedup_key TEXT;

-- 쿨다운 조회 성능용 부분 인덱스.
--   디스패처 쿨다운 쿼리: dedup_key = ? AND member_id = ? AND channel = ?
--                        AND status = 'sent' AND created_at >= window
--   → dedup_key IS NOT NULL 행만 인덱싱(억제 대상 소수)해 조회 비용을 낮춘다.
CREATE INDEX IF NOT EXISTS idx_app_notif_log_dedup
    ON app_notification_log(dedup_key, created_at)
    WHERE dedup_key IS NOT NULL;

COMMENT ON COLUMN app_notification_log.dedup_key
    IS '재정정 스팸 억제용 논리 엔티티 키 (P1-4). '
       '"{category}:{entity_type}:{entity_id}". NULL = 억제 대상 아님(불완전 이벤트).';
