# EVAL — services/app 현재 상태 평가

**작성일**: 2026-07-09
**브랜치**: `feature/app/hide-kakao` (평가 시작 시점 작업 트리 깨끗, master 대비 +26커밋 / 뒤짐 0)
**평가 방식**: 읽기 전용. deep-reasoner(아키텍처 심층 평가) + runner(사실 수집·테스트/린트 실행) 병렬 위임 후 종합.
**범위**: 이 워크트리의 담당 영역인 `services/app/` (PWA/알림 허브). 워크트리 규칙상 수정 가능 범위도 여기까지.

---

## 1) 현재까지 진행된 것

### 동작하는 것 (검증됨)
- **Phase 1~7 로드맵 전체 구현 완료** (31개 파일, 약 3,356줄): scaffold, PWA(manifest/SW/offline), 알림 설정 UI+API, 이벤트 폴러+디스패처, FCM 웹 푸시, iOS 설치 배너, 오프라인 강화
- **서버 임포트 스모크 테스트 통과**: FastAPI 앱 정상 로드, 19개 라우트 등록
- **테스트 5/5 통과** (venv + 의존성 설치 후 실행): 카카오 디스패처의 pending 처리, 멱등 스킵, httpx 부재 graceful, 전화번호 정규화
- **ruff 린트 통과**: 에러 0, 경고 0
- **i18n 실제 연동됨**: `LanguageMiddleware` 등록(`server.py:65`), 템플릿에서 `t()` 실사용(settings 25회, home 14회, base 11회) — 루트 CLAUDE.md의 "연동 예정" 표기보다 진척됨
- **TODO/FIXME/HACK 주석 0건**

### 미완성 / 보류
- **카카오 알림톡(Phase 6)**: 의도적 보류. `ENABLE_KAKAO_ALIMTALK=false` + 설정 pref 이중 게이트로 실행 경로에서 제외, 코드/DB 컬럼/env 보존. 실행 경로상 깔끔하나 JS 잔재 1건 있음(P2-6)
- **FCM 실발송**: 코드 완성, VAPID 키/pywebpush 환경 세팅 대기 (미설정 시 graceful `pending`)
- **알림 콘텐츠 i18n**: 알림 본문이 한국어 하드코딩 (P2-3)

### 깨진 것
- 없음 (동작 불가 수준 결함 미발견). 단, 아래 P1들은 **수평 확장·동시 이벤트 기록·전송 실패 조건에서 알림 유실/중복**으로 발현되는 잠복 결함.

---

## 2) 구조 평가

### 강점 (근거 확인됨)
- **레이어링 적절**: `app/`(server·config) / `auth/`(shim) / `notifications/`(router·service) / `pipeline/`(poller·dispatcher·kakao·event_types) — 관심사 분리 명확
- **보안 기본기**: 쓰기 엔드포인트 전부 회원 id를 JWT에서 파생(IDOR 없음, `notifications/router.py:79,108,127`), JWT 알고리즘 명시 검증(`shared_core/auth/jwt.py:57-61`)
- **폴러가 이벤트 루프 미차단**: 동기 supabase 호출을 `asyncio.to_thread`로 오프로드(`poller.py:127`)
- **SW 캐시 전략이 CLAUDE.md 정책과 일치**: static→cache-first, API/auth→network-only, HTML→network-first+offline 폴백, 버전 불일치 캐시 purge(`service-worker.js:36-73`)
- **graceful degradation 일관**: VAPID/pywebpush/httpx 부재 시 크래시 대신 `pending` 로그(`dispatcher.py:197-208`, `kakao.py:95-99`)
- **모노레포 규칙 준수**: 수정 범위 services/app 한정, 테이블 전부 `app_*`, migration 021 신규 파일만, auth shim data 패턴 동일, CORS 정확
- **의존성 최소**: pywebpush, httpx 2개만 서비스 고유 (경량 자체 .env 로더로 python-dotenv 불필요)

### 약점 (구조 차원)
- 폴링 파이프라인의 전달 보증이 사실상 "0~1회" — 어느 층도 정확히 1회 전달을 보장 못 함 (P1-1~4 복합)
- `pending`/`failed` 로그는 성실히 기록되나 이를 소비·재시도하는 주체가 없어 사후 부검용에 그침
- 보안 기본값이 "열림" (RLS `true/true`)

---

## 3) 발견된 문제 분류

### P0 (치명) — 없음
단, P1-1~4는 확장/장애/재스크래핑 조건에서 알림 유실·중복·스팸으로 악화되므로 데이터 신뢰가 생명인 이 프로젝트 기준 **P0에 준해 처리 권장**.

### P1 (중요)

| # | 문제 | 근거 | 실패 시나리오 |
|---|------|------|--------------|
| P1-1 | **전송 실패 = 영구 유실**. 커서가 배치 max(id)로 무조건 전진, 디스패처는 예외 흡수 후 `failed` 로그만. 재시도 경로 부재 | `poller.py:112,116`, `dispatcher.py:178-181,220-223` | 발송 순간 Supabase 일시 오류 → failed 기록 → 커서 통과 → 해당 알림 영원히 미발송 |
| P1-2 | **id 워터마크의 커밋 순서 경쟁**. BIGSERIAL은 커밋 순서 무보장인데 `.gt("id", last_id)` 사용 | `poller.py:90-96`, migration `005:10` | id=101이 100보다 먼저 커밋 → 폴링이 101 처리·커서 전진 → 늦게 커밋된 100 영구 누락. (data 측 동시 기록 여부는 미검증) |
| P1-3 | **다중 폴러 = 중복 발송**. 멱등성이 SELECT→INSERT 방식, `app_notification_log`에 UNIQUE 제약 없음, 리더 락 없이 lifespan마다 폴러 무조건 생성 | `dispatcher.py:341-359`, `server.py:40-42`, migration `021:79-80` | uvicorn workers>1 또는 인스턴스 2개 → 같은 배치 N회 디스패치, 경쟁으로 둘 다 INSERT. 현재 단일 인스턴스라 잠복 |
| P1-4 | **재스크래핑 시 알림 스팸**. 멱등키가 data_events 행 id 기준 → 대회 정정마다 새 행 = 참가 선수 전원에 재알림 | `dispatcher.py:351-353`, `event_types.py:20-21` | 정정 재스크래핑 1회 = 전원 스팸 1회. 엔티티 단위 dedup/cool-down 없음 |
| P1-5 | **RLS 무력화 — PII 노출면**. app_* 4개 테이블 정책이 `USING(true) WITH CHECK(true)` | migration `021:107-121` | anon 키 유출 시 전 회원 푸시 구독(엔드포인트/키)·설정·발송 이력 열람/조작 가능 |
| P1-6 | **테스트가 비활성 기능만 커버**. 유일 테스트가 숨김 처리된 카카오 경로만 검증. 운영 경로(인앱/웹푸시/타깃 결정/폴러 커서/메시지 빌드) 테스트 0 | `tests/test_dispatcher_kakao.py` | P1-1~4의 실제 위험을 어떤 테스트도 안 만짐. 페이크 DB 필터가 no-op이라 쿼리 정확성 검증 불가 |

### P2 (개선)

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

### 운영 메모 (코드 외)
- `services/app/.env`에 실제 VAPID 개인키·JWT_SECRET_KEY 평문 존재(git 미추적, 유출 없음). 과거 채팅 노출 이력이 주석에 언급됨 → **운영 전 키 재발급 권장**
- pytest/ruff가 시스템에 미설치 (Homebrew Python 3.14 PEP 668) → 평가 중 venv(/tmp/fm_test_env)로 실행. 반복 가능한 테스트 환경 부재

---

## 4) 테스트 유무와 커버리지

- **테스트 존재**: `tests/test_dispatcher_kakao.py` 1파일 5케이스 (5/5 통과)
- **커버리지 수준**: 사실상 **비활성(카카오) 경로만**. 운영 핵심인 인앱 발송, 웹 푸시, 타깃 결정(`_resolve_targets`/`_players_for_result`), 폴러 커서 로직, 이벤트→카테고리 매핑, 메시지 빌드는 **테스트 부재**
- 3단계 검증 시사점: 파이프라인 수정 항목은 **테스트 신규 작성 + 실행**으로 검증해야 하며, UI/템플릿 항목은 서버 구동 확인으로 대체

## 미검증 항목 (명시)

1. data 서비스 EventPublisher의 동시 기록 여부 (P1-2 발동 조건) — data 워크트리 범위라 미확인
2. `settings.html:259`의 `get('kakao_alimtalk')`가 토글 부재 시 예외인지 false인지 — 런타임 미실행
3. 프로덕션 uvicorn worker 수 (P1-3 발동 조건)
4. FCM 실발송 (VAPID 키 환경 필요)
