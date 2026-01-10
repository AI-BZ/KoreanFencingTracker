"""
한국 펜싱 랭킹 시스템

FIE + USA Fencing 방식을 참고한 랭킹 계산 모듈
"""
from .calculator import (
    RankingCalculator,
    PlayerResult,
    PlayerRanking,
    calculate_points,
    classify_competition_tier,
    classify_category,
    extract_age_group,
    extract_weapon,
    extract_gender,
    AGE_GROUP_CODES,
    AGE_GROUP_WEIGHTS,
    TIER_BASE_POINTS,
    CATEGORY_CODES,
    CATEGORY_APPLICABLE_AGE_GROUPS,
)

__all__ = [
    "RankingCalculator",
    "PlayerResult",
    "PlayerRanking",
    "calculate_points",
    "classify_competition_tier",
    "classify_category",
    "extract_age_group",
    "extract_weapon",
    "extract_gender",
    "AGE_GROUP_CODES",
    "AGE_GROUP_WEIGHTS",
    "TIER_BASE_POINTS",
    "CATEGORY_CODES",
    "CATEGORY_APPLICABLE_AGE_GROUPS",
]
