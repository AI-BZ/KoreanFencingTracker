# Team Address Data Collection Research Report

**Date**: 2025-12-18
**Objective**: Research methods to collect organization/team address data (국가, 시도, 구, 도로주소, 세부주소) for Korean fencing teams

---

## Executive Summary

After comprehensive investigation of the Korean Fencing Association website and alternative data sources, **detailed address information is NOT readily available through public scraping**. However, several potential data collection methods have been identified with varying levels of feasibility.

### Key Findings
1. **Primary Source** (fencing.sports.or.kr): Team directory exists but addresses are NOT visible in public listings
2. **Alternative Methods**: Multiple viable approaches through government APIs and databases
3. **Recommended Strategy**: Hybrid approach combining multiple data sources

---

## 1. Korean Fencing Association Website Analysis

### 1.1 Team Search Page Structure

**URL**: https://fencing.sports.or.kr/team/teamSearchList

**Available Search Filters**:
- Team Type: 전체/전문/동호인 (All/Professional/Amateur)
- Region: 16 provinces (Seoul, Incheon, Gyeonggi, Gangwon, etc.)
- Gender: 전체/남자팀/여자팀/혼성팀 (All/Male/Female/Mixed)
- Division: 전체/초등부/중등부/고등부/대학부/실업(일반) (All/Elementary/Middle/High/University/Professional)
- Team Name: Text search

**Publicly Visible Information**:
| Field | Available | Notes |
|-------|-----------|-------|
| Team Name | ✅ Yes | Clickable |
| Team Type | ✅ Yes | Professional/Amateur |
| Division | ✅ Yes | Elementary/Middle/High/University/Pro |
| Region | ✅ Yes | Province level only |
| Phone | ✅ Yes | Contact number |
| Member Count | ✅ Yes | Registered athletes |
| **Detailed Address** | ❌ **NO** | **Not visible in public listings** |

**Team Detail Popup**:
- Clicking team names triggers AJAX popups (`amaOpenLayer` or `proOpenLayer` functions)
- May contain additional data (homepage URL confirmed)
- **Unconfirmed**: Whether full addresses appear in popups (requires authentication or logged-in access)

### 1.2 Affiliated Organizations Page

**URL**: https://fencing.sports.or.kr/group/groupIntro3
**Status**: Returns 404 error (page not found or access restricted)

### 1.3 Competition Results Pages

**Current Scraper**: `scraper/playwright_scraper.py`
**Data Collected**: Competitions, events, matches, player names, team names
**Address Data**: Team names only, no address information embedded

---

## 2. Alternative Data Sources

### 2.1 Korea Sports Council (대한체육회) - G1 Portal

**Portal**: https://g1.sports.or.kr/
**Relevance**: ⭐⭐⭐⭐⭐ (Highest)

**Available Services**:
- Team registration system (팀등록신청)
- Player registration database
- School team registration status (https://g1.sports.or.kr/stat/stat08.do)

**Address Data Potential**:
- ✅ Centralized sports registration system
- ✅ Official team registry including fencing teams
- ⚠️ **Requires authentication** for detailed access
- ✅ Likely contains full organizational addresses

**Recommended Action**:
1. Register for API access through g1.sports.or.kr
2. Explore authenticated endpoints for team detail information
3. Check if batch export or API endpoints are available

**References**:
- [G1 Sports Portal](https://g1.sports.or.kr/)
- [School Team Registration Status](https://g1.sports.or.kr/stat/stat08.do)

---

### 2.2 NEIS Education Information Portal (나이스 교육정보)

**Portal**: https://open.neis.go.kr/
**Relevance**: ⭐⭐⭐⭐ (High for school teams)

**School Basic Information API**:
- API provides: School name, location, address, phone, homepage, etc.
- **Perfect for**: Middle schools, high schools with fencing teams
- **Coverage**: All Korean educational institutions

**Implementation**:
1. Get API key from https://open.neis.go.kr/
2. Use "School Basic Information" API (학교기본정보)
3. Match school names from fencing team data to NEIS database
4. Extract full addresses for school-based teams

**API Details**:
- Service: OPEN17020190531110010104913
- Fields: 학교명, 소재지, 주소, 전화번호, 홈페이지주소
- Authentication: Free API key required (5 sample records without key)

**Limitations**:
- ❌ Only covers school teams (중등부, 고등부)
- ❌ Doesn't cover clubs, university teams, professional teams

**References**:
- [NEIS Open API Portal](https://open.neis.go.kr/portal/data/service/selectServicePage.do?infId=OPEN17020190531110010104913&infSeq=2)
- [Public Data Portal - NEIS School Info](https://www.data.go.kr/data/15122275/openapi.do)

---

### 2.3 Business Registration Number Database (사업자등록번호)

**Services**: National Tax Service API, Moneypin, BIZNO.NET
**Relevance**: ⭐⭐⭐ (Medium for clubs/professional teams)

**National Tax Service API**:
- URL: https://www.data.go.kr/tcs/dss/selectApiDataDetailView.do?publicDataPk=15081808
- Provides: Business status, tax type, representative name
- ⚠️ **Limited address info** in free tier

**Third-Party APIs** (Moneypin, BIZNO.NET, 에이픽):
- Comprehensive data: 대표자, 상호, 주소, 도로명주소, 지번주소, 위경도
- ✅ Includes detailed addresses
- ⚠️ **Requires** business registration numbers
- ⚠️ **Paid services** for bulk queries

**Implementation Strategy**:
1. Identify fencing clubs that are registered businesses
2. Obtain business registration numbers (from public records or team websites)
3. Query business APIs for full address information
4. Best for: Private clubs, professional teams, academies

**Limitations**:
- ❌ Requires knowing business registration numbers first
- ❌ Not all teams are registered businesses (school teams, amateur clubs)
- ⚠️ Cost considerations for large-scale queries

**References**:
- [National Tax Service Business Registration API](https://www.data.go.kr/tcs/dss/selectApiDataDetailView.do?publicDataPk=15081808)
- [BIZNO.NET Open API](https://bizno.net/openapi)
- [Moneypin Business Info API](https://help.moneypin.biz/035c943a06e74489a97f3e8e147129ff)

---

### 2.4 Public Sports Facility Database (공공체육시설)

**Portal**: Public Data Portal (공공데이터포털)
**Relevance**: ⭐⭐ (Low - facilities, not teams)

**Available Data**:
- National public sports facilities
- Facility names, addresses, contact info, coordinates
- Operated by local governments and sports promotion agencies

**Use Case**:
- ❌ **Not suitable** for team address collection
- ✅ Useful for mapping where competitions are held
- ✅ Could correlate team training locations (indirect)

**References**:
- [National Public Facility Open Info](https://www.data.go.kr/data/15013117/standard.do)
- [Seoul Olympic Sports Promotion - National Sports Facility Info](https://www.data.go.kr/dataset/15011222/openapi.do)

---

## 3. Recommended Implementation Strategy

### Phase 1: School Teams (Immediate - High Success Rate)

**Target**: 중등부 (Middle School), 고등부 (High School) teams

**Data Source**: NEIS Education Information Portal

**Steps**:
1. Register for NEIS API key at https://open.neis.go.kr/
2. Extract school team names from existing fencing data (`fencing_data_full.json`)
3. Match team names to school database via API
4. Retrieve full addresses for all school-based teams

**Expected Coverage**: 40-50% of all teams (school teams)

**Implementation**:
```python
# Pseudo-code
neis_api = NEISClient(api_key="YOUR_KEY")
school_teams = [team for team in teams if team.division in ["중등부", "고등부"]]

for team in school_teams:
    school_info = neis_api.get_school_by_name(team.name)
    team.address = school_info.road_address
    team.detail_address = school_info.detailed_address
```

---

### Phase 2: Professional/Club Teams (Medium - Requires Multiple Sources)

**Target**: 실업팀 (Professional), 클럽 (Clubs)

**Data Sources**:
1. G1 Sports Portal (authentication required)
2. Business registration databases (for registered clubs)
3. Manual web scraping from team websites

**Steps**:
1. **G1 Portal Access**:
   - Register account at https://g1.sports.or.kr/
   - Explore authenticated team registration endpoints
   - Check for bulk export or API access

2. **Business Database**:
   - Identify clubs with business registration
   - Query business APIs for address data
   - Cross-reference with team names

3. **Web Scraping**:
   - Many professional teams have official websites
   - Extract addresses from "About Us" or "Contact" pages
   - Examples: Seoul Fencing Club, Star Fencing Academy

**Expected Coverage**: 30-40% additional coverage

---

### Phase 3: University/Amateur Teams (Low Priority)

**Target**: 대학부 (University), 동호인 (Amateur) teams

**Data Sources**:
- University websites (manual collection)
- Amateur sports club registries (if available)
- Direct contact with teams

**Steps**:
1. Extract university team names
2. Visit university athletics department websites
3. Manually collect addresses
4. For amateur teams: May require direct outreach

**Expected Coverage**: 10-20% additional coverage

---

## 4. Technical Implementation Recommendations

### 4.1 Scraping Korean Fencing Association Popups

**Feasibility**: ⚠️ Medium (May be blocked or require authentication)

**Approach**:
```python
async def scrape_team_details(page: Page, team_name: str):
    # Click team name to trigger popup
    await page.click(f"text={team_name}")

    # Wait for AJAX popup
    await page.wait_for_selector(".team-detail-popup")

    # Extract address if available
    address = await page.query_selector(".address")
    detailed_address = await page.query_selector(".detailed-address")

    return {
        "road_address": address.text_content() if address else None,
        "detailed_address": detailed_address.text_content() if detailed_address else None
    }
```

**Risks**:
- May require login/authentication
- Popups might not contain address data
- Rate limiting or IP blocking

---

### 4.2 NEIS API Integration

**Feasibility**: ✅ High (Official public API)

**Implementation**:
```python
import requests

class NEISClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://open.neis.go.kr/hub"

    def get_school_info(self, school_name: str, region: str = None):
        params = {
            "KEY": self.api_key,
            "Type": "json",
            "SCHUL_NM": school_name,  # School name
            "ATPT_OFCDC_SC_CODE": region  # Optional region filter
        }

        response = requests.get(
            f"{self.base_url}/schoolInfo",
            params=params
        )

        data = response.json()

        return {
            "school_name": data["SCHUL_NM"],
            "road_address": data["ORG_RDNMA"],  # 도로명주소
            "address": data["ORG_RDNDA"],  # 도로명상세주소
            "phone": data["ORG_TELNO"],
            "homepage": data["HMPG_ADRES"]
        }
```

---

### 4.3 Hybrid Database Schema

**Recommendation**: Extend existing database with address fields

```sql
-- Add to existing teams/organizations table
ALTER TABLE teams ADD COLUMN country VARCHAR(2) DEFAULT 'KO';
ALTER TABLE teams ADD COLUMN province VARCHAR(50);  -- 시도
ALTER TABLE teams ADD COLUMN district VARCHAR(50);  -- 구
ALTER TABLE teams ADD COLUMN road_address VARCHAR(255);  -- 도로명주소
ALTER TABLE teams ADD COLUMN detailed_address VARCHAR(255);  -- 세부주소
ALTER TABLE teams ADD COLUMN postal_code VARCHAR(10);
ALTER TABLE teams ADD COLUMN latitude DECIMAL(10, 7);
ALTER TABLE teams ADD COLUMN longitude DECIMAL(10, 7);
ALTER TABLE teams ADD COLUMN address_source VARCHAR(50);  -- Track data source
ALTER TABLE teams ADD COLUMN address_verified BOOLEAN DEFAULT FALSE;
ALTER TABLE teams ADD COLUMN address_updated_at TIMESTAMP;
```

---

## 5. Summary & Next Steps

### Current Status
- ❌ Direct scraping from fencing.sports.or.kr is NOT feasible for addresses
- ✅ Multiple alternative data sources identified
- ✅ High success rate possible through hybrid approach

### Recommended Approach
1. **Immediate**: Implement NEIS API integration for school teams (40-50% coverage)
2. **Short-term**: Investigate G1 Sports Portal authenticated access (30-40% additional)
3. **Medium-term**: Business registration database for clubs (10-15% additional)
4. **Manual**: Direct collection for remaining teams (5-10%)

### Expected Total Coverage
- **Automated**: 70-90% of teams
- **Manual**: 10-30% of teams
- **Total**: Near-complete address database achievable

### Implementation Priority
1. ✅ Register for NEIS API key
2. ✅ Create G1 Sports Portal account and explore access
3. ✅ Develop address collection module with multiple data sources
4. ✅ Extend database schema for address storage
5. ✅ Implement data validation and verification system

---

## Sources

### Korean Fencing Association
- [Team Search Page](https://fencing.sports.or.kr/team/teamSearchList)
- [Main Website](https://fencing.sports.or.kr/)

### Government & Public Data
- [NEIS School Basic Information API](https://open.neis.go.kr/portal/data/service/selectServicePage.do?infId=OPEN17020190531110010104913&infSeq=2)
- [Public Data Portal - NEIS](https://www.data.go.kr/data/15122275/openapi.do)
- [Korea Sports Council - G1 Portal](https://g1.sports.or.kr/)
- [School Team Registration Status](https://g1.sports.or.kr/stat/stat08.do)

### Business Registration
- [National Tax Service Business Registration API](https://www.data.go.kr/tcs/dss/selectApiDataDetailView.do?publicDataPk=15081808)
- [BIZNO.NET Open API](https://bizno.net/openapi)
- [Moneypin Business Info API](https://help.moneypin.biz/035c943a06e74489a97f3e8e147129ff)

### Sports Facilities
- [National Public Facility Open Info](https://www.data.go.kr/data/15013117/standard.do)
- [Seoul Olympic Sports Promotion - National Sports Facility Info](https://www.data.go.kr/dataset/15011222/openapi.do)
