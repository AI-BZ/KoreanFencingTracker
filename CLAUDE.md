# FencingMind - Project Context

**회사명:** FencingMind LLC
**도메인:** FencingMind.ai
**비전:** 세계 최초의 펜싱 전문 AI 데이터 플랫폼, 펜싱의 모든 정보를 연결하는 글로벌 허브

---

## 💡 프로젝트 정체성 (ORIGIN STORY)

> **"펜싱 선수 아빠가 딸을 위해 만들었다."**

이 프로젝트의 출발점이자 모든 판단의 기준. 기능·디자인·카피를 결정할 때 이 관점으로 되돌아올 것.

- **1차 사용자는 학부모**다. 대회장에서 스마트폰으로 "우리 애 몇 등이지?"를 확인하는 사람. 모바일 우선, 즉시 이해되는 용어, 로그인 장벽 최소화가 여기서 나온다.
- **데이터는 감정이 실린 기록**이다. 랭킹 숫자 하나가 한 아이의 1년이다. 정확도 타협 금지(제1원칙 데이터 파이프라인), 성적을 함부로 추정·보정하지 않음.
- **전문 데이터 플랫폼의 신뢰도 + 가족이 만든 서비스의 따뜻함**을 동시에 지킨다. 어느 한쪽으로 기울면 안 됨(차갑기만 한 통계 사이트 ❌, 아마추어 팬사이트 ❌).
- 카피/UX 작성 시: 우리가 무엇을 가졌는지(데이터 규모)보다 **방문자가 무엇을 얻는지**(내 선수의 기록)를 먼저 말한다.

---

## 📄 개발/연구 보고서 준비 (진행 중 — 자료 축적 단계)

**목적**: 기획부터 운영까지의 전 과정을 **연구 보고서 형식으로 제출**. 별도로 블로그 운영도 검토.
**공동연구자**: 박소윤 (반드시 공동연구자로 명시할 것)

### 보고서에 들어갈 구성 (계획)
1. **기획 단계 PRD** — 문제 정의, 사용자 정의, 초기 요구사항. (원본 PRD 문서가 있으면 위치 기록 필요)
2. **데이터 취득·관리** — KFA 스크래핑 전략(Playwright, 클릭 기반 네비게이션), Pool+DE+최종순위 세트 수집 원칙, 스케줄러 자동화, Supabase 스키마 설계
3. **기술적 문제와 해결** — 아래 "해결 사례 로그" 참조
4. **기능·디자인 발전사** — 날짜별 정리, 과거 캡처 포함
5. **운영 지표** — 대회 148 / 경기 51,848 / 선수 5,320 (2026-08 기준)

### 자료 보관 위치
- **디자인 캡처 아카이브**: `docs/design-history/YYYY-MM/` (날짜_주제_뷰포트.jpg 규칙)
- **디자인 크리틱 원본**: `.impeccable/critique/`
- **시각 보고서(캡처 포함, claude.ai 아티팩트)**:
  - 2026-07-31 범례/툴팁 패스: `claude.ai/code/artifact/b5eb4371-cb66-4404-b8ec-6991d01bb06e`
  - 2026-07-31 스포츠 브랜드 디자인 패스: `claude.ai/code/artifact/0c1e48ed-bba4-4fcb-b4ae-96505cea1df3`
  - 2026-07-31 디자인 최종 검수(11장): `claude.ai/code/artifact/7ac870a7-9ff9-4c16-ac66-0496edf9f63a`
  - 2026-08-05 랜딩 리디자인: `claude.ai/code/artifact/ea7d8722-a4f9-45ec-9dcf-df37d5892e5a`
- **개발 이력**: git log (커밋 메시지에 문제·원인·해결을 서술형으로 남길 것 — 보고서 1차 사료가 된다)

### 기술적 문제 해결 사례 로그 (보고서 3장 소재)
| 날짜 | 문제 | 근본 원인 | 해결 |
|------|------|-----------|------|
| 2026-06-22 | NT 서브랭킹 포인트 부풀려짐 | 프로덕션 PYTHONPATH 섀도잉으로 구버전 calculator.py import | 루트 섀도 폴더 제거 + PYTHONPATH 재정렬 |
| 2026-07-11 | 배포해도 신코드 미반영 | `cd ${BASE}` + `python -m`이 cwd를 sys.path[0]에 넣어 루트 섀도가 항상 우선 | 섀도 4개 비활성화, `services/data/`만 배포하도록 일원화 |
| 2026-08-01 | 첫 로드 버벅임 | 라이트 테마 parallax를 켜면서 1.4MB PNG가 신규 다운로드 (display:none일 땐 미수신) | WebP 변환 + 모바일 축소본, 이미지 1,830KB → 65KB |
| 2026-08-05 | 모든 비한국어 대회명이 로마자 쓰레기 | `translate_competition_name` 동명 함수 2개, 페이지가 기계 로마자 쪽 사용 | 큐레이션 사전으로 일원화, 미등록은 한국어 원문 폴백 |
| 2026-08-05 | 다크 테마 카드에 박스 7겹 | `[class*="card-"]` 와일드카드가 모든 하위 요소에 매칭 + !important | 실제 카드 컨테이너만 명시 |
| 2026-08-06 | CSS 수정이 프로덕션 미반영 | Cloudflare가 동일 `?v=` 키로 4시간 캐싱 | 캐시버스터 필수 규칙화 (services/data/CLAUDE.md 참조) |
| 2026-08-06 | 게스트에게 랭킹 108/118명 노출 | 블러가 1페이지의 앞 10개 항목에만 적용, 순위 무관 | rank 기준 판정 + 상위 30위로 확대 |
| 2026-08-06 | FencingLab "데이터 없음" | 점수 None인 경기에서 `score_diff` TypeError → 엔드포인트 500 | (수정 예정) None 가드 + 예외 격리 |

**작성 시점**: 기능 안정화 후. 지금은 **자료 축적만** 하고 보고서 본문은 쓰지 않는다.

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
# 프로덕션 (launchd 관리 - 자동 시작/재시작, 포트 9071)
# Cloudflare Tunnel → nginx:9090 → FastAPI:9071
cd /Users/gyejinpark/Documents/GitHub/FencingMind-data/services/data
bash scripts/fencingmind-server.sh restart

# 개발용 (수동)
cd /Users/gyejinpark/Documents/GitHub/FencingMind-data/services/data
PYTHONPATH=".:../../packages" python -m uvicorn app.server:app --host 0.0.0.0 --port 9071

# 모노레포 루트에서 서비스별 실행 (PYTHONPATH 설정 필수!)
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

5. **대회 최종순위 KFA 일치 검증 (MANDATORY)**
   - **원칙**: 대회 종료 후 우리 시스템의 최종순위는 반드시 대한펜싱협회(KFA) 공식 순위와 일치해야 한다
   - **KFA가 진실의 원천**: 최종순위는 KFA 사이트에서 스크래핑한 데이터를 그대로 사용. 자체 계산으로 대체 금지
   - **자체 계산 허용 조건**: KFA 최종순위가 아직 게시되지 않았거나, 스크래핑 실패한 경우에만 `compute_full_final_rankings()`로 임시 계산. 이 경우 `final_rankings_source: "computed"` 표시 필수
   - **검증 절차**:
     1. 대회 종료 + 스크래핑 완료 시, KFA 최종순위와 우리 데이터 비교
     2. 불일치 발견 시 KFA 데이터로 덮어쓰기 (우리 계산 폐기)
     3. 불일치 로그 기록 (`validation_logs` 테이블)
   - **FIE 최종순위 규정 (2026-06 확인 - FencingTime 실제 FIE 대회 결과 기준)**:
     - 1위, 2위: 결승 결과
     - **3위 (동률 3T)**: 준결승 패자 2명 — 유일하게 동률 처리되는 순위
     - **5~8위 (개별)**: 8강 패자 4명, 풀 시드 순으로 개별 순위 (5, 6, 7, 8)
     - **9~16위 (개별)**: 16강 패자, 풀 시드 순으로 개별 순위
     - 이하 동일 패턴 (17~32, 33~64 등)
     - ⚠️ 동률 순위는 3위(3T)만 존재. QF 이하는 모두 시드 기반 개별 순위
   - **구현 위치**: `server.py: compute_dual_de_final_rankings()`, `data_validator.py`에 R24 규칙 추가 예정

### 구현 체크리스트
- [ ] 선수 프로필 수정 시 members 테이블 자동 동기화
- [ ] 동명이인 분리/병합 시 연관 데이터 재계산
- [ ] 캐시 무효화 메커니즘 구현
- [ ] 데이터 변경 로그 기록
- [ ] R24: 대회 최종순위 KFA 일치 검증 자동화

### 랭킹 시스템 원칙 (RANKING SYSTEM RULES)
- **엄격한 연도 기반**: N년 랭킹 = N년 대회 결과만. 롤링 윈도우 사용 금지
- **새 연도 빈 데이터**: 새 해 첫 대회 결과 나올 때까지 해당 연도 랭킹 미생성
- **🔴 자유 참가 원칙 (Open Entry Principle)**: 랭킹 포인트는 자유 참가(open entry) 대회만 인정
  - 포인트 인정: 누구나 자유롭게 참가 신청할 수 있는 대회
  - 포인트 제외: 시도별 선발 등 소수만 참가하는 선발 참가(nominated/selected) 대회
  - 제외 대회: 전국체육대회, 전국소년체육대회 (시도별 1명 선발, 13~18명 참가)
  - 결과 표시: 제외 대회의 경기 결과는 선수 프로필/대회 페이지에 정상 표시 (포인트만 0)
  - 구현: `_extract_results()`에서 해당 대회 skip
- **🔴 유소년/청소년 국가대표 완전 제외**:
  - 유소년/청소년 국가대표 선발전 ≠ 일반 국가대표 선발대회 (완전히 다른 대회)
  - **랭킹 완전 제외**: NT 전체 랭킹, 나이리그 서브랭킹 모두 미포함
  - 대회 페이지/선수 프로필에서는 결과 정상 표시 (포인트만 0)
  - 구현: `_extract_results()`에서 대회명 '유소년'/'청소년' + '국가대표' 포함 시 skip
- **겸 국대선발 = 국가대표 대회**: '겸'은 국가대표 선발도 겸한다는 의미 → NT 전체 랭킹에 포함
- **2카드 시스템**: NT 선발전 출전 선수는 프로필에 2개 랭킹 표시:
  1. 나이리그 랭킹 (일반 대회 + NT 나이리그별 서브랭킹 포인트 합산)
  2. NT 전체 랭킹 (순수 국대선발 + 겸 국대선발 전체 참가자 중 순위)
- **NT 서브랭킹**: NATIONAL급 대회의 전 연령 혼합 결과를 나이리그별로 재순위 → 나이리그 랭킹에 포인트 합산
- **🔴 NT 서브랭킹 포인트 계산**: `total_participants`는 반드시 나이리그별 인원수(`sub_total = len(players)`)를 사용. 전체 NT 이벤트 참가자 수 사용 금지 (2026-06-22 버그 수정 완료)
- **투명한 포인트**: 각 랭킹 카드에 Best N 대회별 포인트 산출 내역 공개
- **NT 나이리그 추론**: 팀 기반 필터링으로 동명이인 혼입 방지 (calculator.py)
- **동명이인 구분**: identity_profile 팀 기반 필터링으로 다른 사람의 랭킹 혼입 방지

---

## 🎯🎯🎯 제2원칙: 사용자 선호 우선 (USER-PREFERENCE-FIRST DESIGN) 🎯🎯🎯

**핵심 시나리오**: 학부모가 "내 딸은 에페 중학생리그 선수"라서 온보딩에서 여자/에페/중등을 선택했다면, 우리는 그 사람에게 **여자 에페 중학생리그와 관련된 모든 데이터를 우선적으로** 보여준다.

### 원칙
1. **리그 중심 필터링**: 사용자가 선택한 무기/성별/나이그룹 조합이 포함된 **모든 대회**의 관련 이벤트를 표시
2. **다연령 대회 포함**: 국가대표선발대회처럼 여러 나이 리그가 혼합된 대회에서도 해당 무기/성별 이벤트를 표시
   - 예: 여자 플뢰레 중등부 선택 → 국가대표선발대회의 "여자 플뢰레" 이벤트도 표시
3. **대회 레벨 불문**: 대회의 레벨(NATIONAL/ELITE/AMATEUR)에 관계없이, 사용자가 선택한 무기/성별에 해당하는 이벤트가 있으면 표시
4. **연령 필터 유연성**: 국가대표 대회 등 다연령 대회는 나이그룹 필터를 적용하지 않음 (해당 대회는 모든 연령에 해당)

### 구현 규칙
```
사용자 선택: weapon=에페, gender=여, age_group=Y14(중등부)

필터링 결과에 포함되는 이벤트:
✅ 제64회 전국남녀종별대회 → 여중 에페(개) (정확한 매칭)
✅ 국가대표선발대회 → 여자 에페 (다연령 대회 - 무기/성별 매칭)
✅ 회장배 → 여자 에페 U13/U17 (U17↔Y14 양방향 매핑)
❌ 제64회 전국남녀종별대회 → 남중 에페(개) (성별 불일치)
❌ 제64회 전국남녀종별대회 → 여중 플뢰레(개) (무기 불일치)
```

### 코드 위치
- `server.py: api_events()` — 이벤트 필터링 로직
- `templates/index.html: autoLoadFromPreferences()` — 온보딩 선호 → 필터 적용
- `static/js/mobile-ux.js: applyPreferencesToHomepage()` — 랭킹 미리보기 적용

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

### 📊 현재 Supabase 데이터 현황 (2026-06-22)
| 테이블 | 데이터 수 | 설명 |
|--------|----------|------|
| competitions | 143 | 2019-2026 대회 (스케줄러 자동 수집) |
| events | 2,795 | 모든 종목 |
| players | 11,786+ | 모든 선수 (영문명 번역 포함), 서버 활성 5,017명 |
| rankings | 964+ | 최종 순위 |
| members | 11 | 클럽 회원 |
| organizations | 507+ | 팀/클럽/학교 |

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
- **프로덕션 URL**: https://data.fencingmind.ai
- **서버**: Mac Studio (Cloudflare Tunnel → nginx:9090 → FastAPI:9071)
- **스케줄러**: `run_scheduler.py --multichannel` (자동 스크래핑 + 변경 감지)

## Current Status (2026-06-22)

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
| 2019~2026 | ✅ 완료 | Supabase에 업로드 완료, 스케줄러로 자동 수집 |
| 2018 이전 | ❌ 불필요 | 텍스트 공지 형태만 (디지털 결과 없음) |

### Database Status
- **Supabase**: ✅ 모든 데이터 업로드 완료
- 테이블: competitions, events, players, matches, rankings, scrape_logs, organizations, members, attendance, fees 등

### 📊 현재 Supabase 데이터 현황 (2026-06-22)
| 테이블 | 데이터 수 | 설명 |
|--------|----------|------|
| competitions | 143 | 2019-2026 대회 (스케줄러 자동 수집) |
| events | 2,795 | 모든 종목 |
| players | 11,786+ | 모든 선수 (영문명 번역 포함), 서버 로드 시 5,017명 활성 |
| rankings | 964+ | 최종 순위 |
| members | 11 | 클럽 회원 |
| organizations | 507+ | 팀/클럽/학교 |

### 구현 완료 기능 요약
| 기능 | 상태 | 구현 시점 |
|------|------|----------|
| 대회/종목/선수 DB | ✅ | 2025-12 |
| 랭킹 시스템 (무기/성별/나이) | ✅ | 2025-12 |
| 실시간 선수 검색 (동명이인 처리) | ✅ | 2025-12 |
| Head-to-Head 상대 전적 | ✅ | 2026-05 |
| 7개 언어 i18n (ko/en/ja/fr/it/zh/tr) | ✅ | 2026-05 |
| 선수명 로마자 변환 + 영문명 수정 API | ✅ | 2026-05 |
| 언어별 테마 분기 (ko/ja/zh→light, en/fr/it/tr→dark) | ✅ | 2026-06 |
| FencingLab 선수 분석 대시보드 | ✅ | 2026-06 |
| 모바일 UX (하단 내비, 반응형) | ✅ | 2026-06 |
| 3단계 접근 제어 (guest/member/verified) | ✅ | 2026-06 |
| Data Guardian 자동 무결성 검증 | ✅ | 2026-05 |
| 자동 스크래핑 스케줄러 | ✅ | 2026-05 |
| 클럽 관리 SaaS (출석/레슨/비용) | ✅ | 2026-01 |
| PWA 제거 (data 서비스) | ✅ | 2026-06 |
| Dual DE 대진표 + Pool 기권 처리 | ✅ | 2026-06 |
| NT 서브랭킹 포인트 버그 수정 | ✅ | 2026-06-22 |
| 스포츠 데이터 브랜드 디자인 (AI슬롭 제거, Barlow Condensed 숫자, 범례 툴팁) | ✅ | 2026-07-31 |
| 라이트 테마 선수 배경 + 선호 리그 변경 UI | ✅ | 2026-08-01 |

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
services/data/
├── app/
│   ├── server.py              # FastAPI 웹 서버 (146 라우트)
│   ├── access_control.py      # 3단계 접근 제어 (guest/member/verified)
│   ├── auth/                  # JWT 인증, OAuth, 역할 기반 접근
│   ├── club/                  # 클럽 관리 SaaS (출석/레슨/비용)
│   ├── i18n/                  # 7개 언어 번역 시스템
│   │   ├── auto_translate.py  # LLM 기반 자동 번역
│   │   ├── event_translator.py # 펜싱 용어 번역
│   │   └── translations/     # ko/en/ja/fr/it/zh/tr
│   ├── player_identity.py     # 동명이인 처리
│   ├── data_guardian.py       # 데이터 무결성 자동 검증
│   └── data_validator.py      # 12개 검증 규칙 (R1-R12)
├── scraper/
│   ├── full_scraper.py        # 메인 스크래퍼 (Playwright)
│   ├── client.py              # API 클라이언트
│   └── backup/                # deprecated 스크래퍼
├── ranking/                   # 랭킹 계산 엔진
├── scheduler/                 # 자동 스크래핑 + 변경 감지
├── templates/                 # 32개 Jinja2 HTML 템플릿
├── static/
│   ├── css/                   # 8개 (variables, dark-theme, components, mobile-ux 등)
│   ├── js/                    # 5개 (main, fencinglab, player-search, mobile-ux 등)
│   └── images/                # 로고, 파비콘
└── scripts/                   # 24개 유지보수/관리 스크립트
```

### Key Pages
| 경로 | 템플릿 | 기능 |
|------|--------|------|
| `/` | index.html | 홈 (선수 검색, 필터) |
| `/{lang}/competitions` | competitions.html | 대회 목록 (정렬/필터) |
| `/competition/{event_cd}` | competition.html | 대회 상세 (Pool/DE/순위) |
| `/{lang}/rankings` | rankings.html | 랭킹 (무기/성별/나이 3단 필터) |
| `/player/{name}` | player_profile.html | 선수 프로필 (통계/이력) |
| `/player/{name}/h2h/{opponent}` | h2h.html | H2H 상대 전적 |
| `/fencinglab` | fencinglab.html | 선수 분석 대시보드 (verified only) |
| `/fencinglab/player/{name}` | fencinglab_player.html | 개별 선수 심층 분석 |
| `/club/` | dashboard.html | 클럽 관리 대시보드 |
| `/selection/kkumnamu/summary` | selection pages | 대표선발 포인트 |

### Key API Endpoints (주요 146개 중)
```
# 선수/검색
GET  /api/players/autocomplete        실시간 검색 제안
GET  /api/player/{name}               선수 프로필
GET  /api/players/{name}/head-to-head/{opponent}  H2H 전적
PUT  /api/player/{name}/english-name  영문명 수정

# 대회/종목
GET  /api/competitions                대회 목록
GET  /api/competition/{event_cd}      대회 상세
GET  /api/events                      종목 목록

# 랭킹
GET  /api/rankings                    필터링 랭킹
GET  /api/rankings/options            필터 옵션

# FencingLab
GET  /api/fencinglab/player/{name}    선수 분석 데이터
GET  /api/fencinglab/demo             비회원 데모 데이터

# 클럽 관리
POST /api/club/check-in              출석 체크인
GET  /api/club/members               회원 목록
POST /api/club/lessons               레슨 생성/관리
GET  /api/club/accounting/summary    비용 대시보드

# 시스템
GET  /api/status                     서버 상태
GET  /api/data/quality               데이터 품질 모니터링
```

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

**Pool 기권(Forfeit/Abandon) 처리 — FIE t.95**
```
KFA 사이트 마커:
- 'A' = Abandon — 해당 선수가 기권
- 'X' = 상대가 기권 — 해당 bout 미진행

처리 규칙:
- A/X 셀은 wins/losses에 카운트하지 않음
- 기권자(is_forfeit: true)는 풀 종합 순위 최하위
- 기권자와의 bout은 상대 선수 승/패에서 완전 제외
- pool_calculator, server.py pool_stats 모두 기권 필터링
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
프로덕션 포트 체계:
  account.fencingmind.ai  = 9070
  data.fencingmind.ai     = 9071 (Cloudflare Tunnel → nginx:9090 → FastAPI:9071)
  club.fencingmind.ai     = 9072
  NLLB 번역 서버          = 8081

프로덕션 서버 관리 (launchd):
  launchctl stop com.fencingmind.data   # 서버 중지
  launchctl start com.fencingmind.data  # 서버 시작
  시작 스크립트: /Users/gyejinpark/opt/fencingmind/scripts/start-data.sh
  로그: /Users/gyejinpark/Library/Logs/FencingMind/data-server.log
  에러 로그: /Users/gyejinpark/Library/Logs/FencingMind/data-server.error.log

관리 스크립트: bash scripts/fencingmind-server.sh {start|stop|restart|status}
스케줄러: python scripts/run_scheduler.py start --multichannel
개발 서버: PYTHONPATH=".:../../packages" python -m uvicorn app.server:app --host 0.0.0.0 --port 9071
```

### 🔴 프로덕션 PYTHONPATH 섀도잉 (CRITICAL — 2026-07-11 근본 해결)
- `${BASE}` = `/Users/gyejinpark/opt/fencingmind/data`
- 현재 `start-data.sh` PYTHONPATH: `${BASE}/services/data:${BASE}:${BASE}/packages` (2026-07-11 재정렬 — services/data 우선)

**진짜 원인 (2026-07-11 규명)**: PYTHONPATH 순서만이 문제가 아니었다. `start-data.sh`가 `cd ${BASE}` 후 `python -m uvicorn`을 실행하는데, `python -m`은 **현재 작업 디렉토리(cwd=`${BASE}`)를 sys.path 맨 앞(sys.path[0])에 넣는다.** 따라서 `${BASE}/app`, `${BASE}/scheduler` 같은 루트 섀도 폴더가 있으면 PYTHONPATH를 어떻게 정렬하든 **cwd가 무조건 먼저 이겨서** 구버전이 import된다. `from app.X` → `${BASE}/app` (구버전), `from ranking.X` → `${BASE}/services/data/ranking` (섀도 없어 정상) 처럼 갈렸다.

**증상 이력**:
- 2026-06-22: `${BASE}/ranking/calculator.py` (구버전)이 신버전을 섀도잉 → NT 서브랭킹 포인트 부풀려짐. `${BASE}/ranking/` 삭제로 부분 해결(나머지 섀도는 방치됨).
- 2026-07-11: `${BASE}/app`, `scheduler`, `scraper`, `data_pipeline` 섀도가 남아있어, `services/data/`에만 배포한 신 server.py가 `from app.de_transforms`를 못 찾아 재시작 시 크래시할 뻔함(재시작 전 import 스모크로 발견·롤백).

**근본 해결 (2026-07-11)**:
1. 루트 섀도 4개(`app`/`scheduler`/`scraper`/`data_pipeline`)를 `${BASE}/_shadow_disabled_20260711/`로 이동(비활성화). cwd에서 사라지니 `from app.X`가 `${BASE}/services/data/`로 폴백.
2. PYTHONPATH를 `services/data` 우선으로 재정렬(start-data.sh + launchd plist 둘 다).
- 검증: 4개 패키지(app/scheduler/scraper/ranking) 모두 `services/data/`에서 로드됨 확인. 이제 **`services/data/`에만 배포하면 반영**된다(루트 이중 배포 불필요).

**예방 (절대 규칙)**:
- `${BASE}/` 루트에 `services/data/` 내부와 동일한 이름의 패키지/모듈 폴더(app, ranking, scheduler, scraper, data_pipeline 등)를 **절대 생성하지 말 것**. `cd ${BASE}` + `python -m` 조합이 cwd를 sys.path[0]에 넣으므로 그런 폴더는 즉시 섀도잉이 된다.
- 배포는 `${BASE}/services/data/`에만 한다. 루트에 코드 폴더가 다시 생기면 이 사고가 재발한다.
- `_shadow_disabled_20260711/`는 며칠 안정 운영 확인 후 삭제 가능.

## Environment Variables
```
SUPABASE_URL=https://tjfjuasvjzjawyckengv.supabase.co
SUPABASE_KEY=<anon_key>
SCRAPE_DELAY=1.0
MAX_CONCURRENT_REQUESTS=3
```

## Next Steps

### 완료 항목
1. [x] ~~JSON 데이터를 Supabase에 업로드~~ (완료 - 2025-12-22)
2. [x] ~~서버 코드를 Supabase 전용으로 수정~~ (완료 - JSON 로드 로직 제거됨)
3. [x] ~~클럽 관리 기능 구현~~ (완료 - 출석/레슨/비용/대회참가)
4. [x] ~~7개 언어 i18n UI 번역 시스템~~ (완료 - 2026-05-18, ko/en/ja/fr/it/zh/tr)
5. [x] ~~선수명 로마자 변환 + 영문명 수정 API~~ (완료 - 2026-05-21)
6. [x] ~~H2H 상대 전적 페이지~~ (완료 - 2026-05-25)
7. [x] ~~언어별 테마 분기 (ko/ja/zh → light, en/fr/it/tr → dark)~~ (완료 - 2026-06-04)
8. [x] ~~FencingLab 선수 분석 대시보드~~ (완료 - 2026-06)
9. [x] ~~모바일 UX (하단 내비, 반응형)~~ (완료 - 2026-06)
10. [x] ~~3단계 접근 제어 (guest/member/verified)~~ (완료 - 2026-06)
11. [x] ~~Data Guardian 자동 무결성 검증~~ (완료 - 2026-05-13)
12. [x] ~~자동 스크래핑 스케줄러 + 변경 감지~~ (완료 - 2026-05)
13. [x] ~~PWA 제거 (data 서비스)~~ (완료 - 2026-06-04, app 서비스로 이동 예정)
14. [x] ~~Dual DE 대진표 + Pool 기권 처리~~ (완료 - 2026-06)
15. [x] ~~NT 서브랭킹 포인트 버그 수정~~ (완료 - 2026-06-22, 프로덕션 PYTHONPATH 섀도잉 해결)
16. [x] ~~shared_core.i18n 공유 모듈 구현~~ (완료 - 2026-05-31, 7개 언어 + 테마 매핑)

### 진행 예정 (data 서비스)
17. [ ] 카카오 로그인 연동 (OAuth)
18. [ ] 대표선발 포인트 시스템 고도화 (꿈나무/선수)
19. [ ] 2026 신규 대회 데이터 지속 수집 (스케줄러 운영)

### 진행 예정 (다른 서비스)
20. [ ] PWA 구현 → app.fencingmind.ai (아래 PWA 계획 참조)
21. [ ] app.fencingmind.ai SaaS 플랫폼 개발
22. [ ] community.fencingmind.ai 커뮤니티
23. [ ] shop.fencingmind.ai 드롭쉬핑
24. [ ] blog.fencingmind.ai 콘텐츠
25. [ ] analytics.fencingmind.ai AI 경기 분석
26. [ ] 각 서비스 워크트리에서 shared_core.i18n 연동 (club, shop, analytics, community, blog, app)
27. [ ] 파비콘 통일 (`services/logo/favicon.ico` → 모든 서비스)
28. [ ] 로고 light/dark 분기 배포 (각 서비스 워크트리에서 진행)
29. [ ] app 서비스 알림 파이프라인 (FCM + 카카오 알림톡)

---

## 📱 PWA (Progressive Web App) 구현 계획

### 현재 상태 (2026-06-04)
- data 서비스에서 **PWA 제거 완료** — manifest.json, sw.js 참조 삭제
- 이유: CSS 자주 변경 중 → Service Worker 캐시가 업데이트 방해, 푸시 알림 미사용
- `static/manifest.json`, `static/sw.js` 파일은 참조만 제거 (파일 자체는 잔류)

### 구현 위치
- **메인 PWA**: `app.fencingmind.ai` (SaaS 플랫폼) — `feature/app/*` 워크트리
- **data 서비스 연동**: 대회 알림 등은 data → app 간 API로 연동

### PWA 핵심 기능 (app 서비스)

#### 1. 푸시 알림 (Push Notifications)
| 알림 유형 | 발신 서비스 | 대상 |
|----------|-----------|------|
| 대회 일정 알림 | **data** → app | 선수/학부모 |
| 대회 결과 알림 | **data** → app | "내 선수" 즐겨찾기 사용자 |
| 랭킹 변동 알림 | **data** → app | 선수 본인/코치 |
| 수업 알림 (5분 전) | **app** 자체 | 학생/학부모 |
| 출석 알림 (미체크인) | **app** 자체 | 학생/학부모 |
| 비용 청구/납부 알림 | **app** 자체 | 학부모 |

#### 2. 홈화면 설치
- app.fencingmind.ai 접속 → "홈 화면에 추가" 프롬프트
- 아이콘: FencingMind 로고
- standalone 모드 (주소창 없는 앱 느낌)

#### 3. 오프라인 지원
- 클럽 로스터, 수업 일정 → 오프라인 캐시
- 출석 체크인 → 오프라인 큐 → 온라인 복귀 시 동기화

#### 4. data ↔ app 알림 파이프라인
```
[data 서비스]                    [app 서비스]
대회 결과 수집 완료               구독자 목록 조회
    → POST /api/notifications     → 푸시 알림 발송
      {type: "result",            → 카카오 알림톡 발송
       competition_id,
       player_ids: [...]}

랭킹 재계산 완료
    → POST /api/notifications
      {type: "ranking_change",
       player_id, old_rank, new_rank}
```

### 구현 순서
1. **카카오 로그인** (선수 식별 필수) → `feature/app/auth`
2. **알림 구독 시스템** (FCM 또는 Web Push API) → `feature/app/notifications`
3. **data → app 알림 API** → `feature/shared/notifications`
4. **manifest.json + Service Worker** → `feature/app/pwa`
5. **오프라인 지원** → `feature/app/offline`

### 기술 스택
- **Web Push API** + **FCM (Firebase Cloud Messaging)** — 브라우저 푸시
- **카카오 알림톡** — 카카오 채널 통한 모바일 알림 (한국 사용자)
- **Service Worker** — 캐싱, 오프라인, 백그라운드 동기화
- **IndexedDB** — 오프라인 데이터 저장

## 🔒 접근 제어 시스템 (Access Control)

### 3단계 접근 레벨
| 레벨 | 인증 상태 | 기능 |
|------|----------|------|
| **guest** | 미로그인 | 검색 (소속 블러), 상위 10위 랭킹 (이름 블러), 기본 정보 |
| **member** | 로그인 | 전체 검색, 전체 랭킹, 통계 표시, H2H/FencingLab 숨김 |
| **verified** | 선수/코치/학부모/감독 | FencingLab, H2H, 민감 분석 등 전체 접근 |

### 구현 파일
- `app/access_control.py` - 접근 레벨 판정 및 데이터 게이팅
- `app/auth/` - JWT 인증, 역할 기반 접근 제어

---

## 🔬 FencingLab 선수 분석

### 기능
- 승률 추이 라인 차트 (히스토리 진행)
- 경기 통계 (라운드별 승/패)
- 무기별 분석, 나이그룹별 분석
- H2H 대진 성적
- Chart.js 기반 시각화 (다크/라이트 테마 적응)

### 접근 제한
- verified 회원만 접근 가능
- 비회원에게는 데모 데이터 제공 (`/api/fencinglab/demo`)

### 관련 파일
- `templates/fencinglab.html` - 분석 대시보드
- `templates/fencinglab_player.html` - 개별 선수 심층 분석
- `static/js/fencinglab.js` - 차트/시각화 로직
- `static/css/fencinglab.css` - FencingLab 전용 스타일

---

## 🌐 i18n & 테마 시스템

### 지원 언어 (7개)
| 언어 | 코드 | 기본 테마 |
|------|------|----------|
| 한국어 | ko | Light |
| 영어 | en | Dark |
| 일본어 | ja | Light |
| 프랑스어 | fr | Dark |
| 이탈리아어 | it | Dark |
| 중국어 | zh | Light |
| 터키어 | tr | Dark |

### 번역 함수 (Jinja2 템플릿)
```jinja2
{{ _t('키') }}              # 정적 번역 (common.json)
{{ tr_event(name) }}        # 펜싱 용어 번역
{{ tr_comp(name) }}         # 대회명 번역
{{ tr_team(name) }}         # 소속 번역 (캐시)
{{ tr_player(name) }}       # 선수명 로마자 변환 (캐시)
```

### 선수명 번역 파이프라인
1. 서버 시작 → `players.translations.en`에서 전체 캐시 로드 (11,786건)
2. 캐시 히트 → 즉시 반환
3. 캐시 미스 → LLM 음역 (비동기) → 캐시 갱신
4. 실패 → 한국어 원문 표시

### 관련 파일
```
app/i18n/
├── __init__.py              # TranslationManager, 미들웨어
├── auto_translate.py        # LLM 기반 자동 번역
├── event_translator.py      # 펜싱 용어 매핑
├── competition_names.py     # 대회명 라이브러리
├── middleware.py            # 언어/테마 감지
└── translations/
    ├── ko/common.json       # 한국어 (기본 언어)
    ├── en/common.json       # 영어
    ├── ja/common.json       # 일본어
    ├── fr/common.json       # 프랑스어
    ├── it/common.json       # 이탈리아어
    ├── zh/common.json       # 중국어
    └── tr/common.json       # 터키어
```

---

## 📱 모바일 UX

### 구현 사항
- 하단 내비게이션 바 (56px, 4탭: Home/Rankings/Competitions/Search)
- iOS 노치 대응 (safe area padding)
- 터치 친화적 버튼 (최소 48px)
- 반응형 브레이크포인트: Mobile(<768px), Tablet(768-1024px), Desktop(>1024px)

### 관련 파일
- `static/css/mobile-ux.css` - 모바일 전용 스타일
- `static/js/mobile-ux.js` - 햄버거 메뉴, 온보딩, 바텀시트

---

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

## 🎨 디자인 시스템

### CSS 파일 구조
| 파일 | 용도 |
|------|------|
| `variables.css` | 디자인 토큰 (색상, 타이포, 간격) |
| `dark-theme.css` | 다크 테마 (태극 컬러) |
| `components.css` | 재사용 컴포넌트 |
| `fencinglab.css` | FencingLab 전용 |
| `bracket.css` | DE 대진표 |
| `mobile-ux.css` | 모바일 반응형 |
| `player-search.css` | 검색 UI |

### 핵심 디자인 토큰
```css
--fm-accent-primary: #c9302c     /* 태극 빨강 */
--fm-accent-secondary: #1e3a8a   /* 태극 파랑 */
--fm-medal-gold: #d4a574         /* 금메달 */
--fm-medal-silver: #9ca3af       /* 은메달 */
--fm-medal-bronze: #cd7f32       /* 동메달 */
```

---

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
- data 서비스에서 PWA 제거됨 (2026-06-04) — CSS 변경 빈도 높아 Service Worker 캐시 방해
- 스케줄러는 `--multichannel` 모드로 자동 스크래핑 + Discord 알림 운영 중
