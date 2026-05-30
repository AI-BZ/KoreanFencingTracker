"""
Language Detection Middleware for Account Service

Detects language from:
1. ?lang= query parameter
2. URL path prefix (/{lang}/...)
3. Cookie (lang) - shared across .fencingmind.ai
4. Accept-Language header
5. Default to Korean

Account service keeps bare paths (/auth/login) without forced URL prefix redirect,
since other services redirect here.
"""

import os
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional

from .manager import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, LANGUAGE_NAMES, LANG_THEME_MAP, DEFAULT_THEME, i18n, get_translator


def get_language_from_request(request: Request) -> str:
    """
    Detect language from request.

    Priority:
    1. ?lang= query parameter
    2. URL path prefix (/en/, /ko/)
    3. Cookie (lang)
    4. Accept-Language header
    5. Default (ko)
    """
    # 1. Check query parameter
    lang_param = request.query_params.get('lang')
    if lang_param and lang_param in SUPPORTED_LANGUAGES:
        return lang_param

    # 2. Check URL path prefix
    path = request.url.path
    for lang in SUPPORTED_LANGUAGES:
        if path.startswith(f'/{lang}/') or path == f'/{lang}':
            return lang

    # 3. Check cookie
    lang_cookie = request.cookies.get('lang')
    if lang_cookie in SUPPORTED_LANGUAGES:
        return lang_cookie

    # 4. Check Accept-Language header
    accept_lang = request.headers.get('accept-language', '')
    for lang in SUPPORTED_LANGUAGES:
        if lang in accept_lang.lower():
            return lang

    # 5. Default
    return DEFAULT_LANGUAGE


class LanguageMiddleware(BaseHTTPMiddleware):
    """
    Middleware to detect and set language for each request.

    Adds to request.state:
    - lang: Current language code
    - t: Translator function
    - supported_langs: List of supported languages
    - i18n_data: All translations for the current language
    """

    # Paths that should NOT have language processing
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
        request.state.theme = LANG_THEME_MAP.get(lang, DEFAULT_THEME)
        request.state.t = get_translator(lang)
        request.state.supported_langs = SUPPORTED_LANGUAGES
        request.state.language_names = LANGUAGE_NAMES
        request.state.i18n_data = i18n.get_for_template(lang)

        response = await call_next(request)

        # Set language cookie (shared across .fencingmind.ai)
        cookie_domain = os.getenv("COOKIE_DOMAIN", ".fencingmind.ai")
        response.set_cookie(
            key='lang',
            value=lang,
            max_age=365 * 24 * 60 * 60,  # 1 year
            httponly=False,
            secure=True,
            samesite='lax',
            domain=cookie_domain,
        )

        return response


def create_language_context(request: Request, lang: str = None) -> dict:
    """
    Create template context with language support.

    Use this in route handlers to pass i18n context to templates.

    Usage:
        @router.get("/page")
        async def page(request: Request):
            return templates.TemplateResponse("page.html", {
                "request": request,
                **create_language_context(request),
            })
    """
    if lang is None:
        lang = getattr(request.state, 'lang', DEFAULT_LANGUAGE)

    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE

    return {
        'lang': lang,
        'theme': LANG_THEME_MAP.get(lang, DEFAULT_THEME),
        't': get_translator(lang),
        'supported_langs': SUPPORTED_LANGUAGES,
        'language_names': LANGUAGE_NAMES,
        'i18n': i18n.get_for_template(lang),
    }
