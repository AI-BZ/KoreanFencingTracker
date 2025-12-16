"""
경기 결과 파서
"""
from typing import List, Dict, Any, Optional
from loguru import logger

from ..models import Match, MatchStatus


class MatchParser:
    """경기 결과 파서"""

    @staticmethod
    def parse_json(json_data: Dict[str, Any]) -> List[Match]:
        """JSON 응답에서 경기 결과 파싱"""
        matches = []

        # matchInfoList에서 경기 정보 추출
        match_list = json_data.get("matchInfoList", [])

        for item in match_list:
            try:
                match = MatchParser._parse_item(item)
                if match:
                    matches.append(match)
            except Exception as e:
                logger.error(f"경기 파싱 오류: {e}")

        return matches

    @staticmethod
    def _parse_item(item: Dict[str, Any]) -> Optional[Match]:
        """단일 경기 아이템 파싱"""
        # 선수 정보
        player1_name = item.get("upPlyNm", "").strip()
        player2_name = item.get("downPlyNm", "").strip()

        # 빈 경기 스킵
        if not player1_name and not player2_name:
            return None

        # 점수
        player1_score = MatchParser._safe_int(item.get("upScore"))
        player2_score = MatchParser._safe_int(item.get("downScore"))

        # 승패 상태
        win_gbn = item.get("winGbn", "")
        match_status = MatchParser._parse_status(win_gbn)

        # 라운드 정보
        round_name = item.get("roundNm", "")
        group_name = item.get("grpNm", "")
        match_number = MatchParser._safe_int(item.get("matchNo"))

        return Match(
            round_name=round_name,
            group_name=group_name,
            match_number=match_number if match_number > 0 else None,
            player1_name=player1_name,
            player1_score=player1_score,
            player2_name=player2_name,
            player2_score=player2_score,
            match_status=match_status,
            raw_data=item
        )

    @staticmethod
    def _parse_status(win_gbn: str) -> MatchStatus:
        """승패 상태 파싱"""
        status_map = {
            "V": MatchStatus.VICTORY,
            "A": MatchStatus.ABANDON,
            "F": MatchStatus.FORFEIT,
            "E": MatchStatus.EXCLUSION,
            "P": MatchStatus.PENALTY,
        }
        return status_map.get(win_gbn.upper(), MatchStatus.UNKNOWN)

    @staticmethod
    def _safe_int(value) -> Optional[int]:
        """안전하게 정수 변환"""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def parse_tableau(json_data: Dict[str, Any]) -> Dict[str, Any]:
        """토너먼트 구조 파싱"""
        result = {
            "rounds": [],
            "groups": [],
            "bracket": {}
        }

        # 라운드 정보
        round_list = json_data.get("roundNmList", [])
        result["rounds"] = round_list

        # 그룹 정보
        group_list = json_data.get("groupKindList", [])
        result["groups"] = group_list

        return result
