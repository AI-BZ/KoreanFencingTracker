# club.fencingmind.ai - 클럽 관리 SaaS

**서브도메인:** club.fencingmind.ai
**포트:** 72 (코드 기본값, `CLUB_PORT`로 오버라이드 — 운영 인스턴스는 9072)
**파일럿:** 최병철펜싱클럽 (org_id: 401)
**상태:** 🔨 개발 중

---

## 서비스 개요
- **선수용**: 경기 기록 관리, 성장 추적 대시보드
- **코치용**: 선수 관리, 훈련 계획, 경기 분석
- **클럽용**: 회원 관리, 일정 관리, 결제 시스템
- **학부모용**: 자녀 성장 모니터링, 대회 일정

## 수익 모델
- Free Plan: 기본 기능 무료
- Pro Plan: $9.99/월 (선수/학부모)
- Coach Plan: $29.99/월 (코치)
- Club Plan: $99~299/월 (클럽 규모별)

---

## 폴더 구조
```
services/club/
├── app/
│   ├── server.py       # FastAPI 메인
│   ├── config.py       # 설정
│   ├── database.py     # shared_core.db 래퍼
│   ├── pages.py        # 페이지 라우트
│   ├── middleware.py   # 언어/테마 미들웨어
│   ├── errors.py       # 에러 핸들러
│   ├── scheduler.py    # 백그라운드 스케줄러
│   ├── auth/           # 인증 (account 서비스 연동 shim)
│   ├── club/           # 클럽 관리
│   │   ├── router.py
│   │   ├── models.py
│   │   ├── dependencies.py  # shared_core.auth 래퍼
│   │   └── players/
│   ├── announcements/  # 공지사항
│   ├── billing/        # 결제
│   ├── checkin/        # 출석 체크인
│   ├── competitions/   # 대회 참가
│   ├── i18n/           # 다국어
│   ├── lessons/        # 레슨
│   ├── notifications/  # 알림
│   ├── schedule/       # 일정
│   ├── settings/       # 설정
│   ├── sync/           # 동기화
│   └── videos/         # 영상
├── templates/club/
├── static/
└── requirements.txt
packages/shared_core/    # 통합 인증/DB 패키지
```

## 서버 실행
```bash
cd /Users/gyejinpark/Documents/GitHub/FencingMind-club
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/club" \
  python -m uvicorn services.club.app.server:app --host 0.0.0.0 --port 72 --reload
```

---

## DB 테이블 (소유)
**이 서비스가 주인인 테이블:**
- `club_subscriptions` - SaaS 구독
- `club_notifications` - 알림
- `club_notification_templates` - 알림 템플릿
- `club_schedules` - 일정
- `club_announcements` - 공지사항
- `club_settings` - 클럽 설정
- `attendance` - 출석
- `lessons` - 레슨
- `fees` - 비용

**공유 테이블 (참조만):**
- `members` - 회원 (공유)
- `players` - 선수 (공유)
- `organizations` - 조직 (공유)

---

## 인증 연동
- **회원가입/로그인**: account.fencingmind.ai (port 70)에서 처리
- **shared_core 기반**: JWT + Supabase Auth 이중 인증
- **JWT 검증**: `from shared_core.auth.jwt import get_current_member`
- **역할 확인**: `from shared_core.auth.dependencies import require_roles, require_coach, require_admin`
- **로그인 필수 처리**: `from shared_core.auth.jwt import require_auth`
- **회원 관리 API 직접 구현 금지** — account 서비스만 담당
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

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/club/*` 브랜치에서만 수정
- 다른 서비스 코드 수정 금지
- 공유 패키지 수정 시 `feature/shared/*` 브랜치 사용

---

## 🎨 UI 디자인 규칙 (필수)

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

### 대시보드 카드 예시
```html
<div class="fm-card">
    <div class="fm-card-header">
        <h3 class="fm-card-title">오늘 출석 현황</h3>
    </div>
    <div class="fm-card-body">
        <div class="fm-stat">
            <span class="fm-stat-value">12</span>
            <span class="fm-stat-label">출석</span>
        </div>
    </div>
</div>
```

---

## 현재 상태
클럽 관리 기능은 이 서비스(`services/club/`)로 분리 완료.
`services/data/app/club/`은 라우터 등록이 해제된 레거시 코드로, 정리 대상.
