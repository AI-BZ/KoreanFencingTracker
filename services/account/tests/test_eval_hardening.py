"""
EVAL 보안 하드닝 테스트 (항목 5·6)

- 항목 5: 공개 선수검색 응답 최소화(정밀 생년 제거 → 구간화, 미성년 이름 부분마스킹)
- 항목 6: claim 점수 기반 자동승인 비활성화(만점 조합이어도 pending)
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.account.app.auth.router import (
    _birth_decade,
    _is_minor_player,
    _mask_name_partial,
    _sanitize_public_player_results,
)
from services.account.app.config import get_account_settings
from services.account.app.verification import claims as claims_mod


# =============================================
# 항목 5 — 응답 최소화 / 마스킹 (순수 함수)
# =============================================

class TestMaskNamePartial:
    def test_three_char_name(self):
        assert _mask_name_partial("홍길동") == "홍*동"

    def test_two_char_name(self):
        assert _mask_name_partial("홍길") == "홍*"

    def test_four_char_name(self):
        assert _mask_name_partial("김하늘새") == "김**새"

    def test_single_char_unchanged(self):
        assert _mask_name_partial("홍") == "홍"

    def test_empty(self):
        assert _mask_name_partial("") == ""


class TestBirthDecade:
    def test_2011(self):
        assert _birth_decade(2011) == "2010년대"

    def test_2005(self):
        assert _birth_decade(2005) == "2000년대"

    def test_string_year(self):
        assert _birth_decade("2011") == "2010년대"

    def test_none(self):
        assert _birth_decade(None) is None

    def test_invalid(self):
        assert _birth_decade("abc") is None

    def test_out_of_range(self):
        assert _birth_decade(1800) is None


class TestIsMinorPlayer:
    def test_middle_league_is_minor(self):
        assert _is_minor_player(["middle"], 2011) is True

    def test_elementary_league_is_minor(self):
        assert _is_minor_player(["elementary"], None) is True

    def test_high_league_is_adult(self):
        assert _is_minor_player(["high"], 2007) is False

    def test_senior_league_is_adult(self):
        assert _is_minor_player(["middle", "senior"], None) is False

    def test_no_league_young_birth_year_is_minor(self):
        # 리그 정보 없음 → 출생연도 fallback(만 19세 미만)
        assert _is_minor_player([], 2015) is True

    def test_no_league_old_birth_year_is_adult(self):
        assert _is_minor_player([], 1990) is False

    def test_no_signal_defaults_adult(self):
        assert _is_minor_player([], None) is False


class TestSanitizePublicPlayerResults:
    def test_strips_precise_birth_year(self):
        raw = [{"id": 1, "player_name": "이성인", "team_name": "서울클럽",
                "birth_year": 1990, "weapons": ["foil"], "leagues": ["senior"]}]
        out = _sanitize_public_player_results(raw)
        assert "birth_year" not in out[0]
        assert out[0]["birth_decade"] == "1990년대"

    def test_adult_name_kept(self):
        raw = [{"id": 1, "player_name": "이성인", "team_name": "T",
                "birth_year": 1990, "weapons": [], "leagues": ["senior"]}]
        out = _sanitize_public_player_results(raw)
        assert out[0]["player_name"] == "이성인"
        assert out[0]["is_minor"] is False

    def test_minor_name_masked(self):
        raw = [{"id": 2, "player_name": "홍길동", "team_name": "T",
                "birth_year": 2012, "weapons": ["epee"], "leagues": ["middle"]}]
        out = _sanitize_public_player_results(raw)
        assert out[0]["player_name"] == "홍*동"
        assert out[0]["is_minor"] is True
        assert "birth_year" not in out[0]

    def test_preserves_identifying_fields(self):
        raw = [{"id": 3, "player_name": "박선수", "team_name": "부산클럽",
                "birth_year": 2000, "weapons": ["sabre"], "leagues": ["university"]}]
        out = _sanitize_public_player_results(raw)
        item = out[0]
        assert item["id"] == 3
        assert item["team_name"] == "부산클럽"
        assert item["weapons"] == ["sabre"]
        assert item["leagues"] == ["university"]


# =============================================
# 항목 6 — 자동승인 비활성화
# =============================================

class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, fake, table):
        self._fake = fake
        self._table = table
        self._op = "select"
        self._row = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, row):
        self._op = "insert"
        self._row = row
        return self

    def update(self, row):
        self._op = "update"
        self._row = row
        return self

    def eq(self, *a, **k):
        return self

    def ilike(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def single(self):
        return self

    def execute(self):
        self._fake.calls.append((self._table, self._op, self._row))
        return _FakeResult(self._fake.results.get((self._table, self._op), []))


class _FakeSupabase:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def table(self, name):
        return _FakeQuery(self, name)


# 만점 매칭 재료: 이름 exact(0.35) + 생년(0.25) + 소속 exact(0.25) + 무기(0.05) = 0.90
_MEMBER = {"id": "m1", "full_name": "홍길동", "birth_date": "2005-03-15", "organization_id": 42}
_PLAYER = {"id": 7, "player_name": "홍길동", "birth_year": 2005,
           "team_name": "서울클럽", "weapon": "foil"}
_RESULTS = {
    ("player_claims", "select"): [],          # 기존 approved claim 없음
    ("players", "select"): _PLAYER,           # single()
    ("organizations", "select"): {"name": "서울클럽"},  # 소속 대조 (single)
    ("player_claims", "insert"): [{"id": "claim-1"}],
    ("members", "update"): [],
}


def _run_submit_player_claim(settings):
    """submit_player_claim을 격리된 mock 환경에서 실행하고 반환값을 돌려준다."""
    fake = _FakeSupabase(_RESULTS)
    req = MagicMock()
    claim = claims_mod.PlayerClaimRequest(player_id=7)

    notifier = MagicMock()
    notifier.notify_admin_new_request = AsyncMock(return_value=None)

    with patch.object(claims_mod, "get_current_member", AsyncMock(return_value=_MEMBER)), \
         patch.object(claims_mod, "get_supabase_client", return_value=fake), \
         patch.object(claims_mod, "get_account_settings", return_value=settings), \
         patch.object(claims_mod, "VerificationNotificationService", return_value=notifier):
        return asyncio.run(claims_mod.submit_player_claim(req, claim)), fake


class TestClaimAutoApproveDisabled:
    def test_confidence_reaches_auto_approve_threshold(self):
        # 만점 조합이 실제로 0.85 이상 도달함을 확인(과거라면 자동승인됐을 점수).
        with patch.object(claims_mod, "get_supabase_client",
                          return_value=_FakeSupabase(_RESULTS)):
            score = claims_mod.calculate_claim_confidence(_MEMBER, _PLAYER)
        assert score >= 0.85

    def test_default_flag_is_disabled(self):
        assert get_account_settings().CLAIM_AUTO_APPROVE_ENABLED is False

    def test_perfect_match_stays_pending_when_disabled(self):
        settings = SimpleNamespace(
            CLAIM_AUTO_APPROVE_ENABLED=False,
            CLAIM_AUTO_APPROVE_THRESHOLD=0.85,
            CLAIM_MANUAL_REVIEW_THRESHOLD=0.50,
        )
        result, fake = _run_submit_player_claim(settings)
        assert result["status"] == "pending"
        assert result["confidence"] >= 0.85
        # pending이므로 members.update(player_id 링크)가 호출되지 않아야 함
        assert all(not (t == "members" and o == "update") for t, o, _ in fake.calls)

    def test_perfect_match_approves_when_re_enabled(self):
        settings = SimpleNamespace(
            CLAIM_AUTO_APPROVE_ENABLED=True,
            CLAIM_AUTO_APPROVE_THRESHOLD=0.85,
            CLAIM_MANUAL_REVIEW_THRESHOLD=0.50,
        )
        result, fake = _run_submit_player_claim(settings)
        assert result["status"] == "approved"
        # approved 시에는 members.update로 player_id 링크가 실행되어야 함
        assert any(t == "members" and o == "update" for t, o, _ in fake.calls)
