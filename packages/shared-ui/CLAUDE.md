# shared-ui - 공유 UI 패키지

**경로:** packages/shared-ui/
**상태:** 📋 구현 예정

---

## 패키지 개요
모든 서브도메인이 공유하는 UI 컴포넌트

## 폴더 구조
```
packages/shared-ui/
├── components/          # UI 컴포넌트
│   ├── buttons/         # 버튼
│   ├── forms/           # 폼
│   ├── modals/          # 모달
│   ├── tables/          # 테이블
│   └── cards/           # 카드
├── layouts/             # 공통 레이아웃
│   ├── header/          # 헤더
│   ├── footer/          # 푸터
│   └── sidebar/         # 사이드바
└── styles/              # 공통 스타일
    ├── variables.css    # CSS 변수
    ├── reset.css        # CSS 리셋
    └── utilities.css    # 유틸리티 클래스
```

---

## Git 브랜치 규칙
🔴 **CRITICAL**: 이 패키지 수정 시 `feature/shared/*` 브랜치 사용
