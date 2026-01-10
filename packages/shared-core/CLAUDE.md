# shared-core - 공유 핵심 패키지

**경로:** packages/shared-core/
**상태:** 📋 구현 예정

---

## 패키지 개요
모든 서브도메인이 공유하는 핵심 기능

## 폴더 구조
```
packages/shared-core/
├── auth/                # 인증 로직
│   ├── supabase.py      # Supabase Auth 연동
│   ├── kakao.py         # 카카오 OAuth
│   ├── jwt.py           # JWT 처리
│   └── permissions.py   # 권한 관리
├── db/                  # 데이터베이스
│   ├── client.py        # Supabase 클라이언트
│   ├── models.py        # 공유 모델
│   └── migrations.py    # 마이그레이션 헬퍼
├── types/               # 공유 타입 정의
│   ├── member.py        # 회원 타입
│   ├── player.py        # 선수 타입
│   └── organization.py  # 조직 타입
└── utils/               # 공통 유틸리티
    ├── i18n.py          # 다국어
    ├── logging.py       # 로깅
    └── config.py        # 설정
```

---

## Git 브랜치 규칙
🔴 **CRITICAL**: 이 패키지 수정 시 `feature/shared/*` 브랜치 사용
- 모든 서비스 테스트 통과 필수
- 하위 호환성 유지 필수
