# Age-Group Classifier Divergence

FencingMind에는 이벤트명을 나이 그룹으로 분류하는 함수가 **의도적으로 두 개** 있다.

| 함수 | 위치 | 출력 체계 |
|------|------|-----------|
| `extract_age_group` | `services/data/app/server.py` | **FIE 코드** — `Y8 / Y10 / Y12 / Y14 / U17 / Cadet / Junior / Veteran` |
| `extract_age_group` | `services/data/ranking/calculator.py` | **리그 코드** — `E1 / E2 / E3 / MS / HS / UNI / SR / U17` |

두 함수는 용도가 다르다. server 쪽은 FIE 나이 카테고리 코드(UI/이벤트 표시)를, calculator 쪽은 국내 나이리그 랭킹 산정용 리그 코드를 만든다. 따라서 출력 어휘가 다른 것은 정상이고 의도된 설계다.

## 문제: 어휘 차이가 아니라 파싱 규칙 자체가 다르다

두 함수는 단순히 같은 나이 버킷을 다른 이름으로 부르는 데 그치지 않는다. **아래 13개 입력에서는 서로 다른 나이 버킷으로 분류한다.** 즉 정규 형태로 매핑해 비교해도 결과가 어긋난다. 한쪽이 인식하는 키워드를 다른 쪽이 인식하지 못해 기본값으로 떨어지는 경우가 대부분이다.

정규화 매핑(비교 기준):

- FIE → canon: `Y8→E12, Y10→E34, Y12→E56, Y14→MID, Cadet→HIGH, Junior→UNIV, Veteran→SR, U17→U17`
- 리그 → canon: `E1→E12, E2→E34, E3→E56, MS→MID, HS→HIGH, UNI→UNIV, SR→SR, U17→U17`

### 13개 불일치 입력

| 입력 이벤트명 | server (FIE) | calculator (league) | 비고 |
|---------------|:------------:|:-------------------:|------|
| `초등부 플뢰레` | `Y12` | `SR` | calculator는 학년 미지정 '초등'을 인식 못해 기본값 SR로 떨어짐. server는 초등 기본값 Y12 |
| `U15 플뢰레` | `Cadet` | `MS` | server는 U15를 Cadet(고등 카테고리), calculator는 중등(MS)으로 분류 |
| `14세이하 플뢰레` | `Y14` | `SR` | calculator에 '14세이하' 키워드 없음 → 기본 SR |
| `15세이하 에페` | `Cadet` | `SR` | calculator에 '15세이하' 키워드 없음 → 기본 SR |
| `16세이하 사브르` | `Cadet` | `SR` | calculator에 '16세이하' 키워드 없음 → 기본 SR |
| `18세이하 에페` | `Cadet` | `SR` | calculator는 `U18`은 인식하나 '18세이하' 한글 텍스트는 미인식 → 기본 SR |
| `카뎃 남자 플뢰레` | `Cadet` | `SR` | calculator에 '카뎃' 키워드 없음 → 기본 SR |
| `Cadet Women Foil` | `Cadet` | `SR` | calculator에 영문 'Cadet' 키워드 없음 → 기본 SR |
| `Junior Men Epee` | `Junior` | `SR` | calculator에 영문 'Junior' 키워드 없음 → 기본 SR |
| `주니어 여자 사브르` | `Junior` | `SR` | calculator에 '주니어' 키워드 없음 → 기본 SR |
| `초등1학년 플뢰레` | `Y12` | `E1` | calculator는 '초등1'을 E1로 인식. server 정규식은 '1-2/1~2'만 매칭해 초등 기본 Y12 |
| `고교 남자 사브르` | `Veteran` | `HS` | server는 '고교' 미인식(고등/카뎃만 인식) → 기본 Veteran. calculator는 '고교' 인식 HS |
| `U23 플뢰레` | `Veteran` | `UNI` | server에 U23 패턴 없음 → 기본 Veteran. calculator는 U23 인식 UNI |

## ⚠️ 경고: 랭킹 포인트 산정 영향 가능

이 불일치들은 랭킹 포인트 산정에 영향을 줄 수 있다. 특히 calculator가 `카뎃` / `Cadet` / `Junior` / `주니어` / `고교` / `14~16세이하` 이벤트를 기본값 `SR`로 잘못 분류하면, 해당 선수가 **잘못된 나이리그 랭킹**에 편입될 수 있다.

**실제 KFA 이벤트명에 이 패턴들이 얼마나 등장하는지 확인한 뒤, 데이터 소유자 판단 하에 별도 수정이 필요하다.** 이 수정은 랭킹의 의미(어느 선수가 어느 나이리그에 들어가는지)를 바꾸므로 현재 세션 스코프 밖이다.

## 테스트로 고정된 현재 동작

두 함수의 현재 출력은 `tests/unit/test_extract_age_group_characterization.py`에 특성화 테스트(characterization test)로 고정되어 있다. 이 테스트는 정확성(correctness)이 아니라 **현재 상태(status quo)**를 검증한다. 어느 한쪽 함수를 변경하면 테스트가 실패하므로 리뷰 단계에서 드리프트가 즉시 잡힌다.

위 불일치 중 하나를 의도적으로 수정하는 경우, 같은 변경에서 해당 테스트의 기대값을 갱신하고 랭킹 영향(어느 선수의 나이리그가 바뀌는지)을 반드시 기록해야 한다.
