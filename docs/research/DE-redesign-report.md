# DE(Direct Elimination) 화면 전면 재설계 연구 보고서

- 작성일: 2026-08-17 (v2 — 메인 세션 추가 데이터 반영, raw 하위 구조 재검증)
- 범위: `services/data`의 DE 대진표 전체 (단일 DE + Dual DE), 관련 서버 변환·API·템플릿·JS·CSS
- 방법: 코드 정독 + Supabase raw 데이터 SQL 검증 + 프로덕션 DOM 실측 (읽기 전용, 코드 미수정)
- 검증 대상 실데이터: 제66회 대통령배 겸 국가대표선수 선발대회 (`COMPM00722`)
  - 남자 플뢰레(개) `COMPS000000000004155` · 남자 에페(개) `COMPS000000000004156`
  - 여자 플뢰레(개) `COMPS000000000004158` · 여자 에페(개) `COMPS000000000004159`

표기 원칙: **[확인]** = 코드/데이터/DOM으로 검증된 사실, **[추정]** = 정황상 유력하나 추가 확인 필요.

---

## A. 현황 규명 (증거 기반)

### A-1. Dual DE 데이터 흐름 (서버 → 클라이언트)

스크래퍼가 저장하는 raw 구조 (`DualDEBracket.to_dict()`, scraper/de_scraper_v4.py:144~178):

```
events.raw_data.de_bracket
  ├─ format: "dual_de", status(스크랩 시점 스냅샷), champion, participant_count
  ├─ first_de:  {bracket_size, starting_round, rounds, bouts, bouts_by_round, seeding, ...}
  ├─ second_de: {bracket_size, starting_round, rounds, bouts, bouts_by_round, seeding, ...}
  ├─ full_bouts: first_de.bouts + second_de.bouts 를 합쳐 top-level에 복제 (149~153행)
  ├─ seeded_players, first_de_qualifiers
```

**핵심 [확인]**: phase별로 올바르게 분리된 bout 데이터가 `first_de.bouts` / `first_de.bouts_by_round`에 **이미 존재한다**. `first_de.full_bouts`라는 키는 원래 없다 — top-level `full_bouts`만 합본으로 존재한다. (실측: 남에 first_de.bouts=224, second_de.bouts=63, top full_bouts=287)

렌더링 파이프라인:

```
server.py:7037 transform_de_bracket()
  → normalize_bracket_data() → is_dual_de_format() (bracket_utils.py:720, 1793)
    → normalize_dual_de_bracket_data() (bracket_utils.py:1820)
      ① 하위 브래킷의 'full_bouts' 키만 검사 (1845~1846)  ← 🔴 버그 1
      ② 비었다고 판단 → top-level full_bouts를 재분배 (1848~1883)
         공유 라운드 분리 시 'match_num' 키 참조 (1874)   ← 🔴 버그 2
      ③ 재분배로 주입된 full_bouts가 원본 bouts를 가림
         (normalize_bracket_data가 full_bouts 최우선, 757~759)  ← 🔴 증폭 지점
  → NormalizedDualDEBracket.to_dict() → event.normalized_bracket
  ↓
event_result.html:1580 → components/dual-bracket-tabs.html (First/Second 탭)
  → 각 phase마다 components/bracket.html include (트리뷰/리스트뷰)
  ↓
static/js/dual-bracket.js DualDEController (data-status 기반 탭 자동 선택)
```

API 계열(`de-results`, `de-prediction`, 선수 프로필 등)은 `_get_full_bouts_from_de_bracket()`(de_transforms.py:188)로 **phase 구분 없는 합본**을 사용한다. dual_de일 때 하위에서 재귀 추출+`de_phase` 태깅하는 경로(de_transforms.py:204~216)가 있으나, 이 역시 하위 `full_bouts` 키를 찾으므로 현행 데이터에서는 top-level 합본이 그대로 흐른다. **[확인]**

### A-2. 🔴 "64강이 사라진" 근본 원인 — 렌더링 버그 체인(남에) + 스크랩 누락(128 브래킷 3종목)

#### A-2-1. 4종목 raw 데이터 전수 실측 [확인]

| 종목 | top full_bouts | first_de.bouts (라운드 구성) | second_de.bouts | seeded | 그중 seed>32 | qualifiers | raw status |
|---|---|---|---|---|---|---|---|
| 남자 에페 | 287 | **224** (256강 128 + 128강 64 + **64강 32**) | 63 (64강 32~결승 1) | 31 | 0 | **32** | first_de_in_progress (낡음) |
| 남자 플뢰레 | 127 | 64 (**128강만**) | 63 | 64 | **32** | **0** | completed |
| 여자 플뢰레 | 127 | 64 (**128강만**) | 63 | 64 | **32** | **0** | completed |
| 여자 에페 | 127 | 64 (**128강만**) | 63 | 64 | **32** | **0** | completed |

#### A-2-2. 남자 에페(256 브래킷): 데이터는 완전한데 렌더링 파이프라인이 3중으로 훼손한다 [확인]

raw에는 First DE 64강 32경기가 `first_de.bouts_by_round['64강']`에 **정확히 분리 저장**돼 있다(SQL 실측: {256강:128, 128강:64, 64강:32}). 그런데:

1. **버그 1 — 잘못된 키 검사** (bracket_utils.py:1845~1846):
   ```python
   first_de_has_bouts = bool((first_de_raw.get('full_bouts') or []))   # 실키는 'bouts'
   second_de_has_bouts = bool((second_de_raw.get('full_bouts') or []))
   ```
   하위 브래킷에 `full_bouts` 키가 없으므로(스크래퍼는 `bouts`로 저장) 항상 False → "하위가 비었다"고 오판, top-level full_bouts **재분배 분기**로 진입한다. 올바른 데이터가 있는데도 재조립을 시작하는 것이 사고의 출발점이다.

2. **버그 2 — 재분배 시 존재하지 않는 키 참조** (bracket_utils.py:1874):
   ```python
   match_num = bout.get('match_num', 0)   # 실데이터 키는 'match_number' (전 bout SQL 확인: match_num 0건)
   if match_num <= max_second_de_match:   # 항상 0 <= 32
       second_de_bouts.append(bout)
   ```
   공유 라운드(64강) 64경기(예선측 match_number 193~224 + 본선측 1~32)가 **전부 Second DE로** 들어간다.

3. **증폭 — 주입된 full_bouts가 원본을 가림** (bracket_utils.py:757~759): `normalize_bracket_data`는 `full_bouts`를 최우선 소스로 쓰므로, 재분배로 주입된 오염본이 하위의 올바른 `bouts`/`bouts_by_round`를 덮는다.

**프로덕션 DOM 실측 결과 [확인]**: First DE 패널 = 256강(128경기)+128강(64경기)만(64강 소실), Second DE 패널 = "64강 **64경기**"(정상 32) — 예선 64강 32경기가 본선 대진표에 섞여 표시 중.

> 버그 1만 고쳐도(하위 `bouts`/`bouts_by_round` 인정) 재분배 분기 자체를 타지 않으므로 남에는 **재스크랩 없이 코드만으로 복구 가능**하다. 버그 2는 그래도 방어적으로 함께 수정해야 한다(하위가 정말 빈 이벤트 대비).

#### A-2-3. 128 브래킷 3종목(남플·여플·여에): First DE 64강이 스크랩 자체에서 누락됐다 [확인]

phase별 raw를 직접 보면 `first_de.rounds = ['128강']`, `bouts_by_round = {128강: 64}` — **예선 64강이 raw 어디에도 없다**. 저장된 유일한 64강(32경기)은 second_de 소속이다. 여자 에페로 교차 검증:

| 검증 항목 | 결과 |
|---|---|
| 시드 1~32가 128강에 출전했는가 | **0명** (예선 면제 확인) |
| 시드 1~32가 64강(저장분)에 출전했는가 | 32명 전원 → 저장된 64강 = **본선 64강** |
| seeded_players의 33~64번이 128강에 출전했는가 | **32명 전원** (예선 참가자) |
| 그 33~64번이 64강(본선)에도 출전했는가 | 32명 전원 → **이들이 곧 예선 통과자 32명** |
| 128강 승자(61명) 중 64강 등장 인원 | 30명 (2명은 이름 표기/승자 미기록 편차) |

즉 128강 승자 약 61~64명 → 본선 비시드 슬롯 32명. DE에서 인원이 절반이 되려면 경기가 있어야 하므로 **예선 64강(32경기)은 실제로 치러졌으나 수집되지 않았다**. 기대 총량 159개 중 127개만 존재.

**"단일 128 토너먼트를 dual로 오분류했다"는 가설은 기각된다 [확인]**: 시드 32명이 128강에 전혀 등장하지 않고(0/32), 스크래퍼가 KFA의 예선/본선 페이지(schEtc01 셀렉터)를 **별도로 방문해 별도 저장**했으며(first_de/second_de가 독립 파싱본), 참가 구조도 "비시드 121명 예선 + 시드 32명 본선 직행"으로 전형적 Dual DE다. 127 = 64+63이 단일 128 브래킷 경기수와 우연히 같을 뿐이다.

**qualifiers=0·seeded=64의 정체 [확인]** — 스크래퍼 유도 로직의 연쇄:
- 진출자 추출 = "first_de의 64강 승자"(de_scraper_v4.py:1706~1720) → 예선 64강이 없으니 **0명**.
- 시드 추출 = "second_de 시딩 − 진출자 명단"(1722~1740) → 진출자가 빈 집합이라 **시딩 64명 전원이 seeded_players로** 저장됐다.
- 이후 정규화는 seed ≤ 32만 시드로 채택(bracket_utils.py:1941)하므로 33~64번(=실제 진출자 32명)은 **어느 목록에도 잡히지 않고 증발**한다. → 프로덕션 배너의 "First DE 진출자 **0명** = 총 64명" 모순 문구.
- 역으로 말하면, **진출자 명단은 재스크랩 없이도 seeded_players의 seed 33~64에서 복원 가능**하다(단, 예선 64강의 경기 내용·점수는 재스크랩 필요).

**[추정]** 누락 원인: 스크랩 시점에 KFA 예선 DE 페이지가 128강만 게시 중이었고(64강은 이후 진행), 이벤트 완료 후 재스크랩이 first_de 페이지를 다시 걷지 않았거나 걷었어도 덮어쓰지 않았을 가능성. 남에의 raw status가 'first_de_in_progress'로 낡아 있는 것도 같은 정황(마지막 dual 파싱이 예선 진행 중 시점). `scraper/full_scraper.py:1108~1113`·`de_scraper_v4.py:1633~1698`의 재스크랩 시나리오를 KFA 실페이지와 대조해 확정해야 한다.

### A-3. "128강 → Second DE" 표시의 정체

`dual-bracket-tabs.html:119~140`의 **First DE 진행 표시 바**다. `first_de.rounds`를 순회해 라운드 스텝을 그리고 마지막에 고정 스텝 `→ Second DE`(136행)를 붙인다. 여자 에페는 first_de.rounds=['128강']뿐이라 화면에 **"128강 64/64 → Second DE"**만 남는다. **[확인 — DOM]** 오류 산출물이 아니라 진행바인데, (a) 예선 64강 누락으로 절단됐고, (b) "→ Second DE"가 무엇이 몇 명 넘어간다는 것인지 설명이 없다.

그 위 안내 배너의 문자열 출처를 분해하면 (dual-bracket-tabs.html:112~115) **[확인]**:

```jinja2
비시드 선수 {{ dual_bracket.first_de_participant_count }}명이 32강 진출을 위해 경쟁합니다.
128강(64경기) → 64강(32경기) 2라운드를 거쳐 32명이 Second DE로 진출합니다.
```

- `121명` — **유일한 동적 값.** raw `first_de.participant_count`는 0으로 저장돼 있으므로(SQL 확인) 정규화가 시딩/bout에서 계산한 값이다.
- `32강 진출`, `128강(64경기) → 64강(32경기) 2라운드`, `32명` — **전부 하드코딩.** 256 브래킷인 남자 에페에도 같은 문장이 나가고(DOM 확인), "32강 진출"은 실제로는 "본선 64강 진출"이므로 내용도 틀렸다. 브래킷 크기가 다르면 즉시 거짓말이 되는 구조다.

### A-4. "선수 루트" 위젯의 실제 동작 규명

위치: `event_result.html:1523~1577`(마크업/스타일), `2510~2692`(JS).

**드롭다운 대상 선정 [확인]** (event_result.html:1524~1527):

```jinja2
{% if event.normalized_bracket.seeding %}          {# 단일 DE: 브래킷 시딩 전원 #}
{% elif event.normalized_bracket.seeded_players %} {# Dual DE: 이쪽으로 폴백 #}
```

`NormalizedDualDEBracket.to_dict()`(bracket_utils.py:129~140)에는 `seeding` 키가 없어 Dual DE는 항상 `seeded_players`로 폴백 → **시드 상위 32명만** 나온다. 단일 DE에서는 참가자 전원이 나온다. 사용자가 "전체인지 시드만인지 헷갈린다"고 한 것은 정확하다 — **이벤트 형식에 따라 대상이 달라진다.** Dual DE에서 First DE를 뛰는 비시드 선수(대다수 학부모의 자녀)는 선택 자체가 불가능하다.

**표시 내용 [확인]** — 선택 시 두 API를 병렬 호출해 합성(2640~2644):

1. `/api/events/{cd}/de-results/{name}` (server.py:4280): 완료된 DE 경기 — 라운드·상대·점수·승/패/부전승.
2. `/api/events/{cd}/de-prediction/{name}` (server.py:3717): 미래 라운드별 **잠재 상대 후보** — 시드 위치 기반 브래킷 수학(3937~), 실제 참가자 필터.

렌더(2542~2634): 완료 라운드 = 승/패/부전승 노드, 탈락·우승 시 종료 노드+최종순위 비동기 채움, 진행 중이면 미래 라운드를 점선 노드로 "상대 후보 N명" 나열(최대 8명).

**한계 [확인]**: de-prediction의 라운드 목록에 256강이 없고(server.py:3800), Dual DE를 인식하지 못한다(phase 혼합 full_bouts로 완료 라운드 판단(3844), 시드는 `de_bracket.seeding`(dual raw에 없음)→풀 순위 폴백(3788)). 예선 시드 체계와 본선 시드 체계(1~64 재부여)가 다른데 하나의 브래킷 수학에 밀어 넣는다. "예상"임을 알리는 표시도 점선+"다음" 뿐으로 약하다.

**기본 선택 [확인]** (2677~2688): `?highlight` → 내 선수(localStorage) → 즐겨찾기 순 자동 선택. 위젯 사상은 이미 "내 선수 우선"이나, Dual DE에서 내 선수가 비시드면 드롭다운에 없어 자동 선택이 실패한다.

### A-5. 현행 "내 선수" 하이라이트가 DE에서 사실상 동작하지 않는 이유

내 선수 인프라 자체는 있다: localStorage 단일 My Player + 서버 즐겨찾기 병합(`getMyPlayerNames`, event_result.html:2184~2213), Pool 탭의 풀 점프 바·풀 버튼 마킹(1327, 2262~2292), EventH2H 상대전적 배지(2700~). 그러나 **DE 대진표에서는**:

1. **트리뷰(데스크톱 기본)가 하이라이트 셀렉터에서 빠져 있다 [확인]**. `PlayerHighlighter.highlight()`(player-search.js:223~302)의 DE 관련 셀렉터는 `.bout-player`, `.match-card`, `.bracket-bout, .bout-card`뿐. 트리뷰 경기 블록은 **`.bracket-match`**(bracket.html:97)인데 어디에도 없고, `player-search.css:88~124`에도 해당 규칙이 없다 → 데스크톱 트리뷰에서 하이라이트 **무동작**. (EventH2H 배지는 `.bracket-match`를 제대로 순회한다 — event_result.html:2855. 같은 파일에서 셀렉터 목록이 분기돼 있는 것.)
2. **단일 선수·색상 1종**: `highlight()`는 호출 시 이전 것을 `clear()` — 여러 명 동시 표시 불가. 효과는 `player-highlighted` 클래스(색 배경) 하나.
3. **이동 보조 없음**: 첫 발견 요소 `scrollIntoView` 1회(298행)뿐. 순회·미니맵·현재 위치 표시 없음. Dual DE용 phase 전환+스크롤 함수 `findAndHighlightPlayer()`(dual-bracket.js:336~389)가 있으나 **호출부가 없는 사장 코드**이고, 그마저 `.bracket-match`를 검색하지 않는다(395행). **[확인]**
4. Pool 탭의 "내 선수 풀 보기" 같은 원클릭 진입 장치가 DE 탭에는 없다.

### A-6. 탭 진입 규칙(문제 5): 현행 메커니즘과 신뢰할 수 없는 메타데이터

**진입 결정 [확인]**: `dual-bracket.js restoreState()`(181~206) — `data-status`가 `second_de_in_progress`/`completed`면 Second DE 자동 전환, 아니면 localStorage 저장값, 최후 First DE.

**status의 출처가 둘이며 둘 다 문제다 [확인]**:

| 출처 | 위치 | 상태 |
|---|---|---|
| raw `de_bracket.status` | 스크래퍼가 파싱 시점에 기록 (de_scraper_v4.py:1742~1779) | **낡은 스냅샷.** 남에는 결승까지 다 끝났는데 'first_de_in_progress'로 저장돼 있음(SQL 확인). 다행히 **렌더러는 이 값을 읽지 않는다** — 정규화가 매 요청 재계산(bracket_utils.py:1966) |
| 계산 status | `_determine_dual_de_status`(bracket_utils.py:2037~2085) | **구조적 오류.** ① first_de_complete 판정이 "first_de의 64강 32경기 전부 완료" 하드코딩(2060~2063) — A-2의 두 원인으로 first_de에 64강이 절대 없어 **first_de_completed 도달 불가능**. ② second_de에 bout이 하나라도 있으면 즉시 second_de_in_progress(2066, 2078) — 버그 2로 예선 64강 bout이 스크랩되는 순간 second_de로 분류돼 **예선 중에 본선 탭으로 자동 진입** |

기타 신뢰 불가 메타데이터 **[확인]**: 4종목 모두 `champion`이 null(결승 결과는 존재), `events.has_first_de`/`has_second_de` 컬럼이 4종목 전부 false(`de_format='dual_de'`인데). has_* 는 pipeline_scraper.py:311~331이 쓰는데 first_de 키가 실존하는데도 false인 이유는 저장 경로 이원화로 보인다 **[추정 — 저장 시점 재현 필요]**.

**→ 탭 진입 규칙을 raw status·has_* 컬럼에 의존해 설계하면 안 된다.** 대안 판정 기준은 C-1에 제시.

부가: localStorage 저장 phase가 다음 방문에서 status 판단보다 우선하는 구간(dual-bracket.js:190~199)이 있어, 상태가 진전돼도 낡은 탭이 열릴 수 있다.

### A-7. 용어(문제 6) 현행 표기

`dual-bracket-tabs.html:28~29, 39~40`:

```
[크게] First DE    [작게] 예선 DE (32명의 면제자가 있는 예선엘리미나시옹디렉트)
[크게] Second DE   [작게] 본선 DE (64강)
```

한국어 UI인데 영문이 주(主), 한국어가 부(副)이고, "32명의 면제자가 있는 예선엘리미나시옹디렉트"는 학부모 1차 사용자에게 해독 불가능하다. 같은 문구가 `bracket_utils.py:156~162`에도 중복 정의돼 있다.

### A-8. 기타 확인 사항

- **Dual DE 최종순위 동적 계산이 현행 데이터에서 불능 [확인]**: `server.py:7045~7051`의 `has_second_de` 게이트와 `compute_dual_de_final_rankings()`(de_transforms.py:441~445) 모두 `second_de.bouts/full_bouts`를 보는데, `bouts` 키는 존재하므로 게이트는 통과하나 계산 함수 내부의 시딩·라운드 파싱이 top-level 오염본과 별개로 동작해 검증 필요. 현재는 KFA 스크랩 final_rankings가 가려주고 있다.
- **스타일 부채 [확인]**: `bracket.css` 하드코딩 hex **146개**, 파랑 슬레이트 팔레트(#2a3f5f, #3b82f6, #60a5fa) — 확정 디자인 방향(태극+`--fm-*` 토큰)과 상이. 트리뷰 라운드 연결선은 우측 20px 수평선 1개(`.match-connector`, bracket.css:533)로 다음 경기와 시각적으로 이어지지 않음. QF 그룹 8색은 `bracket.html:318~366`에 rgba 하드코딩+`!important` 인라인이고 그룹 산정이 DOM 순서 나누기(405~452)라 분배 수정 시 색이 어긋날 수 있다.
- **경기 블록 클릭 동작 없음 [확인]**: `.bracket-match`/`.match-card`에 클릭 핸들러 없음(선수명 링크만). 요구 기능(블록 클릭 → 예상 상대/전적)의 기반 전무.
- **dual-bracket.js 이중 로드 가능 [확인]**: 컴포넌트(dual-bracket-tabs.html:247)와 event_result.html(1909 부근) 양쪽 — defer라 실해 없으나 정리 대상.

---

## B. 문제 목록 (근거·심각도·사용자 영향)

| # | 문제 | 근거 (파일:줄) | 심각도 | 사용자 영향 |
|---|---|---|---|---|
| P1 | 렌더링 버그 체인: ① 하위 브래킷 `full_bouts` 키만 검사(실키 `bouts`) → 불필요한 재분배 진입 ② 재분배가 `match_num`(실키 `match_number`) 참조 → 64강 전량 본선행 ③ 주입 full_bouts가 원본 bouts를 가림. 결과: 남에 예선 64강 소실 + 본선 64강 64경기 오염 | bracket_utils.py:1845~1846, 1874, 757~759 · SQL·DOM 실측 | **치명** | 올바른 raw가 있는데 예선·본선 둘 다 틀리게 표시. 제1원칙 위반 상태. 코드만으로 복구 가능 |
| P2 | 128 브래킷 3종목(남플·여플·여에) 예선 64강 32경기 스크랩 누락(127/159). phase별 raw로 확정. 진출자 명단은 seeded_players seed 33~64에 잠복(경기 내용은 재스크랩 필요) | first_de.rounds=['128강'] SQL · de_scraper_v4.py:1706~1740 · [누락 시점은 추정] | **치명** | 여자·남플 예선 후반 경기가 사라짐. "진출자 0명 = 총 64명" 모순 노출 |
| P3 | 계산 status 구조 오류: first_de_completed 도달 불가(64강 하드코딩) + 예선 64강 스크랩 즉시 second_de_in_progress → 예선 중 본선 탭 자동 진입. raw status·has_* 컬럼은 낡거나 불일치라 대체재도 못 됨 | bracket_utils.py:2060~2063, 2078 · dual-bracket.js:181~206 · SQL(raw status/has_*) | **높음** | 대회 당일 학부모가 엉뚱한 탭에 진입 (문제 5의 원인) |
| P4 | 트리뷰 `.bracket-match`가 하이라이트 셀렉터·CSS에 미포함 → 데스크톱 DE 하이라이트 무동작 | player-search.js:243~294 · player-search.css:88~124 · bracket.html:97 | **높음** | "내 선수 찾기" 핵심 기능이 기본 뷰에서 작동 안 함 |
| P5 | 하이라이트 단일 선수·색 1종·1회 스크롤. 다중/순회/미니맵 없음. phase 점프 함수는 미호출 사장 코드 | player-search.js:223~309 · dual-bracket.js:336~389 | **높음** | 128강 50+ 경기에서 색만으로 탐색 (문제 1·4) |
| P6 | 선수 루트 대상이 형식별로 다름: Dual DE=시드 32명만(to_dict에 seeding 부재), 단일 DE=전원 | event_result.html:1524~1527 · bracket_utils.py:129~140, 1941 | **높음** | 비시드 선수(대다수) 선택 불가, 위젯 개념 불투명 (문제 2 후반) |
| P7 | First DE 배너·진행바 하드코딩: "32강 진출", "128강→64강 2라운드", "32명", "→ Second DE" — 동적 값은 참가자 수 하나뿐. 256 브래킷에도 동일 문구 | dual-bracket-tabs.html:112~115, 134~137 | 중간 | 데이터와 다른 설명 = 신뢰 훼손, "→ Second DE" 해석 불가 (문제 3) |
| P8 | 용어: 영문 주표기 + "32명의 면제자가 있는 예선엘리미나시옹디렉트" (중복 정의) | dual-bracket-tabs.html:28~29,39~40 · bracket_utils.py:156~162 | 중간 | 초심 사용자 개념 이해 실패 (문제 6) |
| P9 | de-prediction 256강 미지원·Dual DE 미인식(시드 폴백=풀순위, phase 혼합) | server.py:3800, 3788~3797, 3844 | 중간 | 선수 루트 "예상 상대"가 대형 대회에서 부정확 |
| P10 | Dual DE 최종순위 동적계산 경로 신뢰 불가(오염본/키 불일치와 얽힘, 미검증) | server.py:7045~7051 · de_transforms.py:408~ | 중간 | KFA 순위 미게시·스크랩 실패 시 폴백 부재 |
| P11 | 경기 블록 클릭 인터랙션 전무 | bracket.html:97~147, 230~300 | 중간 | 문제 2 요구 기능 기반 부재 |
| P12 | bracket.css 하드코딩 hex 146개, 파랑 슬레이트 팔레트, QF 8색 rgba+!important 인라인 | bracket.css 전반 · bracket.html:318~366 | 중간 | 확정 디자인 방향 위반, 라이트 테마 이중 유지비 |
| P13 | 메타데이터 전반 신뢰 불가: raw status 낡음(남에), champion 4종목 null, has_first_de/has_second_de 전부 false | SQL 실측 · de_scraper_v4.py:1742~1779 · pipeline_scraper.py:311~331 | 중간 | 이 필드에 기대는 신규 코드가 생기는 순간 오판. 탭 규칙 설계의 제약 조건 |
| P14 | localStorage 저장 phase가 상태 변화보다 우선하는 복원 구간 | dual-bracket.js:190~199 | 낮음 | 재방문 시 낡은 탭 진입 |
| P15 | seeded_players에 진출자 32명이 seed 33~64로 섞여 저장, ≤32 필터로 증발 · dual-bracket.js 이중 로드 | de_scraper_v4.py:1722~1740 · bracket_utils.py:1941 · dual-bracket-tabs.html:247 | 낮음 | 진출자 명단 미표시(P2 부수 효과) · 유지보수 부채 |

---

## C. 재설계안

전제: FastAPI + Jinja2 + 바닐라 JS 유지, 외부 CDN 금지, 색은 `--fm-*` 토큰만(태극 적/청 + 메달 골드), 숫자는 `--fm-font-display`+`.fm-num`, 예상 데이터는 반드시 "예상" 라벨(제1원칙 — 추정치를 확정처럼 보이지 않게).

### C-1. 정보 구조: 탭 계층·진입 규칙·용어

**탭 구조(유지 + 재표기)** — Dual DE 2탭 구조 자체는 유효하다. 표기를 한국어 주(主)로 뒤집는다:

```
┌──────────────────────────────┬──────────────────────────────┐
│  예선 DE                      │  본선 DE                      │
│  First DE · 128강→64강        │  Second DE · 64강→결승        │
│  ● 진행 중 (64강 12/32)       │  ○ 예선 종료 후 시작           │
└──────────────────────────────┴──────────────────────────────┘
```

- phase-label = "예선 DE"/"본선 DE" (크게), sublabel = "First DE"/"Second DE" (작게) — 문제 6 그대로. en에서는 표기 역전.
- 라운드 범위·배너 문구는 **전부 데이터에서 동적 생성** (P7 해소): "시드 상위 {seeded_count}명을 제외한 {first_de_participant_count}명이 {first_de.rounds[0]}부터 겨루고, {first_de 마지막 라운드} 승자 {진출자 수}명이 본선 {second_de.starting_round}에 합류합니다."
- "면제자" → "시드 (예선 면제)". 개념 설명은 기존 `.fm-help` 툴팁으로: "본선 DE = 시드 {n}명 + 예선 통과 {m}명이 {시작라운드}부터 겨루는 본 토너먼트".
- 진행바의 "→ Second DE" 스텝 → "**본선 진출 {n}명**"으로 교체, 완료 시 실데이터로 채움.

**First DE 완료 판정 — status·has_* 컬럼 의존 금지 (P3·P13 대응).** 경기 데이터에서 직접 판정한다:

| 기준 | 정의 | 근거 |
|---|---|---|
| **A (주판정)** | first_de.rounds의 **마지막 라운드**(second_de.starting_round와 같은 이름이면 그 라운드)의 비-bye bout 전원에 승자 기록 → 예선 완료 | "64강 32경기" 하드코딩(bracket_utils.py:2060~2063)을 일반화. 256·128 어느 브래킷도 대응 |
| **B (보조)** | 진출자 명단 존재 시 완료 간주: first_de_qualifiers 비어 있으면 **seeded_players 중 seed>32 인원**으로 대체 판정 | 128 이벤트처럼 예선 마지막 라운드 데이터가 누락돼도 A-2-3 검증대로 진출자는 시딩에 남는다 |
| **C (본선 진입)** | second_de 비-bye bout 중 **점수/승자가 기록된 경기 ≥ 1**일 때만 second_de_in_progress. bout '존재'만으로 판정 금지 | 본선 대진 스켈레톤이 먼저 게시되는 경우(및 재분배 오염) 오탐 방지 |

진입 규칙:

| 판정 결과 | 기본 탭 |
|---|---|
| 예선 미완료 (A·B 모두 불충족) | 예선 DE |
| 예선 완료 && 본선 미개시 (C 불충족) | 예선 DE (진출자 명단 강조 + "본선 대진 준비 중" 배지) |
| 본선 개시/종료 | 본선 DE |

- localStorage 복원은 **판정 결과가 지난 방문과 같을 때만** 적용(P14). 상태가 진전되면 판정 기본값이 이긴다.
- 내 선수가 지정돼 있으면 한 번 더 보정: 내 선수의 최신 경기가 있는 phase 우선(예선 탈락자의 부모는 본선이 시작돼도 자기 경기부터).

### C-2. "내 선수 우선" 인터랙션 — 3안 비교

공통 선행 조건: `PlayerHighlighter` 셀렉터에 `.bracket-match` 추가 + 다중 하이라이트 API(`highlightMany([{ko,team}])`) (P4·P5). 데이터는 기존 `getMyPlayerNames()`(즐겨찾기+My Player 병합)를 DE 탭 1급 시민으로 승격.

**A안 — 내 선수 스트립 + 점프 내비게이터 (권장, 1차 구현)**

DE 탭 상단 sticky 칩 스트립:

```
⭐ 내 선수:  [박소윤 · 예선 64강 ▶]  [김OO · 탈락(128강)]  [이OO · 본선 32강 ▶]   ◀ 1/3 ▶
```

- 칩 = 선수별 현재 상태 요약(다음 경기 라운드 or 탈락 라운드). 데이터는 de-results API 재사용(선수당 1콜).
- 칩 탭 → 해당 phase 전환 + 그 선수의 최신/다음 경기 블록으로 스크롤 + 1회 펄스(box-shadow, `prefers-reduced-motion` 존중). 사장 코드 `findAndHighlightPlayer()`를 이 용도로 수리·부활.
- ◀ ▶ = 같은 선수의 라운드별 경기 순회. 선수 간 이동은 칩 클릭.
- 다중 동시 표시: 내 선수 전원에 얇은 좌측 보더 + 이름 옆 ⭐ 상시. 색 구분은 태극 레드(첫 선수)/태극 블루(그 외) 2계열로 제한하고 **식별은 색이 아니라 칩·별표·이름**으로(색약 대응, 금지 패턴 회피).
- 장점: 구현비 낮음(기존 API·하이라이터 확장), 트리뷰·리스트뷰 양쪽 동작, "먼저 내 선수 → 다음 경쟁자" 순서(문제 4)와 정합. 단점: 즐겨찾기 5+명이면 칩 가로 스크롤 필요, 브래킷 전체 조망은 못 줌.

**B안 — 브래킷 미니맵**

트리뷰 우상단 고정 소형 개요(순수 DOM/CSS 격자 또는 인라인 SVG): 라운드×경기 격자에 내 선수 경기 셀만 점등, 뷰포트 위치 사각형, 클릭으로 스크롤.

- 장점: 128강급에서 방향감각 제공, 스포츠 데이터 브랜드다운 밀도. 단점: 구현비 최대(스크롤 동기화), 모바일 면적 부족 — 데스크톱 전용이 현실적. A안 정착 후 후순위 권장.

**C안 — "내 선수 여정" 카드 (선수 루트 위젯의 재편)**

기존 "선수 루트"를 개편·개명해 DE 탭 최상단 1차 화면으로 승격. 내 선수 각각에 예선→본선 관통 세로 타임라인(승/패/부전승/다음 경기/예상 상대). 전체 대진표는 그 아래 섹션.

- 드롭다운 대상을 **DE 참가자 전원**으로 확대: 서버가 to_dict에 통합 참가자 목록 제공(`get_dual_de_combined_seeding` 활용) 또는 기존 `/api/events/{cd}/players/search` 자동완성으로 대체 (P6 해소).
- 장점: 학부모 시나리오를 브래킷 탐색 없이 직접 해결, 모바일 최적. 단점: 대진 맥락(어느 산에서 만나나)이 약함 — A안과 병행 필요.

**권고**: A안 + C안 병행, B안 후순위.

### C-3. 경기 블록 클릭 → 매치 시트 (문제 2)

`.bracket-match`/`.match-card` 전체를 클릭 타깃으로(선수명 링크 버블 구분). 모바일=바텀시트, 데스크톱=우측 패널:

```
┌─ 64강 · Match 7 ──────────────────────────── ✕ ─┐
│  [3] 박소윤 · 최병철펜싱클럽      15 : 9   [30] 김OO │   ← .fm-num 점수
│  ● 상대 전적  박소윤 2승 1패  (최근 15-13 승 · 2026 회장기 16강)│
│──────────────────────────────────────────────│
│  이후 예상 경로            ⚠ 시드 기준 예상입니다     │
│  32강  vs [14] 이OO  또는 [19] 정OO   (전적 1-0 / 첫 대결)│
│  16강  상대 후보 4명 ▾                              │
└──────────────────────────────────────────────┘
```

- 데이터: 전적 = EventH2H 일괄 응답 재사용(내 선수 기준) + 임의 두 선수는 `/api/players/{a}/head-to-head/{b}`. 예상 경로 = de-prediction (Phase 3에서 Dual DE·256강 수리 후).
- **제1원칙**: 예상 블록에 상시 "시드 기준 예상" 배지 + 점선 테두리. 확정(실선+점수) / 예상(점선+후보)을 시각적으로 절대 혼동 불가하게.
- 애니메이션: 시트 slide-up/fade(transform·opacity만), 예상 경로 행 60ms 스태거, 클릭 블록 테두리 펄스 1회. width/max-height/padding transition 금지 패턴 회피, `prefers-reduced-motion`에서 즉시 표시.

### C-4. 경기 전 / 경기 후 상태별 화면

| 상태 | 예선 DE 탭 | 본선 DE 탭 | 매치 시트 |
|---|---|---|---|
| 대진 발표 전 | 시딩(풀 순위)만 + "대진 준비 중" | 열람 가능, "시드 {n}명 확정, 상대 미정" 안내 | — |
| 예선 진행 중 | **기본 진입.** 진행바 + 내 선수 스트립. 미완 경기 = "-"·예정 배지 | 열람 가능 + "예선 진행 중, 본선 대진은 예선 종료 후 확정" 배너 | 완료=결과 중심, 미래=예상 중심 |
| 예선 완료 | 진출자 {n}명 명단 강조 | 확정 대진 표시 시작 | 예상→확정 치환 |
| 본선 진행 중 | 열람 가능(기록 보존) | **기본 진입** | 동일 |
| 종료 | 기록 뷰 | Champion + 최종순위 연결 | 결과 전용(예상 숨김) |

핵심: 탭 disabled 잠금(dual-bracket-tabs.html:37) 대신 **열람 항상 허용, 기본 진입만 상태로 제어**. 잠긴 탭은 이유를 설명하지 못한다.

### C-5. 모바일 (1차 사용자: 대회장의 학부모)

- 리스트뷰 모바일 기본 유지(자동 전환, bracket.html:539~548). 라운드 탭 기본 선택(미완료 첫 라운드, 183~199)도 유효 — 유지.
- 내 선수 스트립은 하단 내비(56px) 위 sticky, 칩 가로 스크롤.
- 매치 시트 = 바텀시트(기존 온보딩 시트 패턴 재사용), 스와이프 다운 닫기.
- 트리뷰는 모바일 기본 진입 비권장 — "전체 대진표 보기" 명시적 버튼으로만.
- 성능: 128강 트리뷰 DOM 수천 노드 — SSR 유지, 매치 시트·스트립 JS는 이벤트 위임 리스너 1개.

---

## D. 구현 계획 (단계별 독립 배포)

### Phase 0 — 데이터 무결성 복구 (모든 것의 전제, 화면 변경 없음)

| 파일 | 변경 |
|---|---|
| `app/bracket_utils.py:1845~1846` | 하위 브래킷 보유 판정을 `full_bouts` **or `bouts` or `bouts_by_round`**로 확장 — 재분배 분기 자체를 차단 (P1①). 이것만으로 남에는 재스크랩 없이 복구 |
| `app/bracket_utils.py:1874` | `bout.get('match_num', bout.get('match_number', 0))` — 방어적 이중 키 (P1②, 하위가 정말 빈 이벤트 대비) |
| `app/bracket_utils.py:2060~2063` | first_de_complete 판정을 C-1 기준 A/B로 교체 (P3) |
| `app/bracket_utils.py:1941 부근` | first_de_qualifiers 빈 경우 seeded_players의 seed>32를 진출자로 복원 (P2 부분·P15) |
| `scraper/de_scraper_v4.py` | 예선 64강 수집 결함 수정(원인·수정 방향은 **E절**에서 실측으로 특정: `_detect_tournament_table_tabs`가 li 탭만 읽고, fnGetMatch 재렌더가 다음 라운드 페어링을 지움) → 수정 **후** 3종목 재스크랩 (P2). KFA가 진실의 원천 — 재스크랩으로만 복구, 수기 보정 금지. ⚠️ 수정 없는 재스크랩은 무효 — 실제로 스케줄러가 2026-08-17에도 재수집했으나 결손이 그대로다 |
| `app/data_validator.py` | 신규 규칙 후보: dual_de에서 ① first_de 마지막 라운드 경기 수 = 진출자 수 ② 본선 시작 라운드 경기 수 = second_bracket_size/2 ③ 진출자 수 = second_bracket_size − seeded_count |

- 검증: `PYTHONPATH="." python scripts/run_validation.py` ERROR 0건 + 남에 페이지에서 예선 3라운드/본선 64강 32경기 확인.
- 회귀 위험: **높음** — 분배 결과 변경은 QF 그룹 색(DOM 순서 기반), status, 진행바, de-prediction 완료 라운드 판정에 연쇄. 과거 dual_de 이벤트 전수 스팟체크 필요.

### Phase 1 — 용어·진입·설명의 데이터화 (템플릿 중심)

- `dual-bracket-tabs.html`: 한국어 주표기(C-1), 배너·진행바 동적 생성(P7·P8), 탭 disabled → 열람 허용+안내.
- `dual-bracket.js`: restoreState에 상태 스탬프 비교(P14), 내 선수 phase 보정.
- `bracket_utils.py:156~162` 중복 문구 제거. 위험: 낮음. **캐시버스터(`base.html ?v=`) 필수.**

### Phase 2 — 내 선수 우선 (JS/CSS)

- `player-search.js`: `.bracket-match` 셀렉터 추가(P4), `highlightMany()`, 순회 API.
- `player-search.css`/`bracket.css`: `.bracket-match.player-highlighted` — `--fm-accent-primary` 보더+은은한 배경, 색 외 채널 병용.
- `event_result.html`: DE 탭 내 선수 스트립(A안). `findAndHighlightPlayer()` 수리·연결 또는 삭제.
- 위험: 중간 — Pool 쪽 기존 하이라이트와 간섭·i18n(로마자) 매칭 확인.

### Phase 3 — 선수 루트 재편 + 매치 시트

- 서버: to_dict에 통합 참가자 목록 노출(P6), de-prediction 256강·Dual DE phase 인식(P9) — 본선은 본선 시딩, 예선은 예선 시딩으로 각각 계산.
- `event_result.html`: "내 선수 여정"(C안) + 매치 시트(C-3) + 이벤트 위임.
- 위험: 중간~높음 — de-prediction 소비처 재확인(현재 event_result 전용으로 보임).

### Phase 4 — 스타일 토큰화 디자인 패스

- `bracket.css` 146개 hex → `--fm-*` 토큰, 태극 팔레트 전환, 점수 `.fm-num`, QF 그룹 색 인라인 → CSS 파일+토큰 파생 (P12).
- 검증: impeccable 디텍터 재실행 + 스크린샷 회귀 비교. 위험: 낮음(시각 전용)이나 범위 큼.

### 공통 위험 요소

1. **Cloudflare 캐시**: CSS/JS 수정마다 `?v=` 범프 필수 (2026-08-06 사고 재발 방지).
2. **완료 대회 재스크랩**: 스케줄러와 경합 금지(단발 실행), KFA 원본 diff를 `validation_logs`에 기록.
3. **normalize 계층 소비처 다수**: `_get_full_bouts_from_de_bracket`은 10+ 곳 사용 — top-level full_bouts는 불변이므로 영향 없음 확인됨. 단 `normalized_bracket` 소비처(de-prediction server.py:3766, de-results:4352)는 Phase 0 결과로 출력이 바뀌는 영향권.
4. **localStorage 마이그레이션**: `dualDE_phase_{eventId}` 구값이 새 규칙과 충돌 — 상태 스탬프 도입 시 구값 무시.
5. **메타데이터 봉인**: raw `de_bracket.status`, `champion`, `events.has_first_de/has_second_de`는 신뢰 불가(P13) — 신규 코드에서 참조 금지를 코드 코멘트로 명문화.

---

## E. 재스크랩 타당성 검증 (KFA 원본 실사, 2026-08-17)

### E-1. 방법

Playwright(headless)로 KFA 실페이지를 **읽기 전용** 조사(요청 간 1초 이상 스로틀, 수정 없음).
스크래퍼와 동일 경로로 이동: `compList → COMPM00722 → 경기결과 → 대진표 → 종목 선택 → 엘리미나시옹디렉트`,
`select#schEtc01`로 예선/본선 전환, `fnGetMatch(n)`으로 라운드 뷰 전환.
조사 스크립트·원본 JSON: 세션 스크래치패드 `kfa_de_probe{,2,3,4}.py`, `kfa_probe*_result.json`.
대조군: 남자 에페(raw 완전) vs 결손 3종목(여에·여플·남플).

### E-2. 판정 1 — 원본에 예선 64강이 존재하는가: **존재한다 [확인]**

예선 phase(schEtc01=A)의 **초기 렌더**(대진표>엘리미나시옹디렉트 진입 직후, fnGetMatch 호출 전) DOM 실측:

| 종목 | 초기 뷰 컬럼(xposition) | 예선 64강(x64) 박스 | 그중 완전 경기(양쪽 이름, compmatsym 페어) | 점수·승자 |
|---|---|---|---|---|
| 여자 에페 | 128·64·32 | 64/64 이름 있음 | **32경기** | 전 박스 score+wingbn 존재 |
| 여자 플뢰레 | 128·64·32 | 64/64 | **32경기** | 존재 |
| 남자 플뢰레 | 128·64·32 | 64/64 | **32경기** | 존재 |
| 남자 에페(대조군) | 256·128·64·32 | 64/64 | 32경기 (raw first_de.bouts_by_round['64강']=32와 일치) | 존재 |

**예선/본선 구분 검증(여자 에페) [확인]**: 이 x64 컬럼의 선수 64명 전원을 DB와 대조한 결과 —
본선 시드 상위 32명과의 겹침 **0명**(본선 64강이라면 시드 32명이 반드시 포함되어야 함),
DB에 저장된 본선 64강 참가자와의 겹침 32명(=예선 통과자만). 즉 이 컬럼은 **본선이 아니라 진짜 예선 64강**이다.
박스에 표시된 시드 번호(1~128)는 예선 브래킷 자체 시딩으로, 본선 seeded_players의 시드 공간과 별개다.
같은 데이터는 예선 phase에서 `fnGetMatch(6)`을 호출해도 32경기 페어링 그대로 나온다(phase 선택은 A 유지됨을 확인).

### E-3. 판정 2 — KFA 미게시인가, 스크래퍼가 놓친 것인가: **스크래퍼가 놓친 것 [확인]**

데이터는 게시돼 있고, 현행 파서의 동작 방식으로는 구조적으로 수집이 불가능함을 오늘 DOM에서 파서 단계 그대로 재현했다:

1. 예선 phase의 라운드 탭(li)은 **시작 라운드 하나만** 광고된다 — 여에 탭 목록 = `["128강전"]` (남에 = `["256강전"]`). 후속 예선 라운드(64강)의 li 탭은 없다.
2. `_detect_tournament_table_tabs()`(de_scraper_v4.py:895~948)는 **li 텍스트만** 읽어 탭 목록을 만든다 → 여에는 `[(7, "128강전")]` 하나.
3. `_parse_tournament_table_bracket()`(de_scraper_v4.py:1195~1199)은 각 탭마다 **fnGetMatch를 먼저 호출한 뒤** 추출한다. 그런데 실측 결과 `fnGetMatch(7)` 재렌더 뷰에서는 x64 컬럼이 **페어링 없는 승자 표시 컬럼으로 강등**된다(초기 뷰: x64 완전 경기 32개 → fn7 뷰: 0개, 이름 박스 64개만). 추출 로직 `_extract_tournament_table_data()`는 compmatsym 페어가 2개 모인 경기만 수집하므로 fn7 뷰에서는 128강 57경기만 잡힌다 — **DB에 저장된 결손 형상과 정확히 일치**.
4. 예선 phase에서 `fnGetMatch(6)`을 호출하면 예선 64강 32경기가 페어링째 나오지만(E-2), li 탭에 없으므로 현행 코드는 이 호출을 영원히 하지 않는다.

방증: 3종목 events.updated_at = **2026-08-17 11:39**(조사 당일, 스케줄러 재수집) — 재수집이 돌았어도 결손이 그대로다. **파서 수정 없는 재스크랩은 무효**라는 실증이다.

[추정] 남자 에페의 raw가 예선 3라운드를 온전히 가진 경위(현행 탭 감지 로직으로는 재현이 안 되는 형상)는 스크랩 당시의 코드 버전 또는 DOM 상태가 지금과 달랐던 것으로 보이며 git 이력 대조가 필요하다. 단, 남에는 재스크랩이 필요 없으므로(렌더링 키 버그 수정만으로 복구) 이 미규명이 복구 작업을 막지는 않는다.

### E-4. 판정 3 — 원인 위치와 수정 방향 (수정은 하지 않음)

| 원인 | 위치 | 수정 방향 |
|---|---|---|
| li 탭만 신뢰 → 예선 후속 라운드 탭 부재 | de_scraper_v4.py:895~948 `_detect_tournament_table_tabs` | (안 1, 권장·최소) `_parse_tournament_table_bracket`에서 **fnGetMatch 호출 전 초기 렌더를 1회 먼저 추출**해 병합 — 초기 뷰에 예선 전 라운드 페어링이 이미 있다(128 이벤트: 128강+64강, 256 이벤트: 256+128+64강, E-2 실측). 페이지 요청 추가 없음 |
| fnGetMatch 재렌더가 다음 라운드 페어링 제거 | de_scraper_v4.py:1195~1199 (fnGetMatch 후 추출) | (안 2, 보완) 예선 phase에서는 li와 무관하게 시작 라운드~공유 라운드 구간의 fn 파라미터를 도출해 순회(여에: fn7+fn6). fn6-in-예선이 예선 64강을 반환함은 실측 확인 |
| "256강전" li가 ROUND_TO_FN_PARAM(최대 128)에 없어 탭 목록이 비면 fallback (5,3)으로 감 | de_scraper_v4.py:184~195, 911~918 | 256 라벨 인지 + 초기 렌더 추출(안 1)로 흡수 |

수정 후 재스크랩 대상: **여자 에페·여자 플뢰레·남자 플뢰레 3종목만**. 남자 에페는 대상 아님(P1 렌더링 키 수정으로 이미 복구됨).
회귀 주의: 초기 렌더 추출을 병합할 때 fn 뷰의 "승자 표시 컬럼"(페어 없는 박스)이 경기로 오인되지 않게 기존 페어 조건(compmatsym 2개)을 유지할 것.

### E-5. 중복 컨테이너 점검 (지난주 pouleAjax×2 사고 유형)

DE 관련 컨테이너는 4종목·양 phase 모두 **중복 없음 [확인]**: `#tournament_container`=1, `.tournament_table`=1, `#pouleAjax`=1(다른 탭 잔재, DE 데이터와 무관).
사이트 전역 레이아웃 id 3종(`title-wrap`, `contents-wrap`, `btn-pop`)이 중복돼 있으나 대진표 데이터 컨테이너가 아니므로 DE 스크래핑에는 영향 없다. 풀 쪽과 같은 사본-컨테이너 위험은 DE 탭에서는 발견되지 않았다.

### E-6. 결론 (사용자 전달용)

**재스크랩하면 복구된다 — 단, 스크래퍼를 먼저 고쳐야 한다.**

- KFA 원본에는 사라진 예선 64강 32경기가 3종목 모두 **이름·점수·승자까지 완전한 형태로 게시돼 있다** (여자 에페는 선수 64명 이름 대조로 예선임까지 검증).
- 지금 스크래퍼는 이 데이터를 구조적으로 못 가져온다: 예선 화면의 라운드 탭이 "128강전" 하나뿐인데 파서가 탭 목록만 믿고, 그 탭을 여는 순간 64강 페어링이 화면에서 사라지는 방식이기 때문이다. 실제로 조사 당일(8/17)에도 스케줄러가 재수집했지만 결손이 그대로였다 — **고치지 않고 재스크랩만 돌리면 또 실패한다.**
- 필요한 수정은 `scraper/de_scraper_v4.py` 한 파일: 대진표 진입 직후의 초기 화면(예선 전 라운드가 페어링째 들어 있음)을 먼저 추출하도록 1곳 보완. 수정 후 여자 에페·여자 플뢰레·남자 플뢰레 3종목만 재스크랩하면 된다.
- 남자 에페는 재스크랩 불필요 — 데이터는 이미 완전하며 화면 쪽 키 버그 수정으로 복구된다.

---

## 요약 (핵심 발견과 권고)

1. **남자 에페의 64강 소실은 순수 렌더링 버그 체인**: raw에는 예선 64강 32경기가 `first_de.bouts`에 올바로 분리 저장돼 있으나, 정규화가 하위 브래킷을 `full_bouts` 키로만 검사해(실키 `bouts`, bracket_utils.py:1845) 불필요한 재분배에 진입하고, 재분배가 `match_num`(실키 `match_number`, 1874) 오타로 64강 전량을 본선에 넣어 예선 64강 소실 + 본선 64강 64경기 오염이 발생한다. **재스크랩 없이 코드 수정만으로 복구 가능.**
2. **128 브래킷 3종목(남플·여플·여에)은 예선 64강이 스크랩 자체에서 누락**(127/159 bout, first_de.rounds=['128강']). 시드 1~32는 128강에 0명 출전(예선 면제 실증)이므로 "단일 토너먼트 오분류" 가설은 기각 — 진짜 Dual DE이며 데이터가 빈 것. 진출자 32명은 seeded_players의 seed 33~64에 잠복해 있어 명단은 복원 가능하다. **KFA 원본에는 해당 64강 32경기가 이름·점수·승자까지 완전하게 게시돼 있음을 실사로 확인**(E절) — 파서가 li 탭 목록만 믿는 구조적 결함으로 못 가져올 뿐이며, 파서 수정 후 재스크랩하면 복구된다(수정 없는 재스크랩은 8/17 스케줄러 재수집에서 실증된 대로 무효).
3. "128강 → Second DE"는 진행바 산출물로, 배너의 "128강→64강 2라운드·32명" 문구는 참가자 수 하나 빼고 전부 하드코딩이라 256 브래킷에서도 같은 거짓 문장이 나간다.
4. 탭 오진입(문제 5)의 원인은 계산 status의 구조 결함이며, raw status(남에 'first_de_in_progress'로 낡음)·champion(4종목 null)·has_first_de/has_second_de(전부 false) 등 **메타데이터는 판정 근거로 쓸 수 없다** — 완료 판정은 "예선 마지막 라운드 전원 승자 기록(A) + 진출자 명단 존재(B) + 본선 점수 기록 경기 ≥1(C)"의 경기 데이터 기준으로 대체해야 한다.
5. "선수 루트"는 de-results+de-prediction 합성 위젯인데 Dual DE에서 드롭다운이 시드 32명뿐이고(to_dict에 seeding 부재), 예측 엔진은 256강·Dual DE를 모른다. "내 선수" 기능은 데스크톱 트리뷰(.bracket-match)가 하이라이트 셀렉터에서 빠져 있어 사실상 부재다.
6. 권고: **Phase 0(정규화 키 수정 → 남에 즉시 복구, 3종목 재스크랩, 검증 규칙) → 용어·진입 데이터화 → 내 선수 스트립+다중 하이라이트 → 매치 시트+루트 재편 → CSS 토큰화**. Phase 0 없이는 어떤 UI 개선도 틀린 데이터를 예쁘게 만드는 일이 된다.
