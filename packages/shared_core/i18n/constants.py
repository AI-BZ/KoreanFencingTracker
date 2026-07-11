"""
i18n Constants - 모든 서비스가 공유하는 언어/테마 상수

이 값들은 프로젝트 전체에서 통일되어야 합니다.
수정 시 모든 서비스에 영향이 갑니다.
"""

# 지원 언어 (7개, 모든 서비스 통일)
SUPPORTED_LANGUAGES = ['ko', 'en', 'fr', 'it', 'ja', 'zh', 'tr']
DEFAULT_LANGUAGE = 'ko'

# 언어 표시명
LANGUAGE_NAMES = {
    'ko': '한국어',
    'en': 'English',
    'fr': 'Français',
    'it': 'Italiano',
    'ja': '日本語',
    'zh': '中文',
    'tr': 'Türkçe',
}

# 언어 → 테마 매핑 (아시아: light, 서양: dark)
# 수동 테마 토글 없음 — 언어 선택이 테마를 결정
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
