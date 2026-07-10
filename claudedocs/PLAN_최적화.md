# FencingMind 최적화 수정계획 (2026-07-10)

> 근거: `claudedocs/EVAL_현재상태.md`. deep-reasoner 수립, 코드 미수정 상태.
> 정렬: P0 우선 + 각 티어 내 되돌리기 쉬운 순. YAGNI — 신기능 없음.
> 관할: services/account, packages/shared_core, packages/shared-ui, 루트 공통. 타 워크트리 항목은 맨 끝 이관 권고.
>
> **승인 상태: ⏳ 사용자 승인 대기** — 승인된 항목만 3단계에서 실행.

---

## ⚙️ 항목 A — 검증 인프라 구축 (선행, P0와 병렬)

- **무엇을**: 루트 `requirements.txt`에 account 런타임 누락분 보강 + `requirements-dev.txt`(신규: pytest, pytest-asyncio, ruff, httpx). 서비스별 의존 분리는 YAGNI — 루트 단일 보강만.
- **왜**: pytest·ruff 미설치로 테스트 31개 실행 불가 → 이후 모든 항목의 테스트 검증이 이것에 의존.
- **영향범위**: `/requirements.txt`, `/requirements-dev.txt`(신규), `/pytest.ini`
- **리스크**: 하 (추가만). ARM64 규칙(`arch -arm64 python3 -m pip install`) 준수 필수.
- **난이도**: 하 / **우선순위**: 선행
- **위임**: runner → 실패 시 quality-engineer
- **검증**: 설치 후 `PYTHONPATH=... python -m pytest services/account/tests -q` collect 0→31 전환 확인.

## 🔴 P0

### 1. `.mcp.json` Supabase 토큰 환경변수화  [P0-2]
- **무엇을**: `"SUPABASE_ACCESS_TOKEN": "sbp_..."` 평문 → `"${SUPABASE_ACCESS_TOKEN}"` 치환(github 서버가 이미 `${GITHUB_TOKEN}` 패턴 사용 중 — 검증된 방식). 실제 토큰은 `.env`로 이동(.env는 gitignore됨).
- **왜**: 토큰이 초기 커밋부터 git 히스토리에 평문 노출. Supabase 프로젝트 전체 접근 가능한 관리 토큰.
- **⚠️ 사람 액션 필수**: **사용자가 Supabase 대시보드에서 토큰 회전(revoke+재발급)** 해야 실질 위험 해소. git 히스토리 재작성(filter-repo)은 파괴적이라 별도 승인 필요 — 이 계획엔 미포함.
- **영향범위**: `/.mcp.json`, `/.env`, `/.env.example`
- **리스크**: 하. MCP 재시작 시 env 미주입이면 supabase MCP 도구 사용 불가.
- **난이도**: 하 / **위임**: security-engineer(설계) + runner(편집)
- **검증**: 커밋 후 `git show HEAD:.mcp.json | grep -c sbp_` → 0. 재시작 후 supabase MCP 동작 확인. 토큰 회전 여부 사용자 확인.

### 2. JWT 시크릿 안전하지 않은 기본값 제거  [P0-1]
- **무엇을**: `packages/shared_core/auth/config.py:20`의 fallback `"your-secret-key-change-in-production"` 제거 → env 없으면 기동 시 예외(fail-fast). OAuth secret들의 빈문자 fallback도 명시 검증.
- **왜**: env 누락 시 전 서브도메인(.fencingmind.ai 쿠키 공유)에서 임의 회원 위장 가능.
- **영향범위**: `packages/shared_core/auth/config.py:20-36`
- **리스크**: 중. **R2 충돌** — shared_core는 feature/shared/* 브랜치 + R4(전 서비스 테스트). **배포 env에 JWT_SECRET_KEY 실제 설정 여부 미검증** — 미설정 상태에서 fail-fast 적용 시 전 서비스 기동 실패 → 배포 env 확인 후 적용.
- **난이도**: 하(코드)·중(배포 조율) / **위임**: security-engineer
- **검증**: env unset 시 import 예외 발생, 설정 시 account+data 서버 기동 정상.

## 🟡 P1

### 3. 오픈 리다이렉트 endswith 우회 수정  [P1-1]
- **무엇을**: `_is_safe_redirect`(`services/account/app/auth/router.py:89-96`) `hostname.endswith(d)` → `hostname == d or hostname.endswith("." + d)`.
- **왜**: `evilfencingmind.ai` 통과 → OAuth 후 피싱/토큰 유출 벡터.
- **영향범위**: router.py:89-96 (순수함수, 격리)
- **리스크**: 하. 정당 서브도메인 통과 회귀 확인만.
- **난이도**: 하 / **위임**: security-engineer
- **검증**: 테스트 케이스 추가(evil→False, data.fencingmind.ai→True, 상대경로→True) 후 pytest (항목 A 완료 후).

### 4. OAuth state URL 문자열 파싱 제거  [P1-5]
- **무엇을**: `build_auth_url`이 `(auth_url, state)` 튜플 반환 → `oauth_login`(router.py:492-507)의 `split("state=")` 되파싱 제거.
- **왜**: provider URL 포맷 변경 시 조용히 파손, `except: pass`로 redirect 유실 은폐.
- **영향범위**: `packages/shared_core/auth/oauth/handler.py:69-148` + `services/account/app/auth/router.py:492-507`. **R2/R4 플래그** — 호출처 전수 확인 필요.
- **리스크**: 중 (시그니처 변경).
- **난이도**: 중 / **위임**: refactoring-expert + security-engineer 리뷰
- **검증**: `grep -rn build_auth_url` 호출처 전수 수정 → 서버 기동 후 curl로 302 Location state + DB oauth_states.redirect_url 확인.

### 5. 공개검색 API rate limiting + 응답 필드 최소화  [P1-2]  ⚠️ 정책 승인 게이트
- **무엇을**: (a) `/auth/public/player-search`·`/child-search`·`/org-search`(router.py:211-325)에 IP 기반 rate limit(slowapi). (b) 응답 필드(birth_year·team_name) 노출 최소화 — 정확한 마스킹 정책은 security-engineer 초안 → **사용자 승인 후** 적용(제0원칙 2번).
- **왜**: 무인증·무제한으로 미성년 실명+출생연도+소속 열거 가능. P1-3 신원탈취 재료 배포.
- **영향범위**: router.py:211-325, server.py(미들웨어), requirements.txt(slowapi)
- **리스크**: 중. rate limit 과도 시 가입 검색 UX 저하, 필드 축소는 register.html 프론트 연동 회귀.
- **난이도**: 중 / **위임**: security-engineer + api-agent
- **검증**: 반복 curl → 429 확인, 응답 JSON 필드 정책 준수, register UI 수동 확인.

### 6. claim 자동승인 임계값 재설계  [P1-3]  ⚠️ 정책 승인 게이트
- **무엇을**: `calculate_claim_confidence`(`verification/claims.py:63-119`)가 공개 3필드(이름·출생연도·소속)만으로 AUTO_APPROVE(0.85, config.py:57) 도달 불가하게 — 공개데이터로 위조 불가한 신호 가중치 추가 또는 자동승인 비활성화(pending→관리자 검토). **설계안 → 사용자 승인 필수**.
- **왜**: 공개 API 배포 필드 = 자동승인 조건 → 프로필 탈취, 제1원칙 무결성 전파.
- **영향범위**: verification/claims.py:63-119, config.py:57-58, router.py:870-950, verifications/processor.py(동일 임계값 참조 확인)
- **리스크**: 중~상. 임계 상향 시 관리자 수작업 증가(운영부하), 승인→player 연결 파이프라인 회귀.
- **난이도**: 중 / **위임**: security-engineer + backend-architect
- **검증**: 단위테스트 "공개 3필드만 → confidence < 0.85", 가입 E2E claim status=pending 확인.

### 7. i18n shared_core 수렴  [P1-4]  (마지막, 별도 브랜치)
- **무엇을**: account 자체 i18n(3중 복제 중 1벌)을 `shared_core.i18n.LanguageMiddleware + extra_dirs`로 교체, `server.py:26` 수정.
- **왜**: manager 3벌 병존 — 정책 변경 시 3곳 수정, 편차 위험.
- **영향범위**: services/account/app/server.py:26, services/account/app/i18n/*, packages/shared_core/i18n/*. **R2/R4**. 템플릿 컨텍스트 키(theme/t/i18n_data) 호환 유지 필수.
- **리스크**: 상 (다수 템플릿 영향, 되돌리기 어려움).
- **난이도**: 상 / **위임**: refactoring-expert (+ i18n-coordinator)
- **검증**: 전 auth 페이지 ko/en 렌더 — `?lang=en`→dark, `?lang=ko`→light, 번역키 fallback 로그 0.

### 8. 루트 깨진 레거시/쓰레기 정리  [P1-6]
- **무엇을**: 루트 `main.py`(파손 죽은코드) 제거 + rsync 오실행 산물(`--exclude=*.log`, `-av`, `--dry-run`, `rsync/`) 삭제. Procfile은 services/* 진입점이라 main.py 미참조 확인됨.
- **왜**: 진입점 오인 방지, 워크스페이스 위생.
- **영향범위**: 루트. 삭제 전 참조 전수 grep 필수.
- **리스크**: 하~중 (cron/스크립트 참조 여부 확인 후).
- **난이도**: 하 / **위임**: runner
- **검증**: `grep -rn "main.py" scripts/ infrastructure/ Procfile` 참조 0 확인 후 삭제.

## 🟢 P2

### 9. 마이그레이션 002 번호중복 문서화
- R3(기존 파일 수정 금지) 때문에 rename 불가 → `mcp__supabase__list_migrations`로 실제 적용 순서 확인 후 README/주석으로 실행순서 명시. DB 변경 없음. 난이도 하 / runner.

### 10. register.html 분할 (1001줄 → 부분템플릿 + shared-ui CSS)
- 기능동등 리팩터. 회귀 위험 중간. 난이도 중 / refactoring-expert + ui-agent. 검증: 가입 E2E 수동.

### 11. datetime.utcnow → timezone-aware 통일 (선택)
- router.py 4곳 + 만료비교(:1117-1119). 난이도 하 / refactoring-expert. 검증: 이메일 인증 만료 플로우.

---

## 실행 순서 요약
**A(병렬 선행) → 1 → 2 → 3 → 4 → 5 → 6 → 8 → 9 → 7(마지막·별도브랜치) → 10/11(여유 시)**
3·5·6은 "공개표면→신원탈취" 클러스터 — 한 PR로 묶어 리뷰 권장.

## 브랜치 전략 (R2/R4)
- shared_core 수정(2·4·7): feature/shared/* 브랜치 분리 + account·data 기동 스모크 필수.
- account 전용(3·5·6·10·11) 및 공통(A·1·8·9): feature/account/* 또는 refactor/eval-20260710.

## ⛔ 타 워크트리 이관 권고 (이 계획 제외)
- data 서비스 i18n 자체복제 제거 → FencingMind-data 워크트리.
- club/community/shop/blog/analytics 5개 auth shim 부재 → 각 워크트리에서 data shim 패턴 복사.

## 항목별 진행 상태 (3단계에서 갱신)
| 항목 | 상태 |
|------|------|
| A, 1~11 | ⏳ 승인 대기 |
