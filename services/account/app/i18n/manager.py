"""
Translation Manager for Account Service

Handles loading and retrieving translations from JSON files.
Supports namespaced translations (common, auth, account, admin).
"""

from pathlib import Path
import json
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

# Supported languages (7 languages across all services)
SUPPORTED_LANGUAGES = ['ko', 'en', 'fr', 'it', 'ja', 'zh', 'tr']
DEFAULT_LANGUAGE = 'ko'

# Language display names
LANGUAGE_NAMES = {
    'ko': '한국어',
    'en': 'English',
    'fr': 'Français',
    'it': 'Italiano',
    'ja': '日本語',
    'zh': '中文',
    'tr': 'Türkçe',
}

# Language-to-theme mapping (Asian: light, Western: dark)
LANG_THEME_MAP = {
    'ko': 'light',
    'ja': 'light',
    'zh': 'light',
    'en': 'dark',
    'fr': 'dark',
    'it': 'dark',
    'tr': 'dark',
}
DEFAULT_THEME = 'dark'


class TranslationManager:
    """
    Manages translations loaded from JSON files.

    Translation files are organized by language and namespace:
    translations/
    ├── ko/
    │   ├── common.json
    │   ├── auth.json
    │   ├── account.json
    │   └── admin.json
    └── en/
        ├── common.json
        ├── auth.json
        ├── account.json
        └── admin.json

    Usage:
        i18n = TranslationManager()
        i18n.get('common.nav.login', 'en')  # Returns 'Login'
        i18n.get('common.nav.login', 'ko')  # Returns '로그인'
    """

    def __init__(self, translations_dir: Optional[Path] = None):
        self.translations: Dict[str, Dict[str, Any]] = {}
        self.translations_dir = translations_dir or Path(__file__).parent / 'translations'
        self._load_all_translations()

    def _load_all_translations(self) -> None:
        """Load all translation files for all supported languages."""
        for lang in SUPPORTED_LANGUAGES:
            self.translations[lang] = {}
            lang_path = self.translations_dir / lang

            if not lang_path.exists():
                logger.warning(f"Translation directory not found: {lang_path}")
                continue

            for json_file in lang_path.glob('*.json'):
                namespace = json_file.stem
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        # Remove _meta key for lookups
                        if '_meta' in data:
                            del data['_meta']
                        self.translations[lang][namespace] = data
                    logger.debug(f"Loaded translations: {lang}/{namespace}")
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in {json_file}: {e}")
                except Exception as e:
                    logger.error(f"Error loading {json_file}: {e}")

    def reload(self) -> None:
        """Reload all translations from disk."""
        self.translations = {}
        self._load_all_translations()

    def get(
        self,
        key: str,
        lang: str = DEFAULT_LANGUAGE,
        default: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Get a translation by dot-notation key.

        Args:
            key: Dot-notation key (e.g., 'common.nav.login')
            lang: Language code (e.g., 'ko', 'en')
            default: Default value if key not found
            **kwargs: Format arguments for string interpolation

        Returns:
            Translated string, or default/key if not found
        """
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE

        parts = key.split('.')
        if len(parts) < 2:
            return default or key

        namespace = parts[0]
        path = parts[1:]

        # Try requested language
        value = self._get_nested(self.translations.get(lang, {}), namespace, path)

        # Fallback to default language
        if value is None and lang != DEFAULT_LANGUAGE:
            value = self._get_nested(
                self.translations.get(DEFAULT_LANGUAGE, {}),
                namespace,
                path
            )

        if value is None:
            return default if default is not None else key

        # Format with kwargs
        if kwargs and isinstance(value, str):
            try:
                value = value.format(**kwargs)
            except KeyError:
                pass  # Keep original if format fails

        return value

    def _get_nested(
        self,
        data: Dict,
        namespace: str,
        path: List[str]
    ) -> Optional[str]:
        """Get a nested value from translation data."""
        value = data.get(namespace, {})
        for part in path:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value if isinstance(value, str) else None

    def get_all(self, namespace: str, lang: str = DEFAULT_LANGUAGE) -> Dict[str, Any]:
        """
        Get all translations for a namespace.

        Args:
            namespace: Translation namespace (e.g., 'common', 'auth')
            lang: Language code

        Returns:
            Dictionary of all translations in the namespace
        """
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE
        return self.translations.get(lang, {}).get(namespace, {})

    def get_for_template(self, lang: str = DEFAULT_LANGUAGE) -> Dict[str, Any]:
        """
        Get all translations for a language, suitable for template context.

        Returns flattened structure for easy access in Jinja2 templates.
        """
        return self.translations.get(lang, self.translations.get(DEFAULT_LANGUAGE, {}))

    def t(self, key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
        """Shorthand for get()."""
        return self.get(key, lang, **kwargs)


# Global instance
i18n = TranslationManager()


def get_translator(lang: str):
    """
    Get a translator function for a specific language.

    Usage in templates:
        t = get_translator('en')
        t('common.nav.login')  # Returns 'Login'
    """
    def translator(key: str, default: str = None, **kwargs) -> str:
        return i18n.get(key, lang, default, **kwargs)
    return translator
