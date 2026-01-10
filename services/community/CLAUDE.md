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

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/community/*` 브랜치에서만 수정
