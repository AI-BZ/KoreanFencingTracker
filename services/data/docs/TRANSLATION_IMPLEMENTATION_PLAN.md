# Dynamic Content Translation Implementation Plan

## Overview
English pages (`/en/`) currently display Korean data without translation.
This document outlines the implementation plan to fix this issue.

## Current State

### Existing Infrastructure
1. **i18n System**: `app/i18n/` - JSON-based static translations (working)
2. **TranslationService**: `app/translation_service.py` - Dynamic content translation (exists but underutilized)
3. **DB Schema**: `translations` JSONB column exists on competitions, players, organizations

### Problem
- API endpoints don't accept `lang` parameter
- API returns original Korean names, not translated names
- Some records have empty `translations` field
- Pattern-based translations produce poor quality results

## Solution: Hybrid Approach

### Phase 1: API-Level Translation (Immediate)

#### 1.1 Add `lang` parameter to API endpoints

```python
# In server.py

@app.get("/api/events")
async def api_events(
    request: Request,  # Add this
    weapon: Optional[str] = None,
    gender: Optional[str] = None,
    age_group: Optional[str] = None,
    year: Optional[int] = None,
    event_type: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200)
):
    # Get language from request state (set by middleware)
    lang = getattr(request.state, 'lang', 'ko')

    # ... existing code ...

    # When creating EventSummary, use localized names
    events.append(EventSummary(
        # ...
        name=get_localized_event_name(event, lang),
        competition_name=get_localized_competition_name(comp_info, lang),
        # ...
    ))
```

#### 1.2 Create localization helper functions

```python
# In server.py or app/localization.py

def get_localized_competition_name(comp_info: Dict, lang: str) -> str:
    """Get competition name in specified language."""
    if lang == 'ko':
        return comp_info.get('comp_name', '') or comp_info.get('name', '')

    # Check translations field
    translations = comp_info.get('translations', {})
    if isinstance(translations, dict):
        lang_data = translations.get(lang, {})
        if isinstance(lang_data, dict) and lang_data.get('name'):
            return lang_data['name']

    # Fallback: generate translation on-the-fly
    ts = get_translation_service()
    korean_name = comp_info.get('comp_name', '') or comp_info.get('name', '')
    result = ts.translate_competition_name(korean_name)
    return result.get('en', {}).get('name', korean_name)

def get_localized_event_name(event: Dict, lang: str) -> str:
    """Get event name in specified language."""
    if lang == 'ko':
        return event.get('name', '')

    # Event names follow patterns, translate components
    # Example: "남자 플뢰레 고등부" -> "Men's Foil High School"
    return translate_event_name_components(event.get('name', ''), lang)

def translate_event_name_components(name: str, lang: str) -> str:
    """Translate event name component by component."""
    if lang != 'en':
        return name

    # Component mappings
    mappings = {
        '남자': "Men's",
        '여자': "Women's",
        '플뢰레': 'Foil',
        '에뻬': 'Epee',
        '사브르': 'Sabre',
        '초등부': 'Elementary',
        '중등부': 'Middle School',
        '고등부': 'High School',
        '대학부': 'University',
        '일반부': 'Senior',
        '개인': 'Individual',
        '단체': 'Team',
        # Age groups
        '1-2학년': 'Y8 (Grade 1-2)',
        '3-4학년': 'Y10 (Grade 3-4)',
        '5-6학년': 'Y12 (Grade 5-6)',
    }

    result = name
    for ko, en in sorted(mappings.items(), key=lambda x: -len(x[0])):
        result = result.replace(ko, en)

    return result
```

### Phase 2: Pre-populate Translations (Batch Job)

#### 2.1 Migration to populate translations

```sql
-- Run batch translation for competitions without translations
UPDATE competitions
SET translations = jsonb_build_object(
    'en', jsonb_build_object(
        'name', translate_competition_name_sql(comp_name),
        'verified', false,
        'source', 'auto',
        'updated_at', now()
    )
)
WHERE translations IS NULL OR translations = '{}';
```

#### 2.2 Python batch script

```python
# scripts/populate_translations.py

from app.translation_service import TranslationService
from supabase import create_client

async def populate_competition_translations():
    ts = TranslationService()
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Get competitions without translations
    result = supabase.table('competitions')\
        .select('id', 'comp_name', 'translations')\
        .execute()

    for comp in result.data:
        if not comp.get('translations') or comp['translations'] == {}:
            translation = ts.translate_competition_name(comp['comp_name'])

            supabase.table('competitions')\
                .update({'translations': translation})\
                .eq('id', comp['id'])\
                .execute()

            print(f"Translated: {comp['comp_name']} -> {translation}")
```

### Phase 3: Verified Translation Database (Long-term)

#### 3.1 Create verified translations table

```sql
CREATE TABLE verified_translations (
    id SERIAL PRIMARY KEY,
    entity_type VARCHAR(50) NOT NULL,  -- 'competition', 'organization', 'event_name'
    korean_text TEXT NOT NULL,
    english_text TEXT NOT NULL,
    verified_by VARCHAR(100),
    verified_at TIMESTAMP DEFAULT NOW(),
    notes TEXT,
    UNIQUE(entity_type, korean_text)
);

-- Initial seed data
INSERT INTO verified_translations (entity_type, korean_text, english_text, verified_by) VALUES
('competition', '회장배 전국펜싱선수권대회', 'KFA President''s Cup National Fencing Championship', 'system'),
('competition', '전국체육대회', 'National Sports Festival', 'system'),
('competition', '전국종별펜싱선수권대회', 'National Category Fencing Championship', 'system'),
('organization', '최병철펜싱클럽', 'Choi Byeongcheol Fencing Club', 'system'),
('organization', '서울체육고등학교', 'Seoul Physical Education High School', 'system');
```

#### 3.2 Update TranslationService to check verified first

```python
def translate_competition_name(self, korean_name: str) -> Dict:
    # 1. Check verified_translations table first
    verified = self._get_verified_translation('competition', korean_name)
    if verified:
        return {
            'en': {
                'name': verified['english_text'],
                'verified': True,
                'source': 'verified_db'
            }
        }

    # 2. Check inline VERIFIED_COMPETITION_MAPPINGS
    # 3. Pattern-based translation
    # 4. AI translation API (future)
```

### Phase 4: Real-time Translation API (Optional)

For unverified translations, integrate external translation API:

```python
import httpx

class TranslationService:
    async def translate_with_api(self, text: str, target_lang: str) -> str:
        """Use external API for high-quality translation."""
        # Option 1: Google Translate API
        # Option 2: DeepL API
        # Option 3: OpenAI GPT

        # Cache result in DB for future use
        pass
```

## Frontend Changes

### Template Updates

```html
<!-- In index.html -->
<script>
    // Pass language to API calls
    const currentLang = '{{ lang }}';

    async function loadEvents() {
        const params = new URLSearchParams();
        params.append('lang', currentLang);  // Add language parameter
        // ...
        const res = await fetch('/api/events?' + params.toString());
    }
</script>
```

### Event Card Display

```javascript
// Use translated names from API response
cardsDiv.innerHTML = data.events.map(event => `
    <div class="event-card">
        <div class="event-name">${event.name}</div>  <!-- Already localized by API -->
        <div class="event-meta">${event.competition_name}</div>  <!-- Already localized -->
    </div>
`).join('');
```

## Implementation Priority

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| 1 | Add `lang` to API endpoints | Low | High |
| 2 | Implement `get_localized_*` helpers | Medium | High |
| 3 | Batch populate translations | Medium | Medium |
| 4 | Expand VERIFIED_COMPETITION_MAPPINGS | Low | Medium |
| 5 | Create admin UI for translation management | High | Medium |
| 6 | Integrate external translation API | Medium | Low |

## Testing Checklist

- [ ] `/en/` page shows English competition names
- [ ] `/ko/` page shows Korean competition names (unchanged)
- [ ] API returns correct language based on request
- [ ] Fallback to Korean when translation unavailable
- [ ] Search works in both languages

## Files to Modify

1. `app/server.py` - Add lang parameter to API endpoints
2. `app/translation_service.py` - Enhance pattern translations
3. `templates/index.html` - Pass lang to API calls
4. `templates/base.html` - Ensure lang is available in JS context
