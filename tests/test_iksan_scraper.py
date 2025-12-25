"""
익산 국제대회 스크래퍼 및 데이터 통합 테스트
"""
import pytest
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
IKSAN_FILE = DATA_DIR / "iksan_international_2025.json"


class TestIksanDataIntegrity:
    """익산 대회 데이터 무결성 테스트"""

    @pytest.fixture
    def iksan_data(self):
        """익산 데이터 로드"""
        if not IKSAN_FILE.exists():
            pytest.skip("익산 데이터 파일이 없습니다")
        with open(IKSAN_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_data_structure(self, iksan_data):
        """기본 데이터 구조 확인"""
        assert "scraped_at" in iksan_data, "scraped_at 필드 없음"
        assert "competitions" in iksan_data, "competitions 필드 없음"
        assert len(iksan_data["competitions"]) == 2, "대회가 2개여야 함 (U17/U20, U13/U11/U9)"

    def test_u17_u20_competition(self, iksan_data):
        """U17/U20 대회 데이터 검증"""
        u17_u20 = None
        for comp in iksan_data["competitions"]:
            if comp.get("event_cd") == "COMPM00666":
                u17_u20 = comp
                break

        assert u17_u20 is not None, "U17/U20 대회 데이터 없음"
        assert len(u17_u20.get("events", [])) == 12, "U17/U20 종목은 12개여야 함"
        assert len(u17_u20.get("results", [])) == 12, "U17/U20 결과는 12개여야 함"

    def test_u13_competition(self, iksan_data):
        """U13/U11/U9 대회 데이터 검증"""
        u13 = None
        for comp in iksan_data["competitions"]:
            if comp.get("event_cd") == "COMPM00673":
                u13 = comp
                break

        assert u13 is not None, "U13/U11/U9 대회 데이터 없음"
        assert len(u13.get("events", [])) == 18, "U13/U11/U9 종목은 18개여야 함"
        assert len(u13.get("results", [])) == 18, "U13/U11/U9 결과는 18개여야 함"

    def test_pool_rounds_data(self, iksan_data):
        """Pool 라운드 데이터 검증"""
        for comp in iksan_data["competitions"]:
            for result in comp.get("results", []):
                pool_rounds = result.get("pool_rounds", [])
                event_name = result.get("event_name", "unknown")

                # Pool 라운드가 있는 경우 구조 검증
                if pool_rounds:
                    for pool in pool_rounds:
                        assert "pool_number" in pool, f"{event_name}: pool_number 없음"
                        assert "results" in pool, f"{event_name}: results 없음"

                        # Pool 결과 검증
                        for player in pool.get("results", []):
                            assert "name" in player, f"{event_name}: 선수 이름 없음"
                            assert "team" in player, f"{event_name}: 선수 소속 없음"

    def test_de_bracket_data(self, iksan_data):
        """DE 대진표 데이터 검증"""
        u17_u20 = iksan_data["competitions"][0]

        for result in u17_u20.get("results", []):
            de_bracket = result.get("de_bracket", {})
            de_matches = result.get("de_matches", [])
            event_name = result.get("event_name", "unknown")

            # U17/U20는 완료된 대회이므로 DE 데이터가 있어야 함
            if result.get("status") == "complete":
                assert de_bracket, f"{event_name}: DE 대진표 없음"
                assert de_matches, f"{event_name}: DE 경기 결과 없음"

                # DE 구조 검증
                if isinstance(de_bracket, dict):
                    assert "seeding" in de_bracket or "match_results" in de_bracket, \
                        f"{event_name}: DE 구조 불완전"

    def test_final_rankings_data(self, iksan_data):
        """최종 순위 데이터 검증"""
        u17_u20 = iksan_data["competitions"][0]

        for result in u17_u20.get("results", []):
            final_rankings = result.get("final_rankings", [])
            event_name = result.get("event_name", "unknown")

            # 완료된 경기는 최종 순위가 있어야 함
            if result.get("status") == "complete":
                assert len(final_rankings) > 0, f"{event_name}: 최종 순위 없음"

                # 순위 데이터 검증
                for rank in final_rankings:
                    assert "rank" in rank or "position" in rank, f"{event_name}: 순위 정보 없음"
                    assert "name" in rank, f"{event_name}: 선수 이름 없음"

    def test_pool_total_ranking(self, iksan_data):
        """Pool 최종 랭킹 데이터 검증"""
        for comp in iksan_data["competitions"]:
            for result in comp.get("results", []):
                pool_total = result.get("pool_total_ranking", [])
                event_name = result.get("event_name", "unknown")
                status = result.get("status", "unknown")

                # Pool이 있으면 총 랭킹도 있어야 함 (no_results 제외)
                if result.get("pool_rounds") and status != "no_results":
                    assert len(pool_total) > 0, f"{event_name}: Pool 최종 랭킹 없음"


class TestIksanDataQuality:
    """익산 대회 데이터 품질 테스트"""

    @pytest.fixture
    def iksan_data(self):
        if not IKSAN_FILE.exists():
            pytest.skip("익산 데이터 파일이 없습니다")
        with open(IKSAN_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_no_empty_names(self, iksan_data):
        """빈 이름이 없어야 함"""
        for comp in iksan_data["competitions"]:
            for result in comp.get("results", []):
                for pool in result.get("pool_rounds", []):
                    for player in pool.get("results", []):
                        name = player.get("name", "")
                        assert name.strip(), f"빈 선수 이름 발견: {result.get('event_name')}"

    def test_valid_scores(self, iksan_data):
        """점수가 유효해야 함"""
        u17_u20 = iksan_data["competitions"][0]

        for result in u17_u20.get("results", []):
            for match in result.get("de_matches", []):
                score = match.get("score", {})
                if score:
                    winner = score.get("winner_score", 0)
                    loser = score.get("loser_score", 0)
                    assert winner >= loser, f"승자 점수가 패자보다 낮음: {match}"
                    assert winner <= 15, f"점수가 15점을 초과: {winner}"

    def test_event_age_category(self, iksan_data):
        """종목별 나이 카테고리 일관성"""
        valid_ages = {"U9", "U11", "U13", "U17", "U20"}

        for comp in iksan_data["competitions"]:
            for event in comp.get("events", []):
                age = event.get("age_category")
                assert age in valid_ages, f"잘못된 나이 카테고리: {age}"

    def test_weapon_types(self, iksan_data):
        """무기 종류 일관성"""
        valid_weapons = {"플뢰레", "에페", "사브르"}

        for comp in iksan_data["competitions"]:
            for event in comp.get("events", []):
                weapon = event.get("weapon")
                assert weapon in valid_weapons, f"잘못된 무기 종류: {weapon}"


class TestIksanStatistics:
    """익산 대회 통계 검증"""

    @pytest.fixture
    def iksan_data(self):
        if not IKSAN_FILE.exists():
            pytest.skip("익산 데이터 파일이 없습니다")
        with open(IKSAN_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    def test_u17_u20_statistics(self, iksan_data):
        """U17/U20 대회 통계"""
        u17_u20 = iksan_data["competitions"][0]

        total_pool_rounds = sum(
            len(r.get("pool_rounds", []))
            for r in u17_u20.get("results", [])
        )
        total_de_matches = sum(
            len(r.get("de_matches", []))
            for r in u17_u20.get("results", [])
        )
        total_finals = sum(
            len(r.get("final_rankings", []))
            for r in u17_u20.get("results", [])
        )

        print(f"\n=== U17/U20 통계 ===")
        print(f"총 Pool 라운드: {total_pool_rounds}")
        print(f"총 DE 경기: {total_de_matches}")
        print(f"총 최종 순위: {total_finals}")

        assert total_pool_rounds > 100, "Pool 라운드가 너무 적음"
        assert total_de_matches > 200, "DE 경기가 너무 적음"
        assert total_finals > 300, "최종 순위 인원이 너무 적음"

    def test_u13_statistics(self, iksan_data):
        """U13/U11/U9 대회 통계"""
        u13 = iksan_data["competitions"][1]

        total_pool_rounds = sum(
            len(r.get("pool_rounds", []))
            for r in u13.get("results", [])
        )
        completed_events = sum(
            1 for r in u13.get("results", [])
            if r.get("status") in ["complete", "pool_complete"]
        )

        print(f"\n=== U13/U11/U9 통계 ===")
        print(f"총 Pool 라운드: {total_pool_rounds}")
        print(f"완료된 종목: {completed_events}/18")

        assert total_pool_rounds > 80, "Pool 라운드가 너무 적음"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
