# Korean Fencing Tracker - Project Context

## Project Overview
대한펜싱협회(fencing.sports.or.kr) 대회 결과 데이터를 수집하여 웹사이트로 제공하는 프로젝트

## Current Status (2025-12-15)

### Scraping Status
| 연도 | 상태 | 비고 |
|------|------|------|
| 2019~2025 | ✅ 완료 | 디지털 데이터 존재 |
| 2018 이전 | ❌ 불필요 | 텍스트 공지 형태만 (디지털 결과 없음) |

### Data Files
```
data/
├── fencing_data.json        # 메인 데이터 (2020-2025, 107개 대회, 2483개 종목)
├── fencing_data_108_236.json  # 추가 데이터 (2019-2020, 23개 대회, 326개 종목)
└── fencing_data_full.json   # 전체 통합 (236개 대회, 2809개 종목)
```

### Database Status
- **Supabase**: 설정 완료, **데이터 업로드 아직 안함**
- 테이블: competitions, events, players, matches, rankings, scrape_logs, organizations

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

### playwright_scraper.py
- JavaScript 렌더링이 필요한 사이트용 Playwright 기반 스크래퍼
- 페이지 네비게이션: 클릭 방식 (URL 직접 접근 불가)
- 종목 코드: SELECT 드롭다운에서 COMPS 접두사로 추출

### Usage
```bash
# 전체 스크래핑
python scraper/playwright_scraper.py

# 연도 범위 지정
python scraper/playwright_scraper.py --start-year 2023 --end-year 2025

# 종목만 수집 (경기 결과 제외, 빠름)
python scraper/playwright_scraper.py --events-only
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
1. [ ] JSON 데이터를 Supabase에 업로드
2. [ ] 웹 서버 테스트 및 배포
3. [ ] 자동 업데이트 스케줄러 활성화

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

## Important Notes
- 2019년 이전 데이터는 디지털 형태로 존재하지 않음 (스크래핑 대상 아님)
- 사이트 구조상 페이지 네비게이션은 클릭으로만 가능 (JavaScript 상태 의존)
