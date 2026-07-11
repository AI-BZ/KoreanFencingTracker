# shop.fencingmind.ai - 드롭쉬핑

**서브도메인:** shop.fencingmind.ai
**포트:** 74
**상태:** 📋 계획

---

## 서비스 개요
- 펜싱 용품 큐레이션
- 중국 제조사 직접 연결 (AliExpress, Alibaba)
- 가격 비교 및 리뷰
- 맞춤형 장비 추천 (데이터 기반)

## 수익 모델
- 드롭쉬핑 마진: 15~30%
- 제휴 수수료: 5~10%
- 목표: 월 $10,000 매출 → $2,000 순이익

---

## 폴더 구조
```
services/shop/
├── api/                 # FastAPI API
├── products/            # 상품 관리
│   ├── catalog/         # 카탈로그
│   ├── reviews/         # 리뷰
│   └── recommendations/ # 추천
├── orders/              # 주문 관리
│   ├── checkout/        # 결제
│   └── tracking/        # 배송 추적
├── dropship/            # 드롭쉬핑 연동
│   ├── aliexpress/      # AliExpress API
│   └── alibaba/         # Alibaba API
├── templates/           # 템플릿
├── static/              # 정적 파일
└── tests/               # 테스트
```

## 서버 실행
```bash
cd services/shop
python -m uvicorn api.server:app --host 0.0.0.0 --port 74
```

---

## DB 테이블 (소유)
**이 서비스가 주인인 테이블:**
- `shop_products` - 상품
- `shop_product_variants` - 상품 옵션
- `shop_categories` - 카테고리
- `shop_suppliers` - 공급업체
- `shop_orders` - 주문
- `shop_order_items` - 주문 상세
- `shop_cart_items` - 장바구니
- `shop_reviews` - 상품 리뷰
- `shop_wishlists` - 찜 목록
- `shop_payments` - 결제

**공유 테이블 (참조만):**
- `members` - 회원 (공유)

---

## 인증 연동
- **회원가입/로그인**: account.fencingmind.ai (port 70)에서 처리
- **JWT 검증**: `from shared_core.auth.jwt import get_current_member`
- **역할 확인**: `from shared_core.auth.dependencies import require_auth`
- **회원 관리 API 직접 구현 금지** — account 서비스만 담당

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/shop/*` 브랜치에서만 수정

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

### 상품 카드 예시
```html
<div class="fm-card">
    <img src="..." alt="상품">
    <div class="fm-card-body">
        <h3 class="fm-card-title">플뢰레 블레이드</h3>
        <span class="fm-badge fm-badge-primary">베스트셀러</span>
        <p class="fm-text-secondary">$89.99</p>
        <button class="fm-btn fm-btn-primary">장바구니</button>
    </div>
</div>
```

---

## 데이터 연동 (핵심 차별점)
- **선수 데이터 활용**: 선수의 무기(플뢰레/에페/사브르), 레벨에 맞는 장비 추천
- **대회 일정 연동**: 대회 전 장비 교체 알림
- **클럽 대량 구매**: 클럽 단위 할인
