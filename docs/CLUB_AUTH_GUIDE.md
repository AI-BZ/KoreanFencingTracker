# Club 서비스 인증 연동 가이드

**대상**: club.fencingmind.ai (port 72) 개발자
**인증 제공자**: account.fencingmind.ai (port 70)

---

## 1. 아키텍처 개요

```
사용자 브라우저
    │
    ├── club.fencingmind.ai (port 72)
    │     ├── 로그인 버튼 클릭 → account로 리다이렉트
    │     ├── JWT 쿠키로 인증 상태 확인
    │     └── 역할(club_role)에 따라 다른 대시보드
    │
    └── account.fencingmind.ai (port 70)
          ├── OAuth 로그인 (카카오/구글)
          ├── 회원가입 + 약관 동의
          ├── JWT 토큰 발급 → 쿠키 설정 (domain=.fencingmind.ai)
          └── 로그인 완료 → redirect 파라미터로 원래 페이지 복귀
```

**핵심**: Club 서비스는 로그인/회원가입 기능을 직접 구현하지 않음. Account 서비스로 리다이렉트하고, JWT 쿠키만 읽어서 인증 상태를 확인함.

---

## 2. 로그인 플로우

```
[Club 랜딩 페이지]
    │
    │  "카카오로 시작하기" 클릭
    ▼
[Account 서비스] /auth/login?redirect=https://club.fencingmind.ai/
    │
    │  OAuth 인증 (카카오/구글)
    ▼
[Account 서비스] 신규 → /auth/register (회원가입 폼)
                 기존 → JWT 발급 + 쿠키 설정
    │
    │  redirect URL로 복귀
    ▼
[Club 서비스] JWT 쿠키 확인 → club_role 기반 대시보드 라우팅
```

### 2.1 리다이렉트 URL 규칙

```
로그인:  /auth/login?redirect={원래_URL}
로그아웃: /auth/logout
```

| 환경 | Account URL |
|------|-------------|
| 프로덕션 | `https://account.fencingmind.ai` |
| 로컬 개발 | `http://localhost:70` |

환경변수: `ACCOUNT_SERVICE_URL`

### 2.2 JWT 쿠키

Account 서비스가 로그인 완료 시 설정하는 쿠키:

```
Cookie: access_token=eyJhbGci...
  - Domain: .fencingmind.ai (모든 서브도메인 공유)
  - Path: /
  - HttpOnly: true
  - Secure: true (HTTPS)
  - SameSite: Lax
```

### 2.3 JWT Payload

```json
{
    "member_id": "uuid-string",
    "email": "user@example.com",
    "member_type": "player",
    "exp": 1234567890
}
```

---

## 3. 인증 상태 확인 (서버 사이드)

### 3.1 필수 인증 (로그인 필수 페이지)

```python
from shared_core.auth.dependencies import (
    get_current_club_member,   # 인증 필수 (실패 시 401)
    require_coach,             # 코치 이상
    require_admin,             # 관리자 (owner/head_coach)
    require_staff,             # 스태프 이상
)

@router.get("/dashboard")
async def dashboard(member = Depends(get_current_club_member)):
    # member.member_id, member.club_role, member.organization_id 사용
    ...
```

### 3.2 선택 인증 (비로그인도 접근 가능)

```python
from app.club.dependencies import try_get_current_club_member

@router.get("/")
async def landing(request: Request):
    member = await try_get_current_club_member(request)
    if member:
        # 로그인 상태 → 역할별 대시보드로 리다이렉트
        return RedirectResponse(url=f"/dashboard/{member.club_role.value}")
    # 비로그인 → 랜딩 페이지
    return templates.TemplateResponse("club/landing.html", {"request": request})
```

### 3.3 ServiceMemberContext 필드

```python
member.member_id            # str (UUID)
member.organization_id      # int (소속 클럽 ID)
member.club_role            # ClubRole enum
member.full_name            # str
member.player_id            # Optional[int]
member.guardian_member_id   # Optional[str]
member.email                # Optional[str]
member.member_type          # str ("player", "coach", "club_director", "parent", "general")
member.verification_status  # str ("unverified", "pending", "verified")
member.email_verified       # bool
```

---

## 4. 역할별 라우팅

### 4.1 ClubRole enum

```python
from shared_core.types.member import ClubRole

ClubRole.owner        # 클럽 대표 (관장)
ClubRole.head_coach   # 수석 코치
ClubRole.coach        # 코치
ClubRole.assistant    # 보조 코치
ClubRole.student      # 수강생 (선수)
ClubRole.parent       # 학부모
ClubRole.staff        # 스태프
```

### 4.2 역할별 대시보드 라우팅

**club_role은 해당 클럽(organization_id) 내에서만 유효한 역할입니다.**
owner/head_coach는 "자기 클럽의 관리자"이지, FencingMind 사이트 전체 관리자(admin)가 아닙니다.

```
club_role 범위:
  owner       = 이 클럽의 대표 (organization_id: 401의 관장)
  head_coach  = 이 클럽의 수석 코치
  coach       = 이 클럽의 코치
  ...

사이트 관리자 (별개):
  members.is_admin = true  ← FencingMind 전체 관리자 (account 서비스에서 관리)
  → /admin/* 페이지 접근 (account.fencingmind.ai/admin)
```

```python
@router.get("/")
async def club_root(request: Request):
    member = await try_get_current_club_member(request)
    if not member:
        return templates.TemplateResponse("club/landing.html", {"request": request})

    # club_role은 member.organization_id 클럽 내에서만 유효
    role = member.club_role
    if role in (ClubRole.owner, ClubRole.head_coach):
        return RedirectResponse("/dashboard/owner")     # 클럽 대표 대시보드
    elif role in (ClubRole.coach, ClubRole.assistant):
        return RedirectResponse("/dashboard/coach")     # 코치 대시보드
    elif role == ClubRole.parent:
        return RedirectResponse("/dashboard/parent")    # 학부모 대시보드
    elif role == ClubRole.student:
        return RedirectResponse("/dashboard/student")   # 선수 대시보드
    else:
        return RedirectResponse("/dashboard/student")
```

**주의**: URL에 `/admin`을 사용하지 않음. "admin"은 사이트 전체 관리자로 오해할 수 있으므로 `/dashboard/owner` 사용.

### 4.3 역할 스코프 (CRITICAL)

```
┌─────────────────────────────────────────────────────────┐
│ club_role은 소속 클럽(organization_id) 내에서만 유효      │
│                                                         │
│ owner@최병철펜싱클럽(401)                                 │
│   → 401 클럽의 회원 관리 O                               │
│   → 401 클럽의 설정 변경 O                               │
│   → 402 다른 클럽의 데이터 X (접근 불가)                  │
│   → FencingMind 사이트 관리 X (별개)                     │
│                                                         │
│ 모든 권한 체크 시 반드시 organization_id도 함께 검증       │
└─────────────────────────────────────────────────────────┘
```

```python
# 올바른 권한 체크 패턴
@router.get("/members")
async def list_members(member = Depends(require_staff)):
    # member.organization_id가 자동으로 스코프됨
    # → 자기 클럽(organization_id) 회원만 조회됨
    members = supabase.table("members") \
        .select("*") \
        .eq("organization_id", member.organization_id) \  # 필수!
        .execute()
```

### 4.4 역할별 접근 권한 (클럽 내)

| 기능 | owner | head_coach | coach | assistant | student | parent |
|------|-------|-----------|-------|-----------|---------|--------|
| 클럽 설정 | O | O | - | - | - | - |
| 회원 관리 | O | O | O | O | - | - |
| 비용 관리 | O | O | O | - | - | - |
| 레슨 관리 | O | O | O | O | - | - |
| 출석 전체 조회 | O | O | O | O | - | - |
| 체크인 | - | - | - | - | O | - |
| 내 출석 조회 | - | - | - | - | O | O |
| 자녀 출석 조회 | - | - | - | - | - | O |
| 비용 납부 | - | - | - | - | O | O |
| 선수 데이터 분석 | O | O | O | - | O(본인) | O(자녀) |

---

## 5. 비회원 접근 (클럽 미소속)

로그인은 했지만 `organization_id`가 NULL인 경우 (클럽에 소속되지 않은 회원):

```python
# shared_core/auth/dependencies.py의 get_current_club_member()가
# organization_id가 없으면 403 반환함
# → "소속 클럽이 없습니다" 에러

# 이 경우를 위한 별도 처리가 필요:
async def get_member_or_guest(request: Request):
    """클럽 미소속도 허용 (가입 유도 페이지용)"""
    member = await get_current_member(request)  # shared_core.auth.jwt
    if not member:
        return None  # 비로그인
    if not member.get("organization_id"):
        return {"logged_in": True, "has_club": False, "member": member}
    return {"logged_in": True, "has_club": True, "member": member}
```

### 비소속 회원 플로우

```
로그인 완료 → organization_id == NULL
    │
    ▼
"클럽에 가입하세요" 안내 페이지
    │
    ├── 코치/관장에게 초대 코드 받기
    ├── 클럽 검색 → 가입 신청
    └── 새 클럽 등록 (감독 전용)
```

---

## 6. 로그아웃

### 서버 사이드 (auth shim)

Club 서비스에 `/auth/logout` shim 라우터 추가:

```python
# services/club/app/auth/router.py
ACCOUNT_URL = os.getenv("ACCOUNT_SERVICE_URL", "https://account.fencingmind.ai")

@router.get("/auth/login")
async def login_redirect(redirect: Optional[str] = None):
    url = f"{ACCOUNT_URL}/auth/login"
    if redirect:
        url += f"?redirect={redirect}"
    return RedirectResponse(url=url)

@router.post("/auth/logout")
async def logout_redirect():
    return RedirectResponse(url=f"{ACCOUNT_URL}/auth/logout", status_code=303)

@router.get("/auth/logout")
async def logout_redirect_get():
    return RedirectResponse(url=f"{ACCOUNT_URL}/auth/logout")
```

### 클라이언트 사이드

```javascript
function handleLogout() {
    // 로컬 토큰 정리
    localStorage.removeItem('access_token');
    document.cookie = 'access_token=; Path=/; Expires=Thu, 01 Jan 1970 00:00:01 GMT;';
    // account 서비스로 리다이렉트 (서버 사이드 쿠키 삭제)
    window.location.href = '/auth/logout';
}
```

---

## 7. 참조 파일

### Account 서비스 (인증 발급 측)
| 파일 | 설명 |
|------|------|
| `services/account/app/auth/router.py` | OAuth 콜백 → JWT 발급 |
| `services/account/templates/auth/login.html` | 로그인 페이지 UI (카카오/구글 버튼) |
| `services/account/templates/auth/register.html` | 회원가입 폼 |
| `services/account/templates/base.html` | account base 템플릿 |

### 공유 패키지 (인증 검증)
| 파일 | 설명 |
|------|------|
| `packages/shared_core/auth/jwt.py` | `extract_token()`, `decode_token()`, `get_current_member()` |
| `packages/shared_core/auth/dependencies.py` | `get_current_club_member()`, `require_coach()` 등 |
| `packages/shared_core/types/member.py` | `ClubRole`, `MemberType` enum |

### Club 서비스 (구현 대상)
| 파일 | 설명 |
|------|------|
| `services/club/app/club/dependencies.py` | shared_core 래퍼 (이미 구현됨) |
| `services/club/templates/base.html` | base 템플릿 (navbar 로그인/로그아웃 버튼) |
| `services/club/templates/club/landing.html` | 비로그인 랜딩 (로그인 버튼 있음) |

### Data 서비스 (참고용 — auth shim 패턴)
| 파일 | 설명 |
|------|------|
| `services/data/app/auth/router.py` | auth shim 구현 예시 (login/logout → account 리다이렉트) |

---

## 8. 로컬 개발 환경 설정

### 8.1 필수 조건

Club 서비스의 로그인은 Account 서비스로 리다이렉트하는 구조입니다.
따라서 **로그인 테스트 시 Account 서비스(port 70)를 반드시 함께 실행**해야 합니다.

### 8.2 두 서비스 동시 실행

```bash
# 프로젝트 루트에서 실행
cd /Users/gyejinpark/Documents/GitHub/FencingCommunityDropShipping

# 터미널 1: Account 서비스 (port 70) — 로그인/회원가입 처리
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/account" \
  python3 -m uvicorn services.account.app.server:app --host 0.0.0.0 --port 70

# 터미널 2: Club 서비스 (port 72) — 클럽 관리
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/club" \
  python3 -m uvicorn services.club.app.server:app --host 0.0.0.0 --port 72
```

### 8.3 로그인 플로우 (로컬)

```
사용자가 club(localhost:72)에서 "로그인" 클릭
    │
    ▼
Club auth shim: /auth/login?redirect=http://localhost:72/
    │
    │  → ACCOUNT_SERVICE_URL (localhost:70)로 리다이렉트
    ▼
Account(localhost:70): /auth/login → 카카오/구글 OAuth
    │
    │  로그인 완료 → JWT 쿠키 설정 (domain=localhost)
    ▼
redirect 파라미터로 club(localhost:72)에 복귀
    │
    │  JWT 쿠키 읽어서 인증 상태 확인
    ▼
역할별 대시보드로 라우팅
```

### 8.4 환경변수 (.env)

```bash
# services/club/.env
ACCOUNT_SERVICE_URL=http://localhost:70    # 로컬 개발
# ACCOUNT_SERVICE_URL=https://account.fencingmind.ai  # 프로덕션
```

### 8.5 로컬 쿠키 제약 사항

| 환경 | 쿠키 domain | 서브도메인 공유 |
|------|------------|----------------|
| 프로덕션 | `.fencingmind.ai` | 모든 서브도메인 자동 공유 |
| 로컬 | `localhost` | port만 다르면 공유됨 (localhost:70 ↔ localhost:72) |

로컬에서는 `localhost`로 쿠키가 설정되므로 port가 달라도 JWT 쿠키가 공유됩니다.
별도 설정 없이 로그인/인증이 동작합니다.

### 8.6 Account 서비스 미실행 시

Account 서비스를 실행하지 않고 Club 서비스만 실행하면:
- 로그인 버튼 클릭 → `localhost:70`으로 리다이렉트 → **연결 거부 (ERR_CONNECTION_REFUSED)**
- 해결: Account 서비스를 먼저 실행하세요

---

## 9. 구현 체크리스트

- [ ] `services/club/app/auth/router.py` 생성 — auth shim (login/logout/me → account 리다이렉트)
- [ ] `services/club/app/server.py`에 auth_router 등록
- [ ] 랜딩 페이지 (`landing.html`) 로그인 버튼 URL을 `/auth/login` shim으로 변경
- [ ] `base.html` navbar에서 로그인 상태별 UI 분기 (로그인/프로필/로그아웃)
- [ ] 역할별 대시보드 라우팅 구현 (`/` → role별 redirect)
- [ ] 비소속 회원 안내 페이지 ("클럽에 가입하세요")
- [ ] 환경변수 `ACCOUNT_SERVICE_URL` 설정 (.env)
