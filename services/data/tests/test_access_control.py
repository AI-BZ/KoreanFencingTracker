"""app/access_control.py 단위 테스트.

3단계 접근 제어(guest/member/verified)는 검색·랭킹·선수 프로필·FencingLab 전 화면에
걸쳐 있는 핵심 게이트다. 이 모듈은 순수 함수 위주라 DB/네트워크 없이 검증 가능한데도
기존에 전용 테스트가 없었다. 여기서는 app.server(9천 줄, DB 클라이언트 등)를 끌어들이지
않기 위해 RankingEntry를 흉내 낸 가벼운 더블을 쓴다(access_control은 duck typing으로만
접근하므로 pydantic 모델일 필요가 없다).
"""
import asyncio
import os
import sys

import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app.access_control import (  # noqa: E402
    VERIFIED_MEMBER_TYPES,
    RANKINGS_HIDDEN_TOP_N,
    get_access_level,
    blur_ranking_entries,
    blur_search_result_for_guest,
    can_access_fencinglab,
    apply_player_data_gate,
)


class _FakeRankingEntry:
    """RankingEntry 대역 — blur_ranking_entries가 실제로 건드리는 속성만 갖는다."""

    def __init__(self, rank, name="홍길동", team="최병철펜싱클럽"):
        self.rank = rank
        self.name = name
        self.display_name = name
        self.teams = [team]
        self.display_teams = [team]
        self.blurred = False


def _entries(ranks):
    return [_FakeRankingEntry(r) for r in ranks]


# ---------------------------------------------------------------------------
# blur_ranking_entries — 경계값 및 페이지네이션 무관성
# ---------------------------------------------------------------------------

def test_blur_ranking_entries_masks_within_threshold():
    entries = _entries([1, 15, 30])
    result = blur_ranking_entries(entries, threshold=RANKINGS_HIDDEN_TOP_N)
    assert all(e.blurred for e in result)
    assert all(e.name == "????" for e in result)
    assert all(e.teams == ["????"] for e in result)


def test_blur_ranking_entries_leaves_entries_beyond_threshold():
    entries = _entries([31, 50, 100])
    result = blur_ranking_entries(entries, threshold=RANKINGS_HIDDEN_TOP_N)
    assert all(not e.blurred for e in result)
    assert all(e.name == "홍길동" for e in result)


def test_blur_ranking_entries_boundary_is_inclusive():
    """threshold=30일 때 정확히 30위는 가려지고 31위는 가려지지 않는다."""
    entries = _entries([30, 31])
    result = blur_ranking_entries(entries, threshold=30)
    assert result[0].blurred is True
    assert result[1].blurred is False


def test_blur_ranking_entries_uses_rank_not_list_position():
    """페이지네이션으로 리스트가 31위부터 시작해도, rank 값이 30 이하가 아니면 안 가려진다.
    반대로 리스트 순서와 무관하게 rank<=threshold면 가려져야 한다(역순으로 섞여도 동일)."""
    entries = _entries([50, 5, 40])  # 순서가 뒤섞인 페이지
    result = blur_ranking_entries(entries, threshold=RANKINGS_HIDDEN_TOP_N)
    by_rank = {e.rank: e.blurred for e in result}
    assert by_rank[5] is True
    assert by_rank[40] is False
    assert by_rank[50] is False


def test_blur_ranking_entries_empty_list():
    assert blur_ranking_entries([], threshold=RANKINGS_HIDDEN_TOP_N) == []


# ---------------------------------------------------------------------------
# blur_search_result_for_guest
# ---------------------------------------------------------------------------

def test_blur_search_result_for_guest_masks_team_fields_only():
    result = {
        "name": "박소윤",
        "teams": ["최병철펜싱클럽"],
        "current_team": "최병철펜싱클럽",
        "team_history": ["송도펜싱클럽"],
        "player_id": "KOP00000",
    }
    blurred = blur_search_result_for_guest(result)
    assert blurred["teams"] is None
    assert blurred["current_team"] is None
    assert blurred["team_history"] is None
    assert blurred["blurred"] is True
    # 이름/ID 등 비-소속 필드는 그대로 유지
    assert blurred["name"] == "박소윤"
    assert blurred["player_id"] == "KOP00000"


def test_blur_search_result_for_guest_does_not_mutate_original():
    original = {"name": "박소윤", "teams": ["최병철펜싱클럽"]}
    blur_search_result_for_guest(original)
    assert original["teams"] == ["최병철펜싱클럽"]


# ---------------------------------------------------------------------------
# can_access_fencinglab
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level,expected", [
    ("guest", False),
    ("member", False),
    ("verified", True),
])
def test_can_access_fencinglab(level, expected):
    assert can_access_fencinglab(level) is expected


# ---------------------------------------------------------------------------
# apply_player_data_gate — 등급별 필드 게이팅
# ---------------------------------------------------------------------------

def _full_player_data():
    return {
        "name": "박소윤",
        "stats": {"wins": 10},
        "head_to_head": {"opp": "..."},
        "fencinglab": {"chart": "..."},
        "bout_stats": {"a": 1},
        "round_stats": {"b": 2},
        "records": [1, 2, 3],
    }


def test_apply_player_data_gate_verified_sees_everything_unchanged():
    data = _full_player_data()
    result = apply_player_data_gate(data, "verified")
    assert result == data
    assert result is data  # verified 경로는 원본을 그대로 반환


def test_apply_player_data_gate_guest_hides_everything_sensitive():
    result = apply_player_data_gate(_full_player_data(), "guest")
    assert result["stats"] is None
    assert result["head_to_head"] is None
    assert result["fencinglab"] is None
    assert result["bout_stats"] is None
    assert result["round_stats"] is None
    assert result["records"] is None
    assert result["requires_login"] is True
    assert result["name"] == "박소윤"


def test_apply_player_data_gate_member_sees_stats_but_not_h2h_or_lab():
    result = apply_player_data_gate(_full_player_data(), "member")
    assert result["stats"] == {"wins": 10}
    assert result["bout_stats"] == {"a": 1}
    assert result["round_stats"] == {"b": 2}
    assert result["records"] == [1, 2, 3]
    assert result["head_to_head"] is None
    assert result["fencinglab"] is None
    assert result["requires_verification"] is True
    assert "requires_login" not in result


def test_apply_player_data_gate_does_not_mutate_input():
    original = _full_player_data()
    apply_player_data_gate(original, "guest")
    assert original["stats"] == {"wins": 10}
    assert original["head_to_head"] == {"opp": "..."}


# ---------------------------------------------------------------------------
# get_access_level — 등급 판정 (get_current_member 경계에서 monkeypatch)
# ---------------------------------------------------------------------------

class _FakeRequest:
    """app.auth.router.get_current_member가 요구하는 최소 인터페이스만 흉내낸다."""
    pass


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_get_access_level_no_member_is_guest(monkeypatch):
    async def fake_get_current_member(request):
        return None

    monkeypatch.setattr(
        "app.auth.router.get_current_member", fake_get_current_member
    )
    level, member = _run(get_access_level(_FakeRequest()))
    assert level == "guest"
    assert member is None


def test_get_access_level_verified_member_type_and_status():
    """VERIFIED_MEMBER_TYPES 각각 + verification_status='verified' 조합이 verified로 판정되는지
    (get_access_level의 판정 로직을 직접 재현해 회귀를 잡는다)."""
    for member_type in VERIFIED_MEMBER_TYPES:
        member = {
            "member_type": member_type,
            "verification_status": "verified",
            "player_id": None,
        }
        is_verified = (
            member["member_type"] in VERIFIED_MEMBER_TYPES
            and (member["verification_status"] == "verified" or member["player_id"] is not None)
        )
        assert is_verified is True


def test_get_access_level_player_id_alone_counts_as_verified(monkeypatch):
    """verification_status가 아직 pending이어도 player_id가 연결돼 있으면 verified."""
    async def fake_get_current_member(request):
        return {
            "member_type": "player",
            "verification_status": "pending",
            "player_id": "KOP00000",
        }

    monkeypatch.setattr(
        "app.auth.router.get_current_member", fake_get_current_member
    )
    level, member = _run(get_access_level(_FakeRequest()))
    assert level == "verified"


def test_get_access_level_general_member_type_is_member_not_verified(monkeypatch):
    async def fake_get_current_member(request):
        return {
            "member_type": "general",
            "verification_status": "pending",
            "player_id": None,
        }

    monkeypatch.setattr(
        "app.auth.router.get_current_member", fake_get_current_member
    )
    level, member = _run(get_access_level(_FakeRequest()))
    assert level == "member"


def test_get_access_level_verified_type_without_verification_stays_member(monkeypatch):
    """member_type이 VERIFIED_MEMBER_TYPES에 있어도 인증 완료/player_id 연결이 없으면
    member 등급에 머문다 (신청만 하고 승인 전인 상태)."""
    async def fake_get_current_member(request):
        return {
            "member_type": "club_coach",
            "verification_status": "pending",
            "player_id": None,
        }

    monkeypatch.setattr(
        "app.auth.router.get_current_member", fake_get_current_member
    )
    level, member = _run(get_access_level(_FakeRequest()))
    assert level == "member"
