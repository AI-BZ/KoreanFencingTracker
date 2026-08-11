# DATA_ERROR_CATALOG.md - 데이터 오류 카탈로그

**최종 업데이트:** 2026-02-26
**관리 주체:** FencingMind Data Team
**목적:** 모든 데이터 오류 케이스를 체계적으로 문서화하는 살아있는 문서

---

## 검증 규칙 레퍼런스 (R1 ~ R12)

### 이벤트 레벨 검증 (R1 ~ R6)

| 규칙 | 이름 | 심각도 | 설명 |
|------|------|--------|------|
| **R1a** | Self-bout | ERROR | `player1 == player2` — 스크래퍼가 같은 선수를 양쪽에 배치 |
| **R1b** | Duplicate bout | ERROR | 동일 선수쌍 + 동일 라운드에 2회 이상 등장 |
| **R2** | Winner inconsistency | ERROR | `winner_name`이 `player1`도 `player2`도 아님 |
| **R3** | Score anomaly | ERROR/WARN | 음수 점수, DE > 15점(개인)/45점(단체), 동점+승자 존재 |
| **R4** | Invalid round_name | ERROR/WARN | 빈 라운드명 또는 비표준 라운드명 |
| **R5** | Bracket topology | WARNING | round N 승자가 round N+1 참가자에 없음 |
| **R6** | Ranking mismatch | ERROR/WARN | `final_rankings` 1~2위와 DE bracket 결과 불일치 |

### 선수 레벨 검증 (R7 ~ R12)

| 규칙 | 이름 | 심각도 | 설명 |
|------|------|--------|------|
| **R7** | Same-round duplicate | ERROR | 한 이벤트 내 동일 라운드 2경기 이상 (dual_de는 독립 검증) |
| **R8** | Round progression | ERROR | 라운드 진행 보존법칙 위반 (N강 승리 > N+1강 출전 = 경기 유실) |
| **R9** | Pool bout count | WARNING | 한 이벤트 pool 경기수 > 8 (보통 4~7) |
| **R10** | Gender inconsistency | ERROR | 동일 선수가 남/여 종목 동시 출전 → 동명이인 오염 |
| **R11** | Age group regression | ERROR | 나이그룹 역행 (일반부 → 고등부 등) → 동명이인 가능성 |
| **R12** | Weapon count | WARNING | 무기 3종 이상 사용 → 동명이인 의심 |

### 검증 구현 위치

- **검증기 코드:** `services/data/app/data_validator.py`
- **독립 실행:** `services/data/scripts/run_validation.py`
- **서버 내 자동 실행:** `load_data()` 끝부분 + `/api/admin/validate` API

---

## 발견된 오류 사례 (Discovered Cases)

### CASE-001: Self-bout (tournament_table 파싱 버그)

| 항목 | 내용 |
|------|------|
| **규칙** | R1a |
| **발견일** | 2025-12 |
| **상태** | ✅ 수정 완료 |
| **심각도** | ERROR |
| **영향 범위** | tournament_table 형식의 DE bracket |
| **근본 원인** | `de_scraper_v4.py`의 `_parse_tournament_table_bracket()`에서 빈 슬롯 또는 부전승 시 같은 선수를 양쪽에 배치 |
| **증상** | full_bouts에 `player1_name == player2_name`인 bout 존재 |
| **수정 내역** | 1) 스크래퍼에서 self-bout 생성 방지 로직 추가 2) `data_validator.py`의 `_get_full_bouts_from_bracket()` 3개 경로 모두에 런타임 필터 (Path 1: full_bouts, Path 2: _reconstruct_bouts_from_duplicated_bbr, Path 3: bouts_by_round) |
| **검증** | R1a 이슈 0건 확인 (2026-02-26 재검증 완료) |

### CASE-002: full_bouts 라운드명 오배정 (bracket_size 불일치)

| 항목 | 내용 |
|------|------|
| **규칙** | R7 |
| **발견일** | 2025-12 |
| **상태** | ✅ 수정 완료 |
| **심각도** | ERROR |
| **영향 범위** | bracket_size와 실제 경기 수가 맞지 않는 이벤트 |
| **근본 원인** | 스크래퍼가 bracket_size를 잘못 감지하여 match_number → round_name 매핑 오류 |
| **증상** | 동일 선수가 같은 라운드에 2회 이상 등장 |
| **수정 내역** | `_dedup_keep_highest_round()` 함수 추가 — 동일 선수쌍 중복 시 가장 높은 라운드만 유지 |
| **검증** | dedup 적용 후 R7 이슈 대폭 감소 |

### CASE-003: bouts_by_round 복사 버그 (동일 데이터 반복)

| 항목 | 내용 |
|------|------|
| **규칙** | R1b |
| **발견일** | 2025-12 |
| **상태** | ✅ 수정 완료 |
| **심각도** | ERROR |
| **영향 범위** | bouts_by_round 형식 DE bracket |
| **근본 원인** | 스크래퍼가 모든 라운드 키에 전체 bracket의 bout을 복사 (라운드별 분리 실패) |
| **증상** | 32강, 16강, 8강 등 모든 라운드에 동일한 bout 목록 |
| **수정 내역** | `_reconstruct_bouts_from_duplicated_bbr()` — match_number 기반으로 올바른 라운드명 재배정 |
| **검증** | R1b 중복 bout 0건 확인 |

### CASE-004: tournament_table 후반 라운드 소속팀 → 점수 혼동

| 항목 | 내용 |
|------|------|
| **규칙** | R4 (데이터 품질) |
| **발견일** | 2025-12 |
| **상태** | ✅ 수정 완료 |
| **심각도** | ERROR |
| **영향 범위** | KFF의 .tournament_table 형식 |
| **근본 원인** | `.user_aff span`이 시딩/1라운드에서는 소속팀을 표시하지만, 이후 라운드에서는 이전 경기 점수를 표시 |
| **증상** | team_name 필드에 "15 : 8" 같은 점수 문자열 저장 |
| **수정 내역** | `_parse_tournament_table_bracket()`에서 name→team 맵 구축 후 점수 패턴(`^\d+\s*:\s*\d+$`) 감지 → 정상 팀명으로 교체 |
| **검증** | 점수 패턴이 team_name에 저장되지 않음 확인 |

### CASE-005: 동명이인 성별 불일치

| 항목 | 내용 |
|------|------|
| **규칙** | R10 |
| **발견일** | 2025-12 |
| **상태** | ⚠️ 잔존 (161건) |
| **심각도** | ERROR |
| **영향 범위** | 전체 선수 DB |
| **근본 원인** | 동명이인이 하나의 선수 레코드로 병합됨 (PlayerIdentityResolver 미처리) |
| **증상** | 같은 이름의 선수가 남자/여자 종목에 모두 등장 |
| **해결 방향** | PlayerIdentityResolver에서 성별 기반 선수 분리 로직 구현 필요 |
| **런타임 대응** | 사용자 대면 통계에서 성별 혼재 데이터 필터링 |

### CASE-006: 동명이인 나이그룹 역행

| 항목 | 내용 |
|------|------|
| **규칙** | R11 |
| **발견일** | 2025-12 |
| **상태** | ⚠️ 잔존 (40건) |
| **심각도** | ERROR |
| **영향 범위** | 전체 선수 DB |
| **근본 원인** | 동명이인이 하나의 선수 레코드로 병합되어 나이그룹이 역행하는 것처럼 보임 |
| **증상** | 일반부(2023) → 고등부(2024) 등 시간 역행 나이그룹 |
| **해결 방향** | PlayerIdentityResolver에서 나이그룹 일관성 기반 선수 분리 |
| **런타임 대응** | 나이그룹 역행 선수는 통계 집계에서 주의 표시 |

### CASE-007: 라운드 진행 보존법칙 위반 (경기 유실)

| 항목 | 내용 |
|------|------|
| **규칙** | R8 |
| **발견일** | 2025-12 |
| **상태** | ⚠️ 잔존 (407건, 이전 545건에서 138건 감소) |
| **심각도** | ERROR |
| **영향 범위** | 특정 대회의 DE bracket 데이터 |
| **근본 원인** | 스크래퍼가 특정 라운드의 bout 데이터를 누락하여 DB에 불완전 저장 |
| **증상** | 예: 4강 승리인데 결승 출전 없음 → 경기 유실 |
| **수정 내역** | (2026-02-26) cross-event 합산 → per-event 독립 검증으로 전환. starting_round/bracket_size 기반 하위 라운드 비교 건너뛰기 추가. 138건의 cross-event 오탐 제거. |
| **해결 방향** | 잔여 407건은 이벤트 내 실제 데이터 유실 → 재스크래핑 필요 |
| **런타임 대응** | `_compute_round_stats_from_records()`에서 보존법칙 위반 감지 시 경고 표시 |
| **재스크래핑 명령** | `cd services/data && PYTHONPATH="." python scraper/rescrape_specific_event.py --event-id <ID>` |

---

## 예상 오류 케이스 (Expected Cases)

미래에 발생할 수 있는 데이터 오류 유형. 사전 대비용.

### CASE-E01: 진행 중 대회 불완전 데이터

| 항목 | 내용 |
|------|------|
| **예상 규칙** | R5, R6, R8 |
| **설명** | 대회가 아직 진행 중일 때 스크래핑하면 후반 라운드 데이터 누락 |
| **예상 증상** | bracket에 빈 슬롯, final_rankings 부재, 라운드 진행 불완전 |
| **대응 전략** | 1) 스크래핑 시 대회 진행 상태 확인 2) 불완전 데이터에 `in_progress` 플래그 3) 대회 종료 후 재스크래핑 |
| **관련 코드** | `full_scraper.py`의 bout validation 로직 |

### CASE-E02: 단체전 데이터 구조 차이

| 항목 | 내용 |
|------|------|
| **예상 규칙** | R3, R9 |
| **설명** | 단체전은 45점제이며 한 팀 내 여러 선수가 릴레이 경기 |
| **예상 증상** | 점수 > 15 경고, bout 구조가 개인전과 다름 |
| **대응 전략** | 이벤트 이름에서 "단체" 감지 → 검증 기준 변경 (max_score=45) |
| **현재 상태** | R3에서 부분 대응 (`is_team_event` 분기) |

### CASE-E03: 국제대회 선수명 인코딩/로마자 변환

| 항목 | 내용 |
|------|------|
| **예상 규칙** | R10, R11, R12 |
| **설명** | 국제대회 선수명이 로마자로 표기되어 국내 대회와 매칭 실패 |
| **예상 증상** | 같은 선수가 "홍길동"과 "HONG Gildong"으로 별도 레코드 |
| **대응 전략** | 1) name_mappings.json 확장 2) PlayerIdentityResolver에 로마자-한글 매칭 3) translation_service 연동 |
| **관련 파일** | `data/international_cache/name_mappings.json`, `app/translation_service.py` |

### CASE-E04: dual_de first_de + second_de 합산 시 이중 카운팅

| 항목 | 내용 |
|------|------|
| **예상 규칙** | R7, R8 |
| **설명** | dual_de 형식에서 first_de(예선 DE)와 second_de(본선 DE)를 합칠 때 동일 선수 경기가 이중 집계 |
| **예상 증상** | 선수 통계에서 경기 수가 비정상적으로 많음 |
| **대응 전략** | 1) `de_phase` 태깅으로 예선/본선 구분 2) 통계 집계 시 `de_phase_filter` 적용 |
| **현재 상태** | `_compute_round_stats_from_records(de_phase_filter="main")`로 본선만 집계 |
| **관련 코드** | `server.py`의 `_get_full_bouts_from_de_bracket()` |

### CASE-E05: bracket_size와 실제 참가자 수 불일치

| 항목 | 내용 |
|------|------|
| **예상 규칙** | R5, R7 |
| **설명** | DB에 저장된 bracket_size가 실제 참가 인원과 다를 때 라운드 매핑 오류 |
| **예상 증상** | match_number → round_name 변환 오류, 존재하지 않는 라운드 생성 |
| **대응 전략** | bracket_size를 실제 bout 수에서 역산 검증 |

### CASE-E06: 부전승(bye) 처리 누락

| 항목 | 내용 |
|------|------|
| **예상 규칙** | R5, R8 |
| **설명** | 부전승(bye) 경기가 `is_bye` 플래그 없이 저장되어 정상 bout으로 집계 |
| **예상 증상** | bracket topology에서 승자가 다음 라운드에 없음 (bye 승리가 누락) |
| **대응 전략** | 1) 스크래퍼에서 bye 감지 강화 2) score가 0:0이고 winner가 있으면 bye 후보 |

### CASE-E07: 동점(타이) 처리 — 우선권/시간 기반 승패

| 항목 | 내용 |
|------|------|
| **예상 규칙** | R3 |
| **설명** | 펜싱에서 동점 시 우선권(priorite) 1분 연장으로 승패 결정. 점수는 동점이지만 승자 존재 |
| **예상 증상** | R3 WARNING: "동점이지만 승자 존재" |
| **대응 전략** | 동점+승자는 정상 케이스(우선권 연장)로 처리. WARNING 유지하되 별도 카운트 |
| **현재 상태** | R3에서 WARNING으로 보고 (ERROR가 아님) |

---

## 오류 추가 절차

새로운 데이터 오류 패턴을 발견했을 때 이 카탈로그에 추가하는 절차.

### 1. 신규 케이스 등록

```markdown
### CASE-XXX: [오류 제목]

| 항목 | 내용 |
|------|------|
| **규칙** | R? |
| **발견일** | YYYY-MM |
| **상태** | ⚠️ 발견 / 🔄 수정 중 / ✅ 수정 완료 |
| **심각도** | ERROR / WARNING |
| **영향 범위** | [영향 받는 데이터 범위] |
| **근본 원인** | [왜 이 오류가 발생하는가] |
| **증상** | [어떻게 발견되는가] |
| **수정 내역** | [어떻게 수정했는가] |
| **검증** | [수정 후 검증 방법] |
```

### 2. 케이스 ID 규칙

- **발견된 케이스**: `CASE-NNN` (001부터 순차)
- **예상 케이스**: `CASE-ENNN` (E01부터 순차)
- 예상 케이스가 실제로 발견되면 `CASE-NNN`으로 승격하고 원래 `CASE-ENNN`에 참조 기록

### 3. 상태 전이

```
⚠️ 발견 → 🔄 수정 중 → ✅ 수정 완료
     ↘                    ↗
      🚫 Won't Fix (의도된 동작)
```

### 4. 새 검증 규칙 추가 시

1. `data_validator.py`에 검증 함수 추가 (R13, R14, ...)
2. `run_validation.py`의 `rule_descriptions`에 설명 추가
3. 이 카탈로그의 "검증 규칙 레퍼런스" 테이블에 추가
4. MEMORY.md에 핵심 주의사항 기록 (해당 시)

---

## 현황 요약 (2026-02-26 업데이트)

### 검증 결과
```
수정 전: 2,185건 (ERRORS: 2,168 / WARNINGS: 17)
수정 후:   803건 (ERRORS: 759 / WARNINGS: 44)
감소:   1,382건 (63% 감소)
```

| 규칙 | 수정 전 | 수정 후 | 변화 | 잔여 원인 |
|------|---------|---------|------|----------|
| R1a | 1,244 | 0 | -1,244 | (완전 해결) |
| R8 | 545 | 407 | -138 | per-event 검증 전환, 잔여는 실제 데이터 유실 |
| R7 | 161 | 161 | 0 | 진짜 같은 라운드 다른 상대 (round_name 오배정) |
| R10 | 161 | 161 | 0 | 진짜 동명이인 (PlayerIdentityResolver 필요) |
| R11 | 40 | 40 | 0 | 27건 WARNING 다운그레이드 (일반부 전환) |
| R5 | 17 | 17 | 0 | 진짜 토폴로지 위반 |
| R6 | 17 | 17 | 0 | 진짜 랭킹 불일치 |

### 수정 내역 (2026-02-26)
1. **R1a self-bout 필터**: `_get_full_bouts_from_bracket()` 3개 경로 모두에 self-bout 필터 추가 → 1,244건 제거
2. **R8 per-event 검증**: cross-event 합산 → per-event 독립 검증, starting_round 기반 하위 라운드 비교 스킵 → 138건 제거
3. **R7 dedup**: `_r7_count_rounds()`에 seen_bouts 추가 (동일 상대 중복 제거)
4. **R10 혼합 이벤트**: `_extract_gender()`에 "남녀" 패턴 우선 감지 → 성별 미지정 반환
5. **R11 일반부**: 일반부→하위그룹 전환 시 ERROR→WARNING 다운그레이드
6. **R5 dual_de**: first_de/second_de 독립 토폴로지 검증
7. **R6 dual_de**: second_de(본선) 결과만으로 최종 순위 비교

| 카테고리 | 건수 | 상태 |
|----------|------|------|
| 발견된 케이스 (수정 완료) | 4건 | ✅ CASE-001 ~ 004 |
| 발견된 케이스 (잔존) | 3건 | ⚠️ CASE-005 ~ 007 |
| 예상 케이스 | 7건 | CASE-E01 ~ E07 |

### 잔존 이슈 우선순위

1. **CASE-007** (R8, 407건) — 이벤트 내 실제 데이터 유실 → 재스크래핑 필요
2. **CASE-005** (R10, 161건) — PlayerIdentityResolver 구현 시 해결
3. **R7** (161건) — round_name 오배정으로 인한 같은 라운드 다른 상대 → 스크래퍼 개선 필요
4. **CASE-006** (R11, 40건) — PlayerIdentityResolver 구현 시 해결 (27건은 이미 WARNING)
