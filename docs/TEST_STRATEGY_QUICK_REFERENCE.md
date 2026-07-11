# Test Strategy Quick Reference

**TL;DR**: Current coverage ~35%, need 3,900 test lines over 8 weeks to reach 80% coverage

---

## Priority Matrix

### 🔴 CRITICAL (Week 1-3) - Start Here!
| Module | Current % | Lines | Priority Reason |
|--------|-----------|-------|-----------------|
| Ranking Calculator | 0% | 800 | Wrong rankings = player complaints |
| AI Chat | 0% | 468 | User-facing, many edge cases |
| Club SaaS | 10% | 600 | Revenue feature, data privacy |

**Impact**: These 3 modules handle money, reputation, and UX. Test first.

---

### 🟡 HIGH (Week 4-6) - Core Infrastructure
| Module | Current % | Lines | Priority Reason |
|--------|-----------|-------|-----------------|
| Server API | 40% | 2818 | Main application, many endpoints |
| Full Scraper | 5% | 3061 | Data collection backbone |
| Player Identity | 80% | 600 | Already good, fill gaps |

**Impact**: Without scraper, no data. Without server, no app.

---

### 🟢 MEDIUM (Week 7-8) - Polish
| Module | Current % | Lines | Priority Reason |
|--------|-----------|-------|-----------------|
| Data Pipeline | 30% | 1200 | Quality monitoring needed |
| Auth System | 50% | 800 | Security critical |
| I18n | 0% | 400 | Multilingual support |

**Impact**: Quality of life improvements, security hardening.

---

### 🔵 LOW (Week 9) - Final Touches
| Module | Current % | Lines | Priority Reason |
|--------|-----------|-------|-----------------|
| Database Client | 20% | 354 | Thin wrapper |
| Organization ID | 0% | 300 | Less critical |
| Terminology | 0% | 150 | Simple mapping |

**Impact**: Nice to have, low complexity.

---

## Test Count Estimates

### By Module (Detailed)

#### Critical Priority (198 tests)
- **Ranking Calculator**: 50 tests (point calc, ranking aggregation, edge cases)
- **AI Chat**: 40 tests (query parsing, response generation, disambiguation)
- **Club SaaS**: 60 tests (auth, checkin, player integration, lessons)
- **Server API**: 65 tests (endpoints, Supabase, transformations, errors)

#### High Priority (65 tests)
- **Full Scraper**: 50 tests (scraping logic, validation, error recovery)
- **Player Identity**: 10 tests (performance, edge cases)
- **Data Pipeline**: 45 tests (validators, monitoring, sync)

#### Medium Priority (70 tests)
- **Auth System**: 35 tests (OAuth, verification, privacy)
- **I18n**: 25 tests (translation, middleware, integration)
- **Database**: 15 tests (connection, queries, migrations)

#### Low Priority (30 tests)
- **Organization**: 20 tests (resolution, search)
- **Terminology**: 10 tests (mapping, normalization)

**TOTAL**: ~428 test cases = ~3,900 test lines (9 lines/test avg)

---

## Coverage Goals by Week

| Week | Focus | Tests Written | Cumulative Coverage |
|------|-------|---------------|---------------------|
| 1 | Ranking Calculator | 50 | 45% |
| 2 | AI Chat | 40 | 50% |
| 3 | Club SaaS | 60 | 60% ⭐ |
| 4 | Server API | 65 | 68% |
| 5-6 | Full Scraper | 50 | 73% |
| 7 | Data Pipeline | 45 | 75% ⭐ |
| 8 | Auth + I18n | 60 | 79% |
| 9 | Low Priority + Integration | 58 | 83% ⭐ |

⭐ Milestone checkpoints

---

## Test File Organization

```
tests/
├── test_ranking_calculator.py      # 250 lines (Week 1)
├── test_ai_chat.py                 # 320 lines (Week 2)
├── test_club_management.py         # 600 lines (Week 3)
├── test_server_api.py              # 520 lines (Week 4)
├── test_scraper.py                 # 600 lines (Week 5-6)
├── test_data_pipeline_full.py      # 450 lines (Week 7)
├── test_auth_complete.py           # 350 lines (Week 8)
├── test_i18n.py                    # 200 lines (Week 8)
├── test_database.py                # 120 lines (Week 9)
├── test_organization.py            # 160 lines (Week 9)
├── test_terminology.py             # 50 lines (Week 9)
└── test_integration_full.py        # 200 lines (Week 9)
```

**Existing tests to keep/expand**:
- `test_player_identity.py` (already good, add 10 cases)
- `test_bracket_utils.py` (already good, keep as is)
- `test_data_pipeline.py` (basic, expand to 450 lines)
- `test_server.py` (basic, expand to 520 lines)

---

## Quick Start Commands

### Run all tests
```bash
pytest tests/ -v
```

### Run with coverage
```bash
pytest --cov=app --cov=scraper --cov=ranking --cov-report=html
```

### Run specific module
```bash
pytest tests/test_ranking_calculator.py -v
```

### Coverage for specific module
```bash
pytest --cov=ranking.calculator tests/test_ranking_calculator.py --cov-report=term
```

### Watch mode (auto-run on file change)
```bash
pip install pytest-watch
ptw tests/test_ranking_calculator.py
```

---

## Test Template

```python
"""
Module: ranking.calculator
Priority: 🔴 Critical
Coverage Target: 95%
"""
import pytest
from ranking.calculator import RankingCalculator, get_base_points_by_participants

class TestBasePointsCalculation:
    """기본 포인트 계산 테스트"""

    def test_128_plus_participants(self):
        """128명 이상 대회 = 1200점"""
        assert get_base_points_by_participants(128) == 1200
        assert get_base_points_by_participants(150) == 1200

    def test_64_to_127_participants(self):
        """64-127명 대회 = 1000점"""
        assert get_base_points_by_participants(64) == 1000
        assert get_base_points_by_participants(100) == 1000

    # ... more tests
```

---

## Testing Best Practices

### 1. AAA Pattern (Arrange-Act-Assert)
```python
def test_player_ranking_calculation(self):
    # Arrange
    calculator = RankingCalculator()
    player_data = {"name": "박소윤", "competitions": [...]}

    # Act
    ranking = calculator.calculate_ranking(player_data)

    # Assert
    assert ranking.total_points > 0
    assert ranking.rank <= 100
```

### 2. Use Fixtures for Common Data
```python
@pytest.fixture
def sample_competition():
    return {
        "name": "2024 회장배",
        "participant_count": 64,
        "level": "전문"
    }

def test_with_fixture(sample_competition):
    # Use sample_competition directly
    assert sample_competition["participant_count"] == 64
```

### 3. Mock External Dependencies
```python
from unittest.mock import patch, MagicMock

def test_scraper_with_mock():
    with patch('scraper.full_scraper.Playwright') as mock_playwright:
        mock_playwright.return_value = MagicMock()
        # Test scraper without real browser
```

### 4. Parametrize for Multiple Cases
```python
@pytest.mark.parametrize("count,expected", [
    (128, 1200),
    (64, 1000),
    (32, 800),
    (16, 500),
])
def test_base_points(count, expected):
    assert get_base_points_by_participants(count) == expected
```

---

## Coverage Enforcement (CI/CD)

### GitHub Actions Workflow
```yaml
name: Test Coverage

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.11

      - name: Install dependencies
        run: pip install -r requirements.txt pytest pytest-cov

      - name: Run tests with coverage
        run: pytest --cov=app --cov=scraper --cov=ranking --cov-report=xml --cov-report=term

      - name: Enforce 80% coverage
        run: pytest --cov=app --cov-fail-under=80

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v2
```

### Pre-commit Hook
```bash
# .git/hooks/pre-commit
#!/bin/bash
pytest --cov=app --cov-fail-under=80
if [ $? -ne 0 ]; then
    echo "❌ Coverage below 80%. Commit rejected."
    exit 1
fi
```

---

## Weekly Checklist

### Week 1: Ranking Calculator
- [ ] Write 50 test cases for point calculation
- [ ] Test all edge cases (0 participants, single player, etc.)
- [ ] Achieve 95% coverage on `ranking/calculator.py`
- [ ] Document known calculation formulas

### Week 2: AI Chat
- [ ] Write 40 test cases for query parsing
- [ ] Test disambiguation logic (동명이인)
- [ ] Mock player data for chat responses
- [ ] Achieve 85% coverage on `app/ai_chat.py`

### Week 3: Club SaaS
- [ ] Write 60 test cases for club management
- [ ] Test IP-based auto-checkin
- [ ] Test player-member linking
- [ ] Achieve 80% coverage on `app/club/`

### Week 4: Server API
- [ ] Write 65 test cases for endpoints
- [ ] Test Supabase integration with mocks
- [ ] Test error handling (404, 500)
- [ ] Achieve 75% coverage on `app/server.py`

### Week 5-6: Scraper
- [ ] Write 50 test cases for scraper
- [ ] Mock Playwright browser
- [ ] Test data validation
- [ ] Achieve 70% coverage on `scraper/full_scraper.py`

### Week 7: Data Pipeline
- [ ] Write 45 test cases for validators
- [ ] Test monitoring and alerts
- [ ] Test data synchronization
- [ ] Achieve 75% coverage on `data_pipeline/`

### Week 8: Auth + I18n
- [ ] Write 35 test cases for auth
- [ ] Write 25 test cases for i18n
- [ ] Test OAuth flows
- [ ] Achieve 80% coverage on `app/auth/` and `app/i18n/`

### Week 9: Final Push
- [ ] Write remaining low-priority tests
- [ ] Write integration tests
- [ ] Set up CI/CD pipeline
- [ ] Achieve 83%+ overall coverage

---

## Success Metrics

### Coverage Targets
- ✅ **Overall**: 80% line coverage
- ✅ **Critical modules**: 95% (ranking, club, auth)
- ✅ **Core modules**: 80% (server, scraper)
- ✅ **Utilities**: 70% (i18n, terminology)

### Quality Gates
- ✅ All tests pass on CI/CD
- ✅ No high-severity bugs in production for 3 months
- ✅ Test execution time < 5 minutes
- ✅ Coverage report generated on every PR

### Maintenance
- ✅ New code must include tests
- ✅ Coverage cannot decrease in PRs
- ✅ Tests reviewed in code review
- ✅ Flaky tests fixed within 24 hours

---

**Next Steps**: Start with Week 1 (Ranking Calculator) - see detailed breakdown in `TEST_COVERAGE_ANALYSIS.md`
