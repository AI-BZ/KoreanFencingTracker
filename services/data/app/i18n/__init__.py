"""
Korean Fencing Tracker - Internationalization (i18n) Module

This module provides multi-language support with:
- JSON-based translation files
- Language detection middleware
- SEO-optimized URL structure (/{lang}/path)
- Translation synchronization validation
"""

from .manager import (
    TranslationManager,
    i18n,
    get_translator,
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
)
from .middleware import (
    get_language_from_request,
    LanguageMiddleware,
    create_language_context,
)
from .auto_translate import make_auto_translator, get_js_translations
from .event_translator import translate_event_name
from .competition_names import translate_competition_name, get_js_competition_names

__all__ = [
    'TranslationManager',
    'i18n',
    'get_translator',
    'SUPPORTED_LANGUAGES',
    'DEFAULT_LANGUAGE',
    'LANGUAGE_NAMES',
    'get_language_from_request',
    'LanguageMiddleware',
    'create_language_context',
    'make_auto_translator',
    'get_js_translations',
    'translate_event_name',
    'translate_competition_name',
    'get_js_competition_names',
]
