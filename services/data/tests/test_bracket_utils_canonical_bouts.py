"""get_canonical_bouts() / dedupe_bouts_by_identity() 회귀 테스트.

2026-09-28 스키마 일관성 감사에서, `scripts/repair_collapsed_de.py` 와
`scripts/repair_computed_team_finals.py` 가 다음 패턴으로 경기 수를 이중 집계하는
것을 발견했다:

    out = list(de.get("full_bouts") or []) + list(de.get("bouts") or [])

`full_bouts`와 `bouts`에 같은 경기가 동시에 들어 있는 브래킷이 실제로 존재한다
(`app/data_validator.py::_get_full_bouts_from_bracket` 주석 참조). 이 테스트는
`app/bracket_utils.py`의 단일 진입점이 그 중복을 만들지 않는다는 것과,
그 진입점을 거치면 이미 합쳐진(이중 집계된) 리스트도 정리된다는 것을 고정한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.bracket_utils import get_canonical_bouts, dedupe_bouts_by_identity


def _bout(round_name, match_number, p1="A", p2="B", de_phase=None):
    b = {
        "bout_id": f"{round_name}_{match_number:02d}",
        "round_name": round_name,
        "match_number": match_number,
        "player1_name": p1,
        "player2_name": p2,
    }
    if de_phase:
        b["de_phase"] = de_phase
    return b


class TestSingleBracketPriority:
    def test_full_bouts_only(self):
        bracket = {"full_bouts": [_bout("64강", 1), _bout("64강", 2)]}
        assert len(get_canonical_bouts(bracket)) == 2

    def test_bouts_alias_only(self):
        bracket = {"bouts": [_bout("32강", 1), _bout("32강", 2), _bout("32강", 3)]}
        assert len(get_canonical_bouts(bracket)) == 3

    def test_bouts_by_round_only_legacy(self):
        bracket = {
            "bouts_by_round": {
                "16강": [_bout("16강", 1), _bout("16강", 2)],
                "8강": [_bout("8강", 1)],
            }
        }
        assert len(get_canonical_bouts(bracket)) == 3

    def test_full_bouts_takes_priority_over_bouts_by_round(self):
        """full_bouts 가 있으면 bouts_by_round 는 아예 읽지 않는다(합치지 않는다)."""
        bracket = {
            "full_bouts": [_bout("64강", 1)],
            "bouts_by_round": {"64강": [_bout("64강", 1), _bout("64강", 2)]},
        }
        bouts = get_canonical_bouts(bracket)
        assert len(bouts) == 1

    def test_empty_full_bouts_falls_back_to_bouts_by_round(self):
        bracket = {
            "full_bouts": [],
            "bouts_by_round": {"64강": [_bout("64강", 1), _bout("64강", 2)]},
        }
        assert len(get_canonical_bouts(bracket)) == 2


class TestDoubleCountingRegression:
    """repair_collapsed_de.py / repair_computed_team_finals.py 가 겪은 정확한 버그 형태."""

    def test_full_bouts_and_bouts_duplicated_does_not_double(self):
        same = [_bout("결승", 1, "X", "Y")]
        # 두 키에 완전히 같은 경기가 중복 저장된 실제 사례를 재현
        bracket = {"full_bouts": same, "bouts": same}
        bouts = get_canonical_bouts(bracket)
        assert len(bouts) == 1, (
            "full_bouts 를 우선 사용하므로 bouts 는 아예 읽지 않아야 한다 "
            "(둘을 이어붙이면 경기가 2배로 집계된다 — 실제로 겪은 버그)"
        )

    def test_naive_concatenation_is_still_safe_through_dedupe(self):
        """호출부가 실수로 두 소스를 이어붙여도(예: 버그 스크립트와 동일한 패턴),
        dedupe_bouts_by_identity() 를 한 번 거치면 원상 복구된다."""
        de = {"full_bouts": [_bout("결승", 1, "X", "Y")], "bouts": [_bout("결승", 1, "X", "Y")]}
        naive = list(de.get("full_bouts") or []) + list(de.get("bouts") or [])
        assert len(naive) == 2  # 버그 재현: 이중 집계된 상태

        fixed = dedupe_bouts_by_identity(naive)
        assert len(fixed) == 1  # 안전망을 거치면 정리됨

    def test_five_participant_bracket_does_not_inflate_to_46(self):
        """repair_collapsed_de.py 독스트링에 기록된 실측 사고
        ("5명 대회의 브래킷이 46경기로 부풀고 그중 24경기가 복제")의 축소 재현."""
        real_bouts = [_bout("8강", i) for i in range(1, 5)] + [_bout("준결승", i) for i in range(1, 3)] + [_bout("결승", 1)]
        # 오염: 같은 경기가 bouts 키에도 복제되어 들어감
        bracket = {"full_bouts": real_bouts, "bouts": list(real_bouts)}
        bouts = get_canonical_bouts(bracket)
        assert len(bouts) == len(real_bouts) == 7


class TestDualDE:
    def test_first_and_second_de_combined_no_double_read(self):
        bracket = {
            "format": "dual_de",
            "first_de": {"full_bouts": [_bout("64강", 1, de_phase="qualifying")]},
            "second_de": {"full_bouts": [_bout("64강", 1, de_phase="main")]},
            # 최상위에도 데이터가 있지만, 서브 브래킷이 있으므로 절대 읽으면 안 된다
            "full_bouts": [_bout("64강", 1, de_phase="qualifying")] * 5,
        }
        bouts = get_canonical_bouts(bracket)
        # 예선 64강_01 과 본선 64강_01 은 de_phase 가 다르므로 서로 다른 경기 = 2건
        assert len(bouts) == 2

    def test_both_sub_brackets_empty_falls_back_to_top_level(self):
        bracket = {
            "format": "dual_de",
            "first_de": {},
            "second_de": {},
            "full_bouts": [_bout("64강", 1), _bout("64강", 2)],
        }
        bouts = get_canonical_bouts(bracket)
        assert len(bouts) == 2

    def test_missing_bracket_returns_empty(self):
        assert get_canonical_bouts(None) == []
        assert get_canonical_bouts({}) == []
        assert get_canonical_bouts({"format": "dual_de"}) == []
