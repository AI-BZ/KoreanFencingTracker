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
