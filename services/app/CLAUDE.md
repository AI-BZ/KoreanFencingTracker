# app.fencingmind.ai - PWA/알림 허브 서비스

**서브도메인:** app.fencingmind.ai
**포트:** 77
**상태:** 🔨 개발 중

---

## 서비스 개요
- **PWA 앱 + 알림 허브** - FCM 웹 푸시 + 카카오 알림톡 통합
- data 서비스의 이벤트(대회 결과, 랭킹 변동)를 폴링하여 사용자에게 알림 발송
- PWA manifest + service worker 호스팅 (data 서비스의 캐시 문제 방지)
- 직접 수익 없음 (인프라 서비스)

## 아키텍처: 알림 흐름 (data -> app -> 사용자)
```
Data Service                    App Service                   User
    |                               |                           |
    |-- EventPublisher.publish() -->|                           |
    |   (data_events 테이블 기록)     |                           |
    |                    EventPoller (30초 간격 폴링)              |
    |                               |                           |
    |                    _process_event():                       |
    |                      1. 대상 회원 결정                       |
    |                      2. 알림 설정 확인                       |
    |                      3. notifications 행 삽입               |
    |                      4. FCM 웹 푸시 발송 ---------> 브라우저 푸시
    |                      5. 카카오 알림톡 발송 --------> 카카오톡
    |                      6. app_notification_log 기록           |
```

## 서비스 간 통신: Supabase 테이블 폴링
- data 서비스는 기존 `EventPublisher`로 `data_events` 테이블에 기록 (변경 없음)
- app 서비스가 `app_event_cursor`의 워터마크 기반으로 30초마다 폴링
- 서비스 간 직접 HTTP 호출 없음 -> 결합도 최소, 내결함성 보장

## PWA 캐시 전략 (이전 data 서비스 문제 방지)
- **API/HTML**: network-first (캐시 부실 방지)
- **static/**: cache-first (CACHE_NAME 버전으로 배포시 버스트)
- **외부 CDN**: 캐시 안 함

---

## 폴더 구조
```
services/app/
├── app/
│   ├── server.py          # FastAPI 앱 (port 77), health check
│   ├── config.py          # AppSettings
│   └── auth/
│       └── router.py      # Auth shim (data 서비스 패턴 복사)
├── templates/             # Jinja2 템플릿
├── static/
│   └── images/logo/       # 로고 (account과 동일)
└── tests/
```

## 서버 실행
```bash
cd /path/to/project/root
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/app" \
  python -m uvicorn services.app.app.server:app --host 0.0.0.0 --port 77
```

---

## DB 테이블 (소유)
**이 서비스가 주인인 테이블:**
- `app_push_subscriptions` - FCM 토큰 + 카카오 사용자 ID 저장
- `app_notification_preferences` - 카테고리별 채널 opt-in/opt-out
- `app_notification_log` - 발송 이력 (채널별 상태 추적)
- `app_event_cursor` - data_events 폴링 워터마크

**공유 테이블 (참조/쓰기):**
- `notifications` - 사이트 내 알림 (삽입)
- `members` - 회원 (참조)

**공유 테이블 (읽기 전용):**
- `data_events` - 데이터 파이프라인 이벤트 (폴링)

---

## 구현 순서 (각 단계별 별도 브랜치)
1. `feature/app/init` - 스캐폴드 + 카카오 로그인 (auth shim) -- 현재
2. `feature/app/notifications` - 알림 구독 UI + 설정
3. `feature/app/pipeline` - data<->app 이벤트 폴러 + NotificationDispatcher
4. `feature/app/fcm` - FCM 웹 푸시
5. `feature/app/pwa` - manifest.json + service worker
6. `feature/app/kakao-alimtalk` - 카카오 알림톡 (비즈니스 채널 필요)
7. `feature/app/offline` - 오프라인 지원

---

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/app/*` 브랜치에서만 수정
- 다른 서비스 코드 수정 금지
- 공유 패키지 수정 시 `feature/shared/*` 브랜치 사용
