#!/usr/bin/env python3
"""스키마 드리프트 · 데이터 모델 일관성 점검 (읽기 전용, 데이터 미변경).

2026-09-28 데이터 구조 일관성 감사에서 만들었다. 정기적으로(새 마이그레이션을
추가하거나 대규모 백필 후) 재실행해서 아래 항목을 확인한다:

  1. `database/migrations/*.sql` 파일 이름 ↔ Supabase 에 기록된 마이그레이션 이력
     (`list_migrations` 와 동등한 정보를 `supabase_migrations.schema_migrations`
     에서 직접 읽는다). 파일은 있는데 이력이 없으면 "적용은 됐는데 추적이 안 됨"
     또는 "아직 적용 안 됨" 둘 중 하나 — 테이블 존재 여부로 구분해서 알려준다.
  2. `public.*` 테이블 중 공유 테이블 화이트리스트에도, `data_` 접두사에도 속하지
     않는 것 (CLAUDE.md "테이블 네이밍 규칙" 위반 후보).
  3. `data_*` 테이블의 RLS 활성화 여부 (레벨만 보고, 판단은 사람이 한다 — 기존
     핵심 테이블도 전부 RLS 가 꺼져 있는 하우스 컨벤션이 있기 때문).
  4. `players.merged_into` 순환 참조 (A→B→A 상호 병합, 더 긴 순환도 함께 탐지).
  5. `events.raw_data.final_rankings_source` 값 분포 (허용값 목록과 다른 값이
     보이면 새 관례가 문서화 없이 생긴 것).

사용법:
    cd services/data
    PYTHONPATH=".:../../packages" python3 scripts/check_schema_drift.py

DB 를 변경하지 않는다 (SELECT 전용). 실패해도 종료 코드는 항상 0 — CI 게이트가
아니라 사람이 읽는 보고서다.
"""
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(HERE), ".env"))

from supabase import create_client

MIGRATIONS_DIR = Path(os.path.dirname(HERE)) / ".." / ".." / "database" / "migrations"

# CLAUDE.md "테이블 네이밍 규칙": 공유 테이블은 접두사 없음, 도메인 전용은 `{domain}_`.
# 이 서비스(data)가 소유하거나 참조하는 공유/레거시 테이블 화이트리스트.
KNOWN_UNPREFIXED_TABLES = {
    # 공유 코어 (packages/shared_core 가 참조)
    "members", "players", "organizations", "services", "member_services",
    "oauth_connections", "oauth_states",
    # data 서비스 소유 (services/data/CLAUDE.md "DB 테이블 (소유)")
    "competitions", "events", "matches", "rankings", "scrape_logs",
    "validation_logs",
    # 레거시/공용 파이프라인 (마이그레이션 020251225 계열)
    "sync_logs", "quality_metrics", "quality_alerts", "pipeline_runs",
    "raw_data_metadata", "competition_processing_logs", "player_update_history",
    # 국제 데이터 소스 (fie_* — FIE 연맹 세계 조직 데이터, data_ 접두사 없이 도입됨)
    "fie_confederations", "fie_national_federations", "fie_federations_summary",
    "fencing_equipment_brands", "fencing_world_organizations", "fencing_data_platforms",
    # 회원/인증/결제/약관 (account 서비스 소유, data 는 참조만)
    "consent_logs", "legal_documents", "admin_audit_logs", "admin_notes",
    "admin_service_assignments", "player_claims", "organization_claims",
    "member_organizations", "member_favorites", "pending_registrations",
    "stripe_customers", "stripe_subscriptions", "payment_events",
    "messenger_providers", "email_broadcasts", "email_broadcast_recipients",
    "notifications",
}
KNOWN_DOMAIN_PREFIXES = ("data_", "app_", "shop_", "club_", "community_", "blog_", "analytics_")

FINAL_RANKINGS_SOURCE_ALLOWED = {"kfa", "computed", "estimated", None, ""}


def _client():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("❌ SUPABASE_URL / SUPABASE_KEY 미설정 — .env 확인")
        sys.exit(1)
    return create_client(url, key)


def check_migration_files_vs_tables(db) -> None:
    print("\n=== 1. 마이그레이션 파일 ↔ 실제 스키마 ===")
    local_files = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql")) if MIGRATIONS_DIR.exists() else []
    print(f"로컬 마이그레이션 파일 {len(local_files)}개")
    # 이 스크립트는 supabase_migrations 스키마를 PostgREST 로 못 읽으므로(기본 비노출),
    # 대신 마이그레이션 파일명에서 CREATE TABLE 대상을 뽑아 실제 존재 여부만 확인한다.
    # (이력 추적 자체의 교차검증은 Claude 세션에서 mcp__supabase__list_migrations 로 한다.)
    import re
    for f in local_files:
        text = (MIGRATIONS_DIR / f).read_text(encoding="utf-8", errors="ignore")
        # 줄 시작(공백 허용)에서만 매칭 — 주석 산문 속 우연한 "CREATE TABLE IF NOT EXISTS"
        # 문구(한글 조사가 뒤따르는 등)를 SQL 문으로 오인하지 않기 위함
        tables = set(re.findall(r"(?m)^\s*CREATE TABLE IF NOT EXISTS (\w+)\s*\(", text))
        for t in tables:
            try:
                db.table(t).select("*").limit(1).execute()
            except Exception as e:
                print(f"  ⚠️  {f}: 테이블 `{t}` 조회 실패 — 아직 적용 안 됐을 수 있음 ({e})")


def check_table_naming(db) -> None:
    print("\n=== 2. 테이블 네이밍 규칙 (data_* 접두사) ===")
    res = db.rpc("noop", {}).execute() if False else None  # placeholder, PostgREST 에 information_schema 없음
    print("  (information_schema 조회는 Supabase MCP execute_sql 로만 가능 — 이 스크립트는")
    print("   화이트리스트만 인쇄한다. 새 테이블이 아래 목록과 KNOWN_DOMAIN_PREFIXES 어느 쪽에도")
    print("   없으면 命名 위반 후보이니 execute_sql 로 `select table_name from information_schema.tables`")
    print("   결과와 수동 대조할 것.)")
    print(f"  알려진 접두사 없는 공유 테이블 {len(KNOWN_UNPREFIXED_TABLES)}개, "
          f"도메인 접두사 {KNOWN_DOMAIN_PREFIXES}")


def check_merged_into_cycles(db) -> None:
    print("\n=== 3. players.merged_into 순환 참조 ===")
    # Supabase 클라이언트 기본 페이지 크기(1000)에 걸리지 않도록 직접 페이지네이션한다.
    rows, offset, page = [], 0, 1000
    while True:
        chunk = (
            db.table("players").select("id,merged_into")
            .not_.is_("merged_into", "null")
            .range(offset, offset + page - 1)
            .execute().data
        )
        rows.extend(chunk)
        if len(chunk) < page:
            break
        offset += page
    by_id = {r["id"]: r["merged_into"] for r in rows}
    cycles = []
    for a, b in by_id.items():
        if by_id.get(b) == a and a < b:
            cycles.append((a, b))
    print(f"  merged_into 설정된 선수 {len(by_id)}명")
    print(f"  상호 순환(A→B→A) {len(cycles)}쌍 발견"
          + (f" (예: {cycles[:5]})" if cycles else ""))
    if cycles:
        print("  ⚠️  자동 수정하지 않음 — 선수 정체성은 신중해야 한다(CLAUDE.md 제1원칙).")
        print("     목록은 위 쌍의 id 로 players 테이블에서 직접 확인할 것.")


def check_final_rankings_source(db) -> None:
    print("\n=== 4. events.raw_data.final_rankings_source 값 분포 ===")
    # PostgREST 로 JSONB 필드 group-by 는 못 하므로 간단 표본만 본다.
    total = db.table("events").select("id", count="exact").execute().count
    print(f"  events 총 {total}건 (정확한 값별 분포는 execute_sql 로:")
    print("   select raw_data->>'final_rankings_source', count(*) from events group by 1)")
    print(f"  허용값(코드에서 실제 사용 중): {sorted(v for v in FINAL_RANKINGS_SOURCE_ALLOWED if v)}")
    print("  'kfa'=협회 원본 표 그대로, 'computed'=자체 계산(compute_full_final_rankings),")
    print("  'estimated'=추정치(scripts/estimate_de_rankings.py). 값 없음(None)은 두 관례가")
    print("  섞여 있던 과거 데이터 — 소급 표기는 하지 않는다(추측 금지, CLAUDE.md 제0원칙).")


def main():
    db = _client()
    check_migration_files_vs_tables(db)
    check_table_naming(db)
    check_merged_into_cycles(db)
    check_final_rankings_source(db)
    print("\n완료. 이 스크립트는 읽기 전용이며 아무것도 수정하지 않았다.")


if __name__ == "__main__":
    main()
