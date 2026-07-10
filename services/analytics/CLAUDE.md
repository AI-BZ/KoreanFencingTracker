# analytics.fencingmind.ai - AI 경기 분석

**서브도메인:** analytics.fencingmind.ai
**포트:** 76
**상태:** 📋 계획

---

## 서비스 개요
- 경기 영상 AI 분석
- 동작 패턴 인식
- 상대 전략 분석
- 훈련 개선 제안

## 수익 모델
- 기본 분석: $19.99/경기
- 프로 분석: $99/월 (무제한)
- 팀 라이선스: $499/월

---

## 폴더 구조
```
services/analytics/
├── api/                 # FastAPI API
├── video/               # 영상 처리
│   ├── upload/          # 업로드
│   ├── processing/      # 전처리
│   └── storage/         # 저장
├── ml/                  # ML 모델
│   ├── detection/       # 동작 감지
│   ├── classification/  # 기술 분류
│   └── prediction/      # 예측
├── reports/             # 리포트 생성
├── templates/           # 템플릿
├── static/              # 정적 파일
└── tests/               # 테스트
```

## 서버 실행
```bash
cd services/analytics
python -m uvicorn api.server:app --host 0.0.0.0 --port 76
```

---

## DB 테이블 (소유)
**이 서비스가 주인인 테이블:**
- `analytics_videos` - 업로드된 영상
- `analytics_analysis_jobs` - 분석 작업 큐
- `analytics_analysis_results` - 분석 결과
- `analytics_techniques` - 감지된 기술
- `analytics_player_metrics` - 선수별 메트릭
- `analytics_bout_reports` - 경기 리포트
- `analytics_training_plans` - AI 생성 훈련 계획
- `analytics_subscriptions` - 분석 서비스 구독
- `analytics_credits` - 크레딧 잔액

**공유 테이블 (참조만):**
- `members` - 회원 (공유)
- `players` - 선수 (프로필)
- `matches` - 경기 데이터 (data 서비스)

---

## 인증 연동
- **회원가입/로그인**: account.fencingmind.ai (port 70)에서 처리
- **JWT 검증**: `from shared_core.auth.jwt import get_current_member`
- **역할 확인**: `from shared_core.auth.dependencies import require_auth`
- **회원 관리 API 직접 구현 금지** — account 서비스만 담당

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/analytics/*` 브랜치에서만 수정

---

## 현재 상태
⚠️ 현재 영상 분석 코드는 `services/data/video/`에 있음
Phase 3에서 이 폴더로 분리 예정

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

### 분석 리포트 카드 예시
```html
<div class="fm-card">
    <div class="fm-card-header">
        <h3 class="fm-card-title">경기 분석 결과</h3>
        <span class="fm-badge fm-badge-success">분석 완료</span>
    </div>
    <div class="fm-card-body">
        <div class="fm-grid fm-grid-cols-3 fm-gap-4">
            <div class="fm-stat">
                <span class="fm-stat-value">78%</span>
                <span class="fm-stat-label">공격 성공률</span>
            </div>
            <div class="fm-stat">
                <span class="fm-stat-value">12</span>
                <span class="fm-stat-label">기술 패턴</span>
            </div>
            <div class="fm-stat">
                <span class="fm-stat-value">A+</span>
                <span class="fm-stat-label">종합 등급</span>
            </div>
        </div>
        <button class="fm-btn fm-btn-primary fm-btn-block">상세 리포트</button>
    </div>
</div>
```

---

## 기술 스택 (예정)
- **영상 처리**: OpenCV, FFmpeg
- **ML 프레임워크**: PyTorch, TensorFlow
- **객체 감지**: YOLO, MediaPipe (포즈 추정)
- **GPU**: CUDA (Mac에서는 Metal)
