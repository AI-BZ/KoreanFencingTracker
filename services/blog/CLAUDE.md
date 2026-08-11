# blog.fencingmind.ai - 콘텐츠

**서브도메인:** blog.fencingmind.ai
**포트:** 75
**상태:** 📋 계획

---

## 서비스 개요
- 펜싱 기술 가이드
- 선수 인터뷰
- 대회 리뷰
- 용품 테스트 및 리뷰
- YouTube 채널 연동

## 수익 모델
- 광고 수익: $500~3,000/월
- 스폰서 콘텐츠: $500~2,000/건
- 제휴 마케팅: $1,000~5,000/월

---

## 폴더 구조
```
services/blog/
├── api/                 # FastAPI API
├── articles/            # 아티클 관리
│   ├── editor/          # 에디터
│   ├── categories/      # 카테고리
│   └── series/          # 시리즈
├── cms/                 # CMS 관리
│   ├── authors/         # 작성자
│   └── media/           # 미디어
├── templates/           # 템플릿
├── static/              # 정적 파일
└── tests/               # 테스트
```

## 서버 실행
```bash
cd services/blog
python -m uvicorn api.server:app --host 0.0.0.0 --port 75
```

---

## DB 테이블 (소유)
**이 서비스가 주인인 테이블:**
- `blog_articles` - 아티클
- `blog_categories` - 카테고리
- `blog_article_categories` - 아티클-카테고리
- `blog_authors` - 작성자
- `blog_comments` - 댓글
- `blog_article_views` - 조회수
- `blog_article_likes` - 좋아요
- `blog_series` - 시리즈
- `blog_series_articles` - 시리즈-아티클

**공유 테이블 (참조만):**
- `members` - 회원 (공유)
- `players` - 선수 (프로필 참조)

---

## 인증 연동
- **회원가입/로그인**: account.fencingmind.ai (port 70)에서 처리
- **JWT 검증**: `from shared_core.auth.jwt import get_current_member`
- **역할 확인**: `from shared_core.auth.dependencies import require_auth`
- **회원 관리 API 직접 구현 금지** — account 서비스만 담당

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/blog/*` 브랜치에서만 수정

---

## 🎨 UI 디자인 규칙 (필수)

**📖 반드시 참조:** `packages/shared-ui/DESIGN_SYSTEM.md`

### 필수 CSS 임포트
```html
<link rel="stylesheet" href="/packages/shared-ui/styles/variables.css">
<link rel="stylesheet" href="/packages/shared-ui/styles/base.css">
<link rel="stylesheet" href="/packages/shared-ui/styles/components.css">
```

### 핵심 규칙
| 규칙 | 설명 |
|------|------|
| 🔴 **다크 모드만** | 라이트 모드 UI 금지 |
| 🔴 **CSS 변수 사용** | `--fm-*` 변수 필수 (하드코딩 색상 금지) |
| 🔴 **컴포넌트 클래스** | `fm-btn`, `fm-card`, `fm-input` 등 사용 |
| 🔴 **배경 구조** | `fm-parallax-bg` + `fm-parallax-overlay` |

### 색상 팔레트 (태극기 컬러)
```css
--fm-accent-primary: #c9302c;    /* 빨강 - Primary CTA */
--fm-accent-secondary: #1e3a8a;  /* 파랑 - Secondary */
--fm-bg-card: rgba(18, 18, 26, 0.85);  /* 글래스 카드 */
```

### 아티클 카드 예시
```html
<article class="fm-card">
    <img src="..." alt="썸네일" class="fm-card-image">
    <div class="fm-card-body">
        <span class="fm-badge fm-badge-info">기술 가이드</span>
        <h3 class="fm-card-title">플뢰레 공격 기술 분석</h3>
        <p class="fm-text-secondary">기술의 핵심 포인트와 연습 방법...</p>
        <div class="fm-flex fm-justify-between fm-items-center">
            <span class="fm-text-xs">2025.01.10</span>
            <button class="fm-btn fm-btn-ghost fm-btn-sm">더 읽기</button>
        </div>
    </div>
</article>
```

---

## 데이터 연동 (핵심 차별점)
- **선수 프로필 연동**: 인터뷰 시 선수 데이터 자동 삽입
- **대회 리뷰 연동**: 대회 결과 데이터 자동 가져오기
- **SEO 최적화**: 선수 이름, 대회명으로 검색 유입
