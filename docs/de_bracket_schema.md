# DE Bracket Data Schema (v2)

## 설계 원칙
1. **경기 중심 구조**: 개별 선수가 아닌 경기(bout) 단위로 데이터 저장
2. **완전한 매치 정보**: 모든 경기는 반드시 두 선수 정보를 포함
3. **라운드 기반 정렬**: 라운드는 DOM 위치나 라운드 헤더로 결정 (매치 개수 추론 금지)
4. **브래킷 재구성 가능**: 시드 정보와 경기 결과로 전체 브래킷 트리 재구성 가능

## 새로운 데이터 구조

```python
DEBracket = {
    # 메타데이터
    "bracket_size": int,          # 8, 16, 32, 64, 128 (시작 라운드 결정)
    "participant_count": int,     # 실제 참가자 수
    "starting_round": str,        # "128강", "64강", "32강", "16강", "8강"

    # 시드 배정 (초기 대진)
    "seeding": [
        {
            "seed": int,          # 시드 번호 (1-128)
            "player_id": str,     # 선수 ID (있으면)
            "name": str,          # 선수 이름
            "team": str,          # 소속
            "nation": str         # 국가 코드 (국제대회용)
        }
    ],

    # 라운드 목록 (진행 순서대로)
    "rounds": ["64강", "32강", "16강", "8강", "준결승", "결승"],

    # 경기 결과 (핵심!)
    "bouts": [
        {
            "bout_id": str,       # "R64_M01" 형식 (라운드_경기번호)
            "round": str,         # "64강", "32강", etc.
            "round_order": int,   # 라운드 순서 (1=첫라운드, 6=결승)
            "match_number": int,  # 해당 라운드 내 경기 번호 (1-32)
            "bracket_position": int,  # 브래킷 내 위치 (트리 재구성용)

            # 선수1 (상단/시드가 높은 쪽)
            "player1": {
                "seed": int,
                "name": str,
                "team": str,
                "score": int      # 최종 점수
            },

            # 선수2 (하단/시드가 낮은 쪽)
            "player2": {
                "seed": int,
                "name": str,
                "team": str,
                "score": int
            },

            # 결과
            "winner_seed": int,   # 승자의 시드 번호
            "winner_name": str,   # 승자 이름
            "is_completed": bool, # 경기 완료 여부
            "is_bye": bool        # 부전승 여부
        }
    ],

    # 라운드별 경기 그룹 (조회 편의용)
    "bouts_by_round": {
        "64강": [bout, bout, ...],
        "32강": [bout, bout, ...],
        # ...
    },

    # 최종 순위
    "final_ranking": [
        {"rank": 1, "seed": int, "name": str, "team": str},
        {"rank": 2, "seed": int, "name": str, "team": str},
        {"rank": 3, "seed": int, "name": str, "team": str},
        {"rank": 3, "seed": int, "name": str, "team": str},
        # ...
    ]
}
```

## 라운드 정의

| 라운드명 | 영문 | 경기 수 | round_order |
|---------|------|--------|-------------|
| 128강 | Round of 128 | 64 | 1 |
| 64강 | Round of 64 | 32 | 2 |
| 32강 | Round of 32 | 16 | 3 |
| 16강 | Round of 16 | 8 | 4 |
| 8강 | Quarterfinals | 4 | 5 |
| 준결승 | Semifinals | 2 | 6 |
| 3-4위 | Third Place | 1 | 7 |
| 결승 | Final | 1 | 8 |

## 브래킷 크기 결정 로직

```python
def get_bracket_size(participant_count: int) -> int:
    """참가자 수에 따른 브래킷 크기 결정"""
    sizes = [8, 16, 32, 64, 128]
    for size in sizes:
        if participant_count <= size:
            return size
    return 128  # 최대값

def get_starting_round(bracket_size: int) -> str:
    """브래킷 크기에 따른 시작 라운드"""
    mapping = {
        8: "8강",
        16: "16강",
        32: "32강",
        64: "64강",
        128: "128강"
    }
    return mapping.get(bracket_size, "32강")
```

## bout_id 생성 규칙

```
{Round}_{MatchNumber:02d}
예시:
- R128_M01: 128강 1번 경기
- R64_M32: 64강 32번 경기
- R32_M01: 32강 1번 경기
- QF_M01: 8강 1번 경기
- SF_M01: 준결승 1번 경기
- F_M01: 결승
- TP_M01: 3-4위전
```

## 라운드 감지 방법 (스크래퍼)

### 1. 라운드 헤더 기반 (권장)
```javascript
// DOM에서 "N 엘리미나시옹디렉트" 텍스트 찾기
// 예: "64 엘리미나시옹디렉트" → 64강
const headerCells = document.querySelectorAll('table td');
headerCells.forEach(cell => {
    const match = cell.textContent.match(/(\d+)\s*엘리미나시옹디렉트/);
    if (match) {
        currentRound = getRoundName(parseInt(match[1]));
    }
});
```

### 2. 탭 기반 (보조)
```javascript
// 탭에서 라운드 정보 추출
const tabs = document.querySelectorAll('ul li a');
tabs.forEach(tab => {
    const text = tab.textContent.trim();
    if (text.match(/\d+강전|준결승|결승/)) {
        rounds.push(text.replace('전', ''));
    }
});
```

### 3. 시각적 위치 기반 (최후 수단)
- 좌측에서 우측으로 진행하는 브래킷 구조
- 각 컬럼이 하나의 라운드

## 경기 매칭 로직

```python
def pair_players_to_bouts(players_in_round: List, round_name: str) -> List[Bout]:
    """
    연속된 두 선수를 하나의 경기로 매칭
    - 인접한 2명이 같은 경기
    - 상단 선수 = player1, 하단 선수 = player2
    - 점수가 있는 선수 = 승자
    """
    bouts = []
    for i in range(0, len(players_in_round), 2):
        p1 = players_in_round[i]
        p2 = players_in_round[i + 1] if i + 1 < len(players_in_round) else None

        bout = create_bout(p1, p2, round_name, match_number=i//2 + 1)
        bouts.append(bout)

    return bouts
```

## 마이그레이션 전략

### 기존 데이터 변환
```python
def migrate_old_de_data(old_data: dict) -> DEBracket:
    """
    기존 results_by_round 형식을 새 구조로 변환
    - 개별 선수 레코드 → 경기 쌍으로 그룹화
    - table_index로 경기 매칭
    - 점수로 승자/패자 구분
    """
    pass
```

### 스크래퍼 수정
1. 라운드 헤더("N 엘리미나시옹디렉트") 기반 라운드 감지
2. 각 라운드 내에서 2명씩 경기 매칭
3. 점수가 있는 선수 = 승자
4. 모든 라운드(128강~결승)를 순회하며 수집

## 검증 체크리스트

- [ ] 모든 경기가 두 선수 정보를 포함하는가?
- [ ] 준결승과 결승 데이터가 포함되는가?
- [ ] 라운드 순서가 올바른가? (64강 → 32강 → ... → 결승)
- [ ] 승자/패자가 정확히 구분되는가?
- [ ] 브래킷 트리를 재구성할 수 있는가?
- [ ] 시드 정보가 일관성 있는가?
