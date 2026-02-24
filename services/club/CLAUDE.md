# FencingMind Club Service

**포트:** 72
**파일럿:** 최병철펜싱클럽 (org_id: 401)

## 서버 실행

```bash
cd /Users/gyejinpark/Documents/GitHub/FencingMind-club
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/club" python -m uvicorn services.club.app.server:app --host 0.0.0.0 --port 72 --reload
```

## 구조

```
services/club/
├── app/
│   ├── server.py       # FastAPI 메인
│   ├── config.py       # 설정
│   ├── database.py     # shared_core.db 래퍼
│   ├── club/           # 클럽 관리
│   │   ├── router.py
│   │   ├── models.py
│   │   ├── dependencies.py  # shared_core.auth 래퍼
│   │   └── players/
│   └── auth/           # 인증 (Phase 2)
├── templates/club/
├── static/
└── requirements.txt
packages/shared_core/    # 통합 인증/DB 패키지
```

## 인증 체계
- **shared_core 기반**: JWT + Supabase Auth 이중 인증
- **JWT 토큰**: account 서비스(포트 70)에서 발급
- **테스트 모드**: `CLUB_TEST_MODE=1` 또는 `?test=1`

## 환경 변수
```
SUPABASE_URL=
SUPABASE_KEY=
CLUB_PORT=72
DEFAULT_ORG_ID=401
JWT_SECRET_KEY=your-jwt-secret-key
KAKAO_CLIENT_ID=
```
