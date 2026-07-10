"""
Account Service - Internationalization (i18n) Module

JSON-based translation system with language detection middleware.
Supports ko (default) and en.
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
