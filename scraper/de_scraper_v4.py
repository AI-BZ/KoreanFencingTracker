"""
DE Bracket Scraper v4 - 엘리미나시옹디렉트 대진표 스크래퍼

주요 개선사항:
1. 탭 기반 네비게이션 (fnGetMatch 함수 사용)
2. row_table 컬럼 기반 파싱
3. user_box 페어링으로 매치 생성
4. 다음 라운드에서 점수 추출
5. BYE 처리 (빈 user_box = 자동 진출)
6. 멀티 탭 병합 (32강전 + 8강전 등)

기준: 제26회 전국남녀대학펜싱선수권대회 여대 플러레(개)
"""

import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from playwright.async_api import Page
import logging

logger = logging.getLogger(__name__)


@dataclass
class DEPlayer:
    """DE 선수 정보"""
    seed: int
    name: Optional[str]
    team: Optional[str]
    is_bye: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'seed': self.seed,
            'name': self.name,
            'team': self.team,
            'is_bye': self.is_bye
        }


@dataclass
class DEMatch:
    """DE 경기 정보"""
    round_name: str  # 32강, 16강, 8강, 준결승, 결승
    match_number: int
    player1: DEPlayer
    player2: DEPlayer
    player1_score: Optional[int] = None
    player2_score: Optional[int] = None
    winner: Optional[DEPlayer] = None
    is_bye_match: bool = False  # 상대 없이 자동 진출

    def to_dict(self) -> Dict[str, Any]:
        return {
            'bout_id': f"{self.round_name}_{self.match_number:02d}",
            'round_name': self.round_name,
            'match_number': self.match_number,
            'player1_seed': self.player1.seed,
            'player1_name': self.player1.name,
            'player1_team': self.player1.team,
            'player1_score': self.player1_score,
            'player2_seed': self.player2.seed if self.player2 else None,
            'player2_name': self.player2.name if self.player2 else None,
            'player2_team': self.player2.team if self.player2 else None,
            'player2_score': self.player2_score,
            'winner_seed': self.winner.seed if self.winner else None,
            'winner_name': self.winner.name if self.winner else None,
            'is_bye': self.is_bye_match
        }


@dataclass
class DEBracket:
    """DE 대진표 전체 데이터"""
    starting_round: str = ""  # 시작 라운드 (32강, 64강 등)
    bracket_size: int = 0  # 32, 64, 128 등
    participant_count: int = 0
    seeding: List[DEPlayer] = field(default_factory=list)
    matches: List[DEMatch] = field(default_factory=list)
    champion: Optional[DEPlayer] = None

    def to_dict(self) -> Dict[str, Any]:
        # 라운드별 경기 그룹화
        bouts_by_round = {}
        for match in self.matches:
            if match.round_name not in bouts_by_round:
                bouts_by_round[match.round_name] = []
            bouts_by_round[match.round_name].append(match.to_dict())

        # 라운드 순서 정렬
        round_order = ['128강', '64강', '32강', '16강', '8강', '준결승', '결승']
        rounds = sorted(
            bouts_by_round.keys(),
            key=lambda x: round_order.index(x) if x in round_order else 99
        )

        return {
            'starting_round': self.starting_round,
            'bracket_size': self.bracket_size,
            'participant_count': self.participant_count,
            'rounds': rounds,
            'seeding': [p.to_dict() for p in self.seeding],
            'bouts': [m.to_dict() for m in self.matches],
            'bouts_by_round': bouts_by_round,
            'champion': self.champion.to_dict() if self.champion else None
        }


class DEScraper:
    """DE 대진표 스크래퍼 v4"""

    # 라운드 크기 -> fnGetMatch 파라미터 매핑
    ROUND_TO_FN_PARAM = {
        128: 7,
        64: 6,
        32: 5,
        16: 4,
        8: 3,
    }

    # 라운드 크기 -> 라운드 이름
    SIZE_TO_ROUND_NAME = {
        128: '128강',
        64: '64강',
        32: '32강',
        16: '16강',
        8: '8강',
        4: '준결승',
        2: '결승',
    }

    def __init__(self, page: Page):
        self.page = page

    async def parse_de_bracket(self) -> DEBracket:
        """DE 대진표 파싱 메인 함수"""
        bracket = DEBracket()

        try:
            # 1. 시작 라운드 감지 - 먼저 가장 큰 탭(32강)을 로드해서 확인
            # 32강전 탭 시도
            await self.page.evaluate("fnGetMatch(5)")
            await asyncio.sleep(2)

            starting_size = await self._detect_starting_round()
            if not starting_size:
                # 16강전 탭 시도
                await self.page.evaluate("fnGetMatch(4)")
                await asyncio.sleep(2)
                starting_size = await self._detect_starting_round()

            if not starting_size:
                # 8강전 탭으로 fallback
                await self.page.evaluate("fnGetMatch(3)")
                await asyncio.sleep(2)
                starting_size = 8

            bracket.starting_round = self.SIZE_TO_ROUND_NAME.get(starting_size, f'{starting_size}강')
            bracket.bracket_size = starting_size
            logger.info(f"DE 시작 라운드: {bracket.starting_round} ({starting_size}명)")

            # 2. 필요한 탭 결정
            tabs_needed = self._get_tabs_needed(starting_size)
            logger.info(f"필요한 탭: {tabs_needed}")

            # 3. 각 탭에서 데이터 수집
            all_matches = []
            seeding_collected = False

            for tab_size in tabs_needed:
                fn_param = self.ROUND_TO_FN_PARAM.get(tab_size, 3)
                logger.debug(f"탭 로드: fnGetMatch({fn_param}) - {tab_size}강전")

                # 탭 로드
                await self.page.evaluate(f"fnGetMatch({fn_param})")
                await asyncio.sleep(2)

                # 시딩 수집 (첫 번째 탭에서만)
                if not seeding_collected:
                    bracket.seeding = await self._parse_seeding()
                    bracket.participant_count = len(bracket.seeding)
                    seeding_collected = True
                    logger.info(f"시딩 수집 완료: {bracket.participant_count}명")

                # 매치 수집
                tab_matches = await self._parse_tab_matches(tab_size)
                all_matches.extend(tab_matches)
                logger.debug(f"  탭 {tab_size}강전: {len(tab_matches)}경기 수집")

            # 4. 중복 제거 및 병합
            bracket.matches = self._deduplicate_matches(all_matches)
            logger.info(f"총 경기 수: {len(bracket.matches)}")

            # 5. 우승자 확인
            bracket.champion = await self._get_champion()
            if bracket.champion:
                logger.info(f"우승자: {bracket.champion.name}")

            return bracket

        except Exception as e:
            logger.error(f"DE 파싱 오류: {e}")
            import traceback
            traceback.print_exc()
            return bracket

    async def _detect_starting_round(self) -> Optional[int]:
        """시작 라운드 크기 감지"""
        # 방법 1: row01의 user_box 개수로 감지
        row01_count = await self.page.evaluate("""
            () => {
                const aTable = document.querySelector('#A_table');
                if (!aTable) return null;

                const row01 = aTable.querySelector('td.row_table.row01');
                if (!row01) return null;

                const userBoxes = row01.querySelectorAll('tr.user_box');
                return userBoxes.length;
            }
        """)

        if row01_count and row01_count > 0:
            # row01의 user_box 개수 = 시작 라운드 크기
            logger.debug(f"row01 user_box 개수로 시작 라운드 감지: {row01_count}")
            return row01_count

        # 방법 2: firstGrpSize 값 확인
        first_grp_size = await self.page.evaluate("""
            () => {
                const input = document.querySelector('input[name=firstGrpSize]');
                if (!input) return null;
                const val = parseInt(input.value);
                return isNaN(val) ? null : val;
            }
        """)

        if first_grp_size and first_grp_size > 0:
            # firstGrpSize는 2^n 형태 (5=32, 6=64 등)
            size = 2 ** first_grp_size
            logger.debug(f"firstGrpSize로 시작 라운드 감지: 2^{first_grp_size} = {size}")
            return size

        return None

    def _get_tabs_needed(self, starting_size: int) -> List[int]:
        """
        필요한 탭 목록 반환

        예: 32강 시작
        - 32강전 탭: 32강, 16강 (8강까지 보이지만 준결승 데이터 없음)
        - 8강전 탭: 8강, 준결승, 결승, 우승자
        """
        tabs = []

        if starting_size >= 128:
            tabs.append(128)  # 128강전 ~ 64강
            tabs.append(64)   # 64강전 ~ 32강

        if starting_size >= 64:
            tabs.append(64)   # 64강전 ~ 32강

        if starting_size >= 32:
            tabs.append(32)   # 32강전 ~ 16강

        if starting_size >= 16:
            tabs.append(16)   # 16강전 ~ 8강

        # 항상 8강전 탭 필요 (준결승, 결승, 우승자)
        tabs.append(8)

        # 중복 제거
        return list(dict.fromkeys(tabs))

    async def _parse_seeding(self) -> List[DEPlayer]:
        """첫 번째 라운드에서 시딩 정보 추출"""
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
                    // 첫 라운드의 user_aff는 팀 정보 (점수 아님)
                    let team = userAff?.textContent?.trim() || null;
                    // 점수 형식이면 팀이 아님
                    if (team && team.includes(':')) {
                        team = null;
                    }

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

        return [
            DEPlayer(
                seed=p['seed'],
                name=p['name'],
                team=p['team'],
                is_bye=p['is_bye']
            )
            for p in seeding if p['seed'] > 0
        ]

    async def _parse_tab_matches(self, tab_size: int) -> List[DEMatch]:
        """현재 탭에서 매치 정보 추출"""
        matches = []

        # row01 ~ row04 각각 파싱
        for row_idx in range(1, 5):
            round_data = await self._parse_round_column(row_idx, tab_size)
            if not round_data:
                continue

            round_name = round_data['round_name']
            players = round_data['players']

            # 이전 라운드 승자들에서 점수 정보 가져오기
            next_round_scores = await self._get_next_round_scores(row_idx)

            # 인접 2명씩 매치 구성
            for i in range(0, len(players), 2):
                p1 = players[i]
                p2 = players[i + 1] if i + 1 < len(players) else None

                if not p1:
                    continue

                match_num = (i // 2) + 1

                # 점수 찾기 (다음 라운드에서)
                p1_score, p2_score = self._find_match_score(
                    p1, p2, next_round_scores
                )

                # 승자 결정
                winner = None
                is_bye = False

                if p2 is None or p2.is_bye:
                    # BYE 매치 - p1 자동 진출
                    winner = p1
                    is_bye = True
                elif p1.is_bye:
                    # p1이 BYE
                    winner = p2
                    is_bye = True
                elif p1_score is not None and p2_score is not None:
                    # 점수로 승자 결정
                    winner = p1 if p1_score > p2_score else p2

                match = DEMatch(
                    round_name=round_name,
                    match_number=match_num,
                    player1=p1,
                    player2=p2 if p2 else DEPlayer(0, None, None, True),
                    player1_score=p1_score,
                    player2_score=p2_score,
                    winner=winner,
                    is_bye_match=is_bye
                )
                matches.append(match)

        return matches

    async def _parse_round_column(self, row_idx: int, tab_size: int) -> Optional[Dict]:
        """특정 row_table 컬럼 파싱"""
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
                        aff: aff,
                        is_bye: !name
                    }});
                }});

                return {{
                    playerCount: userBoxes.length,
                    players: players
                }};
            }}
        """)

        if not data or data.get('playerCount', 0) == 0:
            return None

        # 라운드 이름 결정
        # tab_size=32, row_idx=1 -> 32강
        # tab_size=32, row_idx=2 -> 16강
        # tab_size=8, row_idx=1 -> 8강
        # tab_size=8, row_idx=2 -> 준결승
        round_sizes = {
            32: {1: 32, 2: 16, 3: 8, 4: 4},
            16: {1: 16, 2: 8, 3: 4, 4: 2},
            8: {1: 8, 2: 4, 3: 2, 4: 1},
            64: {1: 64, 2: 32, 3: 16, 4: 8},
            128: {1: 128, 2: 64, 3: 32, 4: 16},
        }

        size_map = round_sizes.get(tab_size, {})
        round_size = size_map.get(row_idx, tab_size // (2 ** (row_idx - 1)))
        round_name = self.SIZE_TO_ROUND_NAME.get(round_size, f'{round_size}강')

        # row04에 우승자만 있는 경우 제외 (경기가 아님)
        if row_idx == 4 and data['playerCount'] == 1:
            return None

        return {
            'round_name': round_name,
            'players': [
                DEPlayer(
                    seed=p['seed'],
                    name=p['name'],
                    team=p['aff'] if p['aff'] and ':' not in str(p['aff']) else None,
                    is_bye=p['is_bye']
                )
                for p in data['players']
            ]
        }

    async def _get_next_round_scores(self, current_row_idx: int) -> Dict[str, Dict]:
        """다음 라운드 컬럼에서 점수 정보 추출"""
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
                        // 점수 형식: "15 : 10" 또는 "V 15 : 10"
                        const scoreMatch = aff.match(/(\\d+)\\s*:\\s*(\\d+)/);
                        if (scoreMatch) {{
                            result[name] = {{
                                winner_score: parseInt(scoreMatch[1]),
                                loser_score: parseInt(scoreMatch[2]),
                                position: idx
                            }};
                        }}
                    }}
                }});

                return result;
            }}
        """)

        return scores or {}

    def _find_match_score(
        self,
        p1: DEPlayer,
        p2: Optional[DEPlayer],
        next_round_scores: Dict
    ) -> tuple:
        """매치 점수 찾기"""
        if not p1.name or not p2 or not p2.name:
            return (None, None)

        # p1이 승자인 경우
        if p1.name in next_round_scores:
            score_info = next_round_scores[p1.name]
            return (score_info['winner_score'], score_info['loser_score'])

        # p2가 승자인 경우
        if p2.name in next_round_scores:
            score_info = next_round_scores[p2.name]
            return (score_info['loser_score'], score_info['winner_score'])

        return (None, None)

    def _deduplicate_matches(self, matches: List[DEMatch]) -> List[DEMatch]:
        """중복 매치 제거 (같은 라운드+매치번호는 나중 것 유지)"""
        unique = {}
        for match in matches:
            key = (match.round_name, match.match_number)
            # 점수 정보가 있는 것을 우선
            if key not in unique or (match.player1_score is not None):
                unique[key] = match

        # 라운드 순서대로 정렬
        round_order = ['128강', '64강', '32강', '16강', '8강', '준결승', '결승']
        result = sorted(
            unique.values(),
            key=lambda m: (
                round_order.index(m.round_name) if m.round_name in round_order else 99,
                m.match_number
            )
        )
        return result

    async def _get_champion(self) -> Optional[DEPlayer]:
        """우승자 정보 추출"""
        champion = await self.page.evaluate("""
            () => {
                const aTable = document.querySelector('#A_table');
                if (!aTable) return null;

                // row04 (마지막 컬럼)에서 우승자 찾기
                const row04 = aTable.querySelector('td.row_table.row04');
                if (!row04) return null;

                const userBox = row04.querySelector('tr.user_box');
                if (!userBox) return null;

                const td = userBox.querySelector('td');
                if (!td) return null;

                const num = td.querySelector('.num');
                const userName = td.querySelector('.info .user_name');
                const userAff = td.querySelector('.info .user_aff');

                return {
                    seed: parseInt(num?.textContent?.trim()) || 0,
                    name: userName?.textContent?.trim() || null,
                    aff: userAff?.textContent?.trim() || null
                };
            }
        """)

        if not champion or not champion.get('name'):
            return None

        return DEPlayer(
            seed=champion['seed'],
            name=champion['name'],
            team=None,  # 우승자 칸의 aff는 결승 점수
            is_bye=False
        )


# 테스트 함수
async def test_de_scraper():
    """DE 스크래퍼 v4 테스트"""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        page.set_default_timeout(30000)

        try:
            # 페이지 이동
            print("1. 페이지 이동...")
            await page.goto("https://fencing.sports.or.kr/game/compList?code=game", timeout=15000)
            await asyncio.sleep(2)

            # 대회 클릭 (제26회 대학선수권)
            await page.locator("a[onclick*='COMPM00668']").first.click(timeout=5000)
            await asyncio.sleep(2)

            # 경기결과 탭
            await page.locator("a[onclick*='funcLeftSub']:has-text('경기결과')").first.click(timeout=5000)
            await asyncio.sleep(2)

            # 종목 선택 (여대 플러레)
            await page.select_option('select', 'COMPS000000000003805')
            await asyncio.sleep(3)

            # 엘리미나시옹디렉트 탭
            await page.locator("a:has-text('엘리미나시옹디렉트')").first.click(timeout=5000)
            await asyncio.sleep(2)

            # DE 스크래퍼 실행
            print("2. DE 스크래퍼 실행...")
            scraper = DEScraper(page)
            bracket = await scraper.parse_de_bracket()

            # 결과 출력
            result = bracket.to_dict()

            print(f"\n=== DE 스크래핑 결과 ===")
            print(f"시작 라운드: {result['starting_round']}")
            print(f"브래킷 크기: {result['bracket_size']}")
            print(f"참가자 수: {result['participant_count']}")
            print(f"라운드: {result['rounds']}")
            print(f"총 경기 수: {len(result['bouts'])}")

            if result['champion']:
                print(f"우승자: {result['champion']['name']}")

            print("\n=== 라운드별 경기 ===")
            for round_name, bouts in result['bouts_by_round'].items():
                print(f"\n[{round_name}] - {len(bouts)}경기")
                for bout in bouts[:3]:  # 첫 3경기만 출력
                    p1 = f"[{bout['player1_seed']}] {bout['player1_name'] or 'BYE'}"
                    p2 = f"[{bout['player2_seed']}] {bout['player2_name'] or 'BYE'}"
                    score = ""
                    if bout['player1_score'] is not None:
                        score = f" ({bout['player1_score']}:{bout['player2_score']})"
                    winner = bout['winner_name'] or ''
                    print(f"  Match {bout['match_number']}: {p1} vs {p2}{score} -> {winner}")

            return result

        except Exception as e:
            print(f"오류: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(test_de_scraper())
