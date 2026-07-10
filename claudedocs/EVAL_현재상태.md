# FencingMind 프로젝트 평가 — 현재 상태 (2026-07-10)

> 평가 방식: deep-reasoner(아키텍처 심층 평가) + runner(사실 수집) 병렬 위임 후 종합.
> 읽기 전용 평가 — 코드 미수정. 근거 없는 주장 금지, 미확인 항목은 "미검증" 표기.

## ⚠️ Git 상태 (평가 시점)

- 브랜치: `feature/account/init` (원격보다 7커밋 앞 — push 안 됨)
- 더러운 작업 트리: `M services/app/CLAUDE.md` (app 워크트리 관할 파일이 이 브랜치에서 수정됨 — 커밋 분리 결정 필요)
- 미추적: `.pids/`, `Hanes enginieering Md.zip`, `docs/I18N_THEME_INTEGRATION_GUIDE.md`, `docs/📊 FENCINGMIND 사업계획서.md`
- 워크트리 8개, 브랜치 24개(local 12 / remote 12)

---

## 1) 현재까지 진행된 것

### 동작하는 것
- **data 서비스** (운영 중, 타 워크트리 관할): Python 64파일, `server.py` 3048줄, 스크래퍼/랭킹/파이프라인 포함
- **account 서비스** (개발 중, 이 워크트리 관할): Python 43파일. OAuth(카카오/구글) 로그인, 회원가입(무기/리그 필터 선수검색 포함), 이메일 인증, claim 기반 선수 본인인증
- **shared_core 패키지**: auth(JWT/OAuth)/db 싱글톤/i18n(7언어+테마)/privacy 마스킹/email — 실제로 서비스들이 인증 핵심을 여기서 import (규칙 준수 확인됨)
- **app 서비스** (스캐폴드): Python 7파일, auth shim + health check 수준
- **DB 마이그레이션**: 22개 (001~021)

### 미완성
- club/community/shop/blog/analytics 5개 서비스: Python 파일 0개 (폴더 스캐폴드만), auth shim도 부재
- `packages/shared-api`: CLAUDE.md만 있는 빈 껍데기 — R5 규칙("서비스 간 통신은 shared-api 통해서만")의 구현체 없음
- `packages/shared-ui`: components 없이 CSS + favicon만
- shared_core.i18n을 만들었으나 account/data가 여전히 자체 복제본 사용 (수렴 미완)

### 깨진 것
- **루트 `main.py`**: `from scraper.client`, `scheduler.scheduler` import하지만 루트에 해당 디렉터리 없음 → import 시점 파손 죽은 코드 (git 추적 중)
- **rsync 사고 잔재물**: 루트에 `--exclude=*.log`, `-av`, `--dry-run`, `rsync/` 등 잘못된 rsync 실행이 만든 쓰레기 디렉터리 잔존
- **pytest·ruff 미설치**: 테스트 31개 파일이 있으나 현재 환경에서 실행 불가, 린터 없음
- 마이그레이션 번호 중복: `002_add_organizations_table.sql` vs `002_ready_to_run.sql` → 실행 순서 모호

---

## 2) 구조 평가

### 잘 지켜지는 것 (근거 확인됨)
- **레이어링**: services → packages(shared_core) 의존 방향 깨끗함. 서비스 간 직접 import 위반 **0건** (전수 grep, R5의 import 측면 준수)
- **인증 단일화**: account만 인증 구현, data는 shim으로 리다이렉트만 (`services/data/app/auth/router.py`) — CLAUDE.md 규칙이 코드로 지켜짐
- **OAuth state를 DB 저장** (`shared_core/auth/oauth/handler.py:29-67`): 1회용 삭제 + 만료 처리, 무상태·수평확장 안전
- OAuth 콜백 에러/취소/state만료의 방어적 처리 (`auth/router.py:520-529`)
- 공개 선수검색의 조인 필터가 후보 ≤60 / 2쿼리 배치 설계 — N+1 아님

### 문제 있는 것
- **응집도/중복**: i18n manager가 3벌 병존(shared_core 220줄 / account 210줄 / data 200줄, 거의 동일) — 정책 변경 시 3곳 동시 수정 필요
- **네임스페이스**: 모든 서비스의 로컬 패키지명이 전부 `app` → 별도 프로세스라 현재는 무사하나 한 프로세스에 둘 로드 시 즉시 파손
- **대형 파일 편중**: `full_scraper.py` 3061줄, `data/server.py` 3048줄, `fencing_analyzer_v3.py` 2085줄, `club/router.py` 1749줄 (대부분 타 워크트리 관할), `register.html` 1001줄(이 관할 — 거대 인라인 script/style)
- **의존성 관리**: 루트 `requirements.txt` 하나로 전 서비스 공용, pyproject.toml 없음, 버전 고정 상태 미검증
- TODO/FIXME/HACK 13개 (account 5, data 5, 기타 3) — 심하지 않음

---

## 3) 발견된 문제 (P0 / P1 / P2)

### 🔴 P0 — 치명 (보안/데이터 무결성)

| # | 문제 | 근거 | 영향 |
|---|------|------|------|
| **P0-1** | **JWT 시크릿 안전하지 않은 기본값**: `os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")` — env 누락 시 공개·예측가능 키로 서명/검증 | `packages/shared_core/auth/config.py:20` | `.fencingmind.ai` 쿠키 공유 구조라 **전 서브도메인에서 임의 회원 위장 가능**. 배포 env 주입 여부는 미검증. 기동 시 fail-fast 필요 |
| **P0-2** | **Supabase 액세스 토큰 평문 노출**: `.mcp.json`에 `sbp_7150f050...` 하드코딩 (git 히스토리 포함 가능성) | `.mcp.json` | 토큰 유출 시 Supabase 프로젝트 전체 제어. **토큰 회전 + 환경변수화 필수**. Stripe/Portone/Kakao/Google은 env 참조라 안전 |

### 🟡 P1 — 중요 (구조적/보안 부채)

| # | 문제 | 근거 | 영향 |
|---|------|------|------|
| **P1-1** | **오픈 리다이렉트**: `_is_safe_redirect`가 `hostname.endswith(d)` — `evilfencingmind.ai`도 통과 | `services/account/app/auth/router.py:89-96` (사용처 :497, :562) | OAuth 로그인 후 피싱/토큰 유출 벡터. `host == d or host.endswith("."+d)`로 수정. 테스트 커버 여부 미검증 |
| **P1-2** | **공개 검색 API 무인증·무제한 PII 노출**: `/auth/public/player-search`가 실명·birth_year·team_name 마스킹 없이 반환, rate limiting 전무(grep 0건) | `auth/router.py:211-299` | 미성년 선수 다수 포함 — 무제한 스크래핑으로 PII 열거 가능. **제0원칙(개인정보 리스크 최소화) 충돌** |
| **P1-3** | **claim 자동승인 임계값(0.85)이 공개검색 노출 필드로 정확히 충족 가능**: 이름 0.35 + 출생연도 0.25 + 소속 0.25 | `config.py:57` + `verification/claims.py:63-119` | 공개 API가 본인인증 검증 재료를 그대로 배포하는 구조. 조직 연결 후 재시도하면 타인 프로필 자동승인 도달 → **제1원칙(데이터 무결성) 전파 리스크**. P1-1·P1-2와 결합 시 신원 탈취 경로 완성 |
| **P1-4** | **i18n 3중 복제**: shared_core.i18n 완성됐으나 account(`server.py:26`)·data가 자체 복제본 사용 | `services/account/app/server.py:26` 외 | 언어·테마 정책 변경 시 3곳 수정, 누락 시 서비스별 편차 |
| **P1-5** | **OAuth state를 URL 문자열 되파싱으로 재추출**: `auth_url.split("state=")[1].split("&")[0]` | `auth/router.py:498` | provider URL 포맷 변경 시 조용히 파손 (redirect 유실이 :505-506 `except: pass`로 무음) |
| **P1-6** | **루트 파손 레거시**: 깨진 `main.py`(git 추적) + rsync 쓰레기 디렉터리 | 루트 | 혼란 유발 죽은 코드. 모노레포 공통 관할 |
| **P1-7** | **테스트 실행 환경 부재**: pytest·ruff 미설치 — 테스트 31개가 사실상 죽어 있음 | 환경 | 3단계 수정 검증이 빌드+구동 확인에 의존하게 됨 |

### 🟢 P2 — 개선 (품질/일관성)

- **`except Exception` 112곳** (account/app 전체): claim/알림 실패가 fail-open 로깅만(:949, :986, :1031) — 가입 흐름 보호 의도는 타당하나 claim 유실이 무음 누적, 재시도 큐 없음. loguru 일관 사용은 양호
- **무기/리그 필터 무음 fail-open** (`auth/router.py:157-159, 170-172`): 조인 실패 시 필터 무시하고 전체 반환 → 필터했는데 무관 선수 섞임, UI에 실패 신호 없음
- **`datetime.utcnow()` 4회 + tz naive/aware 혼용**: verify_email 만료 비교(:1117-1119) tz 실수 소지
- **`register.html` 1001줄 단일 파일**: 위자드+선수검색+연락처 로직이 거대 인라인 script/style로 응집 — 유지보수성 낮음
- **마이그레이션 002 번호 중복** (공통 관할)
- **서비스 패키지명 전부 `app`** — 장기적 네임스페이스 리스크
- **shared-api 미구현** — R5 규칙 강제 수단 없음, 현재 Supabase 테이블 직접 결합

### 타 워크트리 관할 (발견만, 이 브랜치에서 수정 금지)
- data 서비스 i18n 자체 복제본 (P1-4의 일부)
- club/community/shop/blog/analytics 5개 서비스 auth shim 부재 — "모든 서브도메인 auth shim 필수" 규칙과 불일치 (초기 미구현 단계일 가능성, 각 서비스 라우팅 전체는 미검증)
- data/club의 대형 파일 (server.py 3048줄, club/router.py 1749줄)

---

## 4) 테스트 현황

- **테스트 파일 31개 존재** (account 3, tests/unit 10, tests/e2e 3, 기타 15)
- **그러나 현재 환경에서 pytest 미설치 → 실행 불가.** 커버리지 측정 불가 = 사실상 **테스트 부재 상태**
- 린터(ruff) 미설치 — 정적 분석 부재
- **3단계 검증 방식에 영향**: pytest 설치 후 기존 테스트 통과 여부부터 확인하거나, 안 되면 "빌드 + 서버 실제 구동(port 70) + 엔드포인트 수동 확인"으로 검증해야 함
- 실행 시 PYTHONPATH 필수: `${PWD}:${PWD}/packages:${PWD}/services/{service}`

---

## 종합 판단

구조 규율(레이어링, 인증 단일화, worktree 분리)은 문서 규칙이 코드로 실제 지켜지는 드물게 양호한 상태. 그러나 **(1) JWT 기본키 + 토큰 평문 노출이라는 P0 보안 구멍 2개**, **(2) 공개검색 PII 노출 → claim 자동승인으로 이어지는 신원 탈취 경로(P1-1~P1-3 결합)**, **(3) 테스트/린트 실행 환경 부재**가 즉시 조치 대상. i18n 수렴·레거시 정리는 그 다음.
