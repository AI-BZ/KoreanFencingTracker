#!/bin/bash
# FencingMind Data Validation Hook
# Claude Code Stop 이벤트에서 실행: 데이터 관련 파일 수정 시 검증 리마인더 표시

# staged 파일만 체크 (커밋 직전 상태)
CHANGED=$(git diff --name-only --cached 2>/dev/null)
DATA_PATTERNS="scraper/|data_validator|server\.py|bracket_utils|data_pipeline|pipeline_scraper"
DATA_FILES=$(echo "$CHANGED" | grep -E "$DATA_PATTERNS")

if [ -n "$DATA_FILES" ]; then
  cat >&2 <<'EOF'
⚠️ 데이터 관련 파일이 수정되었습니다. 완료 전 필수 검증:
  1. cd services/data && PYTHONPATH="." python scripts/run_validation.py
  2. ERROR 0건 확인
  3. 새 오류 패턴 발견 시 → docs/DATA_ERROR_CATALOG.md에 CASE 추가
EOF
  exit 2
fi

exit 0
