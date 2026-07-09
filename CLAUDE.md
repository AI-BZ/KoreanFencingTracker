# FencingMind - Project Context

**회사명:** FencingMind LLC
**도메인:** FencingMind.ai
**비전:** 세계 최초의 펜싱 전문 AI 데이터 플랫폼, 펜싱의 모든 정보를 연결하는 글로벌 허브

---

## 🧭 세션 핸드오프 (재시작 후 컨텍스트) — 기록: 2026-07-09

> Claude Code를 껏다 켜도 이어서 작업할 수 있도록 남기는 현재 상태 스냅샷.
> 최신 상태는 항상 `git status` / `git diff` 로 재확인할 것. 작업 완료·커밋 후에는 이 섹션을 갱신하거나 삭제.

### 현재 위치
- **워크트리:** `fencingmind` (메인) · **브랜치:** `feature/account/init`
- **작업 서비스:** `services/account/` (회원가입 폼 개선 진행 중), 일부 `packages/shared_core/`

### 미커밋 작업 요약 (아직 커밋 안 됨)
| 파일 | 변경 내용 |
|------|----------|
| `services/account/app/auth/router.py` | ① 공개 선수/자녀 검색(`/auth/public/player-search`, `/child-search`)에 **무기(weapon)·리그(league) 필터** 추가. players 테이블에 무기/연령이 없어 `rankings → events` 조인으로 유도. `LEAGUE_AGE_GROUPS` 로 불규칙한 `events.age_group` 값을 elementary/middle/high/university/senior 5개 리그로 매핑. 후보를 60개로 넓게 뽑아 조인 필터 후 15개로 컷. ② OAuth 콜백(`/callback/{provider}`)에 **에러/사용자취소/state 만료** 처리 → `/auth/login` 리다이렉트(기존 500 방지). ③ `register_member` 에 **phone / phone_country_code / birth_date** 선택 필드 + `member_type` 화이트리스트 검증(migration 008 CHECK와 일치) 추가. |
| `services/account/templates/auth/register.html` | 회원가입 폼 대규모 리라이트(~1000줄). 선수/자녀 검색에 **무기·리그 세그먼트 버튼 UI**(에페/플뢰레/사브르 · 초/중/고/대/일반부), **연락처(국가코드+번호)·생년월일 선택 입력** 추가. |
| `packages/shared_core/email/service.py` | 이메일 인증 URL 경로 변경: `/account/verification/email/verify` → **`/auth/verify-email`**. |
| `tests/unit/test_scraper.py` | fixtures sys.path 를 구 `FencingCommunityDropShipping` → `fencingmind` 로 수정. |
| `services/app/CLAUDE.md` | app 서비스 문서 갱신(※ 원칙상 app 워크트리 관할 파일 — 커밋 전 검토 필요). |

### 다음 할 일 / TODO
1. `register.html` 프론트의 무기/리그 selector 값이 실제로 검색 API 쿼리파라미터(`weapon`, `league`)로 전달되는지 **동작 확인**(account 서버 port 70 띄워서 검증).
2. 이메일 인증 URL 변경(`/auth/verify-email`)에 대응하는 **라우트 핸들러가 실제 존재하는지** 확인 — 없으면 링크 클릭 시 404.
3. `member_type` 화이트리스트 값이 migration 008 CHECK 제약과 정확히 일치하는지 재대조.
4. `services/app/CLAUDE.md` 변경은 app 워크트리 소관 — 이 브랜치에 섞어 커밋할지 분리할지 결정.
5. 커밋 분리 권장: (a) account 회원가입/검색 개선, (b) 이메일 URL 수정, (c) 테스트 경로 수정.

### 결정사항 · 주의점
- **선수 인증 후 수정 정책**은 메모리 `account-post-verification-edit-policy` 참조(영문이름/소속/학년/리그 요청 + SNS만 허용, 대회결과 잠금).
- **개인정보 서류 수집 금지**(제0원칙 4번) — 본인/학부모 인증은 선수 데이터 교차검증 + AI 추론으로만.
- 무기/리그는 players 원본 컬럼이 아니라 **파생 정보**(rankings 조인). 조회 실패 시 필터를 생략하고 원본 결과 반환하도록 fail-open 처리됨.
- 서버 실행: `PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/account" python -m uvicorn services.account.app.server:app --host 0.0.0.0 --port 70`

---

## 🏗️ 8대 서브도메인 아키텍처

### 서브도메인 구조
| 서브도메인 | 용도 | 상태 | 포트 |
|------------|------|------|------|
| **account.fencingmind.ai** | 인증/프로필/구독 관리 | 🔨 개발 중 | 70 |
| **data.fencingmind.ai** | 펜싱 데이터 (대회, 선수, 랭킹) | ✅ 운영 중 | 71 |
| **club.fencingmind.ai** | 클럽 관리 SaaS (클럽/코치/선수/학부모) | 🔨 개발 중 | 72 |
| **community.fencingmind.ai** | 커뮤니티 (포럼, Q&A) | 📋 계획 | 73 |
| **shop.fencingmind.ai** | 드롭쉬핑 (용품) | 📋 계획 | 74 |
| **blog.fencingmind.ai** | 콘텐츠 (기술 가이드, 리뷰) | 📋 계획 | 75 |
| **analytics.fencingmind.ai** | AI 경기 분석 | 📋 계획 | 76 |
| **app.fencingmind.ai** | PWA/알림 허브 (FCM + 카카오 알림톡) | 🔨 개발 중 | 77 |

### 수익 모델 요약
| 서비스 | 모델 | 예상 수익 |
|--------|------|----------|
| Account | 직접 수익 없음 (인프라) | - |
| Data | API 구독 ($99~999/월) | B2B |
| Club | SaaS 구독 ($9.99~299/월) | B2C/B2B |
| Community | 광고 + 프리미엄 멤버십 | B2C |
| Shop | 드롭쉬핑 마진 (15~30%) | B2C |
| Blog | 광고 + 스폰서 콘텐츠 | B2C |
| Analytics | 건별/구독 ($19.99~499/월) | B2C/B2B |
| App | 직접 수익 없음 (인프라) | - |

---

## 🗄️ 데이터베이스 아키텍처 (Merge 충돌 방지)

### 테이블 분류
```
┌─────────────────────────────────────────────────────────────────────┐
│                    SHARED CORE (공유 - 모든 서브도메인 참조)          │
├─────────────────────────────────────────────────────────────────────┤
│  members              회원 (통합 인증 - SSO)                         │
│  oauth_connections    OAuth 연동 (카카오 등)                         │
│  organizations        조직 (클럽/학교/팀)                            │
│  players              선수 프로필 (대회 데이터에서 추출)               │
│  services             서비스 정의                                    │
│  member_services      회원-서비스 구독 관계                          │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│               DOMAIN-SPECIFIC (서브도메인별 독립 - 접두사 규칙)        │
├─────────────────────────────────────────────────────────────────────┤
│  (기존 유지)    competitions, events, players, matches, rankings     │
│  data_*         데이터 파이프라인 (data_events, validation_logs 등)   │
│  club_*         클럽 SaaS 기능 (club_notifications, club_schedules 등) │
│  community_*    커뮤니티 (community_posts, community_comments 등)    │
│  shop_*         쇼핑 (shop_products, shop_orders 등)                 │
│  blog_*         블로그 (blog_articles, blog_comments 등)             │
│  analytics_*    AI 분석 (analytics_videos, analytics_results 등)     │
│  app_*          PWA/알림 (app_push_subscriptions, app_notification_log 등) │
└─────────────────────────────────────────────────────────────────────┘
```

### 🔴 테이블 네이밍 규칙 (CRITICAL)
- **공유 테이블**: 접두사 없음 (members, players, organizations)
- **도메인 전용**: `{domain}_` 접두사 필수 (shop_orders, blog_articles)
- **마이그레이션**: 새 파일로만 추가, 기존 파일 수정 금지

### 회원 시스템: 통합 인증 (SSO)
```
members (핵심)
├── id (UUID)
├── supabase_auth_id → Supabase Auth
├── player_id → players (선수 프로필 연결)
└── organization_id → organizations

member_services (서비스별 구독)
├── member_id → members
├── service_id: 'data' | 'club' | 'community' | 'shop' | 'blog' | 'analytics' | 'app'
├── tier: 'free' | 'basic' | 'premium'
└── settings: JSONB (서비스별 설정)
```

### 결제 시스템: 서비스별 분리
| 서비스 | 결제 특성 | 테이블 |
|--------|----------|--------|
| club (SaaS) | 월정액 구독 | club_subscriptions |
| shop (쇼핑) | 건별 결제 | shop_payments |
| analytics (AI) | 크레딧 기반 | analytics_credits |

---

## 🌐 다국어 & 테마 정책 (i18n & Theme Policy)

### 구현 상태 (2026-05-31)
| 구성 요소 | 상태 | 위치 |
|-----------|------|------|
| **shared_core.i18n 모듈** | ✅ 완료 | `packages/shared_core/i18n/` |
| **공유 번역 (7개 언어)** | ✅ 완료 | `packages/shared_core/i18n/translations/` |
| **account 서비스 연동** | ✅ 완료 | 자체 i18n + shared_core 미들웨어 |
| **data 서비스 연동** | ✅ 완료 | 자체 i18n + shared_core 미들웨어 |
| **club 서비스 연동** | ⏳ 각 워크트리에서 진행 필요 | `FencingMind-club` 워크트리 |
| **shop 서비스 연동** | ⏳ 각 워크트리에서 진행 필요 | `FencingMind-shop` 워크트리 |
| **analytics 서비스 연동** | ⏳ 각 워크트리에서 진행 필요 | `FencingMind-analytics` 워크트리 |
| **community 서비스 연동** | ⏳ 각 워크트리에서 진행 필요 | `FencingMind-community` 워크트리 |
| **blog 서비스 연동** | ⏳ 각 워크트리에서 진행 필요 | `FencingMind-blog` 워크트리 |
| **app 서비스 연동** | ⏳ 각 워크트리에서 진행 필요 | `FencingMind-app` 워크트리 |

### 지원 언어 (7개)
| 코드 | 언어 | 테마 | 비고 |
|------|------|------|------|
| `ko` | 한국어 | Light | 기본 언어, Toss/Apple 스타일 |
| `en` | English | Dark | 글로벌 기본 |
| `fr` | Français | Dark | |
| `it` | Italiano | Dark | |
| `ja` | 日本語 | Light | |
| `zh` | 中文 | Light | |
| `tr` | Türkçe | Dark | |

### 테마 결정 규칙
- **수동 테마 토글 없음** — 언어 선택이 테마를 자동 결정
- 아시아 3개 언어(ko, ja, zh) → Light 테마
- 서양 4개 언어(en, fr, it, tr) → Dark 테마
- `LANG_THEME_MAP` 딕셔너리로 관리 (`shared_core.i18n.constants`)

### 테마 구현 방식
- `<html data-theme="light|dark">` 속성으로 CSS 변수 전환
- 디자인 토큰: `packages/shared-ui/styles/variables.css`
- 각 서비스 미들웨어가 `request.state.theme` 설정
- 로고: light → 검정 텍스트 로고, dark → 흰색 텍스트 로고

### 🔴 금지 사항
- ❌ 테마 수동 토글 UI 구현 금지
- ❌ 하드코딩 색상 사용 금지 (CSS 변수 필수)
- ❌ 서비스별 다른 언어 목록 금지 (7개 통일)
- ❌ 서비스별 다른 언어 전환 UI 금지 (포맷 통일)

### shared_core.i18n 모듈 사용법
```python
# 서비스의 server.py에서 (공유 번역만 사용)
from shared_core.i18n import LanguageMiddleware
app.add_middleware(LanguageMiddleware)

# 서비스별 번역을 추가로 로드하려면 (deep merge)
from shared_core.i18n import LanguageMiddleware, create_shared_i18n
from pathlib import Path
i18n = create_shared_i18n(extra_dirs=[Path(__file__).parent / "i18n" / "translations"])
app.add_middleware(LanguageMiddleware, i18n=i18n)

# 라우터에서 템플릿 컨텍스트
from shared_core.i18n import create_language_context
context = create_language_context(request)
```

### 번역 파일 구조 (Deep Merge)
```
packages/shared_core/i18n/translations/   (공통 번역, 기본)
    + 서비스별 app/i18n/translations/      (서비스 고유, 오버라이드)
    = 최종 번역 (deep merge, 서비스별이 우선)
```
- 미번역 언어는 en fallback → ko fallback → 키 자체 반환 순서
- 새 언어 추가 시 모든 서비스에 동시 추가

### LanguageMiddleware가 request.state에 설정하는 값
| 키 | 타입 | 설명 |
|----|------|------|
| `lang` | str | 현재 언어 코드 (예: 'ko') |
| `theme` | str | 'light' 또는 'dark' |
| `t` | callable | 번역 함수 `t('common.nav.login')` |
| `supported_langs` | list | 지원 언어 목록 |
| `language_names` | dict | 언어 표시명 |
| `i18n_data` | dict | 현재 언어의 전체 번역 데이터 |

### 언어 감지 우선순위
1. `?lang=` 쿼리 파라미터
2. URL 경로 접두사 (`/{lang}/...`)
3. `lang` 쿠키 (domain: `.fencingmind.ai`)
4. `Accept-Language` 헤더
5. 기본값: `ko`

---

## 🌲 Git Worktree 개발 전략

### 브랜치 구조
```
main                           # 프로덕션 (보호됨)
├── develop                    # 통합 개발
│   ├── feature/account/*       # account.fencingmind.ai
│   ├── feature/data/*         # data.fencingmind.ai
│   ├── feature/club/*         # club.fencingmind.ai
│   ├── feature/community/*    # community.fencingmind.ai
│   ├── feature/shop/*         # shop.fencingmind.ai
│   ├── feature/blog/*         # blog.fencingmind.ai
│   ├── feature/analytics/*    # analytics.fencingmind.ai
│   ├── feature/app/*          # app.fencingmind.ai
│   └── feature/shared/*       # 공유 패키지
└── release/v*                 # 릴리스 브랜치
```

### Worktree 설정 명령어
```bash
# 서브도메인별 worktree 생성
git worktree add ../FencingMind-account feature/account/main
git worktree add ../FencingMind-data   feature/data/main
git worktree add ../FencingMind-club   feature/club/main
git worktree add ../FencingMind-community feature/community/main
git worktree add ../FencingMind-shop   feature/shop/main
git worktree add ../FencingMind-blog   feature/blog/main
git worktree add ../FencingMind-analytics feature/analytics/main
git worktree add ../FencingMind-app    feature/app/main
```

### 현재 활성 Worktree 목록
```
/Users/gyejinpark/Documents/GitHub/fencingmind           → feature/account/init (메인 저장소)
/Users/gyejinpark/Documents/GitHub/FencingMind-data       → feature/data/main
/Users/gyejinpark/Documents/GitHub/FencingMind-club       → feature/club/main
/Users/gyejinpark/Documents/GitHub/FencingMind-community  → feature/community/main
/Users/gyejinpark/Documents/GitHub/FencingMind-shop       → feature/shop/main
/Users/gyejinpark/Documents/GitHub/FencingMind-blog       → feature/blog/main
/Users/gyejinpark/Documents/GitHub/FencingMind-analytics  → feature/analytics/main
/Users/gyejinpark/Documents/GitHub/FencingMind-app        → feature/app/main
```

### 🔴 워크트리별 수정 범위 (CRITICAL)
각 워크트리의 Claude 세션에서 수정 가능한 파일:
| 워크트리 | 수정 가능 | 수정 금지 |
|----------|----------|----------|
| `fencingmind` (메인) | `services/account/`, `packages/shared_core/`, `packages/shared-ui/`, 프로젝트 공통 | 다른 `services/*/` |
| `FencingMind-data` | `services/data/` | 다른 `services/*/` |
| `FencingMind-club` | `services/club/` | 다른 `services/*/` |
| `FencingMind-app` | `services/app/` | 다른 `services/*/` |
| (기타 동일 패턴) | `services/{해당서비스}/` | 다른 `services/*/` |

### 🔴 Merge 충돌 방지 규칙 (CRITICAL)
| 규칙 | 설명 |
|------|------|
| **R1** | `services/{domain}/` 내부 파일은 해당 도메인 브랜치에서만 수정 |
| **R2** | `packages/shared-*` 수정 시 `feature/shared/*` 브랜치 사용 |
| **R3** | `database/migrations/` 새 파일 추가만 허용 (기존 파일 수정 금지) |
| **R4** | 공유 패키지 수정 PR은 모든 서비스 테스트 통과 필수 |
| **R5** | 서브도메인 간 직접 import 금지 (shared-api 통해서만) |

---

## 🔴 로고 규칙 (LOGO RULES - DO NOT CHANGE)

### 로고 원본 저장소
```
services/logo/                              ← 모든 로고 원본 (중앙 저장소)
├── FencingMind_logo_long.png               # 기본 (검은 텍스트)
├── FencingMind_logo_long_white.png         # 다크 테마용 (흰 텍스트) ⭐
├── FencingMind_logo_long_Tracker.png       # Data 서비스 (검은 텍스트)
├── FencingMind_logo_long_Tracker_white.png # Data 서비스 다크 테마용 ⭐
├── FencingMind_logo_long_Club.png          # Club 서비스 (검은 텍스트)
├── FencingMind_logo_long_Club_white.png    # Club 서비스 다크 테마용 ⭐
├── FencingMind_logo_long_Shop.png          # Shop 서비스 (검은 텍스트)
├── FencingMind_logo_long_Shop_white.png    # Shop 서비스 다크 테마용 ⭐
├── FencingMind_logo_square.png             # 정사각형 (파비콘/앱 아이콘)
├── FencingMind_logo_square_white.png       # 정사각형 다크 테마용
├── FencingMind_logo_square_tracker.png     # Data 정사각형
├── FencingMind_logo_square_tracker_white.png
├── FencingMind_logo_square_shop.png        # Shop 정사각형
├── FencingMind_logo_square_shop_white.png
└── *.afdesign                              # Affinity Designer 원본 파일
```

### 서비스별 로고 매핑 (테마별 2종)
| 서비스 | 서비스명 | Dark 테마 (white) | Light 테마 (검정) |
|--------|---------|-------------------|-------------------|
| **account** | (없음) | `FencingMind_logo_long_white.png` | `FencingMind_logo_long.png` |
| **data** | Tracker | `FencingMind_logo_long_Tracker_white.png` | `FencingMind_logo_long_Tracker.png` |
| **club** | Club | `FencingMind_logo_long_Club_white.png` | `FencingMind_logo_long_Club.png` |
| **shop** | Shop | `FencingMind_logo_long_Shop_white.png` | `FencingMind_logo_long_Shop.png` |
| **community** | Community | `FencingMind_logo_long_white.png` (기본) | `FencingMind_logo_long.png` (기본) |
| **blog** | Blog | `FencingMind_logo_long_white.png` (기본) | `FencingMind_logo_long.png` (기본) |
| **analytics** | Analytics | `FencingMind_logo_long_white.png` (기본) | `FencingMind_logo_long.png` (기본) |
| **app** | (없음) | `FencingMind_logo_long_white.png` | `FencingMind_logo_long.png` |

### 각 서비스에서 로고 사용법
각 서비스의 `static/images/logo/`에 필요한 로고를 복사하여 사용:
```bash
# 예: data 서비스
cp services/logo/FencingMind_logo_long_Tracker_white.png \
   services/data/static/images/logo/

# 예: account 서비스
cp services/logo/FencingMind_logo_long_white.png \
   services/account/static/images/logo/
```

### HTML 로고 마크업 (표준 — 테마별 분기)
```html
<!-- Jinja2 템플릿에서 테마별 로고 분기 -->
{% if theme == 'dark' %}
<a href="/" class="logo">
    <img src="/static/images/logo/FencingMind_logo_long_Tracker_white.png"
         alt="FencingMind Tracker" height="32">
</a>
{% else %}
<a href="/" class="logo">
    <img src="/static/images/logo/FencingMind_logo_long_Tracker.png"
         alt="FencingMind Tracker" height="32">
</a>
{% endif %}
```
- `theme` 변수는 `LanguageMiddleware`가 `request.state.theme`에 설정
- 템플릿 컨텍스트: `create_language_context(request)`에서 자동 포함

### 로고 형태 선택 기준
| 형태 | 용도 |
|------|------|
| `_long` | navbar, 헤더, 이메일 상단 |
| `_square` | 파비콘, 앱 아이콘, SNS 프로필 |
| `_white` | 다크 테마 배경 (현재 모든 서비스) |
| (white 없음) | 라이트 테마, 인쇄물, 명함 |

### 🔴 금지 사항
- ❌ 이모지(⚔️, 🤺 등)를 로고 대용으로 사용 금지
- ❌ 서비스명 없이 "FencingMind"만 단독 사용 금지 (account 서비스 제외)
- ❌ 로고 색상/폰트를 임의 변경 금지 — 반드시 원본 이미지 사용
- ❌ "Korean Fencing Tracker" 등 비공식 명칭 사용 금지
- ❌ `services/logo/` 외 경로에서 로고 원본 관리 금지

---

## 🔐 통합 인증 UI 규칙 (ALL SERVICES MUST FOLLOW)

**모든 서브도메인(data, club, community, shop, blog, analytics, app)은 아래 규칙을 반드시 따라야 합니다.**

### 인증 주체
- **Account 서비스만 로그인/회원가입을 처리** — 다른 서비스에서 직접 구현 금지
- 각 서비스는 auth shim 라우터로 account 서비스로 리다이렉트만 함
- JWT 쿠키(domain=.fencingmind.ai)를 읽어서 인증 상태 확인

### 로그인 버튼 (통일)
```
[카카오 아이콘] 카카오로 시작하기     ← 노란색 (#FEE500), 검은 글자
[구글 아이콘]   Google로 계속하기     ← 흰색 배경, 회색 테두리
```
- 버튼 순서: 카카오 → 구글 (한국 시장 우선)
- 버튼 높이: 48px, 모서리: 8px, 아이콘: 24x24px
- CSS 클래스: `.auth-btn`, `.kakao-btn`, `.google-btn`
- SVG 아이콘: `services/account/templates/auth/login.html` 참조

### 로그인 URL 패턴
```
로그인:  /auth/login?redirect={현재페이지URL}
로그아웃: /auth/logout (GET, POST 둘 다 지원)
```
- `/auth/login` → account 서비스로 리다이렉트 (auth shim)
- `redirect` 파라미터로 로그인 후 원래 페이지 복귀
- 환경변수: `ACCOUNT_SERVICE_URL` (기본값: `https://account.fencingmind.ai`)

### Auth Shim 라우터 (각 서비스에 필수 구현)
```python
# services/{service}/app/auth/router.py — data 서비스 참조
ACCOUNT_URL = os.getenv("ACCOUNT_SERVICE_URL", "https://account.fencingmind.ai")

@router.get("/auth/login")   # → account 서비스 리다이렉트
@router.get("/auth/me")      # → 로컬 JWT 디코드 (shared_core 사용)
@router.post("/auth/logout") # → account 서비스 리다이렉트
@router.get("/auth/logout")  # → account 서비스 리다이렉트
```
참고 구현: `services/data/app/auth/router.py`

### 로그인 상태 유지 (JWT 쿠키)
```
Cookie: access_token=eyJhbGci...
  Domain: .fencingmind.ai
  Path: /
  HttpOnly: true
  Secure: true
  SameSite: Lax
```
- 서버 사이드: `shared_core.auth.jwt.extract_token(request)` → 쿠키에서 자동 추출
- 클라이언트 사이드: HttpOnly이므로 JS 접근 불가 (보안)

### Navbar 로그인/로그아웃 UI (통일)
```html
<!-- 비로그인 상태 -->
<a href="/auth/login?redirect={{ request.url }}" class="btn-login">로그인</a>

<!-- 로그인 상태 -->
<div class="nav-profile-dropdown">
    <button class="nav-profile-btn">
        <span class="nav-profile-avatar">{{ member.full_name[0] }}</span>
        <span class="nav-profile-name">{{ member.full_name }}</span>
    </button>
    <div class="nav-profile-menu">
        <a href="/dashboard">대시보드</a>
        <a href="https://account.fencingmind.ai/account/me">내 계정</a>
        <a href="#" onclick="handleLogout()">로그아웃</a>
    </div>
</div>
```

### 로그아웃 JS (통일)
```javascript
function handleLogout() {
    localStorage.removeItem('access_token');
    document.cookie = 'access_token=; Path=/; Domain=.fencingmind.ai; Expires=Thu, 01 Jan 1970 00:00:01 GMT;';
    window.location.href = '/auth/logout';
}
```

### 푸터 링크 (통일)
```
이용약관 | 개인정보처리방침 | 개인정보 문의
```
- 이용약관: `https://account.fencingmind.ai/legal/terms`
- 개인정보처리방침: `https://account.fencingmind.ai/legal/privacy`
- 개인정보 문의: `mailto:privacy@fencingmind.ai`
- 하단: `(c) 2024-2026 FencingMind LLC`

### club_role vs 사이트 관리자 (혼동 금지)
```
club_role (클럽 내 역할) — organization_id 스코프 내에서만 유효
  owner       = 이 클럽의 대표 (다른 클럽 접근 불가, 사이트 관리 불가)
  head_coach  = 이 클럽의 수석 코치
  coach       = 이 클럽의 코치
  student     = 이 클럽의 수강생
  parent      = 이 클럽의 학부모

사이트 관리자 (별개 시스템)
  members.is_admin = true → account.fencingmind.ai/admin 접근
  club_role과 무관한 독립적인 권한
```
- Club 서비스에서 URL에 `/admin`을 사용하지 않음 → `/dashboard/owner` 사용
- 모든 클럽 데이터 조회 시 `WHERE organization_id = {member.organization_id}` 필수

### 관련 문서
- `docs/CLUB_AUTH_GUIDE.md` — Club 서비스 인증 연동 상세 가이드
- `docs/DATA_ACCESS_CONTROL.md` — Data 서비스 등급별 접근 권한 명세
- `packages/shared_core/CLAUDE.md` — 공유 인증 패키지 설명

---

## 📁 모노레포 폴더 구조 (현재)

```
FencingMind/
├── packages/                    # 공유 패키지 ✅
│   ├── shared_core/             # 인증, DB, 타입, 개인정보, i18n ✅ 구현 완료
│   │   ├── auth/                # JWT, OAuth, Dependencies
│   │   │   └── oauth/           # OAuthHandler, providers
│   │   ├── db/                  # Supabase 싱글톤 클라이언트
│   │   ├── types/               # 공유 Enum (MemberType, ClubRole 등)
│   │   ├── privacy/             # 마스킹, 익명화
│   │   ├── i18n/                # 다국어 지원 (7개 언어, 테마 매핑)
│   │   │   ├── constants.py     # SUPPORTED_LANGUAGES, LANG_THEME_MAP
│   │   │   ├── manager.py       # TranslationManager (deep merge)
│   │   │   ├── middleware.py    # LanguageMiddleware
│   │   │   └── translations/    # 공유 번역 (7개 언어)
│   │   └── utils/
│   ├── shared-ui/               # 공유 UI 컴포넌트
│   │   ├── components/
│   │   ├── layouts/
│   │   └── styles/
│   └── shared-api/              # 공유 API 클라이언트
│       ├── fencing-data/
│       └── member/
│
├── services/                    # 서브도메인별 서비스 ✅
│   ├── account/                # account.fencingmind.ai 🔨 개발 중
│   │   ├── app/
│   │   ├── templates/
│   │   └── tests/
│   │
│   ├── data/                    # data.fencingmind.ai ✅ 운영 중
│   │   ├── app/                 # FastAPI 앱
│   │   ├── scraper/             # 스크래퍼
│   │   ├── ranking/             # 랭킹 계산
│   │   ├── data_pipeline/       # 데이터 파이프라인
│   │   ├── templates/           # 템플릿
│   │   ├── static/              # 정적 파일
│   │   ├── scheduler/           # 스케줄러
│   │   └── video/               # 영상 (→ analytics로 이동 예정)
│   │
│   ├── club/                    # club.fencingmind.ai 🔨 개발 중
│   │   ├── api/
│   │   ├── dashboard/
│   │   ├── checkin/
│   │   ├── members/
│   │   ├── player/
│   │   └── parent/
│   │
│   ├── community/               # community.fencingmind.ai 📋 계획
│   │   ├── api/
│   │   ├── forum/
│   │   └── qna/
│   │
│   ├── shop/                    # shop.fencingmind.ai 📋 계획
│   │   ├── api/
│   │   ├── products/
│   │   ├── orders/
│   │   └── dropship/
│   │
│   ├── blog/                    # blog.fencingmind.ai 📋 계획
│   │   ├── api/
│   │   ├── articles/
│   │   └── cms/
│   │
│   ├── analytics/               # analytics.fencingmind.ai 📋 계획
│   │   ├── api/
│   │   ├── video/
│   │   ├── ml/
│   │   └── reports/
│   │
│   └── app/                     # app.fencingmind.ai 🔨 개발 중
│       ├── app/                 # FastAPI 앱
│       ├── templates/           # Jinja2 템플릿
│       ├── static/              # 정적 파일
│       └── tests/
│
├── database/migrations/         # 전체 마이그레이션 (공유)
├── infrastructure/              # Docker, Nginx, K8s ✅
│   ├── docker/
│   ├── nginx/
│   └── kubernetes/
│
├── docs/                        # 문서
├── tests/                       # 통합 테스트
└── CLAUDE.md                    # 이 파일
```

### 서버 실행 방법
```bash
# 프로젝트 루트에서 실행 (PYTHONPATH 설정 필수!)
cd /Users/gyejinpark/Documents/GitHub/fencingmind

# data 서비스 실행 (packages 경로 포함 필수!)
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/data" python -m uvicorn services.data.app.server:app --host 0.0.0.0 --port 71

# account 서비스 실행
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/account" python -m uvicorn services.account.app.server:app --host 0.0.0.0 --port 70

# app 서비스 실행
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/app" python -m uvicorn services.app.app.server:app --host 0.0.0.0 --port 77

# 또는 환경변수 export 후 실행
export PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/data"
python -m uvicorn services.data.app.server:app --host 0.0.0.0 --port 71
```

### Import 규칙 (shared_core)
```python
# ✅ 새 코드 (권장) - shared_core에서 직접 import
from shared_core.auth.jwt import create_access_token, get_current_member
from shared_core.types.member import MemberType, ClubRole
from shared_core.privacy.masking import mask_korean_name
from shared_core.db.client import get_supabase_client
from shared_core.auth.dependencies import ServiceMemberContext, require_coach

# ✅ i18n import (권장)
from shared_core.i18n import LanguageMiddleware, create_language_context
from shared_core.i18n import SUPPORTED_LANGUAGES, LANG_THEME_MAP, LANGUAGE_NAMES
from shared_core.i18n import TranslationManager, create_shared_i18n

# ✅ 기존 호환성 (shim) - data 서비스 내에서만 동작
from app.auth.models import MemberType  # → shared_core.types.member에서 가져옴
from app.auth.privacy import mask_korean_name  # → shared_core.privacy.masking에서 가져옴
```

---

## 🚫🚫🚫 제0원칙: Claude 행동 규칙 (CLAUDE BEHAVIOR RULES) 🚫🚫🚫

**이 규칙은 모든 다른 규칙보다 우선합니다**

### 1. 할루시네이션 금지 (NO HALLUCINATION)
- **모르면 모른다고 말하기** - 추측하거나 지어내지 않기
- **확인되지 않은 정보 제공 금지** - 데이터/코드 확인 없이 "~일 것입니다" 금지
- **잘못 알았으면 즉시 인정** - 변명하지 않고 바로 수정

### 2. 룰 변경 시 반드시 허가 받기 (ASK BEFORE CHANGING RULES)
- **기존 동작 방식 변경 금지** - 사용자 허가 없이 로직/UI/데이터 표시 방식 변경 금지
- **"이게 더 좋을 것 같아서" 금지** - 사용자가 요청한 것만 수행
- **불확실하면 질문하기** - 마음대로 판단하지 않고 확인 요청

### 3. 선수 소속 표시 규칙 (PLAYER TEAM DISPLAY)
- **현재 소속은 단 한 군데** - 가장 최근 대회에서의 소속만 표시
- **소속 이력은 별도 섹션** - team_history에서 이전 소속 기록 표시
- **예시**:
  - ✅ 현재 소속: `최병철펜싱클럽`
  - ✅ 소속 이력: `송도펜싱클럽(2023-06~2024-08)`, `최병철펜싱클럽(2024-09~현재)`
  - ❌ 잘못된 표시: `송도펜싱클럽, 최병철펜싱클럽` (두 개 나열 금지)

### 4. 개인정보 서류 수집 금지 (NO PERSONAL DOCUMENT COLLECTION)
- **가족관계증명서, 주민등록등본, 건강보험자격확인서 등 개인정보 서류 절대 수집 금지**
- 개인정보 리스크를 키우는 행위는 리스크가 조금이라도 있으면 절대 하지 않음
- 본인 인증은 AI 추론 + 관리자 검토 방식으로만 처리
- 예외: 사업자등록증 (조직 Claim용 - 공개 정보)
- 학부모 인증: 선수 데이터 교차 검증 + AI 추론으로만 처리

---

## 🔴🔴🔴 제1원칙: 데이터 파이프라인 연결 (DATA PIPELINE INTEGRITY) 🔴🔴🔴

**데이터 사업의 생존 원칙**: 한 곳에서 데이터가 수정되면 관련된 모든 데이터가 파이프라인을 통해 자동으로 업데이트되어야 함

### 핵심 규칙
1. **단일 진실 원천 (Single Source of Truth)**
   - 선수 프로필: `PlayerIdentityResolver` → 모든 UI/API가 이를 참조
   - 수정 발생 시 → 관련 캐시/파생 데이터 모두 무효화 및 재계산

2. **파이프라인 전파 (Propagation)**
   - 선수 프로필 수정 → members 테이블 동기화 → 로스터 UI 업데이트
   - 동명이인 분리/병합 → 모든 참조 데이터 자동 업데이트

3. **데이터 무결성 규칙 (ABSOLUTE)**
   - **성별 불변**: 남자 ↔ 여자 전환 절대 불가 (다른 사람임)
   - **나이그룹 진행**: 시간이 지나면 나이그룹은 올라가거나 유지 (절대 내려가지 않음)
   - **무기 일관성**: 대부분 단일 무기 전문 (2개 이상이면 동명이인 가능성)

4. **위반 시 결과**
   - 데이터 불일치 → 사용자 신뢰 상실 → 사업 실패
   - 모든 데이터 수정 작업은 파이프라인 전파 검증 필수

### 구현 체크리스트
- [ ] 선수 프로필 수정 시 members 테이블 자동 동기화
- [ ] 동명이인 분리/병합 시 연관 데이터 재계산
- [ ] 캐시 무효화 메커니즘 구현
- [ ] 데이터 변경 로그 기록

---

## 🚨🚨🚨 CRITICAL: 데이터 소스 규칙 (반드시 읽으세요!) 🚨🚨🚨

### ❌ 절대 금지 (DO NOT)
- **JSON 파일 생성 금지** - `data/*.json` 파일 새로 만들지 마세요
- **JSON 파일에서 데이터 로드 금지** - 로컬 JSON 파일 읽지 마세요
- **별도 데이터 파일 관리 금지** - 익산, 특정 대회 등 분리 관리 금지
- **test_*.py로 JSON 분석 금지** - 테스트도 Supabase 사용

### ✅ 반드시 사용 (MUST USE)
- **모든 대회 데이터**: `Supabase > competitions` 테이블
- **모든 종목 데이터**: `Supabase > events` 테이블
- **모든 선수 데이터**: `Supabase > players` 테이블
- **모든 순위 데이터**: `Supabase > rankings` 테이블
- **회원 데이터**: `Supabase > members` 테이블

### 📊 현재 Supabase 데이터 현황 (2025-12-22)
| 테이블 | 데이터 수 | 설명 |
|--------|----------|------|
| competitions | 132 | 2019-2025 대회 (익산 포함) |
| events | 2,500 | 모든 종목 |
| players | 11,786 | 모든 선수 |
| rankings | 964 | 최종 순위 |
| members | 11 | 클럽 회원 |
| organizations | 507 | 팀/클럽/학교 |

### 🔧 데이터 조회 방법
```python
# ✅ 올바른 방법 - Supabase MCP 사용
mcp__supabase__execute_sql("SELECT * FROM competitions WHERE ...")
mcp__supabase__execute_sql("SELECT * FROM players WHERE team_name LIKE '%최병철%'")

# ❌ 잘못된 방법 - JSON 파일 사용
# with open("data/fencing_data.json") as f:  # 사용 금지!
#     data = json.load(f)
```

### ⚠️ data/ 폴더의 JSON 파일들
`data/backup/`에 백업 용도로만 보관, **절대 코드에서 로드하지 마세요**

---

## Project Overview
대한펜싱협회(fencing.sports.or.kr) 대회 결과 데이터를 수집하여 웹사이트로 제공하는 프로젝트

## Current Status (2026-05-31)

### 서비스별 개발 현황
| 서비스 | 워크트리 | 브랜치 | i18n | 테마 | 로고 | 상태 |
|--------|----------|--------|------|------|------|------|
| **account** | `FencingMind` (메인) | `feature/account/init` | ✅ 자체 구현 | ✅ 완료 | ✅ 배포 | 🔨 개발 중 |
| **data** | `FencingMind-data` | `feature/data/main` | ✅ 자체 구현 | ✅ 완료 | ✅ 배포 | ✅ 운영 중 |
| **club** | `FencingMind-club` | `feature/club/main` | ⚠️ 자체 i18n 있음 | ⏳ 연동 필요 | ⏳ 미배포 | 🔨 개발 중 |
| **shop** | `FencingMind-shop` | `feature/shop/main` | ⚠️ ko/en만 있음 | ⏳ 연동 필요 | ⏳ 미배포 | 📋 초기 개발 |
| **analytics** | `FencingMind-analytics` | `feature/analytics/main` | ⚠️ 자체 i18n 있음 | ⏳ 연동 필요 | ⏳ 미배포 | 📋 초기 개발 |
| **community** | `FencingMind-community` | `feature/community/main` | ❌ 없음 | ❌ 없음 | ❌ 없음 | 📋 계획 |
| **blog** | `FencingMind-blog` | `feature/blog/main` | ❌ 없음 | ❌ 없음 | ❌ 없음 | 📋 계획 |
| **app** | `FencingMind-app` | `feature/app/main` | ⏳ shared_core 연동 예정 | ⏳ 연동 예정 | ✅ 복사 완료 | 🔨 개발 중 |

### i18n 통일 작업 진행 계획
각 서비스 워크트리에서 `shared_core.i18n`을 import하여 연동해야 함:
1. 기존 자체 i18n → `shared_core.i18n.LanguageMiddleware` 교체
2. 서비스별 번역은 `extra_dirs`로 deep merge
3. 테마 자동 결정 (언어 기반) 적용
4. 로고 light/dark 분기 적용

### Scraping Status
| 연도 | 상태 | 비고 |
|------|------|------|
| 2019~2025 | ✅ 완료 | Supabase에 업로드 완료 |
| 2018 이전 | ❌ 불필요 | 텍스트 공지 형태만 (디지털 결과 없음) |

### Database Status
- **Supabase**: ✅ 모든 데이터 업로드 완료
- 테이블: competitions, events, players, matches, rankings, scrape_logs, organizations, members, attendance, fees 등

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
├── 001_create_tables.sql                # 기본 테이블
├── 002_add_organizations_table.sql      # 조직/주소 테이블
├── ...                                  # 003~020 (생략)
└── 021_create_app_tables.sql            # App 서비스 (PWA/알림)
```

## Architecture

### Components
```
fencingmind/
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

### 🚨 스크래퍼 파일 관리 규칙 (CRITICAL)

#### ✅ 메인 스크래퍼 (사용 중)
```
scraper/
├── full_scraper.py   ← 유일한 메인 스크래퍼 (대한펜싱협회 전체 대회)
├── client.py         ← API 클라이언트
├── config.py         ← 설정
└── models.py         ← 데이터 모델
```

#### 📦 백업 폴더 (사용 완료/deprecated)
```
scraper/backup/
├── playwright_scraper.py    # deprecated - full_scraper.py로 대체됨
├── iksan_international.py   # 2025 익산 대회 전용 (사용 완료)
├── incremental_scraper.py   # 증분 스크래퍼
├── diagnose_*.py            # 디버깅 도구
└── rescrape_*.py            # 재스크래핑 유틸리티
```

#### ⚠️ 대회별 스크래퍼 규칙
- **특정 대회용 스크래퍼 작성 시**: 사용 완료 후 반드시 `scraper/backup/`으로 이동
- **새 스크래퍼 생성 금지**: `full_scraper.py` 수정/확장으로 해결
- **예외**: 완전히 다른 사이트 구조인 경우만 별도 스크래퍼 허용

### 🚨 스크래핑 핵심 규칙 (CRITICAL)
**Pool과 DE는 항상 함께 수집해야 함**
- 대회 데이터는 Pool 결과 + DE 대진표 + 최종 순위가 하나의 세트
- Pool만 따로 수집하거나 DE만 따로 수집하는 것은 불완전한 데이터
- 종목이 끝나면 최종 순위까지 반드시 수집

**데이터 완성도 체크**
```
✅ 완전한 종목 데이터:
- pool_rounds: 풀 라운드별 경기 결과
- pool_total_ranking: 풀 종합 순위 (진출자/탈락자)
- de_bracket: DE 대진표 (16강, 8강, 4강, 결승) + full_bouts
- final_rankings: 최종 순위

❌ 불완전한 데이터:
- pool만 있고 de_bracket 없음
- final_rankings 없음
- de_bracket은 있지만 full_bouts 없음
```

### full_scraper.py (메인 스크래퍼)
- JavaScript 렌더링이 필요한 사이트용 Playwright 기반 스크래퍼
- 페이지 네비게이션: 클릭 방식 (URL 직접 접근 불가)
- Pool + DE + 최종순위 통합 수집

### Usage
```bash
# 전체 스크래핑
python scraper/full_scraper.py

# 연도 범위 지정
python scraper/full_scraper.py --start-year 2023 --end-year 2025

# 특정 대회만
python scraper/full_scraper.py --competition-id 123
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
1. [x] ~~JSON 데이터를 Supabase에 업로드~~ (완료 - 2025-12-22)
2. [x] ~~서버 코드를 Supabase 전용으로 수정~~ (완료 - JSON 로드 로직 제거됨)
3. [x] ~~shared_core.i18n 공유 모듈 구현~~ (완료 - 2026-05-31, 7개 언어 + 테마 매핑)
4. [ ] 각 서비스 워크트리에서 shared_core.i18n 연동 (club, shop, analytics, community, blog, app)
5. [ ] 파비콘 통일 (`services/logo/favicon.ico` → 모든 서비스)
6. [ ] 로고 light/dark 분기 배포 (각 서비스 워크트리에서 진행)
7. [ ] 클럽 관리 기능 완성 (로스터, 출석, 비용)
8. [ ] 카카오 로그인 연동
9. [ ] app 서비스 알림 파이프라인 (FCM + 카카오 알림톡)

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

## Club Management SaaS (클럽 관리 시스템)

### 개요
펜싱 클럽/학교 회원 관리 SaaS - 파일럿: 최병철펜싱클럽 (organization_id: 401)

### 핵심 가치
**우리 데이터 활용이 핵심** - 코치가 자신의 선수들의 대회 성적, 랭킹, 상대 전적을 모두 활용

### API 구조
```
/api/club/
├── /dashboard          대시보드
├── /check-in           출석 체크인 (학생용)
├── /check-in/status    체크인 상태
├── /members            회원 관리
└── /players/           선수 데이터 연동 (핵심!)
    ├── /search         선수 검색
    ├── /link           회원-선수 연결
    ├── /{id}/profile   프로필
    ├── /{id}/competitions  대회 히스토리
    ├── /{id}/stats     성과 지표
    ├── /{id}/head-to-head  상대 전적
    └── /team/roster    팀 로스터
```

### DB 테이블 (Migration 004)
- `club_settings` - 클럽 설정 (자동 체크인 IP, 비용 기본값)
- `attendance` - 출석 기록
- `lessons` - 레슨 일정
- `lesson_participants` - 레슨 참가자
- `fees` - 비용 관리
- `competition_entries` - 대회 참가 관리
- `competition_participants` - 대회 참가자
- `members` 확장: club_role, member_status, enrollment_date

### 역할 (ClubRole)
- `owner` - 클럽 대표
- `head_coach` - 수석 코치
- `coach` - 코치
- `assistant` - 보조 코치
- `student` - 수강생
- `parent` - 학부모
- `staff` - 스태프

### Phase 2 개발 예정

#### 0. 카카오 로그인 연동 (핵심 - 학생 구분 필수)
**문제**: 같은 클럽 IP에서 접속하는 학생들을 구분할 수 없음
**해결**: 카카오 로그인으로 학생 신원 확인

**구현 계획**:
```
1. 카카오 개발자 앱 등록
   - 앱 키 발급 (REST API Key, JavaScript Key)
   - Redirect URI 설정: /auth/kakao/callback

2. 로그인 플로우
   학생 → 카카오 로그인 → 카카오 계정 연동 → 회원 자동 매칭

3. 회원-카카오 계정 연동
   - members 테이블에 kakao_id 컬럼 추가
   - 최초 로그인 시 전화번호/이름으로 회원 자동 매칭
   - 매칭 실패 시 코치가 수동 연결

4. 체크인 플로우 (완성형)
   ┌─────────────────────────────────────────┐
   │ 박소윤 스마트폰                          │
   │ ┌─────────────────────────────────────┐ │
   │ │ 1. 카카오 로그인 (박소윤 계정)       │ │
   │ │ 2. /club/checkin 접속               │ │
   │ │ 3. IP 확인 → 클럽 내 ✅             │ │
   │ │ 4. "체크인" 버튼 탭                  │ │
   │ │ 5. 박소윤 출석 기록 완료 ✅          │ │
   │ └─────────────────────────────────────┘ │
   └─────────────────────────────────────────┘
```

**필요 API**:
- `POST /auth/kakao` - 카카오 로그인 시작
- `GET /auth/kakao/callback` - 카카오 콜백 처리
- `POST /api/club/members/{id}/link-kakao` - 회원-카카오 연결

**DB 변경**:
```sql
ALTER TABLE members ADD COLUMN kakao_id VARCHAR(50);
ALTER TABLE members ADD COLUMN kakao_nickname VARCHAR(100);
ALTER TABLE members ADD COLUMN kakao_profile_image TEXT;
CREATE UNIQUE INDEX idx_members_kakao_id ON members(kakao_id) WHERE kakao_id IS NOT NULL;
```

#### 1. 수업 전 알림 시스템
- 수업 시작 **5분 전** 미체크인 선수 자동 감지
- 코치에게 **웹 알림 + 카카오톡** 발송
- 수업별 출결 현황 실시간 대시보드

#### 2. 미체크인 선수/학부모 알림
- 미체크인 선수에게 **카카오톡 알림** 발송
- 보호자(학부모)에게도 동시 알림
- "자녀 [이름]이 아직 체크인하지 않았습니다" 메시지

#### 3. IP 인식 실패 대응 (Fallback Check-in)
**문제**: 클럽 IP 범위 밖에서 접속 시 자동 체크인 불가
**해결 방안**:
- **코치 대리 체크인**: 코치가 직접 선수 체크인 (checkin_method='coach')
- **위치 인증 체크인**: GPS 기반 geofence 내에서만 수동 체크인 허용
- **QR 코드 체크인**: 클럽 현장에 QR 코드 비치, 스캔 시 체크인 (위치+시간 검증)
- **블루투스 비콘**: 클럽 내 BLE 비콘 설치, 근접 시에만 체크인 가능

#### 4. 가짜 체크인 방지 전략
| 방식 | 설명 | 우회 난이도 |
|------|------|------------|
| IP 검증 | 클럽 공인 IP 확인 | 중 (VPN 가능) |
| GPS Geofence | 반경 100m 내 위치 | 중 (위치 조작 앱) |
| QR 동적 코드 | 5분마다 변경되는 QR | 상 |
| BLE 비콘 | 물리적 근접 필요 | 최상 |
| 복합 인증 | IP + GPS + 시간 조합 | 최상 |

**권장**: Phase 2에서 **QR 동적 코드 + GPS** 조합 구현

#### 5. 카카오톡 알림 연동
- **카카오 알림톡 API** 사용 (비즈니스 채널 필요)
- 템플릿 메시지:
  - 미체크인 알림: "안녕하세요, [클럽명]입니다. [이름]님의 [시간] 수업 출석이 확인되지 않았습니다."
  - 체크인 완료: "[이름]님이 [시간]에 체크인했습니다."

### 관련 파일
```
app/club/
├── router.py           # 메인 라우터
├── models.py           # Pydantic 모델
├── dependencies.py     # 인증/권한
└── players/
    ├── router.py       # 선수 데이터 API
    └── service.py      # 비즈니스 로직

templates/club/
├── dashboard.html      # 코치용 대시보드
└── checkin.html        # 학생용 체크인
```

## App Service - PWA/알림 허브 (app.fencingmind.ai)

### 개요
data 서비스에서 PWA 캐시 문제가 발생하여 PWA를 독립 서비스로 분리.
FCM 웹 푸시 + 카카오 알림톡 알림 허브 역할. data 서비스는 알림 발신자(대회 결과, 랭킹 변동 이벤트)로만 동작.

### 알림 흐름 (data -> app -> 사용자)
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

### 서비스 간 통신: Supabase 테이블 폴링
- data 서비스는 기존 `EventPublisher`로 `data_events` 테이블에 기록 (변경 없음)
- app 서비스가 `app_event_cursor`의 워터마크 기반으로 30초마다 폴링
- 서비스 간 직접 HTTP 호출 없음 -> 결합도 최소, 내결함성 보장

### PWA 캐시 전략 (이전 data 서비스 문제 방지)
- **API/HTML**: network-first (캐시 부실 방지)
- **static/**: cache-first (CACHE_NAME 버전으로 배포시 버스트)
- **외부 CDN**: 캐시 안 함

### DB 테이블 (Migration 021)
- `app_push_subscriptions` - FCM 토큰 + 카카오 사용자 ID 저장
- `app_notification_preferences` - 카테고리별 채널 opt-in/opt-out
- `app_notification_log` - 발송 이력 (채널별 상태 추적)
- `app_event_cursor` - data_events 폴링 워터마크

### 구현 순서 (각 단계별 별도 브랜치)
1. `feature/app/init` - 스캐폴드 + auth shim
2. `feature/app/notifications` - 알림 구독 UI + 설정
3. `feature/app/pipeline` - data<->app 이벤트 폴러 + NotificationDispatcher
4. `feature/app/fcm` - FCM 웹 푸시
5. `feature/app/pwa` - manifest.json + service worker
6. `feature/app/kakao-alimtalk` - 카카오 알림톡 (비즈니스 채널 필요)
7. `feature/app/offline` - 오프라인 지원

### 외부 의존성 (향후 필요)
| 의존성 | 필요 시점 | 비고 |
|--------|----------|------|
| Firebase 프로젝트 (FCM) | Phase 4 | VAPID 키 발급 |
| 카카오 비즈니스 채널 | Phase 6 | 알림톡 템플릿 승인 필요 |
| Cloudflare DNS CNAME | 배포 시 | `app.fencingmind.ai` |
| Cloudflare Tunnel 업데이트 | 배포 시 | app 서비스 라우팅 추가 |
| `pywebpush` 패키지 | Phase 4 | `arch -arm64 python3 -m pip install pywebpush` |

### 관련 파일
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

---

## Important Notes
- 2019년 이전 데이터는 디지털 형태로 존재하지 않음 (스크래핑 대상 아님)
- 사이트 구조상 페이지 네비게이션은 클릭으로만 가능 (JavaScript 상태 의존)
