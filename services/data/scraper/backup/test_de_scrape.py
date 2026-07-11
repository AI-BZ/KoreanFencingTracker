"""
DE 브라켓 스크래핑 테스트 스크립트

특정 대회/종목의 DE 데이터를 수집하여 준결승/결승 데이터가 포함되는지 확인
"""

import asyncio
import json
import sys
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.full_scraper import KFFFullScraper
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_de_scrape(competition_cd: str, event_cd: str, page_num: int = 1):
    """특정 종목의 DE 데이터 수집 테스트"""

    async with KFFFullScraper(headless=True) as scraper:
        logger.info(f"DE 데이터 수집 시작: 대회={competition_cd}, 종목={event_cd}")

        # get_de_only 메서드 사용
        result = await scraper.get_de_only(
            event_cd=competition_cd,
            sub_event_cd=event_cd,
            page_num=page_num
        )

        bracket_data = result.get("de_bracket", {})

        # 결과 분석
        logger.info("=" * 60)
        logger.info("DE 데이터 수집 결과")
        logger.info("=" * 60)

        if bracket_data:
            logger.info(f"브라켓 크기: {bracket_data.get('bracket_size', 'N/A')}")
            logger.info(f"참가자 수: {bracket_data.get('participant_count', 'N/A')}")
            logger.info(f"시작 라운드: {bracket_data.get('starting_round', 'N/A')}")
            logger.info(f"수집된 라운드: {bracket_data.get('rounds', [])}")
            logger.info(f"시딩 수: {len(bracket_data.get('seeding', []))}")
            logger.info(f"경기(bouts) 수: {len(bracket_data.get('bouts', []))}")

            # 라운드별 경기 수
            bouts_by_round = bracket_data.get('bouts_by_round', {})
            logger.info("\n라운드별 경기 수:")
            for round_name, bouts in bouts_by_round.items():
                logger.info(f"  {round_name}: {len(bouts)}경기")

            # 준결승/결승 데이터 확인
            semifinal_bouts = bouts_by_round.get('준결승', [])
            final_bouts = bouts_by_round.get('결승', [])

            logger.info("\n" + "=" * 60)
            if semifinal_bouts:
                logger.info(f"✅ 준결승 데이터 있음: {len(semifinal_bouts)}경기")
                for bout in semifinal_bouts:
                    p1_data = bout.get('player1', {})
                    p2_data = bout.get('player2', {})
                    p1 = f"{p1_data.get('name', 'N/A')} ({p1_data.get('team', '')})"
                    p2 = f"{p2_data.get('name', 'N/A')} ({p2_data.get('team', '')})"
                    score = f"{p1_data.get('score', '-')} : {p2_data.get('score', '-')}"
                    inferred = " [추론]" if bout.get('isInferred') else ""
                    logger.info(f"  {p1} vs {p2} = {score}{inferred}")
            else:
                logger.warning("❌ 준결승 데이터 없음")

            if final_bouts:
                logger.info(f"✅ 결승 데이터 있음: {len(final_bouts)}경기")
                for bout in final_bouts:
                    p1_data = bout.get('player1', {})
                    p2_data = bout.get('player2', {})
                    p1 = f"{p1_data.get('name', 'N/A')} ({p1_data.get('team', '')})"
                    p2 = f"{p2_data.get('name', 'N/A')} ({p2_data.get('team', '')})"
                    score = f"{p1_data.get('score', '-')} : {p2_data.get('score', '-')}"
                    winner = bout.get('winnerName', 'N/A')
                    inferred = " [추론]" if bout.get('isInferred') else ""
                    logger.info(f"  {p1} vs {p2} = {score} (승자: {winner}){inferred}")
            else:
                logger.warning("❌ 결승 데이터 없음")

            logger.info("=" * 60)
        else:
            logger.warning("DE 브라켓 데이터가 비어있음")

        return bracket_data


async def main():
    # 테스트 대회: 2025년 완료된 대회 (1페이지에 있음)
    competition_cd = "COMPM00663"
    event_cd = "COMPS000000000003727"  # 예: 개인 종목

    # 최신 대회는 1페이지에 있음
    page_num = 1

    logger.info(f"테스트 대상: 대회={competition_cd}, 종목={event_cd}")

    result = await test_de_scrape(competition_cd, event_cd, page_num)

    if result:
        # 결과를 JSON으로 저장
        output_file = Path(__file__).parent.parent / "data" / "test_de_result.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"결과 저장: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
