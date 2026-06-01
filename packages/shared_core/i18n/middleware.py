"""
Language Detection Middleware

모든 서비스가 공유하는 언어 감지 미들웨어.

감지 우선순위:
1. ?lang= 쿼리 파라미터
2. URL path prefix (/{lang}/...)
3. Cookie (lang) — domain=.fencingmind.ai 공유
4. Accept-Language 헤더
5. 기본값 (ko)

Usage (서비스 server.py에서):
    from shared_core.i18n import LanguageMiddleware
    app.add_middleware(LanguageMiddleware)

    # 서비스별 번역을 추가하려면:
    from shared_core.i18n import LanguageMiddleware, create_shared_i18n
    i18n = create_shared_i18n([Path("app/i18n/translations")])
    app.add_middleware(LanguageMiddleware, i18n=i18n)
"""

import os
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from .constants import (
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    LANG_THEME_MAP,
    DEFAULT_THEME,
)
from .manager import TranslationManager, get_translator, get_global_i18n


def get_language_from_request(request: Request) -> str:
    """
    요청에서 언어 감지.

    Priority:
    1. ?lang= query parameter
    2. URL path prefix (/en/, /ko/)
    3. Cookie (lang)
    4. Accept-Language header
    5. Default (ko)
    """
    # 1. 쿼리 파라미터
    lang_param = request.query_params.get('lang')
    if lang_param and lang_param in SUPPORTED_LANGUAGES:
        return lang_param

    # 2. URL path prefix
    path = request.url.path
    for lang in SUPPORTED_LANGUAGES:
        if path.startswith(f'/{lang}/') or path == f'/{lang}':
            return lang

    # 3. Cookie
    lang_cookie = request.cookies.get('lang')
    if lang_cookie in SUPPORTED_LANGUAGES:
        return lang_cookie

    # 4. Accept-Language header
    accept_lang = request.headers.get('accept-language', '')
    for lang in SUPPORTED_LANGUAGES:
        if lang in accept_lang.lower():
            return lang

    # 5. Default
    return DEFAULT_LANGUAGE


class LanguageMiddleware(BaseHTTPMiddleware):
    """
    언어 감지 및 설정 미들웨어.

    request.state에 추가:
    - lang: 현재 언어 코드
    - theme: 현재 테마 ('light' 또는 'dark')
    - t: 번역 함수 t('common.nav.login')
    - supported_langs: 지원 언어 목록
    - language_names: 언어 표시명 딕셔너리
    - i18n_data: 현재 언어의 전체 번역 데이터
    """

    # 언어 처리 제외 경로
    EXEMPT_PATHS = [
        '/api/',
        '/static/',
        '/auth/callback',
        '/health',
        '/favicon.ico',
        '/robots.txt',
        '/sitemap.xml',
    ]

    def __init__(self, app, i18n: TranslationManager = None):
        super().__init__(app)
        self._i18n = i18n

    @property
    def i18n(self) -> TranslationManager:
        if self._i18n is None:
            self._i18n = get_global_i18n()
        return self._i18n

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 제외 경로 스킵
        for exempt in self.EXEMPT_PATHS:
            if path.startswith(exempt):
                return await call_next(request)

        # 언어 감지
        lang = get_language_from_request(request)

        # request.state에 저장
        request.state.lang = lang
        request.state.theme = LANG_THEME_MAP.get(lang, DEFAULT_THEME)
        request.state.t = self._make_translator(lang)
        request.state.supported_langs = SUPPORTED_LANGUAGES
        request.state.language_names = LANGUAGE_NAMES
        request.state.i18n_data = self.i18n.get_for_template(lang)

        response = await call_next(request)

        # 언어 쿠키 설정 (.fencingmind.ai 공유)
        cookie_domain = os.getenv("COOKIE_DOMAIN", ".fencingmind.ai")
        response.set_cookie(
            key='lang',
            value=lang,
            max_age=365 * 24 * 60 * 60,
            httponly=False,
            secure=True,
            samesite='lax',
            domain=cookie_domain,
        )

        return response

    def _make_translator(self, lang: str):
        """현재 i18n 인스턴스를 사용하는 번역 함수 생성."""
        i18n = self.i18n

        def translator(key: str, default: str = None, **kwargs) -> str:
            return i18n.get(key, lang, default, **kwargs)
        return translator


def create_language_context(request: Request, lang: str = None) -> dict:
    """
    템플릿 컨텍스트에 언어 지원 추가.

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

    # request.state에 i18n_data가 있으면 그것 사용 (서비스별 번역 포함)
    i18n_data = getattr(request.state, 'i18n_data', None)
    t_func = getattr(request.state, 't', None)

    if i18n_data is None:
        i18n = get_global_i18n()
        i18n_data = i18n.get_for_template(lang)

    if t_func is None:
        t_func = get_translator(lang)

    return {
        'lang': lang,
        'theme': LANG_THEME_MAP.get(lang, DEFAULT_THEME),
        't': t_func,
        'supported_langs': SUPPORTED_LANGUAGES,
        'language_names': LANGUAGE_NAMES,
        'i18n': i18n_data,
    }
