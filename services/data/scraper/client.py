"""
대한펜싱협회 HTTP 클라이언트
"""
import aiohttp
import asyncio
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
import json
from loguru import logger

from .config import scraper_config, Endpoints
from .models import (
    Competition, Event, Player, Match, Ranking,
    CompetitionListResponse, CompetitionStatus
)


class KFFClient:
    """대한펜싱협회 API 클라이언트"""

    def __init__(self):
        self.base_url = scraper_config.base_url
        self.delay = scraper_config.scrape_delay
        self.max_retries = scraper_config.max_retries
        self.timeout = aiohttp.ClientTimeout(total=scraper_config.request_timeout)
        self.headers = {
            "User-Agent": scraper_config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(scraper_config.max_concurrent_requests)

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(
            timeout=self.timeout,
            headers=self.headers
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        retry_count: int = 0
    ) -> str:
        """HTTP 요청 실행"""
        async with self._semaphore:
            url = f"{self.base_url}{endpoint}"
            try:
                await asyncio.sleep(self.delay)

                if method.upper() == "GET":
                    async with self._session.get(url, params=params) as response:
                        response.raise_for_status()
                        return await response.text()
                else:  # POST
                    async with self._session.post(url, data=data) as response:
                        response.raise_for_status()
                        return await response.text()

            except aiohttp.ClientError as e:
                if retry_count < self.max_retries:
                    wait_time = (2 ** retry_count) * self.delay
                    logger.warning(f"요청 실패, {wait_time}초 후 재시도 ({retry_count + 1}/{self.max_retries}): {e}")
                    await asyncio.sleep(wait_time)
                    return await self._request(method, endpoint, params, data, retry_count + 1)
                raise

    async def _get(self, endpoint: str, params: Optional[Dict] = None) -> str:
        """GET 요청"""
        return await self._request("GET", endpoint, params=params)

    async def _post(self, endpoint: str, data: Optional[Dict] = None) -> str:
        """POST 요청"""
        return await self._request("POST", endpoint, data=data)

    # ==================== 대회 관련 API ====================

    async def get_competitions(self, page: int = 1, status: Optional[str] = None) -> CompetitionListResponse:
        """
        대회 목록 조회

        Args:
            page: 페이지 번호 (1부터 시작)
            status: 상태 필터 (예정/진행중/종료)
        """
        params = {
            "code": "game",
            "pageNum": page
        }
        if status:
            params["searchStatus"] = status

        html = await self._get(Endpoints.COMP_LIST, params)
        return self._parse_competition_list(html, page)

    def _parse_competition_list(self, html: str, page: int) -> CompetitionListResponse:
        """대회 목록 HTML 파싱"""
        soup = BeautifulSoup(html, "lxml")
        competitions = []

        # 테이블에서 대회 정보 추출 (class="list")
        table = soup.find("table", class_="list")
        if not table:
            logger.warning("대회 목록 테이블을 찾을 수 없습니다")
            return CompetitionListResponse(competitions=[], total_count=0, current_page=page)

        rows = table.find_all("tr")[1:]  # 헤더 제외
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 3:
                try:
                    # <a> 태그의 onclick에서 eventCd 추출
                    link = row.find("a")
                    onclick = link.get("onclick", "") if link else ""
                    comp_idx = self._extract_event_cd(onclick)

                    comp_name = cols[1].get_text(strip=True)
                    date_range = cols[2].get_text(strip=True)

                    start_date, end_date = self._parse_date_range(date_range)

                    competitions.append(Competition(
                        comp_idx=comp_idx,
                        comp_name=comp_name,
                        start_date=start_date,
                        end_date=end_date,
                        raw_data={"html_row": str(row)}
                    ))
                except Exception as e:
                    logger.error(f"대회 파싱 오류: {e}")

        # 총 페이지 수 추출
        total_pages = self._extract_total_pages(soup)

        return CompetitionListResponse(
            competitions=competitions,
            total_count=len(competitions),
            current_page=page,
            total_pages=total_pages
        )

    def _extract_event_cd(self, onclick: str) -> str:
        """onclick 속성에서 eventCd 추출"""
        import re
        match = re.search(r"funcView\(['\"]?(\w+)['\"]?", onclick)
        if match:
            return match.group(1)
        return ""

    def _parse_date_range(self, date_range: str) -> tuple:
        """날짜 범위 파싱"""
        from datetime import datetime
        import re

        # "2024.01.01 ~ 2024.01.03" 형식
        match = re.search(r"(\d{4}\.\d{2}\.\d{2})\s*~\s*(\d{4}\.\d{2}\.\d{2})", date_range)
        if match:
            start = datetime.strptime(match.group(1), "%Y.%m.%d").date()
            end = datetime.strptime(match.group(2), "%Y.%m.%d").date()
            return start, end

        # 단일 날짜
        match = re.search(r"(\d{4}\.\d{2}\.\d{2})", date_range)
        if match:
            single_date = datetime.strptime(match.group(1), "%Y.%m.%d").date()
            return single_date, single_date

        return None, None

    def _extract_total_pages(self, soup: BeautifulSoup) -> int:
        """페이지네이션에서 총 페이지 수 추출"""
        pagination = soup.find("ul", class_="pagination")
        if not pagination:
            return 1

        # 마지막 페이지 링크 찾기
        last_link = pagination.find("a", string="마지막")
        if last_link:
            onclick = last_link.get("onclick", "")
            import re
            match = re.search(r"funcPage\((\d+)\)", onclick)
            if match:
                return int(match.group(1))

        # 숫자 링크 중 최대값
        page_links = pagination.find_all("a")
        max_page = 1
        for link in page_links:
            text = link.get_text(strip=True)
            if text.isdigit():
                max_page = max(max_page, int(text))

        return max_page

    async def get_all_competitions(self) -> List[Competition]:
        """모든 대회 목록 조회"""
        all_competitions = []

        # 첫 페이지 조회
        first_response = await self.get_competitions(page=1)
        all_competitions.extend(first_response.competitions)

        # 나머지 페이지 병렬 조회
        if first_response.total_pages > 1:
            tasks = [
                self.get_competitions(page=p)
                for p in range(2, first_response.total_pages + 1)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, CompetitionListResponse):
                    all_competitions.extend(result.competitions)
                else:
                    logger.error(f"페이지 조회 오류: {result}")

        logger.info(f"총 {len(all_competitions)}개 대회 조회 완료")
        return all_competitions

    # ==================== 종목 관련 API ====================

    async def get_events(self, event_cd: str) -> List[Event]:
        """대회의 종목 목록 조회"""
        data = {"eventCd": event_cd}
        response = await self._post(Endpoints.SUB_EVENT_LIST_CNT, data)

        try:
            json_data = json.loads(response)
            events = []
            for item in json_data:
                events.append(Event(
                    event_cd=event_cd,
                    sub_event_cd=item.get("subEventCd"),
                    event_name=item.get("subEventNm"),
                    raw_data=item
                ))
            return events
        except json.JSONDecodeError:
            logger.error(f"종목 JSON 파싱 오류: {response[:200]}")
            return []

    # ==================== 선수 관련 API ====================

    async def get_players(self, event_cd: str, sub_event_cd: str) -> List[Player]:
        """종목별 참가 선수 조회"""
        data = {
            "eventCd": event_cd,
            "subEventCd": sub_event_cd
        }
        response = await self._post(Endpoints.ENTER_PLAYER_LIST, data)

        try:
            json_data = json.loads(response)
            players = []
            for item in json_data:
                players.append(Player(
                    player_name=item.get("plyNm", ""),
                    team_name=item.get("teamNm"),
                    raw_data=item
                ))
            return players
        except json.JSONDecodeError:
            logger.error(f"선수 JSON 파싱 오류: {response[:200]}")
            return []

    # ==================== 경기 결과 API ====================

    async def get_match_results(self, event_cd: str, sub_event_cd: str) -> List[Match]:
        """종목별 경기 결과 조회"""
        data = {
            "eventCd": event_cd,
            "subEventCd": sub_event_cd
        }
        response = await self._post(Endpoints.MATCH_DTL_INFO_LIST, data)

        try:
            json_data = json.loads(response)
            matches = []

            match_list = json_data.get("matchInfoList", [])
            for item in match_list:
                matches.append(Match(
                    round_name=item.get("roundNm"),
                    player1_name=item.get("upPlyNm"),
                    player1_score=self._safe_int(item.get("upScore")),
                    player2_name=item.get("downPlyNm"),
                    player2_score=self._safe_int(item.get("downScore")),
                    match_status=item.get("winGbn", "unknown"),
                    raw_data=item
                ))
            return matches
        except json.JSONDecodeError:
            logger.error(f"경기결과 JSON 파싱 오류: {response[:200]}")
            return []

    async def get_tableau_structure(self, event_cd: str, sub_event_cd: str) -> Dict:
        """토너먼트 구조 조회"""
        data = {
            "eventCd": event_cd,
            "subEventCd": sub_event_cd
        }
        response = await self._post(Endpoints.TABLEAU_GRP_DTL_LIST, data)

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            logger.error(f"토너먼트 구조 JSON 파싱 오류: {response[:200]}")
            return {}

    # ==================== 순위 API ====================

    async def get_rankings(self, event_cd: str, sub_event_cd: str) -> List[Ranking]:
        """종목별 최종 순위 조회"""
        data = {
            "eventCd": event_cd,
            "subEventCd": sub_event_cd
        }
        response = await self._post(Endpoints.FINISH_RANK, data)

        try:
            json_data = json.loads(response)
            rankings = []

            for item in json_data:
                rankings.append(Ranking(
                    rank_position=self._safe_int(item.get("rankNo", 0)),
                    player_name=item.get("plyNm", ""),
                    team_name=item.get("teamNm"),
                    match_count=self._safe_int(item.get("matchCnt", 0)),
                    win_count=self._safe_int(item.get("winCnt", 0)),
                    loss_count=self._safe_int(item.get("lossCnt", 0)),
                    raw_data=item
                ))
            return rankings
        except json.JSONDecodeError:
            logger.error(f"순위 JSON 파싱 오류: {response[:200]}")
            return []

    def _safe_int(self, value) -> int:
        """안전하게 정수 변환"""
        if value is None:
            return 0
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0

    # ==================== 전체 데이터 수집 ====================

    async def scrape_competition_full(self, comp_idx: str) -> Dict[str, Any]:
        """
        단일 대회의 전체 데이터 수집

        Returns:
            {
                "events": [...],
                "players": [...],
                "matches": [...],
                "rankings": [...]
            }
        """
        result = {
            "events": [],
            "players": [],
            "matches": [],
            "rankings": []
        }

        # 종목 조회
        events = await self.get_events(comp_idx)
        result["events"] = events

        # 각 종목별 상세 데이터 수집
        for event in events:
            if event.sub_event_cd:
                # 선수
                players = await self.get_players(comp_idx, event.sub_event_cd)
                result["players"].extend(players)

                # 경기 결과
                matches = await self.get_match_results(comp_idx, event.sub_event_cd)
                result["matches"].extend(matches)

                # 순위
                rankings = await self.get_rankings(comp_idx, event.sub_event_cd)
                result["rankings"].extend(rankings)

        return result
