# Data 서비스 등급별 접근 권한 명세

**작성일**: 2026-02-25
**대상**: data.fencingmind.ai 개발자
**소스**: Account 서비스 인증 시스템 기준

---

## 1. 사용자 분류 (3단계)

| 구분 | 조건 | JWT 상태 |
|------|------|----------|
| **비회원 (Guest)** | 로그인하지 않은 방문자 | 토큰 없음 (`get_current_member()` → None) |
| **일반회원 (Member)** | 가입 완료, 선수 인증 미완료 | `verification_tier` 0~2 |
| **선수인증 회원 (Verified)** | 선수 데이터 연결 완료 | `verification_tier` 3+ (`player_id` IS NOT NULL) |

---

## 2. JWT 토큰 구조

Account 서비스(`account.fencingmind.ai`)에서 발급하는 JWT 토큰:

```python
# 현재 JWT payload (auth/router.py)
{
    "member_id": "uuid-string",
    "email": "user@example.com",
    "member_type": "general" | "player" | "coach" | "club_director" | "school_director" | "parent",
    "exp": 1234567890
}
```

### JWT에 추가 예정 필드

data 서비스에서 DB 추가 조회 없이 등급을 판별하려면, Account 서비스가 아래 필드를 JWT에 포함해야 함:

```python
# 추가 예정 필드
{
    "verification_tier": 0 | 1 | 2 | 3 | 4,
    "player_id": int | null,
    "email_verified": true | false
}
```

**⚠️ 추가 전까지의 대안**: `get_current_member()`가 반환하는 member dict에서 DB 조회로 `verification_tier` 확인 가능 (shared_core/auth/jwt.py:112 — `SELECT *` from members)

---

## 3. 등급 판별 로직

```python
from shared_core.auth.jwt import get_current_member

async def get_access_level(request):
    member = await get_current_member(request)

    if member is None:
        return "guest", None                    # 비회원

    tier = member.get("verification_tier", 0) or 0
    if tier >= 3:
        return "verified", member               # 선수인증 회원

    return "member", member                     # 일반회원
```

---

## 4. 기능별 접근 권한 매트릭스

### 4.1 API 엔드포인트

| 엔드포인트 | 비회원 | 일반회원 | 선수인증 | 비고 |
|-----------|--------|---------|---------|------|
| `GET /` | O | O | O | 메인 (대회 목록) |
| `GET /api/competitions` | O | O | O | 대회 목록 |
| `GET /api/competition/{event_cd}` | O | O | O | 대회 상세 |
| `GET /api/filters` | O | O | O | 필터 옵션 |
| `GET /api/rankings` | **상위 10명** | O | O | 비회원: 10명 제한 |
| `GET /api/rankings/options` | O | O | O | |
| `GET /api/stats` | O | O | O | 전체 통계 |
| `GET /api/players/search` | **3건 제한** | O | O | 비회원: 결과 3건 |
| `GET /api/player/{name}` | **기본만** | O | O | 비회원: 통계 제외 |
| `GET /api/players/by-id/{id}` | X → 로그인 유도 | O | O | |
| `GET /api/rankings/player/{name}` | X → 로그인 유도 | **기본** | O | 일반: 요약만 |
| `GET /api/fencinglab/player/{name}` | X | X | O | 선수인증 전용 |
| `GET /api/fencinglab/demo` | O (blur) | O (blur) | O | 데모용 |
| `GET /api/fencinglab/clubs/{name}/players` | X | X | O (코치) | 코치 전용 |
| `GET /api/fencinglab/tracked-players` | X | X | O | |

### 4.2 HTML 페이지

| 페이지 | 비회원 | 일반회원 | 선수인증 | 비고 |
|--------|--------|---------|---------|------|
| `/player/{name}` | **blur 처리** | 기본 프로필 | 전체 | 핵심 가입 유도 페이지 |
| `/player/{name}/certificate` | X → 로그인 | X → 인증 유도 | O | 선수인증 전용 |
| `/fencinglab` | blur 티저 | blur 티저 | O | |
| `/fencinglab/player/{name}` | X → 로그인 | X → 인증 유도 | O | |
| `/rankings` | O | O | O | |
| `/search` | O | O | O | |
| `/competition/{event_cd}` | O | O | O | |

---

## 5. 선수 프로필 페이지 (`/player/{name}`) 상세

가장 중요한 가입 유도 페이지. 등급별로 보여주는 정보가 다름:

### 비회원이 보는 것
```
┌─────────────────────────────────────────┐
│ 선수 이름, 소속 클럽, 종목              │  ← 공개
│ 최근 대회 참가 목록 (최대 3건)           │  ← 공개 (제한)
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │  🔒  [blur 처리된 영역]              │ │  ← 통계, 성과
│ │  대회 전적 분석                       │ │
│ │  로그인하면 선수 통계를 볼 수 있습니다  │ │
│ │  [로그인 / 회원가입]                  │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │  🔒  [blur 처리된 영역]              │ │  ← H2H, FencingLab
│ │  상대 전적 분석                       │ │
│ │  [로그인 / 회원가입]                  │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### 일반회원이 보는 것
```
┌─────────────────────────────────────────┐
│ 선수 이름, 소속 클럽, 종목              │  ← 공개
│ 전체 대회 참가 목록                      │  ← 제한 해제
│ 기본 통계 (승률, 참가 대회 수)           │  ← 공개
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │  🔒  [blur 처리된 영역]              │ │  ← 심층 분석
│ │  상대 전적, FencingLab 차트           │ │
│ │  선수 인증하면 심층 분석을 볼 수 있습니다│ │
│ │  [선수 인증하기]                      │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### 선수인증 회원이 보는 것
```
┌─────────────────────────────────────────┐
│ 선수 이름, 소속 클럽, 종목              │
│ 전체 대회 참가 목록                      │
│ 상세 통계 (승률, 풀/DE별, 시즌별 추이)   │
│ 상대 전적 (H2H)                        │
│ FencingLab 차트 (레이더, 모멘텀)        │
│ 성과 인증서 다운로드                     │
│ 전적 전체 내보내기                       │
└─────────────────────────────────────────┘
```

---

## 6. FencingLab 티저 뷰 (blur + lock)

FencingLab 차트는 비회원/일반회원에게 blur 처리하여 가입/인증을 유도:

### blur 대상 차트
| 차트 | 설명 | 비회원 | 일반회원 | 선수인증 |
|------|------|--------|---------|---------|
| Hexagon Radar | 능력치 6각형 (공격/방어/활동/역전/집중/경험) | blur | blur | O |
| Momentum Graph | 경기 흐름 분석 (점수 추이) | blur | blur | O |
| Dynamic Badge | 성취 뱃지 | blur | blur | O |
| Rivalry Mode | 1:1 비교 분석 | X | X | O |

### UI 구현 패턴
```
[blur 영역]
├── 실제 차트를 렌더링하되 CSS blur(8px) 적용
├── 반투명 오버레이 배경 (rgba(0,0,0,0.5))
├── 🔒 아이콘
├── 안내 텍스트
└── CTA 버튼 (로그인 또는 선수 인증)
```

---

## 7. API 응답 분기 패턴

### 패턴 A: 데이터 자체를 제한 (API)

비회원/일반회원에게 민감한 필드를 아예 보내지 않음:

```python
# 선수 프로필 API
response = {
    "name": "홍길동",
    "team": "최병철펜싱클럽",
    "weapon": "foil",
    "competitions_count": 15,  # 기본 정보는 제공
}

if access_level == "guest":
    response["stats"] = None
    response["requires_login"] = True

elif access_level == "member":
    response["stats"] = basic_stats     # 기본 통계만
    response["h2h"] = None
    response["requires_verification"] = True

else:  # verified
    response["stats"] = full_stats      # 전체 통계
    response["h2h"] = h2h_data
```

### 패턴 B: 템플릿에서 분기 (HTML 페이지)

Jinja2 템플릿에서 `access_level` 변수로 분기:

```python
# 라우터에서 context에 포함
context = {
    "request": request,
    "player": player_data,
    "access_level": access_level,  # "guest" | "member" | "verified"
    "login_url": f"/auth/login?redirect={request.url}",
    "verify_url": "/account/verification",
}
```

---

## 8. 리다이렉트 URL

| 버튼 | 대상 URL | 비고 |
|------|---------|------|
| 로그인 / 회원가입 | `/auth/login?redirect={현재URL}` | data 서비스의 auth shim이 account로 리다이렉트 |
| 선수 인증하기 | `https://account.fencingmind.ai/account/verification` | account 서비스 직접 |
| 선수 Claim | `https://account.fencingmind.ai/account/claims/player` | account 서비스 직접 |

**중요**: `/auth/login`은 data 서비스의 auth shim(`services/data/app/auth/router.py`)이 account 서비스로 리다이렉트함. `redirect` 쿼리 파라미터로 원래 페이지 URL을 전달하면, 로그인 완료 후 원래 페이지로 돌아옴.

---

## 9. 검색 결과 제한

### 선수 검색 (`/api/players/search`)

| 등급 | 최대 결과 수 | 표시 정보 |
|------|------------|----------|
| 비회원 | 3건 | 이름, 소속만 |
| 일반회원 | 무제한 | 이름, 소속, 종목, 최근 대회 |
| 선수인증 | 무제한 | 전체 (+ 상대 전적 링크) |

비회원 검색 시 "더 많은 결과를 보려면 로그인하세요" 안내 포함.

### 랭킹 (`/api/rankings`)

| 등급 | 표시 범위 |
|------|----------|
| 비회원 | 상위 10명 |
| 일반회원 | 전체 |
| 선수인증 | 전체 + 본인 순위 하이라이트 |

---

## 10. 참조 파일

### Account 서비스 (인증 발급 측)
| 파일 | 설명 |
|------|------|
| `services/account/app/auth/router.py` | OAuth 콜백 → JWT 발급 (L204, L416) |
| `packages/shared_core/auth/jwt.py` | `create_access_token()`, `get_current_member()` |
| `packages/shared_core/auth/subscription.py` | `get_member_tier()` — 구독 등급 조회 |
| `packages/shared_core/types/service.py` | `SubscriptionTier` enum |
| `packages/shared_core/auth/dependencies.py` | `ServiceMemberContext`, `require_verified()` |

### Data 서비스 (구현 대상)
| 파일 | 설명 |
|------|------|
| `services/data/app/server.py:109` | `get_current_member` 이미 import됨 |
| `services/data/app/auth/router.py` | auth shim (login → account 리다이렉트) |
| `services/data/app/server.py:2357` | `/player/{name}` 페이지 — 핵심 분기 대상 |
| `services/data/app/server.py:2883` | `/api/fencinglab/player/{name}` — 선수인증 전용 |
| `services/data/app/server.py:1383` | `/api/players/search` — 검색 결과 제한 |
| `services/data/app/server.py:1668` | `/api/rankings` — 랭킹 표시 제한 |

### DB 테이블
| 테이블 | 관련 컬럼 |
|--------|----------|
| `members` | `verification_tier` (int 0~4), `player_id`, `email_verified`, `member_type` |
| `member_services` | `service_id='data'`, `tier` (free/basic/premium), `status` |

### 문서
| 문서 | 내용 |
|------|------|
| `docs/PRD_member_verification.md` | 전체 인증 시스템 PRD (1,555줄) |
| `FencingLab.md` | FencingLab UI 상세 설계 (radar, momentum, badge) |
| `packages/shared-ui/DESIGN_SYSTEM.md` | `fm-*` CSS 클래스, 다크 모드 규칙 |

---

## 11. 구현 우선순위

1. **`access_control.py` 유틸리티** — 등급 판별 함수
2. **선수 프로필 페이지** (`/player/{name}`) — 가장 트래픽 많은 가입 유도 페이지
3. **검색 결과 제한** (`/api/players/search`) — 비회원 3건 제한
4. **랭킹 제한** (`/api/rankings`) — 비회원 10명 제한
5. **FencingLab blur** (`/fencinglab/*`) — 차트 blur + CTA
6. **certificate 접근 제한** (`/player/{name}/certificate`) — 선수인증 전용
