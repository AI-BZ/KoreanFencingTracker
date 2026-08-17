# DE(Direct Elimination) 화면 전면 재설계 연구 보고서

- 작성일: 2026-08-17
- 범위: `services/data`의 DE 대진표 전체 (단일 DE + Dual DE), 관련 서버 변환·API·템플릿·JS·CSS
- 방법: 코드 정독 + Supabase raw 데이터 SQL 검증 + 프로덕션 DOM 실측 (읽기 전용, 코드 미수정)
- 검증 대상 실데이터: 제66회 대통령배 겸 국가대표선수 선발대회 (`COMPM00722`)
  - 여자 에페(개) `COMPS000000000004159` (events.id=23623)
  - 여자 플뢰레(개) `COMPS000000000004158` (events.id=23622)
  - 남자 에페(개) `COMPS000000000004156` (events.id=23620)

표기 원칙: **[확인]** = 코드/데이터/DOM으로 검증된 사실, **[추정]** = 정황상 유력하나 추가 확인 필요.

---

## A. 현황 규명 (증거 기반)

### A-1. Dual DE 데이터 흐름 (서버 → 클라이언트)

```
Supabase events.raw_data.de_bracket
  ├─ format: "dual_de"
  ├─ first_de:  {bracket_size, starting_round, full_bouts: []}   ← 비어 있음 [확인]
  ├─ second_de: {bracket_size, starting_round, full_bouts: []}   ← 비어 있음 [확인]
  ├─ full_bouts: [모든 bout]  ← 실제 데이터는 전부 여기 (여에 127개, 남에 287개) [확인]
  ├─ seeded_players, first_de_qualifiers
  ↓
server.py 이벤트 페이지 라우트 (server.py:7037)
  → transform_de_bracket() (de_transforms.py:643)
    → normalize_bracket_data() → is_dual_de_format() 감지 (bracket_utils.py:720, 1793)
      → normalize_dual_de_bracket_data() (bracket_utils.py:1820)
        ① 최상위 full_bouts를 first_de / second_de로 분배 (1848~1883)  ← 🔴 버그 지점
        ② first_de 정규화 + Second DE 시작 라운드 이후 라운드 제거 (1885~1928)
        ③ second_de 정규화 (fill_to_final=True) (1930~1933)
        ④ 시드/진출자/status 계산 (1935~1983)
    → NormalizedDualDEBracket.to_dict() → event.normalized_bracket (dict)
  ↓
templates/event_result.html:1580 → format=='dual_de'이면
  components/dual-bracket-tabs.html (First/Second 탭 UI)
    → 각 phase마다 components/bracket.html include (트리뷰/리스트뷰)
  ↓
static/js/dual-bracket.js DualDEController
  - data-status 기반 탭 자동 선택(restoreState), localStorage 기억
```

이와 별개로 API 계열(`/api/.../de-results`, `/api/.../de-prediction`, 선수 프로필 등)은
`_get_full_bouts_from_de_bracket()` (de_transforms.py:188)로 **phase 구분 없이 합쳐진 bout 목록**을 사용한다.
dual_de일 때는 first_de/second_de에서 재귀 추출 후 `de_phase` 태그를 붙이지만(de_transforms.py:204~216),
현행 데이터는 하위 full_bouts가 비어 있으므로 이 태깅 경로는 사실상 동작하지 않고, 최상위 full_bouts가 그대로 흐른다. **[확인]**

### A-2. 🔴 "64강이 사라진" 근본 원인 — 원인은 2개이며 서로 다르다

#### 원인 1 (코드 버그): bout 분배 시 존재하지 않는 키 `match_num` 참조 — bracket_utils.py:1874

공유 라운드(예: 64강)를 First/Second로 나누는 코드:

```python
# bracket_utils.py:1870~1878
# Shared round (e.g., 64강) → split by match_number
second_de_bracket_size = second_de_raw.get('bracket_size', 64)
max_second_de_match = second_de_bracket_size // 2

match_num = bout.get('match_num', 0)          # ← 🔴 실데이터 키는 'match_number'
if match_num <= max_second_de_match:
    second_de_bouts.append(bout)
else:
    first_de_bouts.append(bout)
```

**실데이터 검증 [확인]** — 여자 에페 full_bouts 127개 전수 조사(SQL):

| round_name | bout 수 | `match_num` 보유 | `match_number` 보유 |
|---|---|---|---|
| 128강 | 64 | **0** | 64 |
| 64강 | 32 | **0** | 32 |
| 32강~결승 | 31 | **0** | 31 |

모든 bout이 `match_number`만 가진다. `bout.get('match_num', 0)` → 항상 **0** → `0 <= 32` → **공유 라운드(64강)의 모든 bout이 Second DE로 분류**된다. First DE에서는 64강이 통째로 사라진다.

**남자 에페(256 브래킷)에서 피해가 가장 명확하다 [확인]**:

| round | bout 수 | match_number 범위 | 올바른 소속 |
|---|---|---|---|
| 256강 | 128 | 1~128 | First DE |
| 128강 | 64 | 129~192 | First DE |
| **64강** | **64** | **1~32 및 193~224 혼재** | mn 1~32=Second DE(32경기), mn 193~224=First DE(32경기) |
| 32강 | 16 | 33~48 | Second DE |
| 16강~결승 | 15 | — | Second DE |

즉 데이터 자체에는 First DE 64강(mn 193~224)이 **온전히 존재**하는데, 분배 코드가 키 오타로 전부 Second DE에 넣는다.

**프로덕션 DOM 실측 [확인]** (`/competition/COMPM00722?event=COMPS000000000004156`):

```
first-de-panel  rounds: 256강(128경기), 128강(64경기)          ← 64강 없음
second-de-panel rounds: 64강(64경기), 32강(16경기), ...        ← 본선 64강이 64경기(정상 32)
```

Second DE 64강에 First DE 64강 32경기가 섞여 들어가 **본선 대진표 자체가 오염**돼 있다. 사용자가 본 "64강 소실"의 남자 에페 케이스는 이것이다.

#### 원인 2 (데이터 누락): 128 브래킷 이벤트는 First DE 64강 bout이 아예 수집되지 않았다

여자 에페/플뢰레(first_de bracket_size=128, second_de=64)의 저장 bout은 127개 = 128강 64 + 64강 32 + 32강 16 + 16강 8 + 8강 4 + 준결승 2 + 결승 1. 검증 결과:

- 저장된 64강 32경기에는 **시드 상위 32명이 전원 출전** → 이 64강은 **Second DE의 64강**이다. **[확인 — SQL: top32_in_r64=32]**
- 128강 승자 61명 중 64강에 등장하는 선수는 **30명뿐**. **[확인 — SQL]**
- 즉 "128강 승자 약 64명 → 32명"으로 줄이는 **First DE 64강(32경기)이 데이터에 없다**. 기대 총량은 127+32=159개.
- `first_de_qualifiers`도 0명으로 저장됨 **[확인]** → 화면에 "시드 선수 32명 + **First DE 진출자 0명** = 총 64명"이라는 모순 문구가 그대로 노출된다 **[확인 — 프로덕션 DOM]**.
- 자동 추출 폴백 `_extract_first_de_qualifiers_from_bracket()`(bracket_utils.py:1986)도 `first_de.bouts_by_round['64강']`을 읽으므로(1997) 원인 1·2 어느 쪽이든 빈 결과.

**[추정]** 누락 지점은 스크래퍼: KFA는 예선 DE를 별도 셀렉터(schEtc01)로 제공하는데 128강 페이지만 수집되고 First DE 64강 페이지가 빠졌을 가능성이 크다. 남자 에페(256)는 First DE 3라운드가 전부 수집된 반면 여자(128)만 마지막 라운드가 빠진 패턴이므로, `scraper/full_scraper.py`의 예선 DE 라운드 순회 로직을 KFA 실페이지와 대조해 확정해야 한다.

> 결론: **남자 에페 = 분배 버그(코드 1줄), 여자 에페·플뢰레 = 스크래핑 누락(데이터)**. 두 원인 모두 화면상 증상은 "First DE에 64강이 없다"로 동일하게 보인다.

### A-3. "128강 → Second DE" 표시의 정체

`dual-bracket-tabs.html:119~140`의 **First DE 진행 표시 바(progress bar)**다.
`first_de.rounds`를 순회하며 라운드 스텝을 그린 뒤 마지막에 고정 스텝 `→ Second DE`(136행)를 붙인다.

- 여자 에페: first_de.rounds = `['128강']` (64강 부재) → 화면에 **"128강 64/64 → Second DE"** 만 남는다. **[확인 — DOM]**
- 남자 에페: `['256강','128강']` → "256강 → 128강 → Second DE". **[확인 — DOM]**

즉 이 표시는 오류 산출물이 아니라 "진행 단계 바"인데, (a) 64강 소실로 라운드가 절단돼 의미가 왜곡되고, (b) "→ Second DE"라는 화살표 스텝이 무엇으로 몇 명이 넘어간다는 것인지 설명이 없어 처음 보는 사용자는 해석 불가능하다.

추가로 그 위의 안내 배너(dual-bracket-tabs.html:112~115)는 **템플릿 하드코딩 문구**다:

```
"비시드 선수 {{N}}명이 32강 진출을 위해 경쟁합니다.
 128강(64경기) → 64강(32경기) 2라운드를 거쳐 32명이 Second DE로 진출합니다."
```

256 브래킷인 남자 에페에도 똑같이 "128강(64경기) → 64강(32경기) 2라운드"라고 표시된다. **[확인 — DOM]** 데이터(first_de.rounds, bracket_size)와 무관한 고정 문장이라 브래킷 크기가 다르면 즉시 거짓말이 된다. "32강 진출"이라는 표현도 실제로는 "본선(Second DE) 64강 진출"이므로 부정확하다.

### A-4. "선수 루트" 위젯의 실제 동작 규명

위치: `event_result.html:1523~1577`(마크업/스타일), `2510~2692`(JS).

**드롭다운에 나오는 선수의 선정 기준 [확인]**:

```jinja2
{# event_result.html:1524~1527 #}
{% if event.normalized_bracket and event.normalized_bracket.seeding %}   {# 단일 DE #}
{% elif event.normalized_bracket.seeded_players %}                        {# Dual DE #}
{% elif event.de_seeding %}
```

- 단일 DE: `normalized_bracket.seeding` = 브래킷 시딩 전원 → **DE 참가자 전원**이 나온다.
- Dual DE: `NormalizedDualDEBracket.to_dict()`(bracket_utils.py:129~140)에는 `seeding` 키 자체가 없어 `seeded_players`로 폴백 → **시드 상위 32명만** 나온다(1941행에서 seed ≤ 32만 채택).

사용자가 "전체가 나오는 것도 아니고 시드만인지 헷갈린다"고 한 것은 정확한 관찰이다: **이벤트 형식에 따라 대상이 달라진다.** 대통령배 같은 Dual DE에서는 First DE에서 뛰는 비시드 선수(= 대다수 학부모의 자녀)가 드롭다운에 아예 없다.

**표시 내용 [확인]** — 선택 시 두 API를 병렬 호출해 합성한다(2640~2644):

1. `/api/events/{cd}/de-results/{name}` (server.py:4280): 완료된 DE 경기들 — 라운드·상대·점수·승/패/부전승.
2. `/api/events/{cd}/de-prediction/{name}` (server.py:3717): 아직 안 치른 라운드별 **잠재 상대 후보** — 시드 위치 기반 표준 브래킷 수학으로 계산(3937~), 실제 참가자만 필터.

렌더(2542~2634): 완료 라운드는 승(초록)/패(빨강)/부전승 노드, 탈락/우승 시 종료 노드 + 최종순위 비동기 채움, 진행 중이면 미래 라운드를 점선 노드로 "상대 후보 N명: …" 나열(최대 8명 표시).

**한계 [확인]**:
- `de-prediction`의 라운드 목록에 **256강이 없다**(server.py:3800 `round_order = ["128강", …]`) → 256 브래킷 이벤트에서 계산이 어긋난다.
- Dual DE를 인식하지 못한다: phase 구분 없는 `full_bouts` 합본으로 완료 라운드를 판단하고(3844), 시드도 `de_bracket.seeding`(dual raw에는 없음) → pool 순위 폴백(3788)으로 대체한다. First DE 시드 체계와 Second DE 시드 체계(1~64 재부여)가 다른데 하나의 브래킷 수학에 밀어 넣는다.
- 미래 라운드 후보에 "예상"임을 명시하는 라벨이 약하다(점선+"다음"뿐).

**기본 선택 [확인]** (2677~2688): `?highlight` 파라미터 → 내 선수(localStorage 동기) → 즐겨찾기(비동기) 순으로 자동 선택. 즉 위젯 자체는 "내 선수 우선" 사상을 이미 갖고 있으나, Dual DE에서 내 선수가 비시드면 드롭다운에 없어 자동 선택이 실패한다.

### A-5. 현행 "내 선수" 하이라이트가 DE에서 사실상 동작하지 않는 이유

내 선수 인프라 자체는 있다: localStorage 단일 My Player + 서버 즐겨찾기 병합(`getMyPlayerNames`, event_result.html:2184~2213), Pool 탭에는 풀 점프 바·풀 버튼 마킹(1327, 2262~2292), EventH2H 상대전적 배지(2700~) 등. 그러나 **DE 대진표에서는**:

1. **트리뷰(데스크톱 기본)는 하이라이트 셀렉터에서 빠져 있다 [확인]**.
   `PlayerHighlighter.highlight()`(player-search.js:223~302)가 검사하는 DE 관련 셀렉터는 `.bout-player`, `.match-card`, `.bracket-bout, .bout-card`뿐이다. 트리뷰의 경기 블록 클래스는 **`.bracket-match`**(bracket.html:97)인데 어떤 셀렉터에도 포함되지 않았고, `player-search.css`에도 `.bracket-match.player-highlighted` 규칙이 없다(88~124행에 존재하는 것은 tr/.match-card/.bout-player/.podium-place/.bracket-bout/.bout-card뿐). → 데스크톱 트리뷰에서 검색·내선수 하이라이트가 **아무 일도 하지 않는다**.
   (참고로 EventH2H의 배지는 `.bracket-match`를 제대로 순회한다 — event_result.html:2855. 같은 파일 안에서 셀렉터 목록이 분기돼 있다.)
2. **단일 선수만, 색상만**: `highlight()`는 호출 시 이전 하이라이트를 `clear()`하므로 여러 명 동시 표시가 불가능하고, 시각 효과는 `player-highlighted` 클래스 한 종류(색 배경)뿐이다. 128강 50+ 경기 속에서 색 하나로 찾으라는 구조 — 사용자 지적 그대로.
3. **이동 보조 없음**: 첫 발견 요소로 `scrollIntoView` 1회(298행)가 전부. 다음/이전 경기 순회, 미니맵, 현재 위치 표시 없음. Dual DE에서는 `dual-bracket.js`의 `findAndHighlightPlayer()`(336~389)가 phase 전환+스크롤을 지원하지만, 이 함수 역시 `.bracket-match`가 아닌 `.bracket-bout, .bout-card, .match-card`만 검색(395행)하는 데다 **어디에서도 호출되지 않는다** (grep 결과 정의뿐, 호출부 없음). **[확인]**
4. Pool 탭의 "내 선수 풀 보기" 같은 원클릭 진입 장치가 DE 탭에는 없다(`my-player-pool-bar`는 Pool 전용 — event_result.html:1327).

### A-6. 탭 진입 규칙(문제 5)의 현행 메커니즘

진입 탭은 `dual-bracket.js restoreState()`(181~206)가 결정한다: `data-status`가 `second_de_in_progress`/`completed`면 Second DE로 자동 전환, 아니면 localStorage 저장값, 최후 First DE.

status는 서버가 데이터에서 파생한다(`_determine_dual_de_status`, bracket_utils.py:2037~2085):

- `first_de_complete` 판정: **first_de의 64강 bout이 32개 이상 전부 완료**여야 함(2060~2063).
  → A-2의 두 원인 때문에 first_de에 64강이 **절대 존재하지 않으므로**, `first_de_completed` 상태는 현행 데이터에서 도달 불가능. **[확인]**
- `second_de_in_progress` 판정: second_de에 bout이 하나라도 있으면 즉시(2066, 2078).
  → 분배 버그로 **First DE 64강 bout이 스크래핑되는 순간 second_de로 분류**되므로, 실제로는 예선 DE가 한창인 시점에 status가 `second_de_in_progress`로 바뀌고 사용자는 Second DE 탭으로 자동 진입한다. 게다가 그 Second DE 탭에는 First DE 64강 경기가 섞여 보인다.

사용자가 겪은 "First DE가 안 끝났는데 Second DE로 들어간다"는 현상의 코드 경로가 이것이다. **[확인 — 코드 경로. 진행 중 실관측은 대회 종료로 불가, 현재 두 이벤트 모두 data-status="completed"]**
부가적으로 localStorage에 저장된 phase가 다음 방문의 status 기반 판단보다 우선하는 구간(190~199)이 있어, 상태가 바뀌어도 이전 탭이 열리는 혼선이 가능하다.

### A-7. 용어(문제 6) 현행 표기

`dual-bracket-tabs.html:28~29, 39~40`:

```
[phase-label 큰 글씨]  First DE
[phase-sublabel 작게]  예선 DE (32명의 면제자가 있는 예선엘리미나시옹디렉트)

[phase-label 큰 글씨]  Second DE
[phase-sublabel 작게]  본선 DE (64강)
```

한국어 UI인데 **영문 명칭이 주(主), 한국어가 부(副)**로 배치돼 있고, 부연 문구 "32명의 면제자가 있는 예선엘리미나시옹디렉트"는 외래어 음차+행정용어("면제자")의 조합으로 학부모 1차 사용자에게 사실상 해독 불가다. 같은 문구가 `bracket_utils.py:156~162 get_display_name()`에도 중복 정의돼 있다.

### A-8. 기타 확인 사항

- **Dual DE 최종순위 동적 계산이 현행 데이터에서 작동하지 않는다 [확인]**: `server.py:7045~7051`의 `has_second_de`는 raw `second_de.bouts/full_bouts`가 비어 있으면 False → `compute_dual_de_final_rankings()`(de_transforms.py:408)는 호출되지 않거나(호출돼도 441~445에서 빈 리스트 반환) 단일 DE 경로로 빠진다. 현재는 KFA 스크래핑 final_rankings가 이를 가려주고 있다.
- **DB 컬럼 `has_first_de`/`has_second_de`가 실데이터와 불일치 [확인]**: 세 이벤트 모두 `de_format='dual_de'`인데 두 컬럼은 false. `pipeline_scraper.py:311~312`가 `de_bracket.first_de is not None`이 아니라 하위 full_bouts 존재를 보는 것이 아니라... (정확히는 first_de 키 존재 여부를 보는데 false로 저장됨 — 저장 시점 데이터 형상 차이로 보임). 컬럼을 신뢰하는 코드가 생기면 오판 위험. **[일부 추정 — 저장 시점 재현 필요]**
- **여자 이벤트 seeded_players에 64명 저장 [확인]**: seed 1~64가 들어 있고 템플릿·정규화는 ≤32만 사용(bracket_utils.py:1941). 33~64번의 의미(본선 시딩 전체 목록으로 추정)가 미규명. **[추정]**
- **스타일 부채 [확인]**: `bracket.css`에 하드코딩 hex **146개**. 팔레트가 파랑 슬레이트 계열(#2a3f5f, #3b82f6, #60a5fa)로 확정 디자인 방향(태극 적/청 + `--fm-*` 토큰)과 어긋난다. 승자 표시는 초록 글로우+text-shadow. 트리뷰 라운드 연결선은 우측 20px 수평선 1개(`.match-connector`, bracket.css:533)로 실제 다음 경기와 시각적으로 이어지지 않는다. QF 그룹 8색 인코딩은 `bracket.html:318~366`에 rgba 하드코딩+`!important`로 박혀 있고, 그룹 산정이 DOM 순서 나누기(bracket.html:405~452)라 분배 로직이 바뀌면 색이 어긋난다.
- **경기 블록 클릭 동작 없음 [확인]**: `.bracket-match`/`.match-card`에 클릭 핸들러가 없다. 내부 선수명 링크(프로필 이동)만 존재. 사용자가 요구한 "블록 클릭 → 예상 상대/전적" 기능의 기반이 전무하며, EventH2H 배지(상대전적)가 유일한 인라인 정보다.
- **dual-bracket.js 이중 로드 가능 [확인]**: 컴포넌트(dual-bracket-tabs.html:247)와 event_result.html(1909 부근) 양쪽에서 로드 — defer+클래스 재정의라 실해는 없으나 정리 대상.

---

## B. 문제 목록 (근거·심각도·사용자 영향)

| # | 문제 | 근거 (파일:줄) | 심각도 | 사용자 영향 |
|---|---|---|---|---|
| P1 | 공유 라운드 분배가 `match_num`(실키 `match_number`) 참조 → First DE 64강 전체가 Second DE로 흡수, 본선 64강 64경기로 오염 | bracket_utils.py:1874 · SQL·DOM 실측 | **치명** | 예선·본선 대진표 둘 다 틀린 데이터 표시. 데이터 신뢰 훼손(제1원칙 위반 상태) |
| P2 | 128 브래킷 이벤트의 First DE 64강 bout 미수집(127/159개), first_de_qualifiers=0 | Supabase 실데이터 · scraper 순회 로직 [추정 부분 有] | **치명** | 여자 종목 예선 후반 경기가 세상에서 사라짐. "진출자 0명" 모순 문구 노출 |
| P3 | status 파생 오류: first_de_completed 도달 불가 + First DE 64강 스크랩 즉시 second_de_in_progress → 예선 중 본선 탭 자동 진입 | bracket_utils.py:2060~2063, 2078 · dual-bracket.js:181~206 | **높음** | 대회 당일 학부모가 엉뚱한 탭에서 자녀 경기를 못 찾음 (문제 5의 원인) |
| P4 | 트리뷰 `.bracket-match`가 하이라이트 셀렉터·CSS에 미포함 → 데스크톱 DE 하이라이트 무동작 | player-search.js:243~294 · player-search.css:88~124 · bracket.html:97 | **높음** | "내 선수 찾기" 핵심 기능이 기본 뷰에서 작동 안 함 |
| P5 | 하이라이트가 단일 선수·색상 1종·1회 스크롤뿐. 다중 표시/순회/미니맵 없음. `findAndHighlightPlayer()`는 미호출 사장 코드 | player-search.js:223~309 · dual-bracket.js:336~389(호출부 없음) | **높음** | 128강 50+ 경기에서 색만으로 탐색 — 사용자 명시 불만 (문제 1·4) |
| P6 | 선수 루트 대상이 이벤트 형식에 따라 달라짐: Dual DE에서는 시드 32명만 (to_dict에 seeding 부재) | event_result.html:1524~1527 · bracket_utils.py:129~140, 1941 | **높음** | 비시드 선수(대다수) 선택 불가, 위젯 개념 자체가 불투명 (문제 2 후반) |
| P7 | First DE 안내 배너·진행바가 하드코딩("128강→64강 2라운드", "→ Second DE") — 256 브래킷에도 동일 문구 | dual-bracket-tabs.html:112~115, 134~137 | 중간 | 데이터와 다른 설명 = 신뢰 훼손. "→ Second DE" 해석 불가 (문제 3) |
| P8 | 용어: 영문 주표기 + "32명의 면제자가 있는 예선엘리미나시옹디렉트" | dual-bracket-tabs.html:28~29,39~40 · bracket_utils.py:156~162 | 중간 | 초심 사용자 개념 이해 실패 (문제 6) |
| P9 | de-prediction이 256강 미지원·Dual DE 미인식(시드 폴백=풀순위, phase 혼합) | server.py:3800, 3788~3797, 3844 | 중간 | 선수 루트의 "예상 상대"가 대형 대회에서 부정확 |
| P10 | Dual DE 최종순위 동적계산 경로가 top-level full_bouts 저장 형상에서 불능 | server.py:7045~7051 · de_transforms.py:441~445 | 중간 | KFA 순위 미게시·스크랩 실패 시 폴백 부재 |
| P11 | 경기 블록 클릭 인터랙션 전무 (선수명 링크만) | bracket.html:97~147, 230~300 | 중간 | 문제 2의 요구 기능 기반 부재 |
| P12 | bracket.css 하드코딩 hex 146개, 파랑 슬레이트 팔레트, QF 8색 rgba+!important 인라인 | bracket.css 전반 · bracket.html:318~366 | 중간 | 확정 디자인 방향(태극+토큰) 위반, 라이트 테마 이중 유지비 |
| P13 | localStorage 저장 phase가 상태 변화보다 우선하는 복원 구간 | dual-bracket.js:190~199 | 낮음 | 재방문 시 낡은 탭 진입 |
| P14 | `has_first_de/has_second_de` 컬럼 불일치, seeded_players 64명 저장 의미 미규명, dual-bracket.js 이중 로드 | pipeline_scraper.py:311~331 · SQL · dual-bracket-tabs.html:247 | 낮음 | 잠재 오판·유지보수 부채 |

---

## C. 재설계안

전제: FastAPI + Jinja2 + 바닐라 JS 유지, 외부 CDN 금지, 색은 `--fm-*` 토큰만(태극 적/청 + 메달 골드), 숫자는 `--fm-font-display`+`.fm-num`, 예상 데이터는 반드시 "예상" 라벨(제1원칙 — 추정치를 확정처럼 보이지 않게).

### C-1. 정보 구조: 탭 계층·진입 규칙·용어

**탭 구조(유지 + 재표기)** — Dual DE는 2탭 구조 자체는 유효하다. 표기를 한국어 주(主)로 뒤집는다:

```
┌──────────────────────────────┬──────────────────────────────┐
│  예선 DE                      │  본선 DE                      │
│  First DE · 128강→64강        │  Second DE · 64강→결승        │
│  ● 진행 중 (64강 12/32)       │  ○ 예선 종료 후 시작           │
└──────────────────────────────┴──────────────────────────────┘
```

- phase-label = "예선 DE" / "본선 DE" (크게), phase-sublabel = "First DE" / "Second DE" (작게) — 문제 6 요구 그대로. i18n: en에서는 반대로 First DE 주표기.
- 라운드 범위(`128강→64강`)는 **first_de.rounds/second_de.starting_round에서 동적 생성** (P7 해소). 배너 문구도 동일 원칙: "시드 상위 {seeded_count}명을 제외한 {first_de_participant_count}명이 {rounds[0]}부터 겨루고, {last_round} 승자 {qualifier_count}명이 본선에 합류합니다."
- "면제자" → "시드 (예선 면제)"로 통일하고, 개념 설명은 기존 `.fm-help` 툴팁 컴포넌트로 이동(탭 옆 ? 버튼): "본선 DE = 시드 32명 + 예선 통과 32명이 64강부터 겨루는 본 토너먼트".
- 진행바의 "→ Second DE" 스텝은 "**본선 진출 {n}명**"으로 교체하고 완료 시 진출자 수를 실데이터로 채운다.

**진입 규칙(문제 5)** — 서버가 status를 바로잡은 뒤(D-Phase 0/1) 규칙은 단순화:

| status | 기본 탭 |
|---|---|
| pending / first_de_in_progress | 예선 DE |
| first_de_completed (예선 전 라운드 완료 && 본선 bout 미존재) | 예선 DE (진출자 명단 강조) — "본선 대진 준비 중" 배지 |
| second_de_in_progress / completed | 본선 DE |

- `first_de_complete` 판정을 "64강 32경기 완료" 하드코딩(bracket_utils.py:2060~2063)에서 "**first_de.rounds의 마지막 라운드가 전부 완료**"로 일반화 (256·128 브래킷 모두 대응).
- localStorage 복원은 **status가 지난 방문과 같을 때만** 적용(P13). status가 진전되면 status 기본값이 이긴다.
- 내 선수가 지정돼 있으면 진입 탭을 한 번 더 보정: 내 선수의 최신 경기가 있는 phase를 우선한다(예: 예선 탈락자 부모는 본선이 시작돼도 예선 DE의 자기 경기부터).

### C-2. "내 선수 우선" 인터랙션 — 3안 비교

공통 기반: `getMyPlayerNames()`(즐겨찾기+My Player 병합, 이미 존재)를 DE 탭의 1급 데이터로 승격. `PlayerHighlighter` 셀렉터에 `.bracket-match` 추가 + 다중 하이라이트 API(`highlightMany([{ko,team,slot}])`)로 확장(P4·P5 해소가 모든 안의 선행 조건).

**A안 — 내 선수 스트립 + 점프 내비게이터 (권장, 1차 구현)**

DE 탭 상단에 sticky 칩 스트립:

```
⭐ 내 선수:  [박소윤 · 예선 64강 ▶]  [김OO · 탈락(128강)]  [이OO · 본선 32강 ▶]   ◀ 1/3 ▶
```

- 칩 = 선수별 현재 상태 요약(다음 경기 라운드 or 탈락 라운드). 데이터는 de-results API 재사용(선수당 1콜, 이미 존재).
- 칩 탭 → 해당 phase로 전환 + 그 선수의 최신/다음 경기 블록으로 스크롤 + 펄스 애니메이션(box-shadow 1회, `prefers-reduced-motion` 존중). `findAndHighlightPlayer()` 사장 코드를 이 용도로 부활·수리.
- ◀ ▶ = 같은 선수의 라운드별 경기 사이 순회(128강→64강→…), 여러 선수 간 이동은 칩 클릭.
- 다중 동시 표시: 내 선수 전원에게 항상 얇은 좌측 보더 + 이름 옆 ⭐. 색 구분은 최대 2계열(태극 레드 = 첫 선수, 태극 블루 = 그 외)로 제한하고 **식별은 색이 아니라 칩·별표·이름**으로 한다(색약 대응, 금지 패턴 회피).
- 장점: 구현비 낮음(기존 API·하이라이터 확장), 모바일 리스트뷰와 트리뷰 양쪽 동작, "먼저 내 선수 → 다음 경쟁자" 순서(문제 4)와 정합.
- 단점: 즐겨찾기 다수(5+)면 칩 오버플로(가로 스크롤 필요). 브래킷 전체 조망은 못 준다.

**B안 — 브래킷 미니맵**

트리뷰 우상단에 고정 소형 개요(순수 DOM/CSS 격자 또는 인라인 SVG, 외부 라이브러리 불필요): 라운드×경기 격자에서 내 선수 경기 셀만 점등, 현재 뷰포트 위치 사각형 표시, 클릭/드래그로 해당 위치 스크롤.

- 장점: 128강급에서 "내가 어디를 보고 있나" 방향감각 제공. 스포츠 데이터 브랜드다운 밀도 높은 시각물.
- 단점: 구현비 최대(스크롤 동기화·리사이즈), 모바일에서는 표시 면적 부족 — 데스크톱 전용이 현실적. 1차 범위에서 제외하고 A안 정착 후 데스크톱 강화로 추가 권장.

**C안 — "내 선수 여정" 카드 (선수 루트 위젯의 재편)**

기존 "선수 루트"를 개편·개명("내 선수 여정")해 DE 탭 최상단의 **1차 화면**으로 승격. 내 선수 각각에 대해 예선→본선을 관통하는 세로 타임라인 카드(승/패/부전승/다음 경기/예상 상대 후보)를 자동 표시. 대진표 전체는 그 아래 "전체 대진표" 섹션.

- 드롭다운 대상은 **DE 참가자 전원**으로 확대: Dual DE도 서버가 `seeding`(본선)+`first_de 참가자`를 합쳐 to_dict에 제공하거나, 기존 `/api/events/{cd}/players/search` 자동완성으로 대체(P6 해소).
- 장점: 학부모 시나리오("우리 애 경기만")를 브래킷 탐색 없이 직접 해결. 모바일 최적.
- 단점: 대진표 맥락(어느 산에서 만나는가)이 약함 — A안과 병행해야 완결.

**권고**: A안 + C안 병행(서로 보완), B안은 후순위 데스크톱 옵션.

### C-3. 경기 블록 클릭 → 매치 시트 (문제 2)

`.bracket-match`/`.match-card` 전체를 클릭 타깃으로 (선수명 링크는 유지, 클릭 버블 구분). 클릭 시 모바일=바텀시트, 데스크톱=우측 슬라이드 패널:

```
┌─ 64강 · Match 7 ──────────────────────────── ✕ ─┐
│  [3] 박소윤 · 최병철펜싱클럽      15 : 9   [30] 김OO │   ← .fm-num 점수
│  ● 상대 전적  박소윤 2승 1패  (최근 15-13 승 · 2026 회장기 16강)│
│──────────────────────────────────────────────│
│  이후 예상 경로            ⚠ 시드 기준 예상입니다     │
│  32강  vs [14] 이OO  또는 [19] 정OO   (전적 1-0 / 첫 대결)│
│  16강  상대 후보 4명 ▾                              │
│  8강   상대 후보 8명 ▾                              │
└──────────────────────────────────────────────┘
```

- 데이터: 전적 = 기존 EventH2H 일괄 응답 재사용(내 선수 기준) + 임의 두 선수는 `/api/players/{a}/head-to-head/{b}`. 예상 경로 = de-prediction(단, D-Phase 3에서 Dual DE·256강 대응 수리 후).
- **제1원칙 준수**: 예상 블록에는 항상 "시드 기준 예상" 배지 + 점선 테두리. 확정 결과와 시각적으로 절대 혼동되지 않게(확정=실선+점수, 예상=점선+상대 후보).
- 애니메이션: 시트 slide-up/fade(transform·opacity만), 예상 경로 행 60ms 스태거 등장, 클릭한 블록에서 시트로 이어지는 강조는 블록 테두리 펄스 1회. `width/max-height/padding transition` 금지 패턴 회피, `prefers-reduced-motion`에서 즉시 표시.
- 라운드 승격 애니메이션(선택): 결과 갱신 시 승자 행이 다음 라운드 방향으로 살짝 이동했다 복귀하는 마이크로 모션 — 후순위.

### C-4. 경기 전 / 경기 후 상태별 화면

| 상태 | 예선 DE 탭 | 본선 DE 탭 | 매치 시트 |
|---|---|---|---|
| 대진 발표 전 | 시딩(풀 순위)만 + "대진 준비 중" | 잠금 해제하되 "시드 32명 확정, 상대 미정" 안내 | — |
| 예선 진행 중 | **기본 진입.** 진행바 + 내 선수 스트립. 미완 경기 = 점수 "-", 예정 배지 | 비활성 아님 — 열람 가능하되 "예선 진행 중, 본선 대진은 예선 종료 후 확정" 배너 | 완료 bout=결과 중심, 미래 bout=예상 중심 |
| 예선 완료 | 진출자 32명 명단 강조(현행 qualifiers 섹션 강화) | 확정 대진 표시 시작 | 예상→확정 상대로 치환 |
| 본선 진행 중 | 열람 가능(기록 보존) | **기본 진입** | 동일 |
| 종료 | 기록 뷰 | Champion + 최종순위 연결 | 결과 전용(예상 섹션 숨김) |

핵심 원칙: 탭을 disabled로 잠그는 현행 방식(dual-bracket-tabs.html:37) 대신 **열람은 항상 허용, 기본 진입만 상태로 제어**. 잠긴 탭은 "왜 안 눌리는지"를 설명하지 못한다.

### C-5. 모바일 (1차 사용자: 대회장의 학부모)

- 리스트뷰를 모바일 기본 유지(현행 자동 전환 유지, bracket.html:539~548). 라운드 탭의 기본 선택 로직(미완료 첫 라운드, bracket.html:183~199)은 유효 — 유지.
- 내 선수 스트립은 하단 내비(56px) 위 sticky. 칩은 가로 스크롤.
- 매치 시트 = 바텀시트(기존 온보딩 시트 패턴 재사용), 스와이프 다운 닫기.
- 트리뷰는 모바일에서 가로 스크롤 지옥이므로 진입 자체를 권하지 않되, "전체 대진표 보기" 버튼으로 명시적 진입만 허용.
- 성능: 128강 트리뷰 DOM이 수천 노드 — 초기 렌더는 현행 Jinja2 SSR 유지하되, 매치 시트·스트립의 JS는 이벤트 위임 1개 리스너로.

---

## D. 구현 계획 (단계별 독립 배포)

### Phase 0 — 데이터 무결성 복구 (다른 모든 것의 전제, 화면 변경 없음)

| 파일 | 변경 |
|---|---|
| `app/bracket_utils.py:1874` | `bout.get('match_num', bout.get('match_number', 0))` — 키 이중 지원 (P1) |
| `app/bracket_utils.py:2060~2063` | first_de_complete 판정을 first_de.rounds 마지막 라운드 기준으로 일반화 (P3 절반) |
| `scraper/full_scraper.py` | 128 브래킷 First DE 마지막 라운드(64강) 수집 경로 조사·수정 후 해당 이벤트 재스크랩 (P2). KFA가 진실의 원천 — 재스크랩으로만 복구, 수기 보정 금지 |
| `app/data_validator.py` | 신규 규칙 R24 후보: dual_de에서 공유 라운드 bout 수 = second_bracket_size/2 검증, first_de_qualifiers 수 검증 |

- 검증: `PYTHONPATH="." python scripts/run_validation.py` ERROR 0건 + 남자 에페 페이지에서 First DE 3라운드/본선 64강 32경기 확인.
- 회귀 위험: **높음** — `normalize_dual_de_bracket_data` 분배 결과가 바뀌면 QF 그룹 색(DOM 순서 기반), status, 진행바, de-prediction 완료 라운드 판정이 연쇄로 변한다. 과거 dual_de 이벤트(2026 국가대표 선발전 등) 전수 스팟체크 필요.

### Phase 1 — 용어·진입·설명의 데이터화 (템플릿 중심, 소규모)

- `dual-bracket-tabs.html`: 한국어 주표기 병기(C-1), 배너·진행바 문구를 bracket 데이터로 동적 생성(P7·P8), 탭 disabled → 열람 허용+안내로 전환.
- `dual-bracket.js`: restoreState에 status 스탬프 비교 추가(P13), 내 선수 phase 보정.
- `bracket_utils.py:156~162` 중복 문구 제거.
- 독립 배포 가능. 위험: 낮음. **캐시버스터(`base.html ?v=`) 필수.**

### Phase 2 — 내 선수 우선 (JS/CSS 중심)

- `player-search.js`: `.bracket-match` 셀렉터 추가(P4), `highlightMany()` 다중 하이라이트, 순회 API.
- `player-search.css`/`bracket.css`: `.bracket-match.player-highlighted` — `--fm-accent-primary` 보더+은은한 배경, 색 외 채널(⭐/보더 두께) 병용.
- `event_result.html`: DE 탭 내 선수 스트립(A안) — 기존 `getMyPlayerNames`·de-results 재사용. `findAndHighlightPlayer()` 수리·연결 또는 삭제.
- 독립 배포 가능. 위험: 중간 — 하이라이트 셀렉터 확대가 Pool 쪽 기존 동작과 간섭하지 않는지, i18n(로마자 표기) 매칭 확인.

### Phase 3 — 선수 루트 재편 + 매치 시트

- 서버: `NormalizedDualDEBracket.to_dict()`에 통합 참가자 목록(또는 `get_dual_de_combined_seeding` 활용) 노출(P6). `de-prediction`에 256강 지원·Dual DE phase 인식(P9) — Second DE는 본선 시딩으로 계산, First DE는 예선 시딩으로.
- `event_result.html`: 선수 루트 → "내 선수 여정" 개편(C안), 매치 시트 컴포넌트(C-3) + 이벤트 위임.
- 위험: 중간~높음 — de-prediction 수정은 선수 프로필 등 다른 소비처가 없는지 확인(현재 event_result 전용으로 보이나 재확인 필요).

### Phase 4 — 스타일 토큰화 디자인 패스

- `bracket.css` 146개 hex → `--fm-*` 토큰, 파랑 슬레이트 → 태극 팔레트, 점수 `.fm-num` 적용, 라이트 테마 오버라이드 축소, QF 그룹 색 인라인 스타일을 CSS 파일+토큰 파생으로 이관(P12).
- 검증: `node ~/.claude/skills/impeccable/scripts/detect.mjs --json` 재실행.
- 위험: 낮음(시각 전용)이나 범위가 넓어 스크린샷 회귀 비교 권장.

### 공통 위험 요소

1. **Cloudflare 캐시**: CSS/JS 수정마다 `?v=` 범프 필수 (2026-08-06 사고 재발 방지).
2. **완료 대회 데이터 재스크랩**: 스케줄러와 경합하지 않도록 단발 실행, KFA 원본과 diff 로그(`validation_logs`) 남길 것.
3. **normalize 계층의 소비처 다수**: `_get_full_bouts_from_de_bracket`은 선수 프로필·H2H·랭킹 추출 등 10+ 곳에서 사용(server.py grep 기준). 분배 수정은 이 함수 출력에는 영향 없음(최상위 full_bouts 그대로)을 확인했으나, `normalized_bracket` 소비처(de-prediction:3766, de-results:4352)는 영향권.
4. **localStorage 마이그레이션**: `dualDE_phase_{eventId}` 기존 값이 새 규칙과 충돌 — status 스탬프 도입 시 구값 무시 처리.

---

## 요약 (핵심 발견과 권고)

1. **64강 소실의 원인은 두 개**: 남자 에페는 `bracket_utils.py:1874`의 `match_num`(실제 키 `match_number`) 오타로 First DE 64강 32경기가 전부 본선으로 흡수(본선 64강이 64경기로 오염), 여자 에페·플뢰레는 First DE 64강 32경기가 **스크래핑 자체에서 누락**(127/159개)돼 데이터에 없다.
2. "128강 → Second DE"는 First DE 진행바의 고정 스텝으로, 64강 소실 때문에 절단돼 보이는 것이며, 그 위 배너 문구는 브래킷 크기와 무관한 하드코딩이라 256 브래킷에서도 "128강→64강 2라운드"라고 거짓 표시한다.
3. 예선 중 본선 탭으로 튕기는 문제(사용자 5번)는 status 파생 로직의 구조적 귀결: first_de_completed는 현행 데이터에서 도달 불가능하고, First DE 64강이 스크랩되는 순간 second_de_in_progress가 된다.
4. "선수 루트"는 완료 경기(de-results)+예상 상대(de-prediction, 시드 수학) 합성 위젯인데, Dual DE에서는 드롭다운이 **시드 32명만** 노출되고(to_dict에 seeding 부재) 예측 엔진은 256강·Dual DE를 모른다.
5. "내 선수" 기능은 DE에서 사실상 부재: 데스크톱 트리뷰(.bracket-match)는 하이라이트 셀렉터에서 빠져 있어 무동작, 다중 표시·점프·순회 없음, phase 점프 함수는 미호출 사장 코드다.
6. 권고 우선순위: **Phase 0(분배 키 수정+재스크랩+검증 규칙) → 용어·진입 데이터화 → 내 선수 스트립+다중 하이라이트 → 매치 시트+루트 재편 → CSS 토큰화**. 각 단계 독립 배포 가능하며, Phase 0 없이는 어떤 UI 개선도 틀린 데이터를 예쁘게 만드는 일이 된다.
