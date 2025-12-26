"""
데이터 파이프라인 단위 테스트
- normalizer.py 정규화 함수 테스트
- pipeline.py 이벤트/핸들러 테스트
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_pipeline.normalizer import (
    normalize_weapon,
    normalize_gender,
    normalize_age_group,
    normalize_category,
    extract_from_event_name,
    normalize_event_record,
    get_normalization_changes,
)
from data_pipeline.pipeline import DataPipeline
from data_pipeline.events import DataChangeEvent, EventType


# =============================================================================
# 무기명 정규화 테스트
# =============================================================================

class TestNormalizeWeapon:
    """무기명 정규화 테스트"""

    def test_normalize_epee_variants(self):
        """에페 변형 → 에뻬"""
        assert normalize_weapon("에페") == "에뻬"
        assert normalize_weapon("epee") == "에뻬"

    def test_normalize_foil_variants(self):
        """플뢰레 변형 → 플러레"""
        assert normalize_weapon("플뢰레") == "플러레"
        assert normalize_weapon("foil") == "플러레"

    def test_normalize_sabre_variants(self):
        """사브르 변형"""
        assert normalize_weapon("사브르") == "사브르"
        assert normalize_weapon("sabre") == "사브르"
        assert normalize_weapon("saber") == "사브르"

    def test_standard_weapons_unchanged(self):
        """이미 표준인 경우 유지"""
        assert normalize_weapon("에뻬") == "에뻬"
        assert normalize_weapon("플러레") == "플러레"
        assert normalize_weapon("사브르") == "사브르"

    def test_empty_weapon(self):
        """빈 값 처리"""
        assert normalize_weapon("") is None
        assert normalize_weapon(None) is None


# =============================================================================
# 성별 정규화 테스트
# =============================================================================

class TestNormalizeGender:
    """성별 정규화 테스트"""

    def test_normalize_male(self):
        """남자 변형 → 남"""
        assert normalize_gender("남") == "남"
        assert normalize_gender("남자") == "남"
        assert normalize_gender("m") == "남"
        assert normalize_gender("male") == "남"

    def test_normalize_female(self):
        """여자 변형 → 여"""
        assert normalize_gender("여") == "여"
        assert normalize_gender("여자") == "여"
        assert normalize_gender("f") == "여"
        assert normalize_gender("female") == "여"

    def test_empty_gender(self):
        """빈 값 처리"""
        assert normalize_gender("") is None
        assert normalize_gender(None) is None


# =============================================================================
# 연령대 정규화 테스트
# =============================================================================

class TestNormalizeAgeGroup:
    """연령대 정규화 테스트"""

    def test_elementary_age_groups(self):
        """초등부 코드"""
        assert normalize_age_group("E1") == "E1"
        assert normalize_age_group("E2") == "E2"
        assert normalize_age_group("E3") == "E3"

    def test_korean_age_groups(self):
        """한글 연령대 → 코드"""
        assert normalize_age_group("초등저") == "E1"
        assert normalize_age_group("중등부") == "MS"
        assert normalize_age_group("고등부") == "HS"
        assert normalize_age_group("대학부") == "UNI"
        assert normalize_age_group("일반부") == "SR"

    def test_empty_age_group(self):
        """빈 값 처리"""
        assert normalize_age_group("") is None
        assert normalize_age_group(None) is None


# =============================================================================
# 카테고리 정규화 테스트
# =============================================================================

class TestNormalizeCategory:
    """카테고리 정규화 테스트"""

    def test_normalize_pro(self):
        """전문 변형"""
        assert normalize_category("전문") == "전문"
        assert normalize_category("PRO") == "전문"

    def test_normalize_club(self):
        """동호인 변형"""
        assert normalize_category("동호인") == "동호인"
        assert normalize_category("CLUB") == "동호인"
        assert normalize_category("아마추어") == "동호인"

    def test_empty_category(self):
        """빈 값 처리"""
        assert normalize_category("") is None
        assert normalize_category(None) is None


# =============================================================================
# event_name 추출 테스트
# =============================================================================

class TestExtractFromEventName:
    """event_name에서 필드 추출 테스트"""

    def test_extract_full_info(self):
        """전체 정보 추출"""
        result = extract_from_event_name("남자 중등부 에뻬 개인전")
        assert result.gender == "남"
        assert result.age_group == "MS"
        assert result.weapon == "에뻬"
        assert result.event_type == "개인전"

    def test_extract_elementary_grades(self):
        """초등 학년별 추출"""
        result1 = extract_from_event_name("초등부(1-2학년) 남자 플러레")
        assert result1.age_group == "E1"

        result2 = extract_from_event_name("초등부(3-4학년) 여자 에뻬")
        assert result2.age_group == "E2"

        result3 = extract_from_event_name("초등부(5-6학년) 남자 사브르")
        assert result3.age_group == "E3"

    def test_extract_abbreviated_forms(self):
        """축약형 추출: 남고, 여중, 남일 등"""
        assert extract_from_event_name("남고 에뻬(개)").age_group == "HS"
        assert extract_from_event_name("여중 플러레(단)").age_group == "MS"
        assert extract_from_event_name("남일 사브르(개)").age_group == "SR"
        assert extract_from_event_name("남초 에뻬(단)").age_group == "E3"

    def test_extract_elite(self):
        """엘리트부 추출"""
        result = extract_from_event_name("엘리트부 남자 플러레(개)")
        assert result.age_group == "SR"

    def test_extract_u_age(self):
        """U-age 추출"""
        assert extract_from_event_name("U13 남자 에뻬").age_group == "E3"
        assert extract_from_event_name("U15 여자 플러레").age_group == "MS"
        assert extract_from_event_name("U17 남자 사브르").age_group == "HS"

    def test_extract_weapon(self):
        """무기 추출"""
        assert extract_from_event_name("남자 에뻬 개인전").weapon == "에뻬"
        assert extract_from_event_name("여자 플러레 단체전").weapon == "플러레"
        assert extract_from_event_name("남자 사브르").weapon == "사브르"
        # 비표준도 정규화해서 추출
        assert extract_from_event_name("남자 에페 개인전").weapon == "에뻬"

    def test_extract_event_type(self):
        """종목 유형 추출"""
        assert extract_from_event_name("남자 에뻬 개인전").event_type == "개인전"
        assert extract_from_event_name("여자 플러레 단체전").event_type == "단체전"

    def test_no_age_group_info(self):
        """연령대 정보 없는 경우"""
        result = extract_from_event_name("남자 플러레(개)")
        assert result.age_group is None  # 추출 불가


# =============================================================================
# 레코드 정규화 테스트
# =============================================================================

class TestNormalizeEventRecord:
    """이벤트 레코드 정규화 테스트"""

    def test_normalize_existing_values(self):
        """기존 값 정규화"""
        event = {
            "weapon": "에페",
            "gender": "남자",
            "age_group": "중등부",
            "category": "PRO",
        }
        result = normalize_event_record(event)
        assert result["weapon"] == "에뻬"
        assert result["gender"] == "남"
        assert result["age_group"] == "MS"
        assert result["category"] == "전문"

    def test_extract_missing_from_event_name(self):
        """누락된 값 event_name에서 추출"""
        event = {
            "event_name": "남고 에뻬(개)",
            "weapon": None,
            "gender": None,
            "age_group": None,
        }
        result = normalize_event_record(event)
        assert result["weapon"] == "에뻬"
        assert result["age_group"] == "HS"
        assert result.get("_age_group_source") == "extracted"


# =============================================================================
# 변경사항 추적 테스트
# =============================================================================

class TestGetNormalizationChanges:
    """정규화 변경사항 추출 테스트"""

    def test_detect_weapon_change(self):
        """무기명 변경 감지"""
        original = {"weapon": "에페", "gender": "남", "age_group": "MS"}
        normalized = {"weapon": "에뻬", "gender": "남", "age_group": "MS"}
        changes = get_normalization_changes(original, normalized)
        assert "weapon" in changes
        assert changes["weapon"] == ("에페", "에뻬")

    def test_no_changes(self):
        """변경 없음"""
        original = {"weapon": "에뻬", "gender": "남", "age_group": "MS"}
        normalized = {"weapon": "에뻬", "gender": "남", "age_group": "MS"}
        changes = get_normalization_changes(original, normalized)
        assert len(changes) == 0


# =============================================================================
# 파이프라인 테스트
# =============================================================================

class TestDataPipeline:
    """데이터 파이프라인 테스트"""

    def test_pipeline_initialization(self):
        """파이프라인 초기화 테스트"""
        pipeline = DataPipeline()
        assert pipeline.stats["total_processed"] == 0
        assert pipeline.stats["total_passed"] == 0
        assert pipeline.stats["total_failed"] == 0

    def test_pipeline_stats(self):
        """파이프라인 통계 테스트"""
        pipeline = DataPipeline()
        stats = pipeline.get_stats()
        assert "total_processed" in stats
        assert "total_passed" in stats
        assert "pass_rate" in stats

    def test_pipeline_reset_stats(self):
        """통계 리셋 테스트"""
        pipeline = DataPipeline()
        pipeline.stats["total_processed"] = 100
        pipeline.reset_stats()
        assert pipeline.stats["total_processed"] == 0

    def test_validate_event_data(self):
        """이벤트 데이터 검증 테스트"""
        pipeline = DataPipeline()
        event_data = {
            "name": "남자 에뻬 개인전",
            "weapon": "에뻬",
            "gender": "남",
            "age_group": "Senior",
        }
        tech_result, biz_result = pipeline.validate_data(event_data, "event")
        # 기술적 검증 결과 확인
        assert tech_result is not None

    def test_validate_player_data(self):
        """선수 데이터 검증 테스트"""
        pipeline = DataPipeline()
        player_data = {
            "name": "홍길동",
            "team": "서울체육고등학교",
            "gender": "남",
            "nationality": "KOR",
        }
        tech_result, biz_result = pipeline.validate_data(player_data, "player")
        assert tech_result is not None


# =============================================================================
# 이벤트 시스템 테스트
# =============================================================================

class TestEventSystem:
    """이벤트 발행 시스템 테스트"""

    def test_data_change_event_creation(self):
        """DataChangeEvent 생성 테스트"""
        event = DataChangeEvent(
            event_type=EventType.PLAYER_CREATED,
            entity_type="player",
            entity_id=123,
            data={"name": "홍길동"},
        )
        assert event.event_type == EventType.PLAYER_CREATED
        assert event.entity_id == 123

    def test_event_type_values(self):
        """EventType 값 테스트"""
        assert EventType.PLAYER_CREATED.value == "player.created"
        assert EventType.PLAYER_UPDATED.value == "player.updated"
        assert EventType.MATCH_CREATED.value == "match.created"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
