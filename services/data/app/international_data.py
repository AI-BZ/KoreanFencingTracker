"""
International Fencing Data Integration Module

Handles:
1. Korean ↔ English name conversion (romanization)
2. FIE (International Fencing Federation) data lookup
3. FencingTracker data lookup
4. Name verification and matching

Test cases:
- 박소윤 ↔ Soyun Park (FencingTracker ID: 100809497)
- 공하이 ↔ Hai Gong (FencingTracker ID: 100370147)
"""

import re
import json
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime
import httpx
from pathlib import Path


# Korean to English romanization mapping (Revised Romanization of Korean)
KOREAN_ROMANIZATION = {
    # 초성 (Initial consonants)
    'ㄱ': 'g', 'ㄲ': 'kk', 'ㄴ': 'n', 'ㄷ': 'd', 'ㄸ': 'tt',
    'ㄹ': 'r', 'ㅁ': 'm', 'ㅂ': 'b', 'ㅃ': 'pp', 'ㅅ': 's',
    'ㅆ': 'ss', 'ㅇ': '', 'ㅈ': 'j', 'ㅉ': 'jj', 'ㅊ': 'ch',
    'ㅋ': 'k', 'ㅌ': 't', 'ㅍ': 'p', 'ㅎ': 'h',

    # 중성 (Vowels)
    'ㅏ': 'a', 'ㅐ': 'ae', 'ㅑ': 'ya', 'ㅒ': 'yae', 'ㅓ': 'eo',
    'ㅔ': 'e', 'ㅕ': 'yeo', 'ㅖ': 'ye', 'ㅗ': 'o', 'ㅘ': 'wa',
    'ㅙ': 'wae', 'ㅚ': 'oe', 'ㅛ': 'yo', 'ㅜ': 'u', 'ㅝ': 'wo',
    'ㅞ': 'we', 'ㅟ': 'wi', 'ㅠ': 'yu', 'ㅡ': 'eu', 'ㅢ': 'ui',
    'ㅣ': 'i',

    # 종성 (Final consonants)
    'ㄱ_f': 'k', 'ㄲ_f': 'k', 'ㄳ_f': 'k', 'ㄴ_f': 'n', 'ㄵ_f': 'n',
    'ㄶ_f': 'n', 'ㄷ_f': 't', 'ㄹ_f': 'l', 'ㄺ_f': 'k', 'ㄻ_f': 'm',
    'ㄼ_f': 'l', 'ㄽ_f': 'l', 'ㄾ_f': 'l', 'ㄿ_f': 'p', 'ㅀ_f': 'l',
    'ㅁ_f': 'm', 'ㅂ_f': 'p', 'ㅄ_f': 'p', 'ㅅ_f': 't', 'ㅆ_f': 't',
    'ㅇ_f': 'ng', 'ㅈ_f': 't', 'ㅊ_f': 't', 'ㅋ_f': 'k', 'ㅌ_f': 't',
    'ㅍ_f': 'p', 'ㅎ_f': 't',
}

# Common Korean surnames with standard romanizations
KOREAN_SURNAMES = {
    '김': ['Kim', 'Gim'],
    '이': ['Lee', 'Yi', 'Rhee'],
    '박': ['Park', 'Pak', 'Bak'],
    '최': ['Choi', 'Choe'],
    '정': ['Jung', 'Jeong', 'Chung'],
    '강': ['Kang', 'Gang'],
    '조': ['Jo', 'Cho'],
    '윤': ['Yoon', 'Yun'],
    '장': ['Jang', 'Chang'],
    '임': ['Lim', 'Im', 'Yim'],
    '한': ['Han'],
    '오': ['Oh', 'O'],
    '서': ['Seo', 'Suh'],
    '신': ['Shin', 'Sin'],
    '권': ['Kwon', 'Gwon'],
    '황': ['Hwang'],
    '안': ['An', 'Ahn'],
    '송': ['Song'],
    '류': ['Ryu', 'Yoo', 'Yu'],
    '유': ['Yoo', 'Yu', 'You'],
    '홍': ['Hong'],
    '전': ['Jeon', 'Jun', 'Chun'],
    '고': ['Ko', 'Go', 'Koh'],
    '문': ['Moon', 'Mun'],
    '양': ['Yang'],
    '손': ['Son'],
    '배': ['Bae', 'Pae'],
    '백': ['Baek', 'Paek', 'Back'],
    '허': ['Heo', 'Hur', 'Huh'],
    '노': ['No', 'Noh', 'Roh'],
    '남': ['Nam'],
    '하': ['Ha'],
    '심': ['Shim', 'Sim'],
    '주': ['Joo', 'Ju'],
    '공': ['Gong', 'Kong'],
}

# Known verified mappings (확인된 매핑)
VERIFIED_NAME_MAPPINGS = {
    # Format: 'korean_name': {'en_name': 'English Name', 'fie_id': None, 'fencingtracker_id': '...', 'verified': True}
    '박소윤': {
        'en_name': 'Soyun Park',
        'en_surname': 'Park',
        'en_given': 'Soyun',
        'fie_id': None,
        'fencingtracker_id': '100809497',
        'birth_year': 2013,
        'weapon': 'Foil',
        'verified': True,
        'verified_date': '2024-12-17',
    },
    '공하이': {
        'en_name': 'Hai Gong',
        'en_surname': 'Gong',
        'en_given': 'Hai',
        'fie_id': None,
        'fencingtracker_id': '100370147',
        'birth_year': None,
        'weapon': 'Foil',
        'verified': True,
        'verified_date': '2024-12-17',
    },
    # FIE 랭킹 선수들 (공식 데이터)
    '송세라': {
        'en_name': 'SONG Sera',
        'en_surname': 'Song',
        'en_given': 'Sera',
        'fie_id': '33038',
        'fencingtracker_id': None,
        'birth_year': 1992,
        'weapon': 'Epee',
        'verified': True,
        'verified_date': '2024-12-17',
    },
    '임태희': {
        'en_name': 'LIM Taehee',
        'en_surname': 'Lim',
        'en_given': 'Taehee',
        'fie_id': '46568',
        'fencingtracker_id': None,
        'birth_year': 2001,
        'weapon': 'Epee',
        'verified': True,
        'verified_date': '2024-12-17',
    },
}


@dataclass
class InternationalRecord:
    """Record from international competition"""
    source: str  # 'fie', 'fencingtracker', 'askfred'
    source_id: str  # ID in that system
    competition_name: str
    competition_date: str
    event_name: str
    weapon: str
    result: str  # e.g., "28/40", "Gold", "T32"
    country: str  # e.g., "KOR"


@dataclass
class EnglishNameCandidate:
    """Candidate English name with confidence score"""
    full_name: str  # "Soyun Park"
    surname: str  # "Park"
    given_name: str  # "Soyun"
    name_order: str  # "western" (Given Surname) or "eastern" (Surname Given)
    confidence: float  # 0.0 - 1.0
    source: str  # 'romanization', 'verified', 'fie_match', 'fencingtracker_match'
    external_id: Optional[str] = None  # FIE ID or FencingTracker ID if matched


@dataclass
class PlayerInternationalProfile:
    """Extended player profile with international data"""
    korean_name: str
    english_names: List[EnglishNameCandidate] = field(default_factory=list)
    primary_english_name: Optional[str] = None

    # External IDs
    fie_id: Optional[str] = None
    fencingtracker_id: Optional[str] = None

    # International records
    international_records: List[InternationalRecord] = field(default_factory=list)

    # FIE ranking
    fie_ranking: Optional[Dict] = None  # {'weapon': 'Epee', 'rank': 1, 'points': 233.0}

    # Verification status
    verified: bool = False
    verification_date: Optional[str] = None
    verification_notes: str = ""


def decompose_korean_char(char: str) -> Tuple[str, str, str]:
    """Decompose a Korean character into initial, vowel, final."""
    if not char or not is_korean_char(char):
        return ('', '', '')

    code = ord(char) - 0xAC00

    # 초성, 중성, 종성 분리
    initial_idx = code // (21 * 28)
    vowel_idx = (code % (21 * 28)) // 28
    final_idx = code % 28

    initials = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
    vowels = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'
    finals = ['', 'ㄱ', 'ㄲ', 'ㄳ', 'ㄴ', 'ㄵ', 'ㄶ', 'ㄷ', 'ㄹ', 'ㄺ', 'ㄻ', 'ㄼ',
              'ㄽ', 'ㄾ', 'ㄿ', 'ㅀ', 'ㅁ', 'ㅂ', 'ㅄ', 'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ',
              'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ']

    return (initials[initial_idx], vowels[vowel_idx], finals[final_idx])


def is_korean_char(char: str) -> bool:
    """Check if character is Korean Hangul."""
    return '\uAC00' <= char <= '\uD7A3'


def romanize_korean_name(korean_name: str) -> List[str]:
    """
    Convert Korean name to English romanization.
    Returns multiple possible romanizations.
    """
    if not korean_name:
        return []

    # Check if it's in verified mappings
    if korean_name in VERIFIED_NAME_MAPPINGS:
        verified = VERIFIED_NAME_MAPPINGS[korean_name]
        return [verified['en_name']]

    # Split into surname and given name (assume first char is surname)
    surname_kr = korean_name[0] if korean_name else ''
    given_kr = korean_name[1:] if len(korean_name) > 1 else ''

    # Get surname romanizations
    surname_variants = KOREAN_SURNAMES.get(surname_kr, [romanize_syllable(surname_kr)])

    # Romanize given name
    given_romanized = ''
    for char in given_kr:
        given_romanized += romanize_syllable(char)

    # Capitalize first letter
    given_romanized = given_romanized.capitalize()

    # Generate variants
    variants = []
    for surname in surname_variants:
        # Western order: Given Surname (e.g., "Soyun Park")
        variants.append(f"{given_romanized} {surname}")
        # Eastern order: Surname Given (e.g., "Park Soyun")
        variants.append(f"{surname} {given_romanized}")
        # FIE style: SURNAME Given (e.g., "PARK Soyun")
        variants.append(f"{surname.upper()} {given_romanized}")

    return variants


def romanize_syllable(syllable: str) -> str:
    """Romanize a single Korean syllable."""
    if not syllable or not is_korean_char(syllable):
        return syllable

    initial, vowel, final = decompose_korean_char(syllable)

    result = ''

    # Initial consonant
    result += KOREAN_ROMANIZATION.get(initial, '')

    # Vowel
    result += KOREAN_ROMANIZATION.get(vowel, '')

    # Final consonant
    if final:
        result += KOREAN_ROMANIZATION.get(f'{final}_f', '')

    return result


def generate_english_name_candidates(korean_name: str) -> List[EnglishNameCandidate]:
    """Generate possible English name candidates for a Korean name."""
    candidates = []

    # Check verified mappings first
    if korean_name in VERIFIED_NAME_MAPPINGS:
        verified = VERIFIED_NAME_MAPPINGS[korean_name]
        candidates.append(EnglishNameCandidate(
            full_name=verified['en_name'],
            surname=verified['en_surname'],
            given_name=verified['en_given'],
            name_order='western' if verified['en_name'].split()[0] == verified['en_given'] else 'eastern',
            confidence=1.0,
            source='verified',
            external_id=verified.get('fie_id') or verified.get('fencingtracker_id')
        ))
        return candidates

    # Generate from romanization
    surname_kr = korean_name[0] if korean_name else ''
    given_kr = korean_name[1:] if len(korean_name) > 1 else ''

    surname_variants = KOREAN_SURNAMES.get(surname_kr, [romanize_syllable(surname_kr).capitalize()])
    given_romanized = ''.join(romanize_syllable(c) for c in given_kr).capitalize()

    for i, surname in enumerate(surname_variants):
        # Higher confidence for first (most common) variant
        base_confidence = 0.7 - (i * 0.1)

        # Western order (Given Surname) - more common in international competitions
        candidates.append(EnglishNameCandidate(
            full_name=f"{given_romanized} {surname}",
            surname=surname,
            given_name=given_romanized,
            name_order='western',
            confidence=base_confidence,
            source='romanization'
        ))

        # Eastern order (Surname Given)
        candidates.append(EnglishNameCandidate(
            full_name=f"{surname} {given_romanized}",
            surname=surname,
            given_name=given_romanized,
            name_order='eastern',
            confidence=base_confidence - 0.05,
            source='romanization'
        ))

    return candidates


class FencingTrackerClient:
    """Client for FencingTracker.com data lookup."""

    BASE_URL = "https://fencingtracker.com"

    def __init__(self):
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def search_player(self, name: str) -> List[Dict]:
        """Search for a player by name."""
        try:
            response = self.client.get(f"{self.BASE_URL}/search", params={"s": name})
            # Parse HTML response - would need BeautifulSoup for proper parsing
            # For now, return empty - actual implementation would parse HTML
            return []
        except Exception as e:
            print(f"FencingTracker search error: {e}")
            return []

    def get_player_profile(self, player_id: str) -> Optional[Dict]:
        """Get player profile by FencingTracker ID."""
        try:
            # This would need HTML parsing - placeholder
            return {
                'id': player_id,
                'url': f"{self.BASE_URL}/p/{player_id}"
            }
        except Exception as e:
            print(f"FencingTracker profile error: {e}")
            return None

    def close(self):
        self.client.close()


class FIEClient:
    """Client for FIE.org data lookup."""

    BASE_URL = "https://fie.org"

    def __init__(self):
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def search_korean_fencers(self, weapon: str = 'E', gender: str = 'F',
                               category: str = 'S') -> List[Dict]:
        """Search for Korean fencers in FIE rankings."""
        # This would need proper HTML parsing
        # For now, return known data
        return []

    def get_athlete_profile(self, fie_id: str) -> Optional[Dict]:
        """Get athlete profile by FIE ID."""
        try:
            return {
                'id': fie_id,
                'url': f"{self.BASE_URL}/athletes/{fie_id}"
            }
        except Exception as e:
            print(f"FIE profile error: {e}")
            return None

    def close(self):
        self.client.close()


class InternationalDataManager:
    """
    Manager for international fencing data integration.

    Features:
    1. Korean → English name conversion
    2. Name verification against FIE/FencingTracker
    3. International record lookup
    4. Data caching
    """

    def __init__(self, cache_dir: str = "data/international_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Load name mappings
        self.name_mappings_file = self.cache_dir / "name_mappings.json"
        self.name_mappings = self._load_name_mappings()

        # Initialize clients
        self.fencingtracker = FencingTrackerClient()
        self.fie = FIEClient()

    def _load_name_mappings(self) -> Dict:
        """Load saved name mappings."""
        if self.name_mappings_file.exists():
            with open(self.name_mappings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _save_name_mappings(self):
        """Save name mappings to file."""
        with open(self.name_mappings_file, 'w', encoding='utf-8') as f:
            json.dump(self.name_mappings, f, ensure_ascii=False, indent=2)

    def get_english_name(self, korean_name: str, auto_verify: bool = False) -> Optional[EnglishNameCandidate]:
        """
        Get the best English name for a Korean name.

        Args:
            korean_name: Korean name (e.g., "박소윤")
            auto_verify: If True, attempt to verify against external sources

        Returns:
            Best matching EnglishNameCandidate or None
        """
        # Check cache first
        if korean_name in self.name_mappings:
            cached = self.name_mappings[korean_name]
            return EnglishNameCandidate(
                full_name=cached['en_name'],
                surname=cached.get('en_surname', ''),
                given_name=cached.get('en_given', ''),
                name_order=cached.get('name_order', 'western'),
                confidence=cached.get('confidence', 0.8),
                source=cached.get('source', 'cached'),
                external_id=cached.get('external_id')
            )

        # Check verified mappings
        if korean_name in VERIFIED_NAME_MAPPINGS:
            verified = VERIFIED_NAME_MAPPINGS[korean_name]
            return EnglishNameCandidate(
                full_name=verified['en_name'],
                surname=verified['en_surname'],
                given_name=verified['en_given'],
                name_order='western',
                confidence=1.0,
                source='verified',
                external_id=verified.get('fie_id') or verified.get('fencingtracker_id')
            )

        # Generate candidates
        candidates = generate_english_name_candidates(korean_name)

        if not candidates:
            return None

        # Return highest confidence candidate
        best = max(candidates, key=lambda c: c.confidence)

        # Cache the result
        self.name_mappings[korean_name] = {
            'en_name': best.full_name,
            'en_surname': best.surname,
            'en_given': best.given_name,
            'name_order': best.name_order,
            'confidence': best.confidence,
            'source': best.source,
            'external_id': best.external_id,
            'generated_date': datetime.now().isoformat()
        }
        self._save_name_mappings()

        return best

    def verify_name_match(self, korean_name: str, english_name: str) -> Tuple[bool, float, str]:
        """
        Verify if a Korean name matches an English name.

        Returns:
            (is_match, confidence, reason)
        """
        # Check verified mappings
        if korean_name in VERIFIED_NAME_MAPPINGS:
            verified = VERIFIED_NAME_MAPPINGS[korean_name]
            if verified['en_name'].lower() == english_name.lower():
                return (True, 1.0, "Verified match")
            # Check partial match (surname or given name)
            if (verified['en_surname'].lower() in english_name.lower() or
                verified['en_given'].lower() in english_name.lower()):
                return (True, 0.8, "Partial verified match")

        # Generate candidates and compare
        candidates = generate_english_name_candidates(korean_name)

        for candidate in candidates:
            # Exact match
            if candidate.full_name.lower() == english_name.lower():
                return (True, candidate.confidence, f"Romanization match ({candidate.name_order} order)")

            # Surname + given match (different order)
            en_parts = english_name.lower().split()
            if len(en_parts) >= 2:
                if (candidate.surname.lower() in en_parts and
                    candidate.given_name.lower() in en_parts):
                    return (True, candidate.confidence * 0.9, "Name parts match (different order)")

        # Fuzzy match - check if surname matches
        surname_kr = korean_name[0] if korean_name else ''
        surname_variants = KOREAN_SURNAMES.get(surname_kr, [])

        for variant in surname_variants:
            if variant.lower() in english_name.lower():
                return (True, 0.5, f"Surname match ({variant})")

        return (False, 0.0, "No match found")

    def add_verified_mapping(self, korean_name: str, english_name: str,
                             fie_id: Optional[str] = None,
                             fencingtracker_id: Optional[str] = None,
                             birth_year: Optional[int] = None,
                             weapon: Optional[str] = None):
        """Add a verified name mapping."""
        # Parse English name
        parts = english_name.split()
        if len(parts) >= 2:
            # Assume "Given Surname" or "SURNAME Given" format
            if parts[0].isupper() and len(parts[0]) > 2:
                # FIE format: SURNAME Given
                surname = parts[0].capitalize()
                given = ' '.join(parts[1:])
            else:
                # Western format: Given Surname
                given = parts[0]
                surname = ' '.join(parts[1:])
        else:
            surname = english_name
            given = ''

        self.name_mappings[korean_name] = {
            'en_name': english_name,
            'en_surname': surname,
            'en_given': given,
            'name_order': 'western',
            'confidence': 1.0,
            'source': 'manual_verified',
            'fie_id': fie_id,
            'fencingtracker_id': fencingtracker_id,
            'birth_year': birth_year,
            'weapon': weapon,
            'verified': True,
            'verified_date': datetime.now().isoformat()
        }
        self._save_name_mappings()

    def lookup_international_records(self, korean_name: str) -> List[InternationalRecord]:
        """Look up international records for a Korean player."""
        records = []

        # Get English name candidates
        en_name = self.get_english_name(korean_name)
        if not en_name:
            return records

        # Check if we have external IDs
        if en_name.external_id:
            # TODO: Fetch actual records from FIE/FencingTracker
            pass

        return records

    def close(self):
        """Clean up resources."""
        self.fencingtracker.close()
        self.fie.close()


# Test function
def test_name_conversion():
    """Test the name conversion functionality."""
    manager = InternationalDataManager()

    test_cases = [
        ('박소윤', 'Soyun Park'),
        ('공하이', 'Hai Gong'),
        ('송세라', 'SONG Sera'),
        ('김시우', None),  # Multiple people, no verified mapping
    ]

    print("=== 이름 변환 테스트 ===\n")

    for korean, expected in test_cases:
        result = manager.get_english_name(korean)
        print(f"한글: {korean}")
        if result:
            print(f"  영문: {result.full_name}")
            print(f"  신뢰도: {result.confidence:.2f}")
            print(f"  소스: {result.source}")
            if expected:
                is_match, conf, reason = manager.verify_name_match(korean, expected)
                print(f"  검증: {is_match} ({reason})")
        else:
            print("  영문: 변환 실패")
        print()

    manager.close()


if __name__ == "__main__":
    test_name_conversion()
