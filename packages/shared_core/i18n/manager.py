"""
Translation Manager

공유 번역 + 서비스별 번역을 병합하여 관리.

로드 순서 (우선순위: 뒤가 높음):
1. shared_core/i18n/translations/{lang}/  (공통 번역)
2. 서비스별 extra_dirs                     (서비스 고유 번역, 공통 키 오버라이드 가능)

Fallback 순서:
1. 요청된 언어 (예: fr)
2. en (영어)
3. ko (한국어, DEFAULT_LANGUAGE)
4. key 자체 반환
"""

from pathlib import Path
import json
from typing import Dict, Any, Optional, List
import logging

from .constants import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE

logger = logging.getLogger(__name__)

# 공유 번역 디렉토리
_SHARED_TRANSLATIONS_DIR = Path(__file__).parent / 'translations'


class TranslationManager:
    """
    번역 파일 로드 및 조회.

    translations/
    ├── ko/
    │   └── common.json
    └── en/
        └── common.json

    Usage:
        # 공유 번역만 사용
        i18n = TranslationManager()

        # 서비스별 번역 추가
        i18n = TranslationManager(extra_dirs=[Path("app/i18n/translations")])

        i18n.get('common.nav.login', 'en')  # 'Login'
        i18n.get('common.nav.login', 'ko')  # '로그인'
    """

    def __init__(self, extra_dirs: Optional[List[Path]] = None):
        self.translations: Dict[str, Dict[str, Any]] = {}
        self._dirs = [_SHARED_TRANSLATIONS_DIR]
        if extra_dirs:
            self._dirs.extend(extra_dirs)
        self._load_all()

    def _load_all(self) -> None:
        """모든 번역 디렉토리에서 번역 파일 로드. 뒤의 디렉토리가 앞을 오버라이드."""
        for lang in SUPPORTED_LANGUAGES:
            if lang not in self.translations:
                self.translations[lang] = {}

            for base_dir in self._dirs:
                lang_path = base_dir / lang
                if not lang_path.exists():
                    continue

                for json_file in lang_path.glob('*.json'):
                    namespace = json_file.stem
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        if '_meta' in data:
                            del data['_meta']

                        # 기존 namespace가 있으면 deep merge, 없으면 새로 추가
                        if namespace in self.translations[lang]:
                            self._deep_merge(self.translations[lang][namespace], data)
                        else:
                            self.translations[lang][namespace] = data

                        logger.debug(f"Loaded: {lang}/{namespace} from {base_dir}")
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON in {json_file}: {e}")
                    except Exception as e:
                        logger.error(f"Error loading {json_file}: {e}")

    @staticmethod
    def _deep_merge(base: Dict, override: Dict) -> None:
        """override의 값을 base에 재귀적으로 병합."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                TranslationManager._deep_merge(base[key], value)
            else:
                base[key] = value

    def reload(self) -> None:
        """디스크에서 모든 번역 재로드."""
        self.translations = {}
        self._load_all()

    def get(
        self,
        key: str,
        lang: str = DEFAULT_LANGUAGE,
        default: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        dot-notation 키로 번역 조회.

        Args:
            key: 'common.nav.login' 형태
            lang: 언어 코드
            default: 키 없을 때 기본값
            **kwargs: 문자열 보간 인자

        Fallback: lang → en → ko → default → key
        """
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE

        parts = key.split('.')
        if len(parts) < 2:
            return default or key

        namespace = parts[0]
        path = parts[1:]

        # 1. 요청 언어
        value = self._get_nested(self.translations.get(lang, {}), namespace, path)

        # 2. Fallback to English
        if value is None and lang != 'en':
            value = self._get_nested(self.translations.get('en', {}), namespace, path)

        # 3. Fallback to Korean (DEFAULT_LANGUAGE)
        if value is None and lang != DEFAULT_LANGUAGE:
            value = self._get_nested(
                self.translations.get(DEFAULT_LANGUAGE, {}), namespace, path
            )

        if value is None:
            return default if default is not None else key

        if kwargs and isinstance(value, str):
            try:
                value = value.format(**kwargs)
            except KeyError:
                pass

        return value

    def _get_nested(
        self, data: Dict, namespace: str, path: List[str]
    ) -> Optional[str]:
        """중첩 딕셔너리에서 값 조회."""
        value = data.get(namespace, {})
        for part in path:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value if isinstance(value, str) else None

    def get_all(self, namespace: str, lang: str = DEFAULT_LANGUAGE) -> Dict[str, Any]:
        """namespace 전체 번역 반환."""
        if lang not in SUPPORTED_LANGUAGES:
            lang = DEFAULT_LANGUAGE
        return self.translations.get(lang, {}).get(namespace, {})

    def get_for_template(self, lang: str = DEFAULT_LANGUAGE) -> Dict[str, Any]:
        """Jinja2 템플릿용 전체 번역 반환."""
        return self.translations.get(lang, self.translations.get(DEFAULT_LANGUAGE, {}))

    def t(self, key: str, lang: str = DEFAULT_LANGUAGE, **kwargs) -> str:
        """get()의 축약."""
        return self.get(key, lang, **kwargs)


def get_translator(lang: str):
    """
    특정 언어용 번역 함수 반환.

    Usage:
        t = get_translator('en')
        t('common.nav.login')  # 'Login'
    """
    # 글로벌 인스턴스가 없으면 생성
    global _global_i18n
    if _global_i18n is None:
        _global_i18n = TranslationManager()

    def translator(key: str, default: str = None, **kwargs) -> str:
        return _global_i18n.get(key, lang, default, **kwargs)
    return translator


def create_shared_i18n(extra_dirs: Optional[List[Path]] = None) -> TranslationManager:
    """
    공유 + 서비스별 번역을 병합한 TranslationManager 인스턴스 생성.

    Usage (서비스 server.py에서):
        from shared_core.i18n import create_shared_i18n
        i18n = create_shared_i18n([Path(__file__).parent / "i18n" / "translations"])
    """
    return TranslationManager(extra_dirs=extra_dirs)


# 글로벌 인스턴스 (공유 번역만 로드)
_global_i18n: Optional[TranslationManager] = None


def get_global_i18n() -> TranslationManager:
    """글로벌 공유 번역 인스턴스 반환 (lazy init)."""
    global _global_i18n
    if _global_i18n is None:
        _global_i18n = TranslationManager()
    return _global_i18n
