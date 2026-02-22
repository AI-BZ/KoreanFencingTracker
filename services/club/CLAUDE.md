# FencingMind Club Service

**포트:** 75
**파일럿:** 최병철펜싱클럽 (org_id: 401)

## 서버 실행

```bash
cd /Users/gyejinpark/Documents/GitHub/FencingMind-club
PYTHONPATH="${PWD}/services/club" python -m uvicorn services.club.app.server:app --host 0.0.0.0 --port 75 --reload
```

## 구조

```
services/club/
├── app/
│   ├── server.py       # FastAPI 메인
│   ├── config.py       # 설정
│   ├── club/           # 클럽 관리 (TODO: 마이그레이션)
│   └── auth/           # 인증 (Phase 2)
├── templates/club/
├── static/
└── requirements.txt
```

## Phase 1 (마이그레이션 예정)
- 회원 관리 (roles: owner, coach, student, parent)
- 출석 체크인 (IP 기반 자동 + 수동)
- 레슨 관리
- 비용 관리
- 선수 분석 (대회 성적, 상대 전적)

## Phase 2 (계획)
- 카카오 로그인
- 알림 (카카오톡)
- 클럽 공개 페이지
- 레슨 예약 & 결제

## 환경 변수
```
SUPABASE_URL=
SUPABASE_KEY=
CLUB_PORT=75
DEFAULT_ORG_ID=401
```
