"""
Supabase 마이그레이션 실행 스크립트
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from loguru import logger

load_dotenv()

logger.remove()
logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")


def run_migration():
    """마이그레이션 SQL 실행"""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        logger.error("SUPABASE_URL과 SUPABASE_KEY를 설정해주세요")
        return False

    client: Client = create_client(url, key)

    # 마이그레이션 파일 읽기
    migration_file = Path(__file__).parent / "migrations" / "002_add_organizations_table.sql"

    if not migration_file.exists():
        logger.error(f"마이그레이션 파일을 찾을 수 없습니다: {migration_file}")
        return False

    with open(migration_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    logger.info("Organizations 테이블 마이그레이션 시작...")

    # SQL을 개별 명령으로 분리하여 실행
    # Supabase Python 클라이언트는 직접 SQL 실행을 지원하지 않으므로
    # RPC 함수를 통해 실행하거나 REST API를 사용해야 함

    # 테이블 존재 확인
    try:
        result = client.table("organizations").select("id").limit(1).execute()
        logger.info("✅ organizations 테이블이 이미 존재합니다")
        return True
    except Exception as e:
        if "does not exist" in str(e) or "relation" in str(e).lower():
            logger.info("organizations 테이블이 없습니다. 생성이 필요합니다.")
        else:
            logger.warning(f"테이블 확인 중 오류: {e}")

    # Supabase Dashboard에서 실행해야 하는 SQL 출력
    logger.info("=" * 60)
    logger.info("Supabase Dashboard에서 아래 SQL을 실행해주세요:")
    logger.info("=" * 60)
    logger.info("1. https://supabase.com/dashboard 접속")
    logger.info("2. 프로젝트 선택 → SQL Editor")
    logger.info("3. 아래 SQL 복사하여 실행")
    logger.info("=" * 60)
    print("\n" + sql_content + "\n")
    logger.info("=" * 60)

    # SQL 파일로도 저장
    output_file = Path(__file__).parent / "migrations" / "002_ready_to_run.sql"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(sql_content)
    logger.info(f"SQL 파일 저장: {output_file}")

    return True


if __name__ == "__main__":
    run_migration()
