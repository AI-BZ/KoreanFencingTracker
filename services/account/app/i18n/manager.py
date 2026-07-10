"""
Account Service - Translation Manager (shim)

Converged onto shared_core.i18n. This module now re-exports the shared
TranslationManager and helpers so that any legacy imports of
`app.i18n.manager.*` keep working. Account-specific translations live in
`app/i18n/translations/` and are merged into the shared translations via
`create_shared_i18n(extra_dirs=[...])` in `app/server.py`.
"""

from shared_core.i18n.constants import (
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    LANG_THEME_MAP,
    DEFAULT_THEME,
)
from shared_core.i18n.manager import (
    TranslationManager,
    get_translator,
    create_shared_i18n,
    get_global_i18n,
)

# Backward-compat module global. Nothing in account imports this directly, but
# older code paths expected `app.i18n.manager.i18n` to exist. The request-scoped
# translator/i18n_data provided by LanguageMiddleware (which is wired with the
# account-merged instance in server.py) is what templates actually use.
i18n = get_global_i18n()

__all__ = [
    "TranslationManager",
    "get_translator",
    "create_shared_i18n",
    "get_global_i18n",
    "i18n",
    "SUPPORTED_LANGUAGES",
    "DEFAULT_LANGUAGE",
    "LANGUAGE_NAMES",
    "LANG_THEME_MAP",
    "DEFAULT_THEME",
]
