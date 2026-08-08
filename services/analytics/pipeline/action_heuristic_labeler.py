"""
Heuristic-based action labeling for FACTS 8-class classification.

Converts AutoLabeler's L/R/T/X (who scored) results into FACTS action classes
using temporal heuristics:
  - ATTACK: First touch, or >5s gap from previous
  - RIPOSTE: Touch within 2s after opponent scored
  - COUNTER_ATTACK: Simultaneous touch within 0.5s
  - REMISE: Same scorer within 2s of previous

Direction mapping:
  - Left scorer → *_left
  - Right scorer → *_right
"""

from dataclasses import dataclass
from typing import Optional, List, Tuple


# FACTS 8-class labels
FACTS_CLASSES = [
    "attack_left",       # AL
    "attack_right",      # AR
    "riposte_left",      # RL
    "riposte_right",     # RR
    "counter_attack_left",   # CAL
    "counter_attack_right",  # CAR
    "remise_left",       # ReL
    "remise_right",      # ReR
]

# FACTS directory codes
FACTS_DIR_MAP = {
    "attack_left": "AL",
    "attack_right": "AR",
    "riposte_left": "RL",
    "riposte_right": "RR",
    "counter_attack_left": "CAL",
    "counter_attack_right": "CAR",
    "remise_left": "ReL",
    "remise_right": "ReR",
}

# Heuristic thresholds (seconds)
ATTACK_GAP_THRESHOLD = 5.0       # >5s since last touch → new attack
RIPOSTE_WINDOW = 2.0            # within 2s after opponent's touch
COUNTER_ATTACK_WINDOW = 0.5     # simultaneous within 0.5s
REMISE_WINDOW = 2.0             # same scorer within 2s


@dataclass
class TouchEvent:
    """A touch event with timing and scorer information."""
    timestamp_sec: float     # Time in the match (seconds)
    scorer: str              # "L" (left), "R" (right), "T" (tie)
    lamp_state: str          # "On-On", "On-No", "No-On"
    clip_path: Optional[str] = None


@dataclass
class LabeledAction:
    """A touch event labeled with FACTS action class."""
    touch: TouchEvent
    action: str              # FACTS 8-class label
    confidence: float        # Heuristic confidence (0.0 - 1.0)
    reason: str              # Why this label was assigned


class ActionHeuristicLabeler:
    """
    Labels touch events with FACTS 8-class action labels using temporal heuristics.

    This is an approximate labeling method intended for bootstrapping training data.
    Human review should refine labels before final training.
    """

    def __init__(
        self,
        attack_gap: float = ATTACK_GAP_THRESHOLD,
        riposte_window: float = RIPOSTE_WINDOW,
        counter_attack_window: float = COUNTER_ATTACK_WINDOW,
        remise_window: float = REMISE_WINDOW,
    ):
        self.attack_gap = attack_gap
        self.riposte_window = riposte_window
        self.counter_attack_window = counter_attack_window
        self.remise_window = remise_window

    def label_sequence(self, touches: List[TouchEvent]) -> List[LabeledAction]:
        """
        Label a sequence of touch events with FACTS action classes.

        Args:
            touches: List of TouchEvents in chronological order.

        Returns:
            List of LabeledAction for each classifiable touch.
        """
        results = []

        for i, touch in enumerate(touches):
            # Skip ties and unknown scorers
            if touch.scorer not in ("L", "R"):
                continue

            action, confidence, reason = self._classify_touch(touches, i)
            if action is not None:
                results.append(LabeledAction(
                    touch=touch,
                    action=action,
                    confidence=confidence,
                    reason=reason,
                ))

        return results

    def _classify_touch(
        self,
        touches: List[TouchEvent],
        idx: int,
    ) -> Tuple[Optional[str], float, str]:
        """
        Classify a single touch using heuristic rules.

        Returns:
            (action_label, confidence, reason) or (None, 0, "") if unclassifiable.
        """
        touch = touches[idx]
        scorer = touch.scorer
        direction = "left" if scorer == "L" else "right"

        # Find previous touch (if any)
        prev_touch = touches[idx - 1] if idx > 0 else None
        time_gap = (
            touch.timestamp_sec - prev_touch.timestamp_sec
            if prev_touch else float("inf")
        )

        # Rule 1: Simultaneous (On-On) within counter-attack window
        if touch.lamp_state == "On-On" and prev_touch:
            if time_gap <= self.counter_attack_window:
                action = f"counter_attack_{direction}"
                return action, 0.6, f"simultaneous_within_{self.counter_attack_window}s"

        # Rule 2: Same scorer repeating within remise window
        if prev_touch and prev_touch.scorer == scorer:
            if time_gap <= self.remise_window:
                action = f"remise_{direction}"
                return action, 0.7, f"same_scorer_within_{self.remise_window}s"

        # Rule 3: Touch shortly after opponent scored → riposte
        if prev_touch and prev_touch.scorer != scorer and prev_touch.scorer in ("L", "R"):
            if time_gap <= self.riposte_window:
                action = f"riposte_{direction}"
                return action, 0.65, f"after_opponent_within_{self.riposte_window}s"

        # Rule 4: Large gap or first touch → attack
        if time_gap > self.attack_gap or prev_touch is None:
            action = f"attack_{direction}"
            return action, 0.8, f"gap>{self.attack_gap}s_or_first_touch"

        # Default: if none of the above apply clearly, treat as attack
        # (most common action in fencing)
        action = f"attack_{direction}"
        return action, 0.5, "default_attack"

    @staticmethod
    def get_facts_directory(action_label: str) -> str:
        """
        Get FACTS directory code for an action label.

        Args:
            action_label: Full label like "attack_left"

        Returns:
            Directory code like "AL"
        """
        return FACTS_DIR_MAP.get(action_label, "X")

    @staticmethod
    def validate_label(label: str) -> bool:
        """Check if a label is a valid FACTS 8-class label."""
        return label in FACTS_CLASSES
