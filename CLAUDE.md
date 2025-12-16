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
- 테이블: competitions, events, players, matches, rankings, scrape_logs

## Architecture

### Components
```
FencingCommunityDropShipping/
├── app/
│   ├── server.py          # FastAPI 웹 서버 (포트 71/7171)
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

## Important Notes
- 2019년 이전 데이터는 디지털 형태로 존재하지 않음 (스크래핑 대상 아님)
- 사이트 구조상 페이지 네비게이션은 클릭으로만 가능 (JavaScript 상태 의존)
