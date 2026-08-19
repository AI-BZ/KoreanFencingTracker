-- 023_lock_rls_deny_anon.sql
--
-- ⚠️ 아직 적용하지 마세요. 아래 선행 조건을 먼저 만족해야 합니다.
--
-- 목적
--   회원 데이터 테이블에서 anon 역할의 접근을 끊는다.
--
-- 왜 필요한가
--   2026-08-19 점검에서 확인된 실태: anon 키 하나로 아래가 전부 읽혔다.
--
--     members                79행  (이메일·실명·연락처)
--     consent_logs           72행  (동의 이력, IP, User-Agent)
--     oauth_connections      15행  (카카오/구글 access token — 컬럼명은
--                                   access_token_encrypted 지만 실제로는 평문)
--     pending_registrations  34행  (가입 중 임시 데이터 + provider 토큰)
--     parent_claims           0행  (자녀 이름·생년·소속 — 018 의 정책이
--                                   SELECT USING (true) / INSERT WITH CHECK (true))
--
--   Supabase 의 anon 키는 "공개돼도 안전하다"는 전제 위에 설계된 키다. 그 전제는
--   RLS 가 데이터를 지킬 때만 성립하는데, 지금은 RLS 가 사실상 열려 있어서
--   anon 키가 곧 전체 회원 DB 열람 권한이다. 현재 이 키가 클라이언트로 나가는
--   경로는 확인되지 않았지만(템플릿·static grep 0건), 키가 한 번이라도 새면
--   막을 방법이 없다는 구조 자체가 문제다.
--
-- 🔴 선행 조건 — 순서를 지키지 않으면 전 서비스가 즉시 멈춘다
--
--   1. Supabase 대시보드 > Settings > API 에서 service_role 키를 복사한다.
--   2. 서버 환경변수에 SUPABASE_SERVICE_KEY 로 넣는다.
--      대상: account / data / club 의 launchd plist 또는 각 .env.
--      (shared_core.db.client 가 service key 를 우선 사용하도록 이미 고쳐져 있다.
--       키가 없으면 anon 으로 떨어지므로, 키를 넣기 전까지는 동작 변화가 없다.)
--   3. 각 서비스를 재시작하고, 실제로 service_role 로 붙었는지 확인한다.
--   4. 그 다음에 이 마이그레이션을 적용한다.
--
--   service key 는 RLS 를 무시한다. 서버 환경변수로만 두고 템플릿·클라이언트
--   번들에는 절대 싣지 말 것.
--
-- 롤백
--   맨 아래 주석의 DROP POLICY 문을 실행하면 이전 상태로 돌아간다.

-- ---------------------------------------------------------------------------
-- 1) RLS 활성화 (이미 켜져 있으면 무해)
-- ---------------------------------------------------------------------------
ALTER TABLE members               ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_connections     ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent_logs          ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_registrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE parent_claims         ENABLE ROW LEVEL SECURITY;
ALTER TABLE player_claims         ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_claims   ENABLE ROW LEVEL SECURITY;
ALTER TABLE verifications         ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- 2) 기존의 열린 정책 제거
--    018 이 parent_claims 에 USING (true) / WITH CHECK (true) 를 걸어두었다.
--    이름이 환경마다 다를 수 있어 pg_policies 를 돌며 전부 지운다.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT schemaname, tablename, policyname
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename IN (
              'members', 'oauth_connections', 'consent_logs',
              'pending_registrations', 'parent_claims', 'player_claims',
              'organization_claims', 'verifications'
          )
    LOOP
        EXECUTE format(
            'DROP POLICY IF EXISTS %I ON %I.%I',
            r.policyname, r.schemaname, r.tablename
        );
    END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 3) anon / authenticated 권한 회수
--
--    정책을 하나도 만들지 않으면 RLS 기본값이 "전부 거부"다. 여기서는 그 위에
--    테이블 권한까지 걷어 이중으로 막는다. service_role 은 RLS 를 우회하므로
--    서버 코드는 영향받지 않는다.
--
--    주의: 이 프로젝트는 Supabase Auth 를 쓰지 않는다. 자체 JWT 체계라
--    authenticated 역할로 붙는 클라이언트가 없다. 그래서 "본인 행만 허용"
--    형태의 정책을 만들 수 없고(비교할 auth.uid() 가 없다), 서버 경유만
--    허용하는 것이 유일하게 맞는 모델이다.
-- ---------------------------------------------------------------------------
REVOKE ALL ON members               FROM anon, authenticated;
REVOKE ALL ON oauth_connections     FROM anon, authenticated;
REVOKE ALL ON consent_logs          FROM anon, authenticated;
REVOKE ALL ON pending_registrations FROM anon, authenticated;
REVOKE ALL ON parent_claims         FROM anon, authenticated;
REVOKE ALL ON player_claims         FROM anon, authenticated;
REVOKE ALL ON organization_claims   FROM anon, authenticated;
REVOKE ALL ON verifications         FROM anon, authenticated;

-- ---------------------------------------------------------------------------
-- 롤백 (문제가 생기면 이것을 실행)
--
--   GRANT ALL ON members, oauth_connections, consent_logs,
--     pending_registrations, parent_claims, player_claims,
--     organization_claims, verifications TO anon, authenticated;
--
--   CREATE POLICY parent_claims_all ON parent_claims
--     FOR ALL USING (true) WITH CHECK (true);
--
--   되돌리면 위에 적은 노출 상태로 복귀한다는 점을 인지할 것.
-- ---------------------------------------------------------------------------
