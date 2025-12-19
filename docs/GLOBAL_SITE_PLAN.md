# Global Fencing Tracker - Site Structure & i18n Plan

## Overview

Expansion of Korean Fencing Tracker to cover multiple Asian countries/regions with multilingual support.

## Target Markets

### Primary Markets (Phase 1)
| Country/Region | Language | Fencing Federation | Data Source |
|---------------|----------|-------------------|-------------|
| Korea | Korean | KFF (대한펜싱협회) | fencing.sports.or.kr |
| Japan | Japanese | JFA (日本フェンシング協会) | fencing-jpn.jp |
| Hong Kong | Traditional Chinese | HKFA | hkfencing.org.hk |
| Singapore | English | SFA | singaporefencing.org.sg |

### Secondary Markets (Phase 2)
| Country/Region | Language | Notes |
|---------------|----------|-------|
| Thailand | Thai | Thai Fencing Association |
| Taiwan | Traditional Chinese | Shared with HK locale |
| Malaysia | English/Malay | Close to Singapore |
| China | Simplified Chinese | CFA (中国击剑协会) |

### About Turkey
**Turkey is NOT in Asian Fencing Confederation (AFC).**
- Turkey belongs to **European Fencing Confederation (EFC)**
- Turkey competes in European championships and qualifications
- Not included in our Asian Fencing Tracker scope

## Language Strategy

### Default: English
All fencing-specific terminology remains in English globally:
- Weapons: Foil, Epee, Sabre
- Actions: Touche, Riposte, Parry
- Formats: Direct Elimination (DE), Pool, Tableau
- Rankings: Seeding, Final Ranking

### Per-Region Localization

#### English (Default) - `en`
```yaml
ui_language: English
fencing_terms: English
dates: YYYY-MM-DD
numbers: 1,234.56
```

#### Korean - `ko`
```yaml
ui_language: Korean (essential UI only)
fencing_terms: English (with Korean glossary available)
dates: YYYY년 M월 D일
numbers: 1,234.56
special_notes:
  - Main navigation in English
  - Only essential labels in Korean (e.g., "Search", "Results")
  - Fencing terms always in English
```

#### Japanese - `ja`
```yaml
ui_language: Japanese
fencing_terms: English (with Japanese glossary)
dates: YYYY年M月D日
numbers: 1,234.56
```

#### Chinese Traditional (Hong Kong) - `zh-HK`
```yaml
ui_language: Traditional Chinese
fencing_terms: English (with Chinese glossary)
dates: YYYY年M月D日
numbers: 1,234.56
```

#### Thai - `th`
```yaml
ui_language: Thai
fencing_terms: English (with Thai glossary)
dates: D/M/YYYY (Buddhist Era optional)
numbers: 1,234.56
```

## Site Architecture

### URL Structure
```
fencingtracker.asia/
├── /                          # Default (English, all regions)
├── /kr/                       # Korea-specific content
├── /jp/                       # Japan-specific content
├── /hk/                       # Hong Kong-specific content
├── /sg/                       # Singapore-specific content
├── /th/                       # Thailand-specific content
│
├── /en/                       # English UI override
├── /ko/                       # Korean UI override
├── /ja/                       # Japanese UI override
├── /zh-hk/                    # Chinese (HK) UI override
├── /th/                       # Thai UI override
│
├── /player/{player_id}        # Global player profile
├── /competition/{comp_id}     # Competition detail
├── /rankings                  # Multi-region rankings
└── /api/                      # API endpoints
```

### Data Architecture
```
Global Player Database
├── player_id (global unique)
├── names[]
│   ├── {lang: "ko", name: "김철수", romanized: "Kim Cheol-su"}
│   ├── {lang: "ja", name: "田中太郎", romanized: "Tanaka Taro"}
│   └── {lang: "en", name: "Kim Cheol-su"}
├── country_code (KO, JP, HK, SG, TH)
├── federation_id
├── results[] (linked to competitions)
└── rankings_by_region[]
```

### Multi-Region Competition Model
```python
class Competition:
    comp_id: str           # Global unique ID
    region: str            # KR, JP, HK, SG, TH
    federation_id: str     # Original federation ID
    names: Dict[str, str]  # {en: "...", ko: "...", ja: "..."}
    events: List[Event]

class Event:
    event_id: str
    weapon: str            # Always in English
    gender: str            # M/F
    age_group: str         # Standardized (Y10-Y12, Y14, Y17, Senior, Veteran)
    participants: List[Participant]
    results: List[Result]
```

## Implementation Plan

### Phase 1: Foundation (Week 1-2)
1. **i18n Setup**
   - Install flask-babel or fastapi equivalent
   - Create translation files structure
   - Implement language detection middleware

2. **Database Schema Update**
   - Add multi-language fields to models
   - Add region/federation fields
   - Create player identity linking tables

3. **API Expansion**
   - Add `?lang=` parameter to all endpoints
   - Create `/api/regions` endpoint
   - Standardize response format

### Phase 2: Korea Enhancement (Week 3-4)
1. Apply English-first terminology
2. Add Korean UI translations (minimal)
3. Test bilingual display
4. Optimize for Korean users

### Phase 3: Japan Integration (Week 5-8)
1. Research JFA data source
2. Build Japan scraper
3. Player identity resolution (Japanese names)
4. Japanese UI translations

### Phase 4: Hong Kong & Singapore (Week 9-12)
1. Build regional scrapers
2. Chinese Traditional translations
3. Cross-region player linking
4. Regional ranking calculations

### Phase 5: Thailand & Expansion (Week 13+)
1. Thai localization
2. Additional ASEAN markets
3. Cross-region search
4. Global rankings

## Technical Implementation

### i18n Library Choice: `python-i18n` or `Babel`

```python
# Translation file structure
translations/
├── en/
│   └── LC_MESSAGES/
│       ├── messages.po
│       └── messages.mo
├── ko/
├── ja/
├── zh_HK/
└── th/
```

### Translation Keys Example
```yaml
# en/messages.yaml
nav:
  home: "Home"
  search: "Search"
  rankings: "Rankings"
  competitions: "Competitions"

fencing:
  weapons:
    foil: "Foil"
    epee: "Epee"
    sabre: "Sabre"

results:
  final_ranking: "Final Ranking"
  pool_results: "Pool Results"
  direct_elimination: "Direct Elimination"
```

```yaml
# ko/messages.yaml
nav:
  home: "홈"
  search: "검색"
  rankings: "랭킹"
  competitions: "대회"

fencing:
  # Kept in English for consistency
  weapons:
    foil: "Foil"
    epee: "Epee"
    sabre: "Sabre"

results:
  final_ranking: "Final Ranking"
  pool_results: "Pool Results"
  direct_elimination: "Direct Elimination"
```

### Language Detection Logic
```python
def detect_language(request):
    # Priority order:
    # 1. URL parameter (?lang=ko)
    # 2. URL prefix (/ko/)
    # 3. Cookie preference
    # 4. Accept-Language header
    # 5. Geolocation (country -> default language)
    # 6. Default: English
    pass
```

### Database Multi-language Fields
```python
class Competition(Base):
    __tablename__ = "competitions"

    id = Column(String, primary_key=True)
    region = Column(String, index=True)  # KR, JP, HK, SG, TH

    # Multi-language name stored as JSON
    name_translations = Column(JSON)  # {"en": "...", "ko": "...", "ja": "..."}

    # Original name from source
    original_name = Column(String)
    original_lang = Column(String)
```

## Testing Strategy

### i18n Tests
- All UI strings are translated
- Date/number formatting per locale
- RTL support (if needed in future)
- Character encoding (UTF-8 throughout)

### Regional Tests
- Data scraping for each region
- Player identity matching
- Cross-region search
- Regional ranking calculations

## Deployment Considerations

### CDN & Geo-Routing
- Use Cloudflare or similar for geo-based routing
- Cache per-language versions
- Asset optimization per region

### Domain Strategy
Option A: Single domain with subdirectories
```
fencingtracker.asia/kr/
fencingtracker.asia/jp/
```

Option B: Regional subdomains
```
kr.fencingtracker.asia
jp.fencingtracker.asia
```

**Recommendation**: Option A (subdirectories) for easier SEO and management.

## Glossary - Fencing Terms (Standard English)

### Competition Types
| English | Korean | Japanese | Chinese (HK) | Thai |
|---------|--------|----------|--------------|------|
| Competition | 대회 | 大会 | 比賽 | การแข่งขัน |
| Championship | 선수권대회 | 選手権大会 | 錦標賽 | ชิงแชมป์ |
| Open | 오픈 | オープン | 公開賽 | เปิด |

### Weapons (Keep in English)
- Foil (플러레, フルーレ, 花劍, ฟอยล์)
- Epee (에뻬, エペ, 重劍, อีเป้)
- Sabre (사브르, サーブル, 佩劍, เซเบอร์)

### Age Groups (Standardized)
| Code | Description | Age Range |
|------|-------------|-----------|
| Y10 | Cadet | U-10 |
| Y12 | Youth | U-12 |
| Y14 | Junior | U-14 |
| Y17 | Senior | U-17 |
| Senior | Adult | 17+ |
| Veteran | Veteran | 40+ |

## Next Steps

1. [ ] Set up translation file structure
2. [ ] Implement language detection middleware
3. [ ] Update database schema for multi-region
4. [ ] Create Korean i18n (minimal UI)
5. [ ] Research Japan data source
6. [ ] Research Hong Kong data source
7. [ ] Research Singapore data source
8. [ ] Implement first cross-region player search
