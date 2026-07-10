# Database Migrations

마이그레이션 파일들은 데이터베이스 스키마 변경을 관리합니다.

## Migration File Naming

- 파일명: `NNN_description.sql` (NNN = 3자리 번호)
- 규칙: 새 파일 추가만 허용 (기존 파일 수정 금지 - Rule R3)

## ⚠️ Migration 002 Duplicate Issue (확정)

**파일명**: `002_add_organizations_table.sql`, `002_ready_to_run.sql`

**상태**: 
- 두 파일 모두 동일한 내용 (organizations 테이블 생성)
- 파일명만 다름 (내용은 완전히 동일)
- 두 파일이 모두 Git 추적됨

**DB 적용 이력 (Supabase MCP 확인)**: 
- ✅ **실제 적용됨**: `002_add_organizations_table.sql` (version: 20251218035928, timestamp: 2025-12-18 03:59:28)
  - DB에 organizations 테이블 생성 완료
  - 현재 스키마의 유효한 마이그레이션
  
- ❌ **적용 이력 없음**: `002_ready_to_run.sql`
  - Supabase 마이그레이션 추적 시스템에 개별 적용 기록 없음
  - 초기 번들/스테이징 파일로 추정 (현재 개별 적용되지 않음)

**해소 방법**:
- R3 규칙상 파일명 변경 불가 (기존 파일 수정 금지)
- 문서화로 혼동 해소
- 실제 운영 마이그레이션: `002_add_organizations_table.sql`만 사용
- `002_ready_to_run.sql`은 레거시 파일로 향후 정리 대상
