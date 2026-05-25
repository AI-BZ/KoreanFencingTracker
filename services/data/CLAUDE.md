# data.fencingmind.ai - 펜싱 데이터 서비스

**공식 명칭:** FencingMind Tracker
**서브도메인:** data.fencingmind.ai
**포트:** 9071 (Cloudflare Tunnel → nginx:9090 → FastAPI:9071)
**상태:** ✅ 운영 중 (메인 서비스)
**로고:** `/static/images/logo/FencingMind_logo_long_Tracker.png`

---

## 서비스 개요
- 전 세계 펜싱 대회 결과 데이터베이스
- 선수 프로필 및 랭킹 시스템
- 클럽/코치 디렉토리
- API 제공 (B2B 데이터 판매)

## 핵심 문서 참조
- **선발 포인트 기준** (꿈나무/청소년 대표): `docs/SELECTION_CRITERIA.md`

## 수익 모델
- API 구독: $99~999/월 (이용량별)
- 데이터 라이선스: $5,000~50,000/년 (B2B)

---

## 폴더 구조
```
services/data/
├── app/                 # FastAPI 웹 서버
│   ├── server.py        # 메인 서버
│   ├── auth/            # 인증 시스템
│   ├── club/            # 클럽 관리 (→ services/app/으로 분리 예정)
│   ├── i18n/            # 다국어 지원
│   └── player_*.py      # 선수 분석
├── scraper/             # 스크래퍼
├── ranking/             # 랭킹 계산
├── data_pipeline/       # 데이터 파이프라인
├── templates/           # Jinja2 템플릿
├── static/              # 정적 파일
├── scheduler/           # 자동 업데이트
└── video/               # 영상 분석 (→ services/analytics/로 분리 예정)
```

## 서버 실행
```bash
# 프로덕션 (launchd 관리 - 자동 시작/재시작)
# /Users/gyejinpark/opt/fencingmind/scripts/start-data.sh → port 9071
bash scripts/fencingmind-server.sh restart

# 개발용 (수동)
cd services/data
PYTHONPATH=".:../../packages" python -m uvicorn app.server:app --host 0.0.0.0 --port 9071
```

---

## DB 테이블 (소유)
**이 서비스가 주인인 테이블:**
- `competitions` - 대회
- `events` - 종목
- `matches` - 경기
- `rankings` - 순위
- `scrape_logs` - 스크래핑 로그
- `data_events` - 데이터 이벤트
- `validation_logs` - 검증 로그

**공유 테이블 (참조만):**
- `members` - 회원 (공유)
- `players` - 선수 (공유)
- `organizations` - 조직 (공유)

---

## 🌐 다국어 지원 (i18n) - 2026-05-21 현재

### 지원 언어 (7개)
ko (한국어, 기본), en (영어), ja (일본어), fr (프랑스어), it (이탈리아어), zh (중국어), tr (터키어)

### 아키텍처
```
app/i18n/
├── __init__.py              # TranslationManager, 미들웨어
├── auto_translate.py        # 자동 번역 (LLM 기반)
├── translations/{lang}/     # 정적 번역 JSON (common.json)
└── ...

app/translation_service.py   # TranslationService (선수명 로마자, 조직명 영문)
app/international_data.py    # InternationalDataManager (FIE/FencingTracker 연동)
```

### 선수명 번역 파이프라인 (✅ 구현 완료)
```
서버 시작 → build_player_translation_cache()
         → players.translations.en.name 캐시 로드 (~11,786건)

요청 시:
  lang == 'ko' → 한국어 원본
  lang != 'ko' → _player_translation_cache 히트 → 즉시 반환
              → 캐시 미스 → TranslationService.translate_player_name() 로마자 변환
              → 실패 → 한국어 원본 fallback
```

### 템플릿 번역 함수
| 함수 | 용도 | 사용 위치 |
|------|------|----------|
| `t('키')` | 정적 번역 (common.json) | 전체 |
| `_t('한국어')` | 자동 번역 fallback | 전체 |
| `tr_event(name)` | 종목명 번역 | 전체 |
| `tr_comp(name)` | 대회명 번역 | 전체 |
| `tr_team(name)` | 조직명 번역 (캐시) | 전체 |
| `tr_player(name)` | 선수명 로마자 (캐시) | 전체 |

### JS 번역 (동적 렌더링용)
- `_tr_team(name)`: `_teamTransMap` / `_teamMap` JSON에서 조회
- `_tr_player(name)`: `_playerTransMap` / `_playerMap` JSON에서 조회
- 서버에서 이벤트/대회 내 모든 선수명 수집 → `player_translation_map` 생성 → 템플릿 전달

### 영문명 수정 API
```
PUT /api/player/me/english-name          ← 본인 수정 (JWT, member.player_id)
PUT /api/player/{name}/english-name      ← 관리자/코치 수정 (admin/coach/head_coach/owner)
Body: {"english_name": "Soyun Park"}
→ players.translations.en 업데이트 + _player_translation_cache 즉시 갱신
```

### 핵심 원칙
- **URL은 한국어 유지**: `/player/박소윤` (라우팅용)
- **표시는 로마자**: `{{ tr_player(player.name) }}` → "Soyun Park"
- **캐시 우선**: 서버 시작 시 1회 빌드, API 수정 시 즉시 갱신

---

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/data/*` 브랜치에서만 수정
- 다른 서비스 코드 수정 금지
- 공유 패키지 수정 시 `feature/shared/*` 브랜치 사용

---

## 🔴🔴🔴 데이터 수정 원칙 (Data Modification Principles) 🔴🔴🔴

**데이터 표시 오류 발생 시 반드시 이 원칙을 따르세요.**

### 핵심 원칙: 근본 데이터 추적 (Root Data Tracing)
데이터 표시에 오류가 있을 때, **표시 레이어(템플릿/UI)가 아닌 근본 데이터 소스부터 추적**해야 합니다.

### 데이터 파이프라인 계층
```
1. 스크래퍼 (scraper/) - 원본 데이터 수집
     ↓
2. DB 저장 (raw_data, de_bracket 등) - 근본 데이터
     ↓
3. 서버 API (server.py) - 데이터 가공/전달
     ↓
4. 템플릿 (templates/) - 최종 표시
```

### 오류 수정 절차

**Step 1: 근본 데이터 확인**
```sql
-- 예: 라운드 정보가 잘못 표시되는 경우
SELECT
    (raw_data->'de_bracket'->>'bracket_size')::int,
    raw_data->'de_bracket'->>'starting_round'
FROM events WHERE id = ?
```

**Step 2: 파이프라인 역추적**
- DB 데이터가 올바름 → 서버 API 또는 템플릿 문제
- DB 데이터가 잘못됨 → 스크래퍼 문제

**Step 3: 근본 원인 수정**
- 증상이 아닌 원인을 수정
- 하드코딩 제거, 근본 데이터 참조로 교체

### 실제 사례

**문제**: 모든 대회에서 첫 라운드가 "128강"으로 표시됨

**잘못된 접근** ❌:
```python
# 템플릿에서 128강을 다른 값으로 바꿈
round_order = ["128강", "64강", ...]  # 하드코딩된 순서
```

**올바른 접근** ✅:
```python
# DB에 저장된 실제 시작 라운드 사용
starting_round = de_bracket.get("starting_round", "32강")
if starting_round in full_round_order:
    start_idx = full_round_order.index(starting_round)
    round_order = full_round_order[start_idx:]
```

### 체크리스트
- [ ] 근본 데이터(DB) 확인했는가?
- [ ] 파이프라인 어느 단계에서 오류가 발생하는지 파악했는가?
- [ ] 하드코딩을 근본 데이터 참조로 교체했는가?
- [ ] 수정 후 다른 대회/이벤트에서도 정상 작동하는지 확인했는가?

---

## 📏📏📏 데이터 일관성 원칙 (Data Consistency Principles) 📏📏📏

### 핵심 원칙: 같은 지표는 어디서나 같은 숫자
하나의 지표(참가자 수, 순위 등)는 **모든 화면/API에서 동일한 값**을 표시해야 한다.

### 참가자 수 (total_participants) 우선순위
```
1. participants 리스트 (fetch_participants.py 수집) — 가장 정확
2. Pool 참가자 합계 (pool_rounds에서 집계한 unique 선수)
3. pool_total_ranking 수 (자체 계산 시 전원 포함)
4. final_rankings 수 (최소 fallback)
```
⚠️ `event.total_participants` 명시값은 더 이상 사용하지 않음 (과거 final_rankings 수 기반이라 부정확)

### Pool 종합 순위 (pool_total_ranking) 정책
- **Primary Source**: pool_rounds에서 자체 계산 (`pool_calculator.calculate_pool_total_ranking()`)
- **KFF 스크래핑 데이터**: "진출" 상태 마킹에만 사용 (KFF는 본선 미진출자 삭제하므로 불완전)
- **자체 계산 이점**: 전체 참가자 포함, 일관된 순위 산출, 중복 없음
- **적용 시점**: 저장 시(competition_detector) + 표시 시(server.py) 이중 보장

### 위반 방지 체크리스트
- [ ] 같은 지표가 서로 다른 숫자로 표시되지 않는가?
- [ ] pool_total_ranking이 pool_rounds 선수 수와 일치하는가?
- [ ] participants 탭의 참가자 수와 헤더의 참가자 수가 같은가?

---

## 🔍🔍🔍 데이터 무결성 검증 (Data Integrity Validation) 🔍🔍🔍

### 원칙: 데이터 오류 제로 (ZERO DATA ERRORS)
데이터 사업에서 **1개의 오류도 있으면 안 된다.** 모든 데이터 수정은 검증을 거쳐야 하며, 새로운 오류 패턴은 반드시 카탈로그에 기록한다.

### 검증 규칙 12개 (R1 ~ R12) 요약

| 규칙 | 검증 대상 | 설명 |
|------|----------|------|
| R1a/R1b | 이벤트 | Self-bout / Duplicate bout |
| R2 | 이벤트 | Winner 일관성 (winner ∉ {p1, p2}) |
| R3 | 이벤트 | 점수 범위 이상 (음수, >15, 동점) |
| R4 | 이벤트 | 빈/비표준 round_name |
| R5 | 이벤트 | Bracket topology (승자→다음 라운드) |
| R6 | 이벤트 | Final ranking vs DE bracket 불일치 |
| R7 | 선수 | 같은 라운드 2경기 이상 |
| R8 | 선수 | 라운드 진행 보존법칙 (경기 유실) |
| R9 | 선수 | Pool 경기수 이상 (>8) |
| R10 | 선수 | 성별 불일치 (동명이인) |
| R11 | 선수 | 나이그룹 역행 (동명이인) |
| R12 | 선수 | 무기 3종 이상 (동명이인) |

### 필수 검증 명령어
```bash
cd services/data
PYTHONPATH="." python scripts/run_validation.py
```

### 데이터 파일 수정 시 필수 절차
1. 코드 수정 (scraper/, server.py, bracket_utils.py 등)
2. **검증 실행**: `PYTHONPATH="." python scripts/run_validation.py`
3. **ERROR 0건** 확인 (WARNING은 허용하되 검토 필수)
4. 새 오류 패턴 발견 시 → `docs/DATA_ERROR_CATALOG.md`에 CASE 추가
5. 기존 이슈 수정 시 → 카탈로그의 해당 CASE 상태 업데이트

### Claude Code Hook
`.claude/hooks/data-validation-check.sh`가 Stop 이벤트에서 자동 실행됨.
데이터 관련 파일(scraper/, data_validator, server.py, bracket_utils, data_pipeline, pipeline_scraper) 수정 시 검증 리마인더를 표시.

### 오류 카탈로그
**상세 문서:** `services/data/docs/DATA_ERROR_CATALOG.md`
- 발견된 오류 사례 7건 (CASE-001 ~ 007)
- 예상 오류 케이스 7건 (CASE-E01 ~ E07)
- 새 케이스 등록/상태 업데이트 절차 포함

---

## Player-Centric Data Philosophy (선수 중심 데이터 철학)

### 핵심 개념
**"나를 찾는다" 또는 "보고 싶은 선수를 찾는다"**

데이터 서비스의 핵심 가치는 단순한 데이터 나열이 아닌, 사용자(선수/학부모/코치)가 자신 또는 관심 있는 선수의 정보를 쉽게 찾고 추적할 수 있도록 하는 것입니다.

### 주요 기능

#### 1. 선수 자동완성 검색 (Autocomplete)
- 이름 입력 시 실시간 드롭다운 제안
- 동명이인 구분을 위한 소속 정보 함께 표시
- 대회 내 검색과 전체 검색 지원

```
API: GET /api/players/autocomplete?q=오&limit=10&event_cd=xxx
응답: { suggestions: [{ name, team, display, player_id }] }
```

#### 2. 자동 하이라이트 (Auto-Highlight)
- 검색된 선수가 나타나는 모든 위치를 자동으로 강조
- Pool 결과, DE 대진표, 최종 순위 등 전 영역 지원
- 첫 발견 위치로 자동 스크롤

```javascript
// 하이라이트 대상 영역
- Pool 결과 테이블
- Pool 총 순위
- DE 대진표 (브라켓)
- 시상대 (Podium)
- 최종 순위
```

#### 3. DE 예측 대진표 (DE Prediction Table)
- 선수가 각 라운드에서 만날 수 있는 잠재적 상대 목록
- 상대 전적(Head-to-Head) 정보 포함
- 시드 기반 대진표 수학적 계산

```
API: GET /api/events/{sub_event_cd}/de-prediction/{player_name}
응답: {
  player: { name, team, seed },
  predictions: [
    { round: "64강", potential_opponents: [...] },
    { round: "32강", potential_opponents: [...] }
  ]
}
```

#### 4. 상대 전적 조회 (Head-to-Head)
- 두 선수 간 역대 대결 기록
- Pool/DE 경기 구분
- 필터: 무기, 나이그룹별

```
API: GET /api/players/{player}/head-to-head/{opponent}
응답: {
  record: { wins, losses, total },
  matches: [{ date, competition, round, score, winner }]
}
```

#### 5. 내 선수 기능 (My Player)
- localStorage 기반 즐겨찾기 선수 저장
- 페이지 로드 시 자동 하이라이트
- 대회 페이지 간 연속성 유지

### 페이지 연동 흐름

```
대회 목록 → 대회 상세 (Competition)
                ↓
         선수 검색 (Autocomplete)
                ↓
         검색 결과 카드
                ↓ [상세 보기 & 하이라이트]
         종목 결과 (Event Result)
                ↓
         자동 하이라이트 + DE 예측
```

### 관련 파일
```
static/js/player-search.js     # PlayerSearch, PlayerHighlighter, DEPredictionTable
static/css/player-search.css   # 검색 UI 스타일
templates/event_result.html    # 종목 결과 (하이라이트 적용)
templates/competition.html     # 대회 상세 (검색 → 종목 이동)
app/server.py                  # API 엔드포인트
```

### URL 파라미터
- `?highlight=선수이름` - 페이지 로드 시 해당 선수 자동 하이라이트
- 대회 페이지에서 종목 페이지로 이동 시 자동 전달

---

## 이벤트 정렬 순서 (Event Sorting Order)
대회 상세 페이지에서 이벤트(종목) 목록의 표시 순서:
1. **무기**: 플뢰레 → 에페 → 사브르
2. **성별**: 여 → 남
3. **나이그룹**: 초등 → 중학 → 고등 → 일반(대학/실업)
4. **종류**: 개인전 → 단체전

구현: server.py의 `_event_sort_key()` 함수
