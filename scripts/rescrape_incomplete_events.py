#!/usr/bin/env python3
"""
불완전한 DE 데이터 재스크래핑 스크립트

rescrape_targets.json에 있는 421개 이벤트를 재스크래핑하여
누락된 라운드 데이터를 수집합니다.
"""

import asyncio
import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from playwright.async_api import async_playwright, Page
from supabase import create_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Supabase 클라이언트
url = os.environ.get('SUPABASE_URL')
key = os.environ.get('SUPABASE_KEY')
supabase = create_client(url, key)

# 대한펜싱협회 사이트 기본 URL
BASE_URL = "https://fencing.sports.or.kr"

# 페이지당 대회 수 (대회 목록)
COMPS_PER_PAGE = 10


class DERescraper:
    """DE 데이터 재스크래핑 클래스"""

    # 라운드 크기 -> fnGetMatch 파라미터
    ROUND_TO_FN_PARAM = {
        128: 7, 64: 6, 32: 5, 16: 4, 8: 3, 4: 2, 2: 1
    }

    # 라운드 크기 -> 라운드 이름
    SIZE_TO_ROUND_NAME = {
        128: '128강', 64: '64강', 32: '32강', 16: '16강',
        8: '8강', 4: '준결승', 2: '결승'
    }

    def __init__(self, page: Page):
        self.page = page

    async def navigate_to_event(self, comp_idx: str, sub_event_cd: str, page_num: int = 1) -> bool:
        """대회/종목 페이지로 이동 (대회 목록에서 시작)"""
        try:
            # 1. 대회 목록 페이지 접속
            await self.page.goto(
                f"{BASE_URL}/game/compList?code=game",
                wait_until="domcontentloaded",
                timeout=15000
            )
            await asyncio.sleep(1.5)

            # 2. 페이지 이동 (필요한 경우)
            if page_num > 1:
                for _ in range(page_num - 1):
                    try:
                        next_btn = self.page.locator("a:has-text('다음페이지')")
                        await next_btn.click(timeout=3000)
                        await asyncio.sleep(1)
                    except:
                        break

            # 3. 대회 클릭 (여러 페이지 검색)
            clicked = False
            for attempt in range(5):  # 최대 5페이지 검색
                try:
                    comp_link = self.page.locator(f"a[onclick*=\"{comp_idx}\"]")
                    if await comp_link.count() > 0:
                        await comp_link.click(timeout=5000)
                        clicked = True
                        break
                    else:
                        # 다음 페이지로 이동
                        next_btn = self.page.locator("a:has-text('다음페이지')")
                        await next_btn.click(timeout=3000)
                        await asyncio.sleep(1)
                except:
                    break

            if not clicked:
                logger.warning(f"대회 {comp_idx}를 찾을 수 없음")
                return False

            await asyncio.sleep(1.5)

            # 4. 경기결과 탭 클릭
            result_tab = self.page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first
            await result_tab.click(timeout=5000)
            await asyncio.sleep(1.5)

            # 5. 종목 선택
            select = self.page.locator("select").first
            await select.select_option(value=sub_event_cd)
            await asyncio.sleep(0.5)

            # 6. 검색 버튼 클릭
            search_btn = self.page.locator("a[href='#search']").first
            await search_btn.click()
            await asyncio.sleep(1.5)

            # 7. 대진표 탭 클릭
            bracket_tab = self.page.locator("a:has-text('대진표')").first
            await bracket_tab.click(timeout=5000)
            await asyncio.sleep(1.5)

            # 8. 종목 다시 선택 (탭 전환 시 초기화될 수 있음)
            try:
                select = self.page.locator("select").first
                await select.select_option(value=sub_event_cd)
                await asyncio.sleep(0.5)

                search_btn = self.page.locator("a[href='#search']").first
                await search_btn.click()
                await asyncio.sleep(1)
            except:
                pass

            # 9. 엘리미나시옹디렉트 탭 클릭
            de_tab = self.page.locator("a:has-text('엘리미나시옹디렉트')").first
            await de_tab.click(timeout=5000)
            await asyncio.sleep(1.5)

            return True
        except Exception as e:
            logger.error(f"페이지 이동 오류: {e}")
            return False

    async def detect_starting_round(self) -> Optional[int]:
        """시작 라운드 감지"""
        import re

        tab_text = await self.page.evaluate("""
            () => {
                const activeTab = document.querySelector('.tab-tableau-wrap ul li.on');
                if (activeTab) return activeTab.textContent.trim();
                const firstTab = document.querySelector('.tab-tableau-wrap ul li');
                if (firstTab) return firstTab.textContent.trim();
                return null;
            }
        """)

        if tab_text:
            match = re.search(r'(\d+)강', tab_text)
            if match:
                return int(match.group(1))
            if '준결승' in tab_text:
                return 4
            if '결승' in tab_text:
                return 2

        return None

    def get_tabs_needed(self, starting_size: int) -> List[int]:
        """필요한 탭 목록"""
        tabs = []
        for size in [128, 64, 32, 16]:
            if starting_size >= size:
                tabs.append(size)
        tabs.append(8)  # 항상 8강전 탭 필요
        return list(dict.fromkeys(tabs))

    async def parse_seeding(self) -> List[Dict]:
        """시딩 정보 파싱"""
        seeding = await self.page.evaluate("""
            () => {
                const aTable = document.querySelector('#A_table');
                if (!aTable) return [];

                const row01 = aTable.querySelector('td.row_table.row01');
                if (!row01) return [];

                const userBoxes = row01.querySelectorAll('tr.user_box');
                const players = [];

                userBoxes.forEach((box) => {
                    const td = box.querySelector('td');
                    if (!td) return;

                    const num = td.querySelector('.num');
                    const info = td.querySelector('.info');
                    const userName = info?.querySelector('.user_name');
                    const userAff = info?.querySelector('.user_aff');

                    const seed = parseInt(num?.textContent?.trim()) || 0;
                    const name = userName?.textContent?.trim() || null;
                    let team = userAff?.textContent?.trim() || null;
                    if (team && team.includes(':')) team = null;

                    players.push({
                        seed: seed,
                        name: name,
                        team: team,
                        is_bye: !name
                    });
                });

                return players;
            }
        """)
        return [p for p in seeding if p.get('seed', 0) > 0]

    async def parse_tab_matches(self, tab_size: int) -> List[Dict]:
        """현재 탭에서 매치 파싱"""
        matches = []

        for row_idx in range(1, 5):
            round_data = await self.parse_round_column(row_idx, tab_size)
            if not round_data:
                continue

            round_name = round_data['round_name']
            players = round_data['players']

            # 다음 라운드에서 점수 정보
            next_scores = await self.get_next_round_scores(row_idx)

            for i in range(0, len(players), 2):
                p1 = players[i]
                p2 = players[i + 1] if i + 1 < len(players) else None

                if not p1:
                    continue

                match_num = (i // 2) + 1
                p1_score, p2_score = self.find_match_score(p1, p2, next_scores)

                # 승자 결정
                winner_name = None
                is_bye = False

                if p2 is None or p2.get('is_bye'):
                    winner_name = p1.get('name')
                    is_bye = True
                elif p1.get('is_bye'):
                    winner_name = p2.get('name')
                    is_bye = True
                elif p1_score is not None and p2_score is not None:
                    winner_name = p1['name'] if p1_score > p2_score else p2['name']

                match = {
                    'bout_id': f"{round_name}_{match_num:02d}",
                    'round_name': round_name,
                    'match_number': match_num,
                    'player1_seed': p1.get('seed'),
                    'player1_name': p1.get('name'),
                    'player1_team': p1.get('team'),
                    'player1_score': p1_score,
                    'player2_seed': p2.get('seed') if p2 else None,
                    'player2_name': p2.get('name') if p2 else None,
                    'player2_team': p2.get('team') if p2 else None,
                    'player2_score': p2_score,
                    'winner_name': winner_name,
                    'is_bye': is_bye
                }
                matches.append(match)

        return matches

    async def parse_round_column(self, row_idx: int, tab_size: int) -> Optional[Dict]:
        """특정 라운드 컬럼 파싱"""
        data = await self.page.evaluate(f"""
            () => {{
                const aTable = document.querySelector('#A_table');
                if (!aTable) return null;

                const col = aTable.querySelector('td.row_table.row0{row_idx}');
                if (!col) return null;

                const userBoxes = col.querySelectorAll('tr.user_box');
                const players = [];

                userBoxes.forEach((box) => {{
                    const td = box.querySelector('td');
                    if (!td) return;

                    const num = td.querySelector('.num');
                    const info = td.querySelector('.info');
                    const userName = info?.querySelector('.user_name');
                    const userAff = info?.querySelector('.user_aff');

                    const seed = parseInt(num?.textContent?.trim()) || 0;
                    const name = userName?.textContent?.trim() || null;
                    const aff = userAff?.textContent?.trim() || null;

                    players.push({{
                        seed: seed,
                        name: name,
                        team: aff && !aff.includes(':') ? aff : null,
                        is_bye: !name
                    }});
                }});

                return {{ playerCount: userBoxes.length, players: players }};
            }}
        """)

        if not data or data.get('playerCount', 0) == 0:
            return None

        # 라운드 이름 결정
        round_sizes = {
            128: {1: 128, 2: 64, 3: 32, 4: 16},
            64: {1: 64, 2: 32, 3: 16, 4: 8},
            32: {1: 32, 2: 16, 3: 8, 4: 4},
            16: {1: 16, 2: 8, 3: 4, 4: 2},
            8: {1: 8, 2: 4, 3: 2, 4: 1},
        }

        size_map = round_sizes.get(tab_size, {})
        round_size = size_map.get(row_idx, tab_size // (2 ** (row_idx - 1)))
        round_name = self.SIZE_TO_ROUND_NAME.get(round_size, f'{round_size}강')

        if row_idx == 4 and data['playerCount'] == 1:
            return None

        return {'round_name': round_name, 'players': data['players']}

    async def get_next_round_scores(self, current_row_idx: int) -> Dict:
        """다음 라운드에서 점수 추출"""
        next_row_idx = current_row_idx + 1
        if next_row_idx > 4:
            return {}

        scores = await self.page.evaluate(f"""
            () => {{
                const aTable = document.querySelector('#A_table');
                if (!aTable) return {{}};

                const col = aTable.querySelector('td.row_table.row0{next_row_idx}');
                if (!col) return {{}};

                const result = {{}};
                const userBoxes = col.querySelectorAll('tr.user_box');

                userBoxes.forEach((box, idx) => {{
                    const td = box.querySelector('td');
                    if (!td) return;

                    const userName = td.querySelector('.info .user_name');
                    const userAff = td.querySelector('.info .user_aff');

                    const name = userName?.textContent?.trim();
                    const aff = userAff?.textContent?.trim();

                    if (name && aff) {{
                        const scoreMatch = aff.match(/(\\d+)\\s*:\\s*(\\d+)/);
                        if (scoreMatch) {{
                            result[name] = {{
                                winner_score: parseInt(scoreMatch[1]),
                                loser_score: parseInt(scoreMatch[2])
                            }};
                        }}
                    }}
                }});

                return result;
            }}
        """)
        return scores or {}

    def find_match_score(self, p1: Dict, p2: Optional[Dict], scores: Dict) -> tuple:
        """매치 점수 찾기"""
        if not p1.get('name') or not p2 or not p2.get('name'):
            return (None, None)

        if p1['name'] in scores:
            info = scores[p1['name']]
            return (info['winner_score'], info['loser_score'])

        if p2['name'] in scores:
            info = scores[p2['name']]
            return (info['loser_score'], info['winner_score'])

        return (None, None)

    async def scrape_de_bracket(self) -> Dict[str, Any]:
        """DE 대진표 전체 스크래핑"""
        result = {
            'starting_round': '',
            'bracket_size': 0,
            'participant_count': 0,
            'rounds': [],
            'seeding': [],
            'bouts': [],
            'bouts_by_round': {}
        }

        try:
            # 시작 라운드 감지
            starting_size = await self.detect_starting_round()
            if not starting_size:
                starting_size = 32  # 기본값

            result['starting_round'] = self.SIZE_TO_ROUND_NAME.get(starting_size, f'{starting_size}강')
            result['bracket_size'] = starting_size

            # 필요한 탭들
            tabs_needed = self.get_tabs_needed(starting_size)

            all_matches = []
            seeding_collected = False

            for tab_size in tabs_needed:
                fn_param = self.ROUND_TO_FN_PARAM.get(tab_size, 3)

                # 탭 로드
                await self.page.evaluate(f"fnGetMatch({fn_param})")
                await asyncio.sleep(2)

                # 시딩 (첫 탭에서만)
                if not seeding_collected:
                    result['seeding'] = await self.parse_seeding()
                    result['participant_count'] = len(result['seeding'])
                    seeding_collected = True

                # 매치 수집
                tab_matches = await self.parse_tab_matches(tab_size)
                all_matches.extend(tab_matches)

            # 중복 제거
            unique = {}
            for match in all_matches:
                key = (match['round_name'], match['match_number'])
                if key not in unique or match['player1_score'] is not None:
                    unique[key] = match

            result['bouts'] = list(unique.values())

            # 라운드별 그룹화
            for bout in result['bouts']:
                round_name = bout['round_name']
                if round_name not in result['bouts_by_round']:
                    result['bouts_by_round'][round_name] = []
                result['bouts_by_round'][round_name].append(bout)

            result['rounds'] = list(result['bouts_by_round'].keys())

        except Exception as e:
            logger.error(f"DE 스크래핑 오류: {e}")

        return result


async def update_event_in_db(sub_event_cd: str, de_bracket: Dict) -> bool:
    """Supabase에 DE 브라켓 데이터 업데이트"""
    try:
        # 기존 이벤트 조회
        result = supabase.table('events').select('id, raw_data').eq('sub_event_cd', sub_event_cd).execute()

        if not result.data:
            logger.warning(f"이벤트 없음: {sub_event_cd}")
            return False

        event = result.data[0]
        event_id = event['id']
        raw_data = event.get('raw_data', {}) or {}

        # raw_data에 de_bracket 업데이트
        raw_data['de_bracket'] = de_bracket

        # 업데이트
        update_result = supabase.table('events').update({
            'raw_data': raw_data,
            'updated_at': datetime.now().isoformat()
        }).eq('id', event_id).execute()

        return bool(update_result.data)
    except Exception as e:
        logger.error(f"DB 업데이트 오류: {e}")
        return False


async def rescrape_single_event(
    context,
    comp_idx: str,
    sub_event_cd: str,
    event_name: str,
    page_num: int = 1
) -> Dict[str, Any]:
    """단일 이벤트 재스크래핑"""
    result = {
        'sub_event_cd': sub_event_cd,
        'event_name': event_name,
        'success': False,
        'bouts_count': 0,
        'rounds': []
    }

    page = await context.new_page()

    try:
        scraper = DERescraper(page)

        if not await scraper.navigate_to_event(comp_idx, sub_event_cd, page_num):
            result['error'] = 'Navigation failed'
            return result

        de_bracket = await scraper.scrape_de_bracket()

        if de_bracket and de_bracket.get('bouts'):
            # DB 업데이트
            if await update_event_in_db(sub_event_cd, de_bracket):
                result['success'] = True
                result['bouts_count'] = len(de_bracket['bouts'])
                result['rounds'] = de_bracket.get('rounds', [])
            else:
                result['error'] = 'DB update failed'
        else:
            result['error'] = 'No bouts found'

    except Exception as e:
        result['error'] = str(e)
    finally:
        await page.close()

    return result


async def test_single_event():
    """단일 이벤트 테스트"""
    # 테스트 대상: COMPM00664의 여일 사브르(개)
    comp_idx = "COMPM00664"
    sub_event_cd = "COMPS000000000003759"
    event_name = "여일 사브르(개)"

    logger.info(f"테스트: {comp_idx} / {event_name}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='ko-KR'
        )

        try:
            result = await rescrape_single_event(context, comp_idx, sub_event_cd, event_name)

            if result['success']:
                logger.info(f"✅ 성공: {result['bouts_count']}경기, {result['rounds']}")
            else:
                logger.error(f"❌ 실패: {result.get('error')}")

            return result
        finally:
            await browser.close()


async def main():
    """메인 실행"""
    # 재스크래핑 대상 로드
    targets_path = os.path.join(os.path.dirname(__file__), 'rescrape_targets.json')

    with open(targets_path, 'r') as f:
        targets_data = json.load(f)

    events = targets_data['events']
    total = len(events)

    logger.info(f"=" * 60)
    logger.info(f"DE 재스크래핑 시작")
    logger.info(f"대상: {total}개 이벤트, {len(targets_data['by_competition'])}개 대회")
    logger.info(f"=" * 60)

    # 결과 추적
    stats = {
        'total': total,
        'success': 0,
        'failed': 0,
        'errors': []
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            locale='ko-KR'
        )

        try:
            # 대회별로 그룹화하여 처리
            by_comp = {}
            for event in events:
                comp_idx = event['comp_idx']
                if comp_idx not in by_comp:
                    by_comp[comp_idx] = {
                        'name': event['comp_name'],
                        'events': []
                    }
                by_comp[comp_idx]['events'].append(event)

            processed = 0

            for comp_idx, comp_data in by_comp.items():
                comp_name = comp_data['name']
                comp_events = comp_data['events']

                logger.info(f"\n[{comp_idx}] {comp_name}")
                logger.info(f"  → {len(comp_events)}개 종목 처리 중...")

                for event in comp_events:
                    processed += 1
                    sub_event_cd = event['sub_event_cd']
                    event_name = event['event_name']

                    result = await rescrape_single_event(
                        context, comp_idx, sub_event_cd, event_name
                    )

                    if result['success']:
                        stats['success'] += 1
                        logger.info(
                            f"  ✅ [{processed}/{total}] {event_name}: "
                            f"{result['bouts_count']}경기, {result['rounds']}"
                        )
                    else:
                        stats['failed'] += 1
                        error = result.get('error', 'Unknown error')
                        stats['errors'].append({
                            'sub_event_cd': sub_event_cd,
                            'event_name': event_name,
                            'error': error
                        })
                        logger.warning(f"  ❌ [{processed}/{total}] {event_name}: {error}")

                    # 요청 간 딜레이
                    await asyncio.sleep(1)

        finally:
            await browser.close()

    # 결과 출력
    logger.info(f"\n" + "=" * 60)
    logger.info(f"재스크래핑 완료")
    logger.info(f"=" * 60)
    logger.info(f"총 대상: {stats['total']}개")
    logger.info(f"성공: {stats['success']}개")
    logger.info(f"실패: {stats['failed']}개")

    if stats['errors']:
        logger.info(f"\n실패 목록:")
        for err in stats['errors'][:20]:
            logger.info(f"  - {err['event_name']}: {err['error']}")
        if len(stats['errors']) > 20:
            logger.info(f"  ... 외 {len(stats['errors']) - 20}개")

    # 결과 저장
    result_path = '/tmp/rescrape_result.json'
    with open(result_path, 'w') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    logger.info(f"\n결과 저장: {result_path}")

    return stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='DE 데이터 재스크래핑')
    parser.add_argument('--test', action='store_true', help='단일 이벤트 테스트')
    parser.add_argument('--limit', type=int, default=0, help='처리할 이벤트 수 제한')

    args = parser.parse_args()

    if args.test:
        asyncio.run(test_single_event())
    else:
        asyncio.run(main())
