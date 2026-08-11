"""Characterization tests pinning the CURRENT behavior of the two
`extract_age_group` implementations.

There are two intentionally-separate age classifiers:
  - services/data/app/server.py       -> FIE codes (Y8/Y10/Y12/Y14/U17/Cadet/Junior/Veteran)
  - services/data/ranking/calculator.py -> league codes (E1/E2/E3/MS/HS/UNI/SR/U17)

They do NOT merely differ in output vocabulary: they parse some inputs
differently (see docs/AGE_GROUP_DIVERGENCE.md). Because both feed ranking
points and event filtering (CLAUDE.md 제1원칙), their outputs must not drift
accidentally. These tests lock the current outputs so any change to either
function is caught in review. They assert the STATUS QUO, not correctness —
if a divergence is later deliberately fixed, update the expected value here in
the same change and record the ranking impact.
"""
import os

os.environ.setdefault("JWT_SECRET_KEY", "characterization-test-key-not-secret")

from ranking.calculator import extract_age_group as calc_extract_age_group  # noqa: E402
import app.server as server  # noqa: E402

server_extract_age_group = server.extract_age_group


SERVER_EXPECTED = {
    '여중 에페(개)': 'Y14', '남중 에페(개)': 'Y14', '여고 플뢰레': 'Cadet', '남고 사브르': 'Cadet',
    '여대 에페': 'Junior', '남대 플뢰레': 'Junior',
    '초등부 1-2학년 플뢰레': 'Y8', '초등부 3-4학년 에페': 'Y10', '초등부 5-6학년 사브르': 'Y12',
    '초등부 플뢰레': 'Y12', '일반부 에페': 'Veteran', '시니어 사브르': 'Veteran', '베테랑 플뢰레': 'Veteran',
    '중등부 사브르': 'Y14', '고등부 에페': 'Cadet', '대학부 플뢰레': 'Junior',
    'U9 플뢰레': 'Y8', 'U11 에페': 'Y10', 'U13 사브르': 'Y12', 'U15 플뢰레': 'Cadet', 'U17 에페': 'U17',
    'U18 사브르': 'Cadet', 'U20 플뢰레': 'Junior',
    '9세이하 플뢰레': 'Y8', '11세이하 에페': 'Y10', '13세이하 사브르': 'Y12', '14세이하 플뢰레': 'Y14',
    '15세이하 에페': 'Cadet', '16세이하 사브르': 'Cadet', '17세이하 플뢰레': 'U17', '18세이하 에페': 'Cadet',
    '20세이하 사브르': 'Junior', '2026 펜싱 국가대표선수 선발대회 여자 에페': 'Veteran',
    '카뎃 남자 플뢰레': 'Cadet', 'Cadet Women Foil': 'Cadet', 'Junior Men Epee': 'Junior',
    '주니어 여자 사브르': 'Junior', '제64회 전국남녀종별선수권 남중 에페': 'Y14',
    '회장배 여자 에페 U13': 'Y12', '회장배 남자 사브르 U17': 'U17', '초등1학년 플뢰레': 'Y12',
    '초등6학년 에페': 'Y12', '3~4학년 여자 플뢰레': 'Y10', '5~6학년 남자 에페': 'Y12', '1~2학년 사브르': 'Y8',
    '남중부 에페': 'Y14', '여중부 플뢰레': 'Y14', '고교 남자 사브르': 'Veteran', 'U23 플뢰레': 'Veteran',
    'Senior Epee': 'Veteran', 'Open 플뢰레': 'Veteran', '마스터즈 에페': 'Veteran', 'Veteran Sabre': 'Veteran',
    '여자 에페': 'Veteran', '남자 플뢰레': 'Veteran', '여자 사브르 개인전': 'Veteran', '혼성 플뢰레': 'Veteran',
    '': 'Veteran',
}

CALC_EXPECTED = {
    '여중 에페(개)': 'MS', '남중 에페(개)': 'MS', '여고 플뢰레': 'HS', '남고 사브르': 'HS',
    '여대 에페': 'UNI', '남대 플뢰레': 'UNI',
    '초등부 1-2학년 플뢰레': 'E1', '초등부 3-4학년 에페': 'E2', '초등부 5-6학년 사브르': 'E3',
    '초등부 플뢰레': 'SR', '일반부 에페': 'SR', '시니어 사브르': 'SR', '베테랑 플뢰레': 'SR',
    '중등부 사브르': 'MS', '고등부 에페': 'HS', '대학부 플뢰레': 'UNI',
    'U9 플뢰레': 'E1', 'U11 에페': 'E2', 'U13 사브르': 'E3', 'U15 플뢰레': 'MS', 'U17 에페': 'U17',
    'U18 사브르': 'HS', 'U20 플뢰레': 'UNI',
    '9세이하 플뢰레': 'E1', '11세이하 에페': 'E2', '13세이하 사브르': 'E3', '14세이하 플뢰레': 'SR',
    '15세이하 에페': 'SR', '16세이하 사브르': 'SR', '17세이하 플뢰레': 'U17', '18세이하 에페': 'SR',
    '20세이하 사브르': 'UNI', '2026 펜싱 국가대표선수 선발대회 여자 에페': 'SR',
    '카뎃 남자 플뢰레': 'SR', 'Cadet Women Foil': 'SR', 'Junior Men Epee': 'SR',
    '주니어 여자 사브르': 'SR', '제64회 전국남녀종별선수권 남중 에페': 'MS',
    '회장배 여자 에페 U13': 'E3', '회장배 남자 사브르 U17': 'U17', '초등1학년 플뢰레': 'E1',
    '초등6학년 에페': 'E3', '3~4학년 여자 플뢰레': 'E2', '5~6학년 남자 에페': 'E3', '1~2학년 사브르': 'E1',
    '남중부 에페': 'MS', '여중부 플뢰레': 'MS', '고교 남자 사브르': 'HS', 'U23 플뢰레': 'UNI',
    'Senior Epee': 'SR', 'Open 플뢰레': 'SR', '마스터즈 에페': 'SR', 'Veteran Sabre': 'SR',
    '여자 에페': 'SR', '남자 플뢰레': 'SR', '여자 사브르 개인전': 'SR', '혼성 플뢰레': 'SR', '': 'SR',
}

KNOWN_DIVERGENT_INPUTS = {
    '초등부 플뢰레', 'U15 플뢰레', '14세이하 플뢰레', '15세이하 에페', '16세이하 사브르',
    '18세이하 에페', '카뎃 남자 플뢰레', 'Cadet Women Foil', 'Junior Men Epee', '주니어 여자 사브르',
    '초등1학년 플뢰레', '고교 남자 사브르', 'U23 플뢰레',
}

_FIE_TO_CANON = {"Y8": "E12", "Y10": "E34", "Y12": "E56", "Y14": "MID", "Cadet": "HIGH",
                 "Junior": "UNIV", "Veteran": "SR", "U17": "U17"}
_LEAGUE_TO_CANON = {"E1": "E12", "E2": "E34", "E3": "E56", "MS": "MID", "HS": "HIGH",
                    "UNI": "UNIV", "SR": "SR", "U17": "U17"}


import pytest  # noqa: E402


@pytest.mark.parametrize("event_name,expected", sorted(SERVER_EXPECTED.items()))
def test_server_extract_age_group_pinned(event_name, expected):
    assert server_extract_age_group(event_name) == expected


@pytest.mark.parametrize("event_name,expected", sorted(CALC_EXPECTED.items()))
def test_calculator_extract_age_group_pinned(event_name, expected):
    assert calc_extract_age_group(event_name) == expected


def test_divergence_set_is_exactly_as_documented():
    observed = set()
    for name in SERVER_EXPECTED:
        s_canon = _FIE_TO_CANON[server_extract_age_group(name)]
        c_canon = _LEAGUE_TO_CANON[calc_extract_age_group(name)]
        if s_canon != c_canon:
            observed.add(name)
    assert observed == KNOWN_DIVERGENT_INPUTS
