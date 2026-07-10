# account.fencingmind.ai - 인증/프로필/구독 관리 서비스

**서브도메인:** account.fencingmind.ai
**포트:** 70
**상태:** 🔨 개발 중

---

## 서비스 개요
- **"누구인가"를 담당** - OAuth 로그인/회원가입, 본인인증, 프로필 관리, 서비스 구독
- 다른 모든 서비스(data, club, shop 등)는 JWT 검증만 수행
- **회원 관리 API는 이 서비스에서만 구현** — 다른 서비스에서 직접 구현 금지

## 수익 모델
- 직접 수익 없음 (인프라 서비스)
- 각 서비스의 구독 관리를 중앙화하여 운영 효율화

---

## 폴더 구조
```
services/account/
├── app/
│   ├── server.py              # FastAPI 앱 (port 70)
│   ├── config.py              # AccountSettings (Gemini 포함)
│   ├── auth/                  # OAuth, 로그인, 회원가입, 로그아웃
│   │   └── router.py
│   ├── profile/               # /account/me, 개인정보, 보호자 연결
│   │   └── router.py
│   ├── verification/          # 본인인증 (Gemini)
│   │   ├── router.py
│   │   └── processor.py       # GeminiVerifier + VerificationProcessor
│   └── subscriptions/         # 서비스 구독 CRUD
│       └── router.py
├── templates/auth/            # 인증 관련 HTML
├── static/                    # CSS/JS
└── tests/
```

## 서버 실행
```bash
cd /path/to/project/root
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/account" \
  python -m uvicorn services.account.app.server:app --host 0.0.0.0 --port 70
```

---

## 엔드포인트

### auth (/auth)
| Method | Path | 기능 |
|--------|------|------|
| GET | /auth/providers | OAuth 프로바이더 목록 |
| GET | /auth/login | 로그인 페이지 |
| GET | /auth/login/{provider} | OAuth 시작 |
| GET | /auth/callback/{provider} | OAuth 콜백 |
| GET | /auth/register | 회원가입 페이지 |
| POST | /auth/register | 회원가입 처리 |
| POST | /auth/logout | 로그아웃 |
| GET | /auth/logout | 로그아웃 (GET) |

### profile (/account)
| Method | Path | 기능 |
|--------|------|------|
| GET | /account/me | 내 프로필 |
| PATCH | /account/me | 프로필 수정 |
| PATCH | /account/me/privacy | 개인정보 설정 |
| POST | /account/guardian/link | 보호자 연결 |

### verification (/account/verification)
| Method | Path | 기능 |
|--------|------|------|
| GET | /account/verification | 인증 페이지 |
| POST | /account/verification/upload | 이미지 업로드 + Gemini |
| GET | /account/verification/status | 인증 상태 |

### subscriptions (/account/services)
| Method | Path | 기능 |
|--------|------|------|
| GET | /account/services | 내 구독 목록 |
| POST | /account/services/{service_id}/subscribe | 서비스 구독 |
| PATCH | /account/services/{service_id} | 구독 변경 |
| DELETE | /account/services/{service_id} | 구독 해지 |

---

## DB 테이블 (소유)
**이 서비스가 주인인 테이블:**
- `members` - 회원 (통합 인증)
- `oauth_connections` - OAuth 연동
- `verifications` - 본인인증 기록
- `member_services` - 서비스 구독

**공유 테이블 (참조만):**
- `players` - 선수 프로필
- `organizations` - 조직

---

## 인증 아키텍처
```
account.fencingmind.ai (이 서비스)
├── OAuth 로그인 → JWT 토큰 발급
├── 프로필/구독 관리
└── shared_core.auth.jwt.create_access_token()

data/club/shop/community/blog/analytics (다른 서비스)
└── shared_core.auth.jwt.get_current_member() ← JWT 검증만
```

---

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/account/*` 브랜치에서만 수정
- 다른 서비스 코드 수정 금지
- 공유 패키지 수정 시 `feature/shared/*` 브랜치 사용
