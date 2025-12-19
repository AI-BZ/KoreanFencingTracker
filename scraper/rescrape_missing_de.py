"""
누락된 DE 데이터 재수집 스크립트
- 기존 데이터에서 DE 데이터가 없는 종목만 재수집
- 결과를 기존 파일에 병합
"""
import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
from loguru import logger
import sys

# 로그 설정
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO"
)
logger.add(
    "logs/rescrape_de.log",
    rotation="10 MB",
    level="DEBUG"
)

from full_scraper import KFFFullScraper, Competition


@dataclass
class MissingDEEvent:
    """DE 데이터가 누락된 종목"""
    event_cd: str
    sub_event_cd: str
    event_name: str
    competition_name: str
    competition_idx: int
    event_idx: int


async def find_missing_de_events(data_file: str) -> List[MissingDEEvent]:
    """DE 데이터가 누락된 종목 찾기"""
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    missing = []

    for comp_idx, comp in enumerate(data.get('competitions', [])):
        comp_data = comp.get('competition', {})
        comp_name = comp_data.get('name', 'Unknown')
        event_cd = comp_data.get('event_cd', '')

        for event_idx, event in enumerate(comp.get('events', [])):
            # DE 데이터 체크
            de_bracket = event.get('de_bracket', {})
            de_matches = event.get('de_matches', [])
            final_rankings = event.get('final_rankings', [])

            # DE 데이터가 없거나 빈 경우
            has_de = bool(
                de_bracket.get('seeding') or
                de_bracket.get('match_results') or
                de_matches or
                final_rankings
            )

            if not has_de:
                missing.append(MissingDEEvent(
                    event_cd=event_cd,
                    sub_event_cd=event.get('sub_event_cd', ''),
                    event_name=event.get('name', 'Unknown'),
                    competition_name=comp_name,
                    competition_idx=comp_idx,
                    event_idx=event_idx
                ))

    return missing


async def rescrape_de_data(
    data_file: str = "data/fencing_full_data_v2.json",
    output_file: str = None,
    limit: int = None
) -> None:
    """누락된 DE 데이터 재수집"""

    if output_file is None:
        output_file = data_file

    # 1. 누락된 종목 찾기
    logger.info(f"데이터 파일 분석 중: {data_file}")
    missing_events = await find_missing_de_events(data_file)
    logger.info(f"DE 데이터 누락 종목: {len(missing_events)}개")

    if not missing_events:
        logger.info("누락된 DE 데이터가 없습니다.")
        return

    if limit:
        missing_events = missing_events[:limit]
        logger.info(f"제한 적용: {limit}개 종목만 재수집")

    # 2. 데이터 로드
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 3. 대회별로 그룹화
    events_by_comp: Dict[str, List[MissingDEEvent]] = {}
    for event in missing_events:
        if event.event_cd not in events_by_comp:
            events_by_comp[event.event_cd] = []
        events_by_comp[event.event_cd].append(event)

    logger.info(f"재수집 대상: {len(events_by_comp)}개 대회, {len(missing_events)}개 종목")

    # 4. 스크래핑
    success_count = 0
    fail_count = 0

    async with KFFFullScraper(headless=True) as scraper:
        # 대회 목록 조회 (페이지 번호 계산용)
        all_competitions = await scraper.get_all_competitions(2019, 2025)

        # event_cd -> page_num 매핑
        page_map = {}
        for i, comp in enumerate(all_competitions):
            page_map[comp.event_cd] = (i // 10) + 1

        # 각 대회별로 처리
        for event_cd, events in events_by_comp.items():
            page_num = page_map.get(event_cd, 1)
            comp_name = events[0].competition_name

            logger.info(f"대회: {comp_name} ({len(events)}개 종목)")

            for event in events:
                logger.info(f"  종목: {event.event_name}")

                try:
                    # DE 데이터만 재수집
                    results = await scraper.get_full_results(
                        event.event_cd,
                        event.sub_event_cd,
                        page_num=page_num
                    )

                    # 결과 병합
                    target_event = data['competitions'][event.competition_idx]['events'][event.event_idx]

                    # DE 데이터 업데이트
                    if results.get('de_bracket'):
                        target_event['de_bracket'] = results['de_bracket']
                    if results.get('de_matches'):
                        target_event['de_matches'] = results['de_matches']
                    if results.get('final_rankings'):
                        target_event['final_rankings'] = results['final_rankings']
                        target_event['total_participants'] = len(results['final_rankings'])

                    # Pool 데이터도 없으면 업데이트
                    if not target_event.get('pool_rounds') and results.get('pool_rounds'):
                        target_event['pool_rounds'] = results['pool_rounds']
                    if not target_event.get('pool_total_ranking') and results.get('pool_total_ranking'):
                        target_event['pool_total_ranking'] = results['pool_total_ranking']

                    # 수집 결과 확인
                    has_new_de = bool(
                        results.get('de_bracket', {}).get('seeding') or
                        results.get('de_bracket', {}).get('match_results') or
                        results.get('de_matches') or
                        results.get('final_rankings')
                    )

                    if has_new_de:
                        success_count += 1
                        logger.info(f"    ✅ DE 데이터 수집 성공")
                    else:
                        fail_count += 1
                        logger.warning(f"    ⚠️ DE 데이터 없음 (대회에 DE 없을 수 있음)")

                except Exception as e:
                    fail_count += 1
                    logger.error(f"    ❌ 수집 실패: {e}")

                await asyncio.sleep(0.5)

            # 대회별 중간 저장
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            logger.info(f"중간 저장 완료")

    # 5. 최종 저장
    data['meta']['last_de_rescrape'] = datetime.now().isoformat()

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"")
    logger.info(f"=== 재수집 완료 ===")
    logger.info(f"성공: {success_count}개")
    logger.info(f"실패/없음: {fail_count}개")
    logger.info(f"출력: {output_file}")


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="누락된 DE 데이터 재수집")
    parser.add_argument("--input", type=str, default="data/fencing_full_data_v2.json",
                        help="입력 데이터 파일")
    parser.add_argument("--output", type=str, default=None,
                        help="출력 파일 (기본: 입력과 동일)")
    parser.add_argument("--limit", type=int, default=None,
                        help="재수집할 종목 수 제한 (테스트용)")
    parser.add_argument("--analyze-only", action="store_true",
                        help="분석만 수행 (재수집 안함)")

    args = parser.parse_args()

    if args.analyze_only:
        missing = await find_missing_de_events(args.input)
        print(f"\n총 {len(missing)}개 종목에 DE 데이터 누락")

        # 대회별 통계
        by_comp = {}
        for m in missing:
            if m.competition_name not in by_comp:
                by_comp[m.competition_name] = 0
            by_comp[m.competition_name] += 1

        print(f"\n대회별 누락 현황:")
        for comp, count in sorted(by_comp.items(), key=lambda x: -x[1])[:20]:
            print(f"  {comp}: {count}개")

        if len(by_comp) > 20:
            print(f"  ... 외 {len(by_comp) - 20}개 대회")
    else:
        await rescrape_de_data(
            data_file=args.input,
            output_file=args.output,
            limit=args.limit
        )


if __name__ == "__main__":
    asyncio.run(main())
