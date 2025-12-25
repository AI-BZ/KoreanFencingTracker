# Korean Fencing Tracker - Project Context

## 🚫🚫🚫 제0원칙: Claude 행동 규칙 (CLAUDE BEHAVIOR RULES) 🚫🚫🚫

**이 규칙은 모든 다른 규칙보다 우선합니다**

### 1. 할루시네이션 금지 (NO HALLUCINATION)
- **모르면 모른다고 말하기** - 추측하거나 지어내지 않기
- **확인되지 않은 정보 제공 금지** - 데이터/코드 확인 없이 "~일 것입니다" 금지
- **잘못 알았으면 즉시 인정** - 변명하지 않고 바로 수정

### 2. 룰 변경 시 반드시 허가 받기 (ASK BEFORE CHANGING RULES)
- **기존 동작 방식 변경 금지** - 사용자 허가 없이 로직/UI/데이터 표시 방식 변경 금지
- **"이게 더 좋을 것 같아서" 금지** - 사용자가 요청한 것만 수행
- **불확실하면 질문하기** - 마음대로 판단하지 않고 확인 요청

### 3. 선수 소속 표시 규칙 (PLAYER TEAM DISPLAY)
- **현재 소속은 단 한 군데** - 가장 최근 대회에서의 소속만 표시
- **소속 이력은 별도 섹션** - team_history에서 이전 소속 기록 표시
- **예시**:
  - ✅ 현재 소속: `최병철펜싱클럽`
  - ✅ 소속 이력: `송도펜싱클럽(2023-06~2024-08)`, `최병철펜싱클럽(2024-09~현재)`
  - ❌ 잘못된 표시: `송도펜싱클럽, 최병철펜싱클럽` (두 개 나열 금지)

---

## 🔴🔴🔴 제1원칙: 데이터 파이프라인 연결 (DATA PIPELINE INTEGRITY) 🔴🔴🔴

**데이터 사업의 생존 원칙**: 한 곳에서 데이터가 수정되면 관련된 모든 데이터가 파이프라인을 통해 자동으로 업데이트되어야 함

### 핵심 규칙
1. **단일 진실 원천 (Single Source of Truth)**
   - 선수 프로필: `PlayerIdentityResolver` → 모든 UI/API가 이를 참조
   - 수정 발생 시 → 관련 캐시/파생 데이터 모두 무효화 및 재계산

2. **파이프라인 전파 (Propagation)**
   - 선수 프로필 수정 → members 테이블 동기화 → 로스터 UI 업데이트
   - 동명이인 분리/병합 → 모든 참조 데이터 자동 업데이트

3. **데이터 무결성 규칙 (ABSOLUTE)**
   - **성별 불변**: 남자 ↔ 여자 전환 절대 불가 (다른 사람임)
   - **나이그룹 진행**: 시간이 지나면 나이그룹은 올라가거나 유지 (절대 내려가지 않음)
   - **무기 일관성**: 대부분 단일 무기 전문 (2개 이상이면 동명이인 가능성)

4. **위반 시 결과**
   - 데이터 불일치 → 사용자 신뢰 상실 → 사업 실패
   - 모든 데이터 수정 작업은 파이프라인 전파 검증 필수

### 구현 체크리스트
- [ ] 선수 프로필 수정 시 members 테이블 자동 동기화
- [ ] 동명이인 분리/병합 시 연관 데이터 재계산
- [ ] 캐시 무효화 메커니즘 구현
- [ ] 데이터 변경 로그 기록

---

## 🚨🚨🚨 CRITICAL: 데이터 소스 규칙 (반드시 읽으세요!) 🚨🚨🚨

### ❌ 절대 금지 (DO NOT)
- **JSON 파일 생성 금지** - `data/*.json` 파일 새로 만들지 마세요
- **JSON 파일에서 데이터 로드 금지** - 로컬 JSON 파일 읽지 마세요
- **별도 데이터 파일 관리 금지** - 익산, 특정 대회 등 분리 관리 금지
- **test_*.py로 JSON 분석 금지** - 테스트도 Supabase 사용

### ✅ 반드시 사용 (MUST USE)
- **모든 대회 데이터**: `Supabase > competitions` 테이블
- **모든 종목 데이터**: `Supabase > events` 테이블
- **모든 선수 데이터**: `Supabase > players` 테이블
- **모든 순위 데이터**: `Supabase > rankings` 테이블
- **회원 데이터**: `Supabase > members` 테이블

### 📊 현재 Supabase 데이터 현황 (2025-12-22)
| 테이블 | 데이터 수 | 설명 |
|--------|----------|------|
| competitions | 132 | 2019-2025 대회 (익산 포함) |
| events | 2,500 | 모든 종목 |
| players | 11,786 | 모든 선수 |
| rankings | 964 | 최종 순위 |
| members | 11 | 클럽 회원 |
| organizations | 507 | 팀/클럽/학교 |

### 🔧 데이터 조회 방법
```python
# ✅ 올바른 방법 - Supabase MCP 사용
mcp__supabase__execute_sql("SELECT * FROM competitions WHERE ...")
mcp__supabase__execute_sql("SELECT * FROM players WHERE team_name LIKE '%최병철%'")

# ❌ 잘못된 방법 - JSON 파일 사용
# with open("data/fencing_data.json") as f:  # 사용 금지!
#     data = json.load(f)
```

### ⚠️ data/ 폴더의 JSON 파일들
`data/backup/`에 백업 용도로만 보관, **절대 코드에서 로드하지 마세요**

---

## Project Overview
대한펜싱협회(fencing.sports.or.kr) 대회 결과 데이터를 수집하여 웹사이트로 제공하는 프로젝트

## Current Status (2025-12-22)

### Scraping Status
| 연도 | 상태 | 비고 |
|------|------|------|
| 2019~2025 | ✅ 완료 | Supabase에 업로드 완료 |
| 2018 이전 | ❌ 불필요 | 텍스트 공지 형태만 (디지털 결과 없음) |

### Database Status
- **Supabase**: ✅ 모든 데이터 업로드 완료
- 테이블: competitions, events, players, matches, rankings, scrape_logs, organizations, members, attendance, fees 등

## Supabase MCP 사용 가이드

### MCP 설정
`.mcp.json`에 Supabase MCP 설정됨:
```json
{
  "mcpServers": {
    "supabase": {
      "command": "npx",
      "args": ["-y", "@supabase/mcp-server-supabase@latest", "--project-ref=tjfjuasvjzjawyckengv"],
      "env": { "SUPABASE_ACCESS_TOKEN": "sbp_..." }
    }
  }
}
```

### 마이그레이션 실행 방법
**✅ 우선: Supabase MCP 사용** (Claude Code에서 직접 실행)
```
# MCP 도구 사용 예시
mcp__supabase__execute_sql - SQL 직접 실행
mcp__supabase__list_tables - 테이블 목록 조회
mcp__supabase__get_table_schema - 스키마 조회
```

**⚠️ MCP 미연결시**: Claude Code 재시작 필요
- `/mcp` 명령으로 MCP 상태 확인
- 재시작 후에도 안되면 Dashboard SQL Editor 사용

### MCP 기본 활성화 설정
`~/.claude.json`에 명시적으로 설정됨:
```json
"enabledMcpjsonServers": ["supabase", "github"],
"disabledMcpjsonServers": [],
"disabledMcpServers": []
```
⚠️ MCP가 disable로 변경되면 위 설정 확인 필요

### 마이그레이션 파일 위치
```
database/migrations/
├── 001_create_tables.sql        # 기본 테이블
└── 002_add_organizations_table.sql  # 조직/주소 테이블
```

## Architecture

### Components
```
FencingCommunityDropShipping/
├── app/
│   ├── server.py          # FastAPI 웹 서버
│   └── ai_chat.py         # AI 검색 기능
├── scraper/
│   ├── playwright_scraper.py  # Playwright 기반 스크래퍼 (메인)
│   ├── client.py          # API 클라이언트 (httpx 기반)
│   └── models.py          # Pydantic 모델
├── database/
│   └── supabase_client.py # Supabase 연동
├── templates/             # Jinja2 HTML 템플릿
├── static/                # CSS, JS 정적 파일
└── scheduler/             # 자동 업데이트 스케줄러
```

### Key Endpoints
- `/` - 메인 페이지 (대회 목록)
- `/competition/{event_cd}` - 대회 상세
- `/search` - 선수 검색
- `/chat` - AI 검색
- `/api/competitions` - 대회 목록 API
- `/api/chat` - AI 채팅 API

## Scraper Details

### 🚨 스크래퍼 파일 관리 규칙 (CRITICAL)

#### ✅ 메인 스크래퍼 (사용 중)
```
scraper/
├── full_scraper.py   ← 유일한 메인 스크래퍼 (대한펜싱협회 전체 대회)
├── client.py         ← API 클라이언트
├── config.py         ← 설정
└── models.py         ← 데이터 모델
```

#### 📦 백업 폴더 (사용 완료/deprecated)
```
scraper/backup/
├── playwright_scraper.py    # deprecated - full_scraper.py로 대체됨
├── iksan_international.py   # 2025 익산 대회 전용 (사용 완료)
├── incremental_scraper.py   # 증분 스크래퍼
├── diagnose_*.py            # 디버깅 도구
└── rescrape_*.py            # 재스크래핑 유틸리티
```

#### ⚠️ 대회별 스크래퍼 규칙
- **특정 대회용 스크래퍼 작성 시**: 사용 완료 후 반드시 `scraper/backup/`으로 이동
- **새 스크래퍼 생성 금지**: `full_scraper.py` 수정/확장으로 해결
- **예외**: 완전히 다른 사이트 구조인 경우만 별도 스크래퍼 허용

### 🚨 스크래핑 핵심 규칙 (CRITICAL)
**Pool과 DE는 항상 함께 수집해야 함**
- 대회 데이터는 Pool 결과 + DE 대진표 + 최종 순위가 하나의 세트
- Pool만 따로 수집하거나 DE만 따로 수집하는 것은 불완전한 데이터
- 종목이 끝나면 최종 순위까지 반드시 수집

**데이터 완성도 체크**
```
✅ 완전한 종목 데이터:
- pool_rounds: 풀 라운드별 경기 결과
- pool_total_ranking: 풀 종합 순위 (진출자/탈락자)
- de_bracket: DE 대진표 (16강, 8강, 4강, 결승) + full_bouts
- final_rankings: 최종 순위

❌ 불완전한 데이터:
- pool만 있고 de_bracket 없음
- final_rankings 없음
- de_bracket은 있지만 full_bouts 없음
```

### full_scraper.py (메인 스크래퍼)
- JavaScript 렌더링이 필요한 사이트용 Playwright 기반 스크래퍼
- 페이지 네비게이션: 클릭 방식 (URL 직접 접근 불가)
- Pool + DE + 최종순위 통합 수집

### Usage
```bash
# 전체 스크래핑
python scraper/full_scraper.py

# 연도 범위 지정
python scraper/full_scraper.py --start-year 2023 --end-year 2025

# 특정 대회만
python scraper/full_scraper.py --competition-id 123
```

## Server Configuration
```
내부 포트: 71 (Internal Port - DO NOT CHANGE!)
개발 서버: python -m uvicorn app.server:app --host 0.0.0.0 --port 71
ARM64 서버: arch -arm64 python3 -m uvicorn app.server:app --host 0.0.0.0 --port 71
```

## Environment Variables
```
SUPABASE_URL=https://tjfjuasvjzjawyckengv.supabase.co
SUPABASE_KEY=<anon_key>
SCRAPE_DELAY=1.0
MAX_CONCURRENT_REQUESTS=3
```

## Next Steps
1. [x] ~~JSON 데이터를 Supabase에 업로드~~ (완료 - 2025-12-22)
2. [ ] 서버 코드를 Supabase 전용으로 수정 (JSON 로드 로직 제거)
3. [ ] 클럽 관리 기능 완성 (로스터, 출석, 비용)
4. [ ] 카카오 로그인 연동

## Fencing Terminology (용어 체계)

### 계층 구조 (Hierarchy)
```
Tournament (대회) > Event (종목) > Bout (경기)
```

| 용어 | 의미 | 적용 포인트 |
|------|------|------------|
| Tournament | 대회 전체 (예: 회장배) | 데이터 최상위 |
| Event | 세부 종목 (예: 남자 플뢰레) | 랭킹 산정 기준 |
| Bout | 1:1 대결 | 승률 분석 최소 단위 |
| Match | Bout과 혼용 또는 단체전 | UI 친화적 표기 |

### 경기 유형 (Bout Type) - 핵심 분석 구분
| 유형 | 영문 | 한국어 | 형식 | 분석 특성 |
|------|------|--------|------|----------|
| Pool | Pool | 예선 | 5점, 3분 | 순발력 데이터 |
| DE | Direct Elimination | 본선 | 15점, 3분×3회전 | 지구력/운영 데이터 |

### 표준 용어 매핑
- **엘리미나시옹디렉트** → `de` (코드) / "Direct Elimination" (UI)
- **예선, 풀, 뿔** → `pool` (코드) / "Pool" (UI)
- **32강, 16강, 8강** → `t32`, `t16`, `t8` (코드)

### 용어 사용 가이드
- **내부/개발**: `bout`, `pool`, `de` (명확한 구분)
- **UI/유저**: "Match", "경기", "예선", "본선" (친화적 표현)
- **DB 컬럼**: `bout_type`, `round_type`, `round_name`

### 관련 파일
- `app/terminology.py` - 용어 매핑 시스템

## ID System (ID 체계)

### 선수 ID (Player ID)
- 형식: `{Country}P{Number}` (예: KOP00001)
- 특별 ID: `KOP00000` = 박소윤(최병철펜싱클럽) - 시스템 기준점

### 조직 ID (Organization ID)
- 형식: `{Country}{Type}{Number}`
- 클럽: KOC0001, 중학교: KOM0001, 고등학교: KOH0001, 대학교: KOV0001, 실업팀: KOA0001

### 국가 코드 (2글자 ISO)
- KO (한국), JP (일본), CN (중국), TW (대만), HK (홍콩), SG (싱가포르)

## Club Management SaaS (클럽 관리 시스템)

### 개요
펜싱 클럽/학교 회원 관리 SaaS - 파일럿: 최병철펜싱클럽 (organization_id: 401)

### 핵심 가치
**우리 데이터 활용이 핵심** - 코치가 자신의 선수들의 대회 성적, 랭킹, 상대 전적을 모두 활용

### API 구조
```
/api/club/
├── /dashboard          대시보드
├── /check-in           출석 체크인 (학생용)
├── /check-in/status    체크인 상태
├── /members            회원 관리
└── /players/           선수 데이터 연동 (핵심!)
    ├── /search         선수 검색
    ├── /link           회원-선수 연결
    ├── /{id}/profile   프로필
    ├── /{id}/competitions  대회 히스토리
    ├── /{id}/stats     성과 지표
    ├── /{id}/head-to-head  상대 전적
    └── /team/roster    팀 로스터
```

### DB 테이블 (Migration 004)
- `club_settings` - 클럽 설정 (자동 체크인 IP, 비용 기본값)
- `attendance` - 출석 기록
- `lessons` - 레슨 일정
- `lesson_participants` - 레슨 참가자
- `fees` - 비용 관리
- `competition_entries` - 대회 참가 관리
- `competition_participants` - 대회 참가자
- `members` 확장: club_role, member_status, enrollment_date

### 역할 (ClubRole)
- `owner` - 클럽 대표
- `head_coach` - 수석 코치
- `coach` - 코치
- `assistant` - 보조 코치
- `student` - 수강생
- `parent` - 학부모
- `staff` - 스태프

### Phase 2 개발 예정

#### 0. 카카오 로그인 연동 (핵심 - 학생 구분 필수)
**문제**: 같은 클럽 IP에서 접속하는 학생들을 구분할 수 없음
**해결**: 카카오 로그인으로 학생 신원 확인

**구현 계획**:
```
1. 카카오 개발자 앱 등록
   - 앱 키 발급 (REST API Key, JavaScript Key)
   - Redirect URI 설정: /auth/kakao/callback

2. 로그인 플로우
   학생 → 카카오 로그인 → 카카오 계정 연동 → 회원 자동 매칭

3. 회원-카카오 계정 연동
   - members 테이블에 kakao_id 컬럼 추가
   - 최초 로그인 시 전화번호/이름으로 회원 자동 매칭
   - 매칭 실패 시 코치가 수동 연결

4. 체크인 플로우 (완성형)
   ┌─────────────────────────────────────────┐
   │ 박소윤 스마트폰                          │
   │ ┌─────────────────────────────────────┐ │
   │ │ 1. 카카오 로그인 (박소윤 계정)       │ │
   │ │ 2. /club/checkin 접속               │ │
   │ │ 3. IP 확인 → 클럽 내 ✅             │ │
   │ │ 4. "체크인" 버튼 탭                  │ │
   │ │ 5. 박소윤 출석 기록 완료 ✅          │ │
   │ └─────────────────────────────────────┘ │
   └─────────────────────────────────────────┘
```

**필요 API**:
- `POST /auth/kakao` - 카카오 로그인 시작
- `GET /auth/kakao/callback` - 카카오 콜백 처리
- `POST /api/club/members/{id}/link-kakao` - 회원-카카오 연결

**DB 변경**:
```sql
ALTER TABLE members ADD COLUMN kakao_id VARCHAR(50);
ALTER TABLE members ADD COLUMN kakao_nickname VARCHAR(100);
ALTER TABLE members ADD COLUMN kakao_profile_image TEXT;
CREATE UNIQUE INDEX idx_members_kakao_id ON members(kakao_id) WHERE kakao_id IS NOT NULL;
```

#### 1. 수업 전 알림 시스템
- 수업 시작 **5분 전** 미체크인 선수 자동 감지
- 코치에게 **웹 알림 + 카카오톡** 발송
- 수업별 출결 현황 실시간 대시보드

#### 2. 미체크인 선수/학부모 알림
- 미체크인 선수에게 **카카오톡 알림** 발송
- 보호자(학부모)에게도 동시 알림
- "자녀 [이름]이 아직 체크인하지 않았습니다" 메시지

#### 3. IP 인식 실패 대응 (Fallback Check-in)
**문제**: 클럽 IP 범위 밖에서 접속 시 자동 체크인 불가
**해결 방안**:
- **코치 대리 체크인**: 코치가 직접 선수 체크인 (checkin_method='coach')
- **위치 인증 체크인**: GPS 기반 geofence 내에서만 수동 체크인 허용
- **QR 코드 체크인**: 클럽 현장에 QR 코드 비치, 스캔 시 체크인 (위치+시간 검증)
- **블루투스 비콘**: 클럽 내 BLE 비콘 설치, 근접 시에만 체크인 가능

#### 4. 가짜 체크인 방지 전략
| 방식 | 설명 | 우회 난이도 |
|------|------|------------|
| IP 검증 | 클럽 공인 IP 확인 | 중 (VPN 가능) |
| GPS Geofence | 반경 100m 내 위치 | 중 (위치 조작 앱) |
| QR 동적 코드 | 5분마다 변경되는 QR | 상 |
| BLE 비콘 | 물리적 근접 필요 | 최상 |
| 복합 인증 | IP + GPS + 시간 조합 | 최상 |

**권장**: Phase 2에서 **QR 동적 코드 + GPS** 조합 구현

#### 5. 카카오톡 알림 연동
- **카카오 알림톡 API** 사용 (비즈니스 채널 필요)
- 템플릿 메시지:
  - 미체크인 알림: "안녕하세요, [클럽명]입니다. [이름]님의 [시간] 수업 출석이 확인되지 않았습니다."
  - 체크인 완료: "[이름]님이 [시간]에 체크인했습니다."

### 관련 파일
```
app/club/
├── router.py           # 메인 라우터
├── models.py           # Pydantic 모델
├── dependencies.py     # 인증/권한
└── players/
    ├── router.py       # 선수 데이터 API
    └── service.py      # 비즈니스 로직

templates/club/
├── dashboard.html      # 코치용 대시보드
└── checkin.html        # 학생용 체크인
```

## Important Notes
- 2019년 이전 데이터는 디지털 형태로 존재하지 않음 (스크래핑 대상 아님)
- 사이트 구조상 페이지 네비게이션은 클릭으로만 가능 (JavaScript 상태 의존)
