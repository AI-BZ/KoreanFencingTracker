"""
선수 정보 파서
"""
from typing import List, Dict, Any, Optional
from loguru import logger

from ..models import Player


class PlayerParser:
    """선수 정보 파서"""

    @staticmethod
    def parse_json(json_data: List[Dict[str, Any]]) -> List[Player]:
        """JSON 응답에서 선수 정보 파싱"""
        players = []

        for item in json_data:
            try:
                player = PlayerParser._parse_item(item)
                if player:
                    players.append(player)
            except Exception as e:
                logger.error(f"선수 파싱 오류: {e}")

        return players

    @staticmethod
    def _parse_item(item: Dict[str, Any]) -> Optional[Player]:
        """단일 선수 아이템 파싱"""
        player_name = item.get("plyNm", "").strip()
        if not player_name:
            return None

        team_name = item.get("teamNm", "").strip() or None
        birth_year = PlayerParser._extract_birth_year(item)
        nationality = item.get("nationCd", "KOR")

        return Player(
            player_name=player_name,
            team_name=team_name,
            birth_year=birth_year,
            nationality=nationality,
            raw_data=item
        )

    @staticmethod
    def _extract_birth_year(item: Dict[str, Any]) -> Optional[int]:
        """출생년도 추출"""
        # 여러 가능한 필드명 시도
        for key in ["birthYear", "birthYr", "birthDate"]:
            value = item.get(key)
            if value:
                try:
                    # "1995" 또는 "1995-01-01" 형식 처리
                    year_str = str(value)[:4]
                    return int(year_str)
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def deduplicate(players: List[Player]) -> List[Player]:
        """선수 목록 중복 제거"""
        seen = set()
        unique_players = []

        for player in players:
            key = (player.player_name, player.team_name)
            if key not in seen:
                seen.add(key)
                unique_players.append(player)

        return unique_players

    @staticmethod
    def merge_from_matches(players: List[Player], matches: List) -> List[Player]:
        """경기 결과에서 추가 선수 정보 추출하여 병합"""
        player_names = {(p.player_name, p.team_name) for p in players}

        for match in matches:
            # player1
            if match.player1_name:
                key = (match.player1_name, None)
                if key not in player_names:
                    players.append(Player(player_name=match.player1_name))
                    player_names.add(key)

            # player2
            if match.player2_name:
                key = (match.player2_name, None)
                if key not in player_names:
                    players.append(Player(player_name=match.player2_name))
                    player_names.add(key)

        return players
