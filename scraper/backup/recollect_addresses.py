"""
실패한 주소 재수집 스크립트
- 네이버맵 사용
- 특정 항목은 주소 미상 처리
"""
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

# Logger 설정
logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")

# 주소 미상 처리할 팀 목록
ADDRESS_UNKNOWN_TEAMS = [
    "검속그대",
    "남현희 인터내셔널펜싱아카데미",
    "남현희펜싱클럽",
]


class NaverMapCollector:
    """네이버맵 주소 수집기"""

    BASE_URL = "https://map.naver.com/p/search/"

    def __init__(self):
        self.results = {
            "collected": [],
            "failed": [],
            "unknown": [],  # 주소 미상
        }

    def extract_province_from_address(self, address: str) -> str:
        """주소에서 시도 추출"""
        if not address:
            return ""

        province_map = {
            "서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천",
            "광주": "광주", "대전": "대전", "울산": "울산", "세종": "세종",
            "경기": "경기", "강원": "강원", "충북": "충북", "충남": "충남",
            "전북": "전북", "전남": "전남", "경북": "경북", "경남": "경남",
            "제주": "제주",
        }

        for key, value in province_map.items():
            if key in address:
                return value

        return ""

    async def search_naver_map(self, query: str, page) -> Optional[Dict]:
        """네이버맵에서 장소 검색"""
        try:
            # 법인 접두사 제거
            normalized_query = re.sub(r'^\s*\((사|주|재|학|의|합|유)\)\s*', '', query).strip()

            search_url = f"{self.BASE_URL}{normalized_query}"
            await page.goto(search_url, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # 검색 결과에서 첫 번째 항목 클릭
            first_result = page.locator('li.VLTHu').first
            if await first_result.count() > 0:
                await first_result.click()
                await asyncio.sleep(2)

            # 주소 추출 - 여러 방법 시도
            road_address = ""
            phone = ""

            # 방법 1: 특정 클래스로 추출
            addr_selectors = ['span.LDgIH', 'div.place_section_content span', 'span[class*="addr"]']
            for selector in addr_selectors:
                elem = page.locator(selector).first
                if await elem.count() > 0:
                    text = await elem.text_content()
                    if text and any(p in text for p in ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주']):
                        road_address = text.strip()
                        break

            # 방법 2: 전체 텍스트에서 주소 패턴 추출
            if not road_address:
                page_text = await page.locator('body').text_content()
                road_match = re.search(
                    r'(서울|부산|대구|인천|광주|대전|울산|세종특별자치시|세종|경기|강원특별자치도|강원|충북|충남|전북특별자치도|전북|전남|경북|경남|제주특별자치도|제주)[가-힣\s]+(?:로|길|대로)\s*[\d\-]+',
                    page_text
                )
                if road_match:
                    road_address = road_match.group(0).strip()

            # 전화번호 추출
            phone_match = re.search(r'(\d{2,4}[-\s]?\d{3,4}[-\s]?\d{4})', await page.locator('body').text_content() or "")
            if phone_match:
                phone = phone_match.group(1)

            if road_address:
                # 주소 길이 제한
                road_address = road_address[:200]
                return {
                    "name": query,
                    "road_address": road_address,
                    "province": self.extract_province_from_address(road_address),
                    "phone": phone,
                }

            return None

        except Exception as e:
            logger.debug(f"네이버맵 검색 오류 ({query}): {e}")
            return None

    async def collect_failed_addresses(self, manual_required_file: str):
        """실패한 주소들 재수집"""

        # 실패 목록 로드
        with open(manual_required_file, 'r', encoding='utf-8') as f:
            failed_teams = json.load(f)

        logger.info(f"총 {len(failed_teams)}개 팀 재수집 시작")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="ko-KR"
            )
            page = await context.new_page()

            for i, team in enumerate(failed_teams):
                team_name = team["name"]

                # 주소 미상 처리 대상 확인
                if any(unknown in team_name for unknown in ADDRESS_UNKNOWN_TEAMS):
                    logger.info(f"[{i+1}/{len(failed_teams)}] {team_name} → 주소 미상 처리")
                    team["address_status"] = "unknown"
                    team["address_error"] = "주소 미상"
                    self.results["unknown"].append(team)
                    continue

                # 네이버맵 검색
                logger.info(f"[{i+1}/{len(failed_teams)}] {team_name} 검색 중...")
                result = await self.search_naver_map(team_name, page)

                if result:
                    team["road_address"] = result["road_address"]
                    team["province"] = result["province"]
                    team["phone"] = result.get("phone", "")
                    team["address_source"] = "naver_map"
                    team["address_status"] = "collected"
                    team["address_error"] = ""
                    self.results["collected"].append(team)
                    logger.success(f"  ✓ {result['road_address']}")
                else:
                    # 실패 - 주소 미상 처리
                    team["address_status"] = "unknown"
                    team["address_error"] = "네이버맵에서도 찾을 수 없음 - 주소 미상"
                    self.results["unknown"].append(team)
                    logger.warning(f"  ✗ 미발견 → 주소 미상 처리")

                # 요청 간 딜레이
                await asyncio.sleep(1.5)

            await browser.close()

        # 결과 저장
        self.save_results()

        return self.results

    def save_results(self):
        """결과 저장"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_dir = Path(__file__).parent.parent / "data"

        # 수집 성공 목록
        collected_file = data_dir / f"recollected_addresses_{timestamp}.json"
        with open(collected_file, 'w', encoding='utf-8') as f:
            json.dump(self.results["collected"], f, ensure_ascii=False, indent=2)

        # 주소 미상 목록
        unknown_file = data_dir / f"address_unknown_{timestamp}.json"
        with open(unknown_file, 'w', encoding='utf-8') as f:
            json.dump(self.results["unknown"], f, ensure_ascii=False, indent=2)

        # 통계 출력
        logger.info("=" * 50)
        logger.info("재수집 결과:")
        logger.info(f"  수집 성공: {len(self.results['collected'])}개")
        logger.info(f"  주소 미상: {len(self.results['unknown'])}개")
        logger.info(f"  저장 위치: {data_dir}")


async def main():
    # 가장 최근 manual_required 파일 찾기
    data_dir = Path(__file__).parent.parent / "data"
    manual_files = sorted(data_dir.glob("manual_address_required_*.json"), reverse=True)

    if not manual_files:
        logger.error("manual_address_required 파일을 찾을 수 없습니다")
        return

    latest_file = manual_files[0]
    logger.info(f"사용할 파일: {latest_file}")

    collector = NaverMapCollector()
    await collector.collect_failed_addresses(str(latest_file))


if __name__ == "__main__":
    asyncio.run(main())
