"""
익산 국제대회 E2E 테스트
Playwright를 사용한 웹 페이지 검증
"""
import pytest
import requests
from playwright.sync_api import sync_playwright, expect

BASE_URL = "http://localhost:71"


class TestIksanAPI:
    """익산 대회 API 테스트"""

    def test_iksan_data_api(self):
        """익산 데이터 API 응답 확인"""
        response = requests.get(f"{BASE_URL}/api/iksan/data")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        assert "competitions" in data
        assert len(data["competitions"]) == 2
        assert data["total_event_count"] == 30

    def test_iksan_event_api(self):
        """익산 종목별 API 응답 확인"""
        response = requests.get(f"{BASE_URL}/api/iksan/event/17세이하부 남자 플러레")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        assert "pools" in data
        assert len(data["pools"]) > 0


class TestIksanU17U20Page:
    """U17/U20 대회 페이지 E2E 테스트"""

    @pytest.fixture(scope="class")
    def browser(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            yield browser
            browser.close()

    @pytest.fixture
    def page(self, browser):
        page = browser.new_page()
        yield page
        page.close()

    def test_page_loads(self, page):
        """페이지 로딩 확인"""
        page.goto(f"{BASE_URL}/competition/iksan-u17-u20")
        expect(page).to_have_title("2025 코리아 익산 인터내셔널 펜싱선수권대회 - U17/U20 - Korean Fencing Tracker")

    def test_event_list_visible(self, page):
        """이벤트 목록 표시 확인"""
        page.goto(f"{BASE_URL}/competition/iksan-u17-u20")

        # 12개 종목 링크가 표시되어야 함
        event_links = page.locator("a[href*='iksan-u17-u20?event=']")
        expect(event_links).to_have_count(12)

    def test_event_detail_pool_data(self, page):
        """종목 상세 페이지 - Pool 데이터 확인"""
        page.goto(f"{BASE_URL}/competition/iksan-u17-u20?event=17세이하부_남자_플러레(개)")

        # Pool 버튼들이 표시되어야 함
        pool_buttons = page.locator("button:has-text('Pool')")
        expect(pool_buttons.first).to_be_visible()

        # Pool 버튼 클릭해서 탭 활성화
        pool_buttons.first.click()
        page.wait_for_timeout(500)

        # Pool 테이블이 표시되어야 함 (visible 상태인 테이블만)
        pool_table = page.locator("table:visible")
        expect(pool_table.first).to_be_visible()

        # 선수 데이터가 있어야 함 (visible 상태인 것만)
        player_links = page.locator("table:visible a[href*='/player/']")
        expect(player_links.first).to_be_visible()

    def test_event_detail_de_tab(self, page):
        """종목 상세 페이지 - DE 탭 확인"""
        page.goto(f"{BASE_URL}/competition/iksan-u17-u20?event=17세이하부_남자_플러레(개)")

        # DE 탭 클릭
        de_button = page.locator("button:has-text('Direct Elimination')")
        de_button.click()

        # DE 대진표 또는 데이터가 표시되어야 함
        page.wait_for_timeout(500)

    def test_event_detail_final_tab(self, page):
        """종목 상세 페이지 - 최종결과 탭 확인"""
        page.goto(f"{BASE_URL}/competition/iksan-u17-u20?event=17세이하부_남자_플러레(개)")

        # 최종결과 탭 클릭
        final_button = page.locator("button:has-text('최종결과')")
        final_button.click()

        # 최종 순위 데이터가 표시되어야 함
        page.wait_for_timeout(500)

    def test_player_link_navigation(self, page):
        """선수 링크 클릭 시 선수 페이지 이동"""
        page.goto(f"{BASE_URL}/competition/iksan-u17-u20?event=17세이하부_남자_플러레(개)")

        # Pool 탭 활성화
        pool_button = page.locator("button:has-text('Pool')").first
        pool_button.click()
        page.wait_for_timeout(500)

        # 첫 번째 선수 링크 클릭 (visible 상태인 것만)
        player_link = page.locator("table:visible a[href*='/player/']").first
        player_link.click()

        # 선수 페이지로 이동 확인
        page.wait_for_url(lambda url: "/player/" in url, timeout=10000)


class TestIksanU13Page:
    """U13/U11/U9 대회 페이지 E2E 테스트"""

    @pytest.fixture(scope="class")
    def browser(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            yield browser
            browser.close()

    @pytest.fixture
    def page(self, browser):
        page = browser.new_page()
        yield page
        page.close()

    def test_page_loads(self, page):
        """페이지 로딩 확인"""
        page.goto(f"{BASE_URL}/competition/iksan-u13")
        expect(page).to_have_title("2025 코리아 익산 인터내셔널 펜싱선수권대회 - U13/U11/U9 - Korean Fencing Tracker")

    def test_event_list_visible(self, page):
        """이벤트 목록 표시 확인"""
        page.goto(f"{BASE_URL}/competition/iksan-u13")

        # 18개 종목 링크가 표시되어야 함
        event_links = page.locator("a[href*='iksan-u13?event=']")
        expect(event_links).to_have_count(18)

    def test_event_detail_pool_data(self, page):
        """종목 상세 페이지 - Pool 데이터 확인"""
        page.goto(f"{BASE_URL}/competition/iksan-u13?event=13세이하부_남자_플러레(개)")

        # Pool 버튼들이 표시되어야 함
        pool_buttons = page.locator("button:has-text('Pool')")
        expect(pool_buttons.first).to_be_visible()


class TestFencingLabPage:
    """FencingLab 페이지 E2E 테스트"""

    @pytest.fixture(scope="class")
    def browser(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            yield browser
            browser.close()

    @pytest.fixture
    def page(self, browser):
        page = browser.new_page()
        yield page
        page.close()

    def test_tracked_players_api(self):
        """추적 선수 API 확인"""
        response = requests.get(f"{BASE_URL}/api/fencinglab/tracked-players")
        assert response.status_code == 200

        data = response.json()
        assert "tracked_clubs" in data

        # 최병철펜싱클럽 선수들
        clubs = data["tracked_clubs"]
        assert "최병철펜싱클럽" in clubs

        # 산하 관리 선수들
        affiliated = [k for k in clubs.keys() if k != "최병철펜싱클럽"]
        assert len(affiliated) >= 5, "산하 관리 클럽이 5개 이상이어야 함"

    def test_fencinglab_page_loads(self, page):
        """FencingLab 페이지 로딩 확인"""
        page.goto(f"{BASE_URL}/fencinglab")
        expect(page.locator(".fl-logo")).to_be_visible()

    def test_fencinglab_player_cards(self, page):
        """FencingLab 선수 카드 표시 확인"""
        page.goto(f"{BASE_URL}/fencinglab")

        # 선수 데이터 로딩 대기
        page.wait_for_selector(".fl-player-card", timeout=10000)

        # 선수 카드가 표시되어야 함
        player_cards = page.locator(".fl-player-card")
        expect(player_cards.first).to_be_visible()

        # 최소 50명 이상의 선수가 표시되어야 함
        count = player_cards.count()
        assert count >= 50, f"선수 수가 너무 적음: {count}"

    def test_fencinglab_club_sections(self, page):
        """FencingLab 클럽별 섹션 표시 확인"""
        page.goto(f"{BASE_URL}/fencinglab")
        page.wait_for_selector(".fl-club-section", timeout=10000)

        # 클럽 섹션이 표시되어야 함
        club_sections = page.locator(".fl-club-section")
        expect(club_sections.first).to_be_visible()

        # 최소 5개 이상의 클럽 섹션 (최병철 + 산하 관리)
        count = club_sections.count()
        assert count >= 5, f"클럽 섹션이 너무 적음: {count}"

    def test_fencinglab_affiliated_badge(self, page):
        """FencingLab 산하 관리 배지 표시 확인"""
        page.goto(f"{BASE_URL}/fencinglab")
        page.wait_for_selector(".fl-club-section", timeout=10000)

        # 산하 관리 배지가 표시되어야 함
        affiliated_badges = page.locator(".fl-affiliated-badge")
        expect(affiliated_badges.first).to_be_visible()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
