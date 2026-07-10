"""Unit tests for pure logic in pipeline modules.

Covers side-effect-free rules that do not require video I/O, YOLO, or OCR:
- AutoLabeler.determine_label(): lamp-state + score-delta -> scorer label
- DataAugmentor.LABEL_FLIP_MAP: horizontal-flip label inversion rule

AutoLabeler.determine_label() references no instance state, so it is exercised
via object.__new__() to avoid the template-loading side effect in __init__.
"""

import pytest

from pipeline.auto_labeler import AutoLabeler
from pipeline.data_augmentor import DataAugmentor


@pytest.fixture
def labeler():
    """AutoLabeler instance without running __init__ (no template pickle load)."""
    return object.__new__(AutoLabeler)


class TestDetermineLabel:
    def test_none_score_returns_unknown(self, labeler):
        assert labeler.determine_label("On-On", None, 0, 1, 0) == "X"
        assert labeler.determine_label("On-On", 5, 5, None, 5) == "X"

    def test_both_lamps_left_priority(self, labeler):
        # left score +1, right unchanged -> left scored
        assert labeler.determine_label("On-On", 5, 5, 6, 5) == "L"

    def test_both_lamps_right_priority(self, labeler):
        assert labeler.determine_label("On-On", 5, 5, 5, 6) == "R"

    def test_both_lamps_no_change_is_tie(self, labeler):
        # simultaneous touch annulled -> tie
        assert labeler.determine_label("On-On", 5, 5, 5, 5) == "T"

    def test_both_lamps_both_increment_is_unknown(self, labeler):
        # both deltas 1 matches no branch -> unknown
        assert labeler.determine_label("On-On", 5, 5, 6, 6) == "X"

    def test_left_lamp_left_scored(self, labeler):
        assert labeler.determine_label("On-No", 5, 5, 6, 5) == "L"

    def test_left_lamp_offtarget_gives_right(self, labeler):
        # left lamp but left score unchanged -> off-target, right point
        assert labeler.determine_label("On-No", 5, 5, 5, 5) == "R"

    def test_right_lamp_right_scored(self, labeler):
        assert labeler.determine_label("No-On", 5, 5, 5, 6) == "R"

    def test_right_lamp_offtarget_gives_left(self, labeler):
        assert labeler.determine_label("No-On", 5, 5, 5, 5) == "L"

    def test_unrecognized_hit_type_is_unknown(self, labeler):
        assert labeler.determine_label("Off-Off", 5, 5, 6, 5) == "X"


class TestLabelFlipMap:
    def test_left_becomes_right(self):
        assert DataAugmentor.LABEL_FLIP_MAP["L"] == "R"

    def test_right_becomes_left(self):
        assert DataAugmentor.LABEL_FLIP_MAP["R"] == "L"

    def test_tie_stays_tie(self):
        assert DataAugmentor.LABEL_FLIP_MAP["T"] == "T"

    def test_inversion_is_symmetric(self):
        m = DataAugmentor.LABEL_FLIP_MAP
        assert m[m["L"]] == "L"
        assert m[m["R"]] == "R"

    def test_unknown_label_falls_through(self):
        # flip_clip uses LABEL_FLIP_MAP.get(label, label): unmapped labels pass through
        assert DataAugmentor.LABEL_FLIP_MAP.get("X", "X") == "X"
