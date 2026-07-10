# FencingMind Design System

**모든 서브도메인이 반드시 따라야 하는 UI 가이드라인**

---

## 🎨 디자인 철학

### 핵심 컨셉
- **Dark Mode First**: 다크 테마 기본, 고급스러운 느낌
- **Glassmorphism**: 반투명 배경 + blur 효과로 깊이감 표현
- **Korean Identity**: 태극기 색상(빨강/파랑) 활용
- **Performance Focus**: 경쟁적 스포츠 데이터 강조

### 디자인 원칙
1. **일관성**: 모든 서브도메인에서 동일한 컴포넌트/색상 사용
2. **계층 구조**: 시각적 계층으로 정보 우선순위 표현
3. **반응형**: 모바일 우선 설계
4. **접근성**: WCAG 2.1 AA 기준 준수

---

## 🎯 필수 CSS 임포트

```html
<!-- 모든 페이지에 반드시 포함 -->
<link rel="stylesheet" href="/packages/shared-ui/styles/variables.css">
<link rel="stylesheet" href="/packages/shared-ui/styles/base.css">
<link rel="stylesheet" href="/packages/shared-ui/styles/components.css">
```

또는 CSS에서:
```css
@import url('../../packages/shared-ui/styles/variables.css');
@import url('../../packages/shared-ui/styles/base.css');
@import url('../../packages/shared-ui/styles/components.css');
```

---

## 🎨 컬러 팔레트

### 배경색 (Backgrounds)
| 변수명 | 값 | 용도 |
|--------|-----|------|
| `--fm-bg-primary` | `#0a0a0f` | 메인 배경 |
| `--fm-bg-secondary` | `#12121a` | 섹션 배경 |
| `--fm-bg-tertiary` | `#1a1a25` | 카드 내부 |
| `--fm-bg-card` | `rgba(18, 18, 26, 0.85)` | 글래스 카드 |

### 강조색 (Accents) - 태극기 컬러
| 변수명 | 값 | 용도 |
|--------|-----|------|
| `--fm-accent-primary` | `#c9302c` | 빨강 - Primary CTA |
| `--fm-accent-secondary` | `#1e3a8a` | 파랑 - Secondary |

### 메달 색상 (Rankings)
| 변수명 | 값 | 용도 |
|--------|-----|------|
| `--fm-medal-gold` | `#d4a574` | 1위 |
| `--fm-medal-silver` | `#9ca3af` | 2위 |
| `--fm-medal-bronze` | `#cd7f32` | 3위 |

### 상태 색상 (Status)
| 변수명 | 값 | 용도 |
|--------|-----|------|
| `--fm-success` | `#10b981` | 성공/승리 |
| `--fm-warning` | `#f59e0b` | 경고 |
| `--fm-danger` | `#ef4444` | 오류/패배 |
| `--fm-info` | `#3b82f6` | 정보 |

---

## 📝 타이포그래피

### 폰트
```css
--fm-font-primary: 'Pretendard Variable', 'Inter', sans-serif;
--fm-font-mono: 'JetBrains Mono', monospace;
```

### 폰트 크기
| 클래스 | 크기 | 용도 |
|--------|------|------|
| `--fm-text-xs` | 0.75rem (12px) | 캡션, 라벨 |
| `--fm-text-sm` | 0.875rem (14px) | 보조 텍스트 |
| `--fm-text-base` | 1rem (16px) | 본문 |
| `--fm-text-lg` | 1.125rem (18px) | 강조 본문 |
| `--fm-text-xl` | 1.25rem (20px) | 소제목 |
| `--fm-text-2xl` | 1.5rem (24px) | 제목 |
| `--fm-text-3xl` | 1.875rem (30px) | 대제목 |
| `--fm-text-4xl` | 2.25rem (36px) | 히어로 |

---

## 🧩 컴포넌트

### 버튼 (Buttons)
```html
<!-- Primary (빨강) - 주요 액션 -->
<button class="fm-btn fm-btn-primary">주문하기</button>

<!-- Secondary (파랑) - 보조 액션 -->
<button class="fm-btn fm-btn-secondary">더보기</button>

<!-- Ghost - 덜 중요한 액션 -->
<button class="fm-btn fm-btn-ghost">취소</button>

<!-- 크기 -->
<button class="fm-btn fm-btn-primary fm-btn-sm">Small</button>
<button class="fm-btn fm-btn-primary fm-btn-lg">Large</button>
```

### 카드 (Cards)
```html
<div class="fm-card">
    <div class="fm-card-header">
        <h3 class="fm-card-title">카드 제목</h3>
    </div>
    <div class="fm-card-body">
        카드 내용
    </div>
</div>
```

### 입력 폼 (Forms)
```html
<div class="fm-form-group">
    <label class="fm-label">이름</label>
    <input type="text" class="fm-input" placeholder="이름을 입력하세요">
</div>

<div class="fm-form-group">
    <label class="fm-label">종목</label>
    <select class="fm-select">
        <option>플뢰레</option>
        <option>에페</option>
        <option>사브르</option>
    </select>
</div>
```

### 테이블 (Tables)
```html
<div class="fm-table-container">
    <table class="fm-table">
        <thead>
            <tr>
                <th>순위</th>
                <th>선수</th>
                <th>점수</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>1</td>
                <td>홍길동</td>
                <td>2,450</td>
            </tr>
        </tbody>
    </table>
</div>
```

### 뱃지 (Badges)
```html
<span class="fm-badge fm-badge-gold">1위</span>
<span class="fm-badge fm-badge-silver">2위</span>
<span class="fm-badge fm-badge-bronze">3위</span>

<span class="fm-badge fm-badge-success">승리</span>
<span class="fm-badge fm-badge-danger">패배</span>
```

### 탭 (Tabs)
```html
<div class="fm-tabs">
    <button class="fm-tab active">예선</button>
    <button class="fm-tab">본선</button>
    <button class="fm-tab">결과</button>
</div>
```

### 알림 (Alerts)
```html
<div class="fm-alert fm-alert-success">성공적으로 저장되었습니다.</div>
<div class="fm-alert fm-alert-warning">주의가 필요합니다.</div>
<div class="fm-alert fm-alert-danger">오류가 발생했습니다.</div>
<div class="fm-alert fm-alert-info">참고 정보입니다.</div>
```

---

## 🖼️ 레이아웃

### 배경 구조 (Parallax)
```html
<body>
    <!-- 배경 이미지 + 오버레이 -->
    <div class="fm-parallax-bg"></div>
    <div class="fm-parallax-overlay"></div>

    <!-- 네비게이션 -->
    <nav class="fm-navbar">
        <div class="fm-container">
            <a href="/" class="fm-logo">
                <span>⚔️</span>
                <span class="fm-logo-text">FencingMind</span>
            </a>
        </div>
    </nav>

    <!-- 메인 콘텐츠 -->
    <main class="fm-main">
        <div class="fm-container">
            <!-- 페이지 내용 -->
        </div>
    </main>
</body>
```

### 컨테이너 크기
| 클래스 | 너비 |
|--------|------|
| `fm-container` | 1200px |
| `fm-container-sm` | 640px |
| `fm-container-lg` | 1024px |
| `fm-container-2xl` | 1400px |

---

## 🌗 Glassmorphism 적용

```css
/* 글래스 효과 */
.fm-glass {
    background: var(--fm-bg-card);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid var(--fm-border);
}
```

---

## ⚠️ 금지 사항

### ❌ 절대 하지 마세요
```css
/* 하드코딩된 색상 금지 */
.wrong { color: #ffffff; }
.correct { color: var(--fm-text-primary); }

/* 인라인 스타일 금지 */
<div style="background: #000;">  <!-- 금지 -->
<div class="fm-card">            <!-- 올바름 -->

/* 라이트 모드 색상 금지 */
.wrong { background: white; }
.correct { background: var(--fm-bg-card); }
```

### ✅ 반드시 해야 할 것
1. CSS 변수 사용 (`--fm-*`)
2. 컴포넌트 클래스 사용 (`fm-*`)
3. 반응형 디자인 적용
4. 다크 테마 유지

---

## 📱 반응형 브레이크포인트

```css
/* Mobile First */
@media (min-width: 640px)  { /* sm */ }
@media (min-width: 768px)  { /* md */ }
@media (min-width: 1024px) { /* lg */ }
@media (min-width: 1280px) { /* xl */ }
```

---

## 🔗 서브도메인별 적용

| 서브도메인 | 배경 이미지 | 특이사항 |
|------------|------------|----------|
| data | fencer-bg.png | 기본 |
| club | fencer-bg.png | 클럽 대시보드 레이아웃 |
| shop | fencer-bg.png | 상품 그리드 추가 |
| community | fencer-bg.png | 포럼 레이아웃 추가 |
| blog | fencer-bg.png | 아티클 레이아웃 추가 |
| analytics | fencer-bg.png | 차트 스타일 추가 |

---

## 📋 체크리스트

새 페이지 만들 때:
- [ ] `variables.css` 임포트
- [ ] `base.css` 임포트
- [ ] `components.css` 임포트
- [ ] 배경 구조 (`fm-parallax-bg`, `fm-parallax-overlay`)
- [ ] 네비바 (`fm-navbar`)
- [ ] 컨테이너 (`fm-container`)
- [ ] 하드코딩 색상 없음
- [ ] 반응형 확인
