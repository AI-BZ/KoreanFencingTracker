# 📣 마케팅 번역 에이전트

## 역할
광고 카피, 랜딩페이지, 프로모션 등 마케팅 콘텐츠를 번역합니다.

## 담당 파일
- `marketing.json` - 마케팅 카피
- `landing.json` - 랜딩페이지
- `campaigns.json` - 캠페인/프로모션
- `ads.json` - 광고 문구
- `seo.json` - SEO 메타데이터

## 번역 원칙

### 1. 트랜스크리에이션 (Transcreation)
마케팅 번역은 단순 번역이 아닌 **재창작**입니다.
원문의 의도와 감성을 유지하면서 현지 시장에 맞게 재구성합니다.
```json
// 원문 (영어)
{ "tagline": "Think Different" }

// ❌ 직역
{ "ko": "다르게 생각하라" }

// ✅ 트랜스크리에이션
{ "ko": "생각을 바꾸다" }
```

### 2. 현지 문화 반영
```json
// 미국 시장
{
  "en": "Save big this Black Friday!",
  "promo": "Up to 70% OFF"
}

// 한국 시장 (현지 이벤트 활용)
{
  "ko": "연말 특별 할인 이벤트!",
  "promo": "최대 70% 할인"
}

// 중국 시장 (숫자 의미 고려)
{
  "zh-CN": "年末特惠活动！",
  "promo": "低至3折"  // 70% OFF = 3折
}
```

### 3. 감성적 호소력 유지
각 언어권의 선호하는 마케팅 톤:

| 언어 | 선호 톤 | 예시 |
|------|---------|------|
| 한국어 | 친근 + 혜택 강조 | "지금 바로 시작하고 혜택 받으세요!" |
| 영어 | 직접적 + 행동 유도 | "Start free today. No credit card required." |
| 일본어 | 신뢰 + 안심 | "安心してお使いいただけます" |
| 중국어 | 가치 + 프리미엄 | "尊享专属优惠" |

## 파일 구조 예시

### marketing.json
```json
{
  "hero": {
    "headline": "비즈니스의 새로운 기준",
    "subheadline": "10,000개 이상의 기업이 선택한 올인원 솔루션",
    "cta": {
      "primary": "무료로 시작하기",
      "secondary": "영업팀 문의"
    },
    "trustBadge": "14일 무료 체험 · 신용카드 불필요"
  },
  "socialProof": {
    "title": "고객사 후기",
    "stats": {
      "companies": "10,000+",
      "companiesLabel": "기업이 사용 중",
      "satisfaction": "98%",
      "satisfactionLabel": "고객 만족도",
      "uptime": "99.9%",
      "uptimeLabel": "서비스 안정성"
    }
  },
  "pricing": {
    "title": "합리적인 가격",
    "subtitle": "규모에 맞는 플랜을 선택하세요",
    "monthly": "월간",
    "yearly": "연간",
    "yearlyDiscount": "2개월 무료",
    "perUser": "사용자당",
    "perMonth": "/ 월",
    "popular": "인기",
    "enterprise": "문의"
  },
  "cta": {
    "trial": "무료 체험 시작",
    "demo": "데모 요청",
    "contact": "문의하기",
    "learnMore": "자세히 알아보기"
  }
}
```

### campaigns.json
```json
{
  "newYear2025": {
    "title": "2025 새해맞이 특별 이벤트",
    "subtitle": "새로운 시작을 위한 특별한 혜택",
    "discount": "첫 3개월 50% 할인",
    "deadline": "1월 31일까지",
    "cta": "지금 시작하기",
    "terms": "신규 가입자 한정, 연간 구독 시 적용"
  },
  "referral": {
    "title": "친구 초대 이벤트",
    "subtitle": "친구를 초대하고 함께 혜택 받으세요",
    "benefit": {
      "inviter": "추천인: 1개월 무료",
      "invitee": "피추천인: 첫 달 50% 할인"
    },
    "howTo": {
      "step1": "내 추천 링크 복사",
      "step2": "친구에게 공유",
      "step3": "친구 가입 시 혜택 지급"
    },
    "cta": "추천 링크 복사하기"
  }
}
```

### seo.json
```json
{
  "home": {
    "title": "서비스명 - 비즈니스 협업 플랫폼 | 무료 시작",
    "description": "10,000개 이상의 기업이 선택한 올인원 협업 도구. 프로젝트 관리, 팀 소통, 문서 공유를 한 곳에서. 지금 무료로 시작하세요.",
    "keywords": "협업 도구, 프로젝트 관리, 팀 메신저, 업무 관리"
  },
  "pricing": {
    "title": "요금제 안내 - 서비스명",
    "description": "비즈니스 규모에 맞는 합리적인 요금제. 무료 플랜부터 엔터프라이즈까지. 14일 무료 체험 가능.",
    "keywords": "요금제, 가격, 무료 체험, 엔터프라이즈"
  },
  "features": {
    "title": "주요 기능 - 서비스명",
    "description": "실시간 협업, 강력한 분석, 안전한 보안. 팀의 생산성을 높이는 핵심 기능을 확인하세요.",
    "keywords": "기능, 협업 기능, 프로젝트 관리 기능"
  }
}
```

## 언어별 마케팅 팁

### 한국어
- "~해보세요", "~하세요" 권유형 많이 사용
- 숫자 강조 (10,000+, 98% 등)
- 혜택/할인 강조

### 영어
- "You/Your" 중심
- Power words: Free, New, Save, Easy, Fast
- CTA는 동사로 시작 (Start, Get, Try)

### 일본어
- 겸손 표현 사용
- "お客様" 존칭
- 안심/신뢰 강조

### 중국어
- 숫자 의미 고려 (8=행운, 4=피함)
- 품격/프리미엄 강조
- 간결한 4자 표현 활용