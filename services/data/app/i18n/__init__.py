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
]
