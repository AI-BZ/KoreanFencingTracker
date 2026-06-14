# app.fencingmind.ai - PWA/알림 허브 서비스

**서브도메인:** app.fencingmind.ai
**포트:** 77
**워크트리:** `/Users/gyejinpark/Documents/GitHub/FencingMind-app`
**브랜치:** `feature/app/pwa-base`
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

## 폴더 구조 (현재)
```
services/app/
├── CLAUDE.md                          # 이 파일
├── app/
│   ├── server.py                      # FastAPI 앱 (port 77)
│   │                                  #   GET / → home.html
│   │                                  #   GET /service-worker.js → SW (root scope)
│   │                                  #   GET /offline.html → 오프라인 폴백
│   │                                  #   GET /health → 헬스체크
│   ├── config.py                      # AppSettings (FCM, 카카오, 폴링 설정)
│   ├── auth/
│   │   └── router.py                  # Auth shim → account 서비스 리다이렉트
│   └── notifications/                 # Phase 2: 알림 설정/구독
│       ├── service.py                 # Supabase CRUD (prefs, push subscriptions)
│       └── router.py                  # 설정 페이지 + prefs/subscribe API
├── templates/
│   ├── base.html                      # 공통 레이아웃 (navbar, footer, i18n, SW 등록)
│   ├── home.html                      # 메인 페이지 (기능 소개, PWA 설치 프롬프트)
│   └── notifications/
│       └── settings.html              # 알림 설정 UI (카테고리×채널 토글)
├── static/
│   ├── manifest.json                  # PWA manifest (아이콘, 테마색, standalone)
│   ├── service-worker.js              # SW (캐시 전략, 푸시 수신, 오프라인 폴백)
│   ├── offline.html                   # 오프라인 폴백 페이지
│   ├── js/
│   │   ├── push.js                    # Phase 4: 웹 푸시 구독/해제
│   │   └── install.js                 # Phase 5: iOS 설치 안내 배너 + beforeinstallprompt 중앙화
│   └── images/
│       ├── icons/
│       │   ├── icon-192.png           # PWA 아이콘 192x192
│       │   └── icon-512.png           # PWA 아이콘 512x512
│       └── logo/
│           ├── FencingMind_logo_long.png        # Light 테마
│           └── FencingMind_logo_long_white.png   # Dark 테마
└── tests/
```

## 서버 실행
```bash
cd /Users/gyejinpark/Documents/GitHub/FencingMind-app
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/app" \
  python -m uvicorn services.app.app.server:app --host 0.0.0.0 --port 77
```

---

## DB 테이블 (소유) — Migration 021

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

## 구현 로드맵

| Phase | 브랜치 | 내용 | 외부 의존성 | 상태 |
|-------|--------|------|------------|------|
| 1 | `feature/app/init` | 스캐폴드 + auth shim | 없음 | ✅ 완료 |
| 1.5 | `feature/app/pwa-base` | manifest + SW + offline + base.html + home.html | 없음 | ✅ 완료 |
| 2 | `feature/app/notifications` | 알림 구독 UI + 설정 페이지 | 없음 | ✅ 완료 |
| 3 | `feature/app/pipeline` | EventPoller + NotificationDispatcher | 없음 | ✅ 완료 |
| **4** | **`feature/app/fcm`** | **FCM 웹 푸시 발송 + 권한요청(클릭 제스처 내) + iOS 16.4+ 감지** | **Firebase 프로젝트 (VAPID 키), pywebpush** | **🔨 코드 완료 / 키·패키지 대기** |
| **5** | **`feature/app/pwa-install`** | **설치 프롬프트 최적화 + iOS Safari "홈 화면에 추가" 안내 배너** | **없음** | **✅ 완료** |
| **6** | **`feature/app/kakao-alimtalk`** | **카카오 알림톡 발송 (프로바이더 비종속 sender, Solapi 레퍼런스)** | **카카오 비즈니스 채널 + 템플릿 승인 + 발송 대행사 계정** | **🔨 코드 완료 / 외부 승인·계정 대기** |
| 7 | `feature/app/offline` | 오프라인 지원 강화 | 없음 | 📋 |

---

## 🍎 iOS PWA 제약 & 대응 (필수 체크리스트)

iOS는 Android와 달리 PWA 푸시에 강한 제약이 있다. 아래 항목을 Phase 4/5에서 반드시 처리한다.
(미처리 시 iOS 사용자는 푸시를 전혀 못 받는다.)

| # | iOS 제약 | 대응 | 처리 Phase | 현재 |
|---|----------|------|-----------|------|
| 1 | "홈 화면에 추가" 후 **그 아이콘으로 실행**해야만 알림 권한 요청·수신 가능 | iOS Safari 감지 → 공유→"홈 화면에 추가" **설치 안내 배너** (iOS엔 `beforeinstallprompt` 없음) | **5** | ✅ 구현 (`static/js/install.js` + `base.html` 배너) |
| 2 | 권한 요청은 **사용자 제스처(버튼 클릭) 핸들러 내부**에서만 호출 가능 | `Notification.requestPermission()`을 `#push-toggle-btn` onclick 안에서만 호출 (페이지 로드 시 자동 호출 안 함) | **4** | ✅ 구현 (`static/js/push.js`) |
| 3 | **iOS 16.4+ + standalone 모드**에서만 Web Push 동작 | `push.js`가 iOS 감지 + `display-mode: standalone` 감지 → 미충족 시 버튼 비활성화 + 설치 안내 인라인 메시지. 사이트 전역 설치 안내 배너는 `install.js`(Phase 5) | **4/5** | ✅ 감지·안내 + 전역 배너 구현 |
| 4 | manifest `display: standalone` + 아이콘 + `apple-touch-icon` | 이미 충족 | 1.5 | ✅ 완료 |
| 5 | VAPID 키 + SW `push`/`notificationclick` 핸들러 | SW 핸들러 작성 완료, 프론트/백엔드 발송 코드 완료. **VAPID 키는 사람이 Firebase에서 발급 후 env 설정 필요** | 4 | ⚠️ 키 대기 (코드 완료) |

> **이중 채널 설계 의도**: PWA 푸시(iOS는 설치 필요) + 카카오 알림톡(설치 불필요)으로
> iOS 제약을 보완. 미설치 사용자에게는 알림톡이 백업 도달 경로.

---

## Phase 2 상세: 알림 구독 UI + 설정 (다음 작업)

### 목표
로그인한 회원이 알림 카테고리별로 on/off 설정하고, 푸시 구독을 관리하는 UI + API

### 생성할 파일
```
services/app/
├── app/
│   └── notifications/
│       ├── __init__.py
│       ├── router.py          # 알림 설정 API
│       │   GET  /notifications/settings     → 설정 페이지
│       │   GET  /api/notifications/prefs    → 현재 설정 조회
│       │   PATCH /api/notifications/prefs   → 설정 변경
│       │   POST /api/notifications/subscribe   → 푸시 구독 등록
│       │   DELETE /api/notifications/subscribe → 푸시 구독 해제
│       └── service.py         # 비즈니스 로직 (Supabase CRUD)
├── templates/
│   └── notifications/
│       └── settings.html      # 알림 설정 UI
```

### 알림 카테고리 (app_notification_preferences)
| category | 설명 | 기본값 |
|----------|------|--------|
| `competition_result` | 대회 결과 발표 | on |
| `ranking_change` | 랭킹 변동 | on |
| `club_notice` | 클럽 공지사항 | on |
| `attendance_reminder` | 출석 알림 | on |
| `system` | 시스템 공지 | on (해제 불가) |

### 채널별 설정 (channel)
| channel | 설명 | Phase |
|---------|------|-------|
| `web_push` | FCM 웹 푸시 | Phase 4 |
| `kakao_alimtalk` | 카카오 알림톡 | Phase 6 |
| `in_app` | 인앱 알림 (notifications 테이블) | Phase 2 |

### UI 패턴
- account 서비스의 base.html 패턴 그대로 사용 (이미 templates/base.html에 적용됨)
- 카드 형태로 카테고리별 토글 스위치
- 로그인 필수 (미로그인 시 /auth/login 리다이렉트)
- CSS 변수 사용 (하드코딩 금지)

### Supabase 연동 (실제 스키마 — Migration 021)
> ⚠️ `app_notification_preferences`는 **카테고리당 1행**이며 채널은 boolean 컬럼
> (`web_push`, `kakao_alimtalk`, `in_app`)이다. `channel`/`enabled` 컬럼은 없다.
> UNIQUE(member_id, category) → upsert는 `on_conflict="member_id,category"`.
```python
# 설정 조회
supabase.table("app_notification_preferences") \
    .select("category, web_push, kakao_alimtalk, in_app") \
    .eq("member_id", member.id) \
    .execute()

# 설정 변경 (upsert — 채널 전체를 전달)
supabase.table("app_notification_preferences") \
    .upsert({
        "member_id": member.id,
        "category": category,        # competition_result, ranking_change, ...
        "web_push": True,
        "kakao_alimtalk": False,
        "in_app": True,
    }, on_conflict="member_id,category") \
    .execute()
```
> 구현: `app/notifications/service.py` (`get_preferences`, `update_preference`,
> `save_push_subscription`, `remove_push_subscription`).
> `system` 카테고리는 locked → 인앱 알림 해제 불가.
> Migration 021은 프로덕션 Supabase에 적용 완료 (2026-06-14).

### 참고할 기존 코드
- `services/account/app/profile/router.py` — 로그인 필수 페이지 패턴
- `services/data/app/auth/router.py` — auth shim 패턴 (이미 복사됨)
- `packages/shared_core/auth/jwt.py` — `get_current_member()` 사용법
- `packages/shared_core/i18n/` — `create_language_context(request)` 사용법

---

## Phase 3 상세: EventPoller + NotificationDispatcher

### 목표
data 서비스의 `data_events` 테이블을 폴링하여 알림을 생성/디스패치

### 생성할 파일
```
services/app/
├── app/
│   └── pipeline/
│       ├── __init__.py
│       ├── poller.py          # EventPoller (30초 간격, 워터마크 기반)
│       ├── dispatcher.py      # NotificationDispatcher (채널별 분기)
│       └── event_types.py     # 이벤트 타입 정의 (competition_result, ranking_change 등)
```

### 폴링 로직
```python
# 1. 마지막 처리 위치 조회
cursor = supabase.table("app_event_cursor").select("last_event_id").single().execute()

# 2. 새 이벤트 조회
events = supabase.table("data_events") \
    .select("*") \
    .gt("id", cursor.data["last_event_id"]) \
    .order("id") \
    .limit(100) \
    .execute()

# 3. 이벤트별 알림 생성 + 디스패치
for event in events.data:
    targets = determine_targets(event)  # 대상 회원 결정
    for member in targets:
        prefs = get_notification_prefs(member.id, event.category)
        if prefs.in_app:
            create_notification(member.id, event)
        if prefs.web_push:
            send_fcm(member.id, event)  # Phase 4
        if prefs.kakao:
            send_alimtalk(member.id, event)  # Phase 6

# 4. 워터마크 업데이트
supabase.table("app_event_cursor").update({"last_event_id": last_id}).eq(...).execute()
```

### 실행 방식
- FastAPI lifespan event로 백그라운드 태스크 시작
- `asyncio.create_task()`로 30초 간격 폴링 루프
- 서버 종료 시 graceful shutdown

---

## Phase 4 상세: FCM 웹 푸시 (구현 완료)

### 설계 요점
- **표준 Web Push API 사용** — FCM은 내부적으로 표준 웹 푸시 위에서 동작하므로
  Firebase JS SDK 없이 브라우저 `PushManager.subscribe(applicationServerKey=VAPID공개키)`
  + 서버 `pywebpush`로 발송한다.
- VAPID 키 쌍(공개/비밀)은 **Firebase 콘솔에서 발급**한 뒤 환경변수로 주입.
- 키/패키지가 없어도 **graceful degradation** — 폴러가 죽지 않는다.

### 구현 파일
```
services/app/
├── static/js/push.js              # 구독/해제 + iOS 감지 + 권한요청(클릭 핸들러 내)
├── templates/notifications/settings.html
│                                  # <meta name="vapid-public-key"> + #push-toggle-btn 카드
├── app/notifications/router.py    # settings_page 컨텍스트에 vapid_public_key 주입
├── app/pipeline/dispatcher.py     # _send_web_push 실제 발송 (pywebpush 지연 import)
└── requirements.txt               # pywebpush>=1.14.0
```

### 발송 흐름 (`dispatcher._send_web_push`)
1. 멱등성: `app_notification_log(channel='web_push')` 존재 시 재발송 안 함.
2. `FCM_VAPID_PRIVATE_KEY` 비어있음 → `status='pending'`, error `"VAPID key 미설정"` 로그 후 종료.
3. `pywebpush` import 실패 → `status='pending'`, error `"pywebpush 미설치"` 로그 후 종료.
4. 활성 구독(`app_push_subscriptions.is_active=true`) 조회 → 각 구독에 `webpush(...)`.
5. 404/410 응답 → 해당 구독 `is_active=false` (만료 정리).
6. 1건 이상 성공 → `status='sent'`, 전부 실패 → `status='failed'`.
- payload: `{title, body, url, tag}` (제목/본문은 `event_types.build_message` 재사용).
- `vapid_claims={"sub": "mailto:privacy@fencingmind.ai"}`.

### iOS 제약 처리 (`push.js`)
- 권한 요청은 **버튼 클릭 핸들러 안에서만** (`Notification.requestPermission()`).
- iOS && !standalone → 버튼 비활성화 + "먼저 홈 화면에 추가" 안내 (설치 배너는 Phase 5).
- VAPID 공개키 미주입 → 버튼 "푸시 미설정" 비활성화 (graceful).
- 미지원 브라우저(`!('PushManager' in window)`) → 비활성화.

### 🔴 사람이 해야 할 작업 (실제 푸시 동작 활성화)
1. **Firebase 프로젝트 생성** (또는 기존 사용)
   → 콘솔 > 프로젝트 설정 > Cloud Messaging > **Web Push 인증서**에서 **키 쌍 생성**.
   - 공개 키 = `FCM_VAPID_PUBLIC_KEY` (브라우저 applicationServerKey)
   - 비공개 키 = `FCM_VAPID_PRIVATE_KEY` (서버 서명)
   > 참고: pywebpush는 표준 VAPID 키만 있으면 동작한다. Firebase가 아닌
   > `vapid` CLI(`vapid --gen`)나 `py-vapid`로 자체 발급한 키 쌍도 사용 가능.
2. **환경변수 설정** (배포 환경 / 로컬 `.env`):
   ```bash
   export FCM_VAPID_PUBLIC_KEY="<base64url 공개키>"
   export FCM_VAPID_PRIVATE_KEY="<base64url 또는 PEM 비공개키>"
   ```
3. **패키지 설치** (Mac Studio ARM64):
   ```bash
   arch -arm64 python3 -m pip install pywebpush
   # 또는
   arch -arm64 python3 -m pip install -r services/app/requirements.txt
   ```
4. 서버 재시작 → 설정 페이지에서 "푸시 알림 켜기" 클릭 → 권한 허용 → 구독 저장 확인.

> 위 3가지(키 발급/env/패키지)가 갖춰지기 전까지 코드는 안전하게 no-op 동작하며
> `app_notification_log`에 `pending` 상태로 기록된다.

---

## Phase 6 상세: 카카오 알림톡 (코드 완료 / 외부 승인 대기)

### 설계 요점
- **프로바이더 비종속 sender** — `app/pipeline/kakao.py` 의 `KakaoAlimtalkSender`.
  자격증명/템플릿 코드가 하나라도 없으면 실제 HTTP 호출 없이 `not_configured`를
  반환하고, 디스패처는 이를 `app_notification_log`에 `pending`으로 기록한다.
- **레퍼런스 구현 대상: Solapi (구 CoolSMS)** 알림톡 REST API.
  - 인증: API Key + Secret 기반 **HMAC-SHA256 서명** 헤더.
  - 엔드포인트: `POST {base}/messages/v4/send` (단건), `type: "ATA"`(알림톡).
  - `message.kakaoOptions`에 `pfId`(채널 ID) / `templateId`(승인 템플릿) / `variables`.
  - 🔴 **이 구현은 Solapi 공개 문서 계약을 따른 것이며 라이브 API로 검증되지 않았다(untested).**
    운영 전 실제 응답 스키마·서명 규칙을 대행사 문서로 재확인해야 한다.
  - 다른 대행사(NHN Cloud Toast, Bizm, Aligo 등)를 쓰려면 `kakao.py`에 어댑터 함수를
    추가하고 `KAKAO_ALIMTALK_PROVIDER` 값으로 분기하면 된다.
- **알림톡은 kakao_user_id가 아니라 전화번호로 발송**된다(사전 승인 템플릿 경유).
  수신 번호는 `members` 테이블에서 해석: `phone`(+`phone_country_code`) → `contact_phone`.
  번호가 없으면 graceful하게 `pending`(error `"전화번호 없음"`) 기록 후 종료.
- 어떤 경우에도 **폴러를 죽이지 않는다** — sender는 모든 예외를 흡수, 디스패처도 방어.

### 구현 파일
```
services/app/
├── app/pipeline/kakao.py          # KakaoAlimtalkSender + 전화번호 정규화/해석 헬퍼
├── app/pipeline/dispatcher.py     # _send_kakao 실제 와이어업 (멱등성 + 번호해석 + 로그)
├── app/config.py                  # 카카오 알림톡 env 설정 + kakao_template_map
├── requirements.txt               # httpx>=0.24.0 (지연 import)
└── tests/test_dispatcher_kakao.py # 페이크 Supabase 단위 테스트 (pending/멱등성/번호정규화)
```

### 발송 흐름 (`dispatcher._send_kakao`)
1. 멱등성: `app_notification_log(channel='kakao_alimtalk')` 존재 시 재발송 안 함.
2. `members`에서 수신번호 해석 → 없으면 `status='pending'`(error `"전화번호 없음"`) 후 종료.
3. `KakaoAlimtalkSender().send(to_phone, event)` 호출 (제목/본문은 `event_types.build_message` 재사용).
4. 결과 매핑:
   - `sent` → `app_notification_log status='sent'`.
   - `pending` / `not_configured`(자격증명·템플릿 없음, httpx 미설치, 미지원 프로바이더) → `status='pending'`.
   - `failed`(HTTP 오류, 네트워크 오류, 잘못된 번호) → `status='failed'`.

### 환경변수 (모두 비어있으면 안전한 no-op)
| 변수 | 설명 |
|------|------|
| `KAKAO_ALIMTALK_PROVIDER` | 발송 대행사 식별자. 레퍼런스 구현은 `solapi`. |
| `KAKAO_ALIMTALK_API_KEY` | 대행사 API Key |
| `KAKAO_ALIMTALK_API_SECRET` | 대행사 API Secret (HMAC 서명용) |
| `KAKAO_ALIMTALK_BASE_URL` | 대행사 REST 베이스 URL (미지정 시 Solapi 기본값 `https://api.solapi.com`) |
| `KAKAO_ALIMTALK_SENDER_KEY` | 발신 프로필/발신번호 키 (SMS 대체발송용 from) |
| `KAKAO_ALIMTALK_PFID` | 카카오 비즈니스 채널 ID(플러스친구/PFID) |
| `KAKAO_ALIMTALK_TEMPLATE_COMPETITION_RESULT` | 대회 결과 카테고리 승인 템플릿 코드 |
| `KAKAO_ALIMTALK_TEMPLATE_RANKING_CHANGE` | 랭킹 변동 카테고리 승인 템플릿 코드 |

템플릿 변수는 `#{title}` / `#{body}` / `#{url}` 키로 전달된다 → **승인 템플릿 본문도
이 변수명을 사용**해야 한다(또는 `kakao.py`의 `variables` 매핑을 템플릿에 맞게 조정).

### 🔴 사람이 해야 할 작업 (실제 알림톡 발송 활성화)
1. **카카오 비즈니스 채널 개설** (kakao 비즈니스 / 채널 관리자센터)
   → 채널 ID(PFID) 확보 → `KAKAO_ALIMTALK_PFID`.
2. **알림톡 템플릿 등록 및 검수 승인** (카테고리별 1개 이상).
   본문에 `#{title}`, `#{body}`, `#{url}` 변수 포함 → 승인 후 발급된 템플릿 코드를
   `KAKAO_ALIMTALK_TEMPLATE_COMPETITION_RESULT` / `..._RANKING_CHANGE`에 설정.
   ⚠️ 알림톡 템플릿은 광고성 문구 금지 등 검수 기준이 까다로움(승인까지 수일 소요 가능).
3. **발송 대행사 가입** (레퍼런스: **Solapi**). 대행사 콘솔에서 위 카카오 채널/템플릿을
   연동하고 API Key/Secret 발급 → `KAKAO_ALIMTALK_API_KEY/SECRET`, `KAKAO_ALIMTALK_PROVIDER=solapi`.
   발신번호 등록 → `KAKAO_ALIMTALK_SENDER_KEY`.
4. **패키지 설치** (보통 supabase 의존성으로 이미 설치됨):
   ```bash
   arch -arm64 python3 -m pip install -r services/app/requirements.txt
   ```
5. 서버 재시작 → 알림톡 채널 on인 회원에게 이벤트 발생 시 발송.
   (라이브 API 응답으로 서명/엔드포인트/응답 스키마 1차 검증 필수 — untested 상태이므로.)

> 위 4가지(채널/템플릿/대행사 계정·키)가 갖춰지기 전까지 코드는 안전하게 no-op로
> 동작하며 `app_notification_log`에 `pending` 상태로 기록된다.

---

## 공통 규칙

### Import 패턴
```python
# 인증
from shared_core.auth.jwt import get_current_member
from shared_core.auth.dependencies import require_member

# i18n
from shared_core.i18n import LanguageMiddleware, create_language_context

# DB
from shared_core.db.client import get_supabase_client

# 타입
from shared_core.types.member import MemberResponse
```

### 템플릿 컨텍스트
```python
from shared_core.i18n import create_language_context

@router.get("/some-page")
async def some_page(request: Request):
    return templates.TemplateResponse("some.html", {
        "request": request,
        **create_language_context(request),
    })
```

### CSS 규칙
- CSS 변수 사용 필수 (`var(--bg-primary)` 등), 하드코딩 금지
- 테마: 언어 기반 자동 결정 (수동 토글 없음)
- base.html의 CSS 변수가 account 서비스와 동일

### Git 브랜치 규칙
- 이 서비스 코드는 `feature/app/*` 브랜치에서만 수정
- 다른 서비스(`services/data/`, `services/account/` 등) 코드 수정 금지
- 공유 패키지(`packages/shared_core/` 등) 수정 시 `feature/shared/*` 브랜치 사용
- 수정 가능 범위: `services/app/` 내부만

### 외부 의존성 (향후 필요)
| 의존성 | 필요 시점 | 비고 |
|--------|----------|------|
| Firebase 프로젝트 (FCM) | Phase 4 | VAPID 키 발급 |
| 카카오 비즈니스 채널 + 템플릿 승인 + 발송 대행사(Solapi 등) 계정 | Phase 6 | 코드는 완료, 외부 승인·계정 대기 |
| `httpx` 패키지 | Phase 6 | 보통 supabase 의존성으로 이미 설치됨 |
| Cloudflare DNS CNAME | 배포 시 | `app.fencingmind.ai` |
| Cloudflare Tunnel 업데이트 | 배포 시 | app 서비스 라우팅 추가 |
| `pywebpush` 패키지 | Phase 4 | `arch -arm64 python3 -m pip install pywebpush` |
