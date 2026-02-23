# data.fencingmind.ai - 펜싱 데이터 서비스

**서브도메인:** data.fencingmind.ai
**포트:** 71
**상태:** ✅ 운영 중 (메인 서비스)

---

## 서비스 개요
- 전 세계 펜싱 대회 결과 데이터베이스
- 선수 프로필 및 랭킹 시스템
- 클럽/코치 디렉토리
- API 제공 (B2B 데이터 판매)

## 수익 모델
- API 구독: $99~999/월 (이용량별)
- 데이터 라이선스: $5,000~50,000/년 (B2B)

## ⚠️ Auth 엔드포인트 이동 안내
auth 관련 엔드포인트(로그인, 회원가입, 인증, 프로필)는 **account.fencingmind.ai** (port 70)로 이동되었습니다.
이 서비스에서는 `shared_core.auth.jwt`로 JWT 검증만 수행합니다.

---

## 폴더 구조
```
services/data/
├── app/                 # FastAPI 웹 서버
│   ├── server.py        # 메인 서버
│   ├── auth/            # 인증 시스템
│   ├── club/            # 클럽 관리 (→ services/app/으로 분리 예정)
│   ├── i18n/            # 다국어 지원
│   └── player_*.py      # 선수 분석
├── scraper/             # 스크래퍼
├── ranking/             # 랭킹 계산
├── data_pipeline/       # 데이터 파이프라인
├── templates/           # Jinja2 템플릿
├── static/              # 정적 파일
├── scheduler/           # 자동 업데이트
└── video/               # 영상 분석 (→ services/analytics/로 분리 예정)
```

## 서버 실행
```bash
cd services/data
python -m uvicorn app.server:app --host 0.0.0.0 --port 71
```

---

## DB 테이블 (소유)
**이 서비스가 주인인 테이블:**
- `competitions` - 대회
- `events` - 종목
- `matches` - 경기
- `rankings` - 순위
- `scrape_logs` - 스크래핑 로그
- `data_events` - 데이터 이벤트
- `validation_logs` - 검증 로그

**공유 테이블 (참조만):**
- `members` - 회원 (공유)
- `players` - 선수 (공유)
- `organizations` - 조직 (공유)

---

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/data/*` 브랜치에서만 수정
- 다른 서비스 코드 수정 금지
- 공유 패키지 수정 시 `feature/shared/*` 브랜치 사용

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

### 랭킹 테이블 예시
```html
<div class="fm-card">
    <div class="fm-card-header">
        <h3 class="fm-card-title">남자 플뢰레 랭킹</h3>
    </div>
    <div class="fm-table-container">
        <table class="fm-table">
            <thead>
                <tr>
                    <th>순위</th>
                    <th>선수</th>
                    <th>소속</th>
                    <th>점수</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><span class="fm-badge fm-badge-gold">1</span></td>
                    <td>홍길동</td>
                    <td>최병철펜싱클럽</td>
                    <td>2,450</td>
                </tr>
            </tbody>
        </table>
    </div>
</div>
```

### 대회 카드 예시
```html
<div class="fm-card">
    <div class="fm-card-header">
        <h3 class="fm-card-title">2025 회장배 전국대회</h3>
        <span class="fm-badge fm-badge-info">진행 중</span>
    </div>
    <div class="fm-card-body">
        <p class="fm-text-secondary">2025.01.15 ~ 2025.01.17</p>
        <p class="fm-text-secondary">장소: 태릉선수촌</p>
        <button class="fm-btn fm-btn-primary">결과 보기</button>
    </div>
</div>
```
