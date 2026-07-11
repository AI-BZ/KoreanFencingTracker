# Unit Tests

Unit tests for Korean Fencing Tracker components.

## Test Files

### `test_ranking_calculator.py`
Comprehensive test suite for `ranking/calculator.py` with 86 test cases.

**Coverage**: 74% (238/320 statements)

**Test Categories**:
1. Point Calculation (15 tests)
2. Ranking Aggregation (10 tests)
3. Edge Cases (10 tests)
4. Classification Functions (10 tests)
5. Extraction Functions (10 tests)
6. Age Group Matching (5 tests)
7. Integration Tests (10 tests)

See [TEST_SUMMARY_RANKING.md](TEST_SUMMARY_RANKING.md) for detailed documentation.

## Running Tests

### All unit tests
```bash
pytest tests/unit/
```

### Specific test file
```bash
pytest tests/unit/test_ranking_calculator.py -v
```

### With coverage
```bash
pytest tests/unit/test_ranking_calculator.py --cov=ranking.calculator --cov-report=term-missing
```

### Single test
```bash
pytest tests/unit/test_ranking_calculator.py::TestEdgeCases::test_negative_rank -v
```

## Test Fixtures

Shared test fixtures are located in `tests/fixtures/`:
- `ranking_fixtures.py` - Fixtures for ranking calculator tests

## Test Standards

All unit tests follow these standards:
- ✅ Descriptive test names with docstrings
- ✅ Organized by functionality in test classes
- ✅ Independent and self-contained
- ✅ Cover both success and failure cases
- ✅ Document known bugs explicitly
- ✅ Include edge case testing
