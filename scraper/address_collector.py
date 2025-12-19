"""
펜싱 팀/조직 주소 수집 스크립트
- NEIS API (학교)
- 대한펜싱협회 팀 페이지 스크래핑
- 수동 입력 대상 리스트 생성
"""
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
import aiohttp
from loguru import logger
from dotenv import load_dotenv
from supabase import create_client, Client
from playwright.async_api import async_playwright

load_dotenv()

# Logger 설정
logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")


@dataclass
class Organization:
    """조직 정보"""
    name: str
    org_type: str = ""  # club, elementary, middle, high, university, professional
    province: str = ""
    city: str = ""
    district: str = ""
    road_address: str = ""
    detailed_address: str = ""
    postal_code: str = ""
    latitude: float = None
    longitude: float = None
    phone: str = ""
    email: str = ""
    website: str = ""
    address_source: str = ""
    address_status: str = "pending"
    address_error: str = ""


class NEISClient:
    """NEIS 교육정보 API 클라이언트"""

    BASE_URL = "https://open.neis.go.kr/hub"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("NEIS_API_KEY")
        if not self.api_key:
            logger.warning("NEIS_API_KEY가 설정되지 않았습니다. 샘플 데이터만 조회 가능합니다.")

    async def search_school(self, school_name: str, session: aiohttp.ClientSession) -> Optional[Dict]:
        """학교명으로 학교 정보 검색"""
        params = {
            "Type": "json",
            "SCHUL_NM": school_name,
        }
        if self.api_key:
            params["KEY"] = self.api_key

        try:
            async with session.get(f"{self.BASE_URL}/schoolInfo", params=params) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()

                # 결과 추출
                school_info = data.get("schoolInfo")
                if not school_info:
                    return None

                rows = school_info[1].get("row", [])
                if not rows:
                    return None

                # 첫 번째 결과 반환
                school = rows[0]
                return {
                    "school_name": school.get("SCHUL_NM"),
                    "road_address": school.get("ORG_RDNMA", ""),  # 도로명주소
                    "detailed_address": school.get("ORG_RDNDA", ""),  # 상세주소
                    "postal_code": school.get("ORG_RDNZC", ""),  # 우편번호
                    "phone": school.get("ORG_TELNO", ""),
                    "homepage": school.get("HMPG_ADRES", ""),
                    "province": school.get("LCTN_SC_NM", ""),  # 시도명
                    "school_type": school.get("SCHUL_KND_SC_NM", ""),  # 학교종류
                }
        except Exception as e:
            logger.error(f"NEIS 검색 오류 ({school_name}): {e}")
            return None


class KakaoMapScraper:
    """카카오맵 웹 스크래퍼 (API 키 불필요)"""

    BASE_URL = "https://map.kakao.com/"

    # 법인 접두사 패턴 (검색시 제거)
    CORPORATE_PREFIXES = re.compile(r'^\s*\((사|주|재|학|의|합|유)\)\s*')

    def normalize_query(self, name: str) -> str:
        """검색어 정규화 - 법인 접두사 제거"""
        normalized = self.CORPORATE_PREFIXES.sub('', name)
        return normalized.strip()

    async def search_place(self, query: str, page) -> Optional[Dict]:
        """카카오맵에서 장소 검색 (Playwright 사용)"""
        try:
            # 검색어 정규화
            normalized_query = self.normalize_query(query)

            # 검색창에 입력 (role-based selector)
            search_input = page.get_by_role("textbox", name="지도 검색")
            await search_input.fill(normalized_query)
            await search_input.press("Enter")
            await asyncio.sleep(2)  # 검색 결과 로딩 대기

            # 검색 결과 확인 - 전체 검색 결과 영역에서 추출
            # Kakao Map 구조: #info.search.place 안에 결과 목록이 있음
            search_result = page.locator('#info\\.search\\.place')

            item_text = ""
            if await search_result.count() > 0:
                item_text = await search_result.text_content()

            if not item_text:
                # 펜싱 키워드 추가 시도
                await search_input.fill(f"{normalized_query} 펜싱")
                await search_input.press("Enter")
                await asyncio.sleep(2)
                if await search_result.count() > 0:
                    item_text = await search_result.text_content()

            if not item_text:
                return None

            # 주소 추출 (패턴 매칭)
            road_address = ""
            jibun_address = ""
            phone = ""

            # 도로명 주소 패턴: "시/도 구/군 로/길 번지"
            # 세종특별자치시 포함
            road_match = re.search(
                r'(서울|부산|대구|인천|광주|대전|울산|세종특별자치시|세종|경기|강원특별자치도|강원|충북|충남|전북특별자치도|전북|전남|경북|경남|제주특별자치도|제주)[\s가-힣]+(?:로|길|대로)\s*[\d\-]+',
                item_text
            )
            if road_match:
                road_address = road_match.group(0).strip()

            # 지번 주소 패턴
            jibun_match = re.search(r'\(지번\)\s*([가-힣\d\s\-]+)', item_text)
            if jibun_match:
                jibun_address = jibun_match.group(1).strip()
            elif not road_address:
                # 지번 주소만 있는 경우
                addr_match = re.search(
                    r'(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)[\s가-힣]+동\s+[\d\-]+',
                    item_text
                )
                if addr_match:
                    jibun_address = addr_match.group(0).strip()

            # 전화번호 패턴
            phone_match = re.search(r'(\d{2,4}[-\s]?\d{3,4}[-\s]?\d{4})', item_text)
            if phone_match:
                phone = phone_match.group(1).strip()

            if road_address or jibun_address:
                return {
                    "place_name": normalized_query,
                    "road_address": road_address,
                    "address": jibun_address,
                    "phone": phone,
                }

            return None

        except Exception as e:
            logger.debug(f"카카오맵 검색 오류 ({query}): {e}")
            return None

    def extract_province_from_address(self, address: str) -> str:
        """주소에서 시도 추출"""
        if not address:
            return ""

        province_match = re.match(
            r'^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)',
            address
        )
        if province_match:
            return province_match.group(1)

        # 서울특별시, 부산광역시 등 전체 명칭도 처리
        full_province_match = re.match(
            r'^(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|울산광역시|세종특별자치시|경기도|강원도|충청북도|충청남도|전라북도|전라남도|경상북도|경상남도|제주특별자치도)',
            address
        )
        if full_province_match:
            province_map = {
                "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구",
                "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전",
                "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기",
                "강원도": "강원", "충청북도": "충북", "충청남도": "충남",
                "전라북도": "전북", "전라남도": "전남", "경상북도": "경북",
                "경상남도": "경남", "제주특별자치도": "제주"
            }
            return province_map.get(full_province_match.group(1), "")

        return ""


class NaverMapScraper:
    """네이버맵 웹 스크래퍼 (카카오맵 실패 시 fallback)"""

    BASE_URL = "https://map.naver.com/p/search/"

    # 법인 접두사 패턴 (검색시 제거)
    CORPORATE_PREFIXES = re.compile(r'^\s*\((사|주|재|학|의|합|유)\)\s*')

    def normalize_query(self, name: str) -> str:
        """검색어 정규화 - 법인 접두사 제거"""
        normalized = self.CORPORATE_PREFIXES.sub('', name)
        return normalized.strip()

    async def search_place(self, query: str, page) -> Optional[Dict]:
        """네이버맵에서 장소 검색 (Playwright 사용)"""
        try:
            normalized_query = self.normalize_query(query)
            search_url = f"{self.BASE_URL}{normalized_query}"

            await page.goto(search_url, wait_until="domcontentloaded")
            await asyncio.sleep(2.5)  # 검색 결과 로딩 대기

            # 검색 결과 영역에서 첫 번째 결과 클릭
            first_result = page.locator('li.VLTHu').first
            if await first_result.count() > 0:
                await first_result.click()
                await asyncio.sleep(1.5)

            # 주소 정보 추출
            road_address = ""
            jibun_address = ""
            phone = ""

            # 도로명주소 추출
            road_addr_elem = page.locator('span.LDgIH')
            if await road_addr_elem.count() > 0:
                road_address = await road_addr_elem.first.text_content()
                road_address = road_address.strip() if road_address else ""

            # 지번주소 추출
            jibun_elem = page.locator('span.nQ7Lh')
            if await jibun_elem.count() > 0:
                jibun_address = await jibun_elem.first.text_content()
                jibun_address = jibun_address.strip() if jibun_address else ""

            # 전화번호 추출
            phone_elem = page.locator('span.xlx7Q')
            if await phone_elem.count() > 0:
                phone = await phone_elem.first.text_content()
                phone = phone.strip() if phone else ""

            # 주소가 없으면 전체 텍스트에서 추출 시도
            if not road_address and not jibun_address:
                page_text = await page.locator('body').text_content()

                # 도로명 주소 패턴
                road_match = re.search(
                    r'(서울|부산|대구|인천|광주|대전|울산|세종특별자치시|세종|경기|강원특별자치도|강원|충북|충남|전북특별자치도|전북|전남|경북|경남|제주특별자치도|제주)[^\n]+(?:로|길|대로)\s*[\d\-]+(?:번길\s*\d+)?',
                    page_text
                )
                if road_match:
                    road_address = road_match.group(0).strip()[:200]

            if road_address or jibun_address:
                return {
                    "place_name": normalized_query,
                    "road_address": road_address[:200] if road_address else "",
                    "address": jibun_address[:200] if jibun_address else "",
                    "phone": phone,
                }

            return None

        except Exception as e:
            logger.debug(f"네이버맵 검색 오류 ({query}): {e}")
            return None

    def extract_province_from_address(self, address: str) -> str:
        """주소에서 시도 추출"""
        if not address:
            return ""

        province_match = re.match(
            r'^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)',
            address
        )
        if province_match:
            return province_match.group(1)

        return ""


class KFFTeamScraper:
    """대한펜싱협회 팀 정보 스크래퍼 (레거시 - 더 이상 사용 안함)"""

    BASE_URL = "https://fencing.sports.or.kr"

    async def get_team_details(self, team_name: str, page) -> Optional[Dict]:
        """팀 상세 정보 조회 (팝업 스크래핑)"""
        try:
            # 팀 검색 페이지로 이동
            await page.goto(f"{self.BASE_URL}/team/teamSearchList", wait_until="networkidle")
            await asyncio.sleep(1)

            # 팀명 검색
            search_input = page.locator("input[name='teamNm']")
            await search_input.fill(team_name)

            # 검색 버튼 클릭
            search_btn = page.locator("a[href='#search']").first
            await search_btn.click()
            await asyncio.sleep(1.5)

            # 결과에서 팀 클릭하여 팝업 열기
            team_link = page.locator(f"text={team_name}").first
            await team_link.click(timeout=3000)
            await asyncio.sleep(1)

            # 팝업에서 정보 추출
            popup = page.locator(".layer_pop, #layer_team_detail, [class*='popup']")
            if await popup.count() > 0:
                # 주소, 전화번호 등 추출 시도
                content = await popup.text_content()

                # 주소 패턴 검색
                address_match = re.search(r'주소\s*[:：]?\s*(.+?)(?=\n|전화|연락처|홈페이지|$)', content)
                phone_match = re.search(r'(?:전화|연락처)\s*[:：]?\s*([\d\-]+)', content)
                homepage_match = re.search(r'홈페이지\s*[:：]?\s*(https?://\S+)', content)

                return {
                    "address": address_match.group(1).strip() if address_match else "",
                    "phone": phone_match.group(1).strip() if phone_match else "",
                    "homepage": homepage_match.group(1).strip() if homepage_match else "",
                }

            return None
        except Exception as e:
            logger.debug(f"팀 정보 조회 실패 ({team_name}): {e}")
            return None


class AddressCollector:
    """주소 수집기"""

    # 학교 키워드 패턴
    SCHOOL_PATTERNS = {
        "elementary": ["초등학교", "초교"],
        "middle": ["중학교", "중"],
        "high": ["고등학교", "고교", "고"],
        "university": ["대학교", "대학", "대"],
    }

    # 실업팀/클럽 키워드
    PROFESSIONAL_PATTERNS = ["실업팀", "펜싱클럽", "FC", "아카데미", "체육관", "스포츠", "클럽"]

    def __init__(self):
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")

        if supabase_url and supabase_key:
            self.supabase: Client = create_client(supabase_url, supabase_key)
        else:
            self.supabase = None
            logger.warning("Supabase 연결 정보가 없습니다.")

        self.neis = NEISClient()
        self.kakao_scraper = KakaoMapScraper()  # 카카오맵 웹 스크래퍼
        self.results = {
            "collected": [],      # 수집 성공
            "failed": [],         # 수집 실패 (수동 필요)
            "skipped": [],        # 건너뜀 (이미 있음)
        }
        self.stats = {
            "total": 0,
            "school": 0,
            "club": 0,
            "professional": 0,
            "unknown": 0,
        }

    def classify_organization(self, name: str) -> str:
        """조직 유형 분류"""
        name_lower = name.lower()

        # 학교 분류
        for school_type, patterns in self.SCHOOL_PATTERNS.items():
            for pattern in patterns:
                if pattern in name:
                    return school_type

        # 실업팀/클럽 분류
        for pattern in self.PROFESSIONAL_PATTERNS:
            if pattern in name:
                return "club" if "클럽" in pattern or "아카데미" in pattern else "professional"

        return "unknown"

    def normalize_school_name(self, name: str) -> str:
        """학교명 정규화 (NEIS 검색용)"""
        # 일반적인 약어 확장
        name = re.sub(r'중$', '중학교', name)
        name = re.sub(r'고$', '고등학교', name)
        name = re.sub(r'초$', '초등학교', name)
        name = re.sub(r'대$', '대학교', name)

        # 특수문자 제거
        name = re.sub(r'[^\w가-힣]', '', name)

        return name

    def extract_unique_teams(self, json_filepath: str) -> List[str]:
        """JSON 데이터에서 고유 팀명 추출"""
        teams = set()

        with open(json_filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for comp_data in data.get("competitions", []):
            for event in comp_data.get("events", []):
                # Pool 결과에서 팀 추출
                for pool in event.get("pool_rounds", []):
                    for result in pool.get("results", []):
                        team = result.get("team", "").strip()
                        if team and len(team) > 1:
                            teams.add(team)

                # Pool Total Ranking에서 팀 추출
                for ranking in event.get("pool_total_ranking", []):
                    team = ranking.get("team", "").strip()
                    if team and len(team) > 1:
                        teams.add(team)

                # Final Rankings에서 팀 추출
                for ranking in event.get("final_rankings", []):
                    team = ranking.get("team", "").strip()
                    if team and len(team) > 1:
                        teams.add(team)

                # DE Bracket에서 팀 추출
                de_bracket = event.get("de_bracket", {})
                for seed in de_bracket.get("seeding", []):
                    team = seed.get("team", "").strip()
                    if team and len(team) > 1:
                        teams.add(team)

        return sorted(list(teams))

    def extract_teams_from_supabase(self) -> List[str]:
        """Supabase players 테이블에서 고유 팀명 추출"""
        if not self.supabase:
            logger.error("Supabase 연결이 없습니다")
            return []

        logger.info("Supabase에서 팀 목록 조회 중...")
        teams = set()

        # 페이지네이션으로 전체 팀 조회
        offset = 0
        limit = 1000

        while True:
            result = self.supabase.table("players") \
                .select("team_name") \
                .neq("team_name", "") \
                .not_.is_("team_name", "null") \
                .range(offset, offset + limit - 1) \
                .execute()

            if not result.data:
                break

            for row in result.data:
                team = row.get("team_name", "").strip()
                if team and len(team) > 1:
                    teams.add(team)

            if len(result.data) < limit:
                break

            offset += limit

        logger.info(f"Supabase에서 {len(teams)}개 팀 발견")
        return sorted(list(teams))

    async def collect_school_addresses(self, teams: List[str]) -> int:
        """학교 주소 수집 (NEIS API - 초/중/고만, 대학교는 Kakao API)"""
        logger.info("학교 주소 수집 시작 (NEIS API)...")
        collected = 0

        # 초/중/고만 NEIS로 수집 (대학교는 Kakao로)
        school_teams = [t for t in teams if self.classify_organization(t) in
                        ["elementary", "middle", "high"]]

        logger.info(f"초/중/고 학교 팀 {len(school_teams)}개 발견")

        async with aiohttp.ClientSession() as session:
            for team_name in school_teams:
                self.stats["school"] += 1
                org_type = self.classify_organization(team_name)

                # 학교명 정규화
                normalized = self.normalize_school_name(team_name)

                # NEIS API 검색
                school_info = await self.neis.search_school(normalized, session)

                if school_info and school_info.get("road_address"):
                    org = Organization(
                        name=team_name,
                        org_type=org_type,
                        province=school_info.get("province", ""),
                        road_address=school_info.get("road_address", ""),
                        detailed_address=school_info.get("detailed_address", ""),
                        postal_code=school_info.get("postal_code", ""),
                        phone=school_info.get("phone", ""),
                        website=school_info.get("homepage", ""),
                        address_source="neis",
                        address_status="collected",
                    )
                    self.results["collected"].append(asdict(org))
                    collected += 1
                    logger.debug(f"✅ {team_name}: {school_info.get('road_address')}")
                else:
                    org = Organization(
                        name=team_name,
                        org_type=org_type,
                        address_source="neis",
                        address_status="failed",
                        address_error="NEIS API에서 학교 정보를 찾을 수 없음",
                    )
                    self.results["failed"].append(asdict(org))
                    logger.debug(f"❌ {team_name}: 검색 실패")

                # Rate limiting
                await asyncio.sleep(0.3)

        logger.info(f"학교 주소 수집 완료: {collected}/{len(school_teams)}")
        return collected

    async def collect_university_addresses(self, teams: List[str], page) -> int:
        """대학교 주소 수집 (카카오맵 스크래핑)"""
        logger.info("대학교 주소 수집 시작 (카카오맵)...")
        collected = 0

        # 대학교만 필터링
        uni_teams = [t for t in teams if self.classify_organization(t) == "university"]

        logger.info(f"대학교 팀 {len(uni_teams)}개 발견")

        for team_name in uni_teams:
            self.stats["school"] += 1

            # 대학교명 정규화 - 대학교 이름만 추출 (펜싱부, 펜싱팀, OB 등 모두 제거)
            # "서울대학교 펜싱부" → "서울대학교"
            # "고려대학교펜싱부" → "고려대학교"
            uni_name = re.sub(r'\s*(펜싱부|펜싱팀|펜싱|OB|ob|동호회).*$', '', team_name).strip()

            # "대학교" 없으면 "대학"까지 포함하도록
            if "대학" not in uni_name:
                # 원래 팀명에서 대학교/대학 부분 추출
                match = re.search(r'^(.+(?:대학교|대학))', team_name)
                if match:
                    uni_name = match.group(1)

            logger.debug(f"대학 검색: '{team_name}' → '{uni_name}'")

            # 카카오맵에서 검색
            place_info = await self.kakao_scraper.search_place(uni_name, page)

            if place_info and (place_info.get("road_address") or place_info.get("address")):
                address = place_info.get("road_address") or place_info.get("address", "")
                province = self.kakao_scraper.extract_province_from_address(address)

                org = Organization(
                    name=team_name,
                    org_type="university",
                    province=province,
                    road_address=place_info.get("road_address", ""),
                    detailed_address=place_info.get("address", ""),
                    phone=place_info.get("phone", ""),
                    address_source="kakao_map",
                    address_status="collected",
                )
                self.results["collected"].append(asdict(org))
                collected += 1
                logger.info(f"✅ {team_name}: {address}")
            else:
                org = Organization(
                    name=team_name,
                    org_type="university",
                    address_source="kakao_map",
                    address_status="manual_required",
                    address_error="카카오맵에서 장소를 찾을 수 없음",
                )
                self.results["failed"].append(asdict(org))
                logger.warning(f"❌ {team_name}: 주소 없음 (수동 입력 필요)")

            await asyncio.sleep(1)  # 스크래핑 간격

        logger.info(f"대학교 주소 수집 완료: {collected}/{len(uni_teams)}")
        return collected

    async def collect_club_addresses(self, teams: List[str], page) -> int:
        """클럽/실업팀 주소 수집 (카카오맵 스크래핑)"""
        logger.info("클럽/실업팀 주소 수집 시작 (카카오맵)...")
        collected = 0

        # 클럽/실업팀 필터링
        club_teams = [t for t in teams if self.classify_organization(t) in ["club", "professional"]]

        logger.info(f"클럽/실업팀 {len(club_teams)}개 발견")

        for team_name in club_teams:
            org_type = self.classify_organization(team_name)
            if org_type == "club":
                self.stats["club"] += 1
            else:
                self.stats["professional"] += 1

            # 카카오맵에서 검색
            place_info = await self.kakao_scraper.search_place(team_name, page)

            if place_info and (place_info.get("road_address") or place_info.get("address")):
                address = place_info.get("road_address") or place_info.get("address", "")
                province = self.kakao_scraper.extract_province_from_address(address)

                org = Organization(
                    name=team_name,
                    org_type=org_type,
                    province=province,
                    road_address=place_info.get("road_address", ""),
                    detailed_address=place_info.get("address", ""),
                    phone=place_info.get("phone", ""),
                    address_source="kakao_map",
                    address_status="collected",
                )
                self.results["collected"].append(asdict(org))
                collected += 1
                logger.info(f"✅ {team_name}: {address}")
            else:
                org = Organization(
                    name=team_name,
                    org_type=org_type,
                    address_source="kakao_map",
                    address_status="manual_required",
                    address_error="카카오맵에서 장소를 찾을 수 없음",
                )
                self.results["failed"].append(asdict(org))
                logger.warning(f"❌ {team_name}: 주소 없음 (수동 입력 필요)")

            await asyncio.sleep(1)  # 스크래핑 간격

        logger.info(f"클럽/실업팀 주소 수집 완료: {collected}/{len(club_teams)}")
        return collected

    async def collect_unknown_teams(self, teams: List[str]) -> int:
        """분류되지 않은 팀 처리"""
        logger.info("미분류 팀 처리 중...")

        unknown_teams = [t for t in teams if self.classify_organization(t) == "unknown"]
        self.stats["unknown"] = len(unknown_teams)

        for team_name in unknown_teams:
            org = Organization(
                name=team_name,
                org_type="unknown",
                address_status="manual_required",
                address_error="팀 유형 분류 불가 - 수동 분류 및 주소 입력 필요",
            )
            self.results["failed"].append(asdict(org))

        logger.info(f"미분류 팀: {len(unknown_teams)}개")
        return 0

    async def save_to_supabase(self) -> int:
        """수집된 데이터를 Supabase에 저장"""
        if not self.supabase:
            logger.warning("Supabase 연결이 없어 저장을 건너뜁니다.")
            return 0

        logger.info("Supabase에 데이터 저장 중...")
        saved = 0

        all_orgs = self.results["collected"] + self.results["failed"]

        for org in all_orgs:
            try:
                data = {
                    "name": org["name"],
                    "name_normalized": self.normalize_school_name(org["name"]),
                    "org_type": org.get("org_type"),
                    "country": "KO",
                    "province": org.get("province"),
                    "city": org.get("city"),
                    "district": org.get("district"),
                    "road_address": org.get("road_address"),
                    "detailed_address": org.get("detailed_address"),
                    "postal_code": org.get("postal_code"),
                    "phone": org.get("phone"),
                    "email": org.get("email"),
                    "website": org.get("website"),
                    "address_source": org.get("address_source"),
                    "address_status": org.get("address_status"),
                    "address_error": org.get("address_error"),
                }

                self.supabase.table("organizations").upsert(
                    data, on_conflict="name"
                ).execute()
                saved += 1
            except Exception as e:
                logger.error(f"저장 실패 ({org['name']}): {e}")

        logger.info(f"Supabase 저장 완료: {saved}개")
        return saved

    def generate_report(self, output_dir: str = "data") -> str:
        """수집 결과 리포트 생성"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = Path(output_dir) / f"address_collection_report_{timestamp}.json"

        report = {
            "generated_at": datetime.now().isoformat(),
            "statistics": {
                "total_teams": self.stats["total"],
                "by_type": {
                    "school": self.stats["school"],
                    "club": self.stats["club"],
                    "professional": self.stats["professional"],
                    "unknown": self.stats["unknown"],
                },
                "collection_results": {
                    "collected": len(self.results["collected"]),
                    "failed": len(self.results["failed"]),
                    "skipped": len(self.results["skipped"]),
                },
                "success_rate": f"{len(self.results['collected']) / max(self.stats['total'], 1) * 100:.1f}%"
            },
            "collected_organizations": self.results["collected"],
            "manual_required": [
                {
                    "name": org["name"],
                    "org_type": org["org_type"],
                    "error": org.get("address_error", ""),
                }
                for org in self.results["failed"]
            ],
        }

        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"리포트 저장: {report_file}")

        # 수동 입력 필요 목록 별도 저장
        manual_file = Path(output_dir) / f"manual_address_required_{timestamp}.json"
        with open(manual_file, 'w', encoding='utf-8') as f:
            json.dump(self.results["failed"], f, ensure_ascii=False, indent=2)

        logger.info(f"수동 입력 목록 저장: {manual_file}")

        return str(report_file)

    async def run(self, json_filepath: str = None, from_db: bool = False) -> str:
        """전체 수집 실행"""
        logger.info("=" * 60)
        logger.info("주소 수집 시작")
        logger.info("=" * 60)

        # 1. 팀 추출
        if from_db:
            teams = self.extract_teams_from_supabase()
        else:
            teams = self.extract_unique_teams(json_filepath)
        self.stats["total"] = len(teams)
        logger.info(f"총 {len(teams)}개의 고유 팀 발견")

        # 2. 학교 주소 수집 (NEIS API - 초/중/고만)
        await self.collect_school_addresses(teams)

        # 3. 카카오맵 스크래핑 (대학교 + 클럽/실업팀)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # 카카오맵 페이지 열기
            await page.goto("https://map.kakao.com/", wait_until="networkidle")
            await asyncio.sleep(1)

            # 3-1. 대학교 주소 수집
            await self.collect_university_addresses(teams, page)

            # 3-2. 클럽/실업팀 주소 수집
            await self.collect_club_addresses(teams, page)

            await browser.close()

        # 4. 미분류 팀 처리
        await self.collect_unknown_teams(teams)

        # 5. Supabase 저장
        await self.save_to_supabase()

        # 6. 리포트 생성
        report_file = self.generate_report()

        logger.info("=" * 60)
        logger.info("수집 완료 요약")
        logger.info("=" * 60)
        logger.info(f"총 팀: {self.stats['total']}개")
        logger.info(f"  - 학교: {self.stats['school']}개")
        logger.info(f"  - 클럽: {self.stats['club']}개")
        logger.info(f"  - 실업팀: {self.stats['professional']}개")
        logger.info(f"  - 미분류: {self.stats['unknown']}개")
        logger.info(f"수집 성공: {len(self.results['collected'])}개")
        logger.info(f"수동 필요: {len(self.results['failed'])}개")
        logger.info(f"리포트: {report_file}")

        return report_file


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="펜싱 팀 주소 수집")
    parser.add_argument("--input", type=str, default="data/fencing_full_data.json",
                        help="입력 JSON 파일")
    parser.add_argument("--output-dir", type=str, default="data",
                        help="출력 디렉토리")
    parser.add_argument("--from-db", action="store_true",
                        help="Supabase DB에서 팀 목록 가져오기 (JSON 파일 대신)")

    args = parser.parse_args()

    collector = AddressCollector()

    if args.from_db:
        logger.info("Supabase에서 팀 목록을 가져옵니다...")
        await collector.run(from_db=True)
    else:
        input_file = Path(args.input)
        if not input_file.exists():
            logger.error(f"입력 파일을 찾을 수 없습니다: {input_file}")
            sys.exit(1)
        await collector.run(json_filepath=str(input_file))


if __name__ == "__main__":
    asyncio.run(main())
