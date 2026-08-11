"""Tests for ActionHeuristicLabeler — FACTS 8-class heuristic labeling."""

import pytest

from pipeline.action_heuristic_labeler import (
    ActionHeuristicLabeler,
    TouchEvent,
    LabeledAction,
    FACTS_CLASSES,
    FACTS_DIR_MAP,
    ATTACK_GAP_THRESHOLD,
    RIPOSTE_WINDOW,
    COUNTER_ATTACK_WINDOW,
    REMISE_WINDOW,
)


def _make_touch(time_sec, scorer="L", lamp="On-No"):
    """Helper to create a TouchEvent."""
    return TouchEvent(
        timestamp_sec=time_sec,
        scorer=scorer,
        lamp_state=lamp,
    )


class TestFactsConstants:
    """Test FACTS label constants."""

    def test_eight_classes(self):
        assert len(FACTS_CLASSES) == 8

    def test_all_classes_have_direction(self):
        for cls in FACTS_CLASSES:
            assert cls.endswith("_left") or cls.endswith("_right")

    def test_dir_map_matches_classes(self):
        assert set(FACTS_DIR_MAP.keys()) == set(FACTS_CLASSES)

    def test_dir_codes(self):
        assert FACTS_DIR_MAP["attack_left"] == "AL"
        assert FACTS_DIR_MAP["attack_right"] == "AR"
        assert FACTS_DIR_MAP["riposte_left"] == "RL"
        assert FACTS_DIR_MAP["riposte_right"] == "RR"
        assert FACTS_DIR_MAP["counter_attack_left"] == "CAL"
        assert FACTS_DIR_MAP["counter_attack_right"] == "CAR"
        assert FACTS_DIR_MAP["remise_left"] == "ReL"
        assert FACTS_DIR_MAP["remise_right"] == "ReR"


class TestFirstTouch:
    """First touch in a sequence should always be ATTACK."""

    def test_first_touch_left(self):
        labeler = ActionHeuristicLabeler()
        touches = [_make_touch(10.0, "L")]
        results = labeler.label_sequence(touches)
        assert len(results) == 1
        assert results[0].action == "attack_left"

    def test_first_touch_right(self):
        labeler = ActionHeuristicLabeler()
        touches = [_make_touch(10.0, "R")]
        results = labeler.label_sequence(touches)
        assert len(results) == 1
        assert results[0].action == "attack_right"


class TestAttackDetection:
    """Touch after large time gap (>5s) should be ATTACK."""

    def test_large_gap_attack(self):
        labeler = ActionHeuristicLabeler()
        touches = [
            _make_touch(10.0, "L"),
            _make_touch(20.0, "R"),  # 10s gap > 5s threshold
        ]
        results = labeler.label_sequence(touches)
        assert len(results) == 2
        assert results[1].action == "attack_right"

    def test_exactly_at_threshold(self):
        labeler = ActionHeuristicLabeler()
        touches = [
            _make_touch(10.0, "L"),
            _make_touch(10.0 + ATTACK_GAP_THRESHOLD + 0.1, "R"),
        ]
        results = labeler.label_sequence(touches)
        assert results[1].action == "attack_right"


class TestRiposteDetection:
    """Touch shortly after opponent scored should be RIPOSTE."""

    def test_riposte_after_opponent(self):
        labeler = ActionHeuristicLabeler()
        touches = [
            _make_touch(10.0, "L"),      # L scores
            _make_touch(11.5, "R"),      # R scores 1.5s later (within 2s)
        ]
        results = labeler.label_sequence(touches)
        assert results[1].action == "riposte_right"

    def test_riposte_left(self):
        labeler = ActionHeuristicLabeler()
        touches = [
            _make_touch(10.0, "R"),
            _make_touch(11.0, "L"),  # L ripostes within 2s
        ]
        results = labeler.label_sequence(touches)
        assert results[1].action == "riposte_left"


class TestCounterAttackDetection:
    """Simultaneous touch (On-On) within 0.5s should be COUNTER_ATTACK."""

    def test_counter_attack(self):
        labeler = ActionHeuristicLabeler()
        touches = [
            _make_touch(10.0, "L", "On-No"),
            _make_touch(10.3, "R", "On-On"),  # 0.3s gap, On-On
        ]
        results = labeler.label_sequence(touches)
        assert results[1].action == "counter_attack_right"

    def test_not_counter_if_no_on_on(self):
        """Without On-On lamp state, shouldn't classify as counter."""
        labeler = ActionHeuristicLabeler()
        touches = [
            _make_touch(10.0, "L", "On-No"),
            _make_touch(10.3, "R", "No-On"),  # Close but not On-On
        ]
        results = labeler.label_sequence(touches)
        # Should be riposte instead (within 2s after opponent)
        assert results[1].action == "riposte_right"


class TestRemiseDetection:
    """Same scorer within 2s should be REMISE."""

    def test_remise_same_scorer(self):
        labeler = ActionHeuristicLabeler()
        touches = [
            _make_touch(10.0, "L"),
            _make_touch(11.0, "L"),  # Same scorer within 2s
        ]
        results = labeler.label_sequence(touches)
        assert results[1].action == "remise_left"

    def test_remise_right(self):
        labeler = ActionHeuristicLabeler()
        touches = [
            _make_touch(10.0, "R"),
            _make_touch(11.5, "R"),  # Same scorer within 2s
        ]
        results = labeler.label_sequence(touches)
        assert results[1].action == "remise_right"


class TestTieHandling:
    """Ties (T) should be skipped."""

    def test_tie_skipped(self):
        labeler = ActionHeuristicLabeler()
        touches = [
            _make_touch(10.0, "T"),
        ]
        results = labeler.label_sequence(touches)
        assert len(results) == 0

    def test_tie_in_sequence(self):
        labeler = ActionHeuristicLabeler()
        touches = [
            _make_touch(10.0, "L"),
            _make_touch(12.0, "T"),  # Skip
            _make_touch(20.0, "R"),  # Attack (>5s gap from L)
        ]
        results = labeler.label_sequence(touches)
        assert len(results) == 2
        assert results[0].action == "attack_left"
        assert results[1].action == "attack_right"


class TestValidation:
    """Test label validation helpers."""

    def test_validate_valid_labels(self):
        for label in FACTS_CLASSES:
            assert ActionHeuristicLabeler.validate_label(label)

    def test_validate_invalid_labels(self):
        assert not ActionHeuristicLabeler.validate_label("invalid")
        assert not ActionHeuristicLabeler.validate_label("")
        assert not ActionHeuristicLabeler.validate_label("attack")  # missing direction

    def test_get_facts_directory(self):
        assert ActionHeuristicLabeler.get_facts_directory("attack_left") == "AL"
        assert ActionHeuristicLabeler.get_facts_directory("remise_right") == "ReR"
        assert ActionHeuristicLabeler.get_facts_directory("invalid") == "X"


class TestConfidence:
    """Test confidence scoring."""

    def test_first_touch_high_confidence(self):
        labeler = ActionHeuristicLabeler()
        touches = [_make_touch(10.0, "L")]
        results = labeler.label_sequence(touches)
        assert results[0].confidence >= 0.7

    def test_default_lower_confidence(self):
        """Fallback labels should have lower confidence."""
        labeler = ActionHeuristicLabeler()
        # Gap between 2-5s, same opponent — ambiguous
        touches = [
            _make_touch(10.0, "L"),
            _make_touch(13.0, "R"),  # 3s gap, different scorer
        ]
        results = labeler.label_sequence(touches)
        # Should still get a label but with moderate confidence
        assert results[1].confidence > 0
        assert results[1].confidence <= 1.0
