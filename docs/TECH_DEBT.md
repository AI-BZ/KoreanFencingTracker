# Technical Debt & Deprecation Warnings

**작성일**: 2026-01-09
**출처**: pytest 경고 분석 (548 tests, 23 warnings)

---

## 📋 개요

테스트 실행 시 발견된 deprecation warning들을 우선순위별로 정리하고 해결 계획을 수립합니다.

**현재 상태**: ✅ 모든 테스트 통과 (548/548)
**경고 수**: 23개 (테스트 실패 아님, 향후 개선 필요)

---

## 🔴 HIGH PRIORITY (Breaking Change 예정)

### 1. FastAPI `on_event` Deprecation (5개 경고)

**위치**: `app/server.py`
- Line 913: `@app.on_event("startup")`
- Line 924: `@app.on_event("shutdown")`

**문제**:
```python
# ❌ Deprecated (현재 코드)
@app.on_event("startup")
async def startup_event():
    await init_supabase_client()

@app.on_event("shutdown")
async def shutdown_event():
    await close_supabase_client()
```

**해결 방법**:
```python
# ✅ Modern approach (FastAPI 0.109+)
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_supabase_client()
    yield
    # Shutdown
    await close_supabase_client()

app = FastAPI(lifespan=lifespan)
```

**우선순위**: 🔴 HIGH
**예상 작업 시간**: 30분
**영향도**: FastAPI 향후 버전에서 제거될 예정
**참고 문서**: https://fastapi.tiangolo.com/advanced/events/

**실행 계획**:
1. `app/server.py`에서 lifespan context manager 구현
2. `@app.on_event()` 데코레이터 제거
3. 테스트 실행하여 동작 확인
4. 경고 사라지는지 확인

---

### 2. Pydantic V2 Migration (7개 경고)

**위치**: 여러 파일 (주로 `app/club/models.py`, `app/auth/models.py`)

**문제**:
```python
# ❌ Deprecated (Pydantic V1 스타일)
class ClubMember(BaseModel):
    name: str
    role: str

    class Config:
        orm_mode = True
        allow_population_by_field_name = True
```

**해결 방법**:
```python
# ✅ Pydantic V2 스타일
from pydantic import ConfigDict

class ClubMember(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,  # orm_mode 대체
        populate_by_name=True   # allow_population_by_field_name 대체
    )

    name: str
    role: str
```

**우선순위**: 🔴 HIGH
**예상 작업 시간**: 2시간
**영향도**: Pydantic V3에서 제거될 예정
**참고 문서**: https://docs.pydantic.dev/latest/migration/

**주요 변경 사항**:
| V1 (Old) | V2 (New) |
|----------|----------|
| `class Config:` | `model_config = ConfigDict()` |
| `orm_mode = True` | `from_attributes=True` |
| `allow_population_by_field_name` | `populate_by_name=True` |
| `.dict()` | `.model_dump()` |
| `.json()` | `.model_dump_json()` |

**실행 계획**:
1. `app/club/models.py` 전체 마이그레이션 (14개 모델)
2. `app/auth/models.py` 전체 마이그레이션 (8개 모델)
3. `scraper/models.py` 전체 마이그레이션 (5개 모델)
4. `.dict()` → `.model_dump()` 전체 교체
5. `.json()` → `.model_dump_json()` 전체 교체
6. 테스트 실행하여 동작 확인

---

## 🟡 MEDIUM PRIORITY (권장 사항)

### 3. FastAPI Query `regex` Deprecation (1개 경고)

**위치**: `app/club/players/router.py:459`

**문제**:
```python
# ❌ Deprecated
status: str = Query(..., regex="^(active|inactive)$", description="새 상태")
```

**해결 방법**:
```python
# ✅ Modern approach
from pydantic import Field

status: str = Query(..., pattern="^(active|inactive)$", description="새 상태")

# 또는 Pydantic V2 스타일 (더 권장)
from typing import Literal

status: Literal["active", "inactive"] = Query(..., description="새 상태")
```

**우선순위**: 🟡 MEDIUM
**예상 작업 시간**: 10분
**영향도**: 향후 버전에서 제거 가능성
**참고 문서**: FastAPI Query parameter docs

**실행 계획**:
1. `app/club/players/router.py:459` 수정
2. 프로젝트 전체에서 `regex=` 검색하여 모두 교체
3. 가능하면 `Literal` 타입으로 변경 (더 안전)

---

## 🟢 LOW PRIORITY (정보성)

### 4. pytest-asyncio 모드 경고

**위치**: `pytest.ini`

**현재 설정**:
```ini
[tool:pytest]
asyncio_mode = strict
```

**문제**: 향후 버전에서 기본값이 변경될 수 있음
**해결 방법**: 명시적으로 설정하고 있으므로 현재 문제 없음
**우선순위**: 🟢 LOW
**작업 필요**: 없음 (모니터링만)

---

## 📊 우선순위별 요약

| 우선순위 | 항목 | 예상 시간 | 영향도 | 완료 여부 |
|----------|------|-----------|--------|-----------|
| 🔴 HIGH | FastAPI lifespan 마이그레이션 | 30분 | Breaking Change 예정 | ⬜ |
| 🔴 HIGH | Pydantic V2 마이그레이션 | 2시간 | Breaking Change 예정 | ⬜ |
| 🟡 MEDIUM | Query regex → pattern | 10분 | 권장 사항 | ⬜ |
| 🟢 LOW | pytest-asyncio 모니터링 | - | 정보성 | ⬜ |

**총 예상 작업 시간**: 2시간 40분

---

## 🚀 실행 전략

### Phase 1: Quick Wins (10분)
```bash
# 1. Query regex 교체
git checkout -b fix/deprecation-warnings
# app/club/players/router.py:459 수정
git commit -m "Fix: Replace Query regex with pattern parameter"
```

### Phase 2: FastAPI Lifespan (30분)
```bash
# 2. app/server.py 리팩토링
# - @asynccontextmanager 구현
# - on_event 제거
git commit -m "Refactor: Migrate to FastAPI lifespan events"
```

### Phase 3: Pydantic V2 Migration (2시간)
```bash
# 3. 모든 Pydantic 모델 마이그레이션
# - app/club/models.py
# - app/auth/models.py
# - scraper/models.py
git commit -m "Refactor: Migrate all models to Pydantic V2"

# 4. .dict() → .model_dump() 전체 교체
git commit -m "Refactor: Replace .dict() with .model_dump()"
```

### Phase 4: 검증 (10분)
```bash
# 5. 모든 테스트 실행
python -m pytest tests/unit/ -v

# 6. 경고 확인 (0개가 되어야 함)
python -m pytest tests/unit/ -v 2>&1 | grep -i warning

# 7. PR 생성
git push origin fix/deprecation-warnings
gh pr create --title "Fix deprecation warnings" --body "..."
```

---

## 📝 체크리스트

### FastAPI Lifespan Migration
- [ ] `app/server.py`에 `@asynccontextmanager` 추가
- [ ] `lifespan` 함수 구현 (startup/shutdown 로직 통합)
- [ ] `FastAPI(lifespan=lifespan)` 설정
- [ ] `@app.on_event("startup")` 제거
- [ ] `@app.on_event("shutdown")` 제거
- [ ] 테스트 실행 (`pytest tests/unit/test_server_endpoints.py`)
- [ ] 서버 시작/종료 동작 확인

### Pydantic V2 Migration
- [ ] `app/club/models.py` 마이그레이션
  - [ ] `class Config` → `model_config = ConfigDict()`
  - [ ] `orm_mode=True` → `from_attributes=True`
  - [ ] `allow_population_by_field_name` → `populate_by_name=True`
- [ ] `app/auth/models.py` 마이그레이션
- [ ] `scraper/models.py` 마이그레이션
- [ ] 전체 프로젝트에서 `.dict()` → `.model_dump()` 교체
- [ ] 전체 프로젝트에서 `.json()` → `.model_dump_json()` 교체
- [ ] 테스트 실행 (`pytest tests/unit/`)
- [ ] API 응답 형식 확인 (JSON 직렬화 테스트)

### Query Regex Migration
- [ ] `app/club/players/router.py:459` 수정
- [ ] 프로젝트 전체 `regex=` 검색 및 교체
- [ ] 가능한 경우 `Literal` 타입으로 변경
- [ ] 테스트 실행

### Final Validation
- [ ] 모든 테스트 통과 확인 (548/548)
- [ ] 경고 0개 확인
- [ ] 서버 정상 실행 확인
- [ ] API 엔드포인트 동작 확인
- [ ] 문서 업데이트 (CHANGELOG.md)

---

## 🔍 자동 감지 스크립트

향후 deprecation warning을 자동으로 감지하려면:

```bash
# .github/workflows/deprecation-check.yml
name: Deprecation Warning Check

on: [push, pull_request]

jobs:
  check-warnings:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests and check warnings
        run: |
          pytest tests/unit/ -v 2>&1 | tee test-output.log
          WARNING_COUNT=$(grep -c "DeprecationWarning" test-output.log || true)
          echo "Found $WARNING_COUNT deprecation warnings"
          if [ $WARNING_COUNT -gt 0 ]; then
            echo "⚠️ Please fix deprecation warnings"
            exit 1
          fi
```

---

## 📚 참고 자료

### FastAPI
- [Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)
- [FastAPI 0.109 Release Notes](https://github.com/tiangolo/fastapi/releases/tag/0.109.0)

### Pydantic
- [Pydantic V2 Migration Guide](https://docs.pydantic.dev/latest/migration/)
- [Pydantic V2 Config](https://docs.pydantic.dev/latest/api/config/)
- [Migration Tool](https://docs.pydantic.dev/latest/migration/#migration-tool)

### Tools
```bash
# Pydantic V2 자동 마이그레이션 도구
pip install bump-pydantic
bump-pydantic app/ scraper/
```

---

## 🎯 성공 기준

- ✅ `pytest tests/unit/ -v` 실행 시 0 warnings
- ✅ 모든 548 테스트 통과
- ✅ 서버 정상 실행 (`python -m uvicorn app.server:app`)
- ✅ API 엔드포인트 정상 동작
- ✅ CI/CD 파이프라인 통과

---

**작성자**: Claude Code
**다음 리뷰 예정**: 2026-02-09 (1개월 후)
**관련 이슈**: 향후 GitHub Issue 생성 예정
