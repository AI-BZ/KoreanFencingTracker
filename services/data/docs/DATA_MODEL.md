# 데이터 모델 — 구조·스키마 일관성 (2026-09-28 감사)

실측만 적는다. 추측은 "미확인"으로 남긴다(CLAUDE.md 제0원칙). 재실행 가능한 확인
명령은 각 절에 있다.

---

## 1. `events.raw_data.de_bracket` — bout 저장 구조 규약

### 문제
한 브래킷 안에 같은 경기가 **여러 키에 중복 저장**되는 경우가 실제로 있다:
`full_bouts`(리스트), `bouts`(별칭 키), `bouts_by_round`(라운드별로 다시 펼친 파생 뷰).
소비 코드가 이 중 둘 이상을 **더하면**(합집합이 아니라 concatenation) 경기 수가
그대로 부풀어 오른다.

### 실제로 이 버그를 가진 코드 (2026-09-28 전수 조사)
```
grep -rn "full_bouts.*+.*bouts\b" scripts/
```
| 파일 | 위치 | 패턴 |
|---|---|---|
| `scripts/repair_collapsed_de.py` | `de_bouts()` (L54, L57) | `list(full_bouts) + list(bouts)`, sub-bracket도 동일 |
| `scripts/repair_computed_team_finals.py` | L92, L95 | 동일 패턴 |

`repair_collapsed_de.py` 자체 독스트링(②)이 "5명 대회의 브래킷이 46경기로 부풀고
그중 24경기가 복제" 사고를 실측으로 기록하고 있다 — 데이터 오염(옛 스크래퍼)과
이 함수의 concatenation 버그가 같은 증상(부풀려진 경기 수)을 만든다는 점에서
서로를 가리는 관계다. **이 두 파일은 내 편집 범위 밖**(scripts/ 는 audit-repair
담당)이라 고치지 않고 여기 보고한다.

### 안전한 코드 (참고용, 우선순위 OR 방식 — concatenation 아님)
- `app/de_transforms.py::_get_full_bouts_from_de_bracket` — `full_bouts` 우선,
  비어 있을 때만 `bouts_by_round` 폴백. dual_de 는 `first_de`/`second_de` 로
  재귀하고 최상위는 둘 다 빈 경우에만 폴백(무음 유실 방지).
- `app/data_validator.py::_get_full_bouts_from_bracket` — `full_bouts` → `bouts`
  → `bouts_by_round` 순으로 **첫 non-empty 만** 쓴다(R16 우선순위와 동일 사상).
- `scheduler/competition_detector.py` — `full_bouts or bouts or []`, 비었을 때만
  `bouts_by_round` 폴백.
- `scripts/audit_final_rankings.py`, `repair_final_rankings.py` — `or` 폴백, 안전.

⚠️ **같은 로직이 세 곳(`de_transforms`, `data_validator`, 이 문서가 새로 만든
`bracket_utils`)에 독립적으로 존재**한다. 서로 다른 파일이라 한쪽만 버그 수정되고
다른 쪽은 안 될 위험이 있다 — "단일 진입점" 원칙 위반. 아래 참조.

### 이번에 추가한 단일 진입점 (`app/bracket_utils.py`)
```python
from app.bracket_utils import get_canonical_bouts, dedupe_bouts_by_identity

bouts = get_canonical_bouts(de_bracket)   # 읽기 규약을 강제하는 권장 경로
```
- `get_canonical_bouts()`: dual_de → `first_de`/`second_de` 재귀(둘 다 비면 최상위
  폴백) → `full_bouts` → `bouts` → `bouts_by_round` 순, **첫 non-empty 만** 사용.
- `dedupe_bouts_by_identity()`: `(de_phase, round_name, match_number)` 복합키로
  최종 안전망 dedup. **호출부가 실수로 두 소스를 합쳐도**(`repair_collapsed_de.py`
  와 같은 패턴) 이 함수를 한 번 거치면 중복이 사라진다 — 우선순위 로직 자체를
  고치는 것보다 강건하다.
- 테스트: `tests/test_bracket_utils_canonical_bouts.py` (11건, 46→7 축소 재현 포함).
  `PYTHONPATH=".:../../packages" python3 -m pytest tests/test_bracket_utils_canonical_bouts.py -q`

### 권고 (내 편집 범위 밖 — 담당 에이전트에게)
1. `de_transforms.py::_get_full_bouts_from_de_bracket` 와
   `data_validator.py::_get_full_bouts_from_bracket` 를 `bracket_utils.get_canonical_bouts()`
   위임으로 교체 (동작이 거의 같으므로 회귀 위험 낮음 — 차이는 `de_transforms` 가
   추가로 bout 형식을 정규화한다는 것뿐, 그건 유지).
2. `scripts/repair_collapsed_de.py::de_bouts()`, `repair_computed_team_finals.py`
   L92/95 를 `get_canonical_bouts()` 또는 최소한 `dedupe_bouts_by_identity()` 로
   감싸도록 수정.

---

## 2. `final_rankings_source` 관례

**컬럼이 아니라 `raw_data` JSONB 안의 키다** (`events.raw_data->>'final_rankings_source'`).
CLAUDE.md 예시 코드와 실제 스키마가 일치한다 — 컬럼으로 오인하지 말 것.

### 실측 분포 (2026-09-28)
```sql
select raw_data->>'final_rankings_source', count(*) from events group by 1;
```
| 값 | 건수 |
|---|---|
| (없음/NULL) | 2,441 |
| `kfa` | 485 |
| `computed` | 42 |

### 코드에서 실제 쓰이는 값 3개 (CLAUDE.md 는 kfa/computed 2개만 문서화되어 있었음)
| 값 | 의미 | 쓰는 곳 |
|---|---|---|
| `kfa` | 협회 공식 표 그대로 | `scripts/repair_final_rankings.py:305` |
| `computed` | 자체 계산(`compute_full_final_rankings`) | `scripts/repair_computed_team_finals.py:136` |
| `estimated` | 추정치 | `scripts/estimate_de_rankings.py:353` (문서화 안 돼 있었음 — 이번에 추가) |

### 주의: 값이 되돌아 사라지는 경로
`scripts/repair_collapsed_de.py:271` — 최종순위를 라이브 재수집본으로 교체할 때
`final_rankings_source` 키를 **삭제**한다(`rd.pop(...)`). 라이브 재수집본은 KFA
원본이므로 `'kfa'` 로 채우는 것이 맞아 보이지만, 지금은 unset(None) 상태로 남는다.
버그로 단정하기엔 의도(재분류 필요 표시)일 수도 있어 **미확인**으로 남긴다 —
`scripts/` 담당 에이전트가 의도를 확인할 것.

### 소급 표기
2,441건의 미표기 이벤트를 지금 와서 `kfa`/`computed` 로 추정해 채우지 않았다
(근거 없는 소급 표기 = 추측, CLAUDE.md 제0원칙 위반). 새로 계산/수집하는 경로만
표기하도록 코드를 맞추는 것이 맞는 방향.

---

## 3. 마이그레이션 파일 ↔ 실제 스키마 드리프트

### 발견 및 조치 (이번 세션에 해결함)
| 테이블 | 로컬 파일 | Supabase 마이그레이션 이력 | 조치 |
|---|---|---|---|
| `data_pool_revisions` | `026_create_data_pool_revisions.sql` 있음 | **없었음**(파일은 있는데 이력에 없음 — 직접 적용된 것으로 보임) | `apply_migration`으로 재등록 (idempotent, 스키마 변경 없음) |
| `data_de_revisions` | **없었음**(026 은 pool 만 만듦, de 짝 파일이 애초에 없었음) | 테이블은 존재(`app/de_revisions.py` 가 실사용 중) | 실제 스키마를 역추적해 `029_create_data_de_revisions.sql` 신설 + 적용·등록 |

두 조치 모두 `CREATE TABLE IF NOT EXISTS` 라 기존 테이블에 안전하게 재적용됐고
(컬럼 삭제/타입 변경 없음), `apply_migration` 실행 결과 `success:true` 로 기존
스키마와 완전히 일치함을 확인했다(충돌 없이 통과 = 내가 역추적한 컬럼 정의가
실제와 일치한다는 뜻).

### 그 외 (미해결 — 낮은 우선순위, 정보용)
`001_create_tables.sql` 이 정의하는 `tournament_results`, `pool_results`,
`player_rankings`, `final_rankings` 4개 테이블이 실제 DB 에 없다. 프로젝트 초기
설계였다가 `competitions`/`events`/`matches`/`rankings` 체계로 바뀌면서 버려진
것으로 보인다(**미확인** — 커밋 이력 조회 안 함). 파일을 지우면 001 은 "새 파일로만
추가" 규칙상 손댈 수 없는 첫 마이그레이션이라 그대로 두는 것을 권고. 동작에
영향 없음(아무 코드도 이 4개 테이블을 참조하지 않음 — grep 확인).

### 재실행 가능한 확인
```bash
PYTHONPATH=".:../../packages" python3 scripts/check_schema_drift.py
```
Supabase MCP 로 직접: `mcp__supabase__list_migrations` (이력) vs
`ls database/migrations/*.sql` (파일) 수동 대조.

---

## 4. `players.merged_into` 순환 참조

### 실측 (2026-09-28)
```sql
select count(*) from players p1 join players p2
  on p1.merged_into = p2.id and p2.merged_into = p1.id
  where p1.id < p2.id;
```
- `merged_into` 설정된 선수: **3,846명**
- **상호 순환(A→B→A) 62쌍**(=124명) — 전부 길이-2 순환. 길이-3 이상 순환은
  **0건**(재귀 CTE 로 확인).
- 자기참조(`merged_into = id`)는 0건.

62쌍 전원이 두 레코드의 `player_name` 이 **완전히 동일**하다(예: 정재승↔정재승
id 29/10874, 도경동↔도경동 id 2362/7306). 즉 "동명이인 병합/분리" 파이프라인이
같은 이름 쌍을 서로를 향해 양방향으로 병합해버린 것으로 보인다(**미확인** — 어느
스크립트가 이걸 만들었는지는 git blame/이력 조사 필요, 이번 감사 범위 밖).

### 조치하지 않은 이유
선수 정체성은 신중해야 한다(CLAUDE.md 제1원칙, "동명이인 구분"). 어느 쪽이
"정본"이고 어느 쪽이 "병합된 레코드"인지는 대회 참가 이력을 직접 봐야 판단
가능하며, 자동으로 한쪽을 고르면 잘못될 위험이 있다. **탐지만 하고 목록만
남긴다.**

### 62쌍 전체 목록
`scripts/check_schema_drift.py` 실행 시 콘솔에 상위 5쌍만 표본 출력한다.
전체 목록은 아래 쿼리로 즉시 재현 가능:
```sql
select p1.id, p1.player_name, p2.id, p2.player_name
from players p1 join players p2
  on p1.merged_into = p2.id and p2.merged_into = p1.id
where p1.id < p2.id order by p1.id;
```
id 쌍(62개, `player_name` 은 위 쿼리로 재조회):
29↔10874, 34↔812, 118↔496, 224↔5834, 318↔8995, 381↔6353, 513↔6421, 553↔11100,
573↔1406, 586↔5859, 696↔10361, 725↔10017, 831↔1779, 855↔2497, 1119↔6792,
1270↔10793, 1307↔10525, 1418↔10914, 1510↔5308, 1590↔5472, 1593↔1920, 1618↔11111,
1729↔5292, 1939↔9220, 1956↔6490, 1958↔2179, 2228↔9533, 2362↔7306, 2492↔7893,
2527↔3916, 2587↔8372, 2680↔10371, 2787↔6690, 2797↔9822, 2832↔6442, 2834↔5067,
3239↔9357, 3302↔8442, 3429↔5990, 3468↔3648, 3488↔7632, 3573↔7252, 3790↔10866,
4083↔8582, 4304↔7845, 4795↔6596, 4842↔7850, 4874↔5869, 4985↔5662, 5182↔11383,
6135↔7391, 6263↔8174, 6440↔11284, 6855↔7749, 6863↔10500, 6985↔11651, 7414↔9651,
7418↔8890, 7849↔9166, 7981↔8061, 9711↔11351, 10139↔10747

### 검증 스크립트
`scripts/check_schema_drift.py`(3절)가 매 실행마다 이 쌍 수를 다시 세어 인쇄한다
(Supabase 클라이언트 기본 페이지 크기 1,000건 제한을 피하려 직접 페이지네이션함
— 첫 구현은 이 제한에 걸려 3,846명 중 1,000명만 보고 62쌍 중 4쌍만 찾는 버그가
있었다; 페이지네이션 추가로 수정·검증 완료).

---

## 5. `data_*` 접두사 · RLS · 타임존 관례

### 접두사 (CLAUDE.md "테이블 네이밍 규칙")
신설 테이블(`data_pool_revisions`, `data_de_revisions`, `data_kfa_notices`,
`data_kfa_rosters`, `data_fie_rankings`, `data_intl_events`, `data_intl_results`,
`data_intl_bouts`, `data_events`)은 전부 `data_` 접두사 규칙을 지키고 있다.
위반 없음.

기존 `fie_confederations`, `fie_national_federations`, `fencing_equipment_brands`,
`fencing_world_organizations`, `fencing_data_platforms` 는 접두사 없이 도입됐다
(2026-05-24~25, `global_fencing_*` 마이그레이션). data 서비스 소유가 맞다면 규칙
위반이지만, **테이블 이름을 바꾸는 것은 파괴적 변경**(다른 마이그레이션 규칙:
"기존 마이그레이션 파일 수정 금지"와 별개로, ALTER TABLE RENAME 은 이번 작업
범위의 "컬럼 삭제·타입 변경 금지" 원칙과 같은 급의 위험도)이라 손대지 않음.
문서화만 함 — 이름 정정이 필요하면 별도 논의 필요.

### RLS
```
mcp__supabase__get_advisors(type="security")
```
`rls_disabled_in_public` (ERROR 레벨) 61건 — `data_pool_revisions`,
`data_de_revisions`, `data_intl_results`, `data_kfa_notices`, `data_kfa_rosters`,
`data_fie_rankings`, `data_intl_events`, `data_intl_bouts` 전부 포함.

**신규 위반이 아니라 기존 컨벤션과 동일선상**이다 — `events`, `players`,
`competitions`, `matches`, `rankings`, `organizations` 등 핵심 테이블도 전부
RLS 가 꺼져 있다(전체 DB 공개 읽기 전제, `anon key` 로 서버가 직접 읽는 구조로
보임 — **미확인**, RLS 정책 설계 문서가 따로 없음). 새 `data_*` 테이블이 기존
관례를 그대로 따른 것이므로 "이번에 생긴 구멍"은 아니다. RLS 를 프로젝트 전체
차원에서 켤지는 이번 작업 범위를 넘는 별도 결정이 필요해 보인다 — 사장님 판단
필요.

`app_*` 테이블 5개는 반대로 **RLS 는 켰는데 정책이 없다**(`rls_enabled_no_policy`,
INFO 레벨) — 이건 app 서비스 담당 범위라 여기서는 사실만 기록.

### 타임스탬프
`data_pool_revisions`/`data_de_revisions` 의 `detected_at` 은 `TIMESTAMPTZ NOT NULL
DEFAULT NOW()` — UTC 로 저장되고 Postgres 가 타임존 변환을 책임진다(표준적).
KST 라벨링은 애플리케이션 레이어(`app/de_revisions.py::_to_kst_label()`)에서만
하고 있어 저장은 항상 UTC, 표시만 KST — 일관된 관례. 문제 없음.

---

## 요약 (한 줄씩)
1. `de_bracket` bout 추출: 규약을 `app/bracket_utils.get_canonical_bouts()` 로
   문서화·구현·테스트 완료. `scripts/repair_collapsed_de.py`,
   `repair_computed_team_finals.py` 의 concatenation 버그는 **보고만 함**(편집 범위 밖).
2. `final_rankings_source`: 컬럼 아님(JSONB 키). 허용값 3개(`kfa`/`computed`/`estimated`)
   확인, 소급 표기 안 함, 되돌아 사라지는 경로 1건 발견·보고.
3. 마이그레이션 026(추적 누락)·de_revisions(파일 자체 누락) 드리프트 **해결**
   (029 신설). 001 의 죽은 테이블 4개는 정보용으로만 기록.
4. `merged_into` 상호 순환 **62쌍(124명)** 확정. 자동 수정 안 함, 검증 스크립트로 고정.
5. `data_*` 접두사 위반 없음. RLS 는 기존 컨벤션과 동일(전체 미비 — 신규 문제 아님).
   타임존은 일관됨.
