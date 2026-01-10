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

## Git 브랜치 규칙
- 이 서비스의 코드는 `feature/shop/*` 브랜치에서만 수정

---

## 데이터 연동 (핵심 차별점)
- **선수 데이터 활용**: 선수의 무기(플뢰레/에페/사브르), 레벨에 맞는 장비 추천
- **대회 일정 연동**: 대회 전 장비 교체 알림
- **클럽 대량 구매**: 클럽 단위 할인
