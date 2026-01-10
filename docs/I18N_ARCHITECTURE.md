# Korean Fencing Tracker - Internationalization (i18n) Architecture

## 1. Overview

### Goals
- Support multiple languages (starting with Korean + English)
- SEO optimization with proper hreflang tags and language-specific URLs
- **Synchronization Rule**: When Korean content changes, all translations must be updated
- Minimal impact on existing codebase

### Supported Languages
| Code | Language | Priority | Status |
|------|----------|----------|--------|
| `ko` | Korean | Default | Existing |
| `en` | English | Phase 1 | New |
| `ja` | Japanese | Phase 2 | Planned |
| `zh` | Chinese | Phase 3 | Planned |

---

## 2. URL Structure (SEO Optimized)

### URL Pattern
```
/{lang}/{path}

Examples:
/ko/                    # Korean homepage
/en/                    # English homepage
/ko/rankings            # Korean rankings
/en/rankings            # English rankings
/ko/player/박소윤       # Korean player profile
/en/player/박소윤       # English player profile (same player name)
```

### SEO Headers
```html
<!-- On /ko/rankings -->
<html lang="ko">
<head>
    <link rel="canonical" href="https://fencing.example.com/ko/rankings">
    <link rel="alternate" hreflang="ko" href="https://fencing.example.com/ko/rankings">
    <link rel="alternate" hreflang="en" href="https://fencing.example.com/en/rankings">
    <link rel="alternate" hreflang="x-default" href="https://fencing.example.com/ko/rankings">
</head>
```

### Redirect Rules
```
/              → /ko/              (default language)
/rankings      → /ko/rankings      (legacy URL support)
/player/...    → /ko/player/...    (legacy URL support)
```

---

## 3. File Structure

```
app/
├── i18n/
│   ├── __init__.py           # i18n module init
│   ├── manager.py            # Translation manager
│   ├── middleware.py         # Language detection middleware
│   ├── validators.py         # Translation sync validator
│   └── translations/
│       ├── ko/
│       │   ├── common.json       # Navigation, buttons, labels
│       │   ├── player.json       # Player page strings
│       │   ├── competition.json  # Competition page strings
│       │   ├── rankings.json     # Rankings page strings
│       │   ├── club.json         # Club management strings
│       │   ├── auth.json         # Login/register strings
│       │   └── errors.json       # Error messages
│       └── en/
│           ├── common.json
│           ├── player.json
│           ├── competition.json
│           ├── rankings.json
│           ├── club.json
│           ├── auth.json
│           └── errors.json
│
templates/
├── base.html                 # Updated with i18n support
├── index.html                # Uses i18n functions
└── ...
```

---

## 4. Translation File Format

### Example: `translations/en/common.json`
```json
{
  "_meta": {
    "language": "en",
    "version": "1.0.0",
    "last_updated": "2025-01-06T00:00:00Z"
  },
  "site": {
    "title": "Korean Fencing Tracker",
    "description": "Track and analyze your fencing competition records"
  },
  "nav": {
    "home": "Home",
    "search": "Search",
    "rankings": "Rankings",
    "fencinglab": "FencingLab",
    "login": "Login",
    "logout": "Logout",
    "profile": "Profile"
  },
  "search": {
    "placeholder": "Search player or team...",
    "button": "Search",
    "reset": "Reset",
    "no_results": "No results found",
    "results_count": "{count} results found"
  },
  "filters": {
    "season": "Season",
    "weapon": "Weapon",
    "gender": "Gender",
    "age_group": "Age Group",
    "event_type": "Event Type",
    "all": "All"
  },
  "weapons": {
    "foil": "Foil",
    "epee": "Epee",
    "sabre": "Sabre"
  },
  "gender": {
    "male": "Men's",
    "female": "Women's"
  },
  "pagination": {
    "previous": "Previous",
    "next": "Next",
    "page": "Page {current} of {total}"
  }
}
```

### Example: `translations/ko/common.json`
```json
{
  "_meta": {
    "language": "ko",
    "version": "1.0.0",
    "last_updated": "2025-01-06T00:00:00Z"
  },
  "site": {
    "title": "Korean Fencing Tracker",
    "description": "나의 펜싱 경기 기록을 확인하고 분석하세요"
  },
  "nav": {
    "home": "홈",
    "search": "검색",
    "rankings": "Ranking",
    "fencinglab": "FencingLab",
    "login": "로그인",
    "logout": "로그아웃",
    "profile": "프로필"
  },
  "search": {
    "placeholder": "선수/소속 검색...",
    "button": "검색",
    "reset": "초기화",
    "no_results": "검색 결과가 없습니다",
    "results_count": "{count}개의 결과"
  }
}
```

---

## 5. Translation Synchronization System

### Sync Validation Rule
**CRITICAL**: When `ko/*.json` is modified, `en/*.json` (and other languages) MUST have the same keys.

### Validator Script: `scripts/validate_translations.py`
```python
def validate_translation_sync():
    """
    Checks that all language files have identical keys.
    Run this in CI/CD and before deployment.
    """
    base_lang = 'ko'
    target_langs = ['en', 'ja', 'zh']

    for file in base_translation_files:
        base_keys = extract_all_keys(load_json(f'ko/{file}'))

        for lang in target_langs:
            target_keys = extract_all_keys(load_json(f'{lang}/{file}'))
            missing = base_keys - target_keys
            extra = target_keys - base_keys

            if missing:
                raise TranslationSyncError(
                    f"Missing keys in {lang}/{file}: {missing}"
                )
```

### Git Pre-commit Hook
```bash
#!/bin/bash
# .git/hooks/pre-commit

# Check if translation files were modified
if git diff --cached --name-only | grep -q "translations/"; then
    python scripts/validate_translations.py
    if [ $? -ne 0 ]; then
        echo "Translation sync validation failed!"
        exit 1
    fi
fi
```

---

## 6. Backend Implementation

### Language Manager: `app/i18n/manager.py`
```python
from pathlib import Path
import json
from functools import lru_cache
from typing import Dict, Any, Optional

SUPPORTED_LANGUAGES = ['ko', 'en']
DEFAULT_LANGUAGE = 'ko'

class TranslationManager:
    def __init__(self):
        self.translations: Dict[str, Dict] = {}
        self.load_all_translations()

    def load_all_translations(self):
        base_path = Path(__file__).parent / 'translations'
        for lang in SUPPORTED_LANGUAGES:
            self.translations[lang] = {}
            lang_path = base_path / lang
            for json_file in lang_path.glob('*.json'):
                namespace = json_file.stem
                with open(json_file, 'r', encoding='utf-8') as f:
                    self.translations[lang][namespace] = json.load(f)

    def get(self, key: str, lang: str = DEFAULT_LANGUAGE,
            default: str = None, **kwargs) -> str:
        """
        Get translation by dot-notation key.
        Example: get('nav.login', 'en') -> 'Login'
        """
        parts = key.split('.')
        namespace = parts[0]
        path = parts[1:]

        value = self.translations.get(lang, {}).get(namespace, {})
        for part in path:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                break

        if value is None:
            # Fallback to default language
            value = self.translations.get(DEFAULT_LANGUAGE, {}).get(namespace, {})
            for part in path:
                if isinstance(value, dict):
                    value = value.get(part)

        if value is None:
            return default or key

        # Format with kwargs if provided
        if kwargs and isinstance(value, str):
            value = value.format(**kwargs)

        return value

# Global instance
i18n = TranslationManager()
```

### Language Middleware: `app/i18n/middleware.py`
```python
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

class LanguageMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Extract language from URL path
        path = request.url.path
        lang = DEFAULT_LANGUAGE

        if path.startswith('/en/'):
            lang = 'en'
        elif path.startswith('/ko/'):
            lang = 'ko'

        # Store in request state
        request.state.lang = lang
        request.state.i18n = lambda key, **kw: i18n.get(key, lang, **kw)

        response = await call_next(request)
        return response
```

### Route Registration: `app/server.py`
```python
from app.i18n.middleware import LanguageMiddleware
from app.i18n.manager import i18n, SUPPORTED_LANGUAGES

app.add_middleware(LanguageMiddleware)

# Language-aware routes
@app.get("/{lang}/", response_class=HTMLResponse)
async def index_i18n(request: Request, lang: str = "ko"):
    if lang not in SUPPORTED_LANGUAGES:
        return RedirectResponse(f"/ko/")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "lang": lang,
            "t": lambda key, **kw: i18n.get(key, lang, **kw),
            "supported_langs": SUPPORTED_LANGUAGES,
        }
    )

# Legacy route redirects
@app.get("/", response_class=HTMLResponse)
async def index_redirect():
    return RedirectResponse("/ko/", status_code=302)
```

---

## 7. Template Integration

### Updated `base.html`
```jinja2
<!DOCTYPE html>
<html lang="{{ lang }}">
<head>
    <meta charset="UTF-8">
    <title>{% block title %}{{ t('site.title') }}{% endblock %}</title>
    <meta name="description" content="{{ t('site.description') }}">

    <!-- SEO: hreflang tags -->
    {% for l in supported_langs %}
    <link rel="alternate" hreflang="{{ l }}"
          href="{{ request.url.scheme }}://{{ request.url.netloc }}/{{ l }}{{ request.url.path.replace('/' + lang, '') }}">
    {% endfor %}
    <link rel="alternate" hreflang="x-default"
          href="{{ request.url.scheme }}://{{ request.url.netloc }}/ko{{ request.url.path.replace('/' + lang, '') }}">
</head>
<body>
    <nav>
        <a href="/{{ lang }}/" class="logo-text">{{ t('site.title') }}</a>
        <a href="/{{ lang }}/rankings">{{ t('nav.rankings') }}</a>
        <a href="/{{ lang }}/auth/login">{{ t('nav.login') }}</a>

        <!-- Language Switcher -->
        <div class="lang-switcher">
            {% for l in supported_langs %}
            <a href="/{{ l }}{{ request.url.path.replace('/' + lang, '') }}"
               class="lang-btn {% if l == lang %}active{% endif %}">
                {{ l.upper() }}
            </a>
            {% endfor %}
        </div>
    </nav>

    <main>
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

### Example: Search Form Translation
```jinja2
<!-- Before -->
<input type="text" placeholder="선수/소속 검색...">
<button>검색</button>

<!-- After -->
<input type="text" placeholder="{{ t('search.placeholder') }}">
<button>{{ t('search.button') }}</button>
```

---

## 8. JavaScript i18n

### Frontend Translation Support
```javascript
// static/js/i18n.js
class I18n {
    constructor(translations, lang = 'ko') {
        this.translations = translations;
        this.lang = lang;
    }

    t(key, params = {}) {
        const keys = key.split('.');
        let value = this.translations;

        for (const k of keys) {
            value = value?.[k];
        }

        if (!value) return key;

        // Replace {param} placeholders
        return value.replace(/\{(\w+)\}/g, (_, name) =>
            params[name] ?? `{${name}}`
        );
    }
}

// Initialize from server-rendered translations
const i18n = new I18n(window.__I18N__ || {}, '{{ lang }}');
```

### Template Integration
```jinja2
<script>
    window.__I18N__ = {{ translations | tojson | safe }};
    window.__LANG__ = '{{ lang }}';
</script>
<script src="/static/js/i18n.js"></script>
```

---

## 9. Implementation Phases

### Phase 1: Infrastructure (Day 1)
- [ ] Create `app/i18n/` module structure
- [ ] Implement `TranslationManager`
- [ ] Create initial translation files (ko, en)
- [ ] Add language middleware

### Phase 2: Core Pages (Day 2-3)
- [ ] Update `base.html` with i18n
- [ ] Update `index.html`
- [ ] Update `rankings.html`
- [ ] Update `player_profile.html`
- [ ] Update `competition.html`

### Phase 3: Routes & SEO (Day 4)
- [ ] Add language-prefixed routes
- [ ] Implement legacy URL redirects
- [ ] Add hreflang tags
- [ ] Add language switcher UI

### Phase 4: Remaining Pages (Day 5-6)
- [ ] Update auth templates
- [ ] Update club management templates
- [ ] Update FencingLab templates

### Phase 5: Validation & Testing (Day 7)
- [ ] Create translation sync validator
- [ ] Add pre-commit hook
- [ ] Test all pages in both languages
- [ ] SEO validation

---

## 10. Translation Workflow

### Adding New Strings
1. Add key to `ko/*.json` first (source language)
2. Run `python scripts/validate_translations.py`
3. Add translations to `en/*.json` (and other languages)
4. Run validator again to confirm sync
5. Commit all translation files together

### Updating Existing Strings
1. Modify `ko/*.json`
2. Update `en/*.json` with new translation
3. Update version in `_meta.last_updated`
4. Commit all changes together

### CI/CD Integration
```yaml
# .github/workflows/i18n-check.yml
name: Translation Sync Check

on:
  pull_request:
    paths:
      - 'app/i18n/translations/**'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Validate translations
        run: python scripts/validate_translations.py
```

---

## 11. Data Translation Strategy

### Static Content
- UI labels, buttons, messages → JSON translation files
- Error messages → JSON translation files

### Dynamic Content (Database)
- Player names → Keep original (Korean names shown as-is)
- Team names → Optional translation mapping in separate file
- Competition names → Optional translation mapping

### Fencing Terminology
```json
// translations/en/terminology.json
{
  "weapons": {
    "플러레": "Foil",
    "에뻬": "Epee",
    "사브르": "Sabre"
  },
  "events": {
    "개인": "Individual",
    "단체": "Team"
  },
  "rounds": {
    "예선": "Pool",
    "본선": "DE",
    "결승": "Final",
    "준결승": "Semi-final",
    "8강": "Quarter-final"
  }
}
```

---

## 12. Summary

| Feature | Implementation |
|---------|---------------|
| URL Structure | `/{lang}/path` (SEO optimized) |
| Default Language | Korean (`ko`) |
| Translation Storage | JSON files per namespace |
| Backend Framework | Custom `TranslationManager` |
| Frontend Framework | Lightweight custom `I18n` class |
| Sync Validation | Automated script + pre-commit hook |
| SEO | hreflang tags on all pages |

### Key Files to Create
1. `app/i18n/__init__.py`
2. `app/i18n/manager.py`
3. `app/i18n/middleware.py`
4. `app/i18n/translations/ko/*.json`
5. `app/i18n/translations/en/*.json`
6. `scripts/validate_translations.py`
7. `static/js/i18n.js`

### Success Criteria
- [ ] All pages accessible at `/en/` and `/ko/` paths
- [ ] hreflang tags present on all pages
- [ ] Language switcher functional
- [ ] Translation sync validator passes
- [ ] No hardcoded Korean strings in templates
