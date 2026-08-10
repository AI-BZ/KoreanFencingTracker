"""
Tests for filming guide recommendations.
"""

import pytest


# ------------------------------------------------------------------
# Import tests
# ------------------------------------------------------------------

def test_import_filming_guide():
    from app.filming_guide import FilmingGuide, get_filming_guide
    assert FilmingGuide is not None
    assert get_filming_guide is not None


# ------------------------------------------------------------------
# FilmingGuide tests
# ------------------------------------------------------------------

def test_filming_guide_coach_ko():
    from app.filming_guide import get_filming_guide
    guide = get_filming_guide("coach", language="ko")
    assert guide.source_type == "coach"
    assert guide.language == "ko"
    assert "삼각대" in guide.camera_height
    assert len(guide.lighting_tips) > 0
    assert len(guide.common_mistakes) > 0


def test_filming_guide_coach_en():
    from app.filming_guide import get_filming_guide
    guide = get_filming_guide("coach", language="en")
    assert guide.language == "en"
    assert "Tripod" in guide.camera_height
    assert len(guide.lighting_tips) > 0


def test_filming_guide_parent():
    from app.filming_guide import get_filming_guide
    guide = get_filming_guide("parent", language="ko")
    assert guide.source_type == "parent"
    assert len(guide.common_mistakes) > 0


def test_filming_guide_player():
    from app.filming_guide import get_filming_guide
    guide = get_filming_guide("player", language="ko")
    assert guide.source_type == "player"


def test_filming_guide_with_weapon():
    from app.filming_guide import get_filming_guide
    guide = get_filming_guide("coach", weapon="foil", language="ko")
    assert guide.weapon == "foil"


def test_filming_guide_to_dict():
    from app.filming_guide import get_filming_guide
    guide = get_filming_guide("coach", language="ko")
    d = guide.to_dict()
    assert "source_type" in d
    assert "camera_position" in d
    assert "lighting_tips" in d
    assert "common_mistakes" in d
    assert isinstance(d["lighting_tips"], list)


def test_filming_guide_unknown_type_fallback():
    """Unknown source type should fall back to coach guide."""
    from app.filming_guide import get_filming_guide
    guide = get_filming_guide("unknown_type", language="ko")
    assert guide.source_type == "unknown_type"
    assert len(guide.camera_position) > 0  # Falls back to coach
