# shared-ui - 공유 UI 패키지

**경로:** packages/shared-ui/
**상태:** ✅ 구현 완료

---

## 패키지 개요
모든 서브도메인이 공유하는 UI 컴포넌트와 디자인 시스템

## 🔴🔴🔴 모든 서브도메인 필수 참조 🔴🔴🔴

**모든 UI 개발 시 반드시 이 패키지의 디자인 시스템을 따라야 합니다.**

```
📖 필수 문서: packages/shared-ui/DESIGN_SYSTEM.md
```

## 폴더 구조
```
packages/shared-ui/
├── styles/
│   ├── variables.css    # CSS 변수 (디자인 토큰) ⭐ 핵심
│   ├── base.css         # 기본 스타일, 리셋
│   └── components.css   # 공통 컴포넌트 스타일
├── DESIGN_SYSTEM.md     # 디자인 시스템 문서 ⭐ 필독
└── CLAUDE.md            # 이 파일
```

## 핵심 디자인 토큰

### 색상 (Colors)
```css
/* 배경 */
--fm-bg-primary: #0a0a0f;
--fm-bg-card: rgba(18, 18, 26, 0.85);

/* 강조 - 태극기 컬러 */
--fm-accent-primary: #c9302c;    /* 빨강 */
--fm-accent-secondary: #1e3a8a;  /* 파랑 */

/* 메달 */
--fm-medal-gold: #d4a574;
--fm-medal-silver: #9ca3af;
--fm-medal-bronze: #cd7f32;
```

### 컴포넌트 클래스
```html
<button class="fm-btn fm-btn-primary">버튼</button>
<div class="fm-card">카드</div>
<input class="fm-input">
<table class="fm-table">테이블</table>
<span class="fm-badge fm-badge-gold">1위</span>
```

---

## Git 브랜치 규칙
🔴 **CRITICAL**: 이 패키지 수정 시 `feature/shared/*` 브랜치 사용

## 중요 규칙
- 하드코딩 색상 금지 → CSS 변수 사용 필수
- 테마는 언어별 자동 결정 (수동 토글 없음)
  - Dark 테마: `:root` 기본값 (en, fr, it, tr)
  - Light 테마: `[data-theme="light"]` 오버라이드 (ko, ja, zh)
- 인라인 스타일 금지 → 클래스 사용
- 새 컴포넌트 추가 시 `[data-theme="light"]` 오버라이드도 함께 추가
