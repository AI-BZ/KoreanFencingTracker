"""
Language Detection Middleware for Korean Fencing Tracker

Detects language from:
1. URL path prefix (/{lang}/...)
2. Cookie
3. Accept-Language header
4. Default to Korean
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from .manager import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, LANGUAGE_NAMES, i18n, get_translator


def get_language_from_request(request: Request) -> str:
    """
    Detect language from request.

    Priority:
    1. URL path prefix (/en/, /ko/)
    2. Cookie (lang)
    3. Accept-Language header
    4. Default (ko)
    """
    path = request.url.path

    # 1. Check URL path prefix
    for lang in SUPPORTED_LANGUAGES:
        if path.startswith(f'/{lang}/') or path == f'/{lang}':
            return lang

    # 2. Check cookie
    lang_cookie = request.cookies.get('lang')
    if lang_cookie in SUPPORTED_LANGUAGES:
        return lang_cookie

    # 3. Check Accept-Language header
    accept_lang = request.headers.get('accept-language', '')
    for lang in SUPPORTED_LANGUAGES:
        if lang in accept_lang.lower():
            return lang

    # 4. Default
    return DEFAULT_LANGUAGE


def get_path_without_lang(path: str) -> str:
    """Remove language prefix from path."""
    for lang in SUPPORTED_LANGUAGES:
        if path.startswith(f'/{lang}/'):
            return path[len(f'/{lang}'):]
        elif path == f'/{lang}':
            return '/'
    return path


def get_alternate_urls(request: Request, current_lang: str) -> dict:
    """
    Generate alternate URLs for hreflang tags.

    Returns dict of {lang: url} for SEO.
    """
    base_url = f"{request.url.scheme}://{request.url.netloc}"
    path_without_lang = get_path_without_lang(request.url.path)

    alternates = {}
    for lang in SUPPORTED_LANGUAGES:
        alternates[lang] = f"{base_url}/{lang}{path_without_lang}"

    # x-default points to Korean
    alternates['x-default'] = alternates[DEFAULT_LANGUAGE]

    return alternates


class LanguageMiddleware(BaseHTTPMiddleware):
    """
    Middleware to detect and set language for each request.

    Adds to request.state:
    - lang: Current language code
    - t: Translator function
    - supported_langs: List of supported languages
    - alternate_urls: Dict of alternate language URLs for SEO
    """

    # Paths that should NOT have language prefixes
    EXEMPT_PATHS = [
        '/api/',
        '/static/',
        '/auth/callback',
        '/health',
        '/favicon.ico',
        '/robots.txt',
        '/sitemap.xml',
    ]

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip language processing for exempt paths
        for exempt in self.EXEMPT_PATHS:
            if path.startswith(exempt):
                return await call_next(request)

        # Detect language
        lang = get_language_from_request(request)

        # Store in request state
        request.state.lang = lang
        request.state.t = get_translator(lang)
        request.state.supported_langs = SUPPORTED_LANGUAGES
        request.state.alternate_urls = get_alternate_urls(request, lang)
        request.state.i18n_data = i18n.get_for_template(lang)

        response = await call_next(request)

        # Set language cookie
        response.set_cookie(
            key='lang',
            value=lang,
            max_age=365 * 24 * 60 * 60,  # 1 year
            httponly=False,
            samesite='lax'
        )

        return response


def create_language_context(request: Request, lang: str = None) -> dict:
    """
    Create template context with language support.

    Use this in route handlers to pass i18n context to templates.
    """
    if lang is None:
        lang = getattr(request.state, 'lang', DEFAULT_LANGUAGE)

    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE

    return {
        'lang': lang,
        't': get_translator(lang),
        'supported_langs': SUPPORTED_LANGUAGES,
        'lang_names': LANGUAGE_NAMES,
        'alternate_urls': get_alternate_urls(request, lang),
        'i18n': i18n.get_for_template(lang),
    }
