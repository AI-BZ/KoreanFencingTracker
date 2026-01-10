"""
대회 정보 파서
"""
from bs4 import BeautifulSoup
from typing import List, Optional, Tuple
from datetime import date, datetime
import re
from loguru import logger

from ..models import Competition, CompetitionStatus


class CompetitionParser:
    """대회 정보 파서"""

    @staticmethod
    def parse_list(html: str) -> List[Competition]:
        """대회 목록 HTML 파싱"""
        soup = BeautifulSoup(html, "lxml")
        competitions = []

        table = soup.find("table", class_="table")
        if not table:
            logger.warning("대회 목록 테이블을 찾을 수 없습니다")
            return competitions

        rows = table.find_all("tr")[1:]  # 헤더 제외

        for row in rows:
            try:
                comp = CompetitionParser._parse_row(row)
                if comp:
                    competitions.append(comp)
            except Exception as e:
                logger.error(f"대회 행 파싱 오류: {e}")

        return competitions

    @staticmethod
    def _parse_row(row) -> Optional[Competition]:
        """테이블 행 파싱"""
        cols = row.find_all("td")
        if len(cols) < 3:
            return None

        # onclick에서 eventCd 추출
        onclick = row.get("onclick", "")
        comp_idx = CompetitionParser._extract_event_cd(onclick)
        if not comp_idx:
            return None

        comp_name = cols[1].get_text(strip=True)
        date_range = cols[2].get_text(strip=True)
        start_date, end_date = CompetitionParser._parse_date_range(date_range)

        # 상태 추출 (있는 경우)
        status = CompetitionStatus.UNKNOWN
        if len(cols) > 3:
            status_text = cols[3].get_text(strip=True)
            status = CompetitionParser._parse_status(status_text)

        return Competition(
            comp_idx=comp_idx,
            comp_name=comp_name,
            start_date=start_date,
            end_date=end_date,
            status=status,
            raw_data={"html": str(row)}
        )

    @staticmethod
    def _extract_event_cd(onclick: str) -> str:
        """onclick 속성에서 eventCd 추출"""
        match = re.search(r"funcView\(['\"]?(\w+)['\"]?", onclick)
        return match.group(1) if match else ""

    @staticmethod
    def _parse_date_range(date_range: str) -> Tuple[Optional[date], Optional[date]]:
        """날짜 범위 파싱"""
        # "2024.01.01 ~ 2024.01.03" 또는 "2024-01-01 ~ 2024-01-03"
        patterns = [
            r"(\d{4}[.\-]\d{2}[.\-]\d{2})\s*~\s*(\d{4}[.\-]\d{2}[.\-]\d{2})",
            r"(\d{4}[.\-]\d{2}[.\-]\d{2})"
        ]

        for pattern in patterns:
            match = re.search(pattern, date_range)
            if match:
                groups = match.groups()
                if len(groups) == 2:
                    start = CompetitionParser._parse_single_date(groups[0])
                    end = CompetitionParser._parse_single_date(groups[1])
                    return start, end
                elif len(groups) == 1:
                    single = CompetitionParser._parse_single_date(groups[0])
                    return single, single

        return None, None

    @staticmethod
    def _parse_single_date(date_str: str) -> Optional[date]:
        """단일 날짜 파싱"""
        date_str = date_str.replace("-", ".").strip()
        try:
            return datetime.strptime(date_str, "%Y.%m.%d").date()
        except ValueError:
            return None

    @staticmethod
    def _parse_status(status_text: str) -> CompetitionStatus:
        """상태 텍스트 파싱"""
        status_map = {
            "예정": CompetitionStatus.SCHEDULED,
            "진행": CompetitionStatus.IN_PROGRESS,
            "진행중": CompetitionStatus.IN_PROGRESS,
            "종료": CompetitionStatus.COMPLETED,
            "완료": CompetitionStatus.COMPLETED,
        }
        return status_map.get(status_text, CompetitionStatus.UNKNOWN)

    @staticmethod
    def extract_total_pages(html: str) -> int:
        """페이지네이션에서 총 페이지 수 추출"""
        soup = BeautifulSoup(html, "lxml")
        pagination = soup.find("ul", class_="pagination")

        if not pagination:
            return 1

        # 마지막 페이지 링크
        last_link = pagination.find("a", string="마지막")
        if last_link:
            onclick = last_link.get("onclick", "")
            match = re.search(r"funcPage\((\d+)\)", onclick)
            if match:
                return int(match.group(1))

        # 숫자 링크 최대값
        max_page = 1
        for link in pagination.find_all("a"):
            text = link.get_text(strip=True)
            if text.isdigit():
                max_page = max(max_page, int(text))

        return max_page
