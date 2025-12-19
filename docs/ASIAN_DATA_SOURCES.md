# Asian Fencing Data Sources Research

## Summary

| Country | Federation | Website | Data Access | Scraping Difficulty |
|---------|------------|---------|-------------|---------------------|
| Japan | FJE | fencing-jpn.jp | DataTables + External Links | Medium |
| Hong Kong | HKFA | hkfa.org.hk | PDF Files + HTML Tables | Low-Medium |
| Singapore | SFA | fencingsingapore.org.sg | FencingTimeLive + PDFs | Medium |

---

## Japan Fencing Federation (JFA/FJE)

### Official Website
- **URL**: https://fencing-jpn.jp/
- **Competition Page**: https://fencing-jpn.jp/competition/
- **FIE Page**: https://fie.org/country/jpn

### Data Structure
The competition page uses **DataTables** JavaScript library with the following fields:
- Competition name (大会名)
- Venue (会場)
- Start/End date (開催日)
- Weapon type: F/E/S (Foil/Epee/Sabre)
- Gender: M/F
- Category: Junior/Cadet/Senior/Minimus

### Result Access Methods
1. **Direct Result Pages**: Links labeled "大会情報" (competition information)
2. **Live Timing**: Integration with fencingtimelive.com
3. **External Sites**: escrime.jp for certain competitions
4. **Custom Domains**: liveresult-szo.main.jp for specific tournaments

### Technical Notes
- Pagination: 50 results per page
- Language: Japanese UI
- Responsive design
- Sortable columns

### Scraping Strategy
```python
# Approach for Japan
1. Scrape competition list from /competition/ using DataTables API
2. Follow "大会情報" links to individual result pages
3. Parse results from:
   - fencingtimelive.com API (if available)
   - escrime.jp pages
   - liveresult-szo.main.jp pages
4. Handle multiple external sources
```

### Challenges
- Multiple external result platforms
- Japanese text encoding
- Dynamic DataTables loading
- External live timing systems

---

## Hong Kong Fencing Association (HKFA)

### Official Website
- **URL**: http://www.hkfa.org.hk/
- **Results Page**: http://hkfa.org.hk/EN/results.html
- **FIE Page**: https://fie.org/country/HKG

### Data Format
Results are primarily available as **PDF files**:
- Under 20 Championships: `/results/24_U20results.pdf`
- Competition Calendar: `/notice_competition-calendar_e.pdf`
- Overseas Competition: `/notice_overseas-competition-calendar.pdf`

### Competition Categories
- Age Group Fencing Championships
- Under-20 Fencing Championships
- Challenge Cups Fencing Championships
- President's Cup Fencing Championships
- Hong Kong Junior Open Fencing Championships

### Available Data Fields (from U20 results)
- Rank
- Fencer name
- Club/School affiliation
- Points/Scores

### Technical Notes
- Website has **expired SSL certificate** (may need HTTP fallback)
- Mix of Chinese and English content
- PDF-based results require PDF parsing
- Bilingual (Traditional Chinese/English)

### Scraping Strategy
```python
# Approach for Hong Kong
1. Scrape results page for PDF links
2. Download and parse PDFs using PyMuPDF or pdfplumber
3. Extract tabular data from PDF tables
4. Handle both English and Chinese text
5. Map club names to standardized format
```

### Challenges
- SSL certificate issues
- PDF parsing complexity
- Mixed language content
- Historical data availability

---

## Singapore Fencing Association (SFA)

### Official Website
- **URL**: https://www.fencingsingapore.org.sg/
- **Results Page**: https://www.fencingsingapore.org.sg/competitions-results/
- **Upcoming**: https://www.fencingsingapore.org.sg/competitions/

### Data Format
- **Live Results**: FencingTimeLive integration (fencingtimelive.com)
- **Result Files**: Downloadable files linked from results page
- **Seasons**: Organized by academic year (2024/2025)

### Competition Categories
- Singapore Senior Trials
- Singapore Junior Trials
- Singapore Cadet Trials
- Singapore Open (by weapon)

### Technical Notes
- Modern WordPress-based website
- Good English content
- Organized by season/year
- External live timing integration

### School Competitions
- National School Games (NSG) has separate system
- MOE tracks school-level competitions
- URL: https://nsg.moe.edu.sg/sssc/fencing

### Scraping Strategy
```python
# Approach for Singapore
1. Scrape results page for competition links
2. Parse result file links (likely PDF/Excel)
3. Integrate with FencingTimeLive API if available
4. Handle both SFA and school competitions separately
```

### Challenges
- External live timing system
- School vs federation competitions
- Result file format variations

---

## Common Tools & Platforms

### FencingTimeLive
- Used by: Japan, Singapore
- URL: fencingtimelive.com
- Provides real-time competition results
- May have API access

### Engarde-Service
- Competition management platform
- URL: engarde-service.com
- Used by many Asian federations
- Standardized result format

### FIE Integration
All three countries have FIE pages with international results:
- Japan: https://fie.org/country/jpn
- Hong Kong: https://fie.org/country/HKG
- Singapore: https://fie.org/country/SGP

---

## Implementation Priority

### Phase 1: Japan (Weeks 5-8)
**Rationale**: Largest market, active fencing community, Paris 2024 gold medalists
**Complexity**: Medium (multiple external sources)
**Data Volume**: High

### Phase 2: Hong Kong (Weeks 9-10)
**Rationale**: Good English content, Traditional Chinese for regional expansion
**Complexity**: Low-Medium (PDF parsing)
**Data Volume**: Medium

### Phase 3: Singapore (Weeks 11-12)
**Rationale**: English-first, modern website, regional hub
**Complexity**: Medium (FencingTimeLive integration)
**Data Volume**: Medium

---

## Technical Requirements

### For Japan Scraper
```python
dependencies = [
    "playwright",      # For dynamic JS pages
    "httpx",          # For API calls
    "beautifulsoup4",  # For HTML parsing
]
```

### For Hong Kong Scraper
```python
dependencies = [
    "httpx",          # For downloads (handle SSL issues)
    "pdfplumber",     # For PDF parsing
    "beautifulsoup4", # For HTML parsing
]
```

### For Singapore Scraper
```python
dependencies = [
    "httpx",          # For API calls
    "beautifulsoup4", # For HTML parsing
    "pandas",         # For tabular data handling
]
```

---

## Data Standardization

### Player Name Handling
| Country | Format | Example |
|---------|--------|---------|
| Japan | Kanji + Romaji | 田中太郎 / TANAKA Taro |
| Hong Kong | Chinese + English | 陳大明 / CHAN Tai Ming |
| Singapore | English | TAN Wei Ming |

### Club/Team Names
Create mapping tables for:
- Japanese clubs → standardized names
- Hong Kong schools/clubs → standardized names
- Singapore clubs → standardized names

### Competition Types
Standardize across regions:
```yaml
standard_types:
  national_championship: "National Championship"
  junior_championship: "Junior Championship"
  cadet_championship: "Cadet Championship"
  open_tournament: "Open Tournament"
  trials: "Selection Trials"
```

---

## Sources

- [Japan Fencing Federation](https://fencing-jpn.jp/)
- [Hong Kong Fencing Association](http://hkfa.org.hk/)
- [Fencing Singapore](https://www.fencingsingapore.org.sg/)
- [FIE - International Fencing Federation](https://fie.org/)
- [FencingTimeLive](https://fencingtimelive.com/)
