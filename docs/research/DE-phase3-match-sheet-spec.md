# Phase 3 설계 명세 — DE 매치 시트 + "내 선수 여정" (선수 루트 재편)

- 작성일: 2026-08-17 · 작성 근거: `DE-redesign-report.md` v2 + 본 명세를 위한 추가 코드 실사 (읽기 전용)
- 대상 독자: 구현 에이전트. **이 문서만으로 추가 판단 없이 구현 가능하도록** 데이터 소스·마크업·클래스명·토큰·수치까지 명시한다.
- 표기: **[확인]** = 코드로 검증된 현재 상태, **[설계]** = 이 문서가 정하는 사항.
- 선행 의존성: Phase 0 렌더링 키 수정(`bracket_utils.py:1845/1874`, de-phase 에이전트가 수정 중). 이 명세는 그 수정이 배포된 상태를 전제한다(예선/본선 브래킷이 올바르게 분리 렌더됨).

---

## 0. 핵심 결정 요약 (5가지)

| # | 결정 | 근거 |
|---|---|---|
| D1 | 매치 시트는 **단일 컴포넌트**: 모바일(≤1024px) = 바텀시트, 데스크톱 = 우측 하단 고정 카드(420px). 기존 `openBottomSheet`/`.bottom-sheet` 인프라 재사용. `bracket.html`은 **수정하지 않는다**(이벤트 위임으로 클릭 수신) | 인라인 확장은 128강 트리 리플로우 유발, 팝오버는 모바일 부적합. bracket.html 무수정으로 de-myplayer 에이전트와 충돌 회피 |
| D2 | "다음 상대"는 예측 엔진이 아니라 **브래킷 인접성**(클라이언트, 결정적 계산)으로: 같은 라운드의 형제 경기(index XOR 1) 승자 = 확정 상대, 미완료면 그 경기의 두 선수 = 후보. `de-prediction` API는 1차 릴리스에서 **사용하지 않음**(256강 미지원·Dual DE 미인식·상대별 전대회 스캔 비용 — [확인]) | 인접성은 추정이 아니라 대진표의 수학적 사실 → 제1원칙 충족. 예측 엔진 수리는 3D 단계로 분리 |
| D3 | 두 선수의 **DE 한정 전적**은 현 API로 불가(합산만 반환) — 단 원천 데이터에는 있음(`matches[].round`가 "Pool"/DE 라운드명으로 구분 저장 [확인]) → `_eh2h_build`에 `de_wins/de_losses/de_last_*` 필드 추가(서버 ~15줄, 하위호환) | 클라 재계산 불가(응답에 matches 미포함). 추가 필드만 얹으므로 기존 배지 코드 무영향 |
| D4 | "선수 루트"는 **유지 + "내 선수 여정"으로 개편**. 드롭다운을 기존 `/api/events/{cd}/players/search` 자동완성으로 교체해 **전 참가자 선택 가능**(서버 무변경). `de-results` 응답에 `de_phase` 필드 추가해 예선 64강/본선 64강 라벨 구분 | 시트=경기 단위, 여정=선수 단위 — 다른 질문에 답하므로 흡수하지 않음. 혼란의 원인(시드 32명만 노출)은 드롭다운 소스 교체로 해소 |
| D5 | 애니메이션은 **3곳만**: 시트 진입(300ms), 섹션 스태거(180ms, 40ms 간격), 원본 블록 펄스(600ms). 전부 `transform`/`opacity`만, `prefers-reduced-motion` 시 즉시 표시 | 사용자가 명시 요청 + AI 슬롭 방지의 균형. 128강 DOM에서 리플로우 금지 |

---

## 1. 기존 자산 판정 [확인]

### 1-1. EventH2H + `GET /api/events/{sub_event_cd}/head-to-head?player=&team=`

- 서버: `server.py:4788~4816`(엔드포인트) → `_eh2h_build()`(`server.py:4715~4786`). 60초 TTL 캐시.
- 응답 구조 (opponent 이름 → 레코드 맵):

```json
{
  "sub_event_cd": "...", "player": "박소윤", "team": "최병철펜싱클럽",
  "opponents": {
    "김OO": {
      "team": "...", "wins": 2, "losses": 1, "total": 3, "win_rate": 66.7,
      "first_meeting": false,
      "last_result": "V", "last_score": "15-13", "last_date": "2026-05-01",
      "last_round": "16강", "last_tournament": "제55회 회장기...",
      "contexts": ["de", "pool"]
    }
  }
}
```

- `contexts`는 **이번 종목에서 그 상대를 만나는 위치**(풀/DE)이지, 과거 전적의 경기 유형이 아니다.
- 과거 전적의 유형 구분은 내부 `calculate_head_to_head()`(`server.py:5261~`)의 `matches[].round`에 있다: 풀 경기는 `"Pool"` 고정(`server.py:5347`), DE 경기는 실제 라운드명(`server.py:5413`). **그러나 `_eh2h_build`가 matches를 응답에 포함하지 않고 합산만 내려주므로, 현 응답만으로 DE 한정 전적은 뽑을 수 없다.**
- **판정: DE 한정 전적 = 서버 확장 필요.** 명세는 §4-1.
- 클라이언트: `window.EventH2H`(`event_result.html:2700~3010`) — 내 선수별로 위 API를 1회씩 호출해 `entry.map`(상대→레코드)을 들고 풀/브래킷/루트에 배지를 붙인다. 시트는 이 캐시를 **재사용**한다(내 선수가 낀 경기면 추가 요청 0회).

### 1-2. `GET /api/players/{a}/head-to-head/{b}` (`server.py:3563~`)

- 쿼리: `weapon`, `age_group` 필터만 있고 **team 파라미터가 없다** → 동명이인 구분 불가.
- 응답: `{ player, opponent, record: {wins, losses, total}, matches: [{date, tournament, round, score, result(V/D)}...] }` — matches에 round가 있으므로 **클라이언트에서 DE 한정 집계 가능**.
- 용도: 클릭한 경기에 내 선수가 없을 때(임의 두 선수)의 폴백. 호출 시 반드시 `?weapon={이벤트 무기}`를 전달하고, 시트에 각주 "동명이인이 있는 이름은 다른 선수의 기록이 섞일 수 있습니다"를 조건부 표시(§4-2).

### 1-3. `GET /api/events/{cd}/de-prediction/{name}` (`server.py:3717~4277`)

- 응답: `{ player{name,team,seed}, event_first_round, completed_rounds[], current_round, elimination_round, eliminated, predictions:[{round, potential_opponents:[{name,team,seed,head_to_head{wins,losses,total}}], expanded_default}] }`
- 결함 [확인]: ① 라운드 목록에 256강 없음(`server.py:3800`) ② Dual DE phase 미인식 — 예선/본선 혼합 bout로 완료 라운드 판정(3844), 시드는 `de_bracket.seeding`(dual raw에 없음)→풀 순위 폴백(3788) ③ `potential_opponents[].head_to_head`가 **풀 bout만** 전 대회 스캔(4232~4246)이라 DE 전적 누락 + 상대 수 × 전 대회 비용.
- **판정: 1차 릴리스의 매치 시트에서 사용 금지.** 수리 후(§7 단계 3D) "이후 전체 경로" 확장에만 쓴다. "내 선수 여정" 위젯은 기존처럼 이 API를 쓰되(현행 유지) 수리 전까지 256 브래킷 이벤트에서 미래 노드가 부정확할 수 있음을 알고 있어야 한다(수리는 3D).

### 1-4. `GET /api/events/{cd}/de-results/{name}` (`server.py:4280~4590`)

- 응답: `{ player{name,team,seed}, event_first_round, participant_count, results:[{round, opponent{name,team,seed}, score:"15-10", result:"win"|"lose"|"bye"}] }`
- 결함: Dual DE에서 phase 구분이 없어 **예선 64강과 본선 64강이 같은 "64강"으로 내려온다**(한 선수가 둘 다 뛴 경우 64강 2건). → `de_phase` 필드 추가 필요(§4-1).

### 1-5. 기타 재사용 자산

| 자산 | 위치 | 시트에서의 용도 |
|---|---|---|
| `window.getMyPlayerNames()` (다수 반환, 즐겨찾기+My Player 병합) | `event_result.html:2184~2213` | 클릭 경기에 내 선수 포함 여부 판정 → EventH2H 캐시 경로 선택 |
| `window.openBottomSheet(id)` / `closeBottomSheet(id)` + 드래그 닫기 | `mobile-ux.js:566~585` | 시트 열기/닫기/스와이프 다운 |
| `.bottom-sheet`, `.bottom-sheet-backdrop`, handle/header/close CSS (라이트 테마 오버라이드 포함) | `mobile-ux.css:847~914, 1404~` | 시트 셸 스타일 베이스 |
| `.fm-badge fm-badge--micro fm-badge--pill h2h-badge h2h-badge--{up,down,even,first}` | EventH2H가 생성, 스타일 기존 | 전적 배지를 시트 안에서 동일 어휘로 |
| `_tr_player/_tr_team` JS 번역 맵 | `event_result.html` 전역 | 시트 내 모든 이름 표기 |
| 경기 블록 DOM: `.bracket-match[data-match-id]`(트리) / `.match-card[data-match-id]`(리스트), 내부 `.match-player|.card-player`, `.player-seed|.player-seed-badge`, `.player-name`, `.player-score|.player-score-badge`, 라운드 컨테이너 `.bracket-round[data-round]` / `.round-panel[data-round-panel]` | `components/bracket.html` | 시트 데이터의 1차 소스(DOM 파싱) — bracket.html 무수정 |

---

## 2. 매치 시트 — 컴포넌트 명세 [설계]

### 2-1. 형식: 바텀시트(모바일) / 우측 하단 고정 카드(데스크톱)

3안 비교 결론:

| 안 | 기각/채택 사유 |
|---|---|
| 인라인 확장 | 기각 — 128강 트리에서 블록 높이 변경은 라운드 컬럼 전체 리플로우 + 연결선 정렬 붕괴 |
| 앵커 팝오버 | 기각 — 모바일 폭에서 결국 풀폭 시트가 됨, 스크롤 컨테이너(가로 스크롤 트리) 안에서 위치 계산 취약 |
| **바텀시트/고정 카드** | 채택 — 1차 사용자(대회장 모바일)의 엄지 도달권, 기존 인프라 재사용, DOM을 트리 밖(body 직속)에 두어 리플로우 0 |

### 2-2. DOM (신규, `event_result.html`의 `</body>` 직전 — #tab-tournament 밖, body 직속)

```html
<div id="match-sheet-backdrop" class="bottom-sheet-backdrop" onclick="MatchSheet.close()"></div>
<aside id="match-sheet" class="bottom-sheet match-sheet" role="dialog" aria-modal="true"
       aria-labelledby="ms-title" hidden>
    <div class="bottom-sheet-handle"></div>
    <header class="ms-head">
        <span id="ms-title" class="ms-round"></span>          <!-- 예: "본선 DE · 64강 · Match 7" -->
        <span class="ms-status" id="ms-status"></span>         <!-- 완료/예정/부전승/기권 배지 -->
        <button type="button" class="bottom-sheet-close" aria-label="닫기"
                onclick="MatchSheet.close()">&times;</button>
    </header>
    <section class="ms-versus" id="ms-versus"></section>       <!-- 두 선수 헤더 -->
    <section class="ms-h2h ms-stagger" id="ms-h2h"></section>  <!-- 상대 전적 -->
    <section class="ms-next ms-stagger" id="ms-next"></section><!-- 다음 상대 -->
    <section class="ms-after ms-stagger" id="ms-after"></section><!-- 그다음 라운드 (접힘) -->
    <footer class="ms-actions ms-stagger" id="ms-actions"></footer>
</aside>
```

시트 셸은 `.bottom-sheet` 스타일을 상속하고 `.match-sheet`가 데스크톱 분기만 얹는다(§5-3). z-index는 기존과 동일한 1500(변수 없음 — 기존 `.bottom-sheet`가 1500 하드코딩이므로 상속으로 해결, 새 하드코딩 금지).

### 2-3. 열기 트리거 — 이벤트 위임 (bracket.html 무수정)

`match-sheet.js` (신규 파일):

```
document.getElementById('tab-tournament').addEventListener('click', handler)
handler:
  1. e.target.closest('a') 이면 return  (선수/팀 프로필 링크는 기존 동작 유지)
  2. block = e.target.closest('.bracket-match, .match-card'); 없으면 return
  3. block.classList.contains('bye-match') 이면 return  (부전승 블록은 시트 없음 — §2-7)
  4. e.preventDefault(); MatchSheet.open(block)
```

접근성: 블록은 이미 `role="treeitem"`(트리)·`article`(리스트)이므로 `handler`와 별개로 `keydown`(Enter/Space) 위임을 같은 컨테이너에 1개 추가. 시트 열릴 때 `.bottom-sheet-close`로 포커스 이동, 닫힐 때 원 블록으로 복귀(블록 참조 보관).

### 2-4. 블록 → 데이터 파싱 (DOM이 1차 소스)

`MatchSheet.open(block)`이 DOM에서 직접 읽는다 — 서버 왕복 없이 즉시 렌더 가능한 부분:

| 항목 | 소스 |
|---|---|
| 라운드명 | `block.closest('.bracket-round')?.dataset.round` 또는 `block.closest('.round-panel')?.dataset.roundPanel` |
| phase (예선/본선) | `block.closest('.de-phase-panel')?.dataset.phase` ("first"/"second") → 라벨 "예선 DE"/"본선 DE". 단일 DE면 패널 없음 → 라벨 생략 |
| 경기 번호 | 트리: `aria-label`의 `Match (\d+)` / 리스트: `.match-number` 텍스트 |
| 선수 2명 | 슬롯 = `block.querySelectorAll('.match-player, .card-player')` (항상 2개). 각각 `.player-seed|.player-seed-badge`(시드), `.player-name` 링크(이름 + href의 `team=` 파라미터 → **한글 원문 소속**; 표시 텍스트는 번역돼 있을 수 있으므로 href에서 원문 이름도 추출: `/player/{urlencoded}`), `.player-team|.player-team-tree`(표시용 소속) |
| 점수/승자/상태 | `.player-score|.player-score-badge` 텍스트('-'=미실시), 슬롯의 `winner` 클래스, `forfeit` 클래스, `.match-status` |

⚠️ 이름 매칭 규칙: API 호출·EventH2H 조회는 **href에서 복원한 한글 원문**으로, 화면 표기는 `_tr_player()`로. (EventH2H도 같은 규칙 사용 [확인] `event_result.html:2757~2765`)

### 2-5. 섹션별 내용과 우선순위 (위 → 아래)

#### ① 헤더 (즉시)
`{phase 라벨} · {라운드} · Match {n}` + 상태 배지: `완료`(승자 있음) / `예정`(점수 없음) / `기권`(forfeit) — 기존 `.match-status` 어휘 재사용.

#### ② 대결 헤더 `ms-versus` (즉시)

```
[3] 박소윤            15 : 9            [30] 김OO
    최병철펜싱클럽      ────────            OO중
     승 ✓
```

- 시드 `[n]`·점수는 `.fm-num`(`--fm-font-display`). 미실시 경기는 점수 대신 `VS`.
- 승자 슬롯: 이름 700 웨이트 + `승` 마이크로 배지 + 좌측 2px 보더(`--fm-accent-primary`). **색+배지+굵기 3중 채널** — 색만으로 전달 금지.
- 기권자: 기존 어휘(취소선 + `기권` 배지) 재사용.

#### ③ 상대 전적 `ms-h2h` (비동기, 스켈레톤 → 채움)

데이터 경로 (순서대로 시도):

```
1. myNames = getMyPlayerNames() 결과에 p1 또는 p2가 포함되고
   EventH2H 캐시(entry.map)에 상대 레코드가 있으면 → 캐시 사용 (요청 0회)
   ※ EventH2H 내부 캐시 접근용 공개 메서드 EventH2H.getRecord(myKo, oppKo) 신설 (§7 단계 3B)
2. 아니면 GET /api/players/{p1}/head-to-head/{p2}?weapon={이벤트 무기}
   (weapon은 서버 템플릿 전역 변수로 이미 존재 — event.weapon을 JS 전역 EVENT_WEAPON으로 노출, §7)
```

표시 (3-1의 서버 확장 배포 후 기준):

```
상대 전적 (DE)   박소윤 2승 1패        ← .fm-num, 기준 선수 명시
  최근 DE: 15-13 승 · 2026 회장기 · 16강
전체 전적        3승 2패 (풀 포함)     ← 보조 행, --fm-text-muted
```

- DE 전적 0건 + 전체 전적 있음 → "DE에서는 첫 대결" + 전체 전적 행.
- 전체 0건 → `첫 대결` 배지(`h2h-badge--first` 어휘) 단독.
- 경로 2(임의 두 선수)로 조회했고 응답 matches의 상대 팀이 블록의 팀과 불일치하는 경기가 섞여 있으면 각주: "※ 동명이인의 기록이 섞였을 수 있습니다"(`--fm-text-muted`, 0.75rem). 판정: matches에 팀 정보가 없으므로 **record.total > 0이고 경로 2일 때 항상 각주 표시**가 단순·정직하다 — 이것으로 확정.
- API 실패/타임아웃(4초) → 섹션 자체를 숨긴다(빈 프레임 금지).

#### ④ 다음 상대 `ms-next` (즉시 — 클라 계산, D2)

**인접성 알고리즘** (정확한 대진표 사실 — 추정 아님):

```
roundEl   = block이 속한 라운드 컨테이너 (tree: .bracket-round / list: .round-panel)
blocks    = roundEl 내 경기 블록 배열 (DOM 순서)
i         = blocks.indexOf(block)
sibling   = blocks[i ^ 1]

가드(제1원칙): 다음 라운드 컨테이너가 존재하고
  blocks.length가 2의 거듭제곱이며 next 라운드 블록 수 == blocks.length/2
  가 아니면 → "다음 상대 정보를 계산할 수 없습니다" 1줄 표시하고 종료.
  (bye가 시작 라운드 외에서 렌더 생략되는 엣지 케이스 방어 — bracket.html:96 [확인])

sibling의 승자 있음  → 확정 상대 1명
sibling 미완료      → 후보 2명 (sibling의 두 선수)
sibling이 bye-match → 확정 상대 = bye 승자
현재 경기 미완료    → 문구를 "이 경기 승자의 다음 상대"로 (누가 이길지는 표시하지 않음)
현재 경기 완료      → "{승자}의 다음 상대"
```

표시:

```
다음 상대 — 32강                         확정: ┌──────────────┐ 실선 카드
  ┌────────────────────┐                      │ [14] 이OO · OO고 │
  │ [14] 이OO  또는  [19] 정OO │ ← 미확정: 점선 테두리 + "예상" pill
  └────────────────────┘
  각 후보 옆: 전적 배지 (③과 같은 경로로 조회, 내 선수 기준일 때만)
```

- **확정 vs 예상 시각 규칙(전 섹션 공통)**: 확정 = 실선 1px `--fm-border-*` + 이름 단독. 예상 = `border: 1px dashed` + `예상` pill 배지(`fm-badge--micro`) + 후보 사이 "또는" 텍스트. 형태(점선)+텍스트(배지) 이중 채널 — 야외 화면·색약 대응.
- 결승 블록이면 섹션 대신 "결승전입니다 🏆" 1줄.
- 예선 DE 마지막 라운드(다음 라운드 컨테이너가 같은 phase에 없음) → "승자는 본선 DE 진출" 1줄 + 본선 탭 이동 버튼(있으면 확정 본선 상대는 1차 릴리스에서 계산하지 않음 — phase 경계는 시드 재배정이 끼므로 인접성이 성립하지 않음. 정직하게 진출 사실만 표기).

#### ⑤ 그다음 라운드 `ms-after` (즉시, 기본 접힘 `<details>`)

같은 인접성으로 한 단계 더: 4블록 그룹(`i & ~3` ~ `+3`)의 나머지 두 경기 → 생존 선수 최대 4명을 후보 pill로. 전부 "예상" 스타일. 그 이후 라운드는 계산하지 않고 "전체 경로는 [내 선수 여정]에서" 링크(§6). 가드 실패 시 섹션 생략.

#### ⑥ 액션 `ms-actions`
`[박소윤 프로필]` `[김OO 프로필]` (기존 `/player/{name}?team=` 링크) + `[이 선수 여정 보기]` ×2 (→ `EventRoute.load(name, team)` 호출 후 시트 닫고 여정 위젯으로 스크롤).

### 2-6. 경기 전/중/후 상태별 시트 내용

| 상태 (판정 기준) | ① 헤더 | ② 대결 | ③ 전적 | ④ 다음 상대 | ⑤ 그다음 |
|---|---|---|---|---|---|
| 예정 — 양측 확정, 점수 '-' | `예정` | VS, 승자 강조 없음 | 표시 (관전 포인트 역할, 가장 중요) | "이 경기 승자의 다음 상대" | 표시 |
| 대기 — 한쪽만 확정(상대 슬롯 이름 없음 "Seed") | `예정` | 확정 선수 + "상대 미정(이전 경기 진행 중)" | 생략 (상대 미정) | 생략 | 생략 |
| 완료 — 승자 있음 | `완료` | 점수 + 승자 3중 강조 | 표시 (이번 경기 반영 전 전적임을 문구로: "이 대회 이전 전적" — EventH2H가 이번 대회를 제외함 [확인] server.py:4741) | "{승자}의 다음 상대" | 표시 |
| 기권 — forfeit 클래스 | `기권` | 기권자 취소선+배지 | 표시 | 승자 기준 | 표시 |
| 부전승 블록 | 시트를 열지 않음 (§2-3) | — | — | — | — |

"경기 중" 상태는 데이터에 없다(KFA는 완료 후 점수 게시 [확인 — 스크래핑 데이터에 진행 중 점수 없음]) → 별도 상태를 만들지 않는다.

---

## 3. 서버 확장 명세 (단계 3A — 독립 배포, 추가 필드만이라 하위호환)

### 3-1. `_eh2h_build` — DE 한정 전적 필드 (server.py:4715~)

opponent 레코드 계산부(4762~4780 부근)에서 이미 필터링된 `matches` 리스트로부터:

```python
de_matches = [m for m in matches if m.get("round") != "Pool"]
de_wins = sum(1 for m in de_matches if m.get("result") == "V")
de_last = de_matches[0] if de_matches else {}
out[opp_name] = {
    # ...기존 필드 전부 유지...
    "de_wins": de_wins,
    "de_losses": len(de_matches) - de_wins,
    "de_total": len(de_matches),
    "de_last_result": de_last.get("result", ""),
    "de_last_score": de_last.get("score", ""),
    "de_last_round": de_last.get("round", ""),
    "de_last_tournament": de_last.get("tournament", ""),
    "de_last_date": de_last.get("date", ""),
}
```

`matches`는 최신순 정렬 상태 [확인 — server.py:4766 주석]. 캐시 키/TTL 변경 없음.

### 3-2. `api_de_results` — `de_phase` 필드 (server.py:4280~)

results 항목 생성부(4560~4570 부근)에서 bout dict의 `de_phase`를 그대로 전달:

```python
"de_phase": bout.get("de_phase", ""),   # "qualifying" | "main" | ""
```

`de_phase`는 `_get_full_bouts_from_de_bracket()`이 dual_de의 하위 브래킷에서 추출할 때 태깅한다(de_transforms.py:204~216 [확인]). ⚠️ 이 태깅은 하위 브래킷에서 bout을 읽을 때만 붙는다 — de-phase 에이전트의 1845 수정(`bouts` 키 인정)과 정합하도록, `_get_full_bouts_from_de_bracket`의 dual 분기도 `full_bouts → bouts → bouts_by_round` 순 폴백이 되는지 **구현 시 확인**하고, 안 되어 있으면 같은 폴백을 추가한다(de_transforms.py:218 부근). 태그가 없으면 빈 문자열 — 클라이언트는 빈 값이면 phase 라벨을 생략(오표기 금지).

---

## 4. 애니메이션 명세 [설계]

| 대상 | 속성 | 값 | 비고 |
|---|---|---|---|
| 시트 진입/퇴장 | `transform: translateY(100%) → 0` | `transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)` | **기존 `.bottom-sheet` 값 그대로 상속** [확인 mobile-ux.css:855] — 새 값 만들지 않음(사이트 내 일관성) |
| 백드롭 | `opacity 0 → 1` | `var(--fm-transition-normal)` (250ms ease) | 기존 `.bottom-sheet-backdrop` 상속 |
| 섹션 스태거 (`.ms-stagger`) | `opacity 0→1`, `transform: translateY(8px)→0` | 180ms ease-out, `transition-delay: calc(var(--ms-i) * 40ms)` — 각 섹션에 `style="--ms-i: n"` (n=0..3, 최대 지연 120ms) | 시트 `open` 클래스 부여 시 1회. 콘텐츠 비동기 도착(③)은 스태거 없이 120ms opacity 페이드만 |
| 원본 블록 펄스 | 오버레이 `opacity` 키프레임 1회 | `.ms-origin-pulse { position: relative; }` + `.ms-origin-pulse::after { content:''; position:absolute; inset:0; border-radius:inherit; background: var(--fm-accent-primary); pointer-events:none; animation: ms-pulse 600ms ease-out; }` / `@keyframes ms-pulse { 0%{opacity:0} 30%{opacity:.14} 100%{opacity:0} }` — `animationend`에서 클래스 제거 | ⚠️ `--fm-glow-primary`는 라이트 테마에서 `transparent`라 글로우 방식은 보이지 않음 [확인 variables.css:279] → 액센트 오버레이 opacity 방식으로 양 테마 동일 동작. opacity만이라 리플로우 없음. 시트 닫힐 때도 1회(복귀 안내) |
| 예상 후보 pill | 스태거의 일부로만 등장 | 별도 애니메이션 없음 | 플립/회전/글로우 금지 — 슬롭 방지 |

- **금지**: width/height/max-height/padding/margin transition, 무한 반복 애니메이션, 스크롤 연동 패럴랙스. (`impeccable` 디텍터 금지 패턴 [확인 — services/data/CLAUDE.md])
- `prefers-reduced-motion: reduce`: 시트 `transition: opacity 120ms` (translateY 즉시 0), 스태거·펄스 전부 무효(`animation: none; transition-delay: 0ms; transform: none`). 미디어쿼리 1블록으로 일괄 처리.
- 성능: 시트는 body 직속 `position: fixed` → 트리 레이아웃과 독립. 열기 전 `hidden` 속성으로 렌더 제외, 열 때 `hidden` 제거 후 다음 프레임에 `open` 클래스(더블 rAF). `will-change: transform`은 열림 직전 부여, `transitionend`에 제거.

---

## 5. 시각 명세 [설계]

### 5-1. 토큰 (전부 `static/css/variables.css` 실존 변수 [확인]. 하드코딩 hex 금지)

| 용도 | 토큰 |
|---|---|
| 시트 표면/보더 | `--fm-bg-card`(라이트 오버라이드는 기존 `.bottom-sheet` 라이트 규칙 상속), `--fm-border`(기본 헤어라인) / `--fm-border-light`(강조 보더) — 둘 다 라이트 테마 오버라이드 실존 [확인 variables.css:67~68, 275~276] |
| 승자 강조/펄스 | `--fm-accent-primary`(#c9302c). 펄스는 §4의 오버레이 방식(글로우 토큰은 라이트 테마에서 transparent이므로 사용 금지) |
| 확정 상대 카드 | 보더 `--fm-accent-secondary`(#1e3a8a) 계열 1px 실선 |
| 텍스트 | `--fm-text-primary` / `--fm-text-secondary` / `--fm-text-muted` |
| 숫자(시드·점수·전적 수치) | `--fm-font-display` + 클래스 `.fm-num` — ⚠️ 한글 혼합 문자열에 `.fm-num` 금지(latin 서브셋만 로드 [확인]) → "2승 1패"는 `<span class="fm-num">2</span>승` 패턴(EventH2H `badgeHtml`이 이미 이 패턴 [확인 event_result.html:2743]) |
| 간격/라운드 | `--fm-space-2/3/4/6`, `--fm-radius-sm/md` |
| 그림자 | `--fm-shadow-lg` (데스크톱 카드) |
| 전환 | `--fm-transition-fast/normal` |

- 보라·다색 그라데이션 금지. 그라데이션 자체를 쓰지 않는다(면 색상만).
- 라이트/다크: 위 토큰이 테마별 값을 이미 가지므로 시트 CSS에 `[data-theme="light"]` 분기는 **기존 `.bottom-sheet` 라이트 규칙(mobile-ux.css:1404~)이 못 덮는 신규 요소에만** 추가한다. 고정 rgba 신규 도입 금지.
- 색상만으로 정보 전달 금지 체크리스트: 승자(색+배지+굵기), 예상(점선+배지), 전적 우세/열세(기존 h2h-badge가 색+숫자 텍스트 병용 [확인]).

### 5-2. 모바일(기본, ≤1024px)
`.bottom-sheet` 그대로: 하단 고정, `max-height: 80vh`, 핸들+스와이프 닫기, `padding-bottom: calc(72px + safe-area)` (하단 내비 위) [확인 mobile-ux.css:860]. 섹션 세로 스택, 대결 헤더는 2열 grid(`1fr auto 1fr`).

### 5-3. 데스크톱(>1024px) — `.match-sheet` 오버라이드

```css
@media (min-width: 1025px) {
  .match-sheet {
    left: auto; right: var(--fm-space-6); bottom: var(--fm-space-6);
    width: 420px; border-radius: var(--fm-radius-md);
    max-height: min(70vh, 640px);
    box-shadow: var(--fm-shadow-lg);
    padding-bottom: var(--fm-space-4);
  }
  .match-sheet .bottom-sheet-handle { display: none; }
  #match-sheet-backdrop { background: transparent; pointer-events: none; }
}
```

데스크톱은 백드롭 없이(대진표 계속 탐색 가능) 카드가 우측 하단에 뜬다. 닫기: X 버튼·Esc·다른 블록 클릭 시 내용 교체(재슬라이드 없이 콘텐츠 페이드 120ms).

---

## 6. "내 선수 여정" — 선수 루트 재편 [설계]

**현행이 헷갈리는 이유 (한 문장)**: 드롭다운 후보가 이벤트 형식에 따라 달라져서 — 단일 DE는 참가자 전원, Dual DE는 `to_dict()`에 `seeding` 키가 없어 시드 32명만 노출된다(`event_result.html:1524~1527` + `bracket_utils.py:129~140` [확인]) — 사용자는 "전체도 아니고 시드만도 아닌" 목록을 보게 된다.

**결론: 없애지 않고 유지 + 개편.** 근거: 매치 시트는 "이 경기"에 답하고, 여정은 "이 선수의 대회 전체"에 답한다. 학부모 1차 시나리오(우리 애 오늘 어떻게 되나)는 후자다. 흡수하면 시트가 비대해지고 선수 단위 진입점이 사라진다.

변경 명세:

1. **이름**: 위젯 타이틀 `🧭 선수 루트` → `내 선수 여정` (i18n 키 추가, en: "Player Path"). 부제 1줄: "선수를 고르면 이 대회의 DE 경로를 처음부터 끝까지 보여줍니다".
2. **선수 선택 = 자동완성 교체** (드롭다운 제거): 기존 엔드포인트 `GET /api/events/{sub_event_cd}/players/search?q=` 사용 — 이 API는 이미 de-route JS가 최종순위 채움에 쓰고 있다 [확인 event_result.html:2624]. **서버 무변경으로 전 참가자(예선 포함) 선택 가능.** 입력 UI는 기존 `player-search.css` 어휘 재사용. 내 선수(`getMyPlayerNames`)는 입력창 아래 칩으로 상시 노출 — 탭 1회로 로드.
3. **기본 자동 선택 로직 유지** [확인 2677~2688]: `?highlight` → My Player(동기) → Favorites(비동기). 변경 없음.
4. **phase 라벨**: `de-results`의 신규 `de_phase`(§3-2)로 노드 라운드를 `예선 128강`/`본선 64강`으로 표기. `de_phase`가 빈 값이면 라운드명만(오표기 금지).
5. **미래 노드(예상)**: 기존 `drt-future` 점선 유지 + `예상` pill 배지 추가(시트와 동일 어휘). de-prediction 수리(3D) 전까지 256 브래킷 이벤트에서는 미래 노드에 후보를 나열하지 않고 "다음: {라운드}" 라벨만 표시하는 안전 모드 플래그를 둔다 — 판정: `pred.player.seed`가 null이거나 `event_first_round`가 실제 시작 라운드(브래킷 DOM의 첫 라운드명)와 다르면 안전 모드.
6. 렌더 함수(`render()`, `event_result.html:2542~2634`)와 노드 스타일(`drt-*`)은 유지 — 변경은 헤더/선택 UI/라벨/배지 4곳으로 한정한다.

---

## 7. 구현 분할 · 파일 소유권 · 충돌 지점

### 단계 3A — 서버 확장 (독립 배포 1)
- `app/server.py`: §3-1(`_eh2h_build` de_* 필드), §3-2(`de_results`에 `de_phase`) — 추가 필드만, 기존 소비자 무영향.
- `app/de_transforms.py`: §3-2의 dual 분기 폴백 확인/보강 (⚠️ **de-phase 에이전트가 `bracket_utils.py`를 잡고 있다** — de_transforms는 소유권 밖이지만 같은 정규화 계층이므로, 3A 착수 전 de-phase 에이전트의 1845 수정 diff를 읽고 동일 폴백 순서를 맞출 것).
- 검증: `curl /api/events/COMPS000000000004159/head-to-head?player=...`에 de_* 필드, `de-results`에 de_phase 확인.

### 단계 3B — 매치 시트 (독립 배포 2)
- **신규** `static/js/match-sheet.js` (~300줄): MatchSheet 모듈(open/close/파싱/인접성/전적 로드/렌더), `EventH2H.getRecord(myKo, oppKo)` 공개 메서드는 event_result.html의 EventH2H IIFE return에 1줄 추가.
- **신규** `static/css/match-sheet.css` (~150줄): §5.
- `templates/event_result.html`: ① `</body>` 직전 시트 DOM + `<script src>`/`<link>`(캐시버스터) ② `EVENT_WEAPON` 전역 1줄 ③ EventH2H return에 getRecord 추가. — ⚠️ **de-myplayer 에이전트가 event_result.html을 잡고 있다.** 충돌 최소화 규칙: 3B의 편집은 위 3곳(파일 말미 + EventH2H return문 + 전역 변수 블록)으로만 한정하고, de-myplayer의 작업 구역(내 선수 스트립 — DE 탭 상단, PlayerHighlighter 연동부)과 줄이 겹치지 않음을 착수 시 diff로 확인. 겹치면 de-myplayer 머지 후 리베이스.
- `bracket.html`·`bracket.css`·`player-search.js`·`dual-bracket.js`는 **건드리지 않는다**(각각 de-myplayer/de-phase 소유).
- `templates/base.html`: `?v=` 캐시버스터 범프 (🔴 필수 — 2026-08-06 사고 규칙).

### 단계 3C — 내 선수 여정 (독립 배포 3)
- `templates/event_result.html`: de-route 블록(1523~1577 마크업/스타일, 2510~2692 JS) 개편 — §6. ⚠️ 같은 파일이지만 de-myplayer·3B와 **구역이 다름**(줄 범위 명시했으므로 구역 밖 수정 금지).
- i18n: `app/i18n/translations/*/common.json` 7개 언어에 신규 키("내 선수 여정", "예상", "첫 대결(DE)" 등 — 기존 키 재사용 우선).

### 단계 3D — de-prediction 수리 (독립 배포 4, 시트와 여정의 "이후 경로" 강화)
- `app/server.py:3717~4277`: ① round_order에 256강 추가(3800) ② dual DE: `normalized_bracket`이 dual이면 phase별로 분리 계산 — 본선은 `second_de.seeding`(1~64 재시드), 예선은 `first_de.seeding` ③ potential_opponents의 인라인 h2h 스캔(4229~4246) 제거 — 클라이언트가 EventH2H로 대체(응답 필드는 빈 객체 유지로 하위호환) ④ bracket math에 256 지원(`generate_bracket_matches`는 이미 재귀라 크기 무관 [확인 3937~3957] — 라운드명 매핑만 추가).
- 배포 후: 여정 위젯 안전 모드 해제, 시트 ⑤에 "이후 전체 경로" 확장 가능.

### 회귀 위험
- EventH2H 캐시 구조에 의존(§2-5 경로 1) — EventH2H 내부 구조가 바뀌면 getRecord만 유지되면 됨(캡슐화 경계).
- 시트의 DOM 파싱은 `bracket.html` 클래스 계약에 의존 — de-myplayer가 클래스명을 바꾸면 파손. **계약 고정 목록**: `.bracket-match`, `.match-card`, `.match-player`, `.card-player`, `.player-seed`, `.player-seed-badge`, `.player-name`, `.player-score`, `.player-score-badge`, `data-match-id`, `data-round`, `data-round-panel`, `.de-phase-panel[data-phase]`, `winner`/`bye`/`forfeit`/`bye-match` 클래스. 이 목록을 de-myplayer·de-phase 에이전트에 공유할 것.
- 인접성 계산은 "라운드 내 DOM 순서 = 대진 순서" 가정에 의존 [확인 — 템플릿이 bouts_by_round 순서대로 렌더]. Phase 0 분배 수정으로 순서가 재정렬되므로 **3B 검증은 반드시 Phase 0 배포 후 실데이터(COMPM00722)로** 수행.

### 검증 체크리스트 (각 단계 공통)
1. 남에(256 dual)·여에(128 dual)·일반 단일 DE(예: 최근 종별대회 아무 종목) 3종에서 시트 열기/전적/다음 상대 확인.
2. 모바일 뷰포트(390px)에서 하단 내비와 겹침 없음, 스와이프 닫기, 트리뷰·리스트뷰 양쪽에서 열림.
3. `prefers-reduced-motion` 에뮬레이션에서 즉시 표시.
4. 라이트(ko)/다크(en) 양 테마 + `node ~/.claude/skills/impeccable/scripts/detect.mjs --json` 신규 파일 검사.
5. 가드 발동 케이스: 다음 라운드 없는 결승, 예선 마지막 라운드, bye 인접.

---

## 8. 명세에서 의도적으로 제외한 것 (스코프 아웃)

- phase 경계(예선→본선)를 넘는 상대 확정 계산 — 시드 재배정 때문에 인접성 불성립, 3D 이후 재검토.
- 경기 "진행 중" 실시간 상태 — 원천 데이터에 없음.
- 시트 내 미니 브래킷 시각화 — B안(미니맵)과 중복, 보고서 C-2 후순위 결정 유지.
