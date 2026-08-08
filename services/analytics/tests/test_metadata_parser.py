"""Tests for fencing metadata parser.

Covers weapon, gender, age_group, bout_type, and expected_final_score
extraction from video titles and filenames.
"""

import pytest

from app.metadata_parser import parse_fencing_metadata


class TestWeaponDetection:
    """Weapon keyword detection tests."""

    def test_foil_english(self):
        result = parse_fencing_metadata("Final - Women's Foil - LEE vs ESAKI")
        assert result["weapon"] == "foil"

    def test_epee_english(self):
        result = parse_fencing_metadata("Men's Epee Gold Medal Bout")
        assert result["weapon"] == "epee"

    def test_epee_accent(self):
        result = parse_fencing_metadata("Épée Senior Final")
        assert result["weapon"] == "epee"

    def test_sabre_english(self):
        result = parse_fencing_metadata("Sabre Semifinal")
        assert result["weapon"] == "sabre"

    def test_saber_american_spelling(self):
        result = parse_fencing_metadata("Junior Saber Quarterfinal")
        assert result["weapon"] == "sabre"

    def test_foil_korean(self):
        result = parse_fencing_metadata("전국체전 남자 플뢰레 결승")
        assert result["weapon"] == "foil"

    def test_epee_korean(self):
        result = parse_fencing_metadata("회장배 여자 에페 예선")
        assert result["weapon"] == "epee"

    def test_sabre_korean(self):
        result = parse_fencing_metadata("사브르 남자 시니어 8강")
        assert result["weapon"] == "sabre"

    def test_unknown_weapon(self):
        result = parse_fencing_metadata("NAC Match 2024")
        assert result["weapon"] == "unknown"

    def test_case_insensitive(self):
        result = parse_fencing_metadata("FOIL GOLD MEDAL BOUT")
        assert result["weapon"] == "foil"


class TestGenderDetection:
    """Gender keyword detection tests."""

    def test_mens(self):
        result = parse_fencing_metadata("Men's Foil Final")
        assert result["gender"] == "men"

    def test_womens(self):
        result = parse_fencing_metadata("Women's Epee Semifinal")
        assert result["gender"] == "women"

    def test_boys(self):
        result = parse_fencing_metadata("Boys Y12 Foil Pool")
        assert result["gender"] == "men"

    def test_girls(self):
        result = parse_fencing_metadata("Girls Y14 Sabre Final")
        assert result["gender"] == "women"

    def test_korean_male(self):
        result = parse_fencing_metadata("남자 플뢰레 결승")
        assert result["gender"] == "men"

    def test_korean_female(self):
        result = parse_fencing_metadata("여자 에페 예선")
        assert result["gender"] == "women"

    def test_unknown_gender(self):
        result = parse_fencing_metadata("Foil Final 2024")
        assert result["gender"] == "unknown"


class TestAgeGroupDetection:
    """Age group keyword detection tests."""

    def test_cadet(self):
        result = parse_fencing_metadata("Cadet Men's Foil")
        assert result["age_group"] == "cadet"

    def test_junior(self):
        result = parse_fencing_metadata("Junior Women's Epee Final")
        assert result["age_group"] == "junior"

    def test_senior(self):
        result = parse_fencing_metadata("Senior Sabre Semifinal")
        assert result["age_group"] == "senior"

    def test_veteran(self):
        result = parse_fencing_metadata("Veteran Foil Gold Medal")
        assert result["age_group"] == "veteran"

    def test_y10(self):
        result = parse_fencing_metadata("Y10 Boys Foil Pool")
        assert result["age_group"] == "y10"

    def test_y12(self):
        result = parse_fencing_metadata("Y12 Women's Foil Final - LEE vs ESAKI")
        assert result["age_group"] == "y12"

    def test_y14(self):
        result = parse_fencing_metadata("Y14 Sabre Semifinal")
        assert result["age_group"] == "y14"

    def test_unknown_age(self):
        result = parse_fencing_metadata("Foil Final 2024")
        assert result["age_group"] == "unknown"


class TestBoutTypeDetection:
    """Bout type detection tests."""

    def test_final_is_de(self):
        result = parse_fencing_metadata("Gold Medal Final - Foil")
        assert result["bout_type"] == "de"

    def test_semifinal_is_de(self):
        result = parse_fencing_metadata("Semifinal Men's Epee")
        assert result["bout_type"] == "de"

    def test_quarterfinal_is_de(self):
        result = parse_fencing_metadata("Quarterfinal Women's Sabre")
        assert result["bout_type"] == "de"

    def test_pool_keyword(self):
        result = parse_fencing_metadata("Pool Round 3 Foil")
        assert result["bout_type"] == "pool"

    def test_poule_keyword(self):
        result = parse_fencing_metadata("Poule 5 Epee")
        assert result["bout_type"] == "pool"

    def test_korean_final(self):
        result = parse_fencing_metadata("남자 플뢰레 결승")
        assert result["bout_type"] == "de"

    def test_korean_pool(self):
        result = parse_fencing_metadata("여자 에페 예선")
        assert result["bout_type"] == "pool"

    def test_t16(self):
        result = parse_fencing_metadata("T16 Men's Foil")
        assert result["bout_type"] == "de"

    def test_unknown_bout(self):
        result = parse_fencing_metadata("NAC Match 2024")
        assert result["bout_type"] == "unknown"

    def test_pool_takes_priority_over_final_in_text(self):
        """Pool keyword appears first, should match pool."""
        result = parse_fencing_metadata("Pool 3 - some final results")
        assert result["bout_type"] == "pool"


class TestExpectedFinalScore:
    """Expected final score inference tests."""

    def test_pool_gives_5(self):
        result = parse_fencing_metadata("Pool Round Foil")
        assert result["expected_final_score"] == 5

    def test_de_gives_15(self):
        result = parse_fencing_metadata("Final Men's Epee")
        assert result["expected_final_score"] == 15

    def test_unknown_gives_none(self):
        result = parse_fencing_metadata("NAC Match 2024")
        assert result["expected_final_score"] is None


class TestCompoundTitles:
    """Tests for complex titles with multiple metadata fields."""

    def test_full_title(self):
        result = parse_fencing_metadata(
            "Final - Y12 Women's Foil - LEE vs ESAKI"
        )
        assert result["weapon"] == "foil"
        assert result["gender"] == "women"
        assert result["age_group"] == "y12"
        assert result["bout_type"] == "de"
        assert result["expected_final_score"] == 15

    def test_nac_filename(self):
        result = parse_fencing_metadata(
            "nac_y12wf_lee_esaki_k-spxGdlWfo.mp4"
        )
        assert result["age_group"] == "y12"
        # 'wf' doesn't match exact keywords, but 'y12' does

    def test_korean_compound(self):
        result = parse_fencing_metadata("2026-전국체전-남자플뢰레-김민수vs박지현.mp4")
        assert result["weapon"] == "foil"
        assert result["gender"] == "men"

    def test_empty_string(self):
        result = parse_fencing_metadata("")
        assert result["weapon"] == "unknown"
        assert result["gender"] == "unknown"
        assert result["age_group"] == "unknown"
        assert result["bout_type"] == "unknown"
        assert result["expected_final_score"] is None
