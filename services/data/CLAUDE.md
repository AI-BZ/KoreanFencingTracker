# data.fencingmind.ai - 펜싱 데이터 서비스

**서브도메인:** data.fencingmind.ai
**포트:** 71
**상태:** ✅ 운영 중 (메인 서비스)

---

## 서비스 개요
- 전 세계 펜싱 대회 결과 데이터베이스
- 선수 프로필 및 랭킹 시스템
- 클럽/코치 디렉토리
- API 제공 (B2B 데이터 판매)

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
cd services/data
python -m uvicorn app.server:app --host 0.0.0.0 --port 71
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

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/data/*` 브랜치에서만 수정
- 다른 서비스 코드 수정 금지
- 공유 패키지 수정 시 `feature/shared/*` 브랜치 사용
