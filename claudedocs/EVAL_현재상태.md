# FencingMind-data 프로젝트 평가 (EVAL)

- **평가일**: 2026-07-09
- **평가 방식**: runner(사실 수집) + 지휘자 직접 아키텍처 분석 (deep-reasoner가 Opus 세션 한도로 실패하여 지휘자가 대체 수행)
- **범위**: services/data/ 전체 + packages/shared_core/ (읽기 전용, 수정 없음)

## ⚠️ Git 상태 특이사항 (평가 시점)

- 브랜치: `feature/data/main` (worktree)
- **수정 중 미커밋 파일 20개** — server.py, calculator.py, full_scraper.py, scheduler.py 등 핵심 파일 포함. 프로덕션에 반영된 코드와 git 이력이 불일치할 위험(롤백 불가 상태).
- **Untracked 63개** — 스크린샷 PNG 54개(루트 오염), `Hanes enginieering Md.zip`, 임시 파일 `templates/.!190!base.html`, 미커밋 신규 모듈 `ranking/team_ranking.py`(387줄), `services/data/data/`(audit_homonyms_report.json, international_cache)
- 3단계(수정) 진입 전 반드시 커밋 정리 필요.

---

## 1) 현재까지 진행된 것

### 동작하는 것 (프로덕션 운영 중 — data.fencingmind.ai)
- FastAPI 서버: 82개 `@app.` 라우트 + auth/club 라우터 2개 (총 146 라우트 규모)
- Supabase 전체 데이터 인메모리 로드 + 캐시 (competitions 143, events 2,795, players 11,786+)
- 랭킹 계산 엔진 (NT 서브랭킹 포함, 2026-06-22 포인트 버그 수정 완료)
- 스크래퍼(full_scraper, Playwright) + 스케줄러(변경 감지, Guardian 연동)
- 7개 언어 i18n, H2H, FencingLab, 클럽 관리 SaaS, 3단계 접근 제어, Dual DE 대진표
- `python -m py_compile app/server.py` 통과 (문법 이상 없음)

### 미완성 / 보류
- `ranking/team_ranking.py` (387줄, untracked) — 팀 랭킹 신규 모듈, 커밋도 통합도 안 된 상태
- 카카오 로그인 OAuth (계획 단계)
- `scripts/TODO_address_collection.md` 잔존 작업

### 깨진 것 / 미검증
- **pytest 현재 환경(Python 3.14 homebrew)에 미설치** → 테스트 41개 파일이 있으나 실행 불가. 테스트 통과 여부 **미검증**
- 린터(ruff/flake8) 미설치 → 정적 품질 미검증
- 프로덕션 `JWT_SECRET_KEY` 환경변수 설정 여부 **미검증** (아래 P0-2 참조)

---

## 2) 구조 평가

### 규모
| 항목 | 수치 |
|---|---|
| Python 파일 (backup 제외) | 100개 / 59,954줄 |
| server.py | **8,932줄, 82 라우트** |
| 템플릿 / JS / CSS | 32 / 5 / 8 |
| 테스트 파일 | 41개 (루트 tests/ + tests/unit/ + tests/e2e/ + services/data/tests/) |
| TODO/FIXME | 4개 (양호) |

### 레이어링·응집도
- **server.py가 God file**: 라우팅 + 데이터 로딩 + 캐시 구축(build_player_index 등 6종) + i18n 헬퍼 + 도메인 로직(`calculate_head_to_head`, `compute_dual_de_final_rankings`, DE 예측, 선발 포인트 페이지)이 한 파일에 공존. `include_router`는 auth/club 2개뿐이고 나머지 82개 라우트는 전부 인라인.
- **전역 mutable 상태 17개** (server.py:595-611): `_data_cache`, `_player_index`, `_org_translation_cache` 등. DI 없음 → 단위 테스트가 전역 상태 몽키패칭에 의존하는 구조.
- **모듈 분리 자체는 양호**: scraper/, ranking/, scheduler/, data_pipeline/, app/club/, app/i18n/ 은 방향성 있는 분리. 의존 방향(스케줄러→스크래퍼→DB, 서버→랭킹)도 대체로 단방향.
- **shared_core 경계 양호**: app/auth는 shared_core re-export shim으로 정리되어 있고(models.py 확인), 역방향 의존 없음. 시크릿 하드코딩 코드 내 없음 (grep 검증).

### 중복
- `extract_age_group()`이 **server.py:1369와 ranking/calculator.py:348에 각각 존재** — 나이그룹 파싱 규칙이 갈라지면 랭킹/필터 불일치 발생. 2026-06-22 PYTHONPATH 섀도잉 사고와 같은 계열의 드리프트 리스크.
- i18n 라우트가 `xxx_page` + `xxx_page_i18n` 쌍으로 전 페이지 중복 (얇은 위임이지만 보일러플레이트 다수).
- `scraper/de_scraper_v4.py`(1,855줄)가 backup이 아닌 scraper 루트에 잔존 — CLAUDE.md "full_scraper.py가 유일 메인" 규칙과 충돌 소지.

### 캐시/파이프라인 (제1원칙 관점)
- 캐시 무효화 수단이 사실상 **전체 reload**(`load_data()`)뿐. 영문명 수정 시 `_player_translation_cache` 즉시 갱신처럼 국소 갱신도 있으나 체계 없음. 선수 프로필 수정→파생 데이터 전파를 보장하는 일반 메커니즘은 부재 (제1원칙 체크리스트의 "캐시 무효화 메커니즘" 미완).

---

## 3) 발견된 문제 분류

### P0 (치명 — 보안/프로덕션 장애 가능)
| # | 문제 | 근거 | 방치 시 결과 |
|---|---|---|---|
| P0-1 | **관리성 엔드포인트 무인증**: `POST /api/data/reload`(server.py:2397), `POST /api/scheduler/run`(:8858), `GET /api/admin/validate`(:8883) 모두 인증 없음 | 코드 직접 확인 — `get_current_member` 호출 없음 | 외부인이 반복 호출로 전체 데이터 리로드/스크래퍼 강제 실행 → 서버 자원 고갈 + KFA 사이트에 무단 트래픽 (차단/법적 리스크) |
| P0-2 | **JWT 시크릿 기본값 폴백**: `JWT_SECRET_KEY: str = os.getenv(..., "your-secret-key-change-in-production")` | shared_core/auth/config.py:20 | 프로덕션에서 env 미설정 시 공개된 기본 키로 토큰 위조 가능 → 인증·접근제어 전체 무력화. (프로덕션 env 설정 여부는 미검증 — 확인 필요) |

### P1 (중요 — 유지보수·운영 심각 저해)
| # | 문제 | 근거 | 방치 시 결과 |
|---|---|---|---|
| P1-1 | 핵심 파일 20개 미커밋 + untracked 63개 | git status | 롤백 불가, 실수 커밋 위험, 프로덕션-저장소 불일치 |
| P1-2 | 테스트 실행 환경 붕괴 (pytest 미설치, Python 3.14 homebrew ≠ ARM64 규칙 환경) | pytest collect 실패 로그 | 41개 테스트가 장식품화 — 회귀 감지 불능 상태로 프로덕션 변경 지속 |
| P1-3 | server.py God file (8,932줄) + 전역 상태 17개 | 구조 맵 | 변경 충돌·리뷰 불능·테스트 불가 악화. 신규 기능마다 비용 증가 |
| P1-4 | `extract_age_group` 중복 정의 (server.py ↔ calculator.py) | :1369 / :348 | 파싱 규칙 드리프트 → 랭킹/필터 데이터 불일치 (제1원칙 위반 경로) |
| P1-5 | 린터 부재 | ruff/flake8 미설치 | 죽은 코드·미사용 import·잠재 버그 누적 미탐지 |

### P2 (개선)
| # | 문제 | 근거 |
|---|---|---|
| P2-1 | 루트 스크린샷 PNG 54개 + zip + `.!190!base.html` 임시 파일 오염 | git status |
| P2-2 | `de_scraper_v4.py` scraper 루트 잔존 (backup 규칙 위반 소지) | 파일 목록 |
| P2-3 | `team_ranking.py` 387줄 미커밋 방치 (완성/폐기 결정 필요) | untracked |
| P2-4 | requirements.txt 상한 없는 버전 지정, lockfile 부재 | requirements.txt |
| P2-5 | 테스트가 루트 `tests/`와 `services/data/tests/`로 분산 | 파일 목록 |
| P2-6 | i18n 라우트 쌍 중복 보일러플레이트 | server.py 구조 |

---

## 4) 테스트 유무와 커버리지

- **테스트 존재**: 41개 파일 (unit 12, e2e 3+, 루트 15, services/data 1). pytest.ini 있음. `.coverage` 파일 흔적 있음(과거 실행).
- **그러나 현재 실행 불가** — 현재 셸의 python3(3.14 homebrew)에 pytest 미설치. **사실상 "테스트 부재 상태"로 간주하고 3단계 검증은 빌드+실제 구동 확인 병행 필요.** pytest 환경 복구가 선행 과제.
- 커버리지 수준: **미검증** (실행 불가로 측정 불가).
