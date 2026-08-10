# community.fencingmind.ai - 커뮤니티

**서브도메인:** community.fencingmind.ai
**포트:** 73
**상태:** 📋 계획

---

## 서비스 개요
- 포럼 (기술 토론, 용품 리뷰)
- Q&A (코치/선수 연결)
- 이벤트 게시판
- 구인/구직

## 수익 모델
- 광고: $500~2,000/월
- 프리미엄 멤버십: $4.99/월 (광고 없음, 고급 기능)
- 구인 게시: $50~200/건

---

## 폴더 구조
```
services/community/
├── api/                 # FastAPI API
├── forum/               # 포럼
│   ├── boards/          # 게시판
│   ├── posts/           # 게시글
│   └── comments/        # 댓글
├── qna/                 # Q&A
├── templates/           # 템플릿
├── static/              # 정적 파일
└── tests/               # 테스트
```

## 서버 실행
```bash
cd services/community
python -m uvicorn api.server:app --host 0.0.0.0 --port 73
```

---

## DB 테이블 (소유)
**이 서비스가 주인인 테이블:**
- `community_forums` - 포럼 게시판
- `community_posts` - 게시글
- `community_comments` - 댓글
- `community_reactions` - 반응 (좋아요)
- `community_tags` - 태그
- `community_post_tags` - 게시글-태그
- `community_reports` - 신고
- `community_user_badges` - 뱃지/레벨
- `community_moderators` - 운영자

**공유 테이블 (참조만):**
- `members` - 회원 (공유)
- `players` - 선수 (공유)

---

## 인증 연동
- **회원가입/로그인**: account.fencingmind.ai (port 70)에서 처리
- **JWT 검증**: `from shared_core.auth.jwt import get_current_member`
- **역할 확인**: `from shared_core.auth.dependencies import require_auth`
- **회원 관리 API 직접 구현 금지** — account 서비스만 담당

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/community/*` 브랜치에서만 수정

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

### 포럼 게시글 예시
```html
<div class="fm-card">
    <div class="fm-card-header">
        <h3 class="fm-card-title">플뢰레 기술 질문</h3>
        <span class="fm-badge fm-badge-info">Q&A</span>
    </div>
    <div class="fm-card-body">
        <p class="fm-text-secondary">질문 내용...</p>
        <div class="fm-flex fm-gap-2">
            <button class="fm-btn fm-btn-ghost fm-btn-sm">좋아요</button>
            <button class="fm-btn fm-btn-ghost fm-btn-sm">댓글</button>
        </div>
    </div>
</div>
```
