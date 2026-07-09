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

## 랭킹 시스템 원칙 (RANKING SYSTEM RULES)
- **엄격한 연도 기반**: N년 랭킹 = N년 대회 결과만. 롤링 윈도우 사용 금지
- **새 연도 빈 데이터**: 새 해 첫 대회 결과 나올 때까지 해당 연도 랭킹 미생성
- **🔴 자유 참가 원칙 (Open Entry Principle)**: 랭킹 포인트는 자유 참가(open entry) 대회만 인정
  - **포인트 인정**: 누구나 자유롭게 참가 신청할 수 있는 대회
  - **포인트 제외**: 시도별 선발 등 소수만 참가하는 선발 참가(nominated/selected) 대회
  - **제외 대회**: 전국체육대회, 전국소년체육대회 (시도별 1명 선발, 13~18명 참가)
  - **결과 표시**: 제외 대회의 경기 결과는 선수 프로필/대회 페이지에 정상 표시 (포인트만 0)
  - **근거**: 선발 참가 대회는 참가 기회의 공정성이 보장되지 않아 전체 선수 실력 비교에 부적합
  - **구현**: `_extract_results()`에서 해당 대회 skip (results 자체를 미생성)
- **2카드 시스템**: NT 선발전 출전 선수는 프로필에 2개 랭킹 표시:
  1. 나이리그 랭킹 (일반 대회 + NT 나이리그별 서브랭킹 포인트 합산)
  2. NT 전체 랭킹 (국가대표 선발전 전체 참가자 중 순위)
- **투명한 포인트**: 각 랭킹 카드에 Best N 대회별 포인트 산출 내역 공개
- **NT 나이리그 추론**: 팀 기반 필터링으로 동명이인 혼입 방지 (calculator.py)
- **동명이인 구분**: identity_profile 팀 기반 필터링으로 다른 사람의 랭킹 혼입 방지
- **구현 위치**: `ranking/calculator.py` (연도 필터 + NT 서브랭킹), `server.py` (프로필 랭킹 + API)

### NT 서브랭킹 상세 규칙 (NATIONAL TEAM SUB-RANKING RULES)

**대회 분류 (classify_competition_level)**:
- `NATIONAL`: 순수 국대선발 (예: "2026 펜싱 국가대표선수 선발대회")
- `YOUTH_NATIONAL`: 유소년/청소년 국대선발 (예: "유소년 국가대표선수 선발전") — 랭킹 완전 제외
- `ELITE`: 겸 국대선발 포함 (예: "제55회 회장기 겸 2026 펜싱 국가대표 2차선발대회")
- **겸 국대선발 = 국가대표 대회**: '겸'은 해당 대회가 국가대표 선발도 겸한다는 의미
  - 나이리그 랭킹: 일반 age_group으로 포함 (SR, MS, HS 등)
  - NT 전체 랭킹: '국가대표' 포함 대회이므로 NT 전체 랭킹에도 포함
- NATIONAL 대회의 모든 이벤트는 `age_group='NT'`로 분류 (DB의 "일반부" 등 무시)
- YOUTH_NATIONAL 대회는 `_extract_results()`에서 완전 제외 (results 미생성)
- ELITE(겸) 대회는 일반 age_group 사용 + NT 전체 랭킹에도 포함

**서브랭킹 생성 (`_generate_national_sub_rankings`)**:
1. NT 결과에서 각 선수의 나이그룹을 다른 대회 출전 이력으로 추론
2. 추론된 나이그룹별로 재순위 (sub_rank) 매김
3. sub_rank 기준 + 전체 참가자 수 기반으로 포인트 계산
4. 생성된 서브랭킹 결과는 해당 나이리그 랭킹에 합산됨

**🔴 유소년/청소년 국가대표 완전 제외 규칙**:
- "유소년 국가대표선수 선발전", "청소년 국가대표선수 선발전"은 일반 국가대표 선발대회와 **완전히 다른 대회**
- 대상 연령, 참가자, 대회 방식이 상이 → 동일 랭킹에서 비교 불가
- **랭킹 완전 제외**: NT 전체 랭킹에도, 나이리그 서브랭킹에도 포함하지 않음
- 대회/선수 프로필 페이지에서는 정상 표시 (대회 결과 데이터는 존재, 포인트만 0)
- 구현: `_extract_results()`에서 대회명에 '유소년' 또는 '청소년' + '국가대표' 포함 시 `continue`
- 참고: 1~2월 NATIONAL 대회는 역사적으로 모두 유소년/청소년 국가대표이므로 별도 월 기반 로직 불필요

**NT 전체 랭킹 (rankings 페이지 & 프로필 2번째 카드)**:
- `national_team_only=True` 필터: 대회명에 '국가대표' 포함 대회 전체
- 순수 NATIONAL + 겸 ELITE 모두 포함 (유소년/청소년은 `_extract_results()`에서 이미 제외)
- **이중 계산 방지**: `national_team_only=True` + `age_group='NT'`일 때 `r.age_group == 'NT'` 결과만 포함
  - 서브랭킹 결과(age_group='MS','HS' 등)는 NT 전체 랭킹에서 제외
  - 서브랭킹 결과는 해당 나이리그 랭킹에만 포함됨
- 구현: `calculate_rankings(age_group='NT', national_team_only=True)` — age_group='NT' 필터 적용

**NT 서브랭킹 포인트 계산**:
- 서브랭킹 포인트는 **해당 나이그룹 참가자 수** 기준으로 계산 (전체 NT 인원 아님)
- 예: MS 51명 → base_points=800, SR 33명 → base_points=800, HS 57명 → base_points=800
- 구현: `_generate_national_sub_rankings()` — `sub_total = len(players)` 사용
- **🔴 2026-06-22 버그 수정**: 프로덕션에서 구버전 calculator.py가 PYTHONPATH 섀도잉으로 import되어 `total_participants=r.total_participants` (전체 NT 인원 173명 → base_points=1200)를 사용. 신버전은 `total_participants=sub_total` (나이그룹별 인원) 사용. 구버전 파일 삭제로 해결.

**포인트 계산 공식**:
- `points = base_points × prestige × rank_ratio × age_weight`
- base_points: 참가자 128+→1200, 64+→1000, 32+→800, 16+→500, 8+→300
- Best N 가중합: [1.0, 0.7, 0.5, 0.3, 0.2, 0.1]
- age_weight: MS=0.7, HS=0.8, UNI=0.9, SR=1.0

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

### Pool 기권(Forfeit/Abandon) 처리 — FIE t.95
- **A 마커**: 해당 선수가 기권 → `is_forfeit: true`, wins/losses 미카운트
- **X 마커**: 상대가 기권 → bout 미진행, wins/losses 미카운트
- **기권자 통계 제외**: pool_calculator, server.py pool_stats 모두 기권자 결과 필터링
- **기권자 순위**: 풀 종합 순위 최하위, `is_forfeit: True` 마킹
- **상대 선수**: 기권자와의 bout은 승/패 계산에서 완전 제외
- **검증**: R23 규칙으로 기권 감지 및 잘못된 집계 경고

### 위반 방지 체크리스트
- [ ] 같은 지표가 서로 다른 숫자로 표시되지 않는가?
- [ ] pool_total_ranking이 pool_rounds 선수 수와 일치하는가?
- [ ] participants 탭의 참가자 수와 헤더의 참가자 수가 같은가?
- [ ] 기권 선수의 bout이 상대 선수 승/패에 포함되지 않았는가?

---

## 🔍🔍🔍 데이터 무결성 검증 (Data Integrity Validation) 🔍🔍🔍

### 원칙: 데이터 오류 제로 (ZERO DATA ERRORS)
데이터 사업에서 **1개의 오류도 있으면 안 된다.** 모든 데이터 수정은 검증을 거쳐야 하며, 새로운 오류 패턴은 반드시 카탈로그에 기록한다.

### 검증 규칙 (R1 ~ R23) 요약

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
| R23 | 이벤트 | Pool 기권(Abandon) 감지 — A/X 마커, 기권 bout 승/패 혼입 |

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

---

## Dual DE 대진표 구조 (Dual Direct Elimination)

### 개요
국가대표선발전 등 대규모 대회에서 사용하는 이중 DE 방식.
First DE(예선 DE)에서 탈락하지 않은 선수들이 Second DE(본선 DE)에 합류하여 결승까지 진행.

### 데이터 구조 (Supabase `events.raw_data.de_bracket`)
```json
{
  "format": "dual_de",
  "bracket_size": 256,
  "first_de": {
    "bracket_size": 256,
    "starting_round": "256강",
    "full_bouts": []
  },
  "second_de": {
    "bracket_size": 64,
    "starting_round": "64강",
    "full_bouts": []
  },
  "full_bouts": [/* 모든 bout이 여기에 저장됨 */],
  "seeded_players": [...],
  "first_de_qualifiers": [...]
}
```

### Bout 분배 로직 (`bracket_utils.py`)
일부 dual DE 이벤트에서 모든 bout이 최상위 `de_bracket.full_bouts`에 저장되고
`first_de.full_bouts`와 `second_de.full_bouts`는 빈 배열인 경우가 있음.

`normalize_dual_de_bracket_data()`에서 자동 분배:
- **Second DE 시작 라운드 이전** (예: 256강, 128강) → First DE
- **Second DE 시작 라운드 이후** (예: 32강~결승) → Second DE
- **공유 라운드** (예: 64강) → `match_num`으로 분리
  - `match_num ≤ bracket_size/2` → Second DE
  - `match_num > bracket_size/2` → First DE

### 라운드 매핑
```
First DE:  256강 → 128강 → 64강 (일부)
Second DE: 64강 (일부) → 32강 → 16강 → 8강 → 준결승 → 결승
```

### FIE 최종순위 규정 (FencingTime 실제 FIE 대회 결과 확인, 2026-06)
```
1위       결승 승자
2위       결승 패자
3T (동률)  준결승 패자 2명 ← 유일한 동률 순위
5위       8강 패자 중 시드 1위
6위       8강 패자 중 시드 2위
7위       8강 패자 중 시드 3위
8위       8강 패자 중 시드 4위
9~16위    16강 패자, 시드 순 개별 순위
17~32위   32강 패자, 시드 순 개별 순위
...이하 동일
```
⚠️ **동률 순위는 3위(3T)만 존재**. QF(8강) 이하는 모두 풀 시드 기반 개별 순위.
구현: `server.py: compute_dual_de_final_rankings()`

### 구현 파일
- `app/bracket_utils.py`: `normalize_dual_de_bracket_data()` - bout 분배 + 정규화
- `app/server.py`: `compute_dual_de_final_rankings()` - Dual DE 최종순위 계산
- `templates/event_result.html`: dual DE 탭 UI (First DE / Second DE)
- `static/css/bracket.css`: 대진표 스타일

---

## 🔄 현재 작업 상태 (2026-07-09)

### ✅ 최근 완료 (이전 세션)

#### Pool 선수 리그 랭킹 표시 + 정렬
- **구현**: pool standings에 리그 순위(league_rank) / 올해 최고순위(league_best) 컬럼 추가
- **정렬 조건**: 경기 결과 없으면 → 리그 랭킹순, 경기 결과 있으면 → 풀 결과순
- **대진표(matrix)**: 풀 결과 rank순 정렬 + scores 배열 재배열(score remapping)
- **FIE 코드 변환**: `get_matching_legacy_codes(ev_age_fie)` → Y14→MS 변환 후 `calculate_rankings()` 호출
- **PlayerRanking 객체**: attribute 접근(`.player_name`, `.current_rank`) — dict 접근 아님
- **코드 위치**: `server.py` ~line 7417 (pool_ranking_map 생성), `event_result.html` (standings/matrix UI)

#### FIE 풀 예상 경기순서
- `FIE_BOUT_ORDER` 상수 (3~8인 풀), `renderBoutOrder()` JS 함수
- 접이식 토글 (`toggleBoutOrder()`)
- `event_result.html` 내 `<script>` 블록

#### 팀 랭킹 모바일 정렬
- 활성 정렬 컬럼을 첫 번째로 동적 재배치
- `.tr-sub` 모바일 숨김

### ⏳ 대기 중 (Pending Plan)

#### 2카드 랭킹 시스템 (piped-cooking-pancake.md)
- **플랜 파일**: `~/.claude/plans/piped-cooking-pancake.md` (6단계 상세 계획)
- **핵심**: NT 선발전 출전 선수 프로필에 2개 랭킹 카드 표시
  - 카드1: 나이리그 랭킹 (일반 대회 + NT 서브랭킹 합산)
  - 카드2: NT 전체 랭킹 (국가대표 선발전 전체 순위)
- **수정 파일**: `calculator.py` (팀 기반 나이추론), `server.py` (primary_age 선택), `player_profile.html` (NT 라벨)
- **핵심 버그**: 박소윤(최병철FC) 프로필이 SR 랭킹(#186/19.4pts)을 표시 — 실제는 MS(#28/74.2pts)
- **근본 원인**: `_infer_player_age_group()`에서 동명이인 3명의 결과 혼합 → SR 기본값 반환

#### 메인 페이지 즐겨찾기 카드 복원
- 이전 세션에서 언급, 미구현

### 🔧 Fable 5 오케스트레이션 (2026-07-12까지)
- **상태**: ON (`fable status`로 확인)
- **구성**: `~/.claude/fable/` (fable.md, agents/, hooks/, env.sh)
- **3티어**: Fable 5 오케스트레이터 → deep-reasoner(Opus 4.8, max) → runner(Haiku 4.5)
- **게이트**: PreToolUse 훅 — 메인 에이전트 턴당 코드 파일 2개 직접 수정 제한, 초과 시 서브에이전트 위임
- **종료**: 7/12 이후 `fable off` 실행
