"""
익산 국제대회 JSON 데이터를 Supabase로 마이그레이션
핵심: events.raw_data 업데이트 (서버가 사용하는 필드)
"""
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from loguru import logger

load_dotenv()

# 환경변수
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://tjfjuasvjzjawyckengv.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# 데이터 파일 경로 (백업 위치로 수정)
DATA_DIR = Path(__file__).parent.parent / "data"
IKSAN_FILE = DATA_DIR / "backup_json_2025-12-22" / "iksan_international_2025.json"


def migrate_iksan_data():
    """익산 대회 데이터를 Supabase로 마이그레이션"""
    if not SUPABASE_KEY:
        logger.error("SUPABASE_KEY 환경변수를 설정해주세요")
        return False

    # Supabase 연결
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Supabase 연결됨")

    # JSON 데이터 로드
    if not IKSAN_FILE.exists():
        logger.error(f"익산 데이터 파일이 없습니다: {IKSAN_FILE}")
        return False

    with open(IKSAN_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    logger.info(f"익산 데이터 로드됨 (스크래핑: {data.get('scraped_at')})")

    stats = {
        "competitions": 0,
        "events": 0,
        "players": 0,
        "matches": 0,
        "rankings": 0
    }

    for comp in data.get("competitions", []):
        event_cd = comp.get("event_cd")
        comp_name = comp.get("competition_name")

        # 1. 대회 저장
        comp_data = {
            "comp_idx": event_cd,
            "comp_name": comp_name,
            "start_date": "2025-12-16" if "U17" in comp.get("competition_key", "") else "2025-12-20",
            "end_date": "2025-12-21",
            "venue": "익산",
            "status": "completed"
        }

        try:
            result = supabase.table("competitions").upsert(
                comp_data, on_conflict="comp_idx"
            ).execute()

            if result.data:
                comp_id = result.data[0]["id"]
                stats["competitions"] += 1
                logger.info(f"대회 저장: {comp_name} (ID: {comp_id})")
            else:
                logger.error(f"대회 저장 실패: {event_cd}")
                continue

        except Exception as e:
            logger.error(f"대회 저장 오류: {e}")
            continue

        # 2. 종목 저장
        event_id_map = {}  # sub_event_cd -> event_id

        for event in comp.get("events", []):
            event_data = {
                "competition_id": comp_id,
                "event_cd": event_cd,
                "sub_event_cd": event.get("sub_event_cd") or event.get("name"),
                "event_name": event.get("name"),
                "weapon": event.get("weapon"),
                "gender": event.get("gender"),
                "age_group": event.get("mapped_age_group") or event.get("age_category")
            }

            try:
                result = supabase.table("events").upsert(
                    event_data, on_conflict="competition_id,event_cd,sub_event_cd"
                ).execute()

                if result.data:
                    event_id = result.data[0]["id"]
                    event_id_map[event.get("name")] = event_id
                    stats["events"] += 1
            except Exception as e:
                logger.warning(f"종목 저장 오류: {e}")

        logger.info(f"  종목 {len(event_id_map)}개 저장됨")

        # 3. 결과 데이터 처리
        for result_data in comp.get("results", []):
            event_name = result_data.get("event_name")
            event_id = event_id_map.get(event_name)

            if not event_id:
                # 이름으로 매칭 시도
                for key, eid in event_id_map.items():
                    if event_name in key or key in event_name:
                        event_id = eid
                        break

            if not event_id:
                logger.warning(f"종목 ID를 찾을 수 없음: {event_name}")
                continue

            # 3-1. Pool 라운드에서 경기 추출
            for pool in result_data.get("pool_rounds", []):
                pool_number = pool.get("pool_number")
                pool_results = pool.get("results", [])

                # Pool 결과에서 bout 추출 (있는 경우)
                for bout in pool.get("bouts", []):
                    player1_name = bout.get("player1_name", "")
                    player2_name = bout.get("player2_name", "")
                    player1_team = bout.get("player1_team", "")
                    player2_team = bout.get("player2_team", "")
                    score1 = bout.get("player1_score", 0)
                    score2 = bout.get("player2_score", 0)

                    # 선수 upsert
                    p1_id = upsert_player(supabase, player1_name, player1_team)
                    p2_id = upsert_player(supabase, player2_name, player2_team)

                    if p1_id:
                        stats["players"] += 1
                    if p2_id:
                        stats["players"] += 1

                    # 경기 저장
                    match_data = {
                        "event_id": event_id,
                        "round_name": "pool",
                        "group_name": f"Pool {pool_number}",
                        "player1_id": p1_id,
                        "player1_name": player1_name,
                        "player1_score": score1,
                        "player2_id": p2_id,
                        "player2_name": player2_name,
                        "player2_score": score2,
                        "winner_id": p1_id if score1 > score2 else p2_id,
                        "match_status": "completed"
                    }

                    try:
                        supabase.table("matches").insert(match_data).execute()
                        stats["matches"] += 1
                    except Exception as e:
                        pass  # 중복 등 무시

            # 3-2. DE 경기 저장
            for match in result_data.get("de_matches", []):
                round_name = match.get("round_name", "DE")
                winner_name = match.get("winner_name", "")
                loser_name = match.get("loser_name", "")
                winner_team = match.get("winner_team", "")
                loser_team = match.get("loser_team", "")
                score = match.get("score", {})

                winner_score = score.get("winner_score", 0)
                loser_score = score.get("loser_score", 0)

                # 선수 upsert
                w_id = upsert_player(supabase, winner_name, winner_team)
                l_id = upsert_player(supabase, loser_name, loser_team)

                match_data = {
                    "event_id": event_id,
                    "round_name": round_name,
                    "match_number": match.get("match_number"),
                    "player1_id": w_id,
                    "player1_name": winner_name,
                    "player1_score": winner_score,
                    "player2_id": l_id,
                    "player2_name": loser_name,
                    "player2_score": loser_score,
                    "winner_id": w_id,
                    "match_status": "completed"
                }

                try:
                    supabase.table("matches").insert(match_data).execute()
                    stats["matches"] += 1
                except Exception as e:
                    pass

            # 3-3. 최종 순위 저장
            for rank in result_data.get("final_rankings", []):
                rank_pos = rank.get("rank") or rank.get("position", 0)
                player_name = rank.get("name", "")
                team_name = rank.get("team", "")

                player_id = upsert_player(supabase, player_name, team_name)

                ranking_data = {
                    "event_id": event_id,
                    "player_id": player_id,
                    "player_name": player_name,
                    "team_name": team_name,
                    "rank_position": rank_pos
                }

                try:
                    supabase.table("rankings").upsert(
                        ranking_data, on_conflict="event_id,player_id"
                    ).execute()
                    stats["rankings"] += 1
                except Exception as e:
                    pass

        logger.info(f"  경기 {stats['matches']}개, 순위 {stats['rankings']}개 저장됨")

    logger.info(f"\n=== 마이그레이션 완료 ===")
    logger.info(f"대회: {stats['competitions']}개")
    logger.info(f"종목: {stats['events']}개")
    logger.info(f"경기: {stats['matches']}개")
    logger.info(f"순위: {stats['rankings']}개")

    return True


def upsert_player(supabase: Client, name: str, team: str) -> int:
    """선수 upsert 및 ID 반환"""
    if not name or name.strip() == "":
        return None

    try:
        result = supabase.table("players").upsert(
            {"player_name": name.strip(), "team_name": team.strip() if team else None},
            on_conflict="player_name,team_name"
        ).execute()

        if result.data:
            return result.data[0]["id"]
    except Exception as e:
        logger.debug(f"선수 upsert 오류: {e}")

    return None


def update_raw_data_only():
    """
    핵심 함수: 기존 events의 raw_data만 업데이트
    (대회/종목은 이미 Supabase에 존재함)
    """
    if not SUPABASE_KEY:
        logger.error("SUPABASE_KEY 환경변수를 설정해주세요")
        return False

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("Supabase 연결됨")

    # JSON 데이터 로드
    if not IKSAN_FILE.exists():
        logger.error(f"익산 데이터 파일이 없습니다: {IKSAN_FILE}")
        return False

    with open(IKSAN_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    logger.info(f"익산 데이터 로드됨 (스크래핑: {data.get('scraped_at')})")

    # Supabase에서 익산 이벤트 ID 매핑 가져오기
    result = supabase.table("events").select(
        "id, event_cd, event_name"
    ).in_("event_cd", ["COMPM00666", "COMPM00673"]).execute()

    # event_name -> event_id 매핑
    event_mapping = {}
    for event in result.data:
        key = (event["event_cd"], event["event_name"])
        event_mapping[key] = event["id"]

    logger.info(f"Supabase 이벤트 매핑: {len(event_mapping)}개")

    updated = 0
    not_found = []

    for comp in data["competitions"]:
        event_cd = comp["event_cd"]
        logger.info(f"\n=== {comp['competition_name']} ({event_cd}) ===")

        for result_data in comp.get("results", []):
            event_name = result_data["event_name"]
            key = (event_cd, event_name)

            if key not in event_mapping:
                not_found.append(key)
                logger.warning(f"  ❌ 매핑 없음: {event_name}")
                continue

            event_id = event_mapping[key]

            # raw_data 구성 (전체 결과 데이터)
            raw_data = {
                "pool_rounds": result_data.get("pool_rounds", []),
                "pool_total_ranking": result_data.get("pool_total_ranking", []),
                "de_bracket": result_data.get("de_bracket", {}),
                "final_rankings": result_data.get("final_rankings", []),
                "status": result_data.get("status", "complete"),
                "age_category": result_data.get("age_category", ""),
                "mapped_age_group": result_data.get("mapped_age_group", "")
            }

            # Supabase 업데이트
            try:
                supabase.table("events").update({
                    "raw_data": raw_data
                }).eq("id", event_id).execute()

                pool_count = len(raw_data["pool_rounds"])
                ranking_count = len(raw_data["final_rankings"])
                logger.info(f"  ✅ {event_name}: pool={pool_count}, rankings={ranking_count}")
                updated += 1
            except Exception as e:
                logger.error(f"  ❌ 업데이트 실패 ({event_name}): {e}")

    logger.info(f"\n=== 마이그레이션 완료 ===")
    logger.info(f"업데이트: {updated}개")
    logger.info(f"매핑 없음: {len(not_found)}개")

    if not_found:
        logger.warning(f"미매핑 이벤트: {not_found}")

    return updated > 0


if __name__ == "__main__":
    import sys
    logger.add("logs/migration_{time}.log", rotation="10 MB")

    # raw_data 업데이트만 실행 (권장)
    if "--full" in sys.argv:
        # 전체 마이그레이션 (대회/종목/경기 모두)
        migrate_iksan_data()
    else:
        # raw_data만 업데이트 (기본)
        update_raw_data_only()
