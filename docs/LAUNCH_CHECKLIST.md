# Production Launch Checklist
## Korean Fencing Tracker - 런칭 전 업데이트 필요 항목

최종 업데이트: 2025-12-19

---

## 1. OAuth / 인증 관련

### 카카오 로그인
| 항목 | 현재 상태 | 런칭 시 필요 작업 | 요구사항 |
|------|----------|------------------|----------|
| `account_email` scope | ❌ 비활성화 | 동의항목 추가 | 사업자 등록 필요 |
| `profile_image` scope | ❌ 미사용 | 선택적 추가 | 사업자 등록 필요 |
| 앱 검수 | ❌ 개발 모드 | 앱 검수 신청 | 사업자 등록 필요 |
| 도메인 등록 | ⚠️ iptime.org | 실제 도메인 등록 | - |

**설정 위치**: `app/auth/config.py` 67번 줄
```python
# 현재: "scopes": ["profile_nickname"]
# 런칭 시: "scopes": ["profile_nickname", "account_email"]
```

### Google 로그인
| 항목 | 현재 상태 | 런칭 시 필요 작업 | 요구사항 |
|------|----------|------------------|----------|
| Client ID | ❌ 미설정 | Google Cloud Console 설정 | Google 계정 |
| Client Secret | ❌ 미설정 | 환경변수 추가 | - |
| OAuth 동의 화면 | ❌ 미설정 | 앱 정보 입력 | 개인정보처리방침 URL |

**설정 위치**: `.env`
```bash
GOOGLE_CLIENT_ID=<your-client-id>
GOOGLE_CLIENT_SECRET=<your-client-secret>
GOOGLE_REDIRECT_URI=https://your-domain.com/auth/callback/google
```

---

## 2. 보안 관련

### JWT 설정
| 항목 | 현재 상태 | 런칭 시 필요 작업 |
|------|----------|------------------|
| JWT_SECRET_KEY | ⚠️ 기본값 사용 | 강력한 랜덤 키 생성 |
| HTTPS | ❌ HTTP | SSL 인증서 적용 |
| Cookie Secure | ❌ False | True로 변경 |

**설정 위치**: `.env`, `app/auth/router.py`
```python
# router.py - 쿠키 설정 변경 필요
response.set_cookie(
    key="access_token",
    value=access_token,
    httponly=True,
    secure=True,  # HTTPS 필수
    samesite="strict",  # 'lax' → 'strict'
    max_age=60 * 60 * 24,
)
```

### Rate Limiting
| 항목 | 현재 상태 | 런칭 시 필요 작업 |
|------|----------|------------------|
| API Rate Limit | ❌ 없음 | slowapi 또는 Redis 기반 구현 |
| 로그인 시도 제한 | ❌ 없음 | 5회 실패 시 잠금 |

---

## 3. 인프라 관련

### 도메인 및 SSL
| 항목 | 현재 상태 | 런칭 시 필요 작업 |
|------|----------|------------------|
| 도메인 | ⚠️ mssv.iptime.org | 실제 도메인 구매 |
| SSL 인증서 | ❌ 없음 | Let's Encrypt 또는 유료 SSL |
| CDN | ❌ 없음 | CloudFlare 등 고려 |

### 환경변수 업데이트
```bash
# .env - 런칭 시 업데이트 필요
KAKAO_REDIRECT_URI=https://your-domain.com/auth/callback/kakao
GOOGLE_REDIRECT_URI=https://your-domain.com/auth/callback/google
X_REDIRECT_URI=https://your-domain.com/auth/callback/x
```

### 세션/캐시 저장소
| 항목 | 현재 상태 | 런칭 시 필요 작업 |
|------|----------|------------------|
| OAuth State 저장 | ⚠️ 메모리 (dict) | Redis 전환 권장 |
| 세션 저장 | ⚠️ 메모리 | Redis 전환 권장 |

**설정 위치**: `app/auth/router.py` 40-41번 줄
```python
# 현재: 메모리 저장 (서버 재시작 시 유실)
_oauth_states = {}
_pending_registrations = {}

# 런칭 시: Redis 사용 권장
# from redis import Redis
# redis_client = Redis(...)
```

---

## 4. 데이터베이스 관련

### Supabase
| 항목 | 현재 상태 | 런칭 시 필요 작업 |
|------|----------|------------------|
| RLS 정책 | ⚠️ 일부만 적용 | 모든 테이블에 RLS 검토 |
| 백업 정책 | ❌ 미설정 | 자동 백업 설정 |
| 인덱스 최적화 | ⚠️ 기본만 | 쿼리 분석 후 인덱스 추가 |

### Storage
| 항목 | 현재 상태 | 런칭 시 필요 작업 |
|------|----------|------------------|
| verification-images 버킷 | ⚠️ 미확인 | 버킷 생성 및 정책 설정 |
| 파일 크기 제한 | 10MB | 필요시 조정 |
| 허용 파일 타입 | image/* | MIME 타입 검증 강화 |

---

## 5. 법적 요구사항

### 필수 페이지
| 항목 | 현재 상태 | 런칭 시 필요 작업 |
|------|----------|------------------|
| 이용약관 | ❌ 없음 | `/terms` 페이지 작성 |
| 개인정보처리방침 | ❌ 없음 | `/privacy` 페이지 작성 |
| 사업자 정보 | ❌ 없음 | Footer에 표시 |

### 개인정보 관련
| 항목 | 현재 상태 | 런칭 시 필요 작업 | 비고 |
|------|----------|------------------|------|
| 만 14세 미만 처리 | ✅ 구현됨 | 법적 검토 필요 | 보호자 동의 로직 |
| 개인정보 암호화 | ⚠️ 일부 | 전체 민감정보 암호화 | 전화번호, 생년월일 등 |
| 데이터 보관 기간 | ❌ 미정의 | 정책 수립 | 회원 탈퇴 후 처리 |

---

## 6. 모니터링 및 운영

### 로깅
| 항목 | 현재 상태 | 런칭 시 필요 작업 |
|------|----------|------------------|
| 에러 로깅 | ⚠️ 기본 loguru | Sentry 또는 유사 서비스 연동 |
| 접근 로그 | ⚠️ 기본 | 분석용 로그 수집 |
| 보안 로그 | ❌ 없음 | 로그인 실패, 의심 활동 기록 |

### 알림
| 항목 | 현재 상태 | 런칭 시 필요 작업 |
|------|----------|------------------|
| 서버 다운 알림 | ❌ 없음 | UptimeRobot 또는 유사 서비스 |
| 에러 알림 | ❌ 없음 | Slack/Discord 웹훅 |

---

## 7. API 관련

### Gemini API (인증 처리용)
| 항목 | 현재 상태 | 런칭 시 필요 작업 |
|------|----------|------------------|
| API Key | ⚠️ 개발용 | 프로덕션 키 발급 |
| 사용량 모니터링 | ❌ 없음 | 비용 알림 설정 |
| 대체 플랜 | ❌ 없음 | API 실패 시 수동 처리 |

---

## 8. 성능 최적화

| 항목 | 현재 상태 | 런칭 시 필요 작업 |
|------|----------|------------------|
| 정적 파일 캐싱 | ⚠️ 기본 | Cache-Control 헤더 설정 |
| API 응답 캐싱 | ❌ 없음 | Redis 캐시 레이어 추가 |
| 이미지 최적화 | ❌ 없음 | WebP 변환, 리사이징 |
| DB 쿼리 최적화 | ⚠️ 기본 | N+1 문제 해결, 인덱스 추가 |

---

## 우선순위별 정리

### P0 - 필수 (런칭 불가)
1. [ ] HTTPS 적용 (SSL 인증서)
2. [ ] JWT_SECRET_KEY 강력한 키로 변경
3. [ ] 이용약관, 개인정보처리방침 페이지
4. [ ] 실제 도메인 설정 및 OAuth redirect URI 업데이트

### P1 - 매우 중요 (1주 내)
1. [ ] 카카오 앱 검수 신청 (사업자 등록 후)
2. [ ] account_email scope 활성화
3. [ ] Cookie secure=True 설정
4. [ ] 에러 모니터링 (Sentry)

### P2 - 중요 (1개월 내)
1. [ ] Google 로그인 구현
2. [ ] Redis 세션 저장소 전환
3. [ ] Rate Limiting 구현
4. [ ] 로그인 시도 제한

### P3 - 권장 (3개월 내)
1. [ ] CDN 적용
2. [ ] 성능 최적화
3. [ ] 백업 정책 수립
4. [ ] 모니터링 대시보드

---

## 관련 파일 목록

| 파일 | 수정 내용 |
|------|----------|
| `.env` | 환경변수 업데이트 (도메인, OAuth, JWT) |
| `app/auth/config.py` | OAuth scopes, 보안 설정 |
| `app/auth/router.py` | 쿠키 설정, 세션 저장소 |
| `templates/base.html` | Footer 법적 정보 |
| `templates/auth/login.html` | OAuth 버튼 활성화/비활성화 |

---

## 체크리스트 사용법

1. 사업자 등록 완료 후 P0 항목부터 순차 진행
2. 각 항목 완료 시 `[ ]` → `[x]` 로 변경
3. 완료 날짜와 담당자 기록 권장
