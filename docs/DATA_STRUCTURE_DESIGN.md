# 데이터 수집 구조 설계서

## 1. 참고 사이트 분석 요약

### FencingTracker (fencingtracker.com)
- 선수 강도(strength) 평가 시스템
- 장기/단기 추세 그래프
- 클럽별 랭킹
- 생년도별 펜서 목록 (대학 리크루팅용)
- 토너먼트 등록 목록, 풀 정보

### FencingTimeLive (fencingtimelive.com)
- 대회 유형 필터링 (FIE/국가/지역/지방)
- 시간별 필터 (30일, 10일, 진행 중, 향후 7일)
- 다국어 지원

### FIE 공식 (fie.org)
- 선수 프로필: ID, 이름, 국가, 출생일, 무기, 성별, 레벨, 키, 손잡이
- 시즌별 랭킹, 포인트
- Head-to-Head 통계
- 메달 기록

---

## 2. 대한펜싱협회 사이트 데이터 구조

### 수집 가능 데이터

#### 대회 목록 페이지 (/game/compList)
- 번호, 대회명, 대회기간, 상태 (예정/진행중/종료)
- 구분 필터 (전문/동호인)

#### 대회 상세 페이지 (/game/compListView)
- 탭: 참가요강, 대진표, 경기결과
- 대회 정보: 진행상태, 구분, 대회명, 대회기간, 참가신청기간, 개최지

#### 종목 (SELECT 드롭다운)
- 형식: "남대 플러레(개)", "여대 에뻬(단)" 등
- 구성: 성별 + 카테고리 + 무기 + 개인/단체

#### 경기결과 탭
**풀 라운드 정보:**
- 뿔 번호, 삐스트(피스트), 시간, 심판
- 회전 선택 (뿔 1회전, 뿔 2회전...)

**풀 결과 테이블:**
| 컬럼 | 설명 | 예시 |
|------|------|------|
| No | 풀 내 번호 | 1-7 |
| 이름 | 선수명 | 김시우 |
| 소속팀 | 팀/학교명 | 호원대학교 |
| 1-7 | 상대방별 점수 | V (승리 5점), 숫자 (득점) |
| 승률 | 승/패 | 4/6 |
| 지수 | 득실차 | 11, -7 |
| 득점 | 총 득점 | 26 |
| 랭킹 | 풀 내 순위 | 1-7 |

#### 엘리미나시옹디렉트 탭
**최종 순위 테이블:**
| 컬럼 | 설명 |
|------|------|
| 순위 | 1위, 2위, 3위... |
| 이름 | 선수명 |
| 소속팀 | 팀명 |

---

## 3. 데이터베이스 스키마 설계

### 3.1 선수 테이블 (players)
```sql
CREATE TABLE players (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    team VARCHAR(200),
    -- 고유 식별: 이름 + 팀 조합
    UNIQUE(name, team),

    -- 통계 (계산됨)
    main_weapon VARCHAR(20),           -- 주 종목 (플러레/에뻬/사브르)
    total_competitions INT DEFAULT 0,  -- 참가 대회 수
    total_events INT DEFAULT 0,        -- 참가 종목 수

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 3.2 대회 테이블 (competitions)
```sql
CREATE TABLE competitions (
    id SERIAL PRIMARY KEY,
    event_cd VARCHAR(50) UNIQUE NOT NULL,  -- COMPM00673
    name VARCHAR(500) NOT NULL,
    start_date DATE,
    end_date DATE,
    status VARCHAR(20),      -- 예정, 진행중, 종료
    location VARCHAR(200),
    category VARCHAR(20),    -- 전문, 동호인

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 3.3 종목 테이블 (events)
```sql
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    competition_id INT REFERENCES competitions(id),
    sub_event_cd VARCHAR(50) UNIQUE NOT NULL,  -- COMPS000000000003260
    name VARCHAR(200) NOT NULL,                -- "남대 플러레(개)"
    weapon VARCHAR(20),       -- 플러레, 에뻬, 사브르
    gender VARCHAR(10),       -- 남, 여
    event_type VARCHAR(20),   -- 개인, 단체
    age_group VARCHAR(50),    -- U9, U11, U13, U17, U20, 대, 일반

    total_participants INT DEFAULT 0,

    created_at TIMESTAMP DEFAULT NOW()
);
```

### 3.4 풀 라운드 테이블 (pool_rounds)
```sql
CREATE TABLE pool_rounds (
    id SERIAL PRIMARY KEY,
    event_id INT REFERENCES events(id),
    round_number INT NOT NULL,      -- 1회전, 2회전
    pool_number INT NOT NULL,       -- 풀 1, 풀 2...
    piste VARCHAR(20),              -- 삐스트 번호
    match_time TIMESTAMP,           -- 경기 시간
    referee VARCHAR(100),           -- 심판명

    UNIQUE(event_id, round_number, pool_number)
);
```

### 3.5 풀 결과 테이블 (pool_results)
```sql
CREATE TABLE pool_results (
    id SERIAL PRIMARY KEY,
    pool_round_id INT REFERENCES pool_rounds(id),
    player_id INT REFERENCES players(id),

    pool_position INT,        -- 풀 내 번호 (1-7)
    wins INT DEFAULT 0,       -- 승리 수
    losses INT DEFAULT 0,     -- 패배 수
    win_rate VARCHAR(10),     -- "4/6"
    indicator INT,            -- 지수 (득실차)
    touches_scored INT,       -- 득점
    pool_rank INT,            -- 풀 내 순위

    UNIQUE(pool_round_id, player_id)
);
```

### 3.6 풀 개별 경기 테이블 (pool_bouts)
```sql
-- 풀 라운드 내 개별 경기 (Head-to-Head 계산용)
CREATE TABLE pool_bouts (
    id SERIAL PRIMARY KEY,
    pool_round_id INT REFERENCES pool_rounds(id),

    player1_id INT REFERENCES players(id),
    player2_id INT REFERENCES players(id),
    player1_score INT,        -- 선수1 득점
    player2_score INT,        -- 선수2 득점
    winner_id INT REFERENCES players(id),

    UNIQUE(pool_round_id, player1_id, player2_id)
);
```

### 3.7 최종 순위 테이블 (final_rankings)
```sql
CREATE TABLE final_rankings (
    id SERIAL PRIMARY KEY,
    event_id INT REFERENCES events(id),
    player_id INT REFERENCES players(id),

    final_rank INT NOT NULL,  -- 최종 순위

    UNIQUE(event_id, player_id)
);
```

---

## 4. 계산 뷰 (Views)

### 4.1 선수 Head-to-Head 통계
```sql
CREATE VIEW player_head_to_head AS
SELECT
    player1_id,
    player2_id,
    COUNT(*) as total_bouts,
    SUM(CASE WHEN winner_id = player1_id THEN 1 ELSE 0 END) as player1_wins,
    SUM(CASE WHEN winner_id = player2_id THEN 1 ELSE 0 END) as player2_wins,
    ROUND(
        SUM(CASE WHEN winner_id = player1_id THEN 1 ELSE 0 END)::DECIMAL / COUNT(*) * 100,
        1
    ) as player1_win_rate
FROM pool_bouts
GROUP BY player1_id, player2_id;
```

### 4.2 선수 종합 통계
```sql
CREATE VIEW player_stats AS
SELECT
    p.id,
    p.name,
    p.team,
    COUNT(DISTINCT e.competition_id) as competitions,
    COUNT(DISTINCT pr.id) as events,

    -- 메달 집계
    SUM(CASE WHEN fr.final_rank = 1 THEN 1 ELSE 0 END) as gold,
    SUM(CASE WHEN fr.final_rank = 2 THEN 1 ELSE 0 END) as silver,
    SUM(CASE WHEN fr.final_rank = 3 THEN 1 ELSE 0 END) as bronze,

    -- 평균 성적
    AVG(fr.final_rank) as avg_rank,

    -- 승률 계산
    SUM(pr2.wins) as total_wins,
    SUM(pr2.losses) as total_losses,
    ROUND(
        SUM(pr2.wins)::DECIMAL / NULLIF(SUM(pr2.wins) + SUM(pr2.losses), 0) * 100,
        1
    ) as overall_win_rate

FROM players p
LEFT JOIN final_rankings fr ON p.id = fr.player_id
LEFT JOIN events e ON fr.event_id = e.id
LEFT JOIN pool_results pr2 ON p.id = pr2.player_id
LEFT JOIN pool_rounds prnd ON pr2.pool_round_id = prnd.id
GROUP BY p.id, p.name, p.team;
```

### 4.3 라이벌 찾기 함수
```sql
CREATE FUNCTION find_rivals(target_player_id INT, min_bouts INT DEFAULT 3)
RETURNS TABLE (
    opponent_id INT,
    opponent_name VARCHAR,
    opponent_team VARCHAR,
    total_bouts INT,
    wins INT,
    losses INT,
    win_rate DECIMAL
) AS $$
SELECT
    p2.id,
    p2.name,
    p2.team,
    h2h.total_bouts,
    h2h.player1_wins as wins,
    h2h.player2_wins as losses,
    h2h.player1_win_rate as win_rate
FROM player_head_to_head h2h
JOIN players p2 ON h2h.player2_id = p2.id
WHERE h2h.player1_id = target_player_id
  AND h2h.total_bouts >= min_bouts
ORDER BY h2h.player2_wins DESC, h2h.total_bouts DESC
LIMIT 10;
$$ LANGUAGE SQL;
```

---

## 5. 수집 우선순위

### Phase 1: 기본 데이터 (필수)
1. **대회 목록** - competitions
2. **종목 목록** - events
3. **최종 순위** - final_rankings
4. **선수 정보** - players (이름 + 팀)

### Phase 2: 상세 데이터 (중요)
5. **풀 라운드 정보** - pool_rounds
6. **풀 결과** - pool_results

### Phase 3: 분석 데이터 (선택)
7. **풀 개별 경기** - pool_bouts (Head-to-Head용)

---

## 6. 스크래퍼 수정 사항

### 현재 스크래퍼 문제점
1. `PoolResult`가 요약만 수집 (개별 점수 매트릭스 누락)
2. `_parse_de_results()` 미완성 (빈 배열)
3. `_parse_final_rankings()` 미완성 (모달 찾기 실패)
4. 선수 테이블 없음 (중복 처리 불가)

### 수정 계획
1. **풀 결과 파싱 개선**: V/숫자 점수 매트릭스 파싱
2. **최종 순위 파싱**: 엘리미나시옹디렉트 탭에서 추출
3. **선수 정규화**: 이름+팀 조합으로 고유 ID 부여
4. **Head-to-Head 계산**: 풀 점수 매트릭스에서 개별 경기 추출

---

## 7. 테스트 계획

### 테스트 대회 선정
- 최근 종료 대회 1개 (2025년)
- 다양한 종목 포함 대회 선택

### 검증 항목
1. 모든 종목 수집 확인
2. 풀 결과 점수 정확성
3. 최종 순위 완전성
4. 선수 중복 처리

### 예상 데이터량 (대회당)
- 종목: 12-42개
- 선수: 50-500명
- 풀 라운드: 종목당 5-20개
- 최종 순위: 종목당 10-100개

---

## 8. JSON 출력 구조

```json
{
  "meta": {
    "scraped_at": "2025-12-16T10:00:00",
    "version": "2.0"
  },
  "competitions": [
    {
      "event_cd": "COMPM00673",
      "name": "제26회 전국남녀대학펜싱선수권대회",
      "start_date": "2025-11-25",
      "end_date": "2025-11-28",
      "status": "종료",
      "location": "해남우슬체육관",
      "category": "전문",
      "events": [
        {
          "sub_event_cd": "COMPS000000000003260",
          "name": "남대 플러레(개)",
          "weapon": "플러레",
          "gender": "남",
          "event_type": "개인",
          "total_participants": 49,
          "pool_rounds": [
            {
              "round_number": 1,
              "pools": [
                {
                  "pool_number": 1,
                  "piste": "6",
                  "time": "25일 09:30",
                  "referee": "성상욱",
                  "results": [
                    {
                      "position": 1,
                      "name": "김시우",
                      "team": "호원대학교",
                      "scores": [null, "V", 4, "V", "V", 2, "V"],
                      "wins": 4,
                      "losses": 2,
                      "indicator": 11,
                      "touches": 26,
                      "rank": 1
                    }
                  ],
                  "bouts": [
                    {
                      "player1": "김시우",
                      "player2": "김명현",
                      "score1": 5,
                      "score2": 0,
                      "winner": "김시우"
                    }
                  ]
                }
              ]
            }
          ],
          "final_rankings": [
            {"rank": 1, "name": "서예찬", "team": "경남대학교"},
            {"rank": 2, "name": "임혜성", "team": "경남대학교"},
            {"rank": 3, "name": "김시우", "team": "호원대학교"},
            {"rank": 3, "name": "정현", "team": "호원대학교"}
          ]
        }
      ]
    }
  ],
  "players": [
    {
      "id": 1,
      "name": "김시우",
      "team": "호원대학교",
      "competitions": 5,
      "events": 12,
      "gold": 1,
      "silver": 2,
      "bronze": 1
    }
  ]
}
```

---

## 9. 다음 단계

1. [x] 참고 사이트 분석
2. [x] 데이터 구조 설계
3. [ ] 스크래퍼 수정 (pool_bouts, final_rankings)
4. [ ] 테스트 스크래핑 (1개 대회)
5. [ ] 결과 검증
6. [ ] 전체 데이터 수집 (2019년 이후)
