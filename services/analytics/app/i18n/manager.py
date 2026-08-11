"""Translation manager for analytics service (ko/en)."""

import json
from pathlib import Path
from typing import Any


SUPPORTED_LANGS = ["ko", "en"]
DEFAULT_LANG = "ko"
TRANSLATIONS_DIR = Path(__file__).parent / "translations"


class TranslationManager:
    """Simple translation manager with dot-notation lookup."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._load_translations()

    def _load_translations(self) -> None:
        for lang in SUPPORTED_LANGS:
            lang_dir = TRANSLATIONS_DIR / lang
            if not lang_dir.exists():
                continue
            self._data[lang] = {}
            for json_file in lang_dir.glob("*.json"):
                ns = json_file.stem
                with open(json_file, encoding="utf-8") as f:
                    self._data[lang][ns] = json.load(f)

    def get(self, key: str, lang: str = DEFAULT_LANG) -> str:
        """Lookup translation by dot-notation key.

        Example: get("nav.gallery", "ko") -> "데모 갤러리"
        Falls back to ko, then returns the key itself.
        """
        parts = key.split(".")
        # Try requested lang first, then fallback to ko
        for try_lang in [lang, DEFAULT_LANG]:
            data = self._data.get(try_lang, {})
            # First part could be namespace or direct key
            result = self._resolve(data, parts)
            if result is not None:
                return result
            # Try with "analytics" namespace prefix
            analytics = data.get("analytics", {})
            result = self._resolve(analytics, parts)
            if result is not None:
                return result
        return key

    def _resolve(self, data: dict, parts: list[str]) -> str | None:
        current: Any = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return str(current) if not isinstance(current, dict) else None

    def get_for_template(self, lang: str = DEFAULT_LANG) -> dict:
        """Return full translation dict for Jinja2 context."""
        return self._data.get(lang, self._data.get(DEFAULT_LANG, {}))


# Global singleton
i18n = TranslationManager()
