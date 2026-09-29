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

## ⚠️ Auth 엔드포인트 이동 안내
auth 관련 엔드포인트(로그인, 회원가입, 인증, 프로필)는 **account.fencingmind.ai** (port 70)로 이동되었습니다.
이 서비스에서는 `shared_core.auth.jwt`로 JWT 검증만 수행합니다.

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

### 🔴 정적 파일(CSS/JS) 배포 시 캐시버스터 필수 (2026-08-06 사고)

**정적 파일을 수정했으면 `templates/base.html`의 `?v=` 값을 반드시 함께 올릴 것.** 안 올리면 파일을 배포하고 서버를 재시작해도 **사용자 브라우저에는 옛날 파일이 그대로 간다.**

- **경로**: Cloudflare Tunnel → nginx → FastAPI. Cloudflare가 `?v=` 를 포함한 URL 전체를 캐시 키로 쓰고 `max-age=14400`(4시간)으로 보관한다.
- **증상**: 배포된 파일(`${BASE}/.../dark-theme.css`)에는 수정이 있는데 브라우저 렌더링은 그대로. `curl`로 확인해도 **캐시 우회 쿼리를 쓰면 새 파일이 오기 때문에** "배포는 됐다"고 착각하기 쉽다.
- **실제 사고**: 다크 테마 와일드카드 셀렉터를 고쳐 배포했으나 `?v=20260806a`를 그대로 둠 → Cloudflare가 수정 전 버전을 계속 서빙(age 1659s) → 프로덕션에 반영 안 됨.
- **진단 방법**: 같은 버전 URL과 랜덤 쿼리 URL의 내용을 비교하면 캐시 여부가 드러난다.
  ```bash
  curl -s "https://data.fencingmind.ai/static/css/dark-theme.css?v=20260806a" | grep -c '패턴'
  curl -s "https://data.fencingmind.ai/static/css/dark-theme.css?nocache=$(date +%s%N)" | grep -c '패턴'
  # 두 값이 다르면 CDN 캐시가 낡은 것
  curl -sI "...?v=20260806a" | grep -i "cf-cache\|age"   # age가 크면 캐시 히트
  ```
- **검증 원칙**: 정적 파일 수정 후에는 파일 배포 확인만으로 끝내지 말고 **실제 브라우저 렌더링**(Playwright의 computed style 등)으로 확인할 것. 서브에이전트가 CSS만 고치고 캐시버스터를 안 올리는 경우가 잦으니, 위임할 때 bump를 지시하거나 배포 직전에 직접 확인할 것.

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
- **엄격한 연도 기반**: N년 랭킹 = N년 대회 결과만. 롤링 윈도우 사용 금지 (유일한 예외: NT 전체 랭킹 — 협회 「국가대표 선발 규정」의 이월 규칙을 그대로 따른다, 아래 절)
- **새 연도 빈 데이터**: 새 해 첫 대회 결과 나올 때까지 해당 연도 랭킹 미생성
- **🔴 자유 참가 원칙 (Open Entry Principle)**: 랭킹 포인트는 자유 참가(open entry) 대회만 인정
  - **포인트 인정**: 누구나 자유롭게 참가 신청할 수 있는 대회
  - **포인트 제외**: 시도별 선발 등 소수만 참가하는 선발 참가(nominated/selected) 대회
  - **제외 대회**: 전국체육대회, 전국소년체육대회 (시도별 1명 선발, 13~18명 참가)
  - **결과 표시**: 제외 대회의 경기 결과는 선수 프로필/대회 페이지에 정상 표시 (포인트만 0)
  - **근거**: 선발 참가 대회는 참가 기회의 공정성이 보장되지 않아 전체 선수 실력 비교에 부적합
  - **구현**: `_extract_results()`에서 해당 대회 skip (results 자체를 미생성)
- **2카드 시스템**: NT 선발전 출전 선수는 프로필에 2개 랭킹 표시:
  1. 나이리그 랭킹 (일반 대회 + NT 나이리그별 서브랭킹 포인트 합산) — 아래 포인트 공식(Best-N 가중합)
  2. NT 전체 랭킹 = **국가대표 선발 포인트** — 협회 「국가대표 선발 규정」 그대로 (아래 절)
- **투명한 포인트**: 나이리그 카드는 Best N 대회별 산출 내역, NT 카드는 협회 표와 같은 4개 대회 칸(순위·점수)+합계 공개

### 🔴 NT 전체 랭킹 = 대한펜싱협회 「국가대표 선발 규정」 (2025.04.23 개정) 그대로 — 2026-09-27
구현: `ranking/national_team.py` (`NationalTeamRankingCalculator`). `calculate_rankings(national_team_only=True, age_group='NT')` 는 이 모듈로 위임한다. 프로필 NT 카드·랭킹 페이지 NT 섹션·`/api/rankings?age_group=NT`(응답 `nt` 머리글) 모두 같은 경로. 정답지: 협회 공지판 「N년 국가대표 선발을 위한 4개 대회 합산 점수 및 랭킹 현황」 PDF (2025 최종 boardNo=10578, 2026 8/26 boardNo=10916).
- **제18조 선발시기 → 연도 창**: 당해 연도 8월 중(아시안게임·올림픽 해는 종료 후). "N년 국가대표 선발 포인트" = **기준일(지난해 12/31, 올해 오늘) 시점에 4개 대회 각각 가장 최근에 결과가 나온 회차 1개씩** — 협회 시즌 중 합산표와 같은 규칙. 4개가 모두 N년 회차면 달력 연도와 동일. 아직 안 열렸거나 결과가 없는 대회 칸은 **직전 연도 회차를 이월**(`is_carryover`, `edition_year`; 2016.11.21 부칙 제2조 "차년도 선발 시 중복 적용"; 2026.08.26 표의 "2025 김창환배"). 이월은 직전 연도까지만, 새 회차 결과가 들어오면 교체. 과거 시점 재현은 `calculate_nt_table(..., today=date)`.
- **제20조 ① 대상 대회 4개**: 대통령배 · 김창환배 · 종목별오픈 · 국가대표 선발대회(겸 아닌 것). **개인전만**. 유소년·청소년·파견·클럽 제외. 같은 해 같은 대회가 둘이면 결과가 많은 쪽.
- **제20조 ② 1호 배점**: 1위 32 · 2위 26 · 3위(공동) 20 · 5~8위 14 · 9~16위 8 · 17~32위 4 · 33~64위 2 · 65~96위 1 · 97~128위 0.5. **예선뿔을 통과해 DE에 진출한 선수만** 점수(풀 탈락 0점). DE 진출 판정 근거: `de_bracket`(first_de/second_de seeding·bouts)에 이름이 있으면 진출, **또는 순위가 '대진표에서 확인된 DE 진출자의 최하위 순위' 이내면 진출**(최종 순위표는 DE 진출자 전원이 풀 탈락자 위에 놓이므로 — 예선 64강 경기 유실 같은 대진표 결손 보정; 2025 종목별오픈 33~45위가 이 보정으로 협회와 일치). 대진표가 없으면 `pool_total_ranking.status=='진출'`, 둘 다 없으면 순위표만(`rank_only`, 표에 표기). 협회 표 실측: 순위 121~128위라도 풀 탈락이면 0점 (2026 여자 플러레).
- **제20조 ② 2호** 국제대회 대체 배점(36/32/28…): 국제대회 데이터 없음 → **미반영**(배점표만 보유). **3호** FIE 개인전 랭킹 1~16위 32→17점: `data_fie_rankings`(intl-track 적재; country=KOR, weapon F/E/S, season N = N-1/N 시즌, `player_name_ko`)가 있으면 가산. **협회가 게시하는 「합산 점수 및 랭킹 현황」은 국내 4개 대회만 합산한 표**라(2026.08.26 표 최세빈 86 = 20+32+2+32, FIE 미포함) 우리 표의 순위·total_points 도 국내 합산이다. FIE 는 별도 칸 + **선발 순위**(`selection_rank`, 국내+FIE = 제20조 ①)로 보여 준다. FIE 데이터 없으면 "FIE 점수 미반영".
- **제20조 ③ 동점** (협회 표 실측으로 확정): 점수를 받은 순위들을 좋은 순으로 늘어놓고 **사전식 비교** — [2,6,11,17] 이 [2,8,14,19] 보다 앞(2026 여사브르 양예솔·선은비), [6,10,18,20] < [6,15,23,28] < [7,11,29,30](2025 여사브르 11~13위); 결과가 적으면 빈 칸을 뒤로. 그래도 같으면 대통령배→김창환배→종목별오픈→국대선발 성적 순. (점수 구간별 개수 비교는 협회와 어긋나서 폐기.)
- **제21조 선발권**: 상위 8명(선수촌) + 25세이하 후보 8명. 증원된 해는 `NT_SELECTION_QUOTA_OVERRIDES` (2025 남녀 사브르 12).
- **Best-N 가중합·참가자 수 base_points·연령 가중치는 NT 랭킹에 쓰지 않는다.** (나이리그 랭킹·NT 나이리그 서브랭킹은 그대로.)
- **이월 칸 표시**: 랭킹 페이지 헤더 "2025 김창환배 · 직전 회차", 표 위 안내에 이월 개수와 부칙 근거, 프로필 카드도 회차 연도·"직전 회차" 태그. (2026-09-27 이전엔 달력 연도 창이었음 — 협회 표와 시즌 중 합계가 달라 폐기.)
- **동명이인**: 협회는 생년월일로 가르지만 우리는 이름·소속뿐. 같은 종목 순위표에 같은 이름이 다른 소속으로 나오면 (이름, 소속 그룹)으로 분리, 아니면 이름으로 합산. 소속 그룹은 `PlayerIdentityResolver.get_players_by_name` 의 소속 집합(개명 인천광역시중구청→영종구청·이적을 한 사람으로)이며 서버가 `team_groups_lookup` 으로 넘긴다. 순위표의 `(*)` 표식은 DE 대진표와 맞출 때만 뗀다.
- **검증(2026-09-27, 2025 데이터 복구 후)**: 2025 최종표(boardNo 10578) 1,370행 중 총점 일치 97.6%(불일치는 2025 종목별오픈 121~128위 0.5점 여부 등 소수), 6종목 상위 8/12 집합·순서 모두 일치, 2025 선발 명단(10576) 56명의 협회 합산 순위와 우리 순위 정확 일치 56/56. 2026 8/26 표(10916, 2025 김창환배 이월) 1,511행 중 98.5%, 6종목 상위 8 집합·순서 일치. 남는 불일치는 동명이인·협회 표에만 있는 소수 선수. 2023·2024는 대통령배·종목별오픈 개인전 이벤트가 DB에 없어 대조 불가.
- 단위 테스트: `tests/test_national_team_ranking.py` (배점·예선탈락 0점·연도 창·동점·FIE·동명이인·calculator 경유).
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

### 검증 규칙 (R1 ~ R28) 요약

| 규칙 | 검증 대상 | 설명 |
|------|----------|------|
| R1a/R1b | 이벤트 | Self-bout / Duplicate bout. ⚠️ R1a 는 2026-09-28까지 **발동 자체가 불가능**했다 — `_get_full_bouts_from_bracket()` 이 p1==p2 경기를 입력에서 먼저 지워, 규칙이 세려던 증거가 사라진 뒤에 검사했다. raw bout 경로로 옮겨 고쳤다(그 사이 자기경기 3,598건이 251종목에 쌓였다) |
| R1c | 이벤트 | 라운드 정원 초과 (16강에 9경기 이상 등, 부전승 제외). 위상 없는 dual DE 는 R25 에 양보 |
| R2 | 이벤트 | Winner 일관성 (winner ∉ {p1, p2}) |
| R3 | 이벤트 | 점수 범위 이상 (음수, >15, 동점) |
| R4 | 이벤트 | 빈/비표준 round_name |
| R5 | 이벤트 | Bracket topology (승자→다음 라운드) |
| R6 | 이벤트 | Final ranking vs DE bracket 불일치 |
| R7 | 선수 | 같은 라운드 2경기 이상 |
| R8 | 선수 | 라운드 진행 보존법칙 (경기 유실) — **라운드 크기별로 따로 본다.** 256/128/64/32강을 한 칸으로 뭉쳐 비교하면 64강·32강을 연달아 이기고 16강 1경기만 치른 선수가 '1경기 유실'로 잡힌다 (2026-09-28 오탐 3,407건 수정) |
| R9 | 선수 | Pool 경기수 이상 (>8) |
| R10 | 선수 | 성별 불일치 (동명이인) |
| R11 | 선수 | 나이그룹 역행 (동명이인) |
| R12 | 선수 | 무기 3종 이상 (동명이인) |
| R23 | 이벤트 | Pool 기권(Abandon) 감지 — A/X 마커, 기권 bout 승/패 혼입 |
| R24 | 이벤트 | Dual DE 공유 라운드 유실 — 예선에 공유 라운드(본선 시작 라운드) 경기가 0개 / 반쪽 스크래핑 |
| R25 | 이벤트 | Dual DE bout 의 `de_phase` 누락 — 예선/본선 구분 불가 상태, 위상 없는 라운드명 충돌 |
| R26 | 이벤트 | 최종순위 1·2위 결손 (동률은 3위만 허용 — FIE 규정). 협회가 표를 안 내는 단체전은 우리 계산분에서 결승 승자가 비면 이 상태가 된다 (2026-09-28 42종목 복구) |
| R27 | 이벤트 | 순위표에만 있는 이름 — 풀·DE 로스터에 없는 선수가 final_rankings 에 있음. `(*)` 표식 정규화 후 판정, 로스터 확보율 80% 미만이면 판정 포기 |
| R28 | 이벤트 | DE 이름 뭉개짐 — 한 이름이 브래킷 슬롯을 비정상 점유(슬롯 10개 이상, 구조적 상한 9). 내용 중복이면 ERROR, 동명이인 가능하면 WARNING |
| F07/F14 | 감사 스크립트 | `audit_final_rankings.py` 전용. 전국체육대회·소년체육대회는 협회가 풀을 게시하지 않아(해당 대회군 96종목 풀 보유 0 / 타 대회 1,872종목 중 93% 보유) F07(결손)이 아니라 F14(정보성)로 분류한다 |

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

## 🚨🚨🚨 Dual DE: 예선 64강 ≠ 본선 64강 (처음 보는 개발자는 반드시 읽을 것) 🚨🚨🚨

**이 절은 이 코드베이스에서 데이터를 두 번 파괴한 함정을 설명한다. 10년 뒤에 읽어도 같은 실수를 하지 않도록 쓴다.**

### 왜 64강이 두 번 나오는가

국가대표 선발 대회(대통령배, 회장기 등)는 **두 개의 독립된 토너먼트**를 연달아 치른다.

```
예선 DE (First DE, 예선엘리미나시옹디렉트)     본선 DE (Second DE, 본선 64강)
  128강 (64경기)                                  ┌─ 시드 32명 (예선 면제자)
     ↓                                            │
   64강 (32경기) ── 승자 32명 ──────────────────→ ├─ 64강 (32경기)
                                                  │     ↓
                                                  │   32강 → 16강 → 8강 → 준결승 → 결승
```

- 예선 64강 32경기와 본선 64강 32경기는 **완전히 다른 경기다.** 선수도, 점수도, 날짜도 다르다.
- 그런데 KFA 원본에서 둘 다 라운드 이름이 문자열 `"64강"` 이다.
- 128 브래킷 종목의 정답은 **159경기** = 예선 128강 64 + 예선 64강 32 + 본선 63.
  256 브래킷은 **287경기** = 예선 256강 128 + 128강 64 + 64강 32 + 본선 63.

### 🔴 절대 금지: 라운드 이름을 키로 쓰지 말 것

```python
# ❌ 절대 금지 — 예선 64강과 본선 64강이 같은 칸에 들어가 한쪽이 사라진다
bouts_by_round[bout["round_name"]].append(bout)
if bout["round_name"] == "64강": ...
seen.add(bout["bout_id"])          # bout_id = "64강_01" 도 위상을 담지 않는다

# ✅ 항상 위상을 포함한 복합 키
from app.bracket_utils import phase_bout_key, get_bout_phase
seen.add(phase_bout_key(bout))     # (de_phase, round_name, match_number)
```

`bout_id` 는 `f"{round_name}_{match_number:02d}"` 형식이며 **위상을 담지 않는다.** 식별자 자체를 바꾸면 하위 소비자가 전부 깨지므로, **식별자가 아니라 그것을 쓰는 키를 복합 키로 바꾸는 것**이 이 코드베이스의 규약이다.

### 우리가 위상을 구분하는 방법: `de_phase`

모든 DE bout 은 자기가 어느 토너먼트 소속인지 **스스로 들고 다닌다.**

| 값 | 의미 |
|---|---|
| `"qualifying"` | 예선 DE (first_de) |
| `"main"` | 본선 DE (second_de) **및 모든 단일 DE·단체전** |
| 키 자체가 없음 | **이 변경(2026-08-18) 이전에 저장된 구 레코드** — 그 외의 의미는 없다 |

- 스크래퍼가 `select#schEtc01` 로 어느 화면을 보고 있는지 알 때 stamp 한다 (`de_scraper_v4.py`: `DEScraper.current_de_phase` → `DEMatch.de_phase`). **파싱 시점에 붙는다** — 직렬화 시점에 붙이면 파싱 중 실행되는 `_deduplicate_matches()` 가 이미 두 경기를 합쳐버린 뒤다.
- 저장 위치: `de_bracket.full_bouts[*]`, `first_de.bouts[*]`, `first_de.bouts_by_round[*][*]`, `second_de` 동일.
- **이 필드를 잃으면 무슨 일이 생기는가**: 예선 64강과 본선 64강이 구분 불가능해진다. 랭킹/선발 포인트가 예선 패자를 본선 33위로 계산하고(`ranking/selection_points.py`), H2H 가 두 경기 중 하나를 버리고, 프로필 경로보기가 64강 노드를 하나만 그린다. 그리고 다음 스크래핑에서 조용히 덮어써진다.

### 표시 라벨 — 화면에는 반드시 위상을 드러낼 것

```python
from app.de_transforms import de_round_label   # 또는 app.bracket_utils

de_round_label("64강", "qualifying")   # → "예선 64강"
de_round_label("64강", "main")         # → "본선 64강"
de_round_label("64강", None)           # → "64강"  (구 레코드에 거짓 라벨을 붙이지 않는다)
de_round_label("64강", "main", qualifying_prefix=_t("예선"), main_prefix=_t("본선"))  # i18n
```

접두사가 인자인 이유는 7개 언어를 지원하기 때문이다. `bracket_utils` 에 i18n 을 import 하지 말 것(최하위 레이어).

### 실제 유실 이력 (같은 일을 세 번째로 겪지 말 것)

| 날짜 | 무엇이 사라졌나 | 원인 |
|------|----------------|------|
| 2026-08-17 | 제66회 대통령배 128 브래킷 3종목: 예선 64강 32경기 (159 → 127) | 예선 화면의 라운드 탭은 시작 라운드 하나만 광고한다. `fnGetMatch()` 재렌더 과정에서 64강 컬럼이 페어링 없는 '승자 표시 컬럼'으로 강등된다. 초기 렌더에는 있는데 탭을 누르는 순간 사라진다 → `_parse_tournament_table_bracket()` 이 `fnGetMatch` 호출 **전에** 초기 렌더를 선추출해 `compmatsym` 으로 병합하도록 수정 (커밋 `e5f8c29`) |
| 2026-08-18 | 같은 3종목이 다시 127경기로 회귀 | **① 스케줄러 프로세스가 7/31부터 18일간 떠 있어서** 디스크에 배포된 수정 코드가 아니라 메모리에 로드된 구버전 모듈을 계속 실행했다. **② 그렇게 만들어진 부분 데이터(127)가 완전 데이터(159)를 덮어썼다** — `_de_data_quality_score()` 가 '점수 있는 경기가 하나라도 있으면 3'에서 천장을 쳐서 159와 127이 **둘 다 3점**이라 보존 가드가 발동하지 않았다 |

**교훈 ①(운영):** 스크래퍼/스케줄러 코드를 배포했으면 **반드시 스케줄러 프로세스를 재시작**해야 한다. 파일만 바꾸는 것은 배포가 아니다. 2026-07-11 PYTHONPATH 섀도잉 사고와 같은 계열의 실패다 — "배포했는데 반영 안 됨".
```bash
ps -eo pid,lstart,command | grep run_scheduler   # 시작 시각이 배포 시각보다 앞서면 구코드가 돌고 있다
```

**교훈 ②(설계):** 데이터 품질을 '있다/없다'로 재면 부분 유실을 못 잡는다. **내용을 비교**해야 한다.

### 재발 방지 장치 (4중)

| 계층 | 위치 | 동작 |
|------|------|------|
| 스크래핑 직후 | `full_scraper._validate_scrape_completeness()` → `DUAL_DE_QUALIFYING_ROUND_MISSING` (ERROR) | `second_de.starting_round`(공유 라운드)의 경기가 `first_de` 에 0개면 경고 |
| 저장 직전 | `competition_detector._de_bracket_regression()` → `DE_BRACKET_REGRESSION` (ERROR) | 기존에 있던 경기가 새 데이터에 없으면 **저장 거부하고 기존 유지**. 선수쌍 기반 집합 비교라 ⑴ match_number 재부여에 흔들리지 않고 ⑵ 중복 저장 사고에 발이 묶이지 않는다 |
| 검증 배치 | `data_validator` R24 | dual_de 인데 공유 라운드가 예선에 없으면 ERROR / 한쪽 위상만 있는 반쪽 스크래핑 ERROR |
| 검증 배치 | `data_validator` R25 | dual_de 이벤트의 DE bout 에 `de_phase` 가 없으면 ERROR (이벤트 단위 집계). 위상 없는 `(round_name, match_number)` 충돌쌍도 ERROR |

Discord 알림은 `competition_detector.ALERTING_WARNING_TYPES` 허용목록으로 좁혀져 있다. 경고는 전부 `raw_data._scrape_metadata.scrape_warnings` 에 기록되지만, 알림은 지금 사람이 봐야 하는 유형만 보낸다. 새 유형을 알리려면 그 목록에 명시적으로 추가할 것.

### 🔢 경기 수를 세는 법 — 슬롯 수 ≠ 경기 수

**부전승(bye)은 경기가 아니다.** 풀 기권 규약(FIE t.95, A/X 셀을 승패에 카운트하지 않음)과 같은 원칙이다.

`build_dual_de_progress()` 의 라운드별 항목은 세 값을 **각각** 준다:

| 필드 | 의미 | 화면에 쓰나? |
|------|------|-------------|
| `total` | 브래킷 **슬롯 수** (부전승 포함) | ❌ 이걸 "N경기"라고 쓰면 안 된다 |
| `real` | **실제 경기 수** = `total - byes` | ✅ "N경기"는 이 값 |
| `byes` | 부전승 수 | ✅ "(부전승 N)" 처럼 분리 표기 |

합계는 `first_de_real_bouts` / `first_de_byes` / `second_de_real_bouts` / `second_de_byes`.

실측 (제66회 대통령배, 2026-08-18):
```
여자 에페 예선 128강   슬롯 64  = 실제 57 + 부전승 7
남자 에페 예선 256강   슬롯 128 = 실제 32 + 부전승 96   ← 화면엔 "128경기"로 나가던 값 (실제의 4배)
남자 에페 예선 128강   슬롯 64  = 실제 64 + 부전승 0
여자 플뢰레 예선 128강 슬롯 64  = 실제 34 + 부전승 30
```

부전승 판정은 반드시 `bracket_utils.is_bye_bout()` 을 쓴다 — `is_bye` 플래그와 **'한쪽 이름이 비어 있음'의 합집합**이다. 스크래퍼 경로에 따라 플래그 없이 슬롯만 비는 형태가 있어 한쪽만 보면 부전승을 경기로 센다. (기권은 부전승이 아니다. 양쪽 선수가 실재하는 편성된 경기이므로 `real` 에 포함된다.)

### 🔢 참가 인원 — 이름으로 dedup 하지 말 것 (동명이인)

참가 인원은 **시드 슬롯 수** 기준이며 데이터로 확정된다: `build_dual_de_progress()['first_de_participants']`.

`bout` 에서 뽑은 **고유 이름 수**를 참가 인원으로 쓰면 **항상 몇 명 적게 나온다.** 데이터 결손이 아니라 **동명이인**이 한 명으로 합쳐지기 때문이다. 실측에서 4개 dual 종목 전부 정확히 2명씩 적었다:

```
                이름 채워진 슬롯   seeding   고유 이름   차이   동명이인
여자 에페           121            121       119        2     김민서 2명, 김나연 2명
남자 플뢰레          123            123       121        2     김도영 2명, 정유준 2명
남자 에페           160            160       158        2     이승현 2명, 이우빈 2명
여자 플뢰레           98             98        96        2     최예진 2명, 김하은 2명
```

`이름 채워진 슬롯 = 2×슬롯수 − 부전승 = seeding 길이` 가 **정확히 일치**하고 seeding 이름 중 bout 에 없는 사람은 0명이다 → 결손 없음. 따라서 참가 인원은 표시해도 되는 확정 수치다.

⚠️ `de_bracket.participant_count` (스크래퍼가 쓰는 최상위 값)는 **이름 dedup 방식이라 동명이인을 누락한다.** 참가 인원 표시에 쓰지 말 것.

### 하위 호환 (구 레코드)

현재 DB의 **모든** 기존 레코드에는 `de_phase` 가 없다. 따라서:
- `de_phase` 부재로 **크래시하면 안 된다.** 항상 `get_bout_phase(bout, default)` 로 읽는다.
- 부재 시에는 기존 동작(= `match_number` 기반 휴리스틱 분배)으로 **정확히** 폴백한다. 새 로직을 구 레코드에 적용하지 않는다.
- 없는 위상을 **추측해서 만들지 않는다.** 모르면 없는 채로 두고 R25 가 잡게 한다 (제1원칙).

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

`normalize_dual_de_bracket_data()`에서 자동 분배. **판정 우선순위가 중요하다:**

1. **bout 에 `de_phase` 가 있으면 그것이 절대적 진실** — 스크래퍼가 어느 화면을 보고 있었는지 알고 붙인 값이다. 아래 휴리스틱을 적용하지 않는다.
2. **`de_phase` 가 없을 때만**(= 2026-08-18 이전 구 레코드) 아래 위치 기반 휴리스틱으로 폴백:
   - **Second DE 시작 라운드 이전** (예: 256강, 128강) → First DE
   - **Second DE 시작 라운드 이후** (예: 32강~결승) → Second DE
   - **공유 라운드** (예: 64강) → `match_num`으로 분리
     - `match_num ≤ bracket_size/2` → Second DE
     - `match_num > bracket_size/2` → First DE

⚠️ 이 휴리스틱은 스크래퍼가 `match_number` 를 브래킷 전역 연속번호로 재부여한다는 전제 위에서만 성립하며, **예선 DE 자체가 공유 라운드에서 시작하는 대회에서는 예선 전체를 본선으로 오분류한다.** 그래서 `de_phase` 를 도입했다. 새 데이터에는 절대 이 경로가 쓰이지 않아야 한다.

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

## 🎨 디자인 시스템 방향 (2026-07-31 확정 — 스포츠 데이터 브랜드)

**사용자가 확정한 방향. 이후 모든 UI 작업은 이 규칙을 따를 것.**

- **디스플레이 서체**: Barlow Condensed 600/700 (`static/fonts/` 셀프호스팅, latin 서브셋 30KB)
  - 토큰 `--fm-font-display`, 클래스 `.fm-num`/`.fm-num--semi` — 랭크·포인트·스코어·D-day 등 데이터 숫자 전용
  - ⚠️ latin만 로드됨 — 한글 혼합 텍스트에 `.fm-num` 부여 금지
- **본문/헤드라인**: Pretendard 웨이트 계층(400~900). **Inter는 제거됨 — 재도입 금지**
- **액센트**: 태극 레드 `#c9302c` / 태극 블루 `#1e3a8a` **만**. 보라(#667eea/#764ba2/#6c5ce7)는 AI 슬롭으로 전면 제거됨 — 재도입 금지
- **UPCOMING 스트립**: 홈/대회목록 공통 태극 네이비 밴드(`#1e3a8a→#16306e`) + 콘덴스드 레드 D-day 1.35rem. 두 페이지 값을 항상 함께 유지
- **라이트 테마 배경**: 다크와 동일한 선수 parallax 이미지 + 흰색 오버레이(0.72→0.97), grayscale 0.25. 콘텐츠 표면은 불투명 유지
- **금지 패턴** (Impeccable 디텍터 기준): gradient-text, 카드 3px+ 컬러 border-left, width/max-height/padding transition, 오프셋 0 halo 그림자, 다색 그라데이션 CTA
- **검증**: `node ~/.claude/skills/impeccable/scripts/detect.mjs --json <파일>` (2026-07-31 기준 24→1건, 잔여 1건은 동명이인 아코디언 max-height 의도적 유지)
- **크리틱 원본**: `.impeccable/critique/2026-07-30T04-12-33Z__services-data-core-pages.md` (26/40)

---

## 🎨 UI 디자인 규칙 (필수)

**⚠️ 적용 범위**: 아래는 모노레포 공통 `shared-ui` 기준 규칙이다. data 서비스는 위 "디자인 시스템 방향 (2026-07-31 확정)"이 우선하며, 언어별 라이트 테마를 실제로 운영 중이므로 "다크 모드만" 항목은 data 서비스에 적용되지 않는다.

**📖 반드시 참조:** `packages/shared-ui/DESIGN_SYSTEM.md`

### 필수 CSS 임포트
```html
<link rel="stylesheet" href="/packages/shared-ui/styles/variables.css">
<link rel="stylesheet" href="/packages/shared-ui/styles/base.css">
<link rel="stylesheet" href="/packages/shared-ui/styles/components.css">
```

### 핵심 규칙
| 규칙 | 설명 |
|------|------|
| 🔴 **다크 모드만** | 라이트 모드 UI 금지 |
| 🔴 **CSS 변수 사용** | `--fm-*` 변수 필수 (하드코딩 색상 금지) |
| 🔴 **컴포넌트 클래스** | `fm-btn`, `fm-card`, `fm-input` 등 사용 |
| 🔴 **배경 구조** | `fm-parallax-bg` + `fm-parallax-overlay` |

### 색상 팔레트 (태극기 컬러)
```css
--fm-accent-primary: #c9302c;    /* 빨강 - Primary CTA */
--fm-accent-secondary: #1e3a8a;  /* 파랑 - Secondary */
--fm-bg-card: rgba(18, 18, 26, 0.85);  /* 글래스 카드 */
```

### 랭킹 테이블 예시
```html
<div class="fm-card">
    <div class="fm-card-header">
        <h3 class="fm-card-title">남자 플뢰레 랭킹</h3>
    </div>
    <div class="fm-table-container">
        <table class="fm-table">
            <thead>
                <tr>
                    <th>순위</th>
                    <th>선수</th>
                    <th>소속</th>
                    <th>점수</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><span class="fm-badge fm-badge-gold">1</span></td>
                    <td>홍길동</td>
                    <td>최병철펜싱클럽</td>
                    <td>2,450</td>
                </tr>
            </tbody>
        </table>
    </div>
</div>
```

### 대회 카드 예시
```html
<div class="fm-card">
    <div class="fm-card-header">
        <h3 class="fm-card-title">2025 회장배 전국대회</h3>
        <span class="fm-badge fm-badge-info">진행 중</span>
    </div>
    <div class="fm-card-body">
        <p class="fm-text-secondary">2025.01.15 ~ 2025.01.17</p>
        <p class="fm-text-secondary">장소: 태릉선수촌</p>
        <button class="fm-btn fm-btn-primary">결과 보기</button>
    </div>
</div>
```

---

## 🔄 현재 작업 상태 (2026-08-03)

### ✅ 최근 완료 (2026-07-31 ~ 08-01, 커밋 24dc3f8 · 516d46f · b9e9664, 프로덕션 배포됨)

#### 디자인 패스 1 — 크리틱 지적 수정 + 범례/툴팁
- 논블로킹 온보딩 카드(전면 모달 제거), 홈 에러 "다시 시도" 버튼, FencingLab 데모 500 → 200 graceful degrade
- i18n 누수 수정(~36키 × 6언어), WCAG muted 대비(#9a9aad/#6b7280), 필터 aria-label, 이중 페이월 CTA 차별화
- 공용 `.fm-help` 툴팁 컴포넌트: A26 레이팅 기준, 8/57·P3 순위 표기, Pool/DE 용어 설명
- 원시 코드 노출 제거: 프로필 랭킹 카드 "MS (Pro)" → "중등 (전문)", 랭킹 섹션 헤더 "SR" → "일반"/"Senior"
  (server.py `age_group_display_map`에 E1~SR 코드 라벨 추가 + rankings.html JS ageMap 이중 수정)

#### 디자인 패스 2 — 스포츠 데이터 브랜드 (위 디자인 시스템 방향 섹션 참조)
- Barlow Condensed 도입, Inter 제거, AI 슬롭 제거(디텍터 24→1)

#### 라이트 테마 + 선호 리그 변경 (2026-08-01)
- 라이트 테마에 선수 parallax 배경 표시 (이후 사용자 피드백으로 다크 수준 가시성으로 강화)
- **선호 리그 변경 진입점 신설**: 랭킹 미리보기 카드 헤더 버튼 + 나이그룹 미선택자용 폴백 스트립
  - `window.fmOpenSportSelector()` (mobile-ux.js) — 온보딩 시트 재오픈 + 저장값 프리필
  - 수정 버그: click-outside 핸들러가 `.fm-prefs-edit` 클릭을 바깥으로 오인해 즉시 닫던 레이스
- ⚠️ 선호 리그는 localStorage `fm_preferences`(v2)에만 저장 — weapon은 영문 코드('foil'/'epee'/'sabre'), gender는 '남'/'여', age_group은 온보딩 키('middle_school' 등)

#### 2카드 랭킹 시스템 — 렌더링 확인 완료
- 박소윤 프로필이 MS #30/118 (148.8pts) + NT #84/163 정상 표시 (기존 pending 플랜 해소)

### ⏳ 다음 후보 (우선순위 미정 — 사용자 지시 대기)

1. **선호 리그 계정 동기화** — 현재 기기별 localStorage만. members 테이블 연동으로 로그인 시 기기 간 공유
2. **이모지 아이콘 → SVG 아이콘 시스템** — 🥇📋🏆 등 이모지를 일관된 stroke SVG로 (범위 큼)
3. **FencingLab 차트 페이지 디자인 패스** — 이번 5개 코어 페이지 범위에서 제외됐던 영역
4. **키보드 단축키** — 크리틱 잔여 (Esc는 툴팁·온보딩에 적용됨)
5. **메인 페이지 즐겨찾기 카드 복원** — 이전 세션 언급, 미구현

### 📌 스택 결정 (2026-08-03)
- **Next.js/React 도입 안 함** — FastAPI + Jinja2 + 바닐라 JS 유지 (package.json 없음)
- 동적 UI 강화가 필요해지면 **htmx/Alpine.js** 부분 도입 검토 (Jinja2 공존, 재작성 불필요)
- React류는 app.fencingmind.ai 신규 개발 시에만 별도 검토 (data 서비스는 유지)
- 디자인 스킬 스택 질문에는 "순수 HTML" 또는 자유입력으로 "FastAPI + Jinja2 + vanilla JS/CSS" 답변

### 🔧 Fable 5 오케스트레이션
- **상태**: 게이트 훅 여전히 활성 (턴당 코드 파일 2개 직접 수정 제한 — 초과분은 서브에이전트 위임)
- **구성**: `~/.claude/fable/` (fable.md, agents/, hooks/, env.sh) · 종료는 `fable off`
