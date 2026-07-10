"""
Account Service - Language Middleware (shim)

Converged onto shared_core.i18n. `LanguageMiddleware` and
`create_language_context` are re-exported from shared_core so that existing
imports (`from app.i18n.middleware import ...`) keep working unchanged.

The middleware is registered in `app/server.py` with an account-merged
TranslationManager (shared translations + `app/i18n/translations/` via
extra_dirs), so request.state carries the merged translations and
create_language_context resolves account-specific keys correctly.
"""

from shared_core.i18n.middleware import (
    get_language_from_request,
    LanguageMiddleware,
    create_language_context,
)

__all__ = [
    "get_language_from_request",
    "LanguageMiddleware",
    "create_language_context",
]
