#!/usr/bin/env python3
"""
종합 테스트 스크립트 - 전체 시스템 점검
API 엔드포인트 + 데이터 무결성 + 페이지 렌더링 검증
"""

import asyncio
import httpx
from typing import Dict, List, Tuple
from dataclasses import dataclass
from loguru import logger
import sys

BASE_URL = "http://localhost:71"

@dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    details: str = ""

class ComprehensiveTest:
    def __init__(self):
        self.results: List[TestResult] = []
        self.client = None

    async def setup(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def teardown(self):
        if self.client:
            await self.client.aclose()

    def add_result(self, name: str, passed: bool, message: str, details: str = ""):
        self.results.append(TestResult(name, passed, message, details))
        status = "✅" if passed else "❌"
        logger.info(f"{status} {name}: {message}")
        if details and not passed:
            logger.debug(f"   Details: {details[:200]}")

    # ==================== API 엔드포인트 테스트 ====================

    async def test_api_health(self):
        """기본 API 상태 확인"""
        try:
            resp = await self.client.get(f"{BASE_URL}/")
            self.add_result("API Health", resp.status_code == 200,
                          f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("API Health", False, f"Error: {e}")

    async def test_api_filters(self):
        """필터 API 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/api/filters")
            if resp.status_code == 200:
                data = resp.json()
                has_weapons = "weapons" in data and len(data["weapons"]) > 0
                has_years = "years" in data and len(data["years"]) > 0
                self.add_result("API Filters", has_weapons and has_years,
                              f"Weapons: {len(data.get('weapons', []))}, Years: {len(data.get('years', []))}")
            else:
                self.add_result("API Filters", False, f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("API Filters", False, f"Error: {e}")

    async def test_api_competitions(self):
        """대회 목록 API 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/api/competitions?per_page=100")
            if resp.status_code == 200:
                data = resp.json()
                total = data.get("total", 0)
                comps = data.get("competitions", [])
                self.add_result("API Competitions", total > 0 and len(comps) > 0,
                              f"Total: {total}, Returned: {len(comps)}")
            else:
                self.add_result("API Competitions", False, f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("API Competitions", False, f"Error: {e}")

    async def test_api_events(self):
        """이벤트 검색 API 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/api/events?year=2025&weapon=플러레&gender=남&age_group=Y12&event_type=개인")
            if resp.status_code == 200:
                data = resp.json()
                events = data.get("events", [])
                self.add_result("API Events Search", True,
                              f"Found: {len(events)} events")
            else:
                self.add_result("API Events Search", False, f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("API Events Search", False, f"Error: {e}")

    async def test_api_fencinglab_demo(self):
        """FencingLab 데모 API 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/api/fencinglab/demo")
            if resp.status_code == 200:
                data = resp.json()
                demo_players = data.get("demo_players", [])
                club_players = data.get("total_club_players", 0)
                self.add_result("API FencingLab Demo", len(demo_players) > 0,
                              f"Demo: {len(demo_players)}, Club: {club_players}")
            else:
                self.add_result("API FencingLab Demo", False,
                              f"Status: {resp.status_code}", resp.text[:500])
        except Exception as e:
            self.add_result("API FencingLab Demo", False, f"Error: {e}")

    async def test_api_player_search(self):
        """선수 검색 API 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/api/players/search?q=박소윤")
            if resp.status_code == 200:
                data = resp.json()
                players = data.get("players", [])
                self.add_result("API Player Search", True,
                              f"Found: {len(players)} players for '박소윤'")
            else:
                self.add_result("API Player Search", False, f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("API Player Search", False, f"Error: {e}")

    async def test_api_player_by_id(self):
        """선수 ID 조회 API 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/api/players/by-id/KOP00000")
            if resp.status_code == 200:
                data = resp.json()
                name = data.get("name", "")
                self.add_result("API Player by ID", name != "",
                              f"Player: {name}")
            else:
                self.add_result("API Player by ID", False, f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("API Player by ID", False, f"Error: {e}")

    async def test_api_competition_detail(self):
        """대회 상세 API 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/api/competition/COMPM00666")
            if resp.status_code == 200:
                data = resp.json()
                events = data.get("events", [])
                comp_name = data.get("competition", {}).get("comp_name", "")
                self.add_result("API Competition Detail", len(events) > 0,
                              f"'{comp_name}' has {len(events)} events")
            else:
                self.add_result("API Competition Detail", False, f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("API Competition Detail", False, f"Error: {e}")

    # ==================== 페이지 렌더링 테스트 ====================

    async def test_page_home(self):
        """메인 페이지 렌더링 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/")
            self.add_result("Page Home", resp.status_code == 200 and "Korean Fencing" in resp.text,
                          f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("Page Home", False, f"Error: {e}")

    async def test_page_search(self):
        """검색 페이지 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/search?q=최민준")
            self.add_result("Page Search", resp.status_code == 200,
                          f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("Page Search", False, f"Error: {e}")

    async def test_page_player(self):
        """선수 페이지 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/player/박소윤")
            self.add_result("Page Player", resp.status_code == 200 and "박소윤" in resp.text,
                          f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("Page Player", False, f"Error: {e}")

    async def test_page_competition(self):
        """대회 페이지 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/competition/COMPM00666")
            passed = resp.status_code == 200 and "익산" in resp.text
            self.add_result("Page Competition", passed,
                          f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("Page Competition", False, f"Error: {e}")

    async def test_page_competition_event(self):
        """대회 이벤트 상세 페이지 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/competition/COMPM00666?event=17세이하부 남자 플러레(개)")
            self.add_result("Page Competition Event", resp.status_code == 200,
                          f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("Page Competition Event", False, f"Error: {e}")

    async def test_page_rankings(self):
        """랭킹 페이지 테스트"""
        try:
            resp = await self.client.get(f"{BASE_URL}/rankings")
            self.add_result("Page Rankings", resp.status_code == 200,
                          f"Status: {resp.status_code}")
        except Exception as e:
            self.add_result("Page Rankings", False, f"Error: {e}")

    # ==================== 익산 대회 데이터 테스트 ====================

    async def test_iksan_data_in_competitions(self):
        """익산 대회가 대회 목록에 있는지 확인"""
        try:
            # API max per_page is 100
            resp = await self.client.get(f"{BASE_URL}/api/competitions?per_page=100")
            data = resp.json()
            comps = data.get("competitions", [])
            # API returns 'name' not 'comp_name'
            iksan_found = any("익산" in c.get("name", "") for c in comps)
            self.add_result("Iksan in Competitions", iksan_found,
                          f"Found Iksan: {iksan_found} (total {len(comps)} competitions)")
        except Exception as e:
            self.add_result("Iksan in Competitions", False, f"Error: {e}")

    async def test_iksan_events_have_data(self):
        """익산 대회 이벤트에 데이터가 있는지 확인"""
        try:
            resp = await self.client.get(f"{BASE_URL}/api/competition/COMPM00666")
            data = resp.json()
            events = data.get("events", [])

            # 각 이벤트의 final_rankings 확인
            events_with_data = 0
            for event in events:
                if event.get("final_rankings") and len(event.get("final_rankings", [])) > 0:
                    events_with_data += 1

            passed = events_with_data > 0
            self.add_result("Iksan Events Have Data", passed,
                          f"{events_with_data}/{len(events)} events have ranking data")
        except Exception as e:
            self.add_result("Iksan Events Have Data", False, f"Error: {e}")

    async def test_iksan_player_in_search(self):
        """익산 대회 우승자가 검색에 나오는지 확인"""
        try:
            resp = await self.client.get(f"{BASE_URL}/api/players/search?q=최민준")
            data = resp.json()
            # API returns 'results' not 'players'
            players = data.get("results", [])

            # 신동중학교 최민준 찾기 - teams 배열이나 current_team에서 확인
            found_shindon = any(
                p.get("name") == "최민준" and (
                    "신동" in p.get("current_team", "") or
                    any("신동" in t for t in p.get("teams", []))
                )
                for p in players
            )
            self.add_result("Iksan Winner Searchable", found_shindon,
                          f"Found 최민준(신동중): {found_shindon}, total: {len(players)}")
        except Exception as e:
            self.add_result("Iksan Winner Searchable", False, f"Error: {e}")

    # ==================== 데이터 무결성 테스트 ====================

    async def test_player_index_count(self):
        """선수 인덱스 수 확인"""
        try:
            resp = await self.client.get(f"{BASE_URL}/api/players/search?q=김")
            data = resp.json()
            total = data.get("total", 0)
            self.add_result("Player Index", total > 100,
                          f"Players with '김': {total}")
        except Exception as e:
            self.add_result("Player Index", False, f"Error: {e}")

    async def test_event_search_by_year(self):
        """연도별 이벤트 검색"""
        try:
            for year in [2025, 2024, 2023]:
                resp = await self.client.get(f"{BASE_URL}/api/events?year={year}")
                data = resp.json()
                events = data.get("events", [])
                self.add_result(f"Events Year {year}", True,
                              f"Found: {len(events)} events")
        except Exception as e:
            self.add_result("Events by Year", False, f"Error: {e}")

    # ==================== 실행 ====================

    async def run_all_tests(self):
        """모든 테스트 실행"""
        await self.setup()

        logger.info("="*60)
        logger.info("🧪 종합 테스트 시작")
        logger.info("="*60)

        # API 테스트
        logger.info("\n📡 API 엔드포인트 테스트")
        logger.info("-"*40)
        await self.test_api_health()
        await self.test_api_filters()
        await self.test_api_competitions()
        await self.test_api_events()
        await self.test_api_fencinglab_demo()
        await self.test_api_player_search()
        await self.test_api_player_by_id()
        await self.test_api_competition_detail()

        # 페이지 테스트
        logger.info("\n📄 페이지 렌더링 테스트")
        logger.info("-"*40)
        await self.test_page_home()
        await self.test_page_search()
        await self.test_page_player()
        await self.test_page_competition()
        await self.test_page_competition_event()
        await self.test_page_rankings()

        # 익산 데이터 테스트
        logger.info("\n🏅 익산 대회 데이터 테스트")
        logger.info("-"*40)
        await self.test_iksan_data_in_competitions()
        await self.test_iksan_events_have_data()
        await self.test_iksan_player_in_search()

        # 데이터 무결성 테스트
        logger.info("\n🔍 데이터 무결성 테스트")
        logger.info("-"*40)
        await self.test_player_index_count()
        await self.test_event_search_by_year()

        await self.teardown()

        # 결과 요약
        logger.info("\n" + "="*60)
        logger.info("📊 테스트 결과 요약")
        logger.info("="*60)

        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)

        logger.info(f"✅ 통과: {passed}")
        logger.info(f"❌ 실패: {failed}")
        logger.info(f"📋 총계: {len(self.results)}")

        if failed > 0:
            logger.info("\n🚨 실패한 테스트:")
            for r in self.results:
                if not r.passed:
                    logger.error(f"  - {r.name}: {r.message}")

        return failed == 0

if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stdout, level="INFO", format="<level>{message}</level>")

    tester = ComprehensiveTest()
    success = asyncio.run(tester.run_all_tests())
    sys.exit(0 if success else 1)
