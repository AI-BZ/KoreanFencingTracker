# 대한펜싱협회 경기결과 스크래퍼

대한펜싱협회(fencing.sports.or.kr) 웹사이트에서 경기결과를 수집하여 Supabase DB에 저장하는 스크래퍼입니다.

## 기능

- 대회 목록 및 상세정보 수집
- 종목별 경기 결과 수집
- 참가 선수 정보 수집
- 최종 순위 수집
- 자동 스케줄링 (매일 전체 동기화, 매시간 증분 업데이트)
- 앱 API 역분석 도구

## 설치

```bash
# 가상환경 생성
python -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate  # Windows

# 의존성 설치
pip install -r requirements.txt
```

## 환경 설정

1. `.env.example`을 `.env`로 복사
2. Supabase 정보 입력

```bash
cp .env.example .env
```

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
```

## Supabase 설정

1. [supabase.com](https://supabase.com)에서 프로젝트 생성
2. SQL Editor에서 `database/schemas.sql` 실행
3. Project Settings > API에서 URL과 anon key 복사

## 사용법

### 전체 동기화
```bash
python main.py --mode sync
```

### 진행중 대회 업데이트
```bash
python main.py --mode update
```

### 통계 조회
```bash
python main.py --mode stats
```

### 스케줄러 모드 (백그라운드 실행)
```bash
python main.py --mode scheduler
```

## 앱 API 역분석

```bash
# mitmproxy 실행
mitmdump -s tools/app_api_analyzer.py -p 8080

# Android 기기/에뮬레이터에서 프록시 설정 후 앱 실행
# 결과는 captured_apis/ 폴더에 저장
```

## 프로젝트 구조

```
FencingCommunityDropShipping/
├── scraper/                 # 스크래퍼 모듈
│   ├── __init__.py
│   ├── config.py            # 설정
│   ├── client.py            # HTTP 클라이언트
│   ├── models.py            # 데이터 모델
│   └── parsers/             # 파서
│       ├── competition.py
│       ├── event.py
│       ├── match.py
│       └── player.py
├── database/                # 데이터베이스 모듈
│   ├── __init__.py
│   ├── supabase_client.py   # Supabase 클라이언트
│   └── schemas.sql          # DB 스키마
├── scheduler/               # 스케줄러 모듈
│   ├── __init__.py
│   └── scheduler.py
├── tools/                   # 도구
│   └── app_api_analyzer.py  # 앱 API 분석
├── logs/                    # 로그 파일
├── main.py                  # 메인 실행 파일
├── requirements.txt
├── .env.example
└── README.md
```

## 수집 데이터

### competitions (대회)
- 대회 ID, 명칭, 기간, 장소, 상태

### events (종목)
- 무기 (플뢰레/에페/사브르)
- 성별 (남자/여자/혼성)
- 카테고리 (개인/단체)
- 연령대 (시니어/주니어/카뎃 등)

### players (선수)
- 선수명, 소속팀, 출생년도

### matches (경기 결과)
- 라운드, 대전 선수, 점수, 승자

### rankings (순위)
- 최종 순위, 경기수, 승패 기록

## API 엔드포인트 (발견된)

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| /game/compList | GET | 대회 목록 |
| /game/compListView | GET | 대회 상세 |
| /game/subEventListCnt | POST | 종목 목록 |
| /game/getTableauGrpDtlList | POST | 토너먼트 구조 |
| /game/getMatchDtlInfoList | POST | 경기 결과 |
| /game/enterPlayerJsonSelectList | POST | 참가 선수 |
| /game/finishRank | POST | 최종 순위 |

## 법적 고려사항

- 공개된 경기 결과 데이터를 수집합니다
- 서버 부하 최소화를 위해 요청 간 딜레이를 적용합니다
- 상업적 이용 시 대한펜싱협회에 문의하세요: (02) 420-4289

## License

MIT
