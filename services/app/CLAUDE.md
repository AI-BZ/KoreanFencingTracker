# app.fencingmind.ai - SaaS 플랫폼

**서브도메인:** app.fencingmind.ai
**포트:** 72
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
services/app/
├── api/                 # FastAPI API
├── club/                # 클럽 관리
│   ├── dashboard/       # 코치용 대시보드
│   ├── checkin/         # 출석 체크인
│   ├── members/         # 회원 관리
│   └── payments/        # 결제
├── player/              # 선수용 기능
├── parent/              # 학부모용 기능
├── templates/           # 템플릿
├── static/              # 정적 파일
└── tests/               # 테스트
```

## 서버 실행
```bash
cd services/app
python -m uvicorn api.server:app --host 0.0.0.0 --port 72
```

---

## DB 테이블 (소유)
**이 서비스가 주인인 테이블:**
- `app_subscriptions` - SaaS 구독
- `app_notifications` - 알림
- `app_notification_templates` - 알림 템플릿
- `app_schedules` - 일정
- `app_announcements` - 공지사항

**현재 services/data/app/club/에 있는 테이블 (마이그레이션 예정):**
- `club_settings` → `app_club_settings`
- `attendance` → `app_attendance`
- `lessons` → `app_lessons`
- `fees` → `app_fees`

**공유 테이블 (참조만):**
- `members` - 회원 (공유)
- `players` - 선수 (공유)
- `organizations` - 조직 (공유)

---

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/app/*` 브랜치에서만 수정
- 다른 서비스 코드 수정 금지
- 공유 패키지 수정 시 `feature/shared/*` 브랜치 사용

---

## 현재 상태
⚠️ 현재 클럽 관리 기능은 `services/data/app/club/`에 있음
Phase 2에서 이 폴더로 분리 예정
