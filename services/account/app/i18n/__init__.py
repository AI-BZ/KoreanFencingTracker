"""
Account Service - Internationalization (i18n) Module

Converged onto shared_core.i18n. This package is now a thin shim: shared
infrastructure (7 languages, LANG_THEME_MAP, LanguageMiddleware,
create_language_context) plus account-specific translations under
`translations/` merged via extra_dirs in `app/server.py`.
"""

from .manager import (
    TranslationManager,
    i18n,
    get_translator,
    create_shared_i18n,
    get_global_i18n,
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    LANG_THEME_MAP,
    DEFAULT_THEME,
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
    'create_shared_i18n',
    'get_global_i18n',
    'SUPPORTED_LANGUAGES',
    'DEFAULT_LANGUAGE',
    'LANGUAGE_NAMES',
    'LANG_THEME_MAP',
    'DEFAULT_THEME',
    'get_language_from_request',
    'LanguageMiddleware',
    'create_language_context',
]
