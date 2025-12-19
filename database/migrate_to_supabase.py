"""
JSON 데이터를 Supabase로 마이그레이션하는 스크립트
Usage: python database/migrate_to_supabase.py
"""
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client
from loguru import logger

# Load environment variables
load_dotenv()

# Configure logger
logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")


class SupabaseMigrator:
    """JSON 데이터를 Supabase로 마이그레이션"""

    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")

        if not url or not key:
            raise ValueError("SUPABASE_URL과 SUPABASE_KEY 환경변수를 설정해주세요")

        self.client: Client = create_client(url, key)
        self.competition_id_map: Dict[str, int] = {}  # event_cd -> id
        self.event_id_map: Dict[str, int] = {}  # sub_event_cd -> id
        self.player_id_map: Dict[str, int] = {}  # (name, team) -> id

    def load_json_data(self, filepath: str) -> Dict[str, Any]:
        """JSON 파일 로드"""
        logger.info(f"JSON 파일 로드 중: {filepath}")
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"총 {len(data.get('competitions', []))}개 대회 로드됨")
        return data

    def clear_all_tables(self):
        """모든 테이블 데이터 삭제 (재마이그레이션용)"""
        logger.warning("기존 데이터 삭제 중...")
        # v1 스키마에 존재하는 테이블만 삭제
        tables = [
            "events",       # events 먼저 삭제 (competitions 참조)
            "competitions",
            "players",
            "scrape_logs"
        ]
        for table in tables:
            try:
                self.client.table(table).delete().neq("id", 0).execute()
                logger.info(f"  - {table} 테이블 삭제 완료")
            except Exception as e:
                logger.debug(f"  - {table} 테이블 삭제 실패: {e}")

    def migrate_competitions(self, competitions: List[Dict]) -> int:
        """대회 데이터 마이그레이션 (v1 스키마: comp_idx, comp_name)"""
        logger.info("대회 데이터 마이그레이션 시작...")
        success_count = 0

        for comp_data in competitions:
            comp = comp_data.get("competition", {})
            event_cd = comp.get("event_cd")

            if not event_cd:
                continue

            # v1 스키마 컬럼명 사용
            data = {
                "comp_idx": event_cd,  # event_cd -> comp_idx
                "comp_name": comp.get("name", ""),  # name -> comp_name
                "start_date": comp.get("start_date"),
                "end_date": comp.get("end_date"),
                "venue": comp.get("location", ""),  # location -> venue
                "status": comp.get("status"),
                "raw_data": comp
            }

            try:
                result = self.client.table("competitions").upsert(
                    data, on_conflict="comp_idx"
                ).execute()

                if result.data:
                    self.competition_id_map[event_cd] = result.data[0]["id"]
                    success_count += 1
            except Exception as e:
                logger.error(f"대회 저장 실패 ({event_cd}): {e}")

        logger.info(f"대회 마이그레이션 완료: {success_count}/{len(competitions)}")
        return success_count

    def migrate_events(self, competitions: List[Dict]) -> int:
        """종목 데이터 마이그레이션 (v1 스키마: event_name, category)"""
        logger.info("종목 데이터 마이그레이션 시작...")
        success_count = 0
        total_events = 0

        for comp_data in competitions:
            comp = comp_data.get("competition", {})
            event_cd = comp.get("event_cd")
            competition_id = self.competition_id_map.get(event_cd)

            if not competition_id:
                continue

            events = comp_data.get("events", [])
            total_events += len(events)

            for event in events:
                sub_event_cd = event.get("sub_event_cd")
                if not sub_event_cd:
                    continue

                # v1 스키마 컬럼명 사용, pool_rounds/final_rankings는 raw_data에 포함
                data = {
                    "competition_id": competition_id,
                    "event_cd": event.get("event_cd"),
                    "sub_event_cd": sub_event_cd,
                    "event_name": event.get("name", ""),  # name -> event_name
                    "weapon": event.get("weapon"),
                    "gender": event.get("gender"),
                    "category": event.get("event_type"),  # event_type -> category
                    "age_group": event.get("age_group"),
                    "raw_data": {
                        "total_participants": event.get("total_participants", 0),
                        "pool_rounds": event.get("pool_rounds", []),
                        "final_rankings": event.get("final_rankings", []),
                        "tournament_bracket": event.get("tournament_bracket", [])
                    }
                }

                try:
                    result = self.client.table("events").upsert(
                        data, on_conflict="competition_id,event_cd,sub_event_cd"
                    ).execute()

                    if result.data:
                        self.event_id_map[sub_event_cd] = result.data[0]["id"]
                        success_count += 1
                except Exception as e:
                    logger.error(f"종목 저장 실패 ({sub_event_cd}): {e}")

        logger.info(f"종목 마이그레이션 완료: {success_count}/{total_events}")
        return success_count

    def migrate_pool_results(self, competitions: List[Dict]) -> int:
        """풀 라운드 결과 마이그레이션"""
        logger.info("풀 라운드 결과 마이그레이션 시작...")
        success_count = 0

        for comp_data in competitions:
            events = comp_data.get("events", [])

            for event in events:
                sub_event_cd = event.get("sub_event_cd")
                event_id = self.event_id_map.get(sub_event_cd)

                if not event_id:
                    continue

                pool_rounds = event.get("pool_rounds", [])

                for pool in pool_rounds:
                    data = {
                        "event_id": event_id,
                        "round_number": pool.get("round_number", 1),
                        "pool_number": pool.get("pool_number", 1),
                        "piste": pool.get("piste", ""),
                        "time": pool.get("time", ""),
                        "referee": pool.get("referee", ""),
                        "results": pool.get("results", [])
                    }

                    try:
                        result = self.client.table("pool_results").insert(data).execute()
                        if result.data:
                            success_count += 1
                    except Exception as e:
                        logger.error(f"풀 결과 저장 실패: {e}")

        logger.info(f"풀 라운드 결과 마이그레이션 완료: {success_count}개")
        return success_count

    def migrate_final_rankings(self, competitions: List[Dict]) -> int:
        """최종 순위 마이그레이션"""
        logger.info("최종 순위 마이그레이션 시작...")
        success_count = 0
        batch_data = []

        for comp_data in competitions:
            events = comp_data.get("events", [])

            for event in events:
                sub_event_cd = event.get("sub_event_cd")
                event_id = self.event_id_map.get(sub_event_cd)

                if not event_id:
                    continue

                final_rankings = event.get("final_rankings", [])

                for ranking in final_rankings:
                    rank = ranking.get("rank")
                    name = ranking.get("name")

                    if not rank or not name:
                        continue

                    data = {
                        "event_id": event_id,
                        "rank": int(rank) if isinstance(rank, str) else rank,
                        "name": name,
                        "team": ranking.get("team", "")
                    }
                    batch_data.append(data)

                    # 배치 크기 500개마다 저장
                    if len(batch_data) >= 500:
                        try:
                            result = self.client.table("final_rankings").insert(batch_data).execute()
                            success_count += len(result.data) if result.data else 0
                            batch_data = []
                        except Exception as e:
                            logger.error(f"최종 순위 배치 저장 실패: {e}")
                            batch_data = []

        # 남은 데이터 저장
        if batch_data:
            try:
                result = self.client.table("final_rankings").insert(batch_data).execute()
                success_count += len(result.data) if result.data else 0
            except Exception as e:
                logger.error(f"최종 순위 배치 저장 실패: {e}")

        logger.info(f"최종 순위 마이그레이션 완료: {success_count}개")
        return success_count

    def extract_and_migrate_players(self, competitions: List[Dict]) -> int:
        """선수 정보 추출 및 마이그레이션"""
        logger.info("선수 데이터 추출 및 마이그레이션 시작...")
        players_set = set()

        for comp_data in competitions:
            events = comp_data.get("events", [])

            for event in events:
                # 풀 라운드에서 선수 추출
                for pool in event.get("pool_rounds", []):
                    for result in pool.get("results", []):
                        name = result.get("name")
                        team = result.get("team", "")
                        if name and name != "1" and len(name) > 1:  # 잘못된 데이터 필터링
                            players_set.add((name, team))

                # 최종 순위에서 선수 추출
                for ranking in event.get("final_rankings", []):
                    name = ranking.get("name")
                    team = ranking.get("team", "")
                    if name and len(name) > 1:
                        players_set.add((name, team))

        logger.info(f"총 {len(players_set)}명의 선수 발견")

        success_count = 0
        batch_data = []

        for name, team in players_set:
            # v1 스키마 컬럼명 사용
            data = {
                "player_name": name,  # name -> player_name
                "team_name": team if team else None  # team -> team_name
            }
            batch_data.append(data)

            if len(batch_data) >= 500:
                try:
                    result = self.client.table("players").upsert(
                        batch_data, on_conflict="player_name,team_name"
                    ).execute()
                    success_count += len(result.data) if result.data else 0
                    batch_data = []
                except Exception as e:
                    logger.error(f"선수 배치 저장 실패: {e}")
                    batch_data = []

        # 남은 데이터 저장
        if batch_data:
            try:
                result = self.client.table("players").upsert(
                    batch_data, on_conflict="player_name,team_name"
                ).execute()
                success_count += len(result.data) if result.data else 0
            except Exception as e:
                logger.error(f"선수 배치 저장 실패: {e}")

        logger.info(f"선수 마이그레이션 완료: {success_count}명")
        return success_count

    def create_scrape_log(self, competitions_count: int, events_count: int, status: str = "completed") -> None:
        """스크래핑 로그 생성"""
        try:
            self.client.table("scrape_logs").insert({
                "scrape_type": "migration",
                "status": status,
                "competitions_processed": competitions_count,
                "events_processed": events_count,
                "completed_at": datetime.now().isoformat()
            }).execute()
        except Exception as e:
            logger.error(f"로그 생성 실패: {e}")

    def run_migration(self, json_filepath: str, clear_existing: bool = True):
        """전체 마이그레이션 실행"""
        logger.info("=" * 60)
        logger.info("Supabase 마이그레이션 시작")
        logger.info("=" * 60)

        # JSON 데이터 로드
        data = self.load_json_data(json_filepath)
        competitions = data.get("competitions", [])

        if not competitions:
            logger.error("마이그레이션할 대회 데이터가 없습니다")
            return

        # 기존 데이터 삭제 (선택)
        if clear_existing:
            self.clear_all_tables()

        # 마이그레이션 실행 (v1 스키마에 맞춤)
        # pool_rounds, final_rankings는 events.raw_data에 JSONB로 저장됨
        comp_count = self.migrate_competitions(competitions)
        event_count = self.migrate_events(competitions)
        player_count = self.extract_and_migrate_players(competitions)

        # 로그 생성
        self.create_scrape_log(comp_count, event_count)

        logger.info("=" * 60)
        logger.info("마이그레이션 완료!")
        logger.info(f"  - 대회: {comp_count}개")
        logger.info(f"  - 종목: {event_count}개 (pool_rounds, final_rankings 포함)")
        logger.info(f"  - 선수: {player_count}명")
        logger.info("=" * 60)


def main():
    # 기본 JSON 파일 경로
    project_root = Path(__file__).parent.parent
    json_filepath = project_root / "data" / "fencing_full_data_v2.json"

    # 명령줄 인자로 파일 경로 지정 가능
    if len(sys.argv) > 1:
        json_filepath = Path(sys.argv[1])

    if not json_filepath.exists():
        logger.error(f"JSON 파일을 찾을 수 없습니다: {json_filepath}")
        sys.exit(1)

    # 마이그레이션 실행
    migrator = SupabaseMigrator()
    migrator.run_migration(str(json_filepath), clear_existing=True)


if __name__ == "__main__":
    main()
