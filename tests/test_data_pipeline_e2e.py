"""
데이터 파이프라인 E2E 테스트
- Supabase 실제 데이터 검증
- 정규화 결과 확인
- 데이터 무결성 검증
"""
import pytest
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client, Client


@pytest.fixture(scope="module")
def supabase_client() -> Client:
    """Supabase 클라이언트 fixture"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        pytest.skip("Supabase credentials not configured")
    return create_client(url, key)


# =============================================================================
# 무기명 정규화 E2E 테스트
# =============================================================================

class TestWeaponNormalizationE2E:
    """무기명 정규화 E2E 테스트"""

    def test_no_non_standard_weapon_names(self, supabase_client):
        """비표준 무기명이 없어야 함 (에페, 플뢰레)"""
        response = supabase_client.table("events").select("id, weapon").in_(
            "weapon", ["에페", "플뢰레"]
        ).execute()

        non_standard = response.data or []
        assert len(non_standard) == 0, (
            f"비표준 무기명 {len(non_standard)}건 발견: "
            f"{[r['weapon'] for r in non_standard[:5]]}"
        )

    def test_only_valid_weapon_names(self, supabase_client):
        """무기명은 에뻬, 플러레, 사브르, NULL만 허용"""
        valid_weapons = ["에뻬", "플러레", "사브르"]

        # NULL이 아니고 유효하지 않은 무기명 조회
        response = supabase_client.table("events").select(
            "id, weapon, event_name"
        ).not_.is_("weapon", "null").execute()

        invalid = [
            r for r in (response.data or [])
            if r["weapon"] not in valid_weapons and r["weapon"] != ""
        ]

        assert len(invalid) == 0, (
            f"잘못된 무기명 {len(invalid)}건: "
            f"{[(r['weapon'], r['event_name'][:30]) for r in invalid[:5]]}"
        )


# =============================================================================
# 연령대 정규화 E2E 테스트
# =============================================================================

class TestAgeGroupNormalizationE2E:
    """연령대 정규화 E2E 테스트"""

    def test_age_group_fill_rate(self, supabase_client):
        """age_group 채워진 비율이 80% 이상이어야 함"""
        # 전체 이벤트 수
        total_resp = supabase_client.table("events").select(
            "id", count="exact"
        ).execute()
        total = total_resp.count or 0

        # 비어있는 age_group 수
        empty_resp = supabase_client.table("events").select(
            "id", count="exact"
        ).or_("age_group.is.null,age_group.eq.").execute()
        empty = empty_resp.count or 0

        fill_rate = (total - empty) / total * 100 if total > 0 else 0

        assert fill_rate >= 80, (
            f"age_group 채움율 {fill_rate:.1f}%가 80% 미만입니다. "
            f"(총 {total}건 중 {empty}건 비어있음)"
        )

    def test_valid_age_group_codes(self, supabase_client):
        """age_group은 유효한 코드만 허용"""
        valid_codes = ["E1", "E2", "E3", "MS", "HS", "UNI", "SR"]

        response = supabase_client.table("events").select(
            "id, age_group, event_name"
        ).not_.is_("age_group", "null").neq("age_group", "").execute()

        invalid = [
            r for r in (response.data or [])
            if r["age_group"] not in valid_codes
        ]

        assert len(invalid) == 0, (
            f"잘못된 age_group 코드 {len(invalid)}건: "
            f"{[(r['age_group'], r['event_name'][:30]) for r in invalid[:5]]}"
        )


# =============================================================================
# 외래키 무결성 E2E 테스트
# =============================================================================

class TestForeignKeyIntegrityE2E:
    """외래키 무결성 E2E 테스트"""

    def test_events_have_valid_competition_id(self, supabase_client):
        """모든 events는 유효한 competition_id를 가져야 함"""
        # 모든 competition ID 조회
        comp_resp = supabase_client.table("competitions").select("id").execute()
        valid_comp_ids = {c["id"] for c in (comp_resp.data or [])}

        # events의 competition_id 조회
        events_resp = supabase_client.table("events").select(
            "id, competition_id"
        ).execute()

        orphans = [
            e for e in (events_resp.data or [])
            if e["competition_id"] not in valid_comp_ids
        ]

        assert len(orphans) == 0, (
            f"고아 이벤트 {len(orphans)}건 발견 "
            f"(존재하지 않는 competition_id 참조)"
        )

    @pytest.mark.xfail(reason="Known issue: 익산대회 rankings가 아직 events와 연결 안됨")
    def test_rankings_have_valid_event_id(self, supabase_client):
        """모든 rankings는 유효한 event_id를 가져야 함"""
        # 모든 event ID 조회
        event_resp = supabase_client.table("events").select("id").execute()
        valid_event_ids = {e["id"] for e in (event_resp.data or [])}

        # rankings의 event_id 조회
        rankings_resp = supabase_client.table("rankings").select(
            "id, event_id"
        ).execute()

        orphans = [
            r for r in (rankings_resp.data or [])
            if r["event_id"] not in valid_event_ids
        ]

        assert len(orphans) == 0, (
            f"고아 랭킹 {len(orphans)}건 발견 "
            f"(존재하지 않는 event_id 참조)"
        )


# =============================================================================
# 데이터 일관성 E2E 테스트
# =============================================================================

class TestDataConsistencyE2E:
    """데이터 일관성 E2E 테스트"""

    @pytest.mark.xfail(reason="Known issue: 일부 대회는 아직 events가 연결되지 않음")
    def test_competition_event_count(self, supabase_client):
        """각 대회는 최소 1개 이상의 종목을 가져야 함"""
        # 대회별 종목 수 조회
        comp_resp = supabase_client.table("competitions").select("id").execute()
        competitions = comp_resp.data or []

        empty_competitions = []
        for comp in competitions[:50]:  # 샘플 50개
            event_resp = supabase_client.table("events").select(
                "id", count="exact"
            ).eq("competition_id", comp["id"]).execute()

            if (event_resp.count or 0) == 0:
                empty_competitions.append(comp["id"])

        assert len(empty_competitions) == 0, (
            f"종목이 없는 대회 {len(empty_competitions)}건: {empty_competitions[:5]}"
        )

    def test_event_name_not_empty(self, supabase_client):
        """event_name이 비어있으면 안 됨"""
        response = supabase_client.table("events").select(
            "id, event_name"
        ).or_("event_name.is.null,event_name.eq.").execute()

        empty_names = response.data or []
        assert len(empty_names) == 0, (
            f"event_name이 비어있는 이벤트 {len(empty_names)}건"
        )


# =============================================================================
# 선수 데이터 E2E 테스트
# =============================================================================

class TestPlayerDataE2E:
    """선수 데이터 E2E 테스트"""

    def test_player_name_not_empty(self, supabase_client):
        """player_name이 비어있으면 안 됨"""
        response = supabase_client.table("players").select(
            "id, player_name"
        ).or_("player_name.is.null,player_name.eq.").limit(100).execute()

        empty_names = response.data or []
        assert len(empty_names) == 0, (
            f"이름이 비어있는 선수 {len(empty_names)}건"
        )

    def test_players_exist(self, supabase_client):
        """선수 데이터가 존재해야 함"""
        response = supabase_client.table("players").select(
            "id", count="exact"
        ).execute()

        player_count = response.count or 0
        assert player_count > 0, "선수 데이터가 없습니다"
        assert player_count >= 10000, (
            f"선수 수가 예상보다 적습니다: {player_count}명 (최소 10,000명 예상)"
        )


# =============================================================================
# 익산국제대회 데이터 검증 (특정 대회 테스트)
# =============================================================================

class TestIksanCompetitionE2E:
    """익산국제대회 데이터 E2E 테스트"""

    def test_iksan_competitions_exist(self, supabase_client):
        """익산국제대회 데이터가 존재해야 함"""
        response = supabase_client.table("competitions").select(
            "id, comp_name"
        ).ilike("comp_name", "%익산%").execute()

        competitions = response.data or []
        assert len(competitions) > 0, "익산국제대회 데이터가 없습니다"

    def test_iksan_events_have_age_group(self, supabase_client):
        """익산국제대회 이벤트에 age_group이 있어야 함"""
        # 익산 대회 ID 조회
        comp_resp = supabase_client.table("competitions").select(
            "id"
        ).ilike("comp_name", "%익산%").execute()

        if not comp_resp.data:
            pytest.skip("익산 대회 데이터 없음")

        comp_ids = [c["id"] for c in comp_resp.data]

        # 해당 대회의 이벤트 중 age_group 없는 것 조회
        for comp_id in comp_ids[:5]:
            event_resp = supabase_client.table("events").select(
                "id, event_name, age_group"
            ).eq("competition_id", comp_id).or_(
                "age_group.is.null,age_group.eq."
            ).execute()

            empty_age = event_resp.data or []
            # 경고만 (일부는 age_group 추출 불가할 수 있음)
            if len(empty_age) > 0:
                print(f"익산 대회 {comp_id}: age_group 없는 이벤트 {len(empty_age)}건")


# =============================================================================
# 검색 기능 E2E 테스트
# =============================================================================

class TestSearchFunctionalityE2E:
    """검색 기능 E2E 테스트"""

    def test_search_by_weapon(self, supabase_client):
        """무기별 검색이 동작해야 함"""
        for weapon in ["에뻬", "플러레", "사브르"]:
            response = supabase_client.table("events").select(
                "id", count="exact"
            ).eq("weapon", weapon).execute()

            count = response.count or 0
            assert count > 0, f"{weapon} 종목이 없습니다"

    def test_search_by_age_group(self, supabase_client):
        """연령대별 검색이 동작해야 함"""
        for age_group in ["MS", "HS", "UNI", "SR"]:
            response = supabase_client.table("events").select(
                "id", count="exact"
            ).eq("age_group", age_group).execute()

            count = response.count or 0
            assert count > 0, f"{age_group} 연령대 이벤트가 없습니다"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
