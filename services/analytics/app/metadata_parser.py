"""Parse fencing metadata from video titles and filenames.

Extracts weapon, gender, age group, and bout type from YouTube
video titles or local filenames using keyword matching.
"""

from __future__ import annotations

import re
from typing import Optional


# Keyword maps (lowercase)
_WEAPON_KEYWORDS = {
    "foil": ["foil", "fleuret", "플뢰레"],
    "epee": ["epee", "épée", "에페"],
    "sabre": ["sabre", "saber", "사브르"],
}

# Women checked before men since "women" contains "men"
_GENDER_KEYWORDS = {
    "women": ["women's", "womens", "women", "female", "girls", "여자", "여"],
    "men": ["men's", "mens", "male", "boys", "남자", "남"],
}

# Patterns that need word-boundary matching to avoid false positives
_GENDER_BOUNDARY_PATTERNS = {
    "men": [r"\bmen\b"],
}

_AGE_GROUP_KEYWORDS = {
    "cadet": ["cadet", "cadets", "카뎃"],
    "junior": ["junior", "juniors", "주니어"],
    "senior": ["senior", "seniors", "시니어"],
    "veteran": ["veteran", "veterans", "베테랑"],
    "y10": ["y10", "y-10", "u10", "u-10"],
    "y12": ["y12", "y-12", "u12", "u-12"],
    "y14": ["y14", "y-14", "u14", "u-14"],
}

_BOUT_DE_KEYWORDS = [
    "final", "finals", "semifinal", "semi-final", "quarterfinal",
    "quarter-final", "결승", "준결승", "8강", "16강", "32강",
    "t64", "t32", "t16", "t8", "t4",
    "de", "direct elimination", "본선",
    "gold", "bronze",
]

_BOUT_POOL_KEYWORDS = [
    "pool", "pools", "poule", "예선", "풀",
]


def parse_fencing_metadata(text: str) -> dict:
    """Parse weapon, gender, age_group, bout_type from video title or filename.

    Args:
        text: Video title, filename, or description.

    Returns:
        Dict with keys:
            weapon: "foil"|"epee"|"sabre"|"unknown"
            gender: "men"|"women"|"unknown"
            age_group: "cadet"|"junior"|"senior"|"veteran"|"y10"|"y12"|"y14"|"unknown"
            bout_type: "pool"|"de"|"unknown"
            expected_final_score: 5 (pool) | 15 (DE) | None
    """
    lower = text.lower()

    weapon = _match_keywords(lower, _WEAPON_KEYWORDS)
    gender = _match_keywords(lower, _GENDER_KEYWORDS, _GENDER_BOUNDARY_PATTERNS)
    age_group = _match_keywords(lower, _AGE_GROUP_KEYWORDS)
    bout_type = _detect_bout_type(lower)
    expected_final_score = _infer_final_score(bout_type)

    return {
        "weapon": weapon,
        "gender": gender,
        "age_group": age_group,
        "bout_type": bout_type,
        "expected_final_score": expected_final_score,
    }


def _match_keywords(text: str, keyword_map: dict, boundary_patterns: dict = None) -> str:
    """Match text against a keyword map. Returns the first matching key or 'unknown'.

    Args:
        text: Lowercased input text.
        keyword_map: Dict of {result_key: [keywords]}.
        boundary_patterns: Optional dict of {result_key: [regex_patterns]} for
            keywords that need word-boundary matching (e.g., "men" vs "women").
    """
    for key, keywords in keyword_map.items():
        for kw in keywords:
            if kw in text:
                return key
        # Check boundary patterns if simple substring didn't match
        if boundary_patterns and key in boundary_patterns:
            for pattern in boundary_patterns[key]:
                if re.search(pattern, text):
                    return key
    return "unknown"


def _detect_bout_type(text: str) -> str:
    """Detect bout type (pool or DE) from text."""
    for kw in _BOUT_POOL_KEYWORDS:
        if kw in text:
            return "pool"
    for kw in _BOUT_DE_KEYWORDS:
        if kw in text:
            return "de"
    return "unknown"


def _infer_final_score(bout_type: str) -> Optional[int]:
    """Infer expected final score from bout type."""
    if bout_type == "pool":
        return 5
    elif bout_type == "de":
        return 15
    return None
