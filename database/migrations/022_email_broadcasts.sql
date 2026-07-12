-- Migration 022: Email Broadcasts (관리자 배치 이메일 발송)
--
-- 마케팅 수신동의(marketing_consent=TRUE) 회원에게 공지/뉴스레터를 배치 발송.
-- 재개 가능(pending 재실행) · 중복발송 방지(UNIQUE 제약).
--
-- 수신거부는 별도 opt-out 컬럼을 만들지 않고 members.marketing_consent 를 FALSE 로
-- 뒤집고 consent_logs 에 이력을 남기는 기존 인프라를 재사용한다.
--
-- 추가 전용(R3): 기존 마이그레이션 수정 금지, IF NOT EXISTS 사용.

-- 발송 배치 (하나의 공지/뉴스레터 = 한 행)
CREATE TABLE IF NOT EXISTS email_broadcasts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject           TEXT NOT NULL,
    body_html         TEXT NOT NULL,
    created_by        UUID REFERENCES members(id),
    status            TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'sending', 'sent', 'failed')),
    total_recipients  INTEGER NOT NULL DEFAULT 0,
    sent_count        INTEGER NOT NULL DEFAULT 0,
    failed_count      INTEGER NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at           TIMESTAMPTZ
);

-- 배치별 수신자 스냅샷 (발송 시점의 opt-in 회원 고정)
CREATE TABLE IF NOT EXISTS email_broadcast_recipients (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broadcast_id  UUID NOT NULL REFERENCES email_broadcasts(id) ON DELETE CASCADE,
    member_id     UUID NOT NULL,
    email         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sent', 'failed', 'skipped')),
    error         TEXT,
    sent_at       TIMESTAMPTZ,
    -- 중복발송 방지: 한 배치 안에서 회원당 한 건만
    CONSTRAINT uq_broadcast_member UNIQUE (broadcast_id, member_id)
);

CREATE INDEX IF NOT EXISTS idx_broadcast_recipients_broadcast
    ON email_broadcast_recipients (broadcast_id);
CREATE INDEX IF NOT EXISTS idx_broadcast_recipients_status
    ON email_broadcast_recipients (status);
