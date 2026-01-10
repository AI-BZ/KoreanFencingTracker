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

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/blog/*` 브랜치에서만 수정

---

## 데이터 연동 (핵심 차별점)
- **선수 프로필 연동**: 인터뷰 시 선수 데이터 자동 삽입
- **대회 리뷰 연동**: 대회 결과 데이터 자동 가져오기
- **SEO 최적화**: 선수 이름, 대회명으로 검색 유입
