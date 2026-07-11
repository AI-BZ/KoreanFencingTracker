"""
Unit tests for app.i18n module

Tests cover:
- Translation loading and retrieval
- Language detection from headers/cookies
- Middleware functionality
- Template context creation
- Edge cases and error handling
- Missing translations and fallbacks
- Unicode and special character handling
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from fastapi import Request
from starlette.datastructures import Headers
import json
import tempfile
import shutil

from app.i18n import (
    TranslationManager,
    i18n,
    get_translator,
    SUPPORTED_LANGUAGES,
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    get_language_from_request,
    LanguageMiddleware,
    create_language_context,
)


# Fixtures
@pytest.fixture
def temp_translations_dir():
    """Create temporary translation directory with test files"""
    temp_dir = Path(tempfile.mkdtemp())

    # Create language directories
    (temp_dir / "ko").mkdir()
    (temp_dir / "en").mkdir()

    # Korean translations
    ko_common = {
        "_meta": {"language": "ko", "version": "1.0.0"},
        "nav": {"home": "홈", "search": "검색", "login": "로그인"},
        "common": {"loading": "로딩 중...", "error": "오류"},
        "search": {
            "placeholder": "검색어를 입력하세요",
            "results_count": "{count}개의 결과",
        },
        "nested": {"deep": {"value": "깊은 값"}},
    }

    ko_player = {
        "_meta": {"language": "ko"},
        "profile": "선수 프로필",
        "statistics": "통계",
        "medals": {"gold": "금메달", "silver": "은메달", "bronze": "동메달"},
    }

    # English translations
    en_common = {
        "_meta": {"language": "en", "version": "1.0.0"},
        "nav": {"home": "Home", "search": "Search", "login": "Login"},
        "common": {"loading": "Loading...", "error": "Error"},
        "search": {
            "placeholder": "Enter search term",
            "results_count": "{count} results",
        },
        "nested": {"deep": {"value": "Deep value"}},
    }

    en_player = {
        "_meta": {"language": "en"},
        "profile": "Player Profile",
        "statistics": "Statistics",
        "medals": {"gold": "Gold Medal", "silver": "Silver Medal", "bronze": "Bronze Medal"},
    }

    # Write files
    with open(temp_dir / "ko" / "common.json", "w", encoding="utf-8") as f:
        json.dump(ko_common, f, ensure_ascii=False, indent=2)

    with open(temp_dir / "ko" / "player.json", "w", encoding="utf-8") as f:
        json.dump(ko_player, f, ensure_ascii=False, indent=2)

    with open(temp_dir / "en" / "common.json", "w", encoding="utf-8") as f:
        json.dump(en_common, f, ensure_ascii=False, indent=2)

    with open(temp_dir / "en" / "player.json", "w", encoding="utf-8") as f:
        json.dump(en_player, f, ensure_ascii=False, indent=2)

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def translation_manager(temp_translations_dir):
    """Create TranslationManager with test translations"""
    return TranslationManager(translations_dir=temp_translations_dir)


@pytest.fixture
def mock_request():
    """Create mock FastAPI request"""
    request = Mock(spec=Request)
    request.state = Mock()
    request.cookies = {}
    request.headers = {}
    request.url = Mock()
    request.url.path = "/"
    request.url.scheme = "http"
    request.url.netloc = "localhost"
    return request


# Translation Loading Tests
class TestTranslationLoading:
    """Test translation file loading"""

    def test_load_korean_translations(self, translation_manager):
        """Test loading Korean translations"""
        assert "ko" in translation_manager.translations
        assert "common" in translation_manager.translations["ko"]
        assert "player" in translation_manager.translations["ko"]

    def test_load_english_translations(self, translation_manager):
        """Test loading English translations"""
        assert "en" in translation_manager.translations
        assert "common" in translation_manager.translations["en"]
        assert "player" in translation_manager.translations["en"]

    def test_meta_removed_from_lookups(self, translation_manager):
        """Test that _meta key is removed"""
        common_ko = translation_manager.translations["ko"]["common"]
        assert "_meta" not in common_ko
        assert "nav" in common_ko

    def test_load_missing_directory(self):
        """Test loading with missing directory"""
        nonexistent_dir = Path("/nonexistent/path")
        manager = TranslationManager(translations_dir=nonexistent_dir)
        # Should not crash, just log warning
        assert manager.translations == {"ko": {}, "en": {}}

    def test_reload_translations(self, translation_manager, temp_translations_dir):
        """Test reloading translations"""
        # Modify a file
        new_data = {"test": "새로운 값"}
        with open(temp_translations_dir / "ko" / "common.json", "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False)

        translation_manager.reload()
        assert translation_manager.translations["ko"]["common"]["test"] == "새로운 값"


# Translation Retrieval Tests
class TestTranslationRetrieval:
    """Test translation retrieval"""

    def test_get_simple_key_korean(self, translation_manager):
        """Test getting simple Korean translation"""
        result = translation_manager.get("common.nav.home", "ko")
        assert result == "홈"

    def test_get_simple_key_english(self, translation_manager):
        """Test getting simple English translation"""
        result = translation_manager.get("common.nav.home", "en")
        assert result == "Home"

    def test_get_nested_key(self, translation_manager):
        """Test getting deeply nested translation"""
        result = translation_manager.get("common.nested.deep.value", "ko")
        assert result == "깊은 값"

    def test_get_with_formatting(self, translation_manager):
        """Test translation with variable formatting"""
        result = translation_manager.get("common.search.results_count", "ko", count=5)
        assert result == "5개의 결과"

        result = translation_manager.get("common.search.results_count", "en", count=10)
        assert result == "10 results"

    def test_fallback_to_default_language(self, translation_manager):
        """Test fallback to Korean when English key missing"""
        # Add key only in Korean
        translation_manager.translations["ko"]["common"]["only_korean"] = "한국어만"

        result = translation_manager.get("common.only_korean", "en")
        assert result == "한국어만"

    def test_missing_key_returns_default(self, translation_manager):
        """Test missing key returns default value"""
        result = translation_manager.get("missing.key", "ko", default="기본값")
        assert result == "기본값"

    def test_missing_key_returns_key(self, translation_manager):
        """Test missing key returns key itself if no default"""
        result = translation_manager.get("missing.key", "ko")
        assert result == "missing.key"

    def test_invalid_key_format(self, translation_manager):
        """Test invalid key format"""
        result = translation_manager.get("invalid", "ko", default="기본")
        assert result == "기본"

    def test_unsupported_language(self, translation_manager):
        """Test unsupported language falls back to default"""
        result = translation_manager.get("common.nav.home", "ja")
        assert result == "홈"  # Falls back to Korean

    def test_shorthand_t_method(self, translation_manager):
        """Test shorthand t() method"""
        result = translation_manager.t("common.nav.home", "ko")
        assert result == "홈"


# Get All Translations Tests
class TestGetAllTranslations:
    """Test getting all translations for namespace"""

    def test_get_all_namespace(self, translation_manager):
        """Test getting all translations for namespace"""
        common = translation_manager.get_all("common", "ko")
        assert "nav" in common
        assert "common" in common
        assert common["nav"]["home"] == "홈"

    def test_get_all_missing_namespace(self, translation_manager):
        """Test getting all for missing namespace"""
        result = translation_manager.get_all("missing", "ko")
        assert result == {}

    def test_get_for_template(self, translation_manager):
        """Test getting translations for template"""
        result = translation_manager.get_for_template("ko")
        assert "common" in result
        assert "player" in result


# Language Detection Tests
class TestLanguageDetection:
    """Test language detection from request"""

    def test_detect_from_url_path_korean(self, mock_request):
        """Test detecting Korean from URL path"""
        mock_request.url.path = "/ko/search"
        lang = get_language_from_request(mock_request)
        assert lang == "ko"

    def test_detect_from_url_path_english(self, mock_request):
        """Test detecting English from URL path"""
        mock_request.url.path = "/en/search"
        lang = get_language_from_request(mock_request)
        assert lang == "en"

    def test_detect_from_url_path_exact(self, mock_request):
        """Test detecting from exact language path"""
        mock_request.url.path = "/en"
        lang = get_language_from_request(mock_request)
        assert lang == "en"

    def test_detect_from_cookie(self, mock_request):
        """Test detecting language from cookie"""
        mock_request.url.path = "/search"
        mock_request.cookies = {"lang": "en"}
        lang = get_language_from_request(mock_request)
        assert lang == "en"

    def test_detect_from_accept_header(self, mock_request):
        """Test detecting language from Accept-Language header"""
        mock_request.url.path = "/search"
        mock_request.headers = {"accept-language": "en-US,en;q=0.9"}
        lang = get_language_from_request(mock_request)
        assert lang == "en"

    def test_priority_url_over_cookie(self, mock_request):
        """Test URL path has priority over cookie"""
        mock_request.url.path = "/en/search"
        mock_request.cookies = {"lang": "ko"}
        lang = get_language_from_request(mock_request)
        assert lang == "en"

    def test_priority_cookie_over_header(self, mock_request):
        """Test cookie has priority over header"""
        mock_request.url.path = "/search"
        mock_request.cookies = {"lang": "en"}
        mock_request.headers = {"accept-language": "ko"}
        lang = get_language_from_request(mock_request)
        assert lang == "en"

    def test_default_language_fallback(self, mock_request):
        """Test fallback to default language"""
        mock_request.url.path = "/search"
        lang = get_language_from_request(mock_request)
        assert lang == DEFAULT_LANGUAGE


# Middleware Tests
class TestLanguageMiddleware:
    """Test LanguageMiddleware"""

    @pytest.mark.asyncio
    async def test_middleware_sets_lang(self, mock_request):
        """Test middleware sets language in request state"""
        mock_request.url.path = "/en/search"

        async def call_next(request):
            assert request.state.lang == "en"
            response = Mock()
            response.set_cookie = Mock()
            return response

        middleware = LanguageMiddleware(app=Mock())
        response = await middleware.dispatch(mock_request, call_next)
        assert response.set_cookie.called

    @pytest.mark.asyncio
    async def test_middleware_sets_translator(self, mock_request):
        """Test middleware sets translator function"""
        mock_request.url.path = "/ko/search"

        async def call_next(request):
            assert hasattr(request.state, "t")
            assert callable(request.state.t)
            response = Mock()
            response.set_cookie = Mock()
            return response

        middleware = LanguageMiddleware(app=Mock())
        await middleware.dispatch(mock_request, call_next)

    @pytest.mark.asyncio
    async def test_middleware_sets_cookie(self, mock_request):
        """Test middleware sets language cookie"""
        mock_request.url.path = "/en/search"

        async def call_next(request):
            response = Mock()
            response.set_cookie = Mock()
            return response

        middleware = LanguageMiddleware(app=Mock())
        response = await middleware.dispatch(mock_request, call_next)

        response.set_cookie.assert_called_once()
        call_args = response.set_cookie.call_args
        assert call_args[1]["key"] == "lang"
        assert call_args[1]["value"] == "en"

    @pytest.mark.asyncio
    async def test_middleware_skips_api_paths(self, mock_request):
        """Test middleware skips API paths"""
        mock_request.url.path = "/api/search"

        called = False

        async def call_next(request):
            nonlocal called
            called = True
            # Should not have language processing
            response = Mock()
            return response

        middleware = LanguageMiddleware(app=Mock())
        await middleware.dispatch(mock_request, call_next)
        assert called

    @pytest.mark.asyncio
    async def test_middleware_skips_static_paths(self, mock_request):
        """Test middleware skips static file paths"""
        for path in ["/static/css/style.css", "/favicon.ico", "/robots.txt"]:
            mock_request.url.path = path

            async def call_next(request):
                response = Mock()
                return response

            middleware = LanguageMiddleware(app=Mock())
            await middleware.dispatch(mock_request, call_next)

    @pytest.mark.asyncio
    async def test_middleware_sets_supported_langs(self, mock_request):
        """Test middleware sets supported languages"""
        mock_request.url.path = "/search"

        async def call_next(request):
            assert request.state.supported_langs == SUPPORTED_LANGUAGES
            response = Mock()
            response.set_cookie = Mock()
            return response

        middleware = LanguageMiddleware(app=Mock())
        await middleware.dispatch(mock_request, call_next)


# Template Context Tests
class TestTemplateContext:
    """Test template context creation"""

    def test_create_context_default_lang(self, mock_request):
        """Test creating context with default language"""
        context = create_language_context(mock_request)
        assert context["lang"] == DEFAULT_LANGUAGE
        assert "t" in context
        assert callable(context["t"])
        assert context["supported_langs"] == SUPPORTED_LANGUAGES

    def test_create_context_specific_lang(self, mock_request):
        """Test creating context with specific language"""
        context = create_language_context(mock_request, lang="en")
        assert context["lang"] == "en"

    def test_create_context_from_state(self, mock_request):
        """Test creating context from request state"""
        mock_request.state.lang = "en"
        context = create_language_context(mock_request)
        assert context["lang"] == "en"

    def test_create_context_invalid_lang(self, mock_request):
        """Test creating context with invalid language falls back"""
        context = create_language_context(mock_request, lang="invalid")
        assert context["lang"] == DEFAULT_LANGUAGE

    def test_context_has_i18n_data(self, mock_request):
        """Test context includes i18n data"""
        context = create_language_context(mock_request)
        assert "i18n" in context
        assert isinstance(context["i18n"], dict)

    def test_context_has_alternate_urls(self, mock_request):
        """Test context includes alternate URLs"""
        mock_request.url.path = "/search"
        context = create_language_context(mock_request)
        assert "alternate_urls" in context
        assert "ko" in context["alternate_urls"]
        assert "en" in context["alternate_urls"]


# Get Translator Tests
class TestGetTranslator:
    """Test get_translator function"""

    def test_get_translator_korean(self):
        """Test getting Korean translator"""
        t = get_translator("ko")
        assert callable(t)

    def test_get_translator_english(self):
        """Test getting English translator"""
        t = get_translator("en")
        assert callable(t)

    def test_translator_function_works(self, translation_manager):
        """Test translator function returns correct translations"""
        t = get_translator("ko")
        # This uses global i18n, so results depend on actual files
        # Just test it's callable and returns strings
        result = t("common.nav.home")
        assert isinstance(result, str)


# Edge Cases Tests
class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_empty_key(self, translation_manager):
        """Test empty translation key"""
        result = translation_manager.get("", "ko")
        assert result == ""

    def test_key_with_extra_dots(self, translation_manager):
        """Test key with extra dots"""
        result = translation_manager.get("common..nav.home", "ko")
        assert result == "common..nav.home"  # Returns key as fallback

    def test_none_value_in_translations(self, translation_manager):
        """Test None value in translation data"""
        translation_manager.translations["ko"]["test"] = {"key": None}
        result = translation_manager.get("test.key", "ko", default="기본")
        assert result == "기본"

    def test_format_with_missing_variable(self, translation_manager):
        """Test formatting with missing variable"""
        # Translation: "{count}개의 결과"
        result = translation_manager.get("common.search.results_count", "ko")
        # Should keep original format string
        assert "{count}" in result

    def test_format_with_extra_variables(self, translation_manager):
        """Test formatting with extra variables"""
        result = translation_manager.get(
            "common.search.results_count", "ko", count=5, extra="ignored"
        )
        assert result == "5개의 결과"


# Unicode Tests
class TestUnicodeHandling:
    """Test Unicode and special character handling"""

    def test_korean_characters(self, translation_manager):
        """Test Korean characters are preserved"""
        result = translation_manager.get("common.nav.home", "ko")
        assert result == "홈"
        assert isinstance(result, str)

    def test_emoji_in_translations(self, temp_translations_dir):
        """Test emoji in translations"""
        emoji_data = {"emoji": "🏅 메달"}
        with open(temp_translations_dir / "ko" / "test.json", "w", encoding="utf-8") as f:
            json.dump(emoji_data, f, ensure_ascii=False)

        manager = TranslationManager(translations_dir=temp_translations_dir)
        result = manager.get("test.emoji", "ko")
        assert result == "🏅 메달"

    def test_special_characters(self, translation_manager):
        """Test special characters in translations"""
        # Korean has special chars
        result = translation_manager.get("common.common.loading", "ko")
        assert "..." in result

    def test_mixed_languages(self, translation_manager):
        """Test mixed Korean/English text"""
        # Some translations have mixed content
        result = translation_manager.get("common.search.placeholder", "ko")
        assert isinstance(result, str)


# Invalid JSON Tests
class TestInvalidJSON:
    """Test handling of invalid JSON files"""

    def test_invalid_json_file(self, temp_translations_dir):
        """Test invalid JSON file is handled gracefully"""
        # Create invalid JSON
        with open(temp_translations_dir / "ko" / "invalid.json", "w") as f:
            f.write("{invalid json content")

        # Should not crash
        manager = TranslationManager(translations_dir=temp_translations_dir)
        # Invalid file should be skipped
        assert "invalid" not in manager.translations.get("ko", {})

    def test_empty_json_file(self, temp_translations_dir):
        """Test empty JSON file"""
        with open(temp_translations_dir / "ko" / "empty.json", "w") as f:
            f.write("{}")

        manager = TranslationManager(translations_dir=temp_translations_dir)
        result = manager.get_all("empty", "ko")
        assert result == {}


# Constants Tests
class TestConstants:
    """Test module constants"""

    def test_supported_languages(self):
        """Test SUPPORTED_LANGUAGES constant"""
        assert "ko" in SUPPORTED_LANGUAGES
        assert "en" in SUPPORTED_LANGUAGES
        assert len(SUPPORTED_LANGUAGES) >= 2

    def test_default_language(self):
        """Test DEFAULT_LANGUAGE constant"""
        assert DEFAULT_LANGUAGE == "ko"
        assert DEFAULT_LANGUAGE in SUPPORTED_LANGUAGES

    def test_language_names(self):
        """Test LANGUAGE_NAMES constant"""
        assert "ko" in LANGUAGE_NAMES
        assert LANGUAGE_NAMES["ko"] == "한국어"
        assert "en" in LANGUAGE_NAMES
        assert LANGUAGE_NAMES["en"] == "English"


# Path Utility Tests
class TestPathUtilities:
    """Test path utility functions from middleware"""

    def test_get_path_without_lang_korean(self):
        """Test removing Korean prefix from path"""
        from app.i18n.middleware import get_path_without_lang

        assert get_path_without_lang("/ko/search") == "/search"
        assert get_path_without_lang("/ko/") == "/"
        assert get_path_without_lang("/ko") == "/"

    def test_get_path_without_lang_english(self):
        """Test removing English prefix from path"""
        from app.i18n.middleware import get_path_without_lang

        assert get_path_without_lang("/en/search") == "/search"
        assert get_path_without_lang("/en") == "/"

    def test_get_path_without_lang_no_prefix(self):
        """Test path without language prefix"""
        from app.i18n.middleware import get_path_without_lang

        assert get_path_without_lang("/search") == "/search"
        assert get_path_without_lang("/api/data") == "/api/data"

    def test_get_alternate_urls(self, mock_request):
        """Test generating alternate URLs"""
        from app.i18n.middleware import get_alternate_urls

        mock_request.url.path = "/ko/search"
        alternates = get_alternate_urls(mock_request, "ko")

        assert "ko" in alternates
        assert "en" in alternates
        assert "x-default" in alternates
        assert "/ko/search" in alternates["ko"]
        assert "/en/search" in alternates["en"]


# Integration Tests
class TestIntegration:
    """Integration tests for i18n system"""

    @pytest.mark.asyncio
    async def test_full_request_workflow(self, mock_request):
        """Test full request workflow with middleware"""
        mock_request.url.path = "/en/search"

        async def call_next(request):
            # After middleware processing
            assert request.state.lang == "en"
            assert callable(request.state.t)
            assert request.state.supported_langs == SUPPORTED_LANGUAGES

            # Create template context
            context = create_language_context(request)
            assert context["lang"] == "en"

            response = Mock()
            response.set_cookie = Mock()
            return response

        middleware = LanguageMiddleware(app=Mock())
        await middleware.dispatch(mock_request, call_next)

    def test_translation_with_actual_files(self):
        """Test translation with actual project files"""
        # Uses global i18n instance with real files
        result_ko = i18n.get("common.nav.home", "ko")
        result_en = i18n.get("common.nav.home", "en")

        assert isinstance(result_ko, str)
        assert isinstance(result_en, str)
        assert result_ko != result_en  # Should be different languages

    def test_multilevel_fallback(self, translation_manager):
        """Test multi-level fallback behavior"""
        # Missing in both languages, should return key
        result = translation_manager.get("missing.deeply.nested.key", "en")
        assert result == "missing.deeply.nested.key"

        # Missing in English, exists in Korean
        translation_manager.translations["ko"]["test"] = {"only_korean": "한국어"}
        result = translation_manager.get("test.only_korean", "en")
        assert result == "한국어"
