"""
DE Bracket Scraper v4 - 엘리미나시옹디렉트 대진표 스크래퍼

주요 개선사항:
1. 탭 기반 네비게이션 (fnGetMatch 함수 사용)
2. row_table 컬럼 기반 파싱
3. user_box 페어링으로 매치 생성
4. 다음 라운드에서 점수 추출
5. BYE 처리 (빈 user_box = 자동 진출)
6. 멀티 탭 병합 (32강전 + 8강전 등)
7. Dual DE 지원 (국가대표 선발전 등 - First DE + Second DE)

기준: 제26회 전국남녀대학펜싱선수권대회 여대 플러레(개)

Dual DE 형식 (국가대표 선발전):
- 대진표 > 엘리미나시옹디렉트 탭의 schEtc01 selector로 감지
  - Option A: "32명의 면제자가 있는 예선엘리미나시옹디렉트" (First DE)
  - Option B: "본선 64강" (Second DE)
- First DE: 비시드 선수들의 예선
  - 128강(64경기) → 64강(32경기) = 2라운드
  - 32명 진출자 선발
- Second DE: 시드 32명 + First DE 진출자 32명 = 64명
  - 64강 → 32강 → 16강 → 8강 → 준결승 → 결승
"""

import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from playwright.async_api import Page
from loguru import logger


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
    is_in_progress: bool = False  # 대회가 진행 중인지 (DE 데이터 없음 상태)

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
            'format': 'single_de',  # 일반 DE (Dual DE와 구분)
            'starting_round': self.starting_round,
            'bracket_size': self.bracket_size,
            'participant_count': self.participant_count,
            'rounds': rounds,
            'seeding': [p.to_dict() for p in self.seeding],
            'bouts': [m.to_dict() for m in self.matches],
            'bouts_by_round': bouts_by_round,
            'champion': self.champion.to_dict() if self.champion else None,
            'is_in_progress': self.is_in_progress
        }


@dataclass
class DualDEBracket:
    """Dual DE 대진표 (국가대표 선발전 등)

    First DE + Second DE로 구성된 특수 형식
    """
    format: str = "dual_de"  # 형식 식별자

    # First DE (예선 DE)
    first_de: Optional[DEBracket] = None

    # Second DE (본선 DE)
    second_de: Optional[DEBracket] = None

    # 시드 선수들 (First DE 면제, Second DE 직행)
    seeded_players: List[DEPlayer] = field(default_factory=list)

    # First DE 진출자 (Second DE 참가)
    first_de_qualifiers: List[DEPlayer] = field(default_factory=list)

    # 전체 상태
    status: str = "pending"  # pending, first_de_in_progress, second_de_in_progress, completed

    def to_dict(self) -> Dict[str, Any]:
        first_dict = self.first_de.to_dict() if self.first_de else None
        second_dict = self.second_de.to_dict() if self.second_de else None

        # full_bouts: first_de + second_de 합산 (top-level)
        all_bouts = []
        if first_dict and first_dict.get('bouts'):
            all_bouts.extend(first_dict['bouts'])
        if second_dict and second_dict.get('bouts'):
            all_bouts.extend(second_dict['bouts'])

        # participant_count: 모든 bout에서 unique 선수 수
        player_names = set()
        for b in all_bouts:
            if b.get('player1_name'):
                player_names.add(b['player1_name'])
            if b.get('player2_name'):
                player_names.add(b['player2_name'])

        # champion: second_de에서 추출
        champion = None
        if self.second_de and self.second_de.champion:
            champion = self.second_de.champion.to_dict()

        return {
            'format': self.format,
            'status': self.status,
            'participant_count': len(player_names),
            'champion': champion,
            'seeded_players': [p.to_dict() for p in self.seeded_players],
            'first_de_qualifiers': [p.to_dict() for p in self.first_de_qualifiers],
            'first_de': first_dict,
            'second_de': second_dict,
            'full_bouts': all_bouts,
        }


class DEScraper:
    """DE 대진표 스크래퍼 v4"""

    # 라운드 크기 -> fnGetMatch 파라미터 매핑
    # 대한펜싱협회 웹사이트 기준:
    # fnGetMatch(7)=128강, (6)=64강, (5)=32강, (4)=16강, (3)=8강, (2)=준결승, (1)=결승
    ROUND_TO_FN_PARAM = {
        128: 7,
        64: 6,
        32: 5,
        16: 4,
        8: 3,
        4: 2,  # 준결승
        2: 1,  # 결승
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
        self.is_tournament_in_progress = False  # 대회 진행 중 상태

    async def _check_tournament_in_progress(self) -> bool:
        """대회가 진행 중인지 확인 (DE 데이터 없음 상태)

        협회 사이트는 DE 진행 전에 "토너먼트가 진행중인 상태 입니다." 메시지를 표시합니다.
        이 경우 DE 데이터를 스크래핑하면 안 됩니다.

        주의: .tournament_table 구조는 _has_tournament_table()에서 별도로 처리되므로
        이 함수가 호출되는 시점에서는 #A_table 기반 구조만 확인하면 됨.
        그러나 안전을 위해 .tournament_table도 체크하여 false positive를 방지.
        """
        in_progress = await self.page.evaluate("""
            () => {
                // 방법 1: "토너먼트가 진행중인 상태 입니다" 텍스트 확인
                const pageText = document.body?.innerText || '';
                if (pageText.includes('토너먼트가 진행중인 상태')) {
                    return true;
                }

                // 방법 2: .tournament_table이 있으면 진행 중이 아님
                // (이 경로는 _has_tournament_table()에서 먼저 처리되어야 하지만 안전장치)
                const tournamentTable = document.querySelector('.tournament_table .user_box');
                if (tournamentTable) {
                    return false;
                }

                // 방법 3: #A_table 기반 구조 확인
                const aTable = document.querySelector('#A_table');
                if (!aTable) {
                    // #A_table도 .tournament_table도 없으면 DE 구조 자체가 없음
                    return true;
                }

                // 방법 4: row01에 user_box가 없으면 데이터 없음
                const row01 = aTable.querySelector('td.row_table.row01');
                if (!row01) {
                    return true;
                }

                const userBoxes = row01.querySelectorAll('tr.user_box');
                if (userBoxes.length === 0) {
                    return true;
                }

                return false;
            }
        """)
        return in_progress or False

    async def _detect_starting_round_from_tab(self) -> Optional[int]:
        """첫 번째 활성화된 탭 이름에서 시작 라운드 크기 감지

        대한펜싱협회 웹사이트는 이벤트별로 시작 라운드에 해당하는 탭부터 표시합니다.
        예: 16강 시작 이벤트는 16강 탭이 첫 번째 활성 탭
        """
        import re

        tab_text = await self.page.evaluate("""
            () => {
                // .tab-tableau-wrap 내의 첫 번째 활성 탭(li.on) 찾기
                const activeTab = document.querySelector('.tab-tableau-wrap ul li.on');
                if (activeTab) {
                    return activeTab.textContent.trim();
                }
                // 활성 탭이 없으면 첫 번째 탭 반환
                const firstTab = document.querySelector('.tab-tableau-wrap ul li');
                if (firstTab) {
                    return firstTab.textContent.trim();
                }
                return null;
            }
        """)

        if tab_text:
            # "16강전" → 16, "32강전" → 32
            match = re.search(r'(\d+)강', tab_text)
            if match:
                size = int(match.group(1))
                logger.debug(f"활성 탭에서 시작 라운드 감지: '{tab_text}' → {size}")
                return size

            # 숫자가 없는 라운드 이름 처리: "준결승", "결승"
            if '준결승' in tab_text:
                logger.debug(f"활성 탭에서 시작 라운드 감지: '{tab_text}' → 4 (준결승)")
                return 4
            if '결승' in tab_text and '준결승' not in tab_text:
                logger.debug(f"활성 탭에서 시작 라운드 감지: '{tab_text}' → 2 (결승)")
                return 2

        return None

    async def parse_de_bracket(self, skip_in_progress_check: bool = False) -> DEBracket:
        """DE 대진표 파싱 메인 함수

        Args:
            skip_in_progress_check: True면 진행중 체크 스킵 (Dual DE 컨텍스트에서 사용)
        """
        bracket = DEBracket()

        try:
            # 0. 대회 진행 중 상태 확인 (DE 데이터 없음)
            # Dual DE 컨텍스트에서는 이미 페이지가 로드되어 있으므로 스킵
            if not skip_in_progress_check:
                self.is_tournament_in_progress = await self._check_tournament_in_progress()
                if self.is_tournament_in_progress:
                    logger.warning("⚠️ 토너먼트가 진행 중입니다 - DE 데이터 스크래핑 스킵")
                    bracket.is_in_progress = True  # 진행 중 플래그 설정
                    return bracket  # 빈 브래킷 반환

            # 0.5. tournament_table 구조 확인 (국가대표 선발전 등)
            has_tt = await self._has_tournament_table()
            if has_tt:
                logger.info("🏆 tournament_table 구조 감지 - 새 파서 사용")
                result = await self._parse_tournament_table_bracket()
                return result

            # 1. 시작 라운드 감지 - 활성화된 탭 이름으로 먼저 확인 (가장 신뢰할 수 있는 방법)
            starting_size = await self._detect_starting_round_from_tab()

            if starting_size:
                logger.info(f"탭 이름에서 시작 라운드 감지: {starting_size}강")
                # 해당 탭 로드
                fn_param = self.ROUND_TO_FN_PARAM.get(starting_size, 3)
                await self.page.evaluate(f"fnGetMatch({fn_param})")
                await asyncio.sleep(2)
            else:
                # 탭 감지 실패 시 기존 로직 (32강 탭 로드 후 row01 개수로 감지)
                logger.warning("탭 이름 감지 실패, 32강 탭에서 row01 개수로 감지 시도")
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

            # 1.5. ★★★ 협회 페이지 첫번째 라운드 교차 검증 ★★★
            verification = await self._verify_first_round_from_page(starting_size)
            if not verification['verified'] and verification['corrected_round']:
                corrected = verification['corrected_round']
                logger.warning(
                    f"🔧 일반 경로: 시작 라운드 교정 {starting_size}강 → {corrected}강"
                )
                starting_size = corrected
                bracket.starting_round = self.SIZE_TO_ROUND_NAME.get(
                    starting_size, f'{starting_size}강'
                )
                bracket.bracket_size = starting_size

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
            deduplicated = self._deduplicate_matches(all_matches)

            # 4.5. 빈 매치 필터링 (양쪽 모두 name=None인 placeholder 제거)
            valid_matches = [
                m for m in deduplicated
                if (m.player1 and m.player1.name) or (m.player2 and m.player2.name)
            ]
            if len(valid_matches) < len(deduplicated):
                logger.warning(f"빈 placeholder 매치 {len(deduplicated) - len(valid_matches)}개 제거")

            # 5. 유효성 검증으로 무효 경기 필터링
            bracket.matches = self._filter_valid_matches(valid_matches)
            logger.info(f"총 경기 수: {len(bracket.matches)} (중복제거 후 {len(deduplicated)}개에서 필터링)")

            # 6. 우승자 확인 (DOM → 결승 bout fallback)
            bracket.champion = await self._get_champion(matches=bracket.matches)
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

    def _is_valid_match(self, match: DEMatch) -> bool:
        """경기 유효성 검증

        무효 판정 기준:
        1. player1 == player2 (같은 사람이 양쪽에 있음) → 템플릿 데이터
        2. 둘 다 이름이 없고 BYE도 아님 → 아직 대진 미정
        3. 점수 없이 승자 없고 BYE도 아님 → 아직 경기 안 함
        """
        p1_name = match.player1.name if match.player1 else None
        p2_name = match.player2.name if match.player2 else None

        # 케이스 1: player1 == player2 (같은 사람) → 무효
        if p1_name and p2_name and p1_name == p2_name:
            logger.warning(f"⚠️ 무효 경기 감지 (동일 선수): {match.round_name} #{match.match_number}: {p1_name} vs {p2_name}")
            return False

        # 케이스 2: BYE 경기는 유효
        if match.is_bye_match:
            return True

        # 케이스 3: 둘 다 이름 없음 → 무효 (대진 미정)
        if not p1_name and not p2_name:
            logger.warning(f"⚠️ 무효 경기 감지 (대진 미정): {match.round_name} #{match.match_number}")
            return False

        # 케이스 4: 점수와 승자 모두 없음 → 아직 경기 안 함
        # (단, 한 명만 있는 경우는 BYE일 수 있으므로 유효)
        if p1_name and p2_name:
            # 두 선수 모두 있는데 점수가 없고 승자도 없으면 경기 안 함
            if match.player1_score is None and match.player2_score is None and match.winner is None:
                logger.warning(f"⚠️ 무효 경기 감지 (미완료): {match.round_name} #{match.match_number}: {p1_name} vs {p2_name}")
                return False

        return True

    def _filter_valid_matches(self, matches: List[DEMatch]) -> List[DEMatch]:
        """유효한 경기만 필터링"""
        valid_matches = []
        invalid_count = 0

        for match in matches:
            if self._is_valid_match(match):
                valid_matches.append(match)
            else:
                invalid_count += 1

        if invalid_count > 0:
            logger.info(f"📊 경기 유효성 검증: {len(matches)}개 중 {invalid_count}개 무효 → {len(valid_matches)}개 유효")

        return valid_matches

    async def _get_champion(self, matches: Optional[List[DEMatch]] = None) -> Optional[DEPlayer]:
        """우승자 정보 추출 (DOM → 결승 bout fallback)"""
        # 1차: DOM .row04 방식
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

        if champion and champion.get('name'):
            return DEPlayer(
                seed=champion['seed'],
                name=champion['name'],
                team=None,  # 우승자 칸의 aff는 결승 점수
                is_bye=False
            )

        # 2차: 결승 bout에서 추론 (dual_de 등 DOM 비어있는 경우)
        if matches:
            final_matches = [
                m for m in matches
                if m.round_name in ('결승', 'Final', '1-2', '2강')
            ]
            if final_matches:
                fm = final_matches[0]
                # winner 직접 확인
                if fm.winner:
                    return fm.winner
                # 점수 비교
                s1 = fm.player1_score or 0
                s2 = fm.player2_score or 0
                try:
                    s1_int = int(s1)
                    s2_int = int(s2)
                except (ValueError, TypeError):
                    s1_int, s2_int = 0, 0
                if s1_int > s2_int and s1_int > 0 and fm.player1:
                    return fm.player1
                elif s2_int > s1_int and s2_int > 0 and fm.player2:
                    return fm.player2

        return None

    # ========================================
    # .tournament_table 구조 파싱 (국가대표 선발전 등)
    # ========================================

    async def _detect_tournament_table_tabs(self) -> List[tuple]:
        """tournament_table 구조에서 실제 존재하는 탭 목록을 동적으로 감지

        Returns:
            List of (fn_param, tab_name) tuples, e.g. [(7, "128강전"), (5, "32강전"), (3, "8강전")]
        """
        import re

        tab_texts = await self.page.evaluate("""
            () => {
                const tabs = document.querySelectorAll('.tab-tableau-wrap ul li');
                return Array.from(tabs).map(t => t.textContent.trim());
            }
        """)

        if not tab_texts:
            # 탭 감지 실패 → 기본값 (32강전 + 8강전)
            logger.warning("tournament_table: 탭 감지 실패 → 기본값 (32강전 + 8강전)")
            return [(5, "32강전"), (3, "8강전")]

        logger.debug(f"tournament_table: 감지된 탭 텍스트 = {tab_texts}")

        # 탭 텍스트에서 라운드 크기 → fn_param 매핑
        tabs = []
        seen_params = set()
        for text in tab_texts:
            match = re.search(r'(\d+)강', text)
            if match:
                size = int(match.group(1))
                fn_param = self.ROUND_TO_FN_PARAM.get(size)
                if fn_param and fn_param not in seen_params:
                    tabs.append((fn_param, text))
                    seen_params.add(fn_param)
            elif '준결승' in text:
                fn_param = self.ROUND_TO_FN_PARAM.get(4)
                if fn_param and fn_param not in seen_params:
                    tabs.append((fn_param, text))
                    seen_params.add(fn_param)
            elif '결승' in text:
                fn_param = self.ROUND_TO_FN_PARAM.get(2)
                if fn_param and fn_param not in seen_params:
                    tabs.append((fn_param, text))
                    seen_params.add(fn_param)

        if not tabs:
            logger.warning("tournament_table: 탭 파싱 실패 → 기본값 (32강전 + 8강전)")
            return [(5, "32강전"), (3, "8강전")]

        # fn_param 내림차순 정렬 (큰 라운드부터 → 128강 → 64강 → 32강 → 8강)
        tabs.sort(key=lambda x: x[0], reverse=True)
        logger.info(f"tournament_table: 탭 {len(tabs)}개 감지: {[t[1] for t in tabs]}")
        return tabs

    async def _verify_first_round_from_page(self, detected_first_round: int) -> dict:
        """협회 페이지에서 첫번째 라운드를 직접 읽어 우리 감지 결과와 교차 검증

        두 가지 소스에서 검증:
        1. 활성 탭 (li.on > a): 맨 왼쪽 첫번째 라운드 탭의 텍스트
        2. #tournament_container 헤더 (thead td): 첫번째 라운드명 + 엘리미나시옹 디렉트

        Returns:
            dict: {
                'tab_round': int or None,     # 탭에서 읽은 첫번째 라운드 크기
                'header_round': int or None,  # 헤더에서 읽은 첫번째 라운드 크기
                'detected_round': int,        # 우리가 감지한 첫번째 라운드
                'verified': bool,             # 검증 통과 여부
                'corrected_round': int or None  # 불일치 시 올바른 라운드
            }
        """
        import re

        result = {
            'tab_round': None,
            'header_round': None,
            'detected_round': detected_first_round,
            'verified': False,
            'corrected_round': None
        }

        try:
            # 소스 1: 첫번째 탭 (맨 왼쪽 = 가장 큰 라운드)
            first_tab_text = await self.page.evaluate("""
                () => {
                    // 모든 탭을 읽어서 첫 번째(맨 왼쪽) 반환
                    const tabs = document.querySelectorAll('.tab-tableau-wrap ul li');
                    if (tabs.length > 0) {
                        return tabs[0].textContent.trim();
                    }
                    return null;
                }
            """)

            if first_tab_text:
                m = re.search(r'(\d+)강', first_tab_text)
                if m:
                    result['tab_round'] = int(m.group(1))
                elif '준결승' in first_tab_text:
                    result['tab_round'] = 4
                elif '결승' in first_tab_text:
                    result['tab_round'] = 2
                logger.debug(f"🔍 페이지 검증 - 첫번째 탭: '{first_tab_text}' → {result['tab_round']}")

            # 소스 2: #tournament_container 헤더의 첫번째 컬럼 (thead td)
            header_text = await self.page.evaluate("""
                () => {
                    // 방법 1: #tournament_container thead의 첫번째 td
                    const headerCells = document.querySelectorAll(
                        '#tournament_container table thead tr td'
                    );
                    if (headerCells.length > 0) {
                        return headerCells[0].textContent.trim();
                    }
                    // 방법 2: .tournament_table 내의 헤더
                    const ttHeaders = document.querySelectorAll(
                        '.tournament_table table thead tr td'
                    );
                    if (ttHeaders.length > 0) {
                        return ttHeaders[0].textContent.trim();
                    }
                    return null;
                }
            """)

            if header_text:
                m = re.search(r'(\d+)강', header_text)
                if m:
                    result['header_round'] = int(m.group(1))
                elif '준결승' in header_text:
                    result['header_round'] = 4
                elif '결승' in header_text:
                    result['header_round'] = 2
                logger.debug(f"🔍 페이지 검증 - 브라켓 헤더: '{header_text}' → {result['header_round']}")

        except Exception as e:
            logger.warning(f"🔍 페이지 첫번째 라운드 검증 중 오류: {e}")

        # 교차 검증
        page_sources = [r for r in [result['tab_round'], result['header_round']] if r is not None]

        if not page_sources:
            # 페이지 소스를 읽지 못함 → 경고만 남기고 통과
            logger.warning("🔍 페이지 검증: 페이지에서 첫번째 라운드를 읽지 못함 (검증 스킵)")
            result['verified'] = True  # 검증 불가 → 일단 통과
            return result

        # 페이지 소스 중 가장 큰 값 = 실제 첫번째 라운드
        page_first_round = max(page_sources)

        if detected_first_round == page_first_round:
            logger.info(f"✅ 페이지 검증 통과: 감지={detected_first_round}강, "
                       f"탭={result['tab_round']}, 헤더={result['header_round']}")
            result['verified'] = True
        else:
            logger.warning(
                f"❌ 페이지 검증 실패: 우리 감지={detected_first_round}강, "
                f"페이지 실제={page_first_round}강 "
                f"(탭={result['tab_round']}, 헤더={result['header_round']})"
            )
            result['corrected_round'] = page_first_round

        return result

    async def _has_tournament_table(self) -> bool:
        """페이지에 .tournament_table 구조가 있는지 확인"""
        return await self.page.evaluate("""
            () => !!document.querySelector('.tournament_table .user_box')
        """)

    async def _extract_tournament_table_data(self, skip_seeding: bool = False) -> Dict:
        """현재 탭의 tournament_table 데이터 추출

        Args:
            skip_seeding: True면 시딩 데이터 수집 스킵 (이미 수집됨)
        """
        return await self.page.evaluate(f"""
            () => {{
                const boxes = document.querySelectorAll('.user_box');
                if (!boxes.length) return {{ matches: [], seeding: [] }};

                const matchMap = new Map();
                const seedingMap = new Map();
                const skipSeeding = {str(skip_seeding).lower()};

                boxes.forEach(box => {{
                    const sym = box.getAttribute('compmatsym');
                    const dir = box.getAttribute('dir');
                    const xpos = parseInt(box.getAttribute('xposition')) || 0;
                    const score = parseInt(box.getAttribute('score')) || 0;
                    const wingbn = box.getAttribute('wingbn');
                    const matchcd = box.getAttribute('matchcd');
                    const seedNum = parseInt(box.querySelector('.num')?.textContent.trim()) || 0;
                    const name = box.querySelector('.user_name span')?.textContent.trim() || '';
                    const team = box.querySelector('.user_aff span')?.textContent.trim() || '';

                    const player = {{
                        seed: seedNum,
                        name,
                        team,
                        score,
                        isWinner: wingbn === '1',
                        isBye: name.toLowerCase().includes('bye') || name === ''
                    }};

                    // 시드 목록 구축 (가장 큰 xposition = 첫 라운드에서 수집)
                    // 128강/64강/32강 등 모든 라운드에서 수집, seedNum 중복시 첫 번째 유지
                    if (!skipSeeding && seedNum > 0 && name && !seedingMap.has(seedNum)) {{
                        seedingMap.set(seedNum, player);
                    }}

                    if (!matchMap.has(sym)) {{
                        matchMap.set(sym, {{ matchcd, xposition: xpos, red: null, green: null }});
                    }}

                    if (dir === 'UP') {{
                        matchMap.get(sym).red = player;
                    }} else {{
                        matchMap.get(sym).green = player;
                    }}
                }});

                // 경기 배열 생성
                const matches = [];
                let matchNum = 0;
                matchMap.forEach((match, sym) => {{
                    if (match.red && match.green) {{
                        matchNum++;
                        const roundName = match.xposition + '강';
                        let winner = null;
                        if (match.red.isWinner) {{
                            winner = match.red;
                        }} else if (match.green.isWinner) {{
                            winner = match.green;
                        }} else {{
                            // Fallback: wingbn 미설정 시 점수로 승자 추론
                            const redScore = parseInt(match.red.score) || 0;
                            const greenScore = parseInt(match.green.score) || 0;
                            if (redScore > greenScore && redScore > 0) {{
                                winner = match.red;
                            }} else if (greenScore > redScore && greenScore > 0) {{
                                winner = match.green;
                            }}
                        }}

                        matches.push({{
                            match_id: sym,
                            match_number: matchNum,
                            round_size: match.xposition,
                            round_name: roundName,
                            red_seed: match.red.seed,
                            red_name: match.red.name,
                            red_team: match.red.team,
                            red_score: match.red.score,
                            red_is_bye: match.red.isBye,
                            green_seed: match.green.seed,
                            green_name: match.green.name,
                            green_team: match.green.team,
                            green_score: match.green.score,
                            green_is_bye: match.green.isBye,
                            winner_name: winner ? winner.name : null,
                            winner_seed: winner ? winner.seed : null
                        }});
                    }}
                }});

                // 시드 배열 생성
                const seeding = [];
                seedingMap.forEach((p, seed) => {{
                    seeding.push({{ seed: p.seed, name: p.name, team: p.team }});
                }});
                seeding.sort((a, b) => a.seed - b.seed);

                return {{ matches, seeding }};
            }}
        """)

    async def _parse_tournament_table_bracket(self) -> DEBracket:
        """국가대표 선발전 스타일의 .tournament_table 구조 파싱

        이 구조는 .user_box 요소에 다음 속성들이 있음:
        - compmatsym: 경기 ID (같은 값의 두 box가 한 경기)
        - xposition: 라운드 크기 (64=64강)
        - score: 점수
        - wingbn: 승자 여부 (1=승)
        - dir: UP/DOWN (대진표 위치)

        수정됨 (2025-01): 멀티 탭 지원 추가
        수정됨 (2026-03): 128강/64강 탭 동적 감지 (하드코딩 제거)
        """
        bracket = DEBracket()

        try:
            # 실제 존재하는 탭을 동적으로 감지
            # fnGetMatch(7)=128강, (6)=64강, (5)=32강, (4)=16강, (3)=8강
            tabs_to_parse = await self._detect_tournament_table_tabs()
            logger.info(f"tournament_table: 감지된 탭 = {[(p, n) for p, n in tabs_to_parse]}")

            all_matches_data = []
            seeding_data = []
            seeding_collected = False

            for fn_param, tab_name in tabs_to_parse:
                # 탭 클릭
                logger.debug(f"tournament_table: {tab_name} 탭 로드 (fnGetMatch({fn_param}))")
                await self.page.evaluate(f"fnGetMatch({fn_param})")
                await asyncio.sleep(2)

                # 디버깅: .user_box 요소 수 확인
                box_count = await self.page.evaluate("document.querySelectorAll('.user_box').length")
                logger.debug(f"  → {tab_name}: .user_box 요소 수 = {box_count}")

                if box_count == 0:
                    logger.warning(f"  → {tab_name}: .user_box 요소가 없음! 스킵")
                    continue

                data = await self._extract_tournament_table_data(seeding_collected)
                tab_matches = data.get('matches', [])
                tab_seeding = data.get('seeding', [])

                logger.debug(f"  → {tab_name}: {len(tab_matches)}경기 수집")

                # 첫 번째 탭에서만 시딩 수집
                if not seeding_collected and tab_seeding:
                    seeding_data = tab_seeding
                    seeding_collected = True
                    logger.info(f"tournament_table: 시딩 수집 완료 ({len(seeding_data)}명)")

                all_matches_data.extend(tab_matches)

            # 중복 제거 (같은 match_id는 나중 것 유지 - 더 완전한 데이터)
            matches_by_id = {}
            for m in all_matches_data:
                match_id = m.get('match_id')
                if match_id:
                    # 점수가 있는 것을 우선
                    if match_id not in matches_by_id or (m.get('red_score') or m.get('green_score')):
                        matches_by_id[match_id] = m

            matches_data = list(matches_by_id.values())
            logger.info(f"tournament_table 파싱: {len(matches_data)}경기 (중복제거 후), {len(seeding_data)}명 시드")

            # 팀 이름 보정: tournament_table 구조에서 후속 라운드는
            # .user_aff span에 팀 이름 대신 이전 경기 점수(예: "15 : 13")가 들어감
            # 시딩 데이터와 첫 라운드 데이터에서 name→team 매핑 구축 후 보정
            import re
            score_pattern = re.compile(r'^\d+\s*:\s*\d+$')
            name_to_team = {}

            # 시딩 데이터에서 매핑 구축
            for s in seeding_data:
                if s.get('name') and s.get('team') and not score_pattern.match(s['team']):
                    name_to_team[s['name']] = s['team']

            # 첫 라운드(유효한 팀 이름이 있는) 경기에서 매핑 추가
            for m in matches_data:
                if m.get('red_name') and m.get('red_team') and not score_pattern.match(m['red_team']):
                    name_to_team[m['red_name']] = m['red_team']
                if m.get('green_name') and m.get('green_team') and not score_pattern.match(m['green_team']):
                    name_to_team[m['green_name']] = m['green_team']

            # 점수가 팀 이름으로 들어간 경우 보정
            fixed_count = 0
            for m in matches_data:
                for prefix in ('red', 'green'):
                    team_key = f'{prefix}_team'
                    name_key = f'{prefix}_name'
                    team_val = m.get(team_key, '')
                    if team_val and score_pattern.match(team_val):
                        correct_team = name_to_team.get(m.get(name_key, ''), '')
                        m[team_key] = correct_team
                        fixed_count += 1
                    elif not team_val and m.get(name_key):
                        m[team_key] = name_to_team.get(m[name_key], '')

            if fixed_count:
                logger.info(f"tournament_table: {fixed_count}개 팀 이름 보정 (점수→실제 팀)")

            # 라운드 이름 정규화 (4강 → 준결승, 2강 → 결승)
            for m in matches_data:
                round_size = m.get('round_size', 0)
                if round_size == 4:
                    m['round_name'] = '준결승'
                elif round_size == 2:
                    m['round_name'] = '결승'
                elif round_size == 1:
                    m['round_name'] = '우승'

            # 라운드 정보 추출
            round_sizes = set(m['round_size'] for m in matches_data if m.get('round_size'))
            if round_sizes:
                max_round = max(round_sizes)
                bracket.bracket_size = max_round
                bracket.starting_round = f'{max_round}강'

            # ★★★ 협회 페이지 첫번째 라운드 교차 검증 ★★★
            verification = await self._verify_first_round_from_page(bracket.bracket_size)
            if not verification['verified'] and verification['corrected_round']:
                corrected = verification['corrected_round']
                logger.warning(
                    f"🔧 첫번째 라운드 교정: {bracket.bracket_size}강 → {corrected}강 "
                    f"(페이지 실제 값 기준)"
                )
                bracket.bracket_size = corrected
                bracket.starting_round = f'{corrected}강'

                # 교정된 라운드의 탭 데이터가 빠졌다면 추가 수집
                corrected_fn = self.ROUND_TO_FN_PARAM.get(corrected)
                parsed_fn_params = {p for p, _ in tabs_to_parse}
                if corrected_fn and corrected_fn not in parsed_fn_params:
                    logger.info(f"🔄 교정된 라운드 {corrected}강 탭 추가 수집 "
                              f"(fnGetMatch({corrected_fn}))")
                    await self.page.evaluate(f"fnGetMatch({corrected_fn})")
                    await asyncio.sleep(2)

                    box_count = await self.page.evaluate(
                        "document.querySelectorAll('.user_box').length"
                    )
                    if box_count > 0:
                        extra_data = await self._extract_tournament_table_data(
                            skip_seeding=False
                        )
                        extra_matches = extra_data.get('matches', [])
                        extra_seeding = extra_data.get('seeding', [])

                        # 추가 경기 데이터 병합
                        for em in extra_matches:
                            mid = em.get('match_id')
                            if mid and mid not in matches_by_id:
                                matches_by_id[mid] = em
                        matches_data = list(matches_by_id.values())

                        # 시딩 데이터 교체 (더 큰 라운드의 시딩이 더 완전)
                        if extra_seeding and len(extra_seeding) > len(seeding_data):
                            logger.info(
                                f"🔄 시딩 데이터 교체: {len(seeding_data)}명 → "
                                f"{len(extra_seeding)}명 (교정 라운드에서)"
                            )
                            seeding_data = extra_seeding

                        # 라운드 크기 재계산
                        round_sizes = set(
                            m['round_size'] for m in matches_data if m.get('round_size')
                        )
                        if round_sizes:
                            max_round = max(round_sizes)
                            bracket.bracket_size = max_round
                            bracket.starting_round = f'{max_round}강'

            # ★★★ bracket_size 최종 검증: bout 수 및 시딩 수 기반 ★★★
            # 탭 감지나 페이지 검증이 실패하는 경우 (예: Second DE에서 탭이
            # 8강전부터만 표시되어 bracket_size=8이 되지만 실제 64명 참가)
            # 수집된 실제 데이터로 bracket_size를 보정
            total_bouts = len(matches_data)
            total_seeded = len(seeding_data)

            if total_bouts > 0:
                # Single elimination: n participants → n-1 bouts
                min_participants_from_bouts = total_bouts + 1
                min_bracket_from_bouts = 1
                while min_bracket_from_bouts < min_participants_from_bouts:
                    min_bracket_from_bouts *= 2

                if min_bracket_from_bouts > bracket.bracket_size:
                    logger.warning(
                        f"🔧 bracket_size 보정 (bout 수 기반): "
                        f"{bracket.bracket_size} → {min_bracket_from_bouts} "
                        f"({total_bouts} bouts → 최소 {min_participants_from_bouts} participants)"
                    )
                    bracket.bracket_size = min_bracket_from_bouts
                    bracket.starting_round = self.SIZE_TO_ROUND_NAME.get(
                        min_bracket_from_bouts, f'{min_bracket_from_bouts}강'
                    )

            if total_seeded > bracket.bracket_size:
                min_bracket_from_seeding = 1
                while min_bracket_from_seeding < total_seeded:
                    min_bracket_from_seeding *= 2

                logger.warning(
                    f"🔧 bracket_size 보정 (시딩 수 기반): "
                    f"{bracket.bracket_size} → {min_bracket_from_seeding} "
                    f"({total_seeded} seeded players)"
                )
                bracket.bracket_size = min_bracket_from_seeding
                bracket.starting_round = self.SIZE_TO_ROUND_NAME.get(
                    min_bracket_from_seeding, f'{min_bracket_from_seeding}강'
                )

            # 경기 데이터 변환
            for m in matches_data:
                red_player = DEPlayer(
                    seed=m['red_seed'],
                    name=m['red_name'],
                    team=m['red_team'],
                    is_bye=m['red_is_bye']
                )
                green_player = DEPlayer(
                    seed=m['green_seed'],
                    name=m['green_name'],
                    team=m['green_team'],
                    is_bye=m['green_is_bye']
                )

                winner = None
                if m['winner_name']:
                    if m['winner_name'] == m['red_name']:
                        winner = red_player
                    elif m['winner_name'] == m['green_name']:
                        winner = green_player

                match = DEMatch(
                    match_number=m['match_number'],
                    round_name=m['round_name'],
                    player1=red_player,
                    player2=green_player,
                    player1_score=m['red_score'],
                    player2_score=m['green_score'],
                    winner=winner,
                    is_bye_match=m['red_is_bye'] or m['green_is_bye']
                )
                bracket.matches.append(match)

            # 시드 데이터 변환
            for s in seeding_data:
                bracket.seeding.append(DEPlayer(
                    seed=s['seed'],
                    name=s['name'],
                    team=s['team'],
                    is_bye=False
                ))

            # 라운드 목록 구성
            rounds_found = sorted(set(m.round_name for m in bracket.matches),
                                 key=lambda r: int(r.replace('강', '')) if '강' in r else 0,
                                 reverse=True)
            bracket.rounds = rounds_found

            # self-bout 등 무효 경기 필터링 (R1a 버그 수정)
            bracket.matches = self._filter_valid_matches(bracket.matches)

            logger.info(f"tournament_table 파싱 완료: 라운드 {bracket.rounds}, {len(bracket.matches)}경기")

        except Exception as e:
            logger.error(f"tournament_table 파싱 오류: {e}")
            import traceback
            traceback.print_exc()

        return bracket

    # ========================================
    # Dual DE 지원 메서드 (국가대표 선발전 등)
    # ========================================

    async def detect_dual_de_format(self, wait_for_selector: bool = True) -> bool:
        """Dual DE 형식인지 감지 (대진표 > 엘리미나시옹디렉트 탭에서)

        schEtc01 selector가 있으면 Dual DE 형식
        - Option A: "32명의 면제자가 있는 예선엘리미나시옹디렉트"
        - Option B: "본선 64강"

        Args:
            wait_for_selector: True면 selector 로딩을 기다림 (기본 True)
        """
        # 1. 먼저 selector가 로드될 때까지 대기
        if wait_for_selector:
            try:
                await self.page.wait_for_selector('select#schEtc01', timeout=3000)
                logger.debug("✅ #schEtc01 selector 발견")
            except TimeoutError:
                logger.debug("❌ #schEtc01 selector 없음 (일반 DE 형식)")
                return False

        # 2. Selector 내용 확인
        result = await self.page.evaluate("""
            () => {
                const selector = document.querySelector('select#schEtc01');
                if (!selector) return { found: false, options: [] };

                // 옵션들 확인
                const options = Array.from(selector.options || []);
                const optionTexts = options.map(opt => opt.text.trim());

                const hasFirstDE = options.some(opt =>
                    opt.text.includes('면제자') || opt.text.includes('예선엘리미나시옹')
                );
                const hasSecondDE = options.some(opt =>
                    opt.text.includes('본선') && opt.text.includes('64강')
                );

                return {
                    found: true,
                    options: optionTexts,
                    hasFirstDE: hasFirstDE,
                    hasSecondDE: hasSecondDE,
                    isDualDE: hasFirstDE && hasSecondDE
                };
            }
        """)

        if result.get('found'):
            logger.debug(f"Dual DE 감지 결과: options={result.get('options')}, "
                        f"hasFirstDE={result.get('hasFirstDE')}, hasSecondDE={result.get('hasSecondDE')}")

            if result.get('isDualDE'):
                logger.info("🎯 Dual DE 형식 감지됨")
                return True
            else:
                logger.debug(f"Dual DE 조건 미충족: First={result.get('hasFirstDE')}, Second={result.get('hasSecondDE')}")

        return False

    async def get_dual_de_options(self) -> Dict[str, str]:
        """Dual DE 옵션 값 가져오기

        Returns:
            {"first_de": "A", "second_de": "B"} - option value
        """
        # 먼저 selector가 로드될 때까지 대기
        try:
            logger.info("    get_dual_de_options: selector 대기 중...")
            await self.page.wait_for_selector('select#schEtc01', timeout=3000)
            logger.info("    get_dual_de_options: selector 발견!")
        except Exception as e:
            logger.warning(f"schEtc01 selector를 찾을 수 없습니다 (timeout): {e}")
            return {}

        options = await self.page.evaluate("""
            () => {
                const selector = document.querySelector('select#schEtc01');
                if (!selector) return { error: 'selector_not_found' };

                const allOptions = Array.from(selector.options || []);
                const optionTexts = allOptions.map(opt => opt.text);

                const result = { debug_options: optionTexts };
                allOptions.forEach(opt => {
                    if (opt.text.includes('면제자') || opt.text.includes('예선엘리미나시옹')) {
                        result.first_de = opt.value;
                    }
                    if (opt.text.includes('본선') && opt.text.includes('64강')) {
                        result.second_de = opt.value;
                    }
                });

                return result;
            }
        """)
        if options and 'error' in options:
            logger.warning("schEtc01 selector를 찾을 수 없습니다 (evaluate)")
            return {}
        if options and 'debug_options' in options:
            logger.debug(f"Dual DE 옵션: {options.get('debug_options', [])}")
        return options or {}

    async def select_dual_de_phase(self, phase: str, cached_options: Dict[str, str] = None) -> bool:
        """Dual DE phase 선택 (first_de 또는 second_de)

        Args:
            phase: "first_de" 또는 "second_de"
            cached_options: 미리 가져온 옵션 (없으면 새로 가져옴)

        Returns:
            성공 여부
        """
        logger.debug(f"select_dual_de_phase 시작: phase={phase}")
        options = cached_options if cached_options else await self.get_dual_de_options()
        logger.debug(f"  옵션: {options}")

        if not options or 'first_de' not in options:
            logger.warning(f"Dual DE 옵션을 찾을 수 없습니다. 옵션: {options}")
            return False

        value = options.get(phase)
        if not value:
            logger.warning(f"'{phase}' 옵션 값을 찾을 수 없습니다. 사용 가능: {list(options.keys())}")
            return False

        try:
            # selector 존재 여부 먼저 확인
            selector_exists = await self.page.evaluate("""
                () => !!document.querySelector('select#schEtc01')
            """)
            logger.debug(f"  selector 존재 (JS): {selector_exists}")

            if not selector_exists:
                logger.warning("schEtc01 selector가 DOM에 없습니다")
                return False

            # 현재 선택된 인덱스 확인
            current_index = await self.page.evaluate("""
                () => document.querySelector('select#schEtc01')?.selectedIndex
            """)
            target_index = 0 if phase == "first_de" else 1

            # First DE (index 0)가 이미 선택된 상태면 페이지 갱신 없이 바로 사용
            if phase == "first_de" and current_index == 0:
                # 이미 First DE가 로드되어 있는지 확인
                has_data = await self.page.evaluate("""
                    () => document.querySelectorAll('.tournament_table .user_box').length > 0
                """)
                if has_data:
                    logger.debug(f"  First DE 이미 로드됨 (index={current_index}), 페이지 갱신 스킵")
                    return True

            # 선택 변경이 필요한 경우만 fnChangeRuls() 호출
            logger.debug(f"  selectedIndex={target_index}로 선택 후 fnChangeRuls() 호출 (현재={current_index})")
            await self.page.evaluate(f"""
                () => {{
                    const selector = document.querySelector('select#schEtc01');
                    if (selector) {{
                        selector.selectedIndex = {target_index};
                        // onchange 핸들러 호출 (fnChangeRuls)
                        if (typeof fnChangeRuls === 'function') {{
                            fnChangeRuls();
                        }} else {{
                            selector.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        }}
                    }}
                }}
            """)

            # .tournament_table .user_box 데이터가 로드될 때까지 대기 (최대 10초)
            for i in range(20):
                await asyncio.sleep(0.5)
                has_data = await self.page.evaluate("""
                    () => document.querySelectorAll('.tournament_table .user_box').length > 0
                """)
                if has_data:
                    logger.debug(f"  {phase} 데이터 로드 완료 ({(i+1)*0.5}초)")
                    break
            else:
                logger.warning(f"  {phase} 데이터 로드 타임아웃 (10초)")

            logger.debug(f"  {phase} 선택 완료")
            return True
        except Exception as e:
            logger.error(f"Dual DE phase 선택 실패: {e}")
            return False

    async def parse_dual_de_bracket(self, skip_detection: bool = True) -> Optional[DualDEBracket]:
        """Dual DE 대진표 파싱 (국가대표 선발전 등)

        1. First DE 선택 및 파싱 (128강 → 64강, 32명 진출)
        2. Second DE 선택 및 파싱 (64강 → 결승)
        3. 시드 선수 추출 (First DE 면제자)
        4. First DE 진출자 추출

        Args:
            skip_detection: True면 Dual DE 재감지 스킵 (이미 감지된 경우)
        """
        # Dual DE 형식 재확인 (선택적)
        if not skip_detection:
            is_dual_de = await self.detect_dual_de_format(wait_for_selector=True)
            if not is_dual_de:
                logger.info("Dual DE 형식이 아닙니다 - 일반 DE로 파싱")
                return None

        dual_bracket = DualDEBracket()

        try:
            # ===== 옵션 미리 가져오기 (한 번만) =====
            logger.info("  옵션 가져오기 시작...")
            cached_options = await self.get_dual_de_options()
            logger.info(f"  옵션 결과: {cached_options}")
            if not cached_options or 'first_de' not in cached_options:
                logger.warning("Dual DE 옵션을 가져올 수 없습니다")
                return None
            logger.info(f"  Dual DE 옵션 캐시됨: first_de={cached_options.get('first_de')}, second_de={cached_options.get('second_de')}")

            # ===== First DE 파싱 =====
            logger.info("📍 First DE (예선 DE) 파싱 시작...")
            select_result = await self.select_dual_de_phase("first_de", cached_options)
            if select_result:
                # Dual DE 컨텍스트에서는 진행중 체크 스킵
                first_de = await self.parse_de_bracket(skip_in_progress_check=True)
                if first_de and first_de.matches:
                    dual_bracket.first_de = first_de
                    logger.info(f"  First DE 파싱 완료: {len(first_de.matches)}경기, "
                               f"라운드: {first_de.starting_round} ~ 64강")

                    # First DE 진출자 추출 (64강에서 이긴 32명)
                    qualifiers = self._extract_first_de_qualifiers(first_de)
                    dual_bracket.first_de_qualifiers = qualifiers
                    logger.info(f"  First DE 진출자: {len(qualifiers)}명")

            # ===== Second DE 파싱 =====
            logger.info("📍 Second DE (본선 DE) 파싱 시작...")
            if await self.select_dual_de_phase("second_de", cached_options):
                # Dual DE 컨텍스트에서는 진행중 체크 스킵
                second_de = await self.parse_de_bracket(skip_in_progress_check=True)
                if second_de and second_de.matches:
                    dual_bracket.second_de = second_de
                    logger.info(f"  Second DE 파싱 완료: {len(second_de.matches)}경기, "
                               f"라운드: 64강 ~ 결승")

                    # 시드 선수 추출 (Second DE seeding에서 First DE 진출자가 아닌 선수)
                    seeded = self._extract_seeded_players(second_de, dual_bracket.first_de_qualifiers)
                    dual_bracket.seeded_players = seeded
                    logger.info(f"  시드 선수 (First DE 면제): {len(seeded)}명")

            # ===== 상태 결정 =====
            dual_bracket.status = self._determine_dual_de_status(dual_bracket)
            logger.info(f"📊 Dual DE 상태: {dual_bracket.status}")

            return dual_bracket

        except Exception as e:
            logger.error(f"Dual DE 파싱 오류: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _extract_first_de_qualifiers(self, first_de: DEBracket) -> List[DEPlayer]:
        """First DE 진출자 추출 (64강 승자들 = Second DE 진출)

        First DE는 128강 → 64강까지 진행, 64강 승자 32명이 Second DE로 진출
        """
        qualifiers = []

        # 64강 라운드의 승자들 추출
        for match in first_de.matches:
            if match.round_name == '64강' and match.winner:
                qualifiers.append(match.winner)

        # 시드 순서로 정렬
        qualifiers.sort(key=lambda p: p.seed)
        return qualifiers

    def _extract_seeded_players(
        self,
        second_de: DEBracket,
        first_de_qualifiers: List[DEPlayer]
    ) -> List[DEPlayer]:
        """시드 선수 추출 (First DE 면제자 = Second DE seeding 중 First DE 진출자가 아닌 선수)

        Second DE seeding에 있는 선수 중 First DE 진출자 명단에 없는 선수가 시드 선수
        """
        qualifier_names = {q.name for q in first_de_qualifiers if q.name}
        seeded = []

        for player in second_de.seeding:
            if player.name and player.name not in qualifier_names:
                seeded.append(player)

        # 시드 순서로 정렬
        seeded.sort(key=lambda p: p.seed)
        return seeded

    def _determine_dual_de_status(self, dual_bracket: DualDEBracket) -> str:
        """Dual DE 전체 상태 결정 — 경기 데이터 기반 (champion 의존 X)"""
        first_de = dual_bracket.first_de
        second_de = dual_bracket.second_de

        # First DE 없음 → pending
        if not first_de:
            return "pending"

        # First DE 완료 여부: 경기 데이터 기반
        first_matches = first_de.matches or []
        if not first_matches:
            return "first_de_in_progress"

        first_non_bye = [m for m in first_matches if not m.is_bye_match]
        first_all_winners = all(m.winner is not None for m in first_non_bye) if first_non_bye else False
        if not first_all_winners:
            return "first_de_in_progress"

        # Second DE 없음 → first_de_complete
        if not second_de:
            return "first_de_complete"

        # Second DE 완료 여부
        second_matches = second_de.matches or []
        if not second_matches:
            return "second_de_in_progress"

        # 결승 완료 여부
        final_matches = [m for m in second_matches if m.round_name in ('결승', 'Final', '1-2')]
        if final_matches and final_matches[0].winner:
            return "completed"

        # champion이 있으면 completed
        if second_de.champion:
            return "completed"

        return "second_de_in_progress"


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
