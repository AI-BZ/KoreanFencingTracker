"""
Algorithmic event name translator for structured Korean fencing event names.

Korean event names from KFF follow patterns like:
  - "여중 에뻬(개)" = Women's Middle School Epee (Individual)
  - "남고 사브르(단)" = Men's High School Sabre (Team)
  - "남자 플뢰레(개인)" = Men's Foil (Individual)
  - "U13 남자 에뻬" = U13 Men's Epee
  - "남자 중등부 에뻬 개인전" = Men's Middle School Epee Individual
  - "17세이하부 남자 사브르(개)" = U17 Men's Sabre Individual
  - "고등부 남자 사브르(개)" = Men's High School Sabre Individual
  - "초등부(1-3학년) 남자 사브르(개)" = Men's Elem. Grade 1-3 Sabre Individual

This module parses the components and reassembles them per language.
"""

import re
from typing import Optional

# ============================================================================
# Component translation tables: Korean token -> {lang: translation}
# ============================================================================

GENDER = {
    '여': {'en': "Women's", 'fr': 'Dames', 'it': 'Femminile', 'ja': '女子', 'zh': '女子', 'tr': 'Kadın'},
    '남': {'en': "Men's", 'fr': 'Hommes', 'it': 'Maschile', 'ja': '男子', 'zh': '男子', 'tr': 'Erkek'},
    '혼성': {'en': 'Mixed', 'fr': 'Mixte', 'it': 'Misto', 'ja': '混合', 'zh': '混合', 'tr': 'Karma'},
}

LEVEL = {
    '초': {'en': 'Elementary', 'fr': 'Primaire', 'it': 'Elementare', 'ja': '小学', 'zh': '小学', 'tr': 'İlkokul'},
    '중': {'en': 'Middle School', 'fr': 'Collège', 'it': 'Scuola Media', 'ja': '中学', 'zh': '初中', 'tr': 'Ortaokul'},
    '고': {'en': 'High School', 'fr': 'Lycée', 'it': 'Liceo', 'ja': '高校', 'zh': '高中', 'tr': 'Lise'},
    '대': {'en': 'University', 'fr': 'Université', 'it': 'Università', 'ja': '大学', 'zh': '大学', 'tr': 'Üniversite'},
    '실': {'en': 'Professional', 'fr': 'Professionnel', 'it': 'Professionista', 'ja': '実業', 'zh': '专业', 'tr': 'Profesyonel'},
    '일': {'en': 'Open', 'fr': 'Open', 'it': 'Open', 'ja': '一般', 'zh': '公开', 'tr': 'Açık'},
}

# Longer-form level names (from different event name formats)
LEVEL_LONG = {
    '초등부': '초', '초등': '초', '초학': '초',
    '중등부': '중', '중등': '중', '중학부': '중', '중학': '중',
    '고등부': '고', '고등': '고', '고교부': '고', '고학': '고',
    '대학부': '대', '대학': '대',
    '실업부': '실', '실업': '실',
    '일반부': '일', '일반': '일', '시니어': '일',
    '엘리트부': '일', '엘리트': '일',
}

WEAPON = {
    '플뢰레': {'en': 'Foil', 'fr': 'Fleuret', 'it': 'Fioretto', 'ja': 'フルーレ', 'zh': '花剑', 'tr': 'Flöre'},
    '에뻬': {'en': 'Epee', 'fr': 'Épée', 'it': 'Spada', 'ja': 'エペ', 'zh': '重剑', 'tr': 'Epe'},
    '에페': {'en': 'Epee', 'fr': 'Épée', 'it': 'Spada', 'ja': 'エペ', 'zh': '重剑', 'tr': 'Epe'},
    '플러레': {'en': 'Foil', 'fr': 'Fleuret', 'it': 'Fioretto', 'ja': 'フルーレ', 'zh': '花剑', 'tr': 'Flöre'},
    '플러러': {'en': 'Foil', 'fr': 'Fleuret', 'it': 'Fioretto', 'ja': 'フルーレ', 'zh': '花剑', 'tr': 'Flöre'},
    '사브르': {'en': 'Sabre', 'fr': 'Sabre', 'it': 'Sciabola', 'ja': 'サーブル', 'zh': '佩剑', 'tr': 'Kılıç'},
}

EVENT_TYPE = {
    '개': {'en': 'Individual', 'fr': 'Individuel', 'it': 'Individuale', 'ja': '個人', 'zh': '个人', 'tr': 'Bireysel'},
    '단': {'en': 'Team', 'fr': 'Équipe', 'it': 'Squadra', 'ja': '団体', 'zh': '团体', 'tr': 'Takım'},
    '개인': {'en': 'Individual', 'fr': 'Individuel', 'it': 'Individuale', 'ja': '個人', 'zh': '个人', 'tr': 'Bireysel'},
    '단체': {'en': 'Team', 'fr': 'Équipe', 'it': 'Squadra', 'ja': '団体', 'zh': '团体', 'tr': 'Takım'},
    '개인전': {'en': 'Individual', 'fr': 'Individuel', 'it': 'Individuale', 'ja': '個人', 'zh': '个人', 'tr': 'Bireysel'},
    '단체전': {'en': 'Team', 'fr': 'Équipe', 'it': 'Squadra', 'ja': '団体', 'zh': '团体', 'tr': 'Takım'},
}

# Elementary sub-grades
ELEM_GRADES = {
    '초등저학년': {'en': 'Elem. Lower', 'fr': 'Primaire inférieur', 'it': 'Elem. Inferiore', 'ja': '小学低学年', 'zh': '小学低年级', 'tr': 'İlkokul Alt'},
    '초등1-2학년': {'en': 'Elem. Grade 1-2', 'fr': 'Primaire 1-2', 'it': 'Elem. 1-2', 'ja': '小学1-2年', 'zh': '小学1-2年级', 'tr': 'İlkokul 1-2'},
    '초등3-4학년': {'en': 'Elem. Grade 3-4', 'fr': 'Primaire 3-4', 'it': 'Elem. 3-4', 'ja': '小学3-4年', 'zh': '小学3-4年级', 'tr': 'İlkokul 3-4'},
    '초등5-6학년': {'en': 'Elem. Grade 5-6', 'fr': 'Primaire 5-6', 'it': 'Elem. 5-6', 'ja': '小学5-6年', 'zh': '小学5-6年级', 'tr': 'İlkokul 5-6'},
    '1-2학년': {'en': 'Grade 1-2', 'fr': '1-2 année', 'it': '1-2 anno', 'ja': '1-2年', 'zh': '1-2年级', 'tr': '1-2. Sınıf'},
    '1-3학년': {'en': 'Grade 1-3', 'fr': '1-3 année', 'it': '1-3 anno', 'ja': '1-3年', 'zh': '1-3年级', 'tr': '1-3. Sınıf'},
    '3-4학년': {'en': 'Grade 3-4', 'fr': '3-4 année', 'it': '3-4 anno', 'ja': '3-4年', 'zh': '3-4年级', 'tr': '3-4. Sınıf'},
    '4-6학년': {'en': 'Grade 4-6', 'fr': '4-6 année', 'it': '4-6 anno', 'ja': '4-6年', 'zh': '4-6年级', 'tr': '4-6. Sınıf'},
    '5-6학년': {'en': 'Grade 5-6', 'fr': '5-6 année', 'it': '5-6 anno', 'ja': '5-6年', 'zh': '5-6年级', 'tr': '5-6. Sınıf'},
}

# Shared weapon regex fragment (all known weapon name variants)
_W = r'플뢰레|에뻬|에페|플러레|플러러|사브르'

# ============================================================================
# Parser: extract components from Korean event name
# ============================================================================

# Compact format: "여중 에뻬(개)" or "남고 사브르(단)" or "남초 플러레(개)(1-3학년)"
_RE_COMPACT = re.compile(
    r'^([남여])'               # gender (1 char)
    r'([초중고대실일])'         # level (1 char)
    r'\s+'                     # space
    r'(' + _W + r')'           # weapon
    r'(?:\(([개단])\))?'       # optional event type in parens
    r'(?:\((\d+[~-]\d+)학년\))?' # optional grade range suffix
    r'$'
)

# Age-under format: "17세이하부 남자 사브르(개)" or "9세이하부 여자 에뻬(개)"
_RE_AGE_UNDER = re.compile(
    r'^(\d+)세이하부'           # age number + 세이하부
    r'\s+'
    r'(남자?|여자?|혼성)'       # gender
    r'\s+'
    r'(' + _W + r')'           # weapon
    r'(?:\(?([개단](?:인|체)?(?:전)?)\)?)?'  # optional event type
    r'$'
)

# Elementary with grade range: "초등부(1-3학년) 남자 사브르(개)" or "초등부 1(1~3학년) 남자 플러레"
_RE_ELEM_GRADE = re.compile(
    r'^초등부\s*\d?\(?(\d+[~-]\d+)학년\)'  # grade range (1-3, 4~6, etc.)
    r'\s+'
    r'(남자?|여자?|혼성)'           # gender
    r'\s+'
    r'(' + _W + r')'               # weapon
    r'(?:\(?([개단](?:인|체)?(?:전)?)\)?)?'  # optional event type
    r'$'
)

# Level with age qualifier: "엘리트부(만40세이상) 남자 플러레"
_RE_LEVEL_AGE = re.compile(
    r'^(엘리트부|일반부|시니어)\(만?(\d+)세이상\)'  # level + age qualifier
    r'\s+'
    r'(남자?|여자?|혼성)'       # gender
    r'\s+'
    r'(' + _W + r')'           # weapon
    r'(?:\(?([개단](?:인|체)?(?:전)?)\)?)?'  # optional event type
    r'$'
)

# Level-first format: "고등부 남자 사브르(개)" or "엘리트부 여자 에뻬(개)"
_RE_LEVEL_FIRST = re.compile(
    r'^(초등[저중고]?부?|중등부?|중학부?|고등부?|고교부?|대학부?|일반부?|실업부?|엘리트부?|시니어)'
    r'\s+'
    r'(남자?|여자?|혼성)'       # gender
    r'\s+'
    r'(' + _W + r')'           # weapon
    r'(?:\(?([개단](?:인|체)?(?:전)?)\)?)?'  # optional event type
    r'$'
)

# Long format: "남자 플뢰레(개인)" or "여자 사브르(단체)"
_RE_LONG_WEAPON_TYPE = re.compile(
    r'^(남자?|여자?|혼성)'     # gender
    r'\s+'
    r'(' + _W + r')'           # weapon
    r'(?:\(([개단](?:인|체)?(?:전)?)\))?'  # optional event type in parens
    r'$'
)

# Full format: "남자 중등부 에뻬 개인전 전문"
_RE_FULL = re.compile(
    r'^(남자?|여자?|혼성)'     # gender
    r'\s+'
    r'(초등[저중고]?부?|중등부?|중학부?|고등부?|고교부?|대학부?|일반부?|실업부?|엘리트부?|시니어)'  # level
    r'\s+'
    r'(' + _W + r')'           # weapon
    r'(?:\s+(개인전?|단체전?))?'  # optional event type
    r'(?:\s+(전문|동호인))?'    # optional category
    r'$'
)

# International format: "U13 남자 에뻬"
_RE_INTERNATIONAL = re.compile(
    r'^(U\d+)'                 # age code
    r'\s+'
    r'(남자?|여자?|혼성)'      # gender
    r'\s+'
    r'(' + _W + r')'           # weapon
    r'(?:\s*(개인전?|단체전?))?'
    r'$'
)


def _normalize_name(name: str) -> str:
    """Normalize common data quality issues in event names."""
    # Fix missing closing parentheses: "에뻬(개" -> "에뻬(개)"
    open_count = name.count('(')
    close_count = name.count(')')
    if open_count > close_count:
        name += ')' * (open_count - close_count)
    return name


def _parse_event_name(name_ko: str) -> Optional[dict]:
    """
    Parse Korean event name into components.

    Returns dict with keys: gender, level, weapon, event_type, u_age, elem_grade, category
    or None if the name doesn't match any known pattern.
    """
    if not name_ko:
        return None

    name = _normalize_name(name_ko.strip())

    # Try compact format: "여중 에뻬(개)" or "남초 플러레(개)(1-3학년)"
    m = _RE_COMPACT.match(name)
    if m:
        return {
            'gender': m.group(1),
            'level': m.group(2),
            'weapon': m.group(3),
            'event_type': m.group(4) or '',
            'u_age': '',
            'elem_grade': m.group(5) or '',
            'category': '',
        }

    # Try age-under format: "17세이하부 남자 사브르(개)"
    m = _RE_AGE_UNDER.match(name)
    if m:
        return {
            'gender': m.group(2).rstrip('자'),
            'level': '',
            'weapon': m.group(3),
            'event_type': m.group(4) or '',
            'u_age': f'U{m.group(1)}',
            'elem_grade': '',
            'category': '',
        }

    # Try international format: "U13 남자 에뻬"
    m = _RE_INTERNATIONAL.match(name)
    if m:
        return {
            'gender': m.group(2).rstrip('자'),
            'level': '',
            'weapon': m.group(3),
            'event_type': m.group(4) or '',
            'u_age': m.group(1),
            'elem_grade': '',
            'category': '',
        }

    # Try elementary with grade: "초등부(1-3학년) 남자 사브르(개)"
    m = _RE_ELEM_GRADE.match(name)
    if m:
        grade_range = m.group(1).replace('~', '-')
        return {
            'gender': m.group(2).rstrip('자'),
            'level': '초',
            'weapon': m.group(3),
            'event_type': m.group(4) or '',
            'u_age': '',
            'elem_grade': grade_range,
            'category': '',
        }

    # Try level with age qualifier: "엘리트부(만40세이상) 남자 플러레"
    m = _RE_LEVEL_AGE.match(name)
    if m:
        age = m.group(2)
        level_long = m.group(1)
        level_key = LEVEL_LONG.get(level_long, '일')
        return {
            'gender': m.group(3).rstrip('자'),
            'level': level_key,
            'weapon': m.group(4),
            'event_type': m.group(5) or '',
            'u_age': f'{age}+',
            'elem_grade': '',
            'category': '',
        }

    # Try level-first format: "고등부 남자 사브르(개)"
    m = _RE_LEVEL_FIRST.match(name)
    if m:
        level_long = m.group(1)
        level_key = LEVEL_LONG.get(level_long, '')
        return {
            'gender': m.group(2).rstrip('자'),
            'level': level_key,
            'weapon': m.group(3),
            'event_type': m.group(4) or '',
            'u_age': '',
            'elem_grade': '',
            'category': '',
        }

    # Try full format: "남자 중등부 에뻬 개인전"
    m = _RE_FULL.match(name)
    if m:
        gender_raw = m.group(1).rstrip('자')
        level_long = m.group(2)
        level_key = LEVEL_LONG.get(level_long, '')
        return {
            'gender': gender_raw,
            'level': level_key,
            'weapon': m.group(3),
            'event_type': m.group(4) or '',
            'u_age': '',
            'elem_grade': '',
            'category': m.group(5) or '',
        }

    # Try long weapon+type format: "남자 플뢰레(개인)"
    m = _RE_LONG_WEAPON_TYPE.match(name)
    if m:
        gender_raw = m.group(1).rstrip('자')
        et_raw = m.group(3) or ''
        return {
            'gender': gender_raw,
            'level': '',
            'weapon': m.group(2),
            'event_type': et_raw,
            'u_age': '',
            'elem_grade': '',
            'category': '',
        }

    return None


# ============================================================================
# Assembler: build translated event name from components
# ============================================================================

def _get(table: dict, key: str, lang: str) -> str:
    """Look up a translation from a component table."""
    entry = table.get(key)
    if entry is None:
        return ''
    return entry.get(lang, entry.get('en', ''))


def _assemble(parts: dict, lang: str) -> str:
    """
    Assemble translated event name from parsed parts.

    Word order by language:
      en/fr/it/tr: Gender Level Weapon EventType    e.g. "Women's Middle School Epee Individual"
      ja:          Gender+Level Weapon EventType     e.g. "女子中学 エペ 個人"
      zh:          Gender+Level Weapon EventType     e.g. "女子初中 重剑 个人"
      ko:          (not used, returns original)
    """
    gender = _get(GENDER, parts['gender'], lang)
    level = _get(LEVEL, parts['level'], lang)
    weapon = _get(WEAPON, parts['weapon'], lang)
    event_type = _get(EVENT_TYPE, parts['event_type'], lang)
    u_age = parts.get('u_age', '')
    elem_grade = parts.get('elem_grade', '')

    # Override level with elementary grade translation when present
    if elem_grade:
        grade_key = f'{elem_grade}학년'
        grade_entry = ELEM_GRADES.get(grade_key)
        if grade_entry:
            grade_text = grade_entry.get(lang, grade_entry.get('en', ''))
        else:
            # Dynamic fallback for unlisted grade ranges
            _templates = {
                'en': f'Grade {elem_grade}', 'fr': f'{elem_grade} année',
                'it': f'{elem_grade} anno', 'ja': f'{elem_grade}年',
                'zh': f'{elem_grade}年级', 'tr': f'{elem_grade}. Sınıf',
            }
            grade_text = _templates.get(lang, _templates['en'])

        if lang in ('ja', 'zh'):
            level = _get(LEVEL, '초', lang) + grade_text  # e.g. "小学1-3年"
        else:
            level = _get(LEVEL, '초', lang) + ' ' + grade_text  # e.g. "Elementary Grade 1-3"

    if lang in ('ja', 'zh'):
        # CJK order: gender+level combined, then weapon, then event_type
        prefix = gender + level  # e.g. "女子中学"
        tokens = [t for t in [u_age, prefix, weapon, event_type] if t]
        return ' '.join(tokens)

    # Western languages: Gender Level Weapon (EventType)
    tokens = [t for t in [u_age, gender, level, weapon, event_type] if t]
    return ' '.join(tokens)


# ============================================================================
# Public API
# ============================================================================

def translate_event_name(name_ko: str, lang: str) -> str:
    """
    Translate a Korean fencing event name to the target language.

    Args:
        name_ko: Korean event name (e.g. "여중 에뻬(개)")
        lang: Target language code ('ko', 'en', 'fr', 'it', 'ja', 'zh', 'tr')

    Returns:
        Translated event name, or the original Korean if parsing fails
        or lang is 'ko'.

    Examples:
        >>> translate_event_name("여중 에뻬(개)", "en")
        "Women's Middle School Epee Individual"
        >>> translate_event_name("남고 사브르(단)", "ja")
        "男子高校 サーブル 団体"
        >>> translate_event_name("남자 플뢰레(개인)", "fr")
        "Hommes Fleuret Individuel"
        >>> translate_event_name("17세이하부 남자 사브르(개)", "en")
        "U17 Men's Sabre Individual"
        >>> translate_event_name("고등부 남자 사브르(개)", "en")
        "Men's High School Sabre Individual"
        >>> translate_event_name("초등부(1-3학년) 남자 사브르(개)", "en")
        "Men's Elementary Grade 1-3 Sabre Individual"
    """
    if lang == 'ko' or not name_ko:
        return name_ko

    parts = _parse_event_name(name_ko)
    if parts is None:
        # Can't parse -> return original
        return name_ko

    return _assemble(parts, lang)
