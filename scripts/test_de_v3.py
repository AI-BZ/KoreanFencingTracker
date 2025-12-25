#!/usr/bin/env python3
"""
DE 파싱 v3 테스트 스크립트

익산 국제대회에서 DE 파싱이 올바르게 작동하는지 검증
"""
import asyncio
import json
import sys
sys.path.insert(0, '/Users/gyejinpark/Documents/GitHub/FencingCommunityDropShipping')

from scraper.full_scraper import KFFFullScraper
from loguru import logger

# 테스트용 대회 정보
# 2025 코리아 익산 인터내셔널 펜싱선수권대회(U17,U20)
TEST_EVENT_CD = "COMPM00666"  # 대회 코드 (첫 페이지에서 확인)


async def test_de_parsing():
    """DE 파싱 v3 테스트"""
    logger.info("=" * 60)
    logger.info("DE 파싱 v3 테스트 시작")
    logger.info("=" * 60)

    async with KFFFullScraper(headless=True) as scraper:
        # 1. 먼저 종목 목록 조회
        logger.info(f"대회 코드: {TEST_EVENT_CD}")
        events = await scraper.get_events(TEST_EVENT_CD, page_num=1)

        if not events:
            logger.error("종목을 찾을 수 없습니다.")
            return False

        logger.info(f"종목 수: {len(events)}")
        for e in events[:5]:
            logger.info(f"  - {e.sub_event_cd}: {e.name}")

        # 개인전 종목 중 첫 번째 선택
        individual_events = [e for e in events if "(개)" in e.name or "개인" in e.name]
        if not individual_events:
            logger.warning("개인전 종목 없음, 첫 번째 종목 사용")
            test_event = events[0]
        else:
            test_event = individual_events[0]

        logger.info(f"\n테스트 종목: {test_event.name} ({test_event.sub_event_cd})")

        # 2. DE 데이터만 수집
        results = await scraper.get_de_only(
            event_cd=TEST_EVENT_CD,
            sub_event_cd=test_event.sub_event_cd,
            page_num=1
        )

        de_bracket = results.get("de_bracket", {})

        logger.info("-" * 40)
        logger.info("DE 파싱 결과:")
        logger.info("-" * 40)

        # 시딩 정보
        seeding = de_bracket.get("seeding", [])
        logger.info(f"시딩 선수 수: {len(seeding)}")
        if seeding:
            logger.info(f"시딩 예시 (상위 5명):")
            for s in seeding[:5]:
                logger.info(f"  {s['seed']}. {s['name']} ({s.get('team', '')})")

        # 라운드 정보
        rounds = de_bracket.get("rounds", [])
        logger.info(f"라운드: {rounds}")

        # 경기 정보
        bouts = de_bracket.get("bouts", [])
        logger.info(f"총 경기 수: {len(bouts)}")

        # 라운드별 경기 출력
        bouts_by_round = de_bracket.get("bouts_by_round", {})
        for round_name, round_bouts in bouts_by_round.items():
            logger.info(f"\n[{round_name}] - {len(round_bouts)}개 경기:")
            for bout in round_bouts[:3]:  # 각 라운드 처음 3경기만
                p1 = bout.get('player1', {})
                p2 = bout.get('player2', {})
                winner = bout.get('winnerName', '?')

                p1_name = p1.get('name', '?') if p1 else 'BYE'
                p2_name = p2.get('name', '?') if p2 else 'BYE'
                p1_score = p1.get('score', '-') if p1 else '-'
                p2_score = p2.get('score', '-') if p2 else '-'

                logger.info(f"  {p1_name} ({p1_score}) vs {p2_name} ({p2_score}) -> 승자: {winner}")

        # 검증: 승자/패자가 올바르게 설정되었는지
        logger.info("\n" + "=" * 40)
        logger.info("검증 결과:")
        logger.info("=" * 40)

        issues = []
        for bout in bouts:
            p1 = bout.get('player1', {})
            p2 = bout.get('player2', {})
            winner_name = bout.get('winnerName')

            # 승자가 없으면 문제
            if bout.get('isCompleted') and not winner_name:
                issues.append(f"완료된 경기에 승자 없음: {bout.get('bout_id')}")

            # 승자 점수가 패자 점수보다 낮으면 문제 (점수가 있는 경우만)
            if p1 and p2 and p1.get('score') and p2.get('score'):
                p1_score = p1['score']
                p2_score = p2['score']

                if winner_name == p1.get('name') and p1_score < p2_score:
                    issues.append(f"점수 역전: {p1.get('name')} ({p1_score}) 승리인데 점수가 낮음")
                elif winner_name == p2.get('name') and p2_score < p1_score:
                    issues.append(f"점수 역전: {p2.get('name')} ({p2_score}) 승리인데 점수가 낮음")

        if issues:
            logger.error(f"발견된 문제: {len(issues)}개")
            for issue in issues[:10]:
                logger.error(f"  - {issue}")
        else:
            if bouts:
                logger.success("✅ 모든 검증 통과!")
            else:
                logger.warning("⚠️ 파싱된 경기가 없습니다. 웹사이트 구조 확인 필요")

        # JSON 저장
        output_file = "/Users/gyejinpark/Documents/GitHub/FencingCommunityDropShipping/data/test_de_v3_result.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(de_bracket, f, ensure_ascii=False, indent=2)
        logger.info(f"결과 저장: {output_file}")

        return len(issues) == 0 and len(bouts) > 0


if __name__ == "__main__":
    success = asyncio.run(test_de_parsing())
    sys.exit(0 if success else 1)
