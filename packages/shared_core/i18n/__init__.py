"""
shared_core.i18n - FencingMind 공통 다국어 지원 모듈

모든 서브도메인이 공유하는 i18n 인프라:
- 7개 언어 지원 (ko, en, fr, it, ja, zh, tr)
- 언어별 테마 자동 결정 (ko/ja/zh → Light, en/fr/it/tr → Dark)
- 언어 감지 미들웨어
- 번역 매니저 (공유 + 서비스별 번역 병합)

Usage:
    # 서비스의 server.py에서
    from shared_core.i18n import LanguageMiddleware
    app.add_middleware(LanguageMiddleware)

    # 서비스의 router에서
    from shared_core.i18n import create_language_context
    context = create_language_context(request)

    # 서비스별 번역을 추가로 로드하려면
    from shared_core.i18n import TranslationManager
    i18n = TranslationManager(extra_dirs=[Path("app/i18n/translations")])
"""

from .constants import (
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    LANG_THEME_MAP,
    DEFAULT_THEME,
)
from .manager import (
    TranslationManager,
    get_translator,
    create_shared_i18n,
    get_global_i18n,
)
from .middleware import (
    get_language_from_request,
    LanguageMiddleware,
    create_language_context,
)

__all__ = [
    'SUPPORTED_LANGUAGES',
    'DEFAULT_LANGUAGE',
    'LANGUAGE_NAMES',
    'LANG_THEME_MAP',
    'DEFAULT_THEME',
    'TranslationManager',
    'get_translator',
    'create_shared_i18n',
    'get_global_i18n',
    'get_language_from_request',
    'LanguageMiddleware',
    'create_language_context',
]
