"""
Translation Service for Multi-Language Database Content

Provides unified translation interface for:
- Player names (Korean -> English romanization)
- Organization names (Korean -> English)
- Competition names (Korean -> English)

Usage:
    from app.translation_service import TranslationService

    ts = TranslationService()

    # Player name
    result = ts.translate_player_name("박소윤")
    # {"en": {"name": "Soyun Park", "verified": False, "source": "romanization"}}

    # Organization name
    result = ts.translate_organization_name("최병철펜싱클럽")
    # {"en": {"name": "Choi Byeongcheol Fencing Club", "verified": True, "source": "verified"}}
"""

import re
from datetime import datetime
from typing import Dict, Any, Optional, List

from app.international_data import (
    InternationalDataManager,
    VERIFIED_NAME_MAPPINGS,
    KOREAN_SURNAMES,
    romanize_syllable,
    is_korean_char,
    generate_english_name_candidates,
)
from app.organization_identity import (
    OrganizationIdentityResolver,
    VERIFIED_ORG_MAPPINGS,
    KOREAN_TO_ENGLISH_ORG,
    KOREAN_REGIONS,
)


# Competition name translation patterns
COMPETITION_NAME_PATTERNS = {
    # 대회 종류
    "회장배": "President's Cup",
    "협회장배": "Association President's Cup",
    "전국선수권대회": "National Championship",
    "전국선수권": "National Championship",
    "선수권대회": "Championship",
    "선수권": "Championship",
    "전국체육대회": "National Sports Festival",
    "전국대회": "National Championship",
    "종별선수권대회": "Category Championship",
    "종별선수권": "Category Championship",
    "종합선수권대회": "General Championship",
    "종합선수권": "General Championship",

    # 연령별 대회
    "꿈나무대회": "Youth Championship",
    "꿈나무": "Youth",
    "초등부대회": "Elementary Championship",
    "중등부대회": "Middle School Championship",
    "고등부대회": "High School Championship",
    "대학부대회": "University Championship",
    "동호인대회": "Club Championship",
    "동호인": "Club",
    "생활체육대회": "Community Sports Championship",

    # 국제대회
    "국제대회": "International Championship",
    "국제펜싱대회": "International Fencing Championship",
    "아시아선수권대회": "Asian Championship",
    "아시아선수권": "Asian Championship",
    "세계선수권대회": "World Championship",
    "세계선수권": "World Championship",
    "올림픽": "Olympic",

    # 기타
    "펜싱대회": "Fencing Championship",
    "대회": "Championship",
    "리그": "League",
    "컵": "Cup",
    "오픈": "Open",
    "페스티벌": "Festival",
    "챔피언십": "Championship",

    # 주최/지역
    "전국": "National",
    "서울시": "Seoul",
    "부산시": "Busan",
    "대구시": "Daegu",
    "인천시": "Incheon",
    "광주시": "Gwangju",
    "대전시": "Daejeon",
    "울산시": "Ulsan",
    "경기도": "Gyeonggi Province",
    "강원도": "Gangwon Province",
    "충청북도": "Chungbuk Province",
    "충청남도": "Chungnam Province",
    "전라북도": "Jeonbuk Province",
    "전라남도": "Jeonnam Province",
    "경상북도": "Gyeongbuk Province",
    "경상남도": "Gyeongnam Province",
    "제주도": "Jeju Province",
    "제주특별자치도": "Jeju Special Self-Governing Province",
}

# Verified competition name mappings
VERIFIED_COMPETITION_MAPPINGS = {
    "회장배 전국펜싱선수권대회": "President's Cup National Fencing Championship",
    "전국체육대회": "National Sports Festival",
    "전국종별펜싱선수권대회": "National Category Fencing Championship",
    "전국종합펜싱선수권대회": "National General Fencing Championship",
    "KFA회장배 전국펜싱대회": "KFA President's Cup National Fencing Championship",
    "협회장배 전국중고펜싱대회": "Association President's Cup National Middle/High School Fencing Championship",
    "꿈나무 전국펜싱대회": "Youth National Fencing Championship",
    "전국동호인펜싱대회": "National Club Fencing Championship",
    "전국생활체육펜싱대회": "National Community Sports Fencing Championship",
}


class TranslationService:
    """
    Unified translation service for database content.

    Provides consistent interface for translating:
    - Player names (Korean -> English, Western order: Given Surname)
    - Organization names (Korean -> English)
    - Competition names (Korean -> English)
    """

    def __init__(self):
        self.intl_manager = InternationalDataManager()
        self.org_resolver = OrganizationIdentityResolver()

    def translate_player_name(self, korean_name: str) -> Dict[str, Any]:
        """
        Convert Korean player name to English romanization.

        Format: Western order (Given name + Surname)
        Example: 박소윤 -> Soyun Park

        Args:
            korean_name: Korean name (e.g., "박소윤")

        Returns:
            Translation dict for JSONB storage:
            {
                "en": {
                    "name": "Soyun Park",
                    "name_order": "western",
                    "verified": False,
                    "source": "romanization",
                    "updated_at": "2025-01-09T..."
                }
            }
        """
        if not korean_name:
            return {}

        korean_name = korean_name.strip()
        now = datetime.utcnow().isoformat() + "Z"

        # Check verified mappings first
        if korean_name in VERIFIED_NAME_MAPPINGS:
            verified = VERIFIED_NAME_MAPPINGS[korean_name]
            return {
                "en": {
                    "name": self._format_western_name(verified['en_given'], verified['en_surname']),
                    "name_order": "western",
                    "verified": True,
                    "source": "verified",
                    "fie_id": verified.get('fie_id'),
                    "fencingtracker_id": verified.get('fencingtracker_id'),
                    "updated_at": now,
                }
            }

        # Generate romanization
        candidates = generate_english_name_candidates(korean_name)
        if not candidates:
            # Fallback: simple romanization
            return self._fallback_romanization(korean_name)

        # Get the best Western-order candidate
        western_candidates = [c for c in candidates if c.name_order == 'western']
        if western_candidates:
            best = max(western_candidates, key=lambda c: c.confidence)
        else:
            best = max(candidates, key=lambda c: c.confidence)

        return {
            "en": {
                "name": best.full_name,
                "name_order": best.name_order,
                "verified": False,
                "source": best.source,
                "confidence": best.confidence,
                "updated_at": now,
            }
        }

    def _format_western_name(self, given: str, surname: str) -> str:
        """Format name in Western order (Given Surname)."""
        return f"{given} {surname}"

    def _fallback_romanization(self, korean_name: str) -> Dict[str, Any]:
        """Fallback romanization for names not matching standard patterns."""
        now = datetime.utcnow().isoformat() + "Z"

        # Assume first character is surname
        surname_kr = korean_name[0] if korean_name else ''
        given_kr = korean_name[1:] if len(korean_name) > 1 else ''

        # Get surname romanization
        surname_variants = KOREAN_SURNAMES.get(surname_kr, [])
        surname_en = surname_variants[0] if surname_variants else self._romanize_text(surname_kr).capitalize()

        # Romanize given name
        given_en = self._romanize_text(given_kr).capitalize()

        return {
            "en": {
                "name": f"{given_en} {surname_en}",
                "name_order": "western",
                "verified": False,
                "source": "fallback_romanization",
                "updated_at": now,
            }
        }

    def _romanize_text(self, text: str) -> str:
        """Romanize Korean text character by character."""
        result = ''
        for char in text:
            if is_korean_char(char):
                result += romanize_syllable(char)
            else:
                result += char
        return result

    def translate_organization_name(self, korean_name: str) -> Dict[str, Any]:
        """
        Convert Korean organization name to English.

        Example: 최병철펜싱클럽 -> Choi Byeongcheol Fencing Club

        Args:
            korean_name: Korean organization name

        Returns:
            Translation dict for JSONB storage
        """
        if not korean_name:
            return {}

        korean_name = korean_name.strip()
        now = datetime.utcnow().isoformat() + "Z"

        # Check verified mappings first
        if korean_name in VERIFIED_ORG_MAPPINGS:
            verified = VERIFIED_ORG_MAPPINGS[korean_name]
            return {
                "en": {
                    "name": verified["name_en"],
                    "verified": True,
                    "source": "verified",
                    "updated_at": now,
                }
            }

        # Use OrganizationIdentityResolver
        profile = self.org_resolver.get_or_create_organization(korean_name)

        return {
            "en": {
                "name": profile.name_en,
                "verified": profile.name_en_verified,
                "source": "auto_translation",
                "org_type": profile.org_type.value,
                "updated_at": now,
            }
        }

    def translate_competition_name(self, korean_name: str) -> Dict[str, Any]:
        """
        Convert Korean competition name to English.

        Example: 회장배 전국펜싱선수권대회 -> President's Cup National Fencing Championship

        Args:
            korean_name: Korean competition name

        Returns:
            Translation dict for JSONB storage
        """
        if not korean_name:
            return {}

        korean_name = korean_name.strip()
        now = datetime.utcnow().isoformat() + "Z"

        # Check verified mappings first
        if korean_name in VERIFIED_COMPETITION_MAPPINGS:
            return {
                "en": {
                    "name": VERIFIED_COMPETITION_MAPPINGS[korean_name],
                    "verified": True,
                    "source": "verified",
                    "updated_at": now,
                }
            }

        # Pattern-based translation
        english_name = self._translate_competition_pattern(korean_name)

        return {
            "en": {
                "name": english_name,
                "verified": False,
                "source": "pattern_translation",
                "updated_at": now,
            }
        }

    def _translate_competition_pattern(self, korean_name: str) -> str:
        """
        Translate competition name using pattern matching.

        Applies translations from longest to shortest patterns to avoid
        partial matches (e.g., "전국대회" before "대회").
        """
        result = korean_name

        # Sort patterns by length (longest first) to avoid partial matches
        sorted_patterns = sorted(
            COMPETITION_NAME_PATTERNS.items(),
            key=lambda x: len(x[0]),
            reverse=True
        )

        for korean, english in sorted_patterns:
            if korean in result:
                result = result.replace(korean, english + " ")

        # Also apply region translations
        for korean, english in sorted(
            KOREAN_REGIONS.items(),
            key=lambda x: len(x[0]),
            reverse=True
        ):
            if korean in result:
                result = result.replace(korean, english + " ")

        # Clean up: remove duplicate spaces and trim
        result = re.sub(r'\s+', ' ', result).strip()

        # Romanize any remaining Korean characters
        if re.search(r'[가-힣]', result):
            parts = []
            current = ""
            for char in result:
                if is_korean_char(char):
                    if current:
                        parts.append(current)
                        current = ""
                    parts.append(romanize_syllable(char))
                else:
                    current += char
            if current:
                parts.append(current)
            result = ''.join(parts).title()

        return result

    def get_localized_name(
        self,
        record: Dict[str, Any],
        lang: str,
        fallback_field: str = "name"
    ) -> str:
        """
        Get name in specified language with fallback to original.

        Args:
            record: Database record with 'translations' field
            lang: Target language code (e.g., 'en', 'ko')
            fallback_field: Field name to use as fallback

        Returns:
            Localized name or fallback value
        """
        # If requesting Korean, return original
        if lang == 'ko':
            return record.get(fallback_field, '')

        # Check translations
        translations = record.get('translations', {})
        if isinstance(translations, dict):
            lang_data = translations.get(lang, {})
            if isinstance(lang_data, dict) and lang_data.get('name'):
                return lang_data['name']

        # Fallback to original
        return record.get(fallback_field, '')

    def batch_translate_players(
        self,
        players: List[Dict[str, Any]],
        name_field: str = "name"
    ) -> List[Dict[str, Any]]:
        """
        Batch translate player names.

        Args:
            players: List of player records
            name_field: Field containing Korean name

        Returns:
            List of translation dicts ready for DB update
        """
        results = []
        for player in players:
            korean_name = player.get(name_field, "")
            player_id = player.get("id")

            translation = self.translate_player_name(korean_name)

            results.append({
                "id": player_id,
                "translations": translation,
            })

        return results

    def batch_translate_organizations(
        self,
        organizations: List[Dict[str, Any]],
        name_field: str = "name"
    ) -> List[Dict[str, Any]]:
        """
        Batch translate organization names.

        Args:
            organizations: List of organization records
            name_field: Field containing Korean name

        Returns:
            List of translation dicts ready for DB update
        """
        results = []
        for org in organizations:
            korean_name = org.get(name_field, "")
            org_id = org.get("id")

            translation = self.translate_organization_name(korean_name)

            results.append({
                "id": org_id,
                "translations": translation,
            })

        return results

    def batch_translate_competitions(
        self,
        competitions: List[Dict[str, Any]],
        name_field: str = "name"
    ) -> List[Dict[str, Any]]:
        """
        Batch translate competition names.

        Args:
            competitions: List of competition records
            name_field: Field containing Korean name

        Returns:
            List of translation dicts ready for DB update
        """
        results = []
        for comp in competitions:
            korean_name = comp.get(name_field, "")
            comp_id = comp.get("id")

            translation = self.translate_competition_name(korean_name)

            results.append({
                "id": comp_id,
                "translations": translation,
            })

        return results


# Singleton instance
_translation_service: Optional[TranslationService] = None


def get_translation_service() -> TranslationService:
    """Get or create singleton TranslationService instance."""
    global _translation_service
    if _translation_service is None:
        _translation_service = TranslationService()
    return _translation_service


# Quick test
if __name__ == "__main__":
    ts = TranslationService()

    print("=== Player Name Tests ===")
    test_names = ["박소윤", "김철수", "공하이", "송세라", "이민지"]
    for name in test_names:
        result = ts.translate_player_name(name)
        print(f"{name} -> {result.get('en', {}).get('name', 'N/A')}")

    print("\n=== Organization Name Tests ===")
    test_orgs = ["최병철펜싱클럽", "서울체육고등학교", "한국체육대학교", "부산시청", "송도펜싱클럽"]
    for org in test_orgs:
        result = ts.translate_organization_name(org)
        print(f"{org} -> {result.get('en', {}).get('name', 'N/A')}")

    print("\n=== Competition Name Tests ===")
    test_comps = ["회장배 전국펜싱선수권대회", "전국체육대회", "전국종별펜싱선수권대회", "꿈나무 전국펜싱대회"]
    for comp in test_comps:
        result = ts.translate_competition_name(comp)
        print(f"{comp} -> {result.get('en', {}).get('name', 'N/A')}")
