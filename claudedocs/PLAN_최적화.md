# PLAN — 최적화 수정 계획

> 이 문서는 같은 경로에 독립적으로 작성된 두 개의 계획을 합친 것이다. Part A는 `services/data`, Part B는 `services/app` 대상이며, 각각 자기 Part의 EVAL(`claudedocs/EVAL_현재상태.md`의 동일 Part)을 근거로 한다. 항목 번호는 Part 안에서만 유효하다.

---

## Part A — FencingMind-data 최적화 수정 계획 (PLAN)

- **작성일**: 2026-07-09
- **근거**: claudedocs/EVAL_현재상태.md
- **작성자**: 지휘자(Fable 5) 직접 — deep-reasoner(Opus)가 세션 한도로 불가하여 대체
- **원칙**: 되돌리기 쉬운 것부터, P0 우선, 신기능 제안 금지(YAGNI)
- **상태**: ⏳ 승인 대기 — 승인된 번호만 3단계에서 실행

---

### 항목 목록 (우선순위 순)

#### 1. [P1-1] 작업 트리 정리 + 커밋 ✋ 모든 항목의 선행 조건
- **무엇을**: (a) 수정 중인 20개 파일을 논리 단위로 검토·커밋, (b) 스크린샷 PNG 54개·zip·임시파일을 삭제 또는 `docs/screenshots/`로 이동, (c) `.gitignore`에 `*.png`(루트), `.coverage`, `services/data/data/` 추가
- **왜**: 롤백 가능 상태 확보. 3단계 가드레일("작업 트리 깨끗한지 확인") 충족 전제
- **영향범위**: git 이력, .gitignore (코드 로직 무변경)
- **리스크**: 낮음 (삭제 전 PNG 목록 사용자 확인)
- **난이도**: 낮음 | **위임**: runner(파일 이동/정리) + 지휘자(커밋 단위 판단)

#### 2. [P0-1] 관리성 엔드포인트 인증 추가
- **무엇을**: `POST /api/data/reload`, `POST /api/scheduler/run`, `GET /api/admin/validate*` 에 admin 권한 검사 추가 (기존 `get_current_member` + member_type=admin 재사용). 스케줄러 내부 호출(`_refresh_server_cache`)은 localhost 예외 또는 내부 토큰으로 유지
- **왜**: 외부인이 데이터 리로드/스크래퍼 실행 가능 — 자원 고갈 + KFA 무단 트래픽 리스크
- **영향범위**: services/data/app/server.py (3-4개 엔드포인트), scheduler/scheduler.py의 캐시 갱신 호출부
- **리스크**: 중간 — 스케줄러의 자체 캐시 갱신 경로가 막히면 자동 갱신 중단. 수정 후 스케줄러 경로 구동 검증 필수
- **난이도**: 낮음~중간 | **위임**: security-engineer (구현) + runner (구동 검증)

#### 3. [P0-2] JWT_SECRET_KEY 기본값 제거
- **무엇을**: shared_core/auth/config.py:20의 폴백 기본값 제거 → 미설정 시 기동 실패(fail-fast)로 변경. 먼저 프로덕션 launchd env에 실제 키 설정 여부 확인
- **왜**: 공개된 기본 키로 토큰 위조 가능 → 인증 전체 무력화
- **영향범위**: packages/shared_core/auth/config.py — ⚠️ **R2 규칙**: shared_core 수정은 `feature/shared/*` 브랜치에서 해야 함. 별도 브랜치·별도 커밋으로 분리
- **리스크**: 중간 — 프로덕션 env 미설정 상태에서 배포하면 서버 기동 실패. 반드시 env 확인 → 키 설정 → 코드 변경 순서
- **난이도**: 낮음 | **위임**: security-engineer + runner (프로덕션 env 확인)

#### 4. [P1-2] 테스트 실행 환경 복구 + 현재 통과율 측정
- **무엇을**: ARM64 규칙(`arch -arm64 python3 -m pip install`)에 맞춰 pytest 설치, 41개 테스트 실행, 통과/실패 현황을 문서화. 코드 수정은 하지 않고 현황 파악까지만
- **왜**: 이후 모든 리팩터링 항목의 검증 수단 확보 (현재는 회귀 감지 불능)
- **영향범위**: 환경만 (코드 무변경)
- **리스크**: 낮음
- **난이도**: 낮음 | **위임**: runner (설치·실행) + quality-engineer (실패 분석)

#### 5. [P1-4] extract_age_group 중복 통일
- **무엇을**: server.py:1369와 calculator.py:348의 `extract_age_group`을 비교해 단일 구현으로 통일 (공용 모듈로 추출, 양쪽에서 import)
- **왜**: 나이그룹 파싱 규칙 드리프트 → 랭킹/필터 불일치 (제1원칙 위반 경로)
- **영향범위**: server.py, ranking/calculator.py, 신규 공용 모듈 1개
- **리스크**: 중간 — 두 구현이 이미 다르게 동작 중이면 통일 시 랭킹 결과가 변할 수 있음. 통일 전 diff 분석 + 랭킹 결과 전후 비교 필수
- **난이도**: 중간 | **위임**: refactoring-expert (diff 분석 선행) + runner (전후 랭킹 비교)

#### 6. [P1-3] server.py 1차 분할 (도메인 로직 추출)
- **무엇을**: 라우트가 아닌 순수 도메인 함수들(`calculate_head_to_head`, `compute_dual_de_final_rankings`, `transform_de_bracket`, DE 예측, `enrich_records_with_match_details` 등 약 2,000줄)을 `app/services/` 모듈로 추출. 라우트 분리는 이번 스코프에서 제외 (2차로)
- **왜**: God file 완화의 첫 단계 중 가장 안전한 절단면 (순수 함수라 이동 리스크 최소)
- **영향범위**: server.py, 신규 app/services/*.py 3-4개
- **리스크**: 중간 — import 경로·전역 캐시 참조 정리 필요. 프로덕션 PYTHONPATH 섀도잉 전례 있으므로 배포 경로 검증 필수
- **난이도**: 높음 | **위임**: refactoring-expert + runner (구동·주요 API 응답 비교 검증)

#### 7. [P1-5] ruff 도입 + 자동 수정 가능한 것만 정리
- **무엇을**: ruff 설치(ARM64), 기본 설정 추가, `--fix` 안전 자동수정만 적용 (미사용 import 등). 수동 판단 필요한 경고는 목록만 보고
- **왜**: 정적 품질 기준선 확보
- **영향범위**: 전체 *.py (기계적 수정만), pyproject.toml 또는 ruff.toml 신규
- **리스크**: 낮음 (안전 수정만)
- **난이도**: 낮음 | **위임**: runner (설치·실행) + quality-engineer (설정)

#### 8. [P2-2] de_scraper_v4.py 처리
- **무엇을**: 사용처 grep 확인 후 미사용이면 `scraper/backup/`으로 이동 (CLAUDE.md 스크래퍼 규칙 준수). full_scraper가 import 중이면 이동하지 않고 현황만 보고
- **영향범위**: scraper/ 파일 1개 이동
- **리스크**: 낮음 (사용처 확인 선행) | **난이도**: 낮음 | **위임**: runner

#### 9. [P2-3] team_ranking.py 처리 결정
- **무엇을**: 387줄 미커밋 모듈 — (a) 완성해 통합, (b) 브랜치로 보존, (c) 폐기 중 **사용자 결정 필요**. 이 항목은 계획 아닌 질문
- **위임**: 사용자 판단

---

### 실행 순서 제안

```
1 (트리 정리) → 4 (테스트 환경) → 2, 3 (P0 보안) → 5 → 7 → 8 → 6 (가장 큰 작업 마지막)
```

- 1·4가 선행되어야 나머지 항목의 검증(커밋 단위·테스트)이 가능
- 3은 shared_core라 별도 브랜치(`feature/shared/*`) — 다른 항목과 커밋 섞지 않음
- 6은 리스크가 가장 크므로 테스트 환경(4) 복구 후에만 진행 권장

### 검증 방식 (공통)

- 테스트 복구 전 항목: `py_compile` + 서버 실제 구동 + 주요 API 응답 확인 ("테스트 부재 상태로 검증" 명시)
- 테스트 복구 후 항목: pytest + 구동 확인
- 각 항목 완료 시 개별 커밋, 실패 시 중단·보고

---

### 승인 기록 및 실행 결과 (2026-07-10 완료)

사용자 승인: "전부 진행, 6번 포함". 브랜치 `refactor/eval-20260710-exec`.

| # | 항목 | 상태 | 커밋 | 비고 |
|---|---|---|---|---|
| 1 | 작업 트리 정리 + 커밋 | ✅ 완료 | 7개 커밋 | 미커밋 20파일 정리, PNG 54개 docs/screenshots/ 이동, .gitignore 갱신, 트리 clean |
| 2 | 관리성 엔드포인트 인증 (P0) | ✅ 완료 | 06babe2 | require_admin_or_internal 게이트 5개 엔드포인트 + 스케줄러 내부토큰 헤더 |
| 3 | JWT 시크릿 기본값 제거 (P0) | ✅ 완료 | b86778d | fail-fast. ⚠️ 배포 전 프로덕션 env 설정 필수 (아래 미결 참조) |
| 4 | 테스트 환경 복구 | ✅ 완료 | (환경) | Python 3.13 pytest 복구. 전체 514통과/170실패(네트워크 의존). 오프라인 기준선 218통과/14실패(기존 stale) 확보 |
| 5 | extract_age_group 통일 | ✅ 재조정 완료 | deac6f3 | 두 함수가 13개 입력서 버킷 자체 불일치 → 병합 불가. 특성화 테스트 117개로 현행 고정 + 불일치 문서화 |
| 6 | server.py 1차 분할 | ✅ 완료 | 6e1450b | DE/bout 변환 9함수 → app/de_transforms.py. server.py 8932→8299줄. AST 동일성 검증 |
| 7 | ruff 도입 | ✅ 완료 | 08d6eda | 234건 자동수정/72파일 + ruff.toml. 회귀 없음 |
| 8 | de_scraper_v4 backup 이동 | ✅ 불필요 확정 | - | full_scraper.py:23이 실제 import하는 활성 DE 모듈. 이동 안 함 |
| 9 | team_ranking.py 결정 | ✅ 보존 처리 | 1cf7aaf | 커밋으로 보존 + server.py 팀랭킹 API 연동 상태로 통합 |

#### 실행 중 신규 발견·처리
- **P1 크래시 2건** (485190e): server.py `get_player_records` 미정의 → 선수페이지 500 크래시 수정; full_scraper `start_time` 미정의 → 스크래퍼 NameError 수정 (ruff F821로 발견)
- **잠재 랭킹 버그** (미수정, 문서화): calculator.py의 age classifier가 카뎃/Junior/고교/14~16세이하/U23 이벤트를 SR로 오분류. 랭킹 의미 변경이라 데이터 소유자 판단 대기 (docs/AGE_GROUP_DIVERGENCE.md)

#### 🔴 배포 전 필수 (사람이 할 일 — 코드 아님)
1. **프로덕션 JWT 키 설정**: 현재 프로덕션 launchd(com.fencingmind.data)에 `JWT_SECRET_KEY` 미설정 → 공개 기본키로 가동 중(토큰 위조 가능). 배포 시 plist EnvironmentVariables에 강력 랜덤 `JWT_SECRET_KEY` 추가 **필수** (없으면 fail-fast로 기동 실패). 키 설정 시 기존 세션 전원 재로그인 발생.
2. **INTERNAL_API_TOKEN 설정**: 스케줄러 캐시 갱신용. plist에 추가.
3. **shared_core R2**: config.py(b86778d)는 data 브랜치에 커밋됨 → feature/shared/* 브랜치로 cherry-pick 필요.
4. **배포 전 전체 테스트**: 오프라인 커버리지가 route/domain 레이어를 못 덮으므로, 배포 전 네트워크 포함 전체 pytest(약 1.5h) 1회 권장.

---

## Part B — services/app 최적화 수정계획

**작성일**: 2026-07-09
**근거**: `claudedocs/EVAL_현재상태.md` (P1-1~6, P2-1~8)
**작성**: deep-reasoner 위임 결과를 오케스트레이터가 정리
**전제**: 수정 범위는 `services/app/` 내부 + `database/migrations/` **신규 파일 추가만**. `packages/shared_core/`·타 서비스·기존 마이그레이션 미수정. 마이그레이션 번호는 022부터 부여(착수 시점 재확인).

핵심 설계 판단:
- **P1-5(RLS)**: shared_core는 수정 금지이므로 app 내부에 service_role 전용 로컬 클라이언트(`services/app/app/db.py`)를 신설해 경계 유지.
- **`app_notification_log` ALTER가 여러 항목에 걸침**(3·4·5): 개별 승인·롤백 가능하게 마이그레이션 파일 분리, 함께 승인되면 스쿼시 가능.

---

### 항목별 계획

#### 1. 운영 경로 특성화 테스트 신설 (P1-6) — 난이도 M, 우선순위 1
- **무엇을**: `tests/`에 활성 경로 테스트 추가 — `dispatcher._send_in_app`, `_resolve_targets`, `_players_for_result`, `event_types.category_for_event`/`build_message`, `poller.poll_once` 커서 전진. 기존 페이크 DB의 `.eq()/.in_()/.gt()` no-op을 실제 필터를 흉내내는 페이크로 교체(`tests/_fakes.py` 신설).
- **왜**: 활성 파이프라인 테스트 0(P1-6). 이후 모든 변경의 회귀 안전망.
- **영향**: `services/app/tests/` 신규 파일만. 프로덕션 코드 무변경.
- **리스크**: 없음(순수 추가). 되돌리기 = 파일 삭제.
- **검증**: 자기 자신. 현재 동작을 특성화로 고정 후 항목 2~6이 갱신.
- **위임**: quality-engineer

#### 2. 워터마크 안전 지연 (P1-2 최소 처방) — 난이도 S, 우선순위 2
- **무엇을**: `poller.poll_once` 조회에 `created_at < now() - safety_lag` 필터 추가. `config.py`에 `EVENT_SAFETY_LAG_SECONDS`(기본 15초) 신설. 워터마크는 id 유지.
- **왜**: BIGSERIAL 커밋 순서 무보장으로 늦게 커밋된 낮은 id 영구 누락(P1-2). data 측 동시성 미검증이므로 저비용 보험만(과설계 회피).
- **영향**: `poller.py`, `config.py`.
- **리스크**: 매우 낮음. 알림 최대 15초 지연(무해). 되돌리기 = 필터 제거.
- **검증**: created_at 섞은 배치로 lag 미경과 이벤트 제외 확인(항목 1 확장).
- **위임**: backend-architect

#### 3. 로그 UNIQUE 제약 + 중복삽입 내성 (P1-3) — 난이도 M, 우선순위 3
- **무엇을**: 신규 마이그레이션 `022_app_notification_log_unique.sql` — (a) 기존 중복 행 정리, (b) `UNIQUE(member_id,channel,event_type,event_id)` 추가. `dispatcher._already_sent` 예외 시 `False` 반환 재검토.
- **왜**: 앱 레벨 SELECT→INSERT만으로는 다중 폴러 경쟁 시 중복 발송(P1-3). DB UNIQUE가 "정확히 1회"의 최종 방어선.
- **영향**: `database/migrations/022_*.sql`(신규), `dispatcher.py`(소폭).
- **리스크**: 낮음(기존 코드가 예외 흡수). **주의**: dedupe 전 프로덕션 중복 건수 조회 필수. 되돌리기 = DROP CONSTRAINT 신규 마이그레이션.
- **검증**: 동일 키 2회 삽입 시 1행 유지 + 마이그레이션 dry-run 카운트.
- **위임**: backend-architect + security-engineer 리뷰
- **의존**: 항목 4·5가 이 제약에 의존.

#### 4. 실패/보류 알림 재시도 스윕 (P1-1) — 난이도 M~L, 우선순위 5
- **무엇을**: 신규 마이그레이션 `023_app_notification_log_retry.sql` — `attempt_count`, `last_attempt_at` 컬럼 추가. 폴 사이클마다 `_retry_failed_once()` — `failed/pending` AND `attempt_count<3` AND 24h 이내 행 재발송, 성공 시 `sent`로 UPDATE.
- **왜**: 전송 실패 시 영구 유실(P1-1)의 유일한 복구 경로. attempt cap + age window로 poison 무한재시도 방지. VAPID 키 도착 시 pending 자동 재시도 부수효과(긍정적).
- **영향**: `023_*.sql`(신규), `poller.py`, `dispatcher.py`.
- **리스크**: 중간 — 재시도발 중복은 항목 3 UNIQUE가 방어. 되돌리기 = 스윕 호출 제거.
- **검증**: 신규 테스트 필수 — failed→sent 전이, 3회 초과 중단, 24h 경과 제외.
- **위임**: backend-architect
- **의존**: 항목 3 이후.

#### 5. 엔티티 단위 재정정 스팸 억제 (P1-4) — 난이도 M, 우선순위 6
- **무엇을**: 신규 마이그레이션 `024_app_notification_log_dedup.sql` — `dedup_key` 컬럼+인덱스. 발송 전 `{category}:{entity_type}:{entity_id}` 키로 쿨다운 창(`NOTIFY_DEDUP_COOLDOWN_HOURS`, 기본 6h — **제품 확정 필요**) 내 `sent` 존재 시 skip.
- **왜**: 정정 재스크래핑마다 새 data_events 행 → 전원 재알림 스팸(P1-4).
- **영향**: `024_*.sql`(신규), `dispatcher.py`, `config.py`.
- **리스크**: 중간 — 쿨다운 과대 시 정당한 재알림 누락. 되돌리기 = 게이트 제거.
- **검증**: 신규 테스트 — 6h 내 2회째 skip, 창 경과 후 재발송.
- **위임**: backend-architect
- **의존**: 항목 3 이후(같은 테이블).

#### 6. RLS 잠금 — service_role 전환 + 정책 교체 (P1-5) — 난이도 L, 우선순위 8
- **무엇을**: 2단계 **순서 엄수**.
  - **A(코드 선행)**: `services/app/app/db.py` 신설 — `SUPABASE_SERVICE_KEY`(env 신규)로 service_role 클라이언트. poller/dispatcher/service가 이를 사용. service_role은 RLS 우회 → 현행 정책에서도 정상 동작(무중단 하위호환).
  - **B(마이그레이션, A 라이브 확인 후)**: `025_app_tables_rls_lockdown.sql` — `USING(true)` 정책 제거, anon 차단.
- **왜**: anon 키로 전 회원 푸시구독/이력/설정 열람·조작 가능(P1-5). 순서를 뒤집으면 서버가 죽음 → A→B 불변.
- **영향**: `db.py`(신규), `poller.py`/`dispatcher.py`/`notifications/service.py`/`config.py`, `025_*.sql`(신규).
- **리스크**: **높음** — 키 오설정 시 DB 접근 상실. 롤백 난이도 최고. **사람 선행조건: SUPABASE_SERVICE_KEY 발급/주입.**
- **검증**: 신규 테스트 + 스테이징 — service_role 주입 후 CRUD 동작, 정책 적용 후 anon SELECT 차단 확인.
- **위임**: security-engineer

#### 7. `.in_()` 대량 리스트 청크 분할 (P2-1) — 난이도 S~M, 우선순위 7
- **무엇을**: `dispatcher.py:114-117,139`의 `.in_(list)`를 200개 단위 분할 조회 헬퍼로 교체.
- **왜**: 대형 대회 수천 id → PostgREST 414 가능(P2-1).
- **영향**: `dispatcher.py`. **리스크**: 낮음.
- **검증**: 250개 초과 id 분할 호출·합산 테스트. **위임**: refactoring-expert

#### 8. 저비용 정리 묶음 (P2-6/7/8) — 난이도 S, 우선순위 4
- **무엇을**: (a) `settings.html:259` 죽은 `kakao_alimtalk` 페이로드 잔재 제거 + 토글 부재 시 예외 여부 확인, (b) `poller.py:108` dispatched 메트릭에 web_push 반영, (c) `event.created` 매핑 누락 — 의도면 주석, 누락이면 추가(**제품 판단 필요**).
- **영향**: `settings.html`, `poller.py`, `event_types.py`. **리스크**: 낮음((c)만 발송 대상 변화 가능).
- **검증**: 항목 1 테스트에 케이스 포함. **위임**: refactoring-expert

**보류(YAGNI 초과로 제외)**: P2-2(배치 드레인 튜닝), P2-3(알림 본문 i18n — 별도 트랙 권장), P2-4(updated_at 트리거), P2-5(offline.html 테마).

---

### 의존 관계
```
항목1(테스트) ──▶ 모든 항목의 안전망 (선행)
항목3(UNIQUE) ──▶ 항목4(재시도), 항목5(dedup)
항목6(RLS): A(코드)▶B(정책) 순서 불변 + 외부 키 발급 선행
항목2·7·8: 독립
```

### 권장 승인 세트

| 세트 | 구성 | 효과 | 전제 |
|------|------|------|------|
| **최소** | 1+2+3+8 | P1-2 누락·P1-3 중복 봉쇄 + 안전망. 마이그레이션 1개, 전부 저위험 | 없음 |
| **표준 (권장)** | 최소 + 4+5+7 | P1-1 유실·P1-4 스팸까지 해소 — "정확히 1회 전달" 사실상 완성 | 없음 |
| **전체** | 표준 + 6 | P1 전량 해소 (보안 잠금) | SUPABASE_SERVICE_KEY 발급 + A→B 순차 배포 + 스테이징 검증 |

### 미검증/판단 필요
1. 항목 5 쿨다운 6h — 제품 확정 필요
2. 항목 8(c) event.created 발송 여부 — 제품 판단
3. 항목 3 dedupe 전 프로덕션 중복 건수 — 착수 시 조회 필수
4. 항목 6 service_role 키 발급 — 사람 선행조건

---

### 진행 상태 (3단계 — 승인: 전체 세트)

브랜치: `refactor/eval-20260710`. 전체 테스트 venv(`/tmp/fm_test_env`) + 시스템 python 임포트 스모크로 각 항목 검증.

| 항목 | 상태 | 커밋 | 비고 |
|------|------|------|------|
| 1 특성화 테스트 | ✅ 완료 | da54fc2 | 67 테스트(신규 62). 필터링 페이크 도입 |
| 2 안전 지연 | ✅ 완료 | 92a2b4d | EVENT_SAFETY_LAG_SECONDS=15, 스키마 변경 없음 |
| 3 UNIQUE 제약 | ✅ 완료 | 11e6574 | **마이그레이션 022 파일만 — 미적용** (중복 건수 조회 후 적용) |
| 8 정리 묶음 | ✅ 완료 | 82043ad | 카카오 잔재/web_push 메트릭/event.created 주석 |
| 4 재시도 스윕 | ✅ 완료 | a1cd33d | **마이그레이션 023 파일만 — 미적용** (022 의존) |
| 5 재정정 억제 | ✅ 완료 | 209ce3e | **마이그레이션 024 파일만 — 미적용**. 쿨다운 6h |
| 7 청크 분할 | ✅ 완료 | 3dd6fb0 | 200개 배치 |
| 6 RLS 잠금 | ✅ 완료 | ee51977 | Part A(코드, anon 폴백) 커밋 / **Part B 마이그레이션 025 미적용** (SERVICE_KEY 발급 후 적용) |

**전체 104개 테스트 통과, 서버 임포트 정상. 8개 항목 전부 코드 완료.**

#### 🔴 사람이 해야 할 선행조건 / 후속 조치
1. **마이그레이션 022·023·024 프로덕션 적용** (순서대로). 022 적용 전 중복 건수 조회(022 헤더 SQL 참조).
2. **항목 6**: `SUPABASE_SERVICE_KEY` 발급 → 프로덕션 env 주입 → 서버 재시작(anon 폴백 warning 없음 확인) → **그 다음에** 마이그레이션 025 적용.
3. 마이그레이션 파일들은 코드로 검증됐으나 **실제 Supabase 스키마에는 미반영** 상태.
