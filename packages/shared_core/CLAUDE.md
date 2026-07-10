# shared_core - 공유 핵심 패키지

**경로:** packages/shared_core/
**상태:** ✅ 구현 완료 (v0.1.0)

---

## 패키지 개요
모든 서브도메인(data, club, community, shop, blog, analytics)이 공유하는 핵심 기능.
인증(JWT/OAuth), DB 클라이언트, 타입 정의, 개인정보 보호 모듈 제공.

## PYTHONPATH 설정 (필수)
```bash
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/data"
```

## 폴더 구조
```
packages/shared_core/
├── __init__.py
├── auth/
│   ├── __init__.py
│   ├── config.py               # SharedAuthSettings (JWT + OAuth 설정)
│   ├── jwt.py                  # create_access_token(), decode_token(), get_current_member()
│   ├── models.py               # MemberCreate, MemberResponse, TokenData 등
│   ├── dependencies.py         # ServiceMemberContext, require_role(), require_auth()
│   └── oauth/
│       ├── __init__.py
│       ├── providers.py        # OAUTH_PROVIDERS, get_available_providers()
│       ├── handler.py          # OAuthHandler (login URL, token exchange)
│       └── user_info.py        # 프로바이더별 유저정보 정규화
├── db/
│   ├── __init__.py
│   ├── config.py               # SharedDBConfig
│   └── client.py               # get_supabase_client() 싱글톤
├── types/
│   ├── __init__.py
│   ├── member.py               # MemberType, ClubRole, MemberStatus, OAuthProvider 등
│   ├── service.py              # ServiceType, SubscriptionTier
│   └── organization.py         # OrganizationType, ORG_TYPE_LABELS
├── privacy/
│   ├── __init__.py
│   ├── masking.py              # mask_korean_name(), mask_email(), mask_phone()
│   └── anonymize.py            # anonymize_team(), is_minor(), get_age()
├── i18n/
│   ├── __init__.py                # 전체 export
│   ├── constants.py               # SUPPORTED_LANGUAGES, LANG_THEME_MAP 등
│   ├── manager.py                 # TranslationManager (공유+서비스별 번역 deep merge)
│   ├── middleware.py              # LanguageMiddleware, create_language_context
│   └── translations/              # 공유 번역 (7개 언어)
│       ├── ko/common.json         # 한국어 (실제 번역)
│       ├── en/common.json         # 영어 (실제 번역)
│       └── {fr,it,ja,zh,tr}/      # en fallback (추후 번역)
├── utils/
│   └── __init__.py
└── tests/
    └── __init__.py
```

## Import 사용법

### 새 코드 (권장)
```python
from shared_core.auth.jwt import create_access_token, get_current_member
from shared_core.types.member import MemberType, ClubRole
from shared_core.privacy.masking import mask_korean_name
from shared_core.db.client import get_supabase_client
from shared_core.auth.dependencies import ServiceMemberContext, require_coach
```

### 기존 호환성 (shim)
기존 `app.auth.*` import 경로도 동작합니다 (re-export):
```python
from app.auth.models import MemberType  # → shared_core.types.member에서 가져옴
from app.auth.privacy import mask_korean_name  # → shared_core.privacy.masking에서 가져옴
```

## i18n (다국어/테마)

### 개요
- **7개 언어**: ko, en, fr, it, ja, zh, tr
- **테마 자동 결정**: 아시아(ko/ja/zh) → Light, 서양(en/fr/it/tr) → Dark
- **수동 테마 토글 없음** — 언어 선택이 테마를 결정

### Import 사용법
```python
# 상수
from shared_core.i18n import SUPPORTED_LANGUAGES, LANG_THEME_MAP, LANGUAGE_NAMES

# 미들웨어 (서비스 server.py에서)
from shared_core.i18n import LanguageMiddleware
app.add_middleware(LanguageMiddleware)

# 서비스별 번역을 추가하려면
from shared_core.i18n import LanguageMiddleware, create_shared_i18n
from pathlib import Path
i18n = create_shared_i18n(extra_dirs=[Path(__file__).parent / "i18n" / "translations"])
app.add_middleware(LanguageMiddleware, i18n=i18n)

# 라우터에서 템플릿 컨텍스트
from shared_core.i18n import create_language_context
context = create_language_context(request)
```

### 번역 병합 구조
```
shared_core/i18n/translations/  (공통 번역, 기본)
    + 서비스별 app/i18n/translations/  (서비스 고유, 오버라이드)
    = 최종 번역 (deep merge, 서비스별이 우선)
```

### Fallback 순서
요청 언어 → en → ko → key 자체 반환

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
2. URL path prefix (`/{lang}/...`)
3. `lang` 쿠키 (domain: `.fencingmind.ai`)
4. `Accept-Language` 헤더
5. 기본값: `ko`

---

## 인증 아키텍처

### JWT 통합 인증
- 모든 서비스가 동일한 JWT 토큰 사용
- `create_access_token()` → 토큰 생성
- `decode_token()` → 토큰 검증
- `get_current_member()` → 요청에서 회원 정보 추출

### OAuth 연동
- `OAuthHandler` 클래스: 상태 관리, URL 생성, 토큰 교환
- 지원 프로바이더: Kakao, Google, X(Twitter)

### 역할 기반 접근 제어
- `ServiceMemberContext`: 통합 회원 컨텍스트 (기존 ClubMemberContext 대체)
- `require_coach()`, `require_admin()`, `require_staff()`: FastAPI 의존성

---

## Git 브랜치 규칙
🔴 **CRITICAL**: 이 패키지 수정 시 `feature/shared/*` 브랜치 사용
- 모든 서비스 테스트 통과 필수
- 하위 호환성 유지 필수
