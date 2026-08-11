# EVAL — 현재 상태 평가

> 이 문서는 같은 경로에 독립적으로 작성된 두 개의 평가를 합친 것이다. Part A는 `services/data`(feature/data/main), Part B는 `services/app`(feature/app/hide-kakao) 평가로, 대상 서비스와 문제 번호 체계(P0/P1/P2)가 서로 독립적이다. 번호를 교차 참조하지 말 것.

---

## Part A — FencingMind-data 프로젝트 평가 (EVAL)

- **평가일**: 2026-07-09
- **평가 방식**: runner(사실 수집) + 지휘자 직접 아키텍처 분석 (deep-reasoner가 Opus 세션 한도로 실패하여 지휘자가 대체 수행)
- **범위**: services/data/ 전체 + packages/shared_core/ (읽기 전용, 수정 없음)

### ⚠️ Git 상태 특이사항 (평가 시점)

- 브랜치: `feature/data/main` (worktree)
- **수정 중 미커밋 파일 20개** — server.py, calculator.py, full_scraper.py, scheduler.py 등 핵심 파일 포함. 프로덕션에 반영된 코드와 git 이력이 불일치할 위험(롤백 불가 상태).
- **Untracked 63개** — 스크린샷 PNG 54개(루트 오염), `Hanes enginieering Md.zip`, 임시 파일 `templates/.!190!base.html`, 미커밋 신규 모듈 `ranking/team_ranking.py`(387줄), `services/data/data/`(audit_homonyms_report.json, international_cache)
- 3단계(수정) 진입 전 반드시 커밋 정리 필요.

---

### 1) 현재까지 진행된 것

#### 동작하는 것 (프로덕션 운영 중 — data.fencingmind.ai)
- FastAPI 서버: 82개 `@app.` 라우트 + auth/club 라우터 2개 (총 146 라우트 규모)
- Supabase 전체 데이터 인메모리 로드 + 캐시 (competitions 143, events 2,795, players 11,786+)
- 랭킹 계산 엔진 (NT 서브랭킹 포함, 2026-06-22 포인트 버그 수정 완료)
- 스크래퍼(full_scraper, Playwright) + 스케줄러(변경 감지, Guardian 연동)
- 7개 언어 i18n, H2H, FencingLab, 클럽 관리 SaaS, 3단계 접근 제어, Dual DE 대진표
- `python -m py_compile app/server.py` 통과 (문법 이상 없음)

#### 미완성 / 보류
- `ranking/team_ranking.py` (387줄, untracked) — 팀 랭킹 신규 모듈, 커밋도 통합도 안 된 상태
- 카카오 로그인 OAuth (계획 단계)
- `scripts/TODO_address_collection.md` 잔존 작업

#### 깨진 것 / 미검증
- **pytest 현재 환경(Python 3.14 homebrew)에 미설치** → 테스트 41개 파일이 있으나 실행 불가. 테스트 통과 여부 **미검증**
- 린터(ruff/flake8) 미설치 → 정적 품질 미검증
- 프로덕션 `JWT_SECRET_KEY` 환경변수 설정 여부 **미검증** (아래 P0-2 참조)

---

### 2) 구조 평가

#### 규모
| 항목 | 수치 |
|---|---|
| Python 파일 (backup 제외) | 100개 / 59,954줄 |
| server.py | **8,932줄, 82 라우트** |
| 템플릿 / JS / CSS | 32 / 5 / 8 |
| 테스트 파일 | 41개 (루트 tests/ + tests/unit/ + tests/e2e/ + services/data/tests/) |
| TODO/FIXME | 4개 (양호) |

#### 레이어링·응집도
- **server.py가 God file**: 라우팅 + 데이터 로딩 + 캐시 구축(build_player_index 등 6종) + i18n 헬퍼 + 도메인 로직(`calculate_head_to_head`, `compute_dual_de_final_rankings`, DE 예측, 선발 포인트 페이지)이 한 파일에 공존. `include_router`는 auth/club 2개뿐이고 나머지 82개 라우트는 전부 인라인.
- **전역 mutable 상태 17개** (server.py:595-611): `_data_cache`, `_player_index`, `_org_translation_cache` 등. DI 없음 → 단위 테스트가 전역 상태 몽키패칭에 의존하는 구조.
- **모듈 분리 자체는 양호**: scraper/, ranking/, scheduler/, data_pipeline/, app/club/, app/i18n/ 은 방향성 있는 분리. 의존 방향(스케줄러→스크래퍼→DB, 서버→랭킹)도 대체로 단방향.
- **shared_core 경계 양호**: app/auth는 shared_core re-export shim으로 정리되어 있고(models.py 확인), 역방향 의존 없음. 시크릿 하드코딩 코드 내 없음 (grep 검증).

#### 중복
- `extract_age_group()`이 **server.py:1369와 ranking/calculator.py:348에 각각 존재** — 나이그룹 파싱 규칙이 갈라지면 랭킹/필터 불일치 발생. 2026-06-22 PYTHONPATH 섀도잉 사고와 같은 계열의 드리프트 리스크.
- i18n 라우트가 `xxx_page` + `xxx_page_i18n` 쌍으로 전 페이지 중복 (얇은 위임이지만 보일러플레이트 다수).
- `scraper/de_scraper_v4.py`(1,855줄)가 backup이 아닌 scraper 루트에 잔존 — CLAUDE.md "full_scraper.py가 유일 메인" 규칙과 충돌 소지.

#### 캐시/파이프라인 (제1원칙 관점)
- 캐시 무효화 수단이 사실상 **전체 reload**(`load_data()`)뿐. 영문명 수정 시 `_player_translation_cache` 즉시 갱신처럼 국소 갱신도 있으나 체계 없음. 선수 프로필 수정→파생 데이터 전파를 보장하는 일반 메커니즘은 부재 (제1원칙 체크리스트의 "캐시 무효화 메커니즘" 미완).

---

### 3) 발견된 문제 분류

#### P0 (치명 — 보안/프로덕션 장애 가능)
| # | 문제 | 근거 | 방치 시 결과 |
|---|---|---|---|
| P0-1 | **관리성 엔드포인트 무인증**: `POST /api/data/reload`(server.py:2397), `POST /api/scheduler/run`(:8858), `GET /api/admin/validate`(:8883) 모두 인증 없음 | 코드 직접 확인 — `get_current_member` 호출 없음 | 외부인이 반복 호출로 전체 데이터 리로드/스크래퍼 강제 실행 → 서버 자원 고갈 + KFA 사이트에 무단 트래픽 (차단/법적 리스크) |
| P0-2 | **JWT 시크릿 기본값 폴백**: `JWT_SECRET_KEY: str = os.getenv(..., "your-secret-key-change-in-production")` | shared_core/auth/config.py:20 | 프로덕션에서 env 미설정 시 공개된 기본 키로 토큰 위조 가능 → 인증·접근제어 전체 무력화. (프로덕션 env 설정 여부는 미검증 — 확인 필요) |

#### P1 신규 (2026-07-10 실행 단계에서 ruff/env 확인으로 확정된 추가 결함)
| # | 문제 | 근거 | 방치 시 결과 |
|---|---|---|---|
| P1-A | **P0-2가 실제 활성 상태로 확정**: 프로덕션 launchd plist(com.fencingmind.data)에 `JWT_SECRET_KEY` env 없음 + `/opt/fencingmind/data/.env` 파일 부재 → 현재 프로덕션이 공개 기본키로 JWT 서명 중 | plist EnvironmentVariables 확인, .env 부재 확인 | 누구나 토큰 위조로 인증 전면 우회 가능 (지금 이 순간 노출) |
| P1-B | **undefined name `get_player_records`** — 선수 페이지 fallback 경로(identity_profile 없을 때)에서 미정의 함수 호출 | server.py:5572, grep으로 정의 부재 확인 (ruff F821) | identity 미해결 선수 페이지 접근 시 500 크래시 |
| P1-C | **undefined name `start_time`** — `get_de_only()`(full_scraper.py:1137)에서 초기화 없이 `time.time()-start_time` 사용 | full_scraper.py:1225 (ruff F821) | DE-only 스크래핑 경로에서 NameError로 중단 |
| P1-D | **중복 dict 키 16건** — location_codes.py의 지역 코드 매핑에서 같은 키 중복 정의(앞 값 소실) + auto_translate.py 번역 키 중복 | ruff F601 (location_codes.py 다수, auto_translate.py:1577) | 일부 지역/번역이 의도와 다르게 매핑 (조용한 데이터 오류) |
| P1-E | **date 재정의(F811)** — player_identity.py:1396에서 line 23의 `date` import를 지역 재정의 | ruff F811 | 섀도잉으로 인한 잠재 오동작 |

**ruff 정적 분석 기준선 (2026-07-10)**: services/data + packages 총 **347건** — F401 미사용 import 137, F541 빈 f-string 96, F841 미사용 변수 43, E402 29, F601 16, E722 bare-except 15, 기타. 234건 자동수정 가능.

#### P1 (중요 — 유지보수·운영 심각 저해)
| # | 문제 | 근거 | 방치 시 결과 |
|---|---|---|---|
| P1-1 | 핵심 파일 20개 미커밋 + untracked 63개 | git status | 롤백 불가, 실수 커밋 위험, 프로덕션-저장소 불일치 |
| P1-2 | 테스트 실행 환경 붕괴 (pytest 미설치, Python 3.14 homebrew ≠ ARM64 규칙 환경) | pytest collect 실패 로그 | 41개 테스트가 장식품화 — 회귀 감지 불능 상태로 프로덕션 변경 지속 |
| P1-3 | server.py God file (8,932줄) + 전역 상태 17개 | 구조 맵 | 변경 충돌·리뷰 불능·테스트 불가 악화. 신규 기능마다 비용 증가 |
| P1-4 | `extract_age_group` 중복 정의 (server.py ↔ calculator.py) | :1369 / :348 | 파싱 규칙 드리프트 → 랭킹/필터 데이터 불일치 (제1원칙 위반 경로) |
| P1-5 | 린터 부재 | ruff/flake8 미설치 | 죽은 코드·미사용 import·잠재 버그 누적 미탐지 |

#### P2 (개선)
| # | 문제 | 근거 |
|---|---|---|
| P2-1 | 루트 스크린샷 PNG 54개 + zip + `.!190!base.html` 임시 파일 오염 | git status |
| P2-2 | `de_scraper_v4.py` scraper 루트 잔존 (backup 규칙 위반 소지) | 파일 목록 |
| P2-3 | `team_ranking.py` 387줄 미커밋 방치 (완성/폐기 결정 필요) | untracked |
| P2-4 | requirements.txt 상한 없는 버전 지정, lockfile 부재 | requirements.txt |
| P2-5 | 테스트가 루트 `tests/`와 `services/data/tests/`로 분산 | 파일 목록 |
| P2-6 | i18n 라우트 쌍 중복 보일러플레이트 | server.py 구조 |

---

### 4) 테스트 유무와 커버리지

- **테스트 존재**: 41개 파일 (unit 12, e2e 3+, 루트 15, services/data 1). pytest.ini 있음. `.coverage` 파일 흔적 있음(과거 실행).
- **그러나 현재 실행 불가** — 현재 셸의 python3(3.14 homebrew)에 pytest 미설치. **사실상 "테스트 부재 상태"로 간주하고 3단계 검증은 빌드+실제 구동 확인 병행 필요.** pytest 환경 복구가 선행 과제.
- 커버리지 수준: **미검증** (실행 불가로 측정 불가).

---

## Part B — services/app 현재 상태 평가

**작성일**: 2026-07-09
**브랜치**: `feature/app/hide-kakao` (평가 시작 시점 작업 트리 깨끗, master 대비 +26커밋 / 뒤짐 0)
**평가 방식**: 읽기 전용. deep-reasoner(아키텍처 심층 평가) + runner(사실 수집·테스트/린트 실행) 병렬 위임 후 종합.
**범위**: 이 워크트리의 담당 영역인 `services/app/` (PWA/알림 허브). 워크트리 규칙상 수정 가능 범위도 여기까지.

---

### 1) 현재까지 진행된 것

#### 동작하는 것 (검증됨)
- **Phase 1~7 로드맵 전체 구현 완료** (31개 파일, 약 3,356줄): scaffold, PWA(manifest/SW/offline), 알림 설정 UI+API, 이벤트 폴러+디스패처, FCM 웹 푸시, iOS 설치 배너, 오프라인 강화
- **서버 임포트 스모크 테스트 통과**: FastAPI 앱 정상 로드, 19개 라우트 등록
- **테스트 5/5 통과** (venv + 의존성 설치 후 실행): 카카오 디스패처의 pending 처리, 멱등 스킵, httpx 부재 graceful, 전화번호 정규화
- **ruff 린트 통과**: 에러 0, 경고 0
- **i18n 실제 연동됨**: `LanguageMiddleware` 등록(`server.py:65`), 템플릿에서 `t()` 실사용(settings 25회, home 14회, base 11회) — 루트 CLAUDE.md의 "연동 예정" 표기보다 진척됨
- **TODO/FIXME/HACK 주석 0건**

#### 미완성 / 보류
- **카카오 알림톡(Phase 6)**: 의도적 보류. `ENABLE_KAKAO_ALIMTALK=false` + 설정 pref 이중 게이트로 실행 경로에서 제외, 코드/DB 컬럼/env 보존. 실행 경로상 깔끔하나 JS 잔재 1건 있음(P2-6)
- **FCM 실발송**: 코드 완성, VAPID 키/pywebpush 환경 세팅 대기 (미설정 시 graceful `pending`)
- **알림 콘텐츠 i18n**: 알림 본문이 한국어 하드코딩 (P2-3)

#### 깨진 것
- 없음 (동작 불가 수준 결함 미발견). 단, 아래 P1들은 **수평 확장·동시 이벤트 기록·전송 실패 조건에서 알림 유실/중복**으로 발현되는 잠복 결함.

---

### 2) 구조 평가

#### 강점 (근거 확인됨)
- **레이어링 적절**: `app/`(server·config) / `auth/`(shim) / `notifications/`(router·service) / `pipeline/`(poller·dispatcher·kakao·event_types) — 관심사 분리 명확
- **보안 기본기**: 쓰기 엔드포인트 전부 회원 id를 JWT에서 파생(IDOR 없음, `notifications/router.py:79,108,127`), JWT 알고리즘 명시 검증(`shared_core/auth/jwt.py:57-61`)
- **폴러가 이벤트 루프 미차단**: 동기 supabase 호출을 `asyncio.to_thread`로 오프로드(`poller.py:127`)
- **SW 캐시 전략이 CLAUDE.md 정책과 일치**: static→cache-first, API/auth→network-only, HTML→network-first+offline 폴백, 버전 불일치 캐시 purge(`service-worker.js:36-73`)
- **graceful degradation 일관**: VAPID/pywebpush/httpx 부재 시 크래시 대신 `pending` 로그(`dispatcher.py:197-208`, `kakao.py:95-99`)
- **모노레포 규칙 준수**: 수정 범위 services/app 한정, 테이블 전부 `app_*`, migration 021 신규 파일만, auth shim data 패턴 동일, CORS 정확
- **의존성 최소**: pywebpush, httpx 2개만 서비스 고유 (경량 자체 .env 로더로 python-dotenv 불필요)

#### 약점 (구조 차원)
- 폴링 파이프라인의 전달 보증이 사실상 "0~1회" — 어느 층도 정확히 1회 전달을 보장 못 함 (P1-1~4 복합)
- `pending`/`failed` 로그는 성실히 기록되나 이를 소비·재시도하는 주체가 없어 사후 부검용에 그침
- 보안 기본값이 "열림" (RLS `true/true`)

---

### 3) 발견된 문제 분류

#### P0 (치명) — 없음
단, P1-1~4는 확장/장애/재스크래핑 조건에서 알림 유실·중복·스팸으로 악화되므로 데이터 신뢰가 생명인 이 프로젝트 기준 **P0에 준해 처리 권장**.

#### P1 (중요)

| # | 문제 | 근거 | 실패 시나리오 |
|---|------|------|--------------|
| P1-1 | **전송 실패 = 영구 유실**. 커서가 배치 max(id)로 무조건 전진, 디스패처는 예외 흡수 후 `failed` 로그만. 재시도 경로 부재 | `poller.py:112,116`, `dispatcher.py:178-181,220-223` | 발송 순간 Supabase 일시 오류 → failed 기록 → 커서 통과 → 해당 알림 영원히 미발송 |
| P1-2 | **id 워터마크의 커밋 순서 경쟁**. BIGSERIAL은 커밋 순서 무보장인데 `.gt("id", last_id)` 사용 | `poller.py:90-96`, migration `005:10` | id=101이 100보다 먼저 커밋 → 폴링이 101 처리·커서 전진 → 늦게 커밋된 100 영구 누락. (data 측 동시 기록 여부는 미검증) |
| P1-3 | **다중 폴러 = 중복 발송**. 멱등성이 SELECT→INSERT 방식, `app_notification_log`에 UNIQUE 제약 없음, 리더 락 없이 lifespan마다 폴러 무조건 생성 | `dispatcher.py:341-359`, `server.py:40-42`, migration `021:79-80` | uvicorn workers>1 또는 인스턴스 2개 → 같은 배치 N회 디스패치, 경쟁으로 둘 다 INSERT. 현재 단일 인스턴스라 잠복 |
| P1-4 | **재스크래핑 시 알림 스팸**. 멱등키가 data_events 행 id 기준 → 대회 정정마다 새 행 = 참가 선수 전원에 재알림 | `dispatcher.py:351-353`, `event_types.py:20-21` | 정정 재스크래핑 1회 = 전원 스팸 1회. 엔티티 단위 dedup/cool-down 없음 |
| P1-5 | **RLS 무력화 — PII 노출면**. app_* 4개 테이블 정책이 `USING(true) WITH CHECK(true)` | migration `021:107-121` | anon 키 유출 시 전 회원 푸시 구독(엔드포인트/키)·설정·발송 이력 열람/조작 가능 |
| P1-6 | **테스트가 비활성 기능만 커버**. 유일 테스트가 숨김 처리된 카카오 경로만 검증. 운영 경로(인앱/웹푸시/타깃 결정/폴러 커서/메시지 빌드) 테스트 0 | `tests/test_dispatcher_kakao.py` | P1-1~4의 실제 위험을 어떤 테스트도 안 만짐. 페이크 DB 필터가 no-op이라 쿼리 정확성 검증 불가 |

#### P2 (개선)

| # | 문제 | 근거 |
|---|------|------|
| P2-1 | `.in_(대량 player_id 리스트)` → PostgREST URI 414 위험, 청크 분할 필요 | `dispatcher.py:114-117,139` |
| P2-2 | 배치 100건/30초 = 최대 200건/분 → 대량 백필 시 수 시간 지연 | `poller.py:95` |
| P2-3 | 알림 본문 한국어 하드코딩 — 7개 언어 플랫폼과 불일치 | `event_types.py:44-53` |
| P2-4 | prefs/subscriptions `updated_at` 미갱신 (트리거·update 미설정) | `service.py:122-151,189-195` |
| P2-5 | offline.html 다크 테마 고정 — 라이트 언어(ko/ja/zh)에도 다크 | `offline.html:16-30` |
| P2-6 | 카카오 숨김 JS 잔재: PATCH 페이로드가 `kakao_alimtalk` 여전히 전송 (토글 부재 시 동작 미검증) | `settings.html:259` |
| P2-7 | `dispatched` 메트릭이 in_app만 합산 — web_push 누락 | `poller.py:108` |
| P2-8 | `event.created` 미매핑 (competition.created는 매핑) — 의도/누락 불명확 | `event_types.py:18-22` |

#### 운영 메모 (코드 외)
- `services/app/.env`에 실제 VAPID 개인키·JWT_SECRET_KEY 평문 존재(git 미추적, 유출 없음). 과거 채팅 노출 이력이 주석에 언급됨 → **운영 전 키 재발급 권장**
- pytest/ruff가 시스템에 미설치 (Homebrew Python 3.14 PEP 668) → 평가 중 venv(/tmp/fm_test_env)로 실행. 반복 가능한 테스트 환경 부재

---

### 4) 테스트 유무와 커버리지

- **테스트 존재**: `tests/test_dispatcher_kakao.py` 1파일 5케이스 (5/5 통과)
- **커버리지 수준**: 사실상 **비활성(카카오) 경로만**. 운영 핵심인 인앱 발송, 웹 푸시, 타깃 결정(`_resolve_targets`/`_players_for_result`), 폴러 커서 로직, 이벤트→카테고리 매핑, 메시지 빌드는 **테스트 부재**
- 3단계 검증 시사점: 파이프라인 수정 항목은 **테스트 신규 작성 + 실행**으로 검증해야 하며, UI/템플릿 항목은 서버 구동 확인으로 대체

### 미검증 항목 (명시)

1. data 서비스 EventPublisher의 동시 기록 여부 (P1-2 발동 조건) — data 워크트리 범위라 미확인
2. `settings.html:259`의 `get('kakao_alimtalk')`가 토글 부재 시 예외인지 false인지 — 런타임 미실행
3. 프로덕션 uvicorn worker 수 (P1-3 발동 조건)
4. FCM 실발송 (VAPID 키 환경 필요)
