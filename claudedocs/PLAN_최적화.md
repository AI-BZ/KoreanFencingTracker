# FencingMind-data 최적화 수정 계획 (PLAN)

- **작성일**: 2026-07-09
- **근거**: claudedocs/EVAL_현재상태.md
- **작성자**: 지휘자(Fable 5) 직접 — deep-reasoner(Opus)가 세션 한도로 불가하여 대체
- **원칙**: 되돌리기 쉬운 것부터, P0 우선, 신기능 제안 금지(YAGNI)
- **상태**: ⏳ 승인 대기 — 승인된 번호만 3단계에서 실행

---

## 항목 목록 (우선순위 순)

### 1. [P1-1] 작업 트리 정리 + 커밋 ✋ 모든 항목의 선행 조건
- **무엇을**: (a) 수정 중인 20개 파일을 논리 단위로 검토·커밋, (b) 스크린샷 PNG 54개·zip·임시파일을 삭제 또는 `docs/screenshots/`로 이동, (c) `.gitignore`에 `*.png`(루트), `.coverage`, `services/data/data/` 추가
- **왜**: 롤백 가능 상태 확보. 3단계 가드레일("작업 트리 깨끗한지 확인") 충족 전제
- **영향범위**: git 이력, .gitignore (코드 로직 무변경)
- **리스크**: 낮음 (삭제 전 PNG 목록 사용자 확인)
- **난이도**: 낮음 | **위임**: runner(파일 이동/정리) + 지휘자(커밋 단위 판단)

### 2. [P0-1] 관리성 엔드포인트 인증 추가
- **무엇을**: `POST /api/data/reload`, `POST /api/scheduler/run`, `GET /api/admin/validate*` 에 admin 권한 검사 추가 (기존 `get_current_member` + member_type=admin 재사용). 스케줄러 내부 호출(`_refresh_server_cache`)은 localhost 예외 또는 내부 토큰으로 유지
- **왜**: 외부인이 데이터 리로드/스크래퍼 실행 가능 — 자원 고갈 + KFA 무단 트래픽 리스크
- **영향범위**: services/data/app/server.py (3-4개 엔드포인트), scheduler/scheduler.py의 캐시 갱신 호출부
- **리스크**: 중간 — 스케줄러의 자체 캐시 갱신 경로가 막히면 자동 갱신 중단. 수정 후 스케줄러 경로 구동 검증 필수
- **난이도**: 낮음~중간 | **위임**: security-engineer (구현) + runner (구동 검증)

### 3. [P0-2] JWT_SECRET_KEY 기본값 제거
- **무엇을**: shared_core/auth/config.py:20의 폴백 기본값 제거 → 미설정 시 기동 실패(fail-fast)로 변경. 먼저 프로덕션 launchd env에 실제 키 설정 여부 확인
- **왜**: 공개된 기본 키로 토큰 위조 가능 → 인증 전체 무력화
- **영향범위**: packages/shared_core/auth/config.py — ⚠️ **R2 규칙**: shared_core 수정은 `feature/shared/*` 브랜치에서 해야 함. 별도 브랜치·별도 커밋으로 분리
- **리스크**: 중간 — 프로덕션 env 미설정 상태에서 배포하면 서버 기동 실패. 반드시 env 확인 → 키 설정 → 코드 변경 순서
- **난이도**: 낮음 | **위임**: security-engineer + runner (프로덕션 env 확인)

### 4. [P1-2] 테스트 실행 환경 복구 + 현재 통과율 측정
- **무엇을**: ARM64 규칙(`arch -arm64 python3 -m pip install`)에 맞춰 pytest 설치, 41개 테스트 실행, 통과/실패 현황을 문서화. 코드 수정은 하지 않고 현황 파악까지만
- **왜**: 이후 모든 리팩터링 항목의 검증 수단 확보 (현재는 회귀 감지 불능)
- **영향범위**: 환경만 (코드 무변경)
- **리스크**: 낮음
- **난이도**: 낮음 | **위임**: runner (설치·실행) + quality-engineer (실패 분석)

### 5. [P1-4] extract_age_group 중복 통일
- **무엇을**: server.py:1369와 calculator.py:348의 `extract_age_group`을 비교해 단일 구현으로 통일 (공용 모듈로 추출, 양쪽에서 import)
- **왜**: 나이그룹 파싱 규칙 드리프트 → 랭킹/필터 불일치 (제1원칙 위반 경로)
- **영향범위**: server.py, ranking/calculator.py, 신규 공용 모듈 1개
- **리스크**: 중간 — 두 구현이 이미 다르게 동작 중이면 통일 시 랭킹 결과가 변할 수 있음. 통일 전 diff 분석 + 랭킹 결과 전후 비교 필수
- **난이도**: 중간 | **위임**: refactoring-expert (diff 분석 선행) + runner (전후 랭킹 비교)

### 6. [P1-3] server.py 1차 분할 (도메인 로직 추출)
- **무엇을**: 라우트가 아닌 순수 도메인 함수들(`calculate_head_to_head`, `compute_dual_de_final_rankings`, `transform_de_bracket`, DE 예측, `enrich_records_with_match_details` 등 약 2,000줄)을 `app/services/` 모듈로 추출. 라우트 분리는 이번 스코프에서 제외 (2차로)
- **왜**: God file 완화의 첫 단계 중 가장 안전한 절단면 (순수 함수라 이동 리스크 최소)
- **영향범위**: server.py, 신규 app/services/*.py 3-4개
- **리스크**: 중간 — import 경로·전역 캐시 참조 정리 필요. 프로덕션 PYTHONPATH 섀도잉 전례 있으므로 배포 경로 검증 필수
- **난이도**: 높음 | **위임**: refactoring-expert + runner (구동·주요 API 응답 비교 검증)

### 7. [P1-5] ruff 도입 + 자동 수정 가능한 것만 정리
- **무엇을**: ruff 설치(ARM64), 기본 설정 추가, `--fix` 안전 자동수정만 적용 (미사용 import 등). 수동 판단 필요한 경고는 목록만 보고
- **왜**: 정적 품질 기준선 확보
- **영향범위**: 전체 *.py (기계적 수정만), pyproject.toml 또는 ruff.toml 신규
- **리스크**: 낮음 (안전 수정만)
- **난이도**: 낮음 | **위임**: runner (설치·실행) + quality-engineer (설정)

### 8. [P2-2] de_scraper_v4.py 처리
- **무엇을**: 사용처 grep 확인 후 미사용이면 `scraper/backup/`으로 이동 (CLAUDE.md 스크래퍼 규칙 준수). full_scraper가 import 중이면 이동하지 않고 현황만 보고
- **영향범위**: scraper/ 파일 1개 이동
- **리스크**: 낮음 (사용처 확인 선행) | **난이도**: 낮음 | **위임**: runner

### 9. [P2-3] team_ranking.py 처리 결정
- **무엇을**: 387줄 미커밋 모듈 — (a) 완성해 통합, (b) 브랜치로 보존, (c) 폐기 중 **사용자 결정 필요**. 이 항목은 계획 아닌 질문
- **위임**: 사용자 판단

---

## 실행 순서 제안

```
1 (트리 정리) → 4 (테스트 환경) → 2, 3 (P0 보안) → 5 → 7 → 8 → 6 (가장 큰 작업 마지막)
```

- 1·4가 선행되어야 나머지 항목의 검증(커밋 단위·테스트)이 가능
- 3은 shared_core라 별도 브랜치(`feature/shared/*`) — 다른 항목과 커밋 섞지 않음
- 6은 리스크가 가장 크므로 테스트 환경(4) 복구 후에만 진행 권장

## 검증 방식 (공통)

- 테스트 복구 전 항목: `py_compile` + 서버 실제 구동 + 주요 API 응답 확인 ("테스트 부재 상태로 검증" 명시)
- 테스트 복구 후 항목: pytest + 구동 확인
- 각 항목 완료 시 개별 커밋, 실패 시 중단·보고

---

## 승인 기록

| # | 항목 | 승인 | 상태 |
|---|---|---|---|
| 1 | 작업 트리 정리 + 커밋 | ⏳ | - |
| 2 | 관리성 엔드포인트 인증 | ⏳ | - |
| 3 | JWT 시크릿 기본값 제거 | ⏳ | - |
| 4 | 테스트 환경 복구 | ⏳ | - |
| 5 | extract_age_group 통일 | ⏳ | - |
| 6 | server.py 1차 분할 | ⏳ | - |
| 7 | ruff 도입 | ⏳ | - |
| 8 | de_scraper_v4 backup 이동 | ⏳ | - |
| 9 | team_ranking.py 결정 | ⏳ | 사용자 결정 필요 |
