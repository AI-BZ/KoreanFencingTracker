# 한국 펜싱 랭킹 시스템 설계서

## 1. 참고 시스템 분석

### FIE (국제펜싱연맹) 랭킹 시스템
- **대회 등급별 가중치**: 세계선수권 > 그랑프리 > 월드컵 > 지역대회
- **롤링 랭킹**: 12개월 기준 누적 점수
- **무기/성별 분리**: 플러레/에뻬/사브르 × 남/여 별도 랭킹

### USA Fencing 포인트 시스템
- **연령대별 최대 점수 차등화**:
  - Y10 SYC: 100점
  - Y12 SYC: 120점
  - Y14 SYC: 200점
  - Cadet NAC: 400점
  - Junior NAC: 600점
  - Senior NAC: 1,000점
- **Best N 결과 합산**: 상위 3~5개 대회 결과만 반영
- **Group I/II 분리**: 국내/국제 대회 별도 계산

---

## 2. 한국 펜싱 연령대 분류

| 코드 | 연령대 | 대상 | 비고 |
|------|--------|------|------|
| E1 | 초등 1-2 | 초등학교 1-2학년 | U8 (9세 이하) |
| E2 | 초등 3-4 | 초등학교 3-4학년 | U10 (11세 이하) |
| E3 | 초등 5-6 | 초등학교 5-6학년 | U12 (13세 이하) |
| MS | 중등 | 중학교 | U15 |
| HS | 고등 | 고등학교 | U18 |
| UNI | 대학 | 대학교 | U23 |
| SR | 일반 | 일반부/시니어 | Senior |

---

## 3. 대회 등급 분류

### 대회 등급 (Tier)
| 등급 | 대회 종류 | 기본 포인트 | 비고 |
|------|-----------|-------------|------|
| S | 전국체전, 회장배 전국대회 | 1000점 | 최상위 대회 |
| A | 전국선수권대회, 대학선수권 | 800점 | 주요 대회 |
| B | 시/도 대회, 연맹배 | 500점 | 지역 대회 |
| C | 클럽 대회, 오픈 대회 | 300점 | 일반 대회 |
| D | 인터내셔널 (국내 개최) | 400점 | 국제 교류전 |

### 대회명 → 등급 자동 분류 규칙
```python
def classify_competition_tier(name: str) -> str:
    if "전국체전" in name or "회장배" in name:
        return "S"
    elif "선수권" in name or "챔피언십" in name:
        return "A"
    elif any(x in name for x in ["시도대항", "협회장배"]):
        return "B"
    elif "인터내셔널" in name or "International" in name:
        return "D"
    else:
        return "C"
```

---

## 4. 점수 계산 시스템

### 4.1 순위별 포인트 비율
FIE 방식을 참고한 순위별 점수 배분 (기본 포인트 대비 %)

| 순위 | 포인트 비율 | 예시 (S등급 1000점) |
|------|-------------|---------------------|
| 1위 | 100% | 1000점 |
| 2위 | 80% | 800점 |
| 3위 | 65% | 650점 |
| 4위 | 55% | 550점 |
| 5-8위 | 40% | 400점 |
| 9-16위 | 25% | 250점 |
| 17-32위 | 15% | 150점 |
| 33-64위 | 8% | 80점 |
| 65위+ | 4% | 40점 |

### 4.2 참가자 수 보정 계수
참가자 수가 적을 경우 포인트 감소 (Strength Factor)

| 참가자 수 | 보정 계수 |
|-----------|-----------|
| 64명 이상 | 1.0 |
| 32-63명 | 0.9 |
| 16-31명 | 0.8 |
| 8-15명 | 0.6 |
| 8명 미만 | 0.4 |

### 4.3 연령대별 최대 포인트 가중치
연령대가 높을수록 더 많은 포인트 획득 가능

| 연령대 | 가중치 | S등급 최대 |
|--------|--------|------------|
| E1 (초등 1-2) | 0.4 | 400점 |
| E2 (초등 3-4) | 0.5 | 500점 |
| E3 (초등 5-6) | 0.6 | 600점 |
| MS (중등) | 0.7 | 700점 |
| HS (고등) | 0.8 | 800점 |
| UNI (대학) | 0.9 | 900점 |
| SR (일반) | 1.0 | 1000점 |

### 4.4 최종 포인트 공식
```
최종 포인트 = 기본 포인트 × 순위 비율 × 참가자 보정 × 연령대 가중치
```

**예시**: 대학부 전국선수권 (A등급, 800점) 3위, 참가자 50명
```
= 800 × 0.65 × 0.9 × 0.9
= 421.2점
```

---

## 5. 랭킹 계산 방식

### 5.1 Rolling Points (롤링 포인트)
- **기간**: 최근 12개월
- **집계 방식**: Best 4 (상위 4개 대회 결과 합산)
- **갱신 주기**: 대회 종료 후 즉시 반영

### 5.2 시즌 포인트
- **기간**: 1월 1일 ~ 12월 31일
- **집계 방식**: Best 5 (상위 5개 대회 결과 합산)
- **용도**: 연간 시상, 대표 선발 기준

### 5.3 연령대별 별도 랭킹
각 연령대 × 무기 × 성별 조합별 독립 랭킹
```
총 랭킹 수 = 7개 연령대 × 3개 무기 × 2개 성별 = 42개 랭킹
```

### 5.4 동점자 처리
1. 1위 횟수
2. 2위 횟수
3. 3위 횟수
4. 대회 참가 수
5. 최근 대회 순위

---

## 6. 데이터 스키마

### 6.1 랭킹 테이블
```sql
CREATE TABLE rankings (
    id SERIAL PRIMARY KEY,
    player_id INT REFERENCES players(id),

    -- 분류
    weapon VARCHAR(20),           -- 플러레, 에뻬, 사브르
    gender VARCHAR(10),           -- 남, 여
    age_group VARCHAR(10),        -- E1, E2, E3, MS, HS, UNI, SR

    -- 랭킹 정보
    rank_type VARCHAR(20),        -- rolling, season, all_time
    season_year INT,              -- 시즌 연도 (NULL for rolling)

    -- 점수
    total_points DECIMAL(10,2),
    best_results JSONB,           -- [{event_id, points, rank, date}]

    -- 순위
    current_rank INT,
    previous_rank INT,
    rank_change INT,              -- 순위 변동 (+/-)

    -- 통계
    competitions_count INT,
    gold_count INT,
    silver_count INT,
    bronze_count INT,
    win_rate DECIMAL(5,2),

    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(player_id, weapon, gender, age_group, rank_type, season_year)
);
```

### 6.2 대회 포인트 테이블
```sql
CREATE TABLE competition_points (
    id SERIAL PRIMARY KEY,
    event_id INT REFERENCES events(id),
    player_id INT REFERENCES players(id),

    -- 대회 정보
    competition_date DATE,
    tier VARCHAR(5),              -- S, A, B, C, D

    -- 점수 계산
    base_points INT,
    rank_ratio DECIMAL(5,2),
    participant_factor DECIMAL(3,2),
    age_factor DECIMAL(3,2),
    final_points DECIMAL(10,2),

    -- 순위 정보
    final_rank INT,
    total_participants INT,

    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 7. 연령대 자동 분류 로직

### 종목명에서 연령대 추출
```python
def extract_age_group(event_name: str) -> str:
    """종목명에서 연령대 코드 추출"""

    # 초등 저학년 (1-2학년)
    if any(x in event_name for x in ["9세이하", "U9", "초1", "초2"]):
        return "E1"

    # 초등 중학년 (3-4학년)
    if any(x in event_name for x in ["11세이하", "U11", "초3", "초4"]):
        return "E2"

    # 초등 고학년 (5-6학년)
    if any(x in event_name for x in ["13세이하", "U13", "초5", "초6", "초등"]):
        return "E3"

    # 중등
    if any(x in event_name for x in ["중등", "중학", "U15"]):
        return "MS"

    # 고등
    if any(x in event_name for x in ["고등", "고교", "U17", "U18"]):
        return "HS"

    # 대학
    if any(x in event_name for x in ["대학", "대", "U20", "U23"]):
        return "UNI"

    # 일반
    if any(x in event_name for x in ["일반", "시니어", "Senior"]):
        return "SR"

    return "SR"  # 기본값: 일반부
```

---

## 8. API 엔드포인트 설계

### 랭킹 조회
```
GET /api/rankings
    ?weapon=플러레
    &gender=남
    &age_group=UNI
    &type=rolling|season
    &year=2024
    &limit=50
    &page=1
```

### 선수 랭킹 상세
```
GET /api/player/{name}/rankings
    → 해당 선수의 모든 랭킹 정보 (연령대별, 무기별)
```

### 랭킹 변동 이력
```
GET /api/rankings/history
    ?player_id=123
    &period=1y
```

---

## 9. 구현 우선순위

### Phase 1: 기본 랭킹 (MVP)
1. [x] 순위별 포인트 계산
2. [ ] 대회 등급 자동 분류
3. [ ] 연령대 자동 추출
4. [ ] Rolling Points 계산
5. [ ] 기본 랭킹 테이블 생성

### Phase 2: 고급 기능
6. [ ] 참가자 수 보정 계수
7. [ ] 동점자 처리 로직
8. [ ] 랭킹 변동 추적
9. [ ] 시즌 포인트

### Phase 3: 시각화
10. [ ] 랭킹 차트 (추이 그래프)
11. [ ] Head-to-Head 비교
12. [ ] 대회별 포인트 분석

---

## 10. 예시 시나리오

### 선수 A의 2024 시즌 롤링 포인트
```
대학부 남자 플러레 랭킹

대회 이력 (최근 12개월):
1. 전국대학선수권 1위 → 800 × 1.0 × 1.0 × 0.9 = 720점
2. 회장배 전국대회 3위 → 1000 × 0.65 × 0.9 × 0.9 = 526점
3. 시도대항 2위 → 500 × 0.80 × 0.8 × 0.9 = 288점
4. 인터내셔널 5위 → 400 × 0.40 × 1.0 × 0.9 = 144점
5. 클럽대회 1위 → 300 × 1.0 × 0.6 × 0.9 = 162점

Best 4 합계: 720 + 526 + 288 + 162 = 1,696점
```
