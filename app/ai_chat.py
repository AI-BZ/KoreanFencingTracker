"""
AI 기반 자연어 검색 서비스
선수 라이벌, 전적, 통계 등을 자연어로 질문할 수 있음
"""
import re
import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from loguru import logger


@dataclass
class ChatResponse:
    """AI 챗봇 응답"""
    message: str
    data: Optional[Dict[str, Any]] = None
    suggestions: Optional[List[str]] = None
    disambiguation: Optional[List[Dict]] = None  # 동명이인 선택 필요시


class FencingAIChat:
    """펜싱 데이터 AI 챗봇 (로컬 데이터 기반)"""

    def __init__(self, data_cache: Dict[str, Any]):
        """
        Args:
            data_cache: 메모리에 로드된 펜싱 데이터
        """
        self.data = data_cache
        self._build_player_index()

    def _build_player_index(self):
        """선수 인덱스 구축 (빠른 검색용)"""
        self.players = {}  # name -> [{team, events: []}]
        self.player_results = {}  # (name, team) -> [results]

        for comp in self.data.get("competitions", []):
            comp_info = comp.get("competition", {})
            comp_name = comp_info.get("name", "")

            for event in comp.get("events", []):
                event_name = event.get("name", "")
                sub_event_cd = event.get("sub_event_cd", "")

                # 풀 결과에서 선수 추출
                event_results = comp.get("results", {}).get(sub_event_cd, {})
                for pool in event_results.get("pool_results", []):
                    for player in pool.get("results", []):
                        name = player.get("name", "").strip()
                        team = player.get("team", "").strip()

                        if not name:
                            continue

                        # 선수 인덱스에 추가
                        if name not in self.players:
                            self.players[name] = []

                        # 해당 팀 정보 찾기
                        team_entry = None
                        for entry in self.players[name]:
                            if entry["team"] == team:
                                team_entry = entry
                                break

                        if team_entry is None:
                            team_entry = {"team": team, "events": []}
                            self.players[name].append(team_entry)

                        team_entry["events"].append({
                            "competition": comp_name,
                            "event": event_name,
                            "rank": player.get("rank"),
                            "win_rate": player.get("win_rate")
                        })

        logger.info(f"선수 인덱스 구축 완료: {len(self.players)}명")

    def process_query(self, query: str) -> ChatResponse:
        """자연어 질문 처리"""
        query = query.strip()

        # 질문 유형 분석
        query_type, params = self._analyze_query(query)

        if query_type == "rival":
            return self._handle_rival_query(params)
        elif query_type == "player_info":
            return self._handle_player_info(params)
        elif query_type == "player_search":
            return self._handle_player_search(params)
        elif query_type == "competition_search":
            return self._handle_competition_search(params)
        elif query_type == "stats":
            return self._handle_stats_query(params)
        else:
            return self._handle_general_query(query)

    def _analyze_query(self, query: str) -> Tuple[str, Dict]:
        """질문 유형 분석"""
        query_lower = query.lower()

        # 라이벌 관련 질문
        rival_patterns = [
            r"(.+?)의?\s*라이벌",
            r"(.+?)가?\s*많이\s*(진|패한|졌)",
            r"(.+?)와?\s*상대전적",
            r"(.+?)의?\s*천적",
        ]

        for pattern in rival_patterns:
            match = re.search(pattern, query)
            if match:
                player_name = match.group(1).strip()
                # "은/는/이/가" 등 조사 제거
                player_name = re.sub(r"[은는이가을를의]$", "", player_name)
                return "rival", {"player_name": player_name}

        # 선수 정보 질문
        info_patterns = [
            r"(.+?)의?\s*(성적|전적|기록|순위)",
            r"(.+?)는?\s*어떤\s*선수",
            r"(.+?)\s*(몇\s*등|몇등)",
        ]

        for pattern in info_patterns:
            match = re.search(pattern, query)
            if match:
                player_name = match.group(1).strip()
                player_name = re.sub(r"[은는이가을를의]$", "", player_name)
                return "player_info", {"player_name": player_name}

        # 선수 검색
        search_patterns = [
            r"(.+?)\s*(누구|찾아|검색)",
            r"선수\s+(.+)",
        ]

        for pattern in search_patterns:
            match = re.search(pattern, query)
            if match:
                return "player_search", {"search_term": match.group(1).strip()}

        # 대회 검색
        comp_patterns = [
            r"(.+?)\s*대회",
            r"전국체육대회",
            r"선수권대회",
        ]

        for pattern in comp_patterns:
            match = re.search(pattern, query)
            if match:
                return "competition_search", {"search_term": query}

        # 통계 질문
        if any(word in query_lower for word in ["통계", "몇 개", "몇개", "총"]):
            return "stats", {"query": query}

        # 이름만 입력한 경우 선수 검색으로 처리
        if len(query) <= 10 and not any(c in query for c in "?!어떤무엇"):
            return "player_info", {"player_name": query.strip()}

        return "general", {"query": query}

    def _handle_rival_query(self, params: Dict) -> ChatResponse:
        """라이벌 질문 처리"""
        player_name = params.get("player_name", "")

        # 동명이인 확인
        if player_name in self.players:
            same_name_players = self.players[player_name]

            if len(same_name_players) > 1:
                # 동명이인 존재 - 선택 필요
                options = []
                for i, entry in enumerate(same_name_players):
                    recent = entry["events"][-1] if entry["events"] else {}
                    options.append({
                        "id": i,
                        "name": player_name,
                        "team": entry["team"],
                        "event_count": len(entry["events"]),
                        "recent_competition": recent.get("competition", "")
                    })

                return ChatResponse(
                    message=f"'{player_name}' 선수가 {len(options)}명 있습니다. 어느 선수를 찾으시나요?",
                    disambiguation=options,
                    suggestions=[
                        f"{player_name} ({opt['team']})" for opt in options
                    ]
                )

            # 한 명만 있는 경우
            player_data = same_name_players[0]
            return self._generate_rival_response(player_name, player_data)

        # 선수를 찾을 수 없음
        similar = self._find_similar_players(player_name)
        if similar:
            return ChatResponse(
                message=f"'{player_name}' 선수를 찾을 수 없습니다. 혹시 다음 중 찾으시는 분이 있나요?",
                suggestions=similar[:5]
            )

        return ChatResponse(
            message=f"'{player_name}' 선수를 찾을 수 없습니다. 정확한 이름을 입력해주세요.",
            suggestions=["선수 이름을 정확히 입력해주세요", "예: 박소윤, 김지연"]
        )

    def _generate_rival_response(self, player_name: str, player_data: Dict) -> ChatResponse:
        """라이벌 정보 생성 (실제로는 DE 결과가 필요함)"""
        team = player_data.get("team", "소속 미상")
        events = player_data.get("events", [])

        # 현재 데이터에는 DE 결과가 없어서 임시 메시지
        message = f"""**{player_name}** ({team})

참가 대회: {len(events)}개

현재 데이터에는 개인별 대결 기록이 포함되어 있지 않아 라이벌 분석이 불가능합니다.
라이벌 분석을 위해서는 본선(엘리미나시옹 디렉트) 경기 결과가 필요합니다.

대신 이 선수의 대회 성적을 보여드립니다:"""

        # 최근 5개 대회 성적
        recent_events = events[-5:] if events else []
        data = {
            "player_name": player_name,
            "team": team,
            "total_events": len(events),
            "recent_events": recent_events
        }

        return ChatResponse(
            message=message,
            data=data,
            suggestions=[
                f"{player_name} 성적 보기",
                f"{player_name} 참가 대회",
            ]
        )

    def _handle_player_info(self, params: Dict) -> ChatResponse:
        """선수 정보 조회"""
        player_name = params.get("player_name", "")

        if player_name in self.players:
            same_name_players = self.players[player_name]

            if len(same_name_players) > 1:
                # 동명이인 존재
                options = []
                for i, entry in enumerate(same_name_players):
                    recent = entry["events"][-1] if entry["events"] else {}
                    options.append({
                        "id": i,
                        "name": player_name,
                        "team": entry["team"],
                        "event_count": len(entry["events"]),
                        "recent_competition": recent.get("competition", "")
                    })

                return ChatResponse(
                    message=f"'{player_name}' 선수가 {len(options)}명 있습니다.",
                    disambiguation=options
                )

            # 한 명만 있는 경우
            player_data = same_name_players[0]
            return self._generate_player_info(player_name, player_data)

        # 유사 선수 검색
        similar = self._find_similar_players(player_name)
        if similar:
            return ChatResponse(
                message=f"'{player_name}' 선수를 찾을 수 없습니다.",
                suggestions=similar[:5]
            )

        return ChatResponse(
            message=f"'{player_name}' 선수를 찾을 수 없습니다.",
            suggestions=["정확한 이름을 입력해주세요"]
        )

    def _generate_player_info(self, player_name: str, player_data: Dict) -> ChatResponse:
        """선수 정보 생성"""
        team = player_data.get("team", "소속 미상")
        events = player_data.get("events", [])

        # 성적 분석
        ranks = [e.get("rank") for e in events if e.get("rank")]
        int_ranks = []
        for r in ranks:
            try:
                int_ranks.append(int(r))
            except:
                pass

        best_rank = min(int_ranks) if int_ranks else "-"
        avg_rank = round(sum(int_ranks) / len(int_ranks), 1) if int_ranks else "-"

        message = f"""**{player_name}** ({team})

- 참가 대회: {len(events)}개
- 최고 순위: {best_rank}위
- 평균 순위: {avg_rank}위

**최근 대회 성적:**"""

        recent = events[-5:] if events else []
        for e in reversed(recent):
            message += f"\n- {e.get('event', '')} : {e.get('rank', '-')}위"

        data = {
            "player_name": player_name,
            "team": team,
            "total_events": len(events),
            "best_rank": best_rank,
            "avg_rank": avg_rank,
            "recent_events": recent
        }

        return ChatResponse(
            message=message,
            data=data,
            suggestions=[
                f"{player_name} 라이벌",
                f"{player_name} 참가 대회 목록"
            ]
        )

    def _handle_player_search(self, params: Dict) -> ChatResponse:
        """선수 검색"""
        search_term = params.get("search_term", "")

        results = []
        for name, entries in self.players.items():
            if search_term in name:
                for entry in entries:
                    results.append({
                        "name": name,
                        "team": entry["team"],
                        "event_count": len(entry["events"])
                    })

        if results:
            message = f"'{search_term}' 검색 결과 ({len(results)}명):"
            for r in results[:10]:
                message += f"\n- {r['name']} ({r['team']}) - {r['event_count']}개 대회"

            return ChatResponse(
                message=message,
                data={"results": results[:10]},
                suggestions=[r["name"] for r in results[:5]]
            )

        return ChatResponse(
            message=f"'{search_term}'에 해당하는 선수를 찾을 수 없습니다.",
            suggestions=["다른 검색어를 입력해주세요"]
        )

    def _handle_competition_search(self, params: Dict) -> ChatResponse:
        """대회 검색"""
        search_term = params.get("search_term", "")

        results = []
        for comp in self.data.get("competitions", []):
            comp_info = comp.get("competition", {})
            name = comp_info.get("name", "")

            if search_term in name or any(word in name for word in search_term.split()):
                results.append({
                    "event_cd": comp_info.get("event_cd"),
                    "name": name,
                    "start_date": comp_info.get("start_date"),
                    "status": comp_info.get("status"),
                    "event_count": len(comp.get("events", []))
                })

        if results:
            message = f"대회 검색 결과 ({len(results)}개):"
            for r in results[:10]:
                message += f"\n- {r['name']} ({r['start_date']}) - {r['event_count']}개 종목"

            return ChatResponse(
                message=message,
                data={"results": results[:10]}
            )

        return ChatResponse(
            message="검색 결과가 없습니다.",
            suggestions=["전국체육대회", "선수권대회", "클럽대회"]
        )

    def _handle_stats_query(self, params: Dict) -> ChatResponse:
        """통계 질문 처리"""
        competitions = self.data.get("competitions", [])

        total_comps = len(competitions)
        total_events = sum(len(c.get("events", [])) for c in competitions)
        total_players = len(self.players)

        # 연도별 통계
        year_counts = {}
        for comp in competitions:
            date = comp.get("competition", {}).get("start_date")
            if date:
                year = str(date)[:4]
                year_counts[year] = year_counts.get(year, 0) + 1

        message = f"""**펜싱 데이터 통계**

- 총 대회 수: {total_comps}개
- 총 종목 수: {total_events}개
- 등록 선수 수: {total_players}명

**연도별 대회 수:**"""

        for year in sorted(year_counts.keys(), reverse=True):
            message += f"\n- {year}년: {year_counts[year]}개"

        return ChatResponse(
            message=message,
            data={
                "total_competitions": total_comps,
                "total_events": total_events,
                "total_players": total_players,
                "by_year": year_counts
            }
        )

    def _handle_general_query(self, query: str) -> ChatResponse:
        """일반 질문 처리"""
        return ChatResponse(
            message="죄송합니다. 질문을 이해하지 못했습니다. 다음과 같이 질문해보세요:",
            suggestions=[
                "박소윤의 라이벌은 누구야?",
                "김지연 선수 성적",
                "전국체육대회 대회 목록",
                "통계 보여줘"
            ]
        )

    def _find_similar_players(self, name: str) -> List[str]:
        """유사한 이름의 선수 찾기"""
        similar = []
        for player_name in self.players.keys():
            # 부분 일치
            if name in player_name or player_name in name:
                similar.append(player_name)
            # 첫 글자 일치
            elif name and player_name and name[0] == player_name[0]:
                similar.append(player_name)

        return similar[:10]

    def select_disambiguation(self, player_name: str, team: str) -> ChatResponse:
        """동명이인 선택 처리"""
        if player_name in self.players:
            for entry in self.players[player_name]:
                if entry["team"] == team:
                    return self._generate_player_info(player_name, entry)

        return ChatResponse(
            message="선수를 찾을 수 없습니다."
        )
