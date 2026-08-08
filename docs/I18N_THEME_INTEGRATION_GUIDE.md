# i18n & Theme 통합 가이드

**작성일:** 2026-05-31
**대상:** 각 서비스 워크트리에서 shared_core.i18n 연동 작업 시 참조
**작성 브랜치:** feature/account/init

---

## 1. 전체 현황 (2026-05-31 기준)

### 서비스별 상태

| 항목 | account | data | club | shop | analytics | community | blog |
|------|---------|------|------|------|-----------|-----------|------|
| **워크트리** | 메인 repo | FencingMind-data | FencingMind-club | FencingMind-shop | FencingMind-analytics | FencingMind-community | FencingMind-blog |
| **브랜치** | feature/account/init | feature/data/main | feature/club/main | feature/shop/main | feature/analytics/main | feature/community/main | feature/blog/main |
| **i18n 모듈** | 자체 구현 | 자체 구현 | 자체 구현 | 자체 구현 | 자체 구현 | 없음 (stub) | 없음 (stub) |
| **언어 수** | 7개 | 7개 | 2개 (en,ko) | 2개 (ko,en) | 2개 (ko,en) | - | - |
| **LANG_THEME_MAP** | O | X | X | X | X | - | - |
| **data-theme 속성** | O | X | X | X | X | - | - |
| **로고** | PNG (light+dark) | PNG (dark만) | 이모지 | 비공식 PNG | PNG (light+dark) | 없음 | 없음 |
| **파비콘** | O | O | O (PWA 포함) | X (PNG 대용) | X | 없음 | 없음 |
| **shared_core.i18n** | X (자체) | X (자체) | X (자체) | X (자체) | X (자체) | - | - |
| **shared-ui CSS** | O | X | X | X | X | - | - |

### 서비스별 i18n 구조 상세

**account** — `services/account/app/i18n/`
- `manager.py` + `middleware.py` (자체 구현)
- `translations/{ko,en,fr,it,ja,zh,tr}/{common,auth,account,admin}.json`
- LANG_THEME_MAP 있음, data-theme 있음

**data** — `services/data/app/i18n/`
- `manager.py` + `middleware.py` (자체 구현)
- `auto_translate.py`, `competition_names.py`, `event_translator.py` (서비스 고유 모듈)
- `translations/{ko,en,fr,it,ja,zh,tr}/common.json`
- 7개 언어 폴더 있으나 LANG_THEME_MAP 없음, dark 테마 고정

**club** — `services/club/app/i18n/`
- `__init__.py` (자체 TranslationManager 포함) + `middleware.py`
- `locales/en.json`, `locales/ko.json` (flat 구조, 151개 키)
- DEFAULT_LANGUAGE = 'en'

**shop** — `services/shop/app/i18n/`
- `translations.py` (Translator 클래스) + `__init__.py`
- `ko.json`, `en.json` (flat 파일, 188개 키)
- LanguageMiddleware 없음 (server.py에서 수동 감지)

**analytics** — `services/analytics/app/i18n/`
- `manager.py` (자체 TranslationManager) + `__init__.py`
- `translations/ko/analytics.json`, `translations/en/analytics.json`
- LanguageMiddleware 없음 (server.py에서 _get_lang() 함수로 수동 감지)

**community / blog** — 서비스 코드 없음 (CLAUDE.md만 존재)

---

## 2. 완료된 공유 인프라

### shared_core.i18n 모듈 (`packages/shared_core/i18n/`)

```
packages/shared_core/i18n/
├── __init__.py          # 전체 export
├── constants.py         # SUPPORTED_LANGUAGES, LANG_THEME_MAP, LANGUAGE_NAMES
├── manager.py           # TranslationManager (deep merge 지원)
├── middleware.py         # LanguageMiddleware (테마 자동 설정)
└── translations/        # 공유 번역 (7개 언어)
    ├── ko/common.json   # 한국어 (실제 번역)
    ├── en/common.json   # 영어 (실제 번역)
    ├── fr/common.json   # en 복사 (추후 번역)
    ├── it/common.json   # en 복사
    ├── ja/common.json   # en 복사
    ├── zh/common.json   # en 복사
    └── tr/common.json   # en 복사
```

**핵심 기능:**
- `SUPPORTED_LANGUAGES` = `['ko', 'en', 'fr', 'it', 'ja', 'zh', 'tr']`
- `LANG_THEME_MAP` = `{'ko': 'light', 'ja': 'light', 'zh': 'light', 'en': 'dark', 'fr': 'dark', 'it': 'dark', 'tr': 'dark'}`
- `TranslationManager(extra_dirs=[...])` — 공유 번역 + 서비스별 번역 deep merge
- `LanguageMiddleware(app, i18n=...)` — 언어 감지 + `request.state.theme` 자동 설정
- `create_language_context(request)` — Jinja2 템플릿 컨텍스트 생성
- Fallback 순서: 요청 언어 → en → ko → 키 자체

### shared-ui CSS (`packages/shared-ui/styles/`)

```css
/* variables.css — 테마별 CSS 변수 */
[data-theme="light"] { --fm-bg-primary: #ffffff; ... }
[data-theme="dark"]  { --fm-bg-primary: #0a0a0f; ... }

/* base.css — 기본 스타일 */
/* components.css — fm-btn, fm-card, fm-table 등 */
```

### 로고 원본 (`services/logo/`)

| 서비스 | Light 테마용 (검정 텍스트) | Dark 테마용 (흰색 텍스트) |
|--------|--------------------------|--------------------------|
| account | FencingMind_logo_long.png | FencingMind_logo_long_white.png |
| data | FencingMind_logo_long_Tracker.png | FencingMind_logo_long_Tracker_white.png |
| club | FencingMind_logo_long_Club.png | FencingMind_logo_long_Club_white.png |
| shop | FencingMind_logo_long_Shop.png | FencingMind_logo_long_Shop_white.png |
| community | FencingMind_logo_long.png (기본) | FencingMind_logo_long_white.png (기본) |
| blog | FencingMind_logo_long.png (기본) | FencingMind_logo_long_white.png (기본) |
| analytics | FencingMind_logo_long.png (기본) | FencingMind_logo_long_white.png (기본) |

파비콘: `services/logo/favicon.ico` (3.0K, 16x16+32x32)

---

## 3. 각 서비스 워크트리 작업 가이드

### Step 1: server.py — shared_core.i18n 연동

**변경 전** (각 서비스의 현재 상태):
```python
# data/club: 자체 미들웨어 사용
from app.i18n import LanguageMiddleware
app.add_middleware(LanguageMiddleware)

# shop/analytics: 미들웨어 없이 수동 감지
# (별도 LanguageMiddleware 없음)
```

**변경 후** (모든 서비스 공통):
```python
from shared_core.i18n import LanguageMiddleware, create_shared_i18n
from pathlib import Path

# 서비스별 번역 디렉토리 경로
SERVICE_I18N_DIR = Path(__file__).parent / "i18n" / "translations"

# 공유 번역 + 서비스별 번역 병합
i18n = create_shared_i18n(extra_dirs=[SERVICE_I18N_DIR])

# 미들웨어 등록 (CORS보다 먼저)
app.add_middleware(LanguageMiddleware, i18n=i18n)
```

**주의:** data 서비스의 `auto_translate.py`, `competition_names.py`, `event_translator.py`는 서비스 고유 모듈이므로 그대로 유지. `LanguageMiddleware`와 `TranslationManager`만 교체.

### Step 2: 번역 파일 구조 정리

각 서비스별로 번역 파일 구조를 통일:

```
app/i18n/translations/
├── ko/
│   └── {service}.json    # 서비스 고유 번역 (한국어)
├── en/
│   └── {service}.json    # 서비스 고유 번역 (영어)
├── fr/
│   └── {service}.json    # en 복사 (추후 번역)
├── it/
│   └── {service}.json
├── ja/
│   └── {service}.json
├── zh/
│   └── {service}.json
└── tr/
    └── {service}.json
```

**서비스별 마이그레이션:**

| 서비스 | 현재 구조 | 변경 내용 |
|--------|----------|----------|
| **data** | `translations/{lang}/common.json` (7개 언어) | 구조 유지, common.json → 서비스 고유 키만 남기기 (공유 키는 shared_core에서 로드) |
| **club** | `locales/en.json`, `locales/ko.json` | `translations/{lang}/club.json`으로 재배치 + 5개 언어 추가 |
| **shop** | `ko.json`, `en.json` (flat) | `translations/{lang}/shop.json`으로 재배치 + 5개 언어 추가 |
| **analytics** | `translations/{ko,en}/analytics.json` | 구조 유지 + 5개 언어 추가 |
| **community** | 없음 | `translations/{lang}/community.json` 신규 생성 |
| **blog** | 없음 | `translations/{lang}/blog.json` 신규 생성 |

**새 언어 추가 방법** (fr, it, ja, zh, tr):
```bash
# en 파일을 복사하여 생성 (추후 실제 번역)
for lang in fr it ja zh tr; do
  mkdir -p app/i18n/translations/$lang
  cp app/i18n/translations/en/*.json app/i18n/translations/$lang/
done
```

### Step 3: base.html — 테마 분기

**`<html>` 태그에 data-theme 추가:**
```html
<!-- 변경 전 -->
<html lang="{{ lang|default('ko') }}">

<!-- 변경 후 -->
<html lang="{{ lang|default('ko') }}" data-theme="{{ theme|default('dark') }}">
```

**로고 테마 분기:**
```html
<!-- 변경 전 (예: data 서비스) -->
<img src="/static/images/logo/FencingMind_logo_long_Tracker.png" alt="FencingMind Tracker">

<!-- 변경 후 -->
{% if theme == 'dark' %}
<img src="/static/images/logo/FencingMind_logo_long_Tracker_white.png"
     alt="FencingMind Tracker" class="logo-img">
{% else %}
<img src="/static/images/logo/FencingMind_logo_long_Tracker.png"
     alt="FencingMind Tracker" class="logo-img">
{% endif %}
```

**언어 전환 UI (7개 언어):**
```html
<div class="lang-switch">
    {% for code in supported_langs %}
    <a href="?lang={{ code }}"
       class="lang-btn {{ 'active' if lang == code }}"
       title="{{ language_names[code] }}">
        {{ code|upper }}
    </a>
    {% endfor %}
</div>
```

### Step 4: 로고 & 파비콘 배포

```bash
# 프로젝트 루트에서 실행 (해당 서비스 워크트리에서)

# 로고 복사 (서비스별 — 아래는 data 예시)
mkdir -p services/data/static/images/logo/
cp services/logo/FencingMind_logo_long_Tracker.png services/data/static/images/logo/
cp services/logo/FencingMind_logo_long_Tracker_white.png services/data/static/images/logo/

# 파비콘 복사
cp services/logo/favicon.ico services/data/static/images/logo/favicon.ico
# 또는 packages/shared-ui/에서 복사
cp packages/shared-ui/favicon-32.png services/data/static/images/logo/
cp packages/shared-ui/apple-touch-icon.png services/data/static/images/logo/
```

**서비스별 로고 파일명:**

| 서비스 | cp 명령 (light) | cp 명령 (dark/white) |
|--------|----------------|---------------------|
| data | `cp services/logo/FencingMind_logo_long_Tracker.png ...` | `cp services/logo/FencingMind_logo_long_Tracker_white.png ...` |
| club | `cp services/logo/FencingMind_logo_long_Club.png ...` | `cp services/logo/FencingMind_logo_long_Club_white.png ...` |
| shop | `cp services/logo/FencingMind_logo_long_Shop.png ...` | `cp services/logo/FencingMind_logo_long_Shop_white.png ...` |
| analytics | `cp services/logo/FencingMind_logo_long.png ...` | `cp services/logo/FencingMind_logo_long_white.png ...` |
| community | `cp services/logo/FencingMind_logo_long.png ...` | `cp services/logo/FencingMind_logo_long_white.png ...` |
| blog | `cp services/logo/FencingMind_logo_long.png ...` | `cp services/logo/FencingMind_logo_long_white.png ...` |

### Step 5: CSS 테마 대응

**옵션 A: shared-ui CSS 사용 (권장)**
```html
<link rel="stylesheet" href="/packages/shared-ui/styles/variables.css">
<link rel="stylesheet" href="/packages/shared-ui/styles/base.css">
<link rel="stylesheet" href="/packages/shared-ui/styles/components.css">
```
- `[data-theme="light"]`와 `[data-theme="dark"]` CSS 변수가 자동 전환

**옵션 B: 기존 CSS에 테마 변수 추가**
```css
/* 기존 dark-theme.css 앞에 추가 */
[data-theme="light"] {
    --bg-primary: #ffffff;
    --bg-secondary: #f5f5f7;
    --text-primary: #1d1d1f;
    --text-secondary: #6e6e73;
    --accent-primary: #c9302c;
    --accent-secondary: #1e3a8a;
}

[data-theme="dark"] {
    --bg-primary: #0a0a0f;
    --bg-secondary: #12121a;
    --text-primary: #ffffff;
    --text-secondary: #b4b4c4;
    --accent-primary: #c9302c;
    --accent-secondary: #1e3a8a;
}
```

### Step 6: 라우터에서 템플릿 컨텍스트

```python
from shared_core.i18n import create_language_context

@router.get("/page")
async def page(request: Request):
    return templates.TemplateResponse("page.html", {
        "request": request,
        **create_language_context(request),
        # 페이지 고유 데이터...
    })
```

`create_language_context(request)` 반환값:
```python
{
    'lang': 'ko',                    # 현재 언어
    'theme': 'light',                # 현재 테마 (언어 기반)
    't': <translator function>,      # t('common.nav.login') → '로그인'
    'supported_langs': ['ko', 'en', 'fr', 'it', 'ja', 'zh', 'tr'],
    'language_names': {'ko': '한국어', 'en': 'English', ...},
    'i18n': { ... },                 # 전체 번역 데이터
}
```

---

## 4. 서비스별 체크리스트

### data 서비스 (`FencingMind-data`)
- [ ] `server.py`: `app.i18n.LanguageMiddleware` → `shared_core.i18n.LanguageMiddleware` 교체
- [ ] `server.py`: `create_shared_i18n(extra_dirs=[...])` 사용
- [ ] `base.html`: `<html data-theme="{{ theme }}">` 추가
- [ ] 로고: `FencingMind_logo_long_Tracker_white.png` 복사 (dark용)
- [ ] 로고: base.html에서 theme 분기 적용
- [ ] CSS: light 테마 변수 추가 (또는 shared-ui 연동)
- [ ] `auto_translate.py`, `competition_names.py`, `event_translator.py` 유지 (서비스 고유)
- [ ] 번역 common.json에서 shared_core와 중복되는 키 제거 (deep merge로 자동 로드)

### club 서비스 (`FencingMind-club`)
- [ ] `locales/` → `translations/{lang}/club.json` 구조 변경
- [ ] 5개 언어 추가 (fr, it, ja, zh, tr)
- [ ] `server.py`: 자체 i18n → `shared_core.i18n` 교체
- [ ] `base.html`: `<html data-theme="{{ theme }}">` 추가
- [ ] 로고: 이모지 → `FencingMind_logo_long_Club.png` / `_white.png` 교체
- [ ] CSS: light 테마 변수 추가
- [ ] 언어 전환 UI: 2개 → 7개 확장

### shop 서비스 (`FencingMind-shop`)
- [ ] `ko.json`, `en.json` → `translations/{lang}/shop.json` 구조 변경
- [ ] `translations.py` 제거 → `shared_core.i18n` 사용
- [ ] 5개 언어 추가 (fr, it, ja, zh, tr)
- [ ] `server.py`: LanguageMiddleware 추가
- [ ] `index.html`: `<html data-theme="{{ theme }}">` 추가
- [ ] 로고: `logo-horizontal.png` → 공식 `FencingMind_logo_long_Shop.png` / `_white.png` 교체
- [ ] 파비콘: `logo-square.png` → 전용 favicon.ico 교체
- [ ] CSS: light 테마 변수 추가

### analytics 서비스 (`FencingMind-analytics`)
- [ ] 자체 `manager.py` 제거 → `shared_core.i18n` 사용
- [ ] `server.py`: `_get_lang()` 함수 → LanguageMiddleware 교체
- [ ] 5개 언어 추가 (fr, it, ja, zh, tr)
- [ ] `base.html`: `<html data-theme="{{ theme }}">` 추가
- [ ] 로고: theme 분기 적용 (light/dark 파일 이미 있음)
- [ ] 파비콘 추가 (현재 없음)
- [ ] CSS: light 테마 변수 추가
- [ ] 언어 전환 UI: 2개 → 7개 확장

### community 서비스 (`FencingMind-community`)
- [ ] 서비스 코드 신규 구축 (현재 stub)
- [ ] 처음부터 `shared_core.i18n` 사용
- [ ] `translations/{lang}/community.json` 생성
- [ ] 로고: `FencingMind_logo_long.png` / `_white.png` 복사
- [ ] 파비콘 복사

### blog 서비스 (`FencingMind-blog`)
- [ ] 서비스 코드 신규 구축 (현재 stub)
- [ ] 처음부터 `shared_core.i18n` 사용
- [ ] `translations/{lang}/blog.json` 생성
- [ ] 로고: `FencingMind_logo_long.png` / `_white.png` 복사
- [ ] 파비콘 복사

---

## 5. 검증 방법

각 서비스에서 작업 완료 후:

```bash
# 1. Python import 테스트
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/{service}" \
  python -c "from shared_core.i18n import SUPPORTED_LANGUAGES, LANG_THEME_MAP; print(len(SUPPORTED_LANGUAGES), '언어')"
# 기대 결과: 7 언어

# 2. 서버 실행 테스트
PYTHONPATH="${PWD}:${PWD}/packages:${PWD}/services/{service}" \
  python -m uvicorn services.{service}.app.server:app --host 0.0.0.0 --port {port}

# 3. 테마 확인 (브라우저에서)
# http://localhost:{port}/?lang=ko  → data-theme="light" 확인
# http://localhost:{port}/?lang=en  → data-theme="dark" 확인
# http://localhost:{port}/?lang=ja  → data-theme="light" 확인
# http://localhost:{port}/?lang=fr  → data-theme="dark" 확인

# 4. 로고 확인
# light 테마 → 검정 텍스트 로고 표시
# dark 테마 → 흰색 텍스트 로고 표시

# 5. 번역 파일 수 확인
ls app/i18n/translations/*/  # 7개 언어 디렉토리 존재 확인
```

---

## 6. 주의사항

1. **shared_core.i18n의 공유 번역 키는 서비스별 번역에서 제거** — deep merge로 자동 로드되므로 중복 불필요. 서비스 고유 키만 서비스별 JSON에 유지.

2. **기존 자체 i18n 모듈을 바로 삭제하지 말 것** — shared_core.i18n 연동 후 동작 확인이 끝나면 제거.

3. **data 서비스의 auto_translate.py, competition_names.py, event_translator.py는 유지** — 이들은 번역 인프라가 아니라 대회/이벤트 이름 번역 로직이므로 shared_core와 무관.

4. **미번역 언어 파일은 en 복사본으로 생성** — 실제 번역은 추후 진행. fallback 순서(요청 언어 → en → ko)로 자동 처리됨.

5. **CSS 색상 하드코딩 금지** — `--fm-*` 또는 `--bg-*`, `--text-*` 등 CSS 변수 사용. 테마 전환 시 변수값만 바뀌어야 함.
