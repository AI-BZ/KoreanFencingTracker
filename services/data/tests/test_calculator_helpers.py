"""ranking/calculator.py의 순수 함수 회귀 테스트.

랭킹 산정 로직(RankingCalculator 클래스 본체) 자체는 협회 규정 검증을 막 끝낸
코드라 건드리지 않는다 — 이 파일은 DB 없이 검증 가능한 헬퍼 함수(대회 레벨 분류,
무기/성별/연령 추출, 배점 테이블)에 대한 순수 단위 테스트만 추가해 향후 리팩토링·
정규식 수정 시 조용히 깨지는 것을 막는다. 모든 값은 CLAUDE.md의 실제 규정 서술
및 calculator.py 소스를 그대로 반영했다(추측 없음).
"""
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from ranking.calculator import (  # noqa: E402
    get_base_points_by_participants,
    get_competition_prestige,
    get_rank_ratio,
    get_participant_factor,
    classify_competition_tier,
    classify_category,
    classify_competition_level,
    extract_weapon,
    extract_gender,
)


# ---------------------------------------------------------------------------
# get_base_points_by_participants — 참가자 수 구간 경계값
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("count,expected", [
    (127, 1000), (128, 1200), (200, 1200),
    (63, 800), (64, 1000),
    (31, 500), (32, 800),
    (15, 300), (16, 500),
    (7, 150), (8, 300),
    (0, 150), (1, 150),
])
def test_get_base_points_by_participants_boundaries(count, expected):
    assert get_base_points_by_participants(count) == expected


# ---------------------------------------------------------------------------
# get_competition_prestige — 동호인 키워드 vs 정식
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("제10회 클럽 대항전", 0.90),
    ("생활체육 동호인 대회", 0.90),
    ("Amateur Fencing Open", 0.90),
    ("제66회 대통령배 전국펜싱대회", 1.00),
    ("2026 종목별오픈", 1.00),
])
def test_get_competition_prestige(name, expected):
    assert get_competition_prestige(name) == expected


# ---------------------------------------------------------------------------
# get_rank_ratio — 표에 명시된 구간과 그 밖의 보간 구간
# ---------------------------------------------------------------------------

def test_get_rank_ratio_table_values():
    assert get_rank_ratio(1) == 1.00
    assert get_rank_ratio(2) == 0.65
    assert get_rank_ratio(3) == 0.50
    assert get_rank_ratio(8) == 0.24
    assert get_rank_ratio(32) == 0.025


def test_get_rank_ratio_is_monotonically_non_increasing_within_each_bracket():
    """각 구간(1-32, 33-64, 65-128) 내부에서는 순위가 나쁠수록 비율이 작거나 같다."""
    for lo, hi in [(1, 32), (33, 64), (65, 128)]:
        prev = get_rank_ratio(lo)
        for rank in range(lo + 1, hi + 1):
            current = get_rank_ratio(rank)
            assert current <= prev, f"rank {rank} ratio {current} > previous {prev}"
            prev = current


def test_get_rank_ratio_is_monotonic_across_bracket_boundaries():
    """구간 경계에서도 순위가 나빠지면 비율이 커지지 않는다 (2026-09-28 수정).

    예전엔 32위(0.025) → 33위(0.05) 로 뛰어올라 32강 탈락자보다 64강 탈락 상위
    시드가 포인트를 더 받았고, 128위(0.0074)보다 129위 이하 고정값(0.01)이 더 컸다.
    """
    for rank in range(1, 200):
        assert get_rank_ratio(rank) <= get_rank_ratio(rank - 1) if rank > 1 else True

    assert get_rank_ratio(33) < get_rank_ratio(32)
    assert get_rank_ratio(65) < get_rank_ratio(64)
    assert get_rank_ratio(129) < get_rank_ratio(128)

def test_get_rank_ratio_beyond_128_is_floor_value():
    # 2026-09-28: 128위(0.0082)보다 낮게 내려 단조성을 맞췄다 (이전 0.01 은 역전이었다).
    assert get_rank_ratio(129) == 0.008
    assert get_rank_ratio(1000) == 0.008


# ---------------------------------------------------------------------------
# get_participant_factor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("count,expected", [
    (63, 0.9), (64, 1.0), (100, 1.0),
    (31, 0.8), (32, 0.9),
    (15, 0.6), (16, 0.8),
    (7, 0.4), (8, 0.6),
    (0, 0.4),
])
def test_get_participant_factor_boundaries(count, expected):
    assert get_participant_factor(count) == expected


# ---------------------------------------------------------------------------
# classify_competition_tier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("제66회 대통령배 전국펜싱대회", "S"),
    ("전국체전 펜싱경기", "S"),
    ("제10회 회장배 전국대회", "S"),
    ("전국선수권대회", "A"),
    ("2026 Fencing Championship", "A"),
    ("국제 인터내셔널 오픈", "D"),
    ("서울시도대항전", "B"),
    ("제5회 클럽오픈대회", "C"),
])
def test_classify_competition_tier(name, expected):
    assert classify_competition_tier(name) == expected


def test_classify_competition_tier_substring_collision_between_association_and_president_cup():
    """⚠️ 발견된 이상 동작(수정하지 않고 회귀 검증만 고정): S등급 키워드 '회장배'가
    '협회장배'(B등급)의 부분 문자열이라 예전엔 S등급으로 잡혔다. 2026-09-28에
    B등급 키워드를 먼저 판정하도록 고쳤다. 실제 영향 범위는 표시·집계뿐이다 —
    `calculate_points()` 는 tier 를 쓰지 않는다(legacy 인자, `TIER_BASE_POINTS` 는
    `calculate_points_legacy` 전용). 오분류 대상이었던 대회: '대한펜싱협회장배
    전국 클럽·동호인 …' 7개(2019~2025)."""
    assert classify_competition_tier("협회장배 신인전") == "B"
    assert classify_competition_tier("2025 제13회 대한펜싱협회장배 전국클럽·동호인펜싱선수권대회") == "B"
    assert classify_competition_tier("제55회 회장배전국남녀종별펜싱선수권대회") == "S"


# ---------------------------------------------------------------------------
# classify_category — 동호인 vs 전문
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("최병철펜싱클럽 초청대회", "CLUB"),
    ("생활체육 동호인전", "CLUB"),
    ("Amateur Cup", "CLUB"),
    ("제66회 대통령배 전국펜싱대회", "PRO"),
    ("국가대표선수 선발대회", "PRO"),
])
def test_classify_category(name, expected):
    assert classify_category(name) == expected


# ---------------------------------------------------------------------------
# classify_competition_level — NT/유소년-청소년 제외/겸 국대선발 분류
# CLAUDE.md의 실제 명세를 그대로 반영: '겸'+'국가대표' → ELITE,
# '유소년'/'청소년'+'국가대표' → YOUTH_NATIONAL(랭킹 완전 제외),
# 순수 '국가대표' → NATIONAL.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("2026 펜싱 국가대표선수 선발대회", "NATIONAL"),
    ("제55회 회장기 겸 2026 펜싱 국가대표 2차선발대회", "ELITE"),
    ("유소년 국가대표선수 선발전", "YOUTH_NATIONAL"),
    ("청소년 국가대표선수 선발전", "YOUTH_NATIONAL"),
    ("제10회 클럽오픈대회", "AMATEUR"),
    ("생활체육 동호인전", "AMATEUR"),
    ("제66회 대통령배 전국펜싱대회", "ELITE"),
    ("2026 종목별오픈", "ELITE"),
])
def test_classify_competition_level(name, expected):
    assert classify_competition_level(name) == expected


def test_classify_competition_level_youth_national_checked_before_plain_national():
    """'유소년...국가대표'가 실수로 NATIONAL(랭킹 포함 대상)로 잘못 분류되면
    유소년/청소년 완전 제외 규칙(CLAUDE.md)이 깨진다 — 순서 의존성을 명시적으로 고정."""
    assert classify_competition_level("유소년 국가대표 선발전") == "YOUTH_NATIONAL"
    assert classify_competition_level("유소년 국가대표 선발전") != "NATIONAL"


# ---------------------------------------------------------------------------
# extract_weapon / extract_gender
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("여자 플뢰레 개인전", "foil"),
    ("남자 플러레 단체전", "foil"),
    ("Men's Foil", "foil"),
    ("여자 에페 개인전", "epee"),
    ("에뻬 단체전", "epee"),
    ("Women's Epee", "epee"),
    ("남자 사브르 개인전", "sabre"),
    ("Sabre Team", "sabre"),
    ("종목명 없음", ""),
])
def test_extract_weapon(name, expected):
    assert extract_weapon(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("여자 에페 개인전", "여"),
    ("남자 플뢰레 단체전", "남"),
    ("무성별 종목", ""),
])
def test_extract_gender(name, expected):
    assert extract_gender(name) == expected
