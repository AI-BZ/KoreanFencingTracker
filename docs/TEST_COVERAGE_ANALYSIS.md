# Test Coverage Analysis & Strategic Test Plan

**Project**: Korean Fencing Tracker
**Analysis Date**: 2026-01-09
**Total Production Code**: ~21,242 lines
**Total Test Files**: 16 test files
**Estimated Current Coverage**: ~35-40%

---

## Executive Summary

### Current State
- **Good Coverage Areas**: Player Identity (동명이인), Bracket Utils, Data Pipeline normalization
- **Medium Coverage**: Server endpoints, Auth system, Player Analytics
- **Low/No Coverage**: AI Chat, Club Management SaaS, Ranking Calculator, Scrapers, I18n, Database layer

### Key Findings
1. **Critical Business Logic Gaps**: Ranking calculator (0%), AI Chat (0%), Club roster management (0%)
2. **Data Pipeline**: Basic normalizer tests exist, but validators/monitoring untested
3. **Integration Tests**: Some E2E tests exist but lack systematic API contract testing
4. **Scraper Reliability**: No systematic scraper tests (critical for data collection)

### Recommendation
Focus on **HIGH-PRIORITY** modules first to reach 60% coverage, then expand to 80% with medium-priority areas.

---

## Module-by-Module Analysis

### 🔴 CRITICAL PRIORITY (Business Logic - Must Test)

#### 1. Ranking Calculator (`ranking/calculator.py`) - **0% Coverage**
**Lines**: ~800+ lines
**Complexity**: HIGH - Complex point calculation algorithms
**Business Impact**: CRITICAL - Determines player standings and competition value

**Why Critical**:
- Financial impact: Wrong rankings = wrong tournament seeding = player complaints
- Algorithm complexity: Multiple factors (participant count, age group, competition level)
- Data integrity: Rankings drive tournament brackets and player profiles

**Test Requirements** (Est. 50+ test cases):
```python
# Point Calculation Tests (15 cases)
- test_base_points_by_participant_count (128+, 64, 32, 16, 8, <8)
- test_competition_authority_multiplier (전문 vs 동호인)
- test_rank_position_multiplier (1st=100%, 2nd=85%, etc.)
- test_age_group_weight_factor (초등 vs 일반부)
- test_combined_points_calculation (all factors together)

# Ranking Aggregation Tests (10 cases)
- test_best_n_results_selection (e.g., top 5 of 10 competitions)
- test_season_filtering (2024 results only)
- test_age_group_filtering (MS events for MS ranking)
- test_weapon_filtering (플러레 events for 플러레 ranking)

# Edge Cases (10 cases)
- test_zero_participants_competition
- test_single_participant_competition
- test_incomplete_competition_data
- test_missing_age_group_fallback
- test_duplicate_competition_handling

# Integration Tests (10 cases)
- test_player_ranking_across_season
- test_multi_weapon_player_separate_rankings
- test_age_group_transition (중등부 → 고등부)
- test_team_change_ranking_continuity

# Regression Tests (5 cases)
- test_known_player_ranking_snapshot (박소윤 2024 ranking)
- test_competition_level_classification (회장배, 종별선수권 등)
```

**Estimated Tests**: 50 cases × 5 lines/test = **250 test lines**

---

#### 2. AI Chat Service (`app/ai_chat.py`) - **0% Coverage**
**Lines**: 468 lines
**Complexity**: MEDIUM-HIGH - NLP pattern matching
**Business Impact**: HIGH - User experience differentiator

**Why Critical**:
- User-facing: Poor responses = poor UX
- Natural language: Many edge cases in query parsing
- Data accuracy: Must correctly identify players/teams

**Test Requirements** (Est. 40+ test cases):
```python
# Query Parsing Tests (15 cases)
- test_player_search_query ("박소윤 전적")
- test_rivalry_query ("박소윤 vs 김철수")
- test_team_query ("최병철펜싱클럽 선수들")
- test_competition_query ("2024 회장배 결과")
- test_ambiguous_query ("김민수") # 동명이인

# Response Generation (10 cases)
- test_player_profile_response
- test_head_to_head_response
- test_team_roster_response
- test_disambiguation_response (multiple players with same name)
- test_no_results_response

# Edge Cases (10 cases)
- test_typo_handling ("박소욱" → "박소윤")
- test_empty_query
- test_special_characters
- test_very_long_query
- test_multiple_questions_in_one

# Integration (5 cases)
- test_chat_with_real_player_data
- test_chat_with_empty_database
```

**Estimated Tests**: 40 cases × 8 lines/test = **320 test lines**

---

#### 3. Club Management SaaS (`app/club/`) - **~10% Coverage**
**Lines**: ~600+ lines across router, models, dependencies, players service
**Complexity**: MEDIUM - Business workflow
**Business Impact**: HIGH - Revenue-generating SaaS feature

**Why Critical**:
- Revenue: Paid feature for clubs
- Data privacy: Handles student/parent data
- Attendance tracking: IP-based auto-checkin logic

**Test Requirements** (Est. 60+ test cases):
```python
# Authentication & Authorization (10 cases)
- test_coach_access_dashboard
- test_student_access_checkin_only
- test_parent_view_child_only
- test_unauthorized_access_denied
- test_organization_isolation (club A can't see club B)

# Check-in Logic (15 cases)
- test_ip_based_auto_checkin
- test_manual_checkin_outside_ip
- test_duplicate_checkin_prevention
- test_late_checkin_warning
- test_coach_manual_checkin_override
- test_checkin_time_validation

# Player Data Integration (15 cases)
- test_link_member_to_player_profile
- test_player_competition_history
- test_player_performance_stats
- test_head_to_head_records
- test_team_roster_generation

# Lesson Management (10 cases)
- test_create_lesson
- test_add_participant_to_lesson
- test_mark_attendance
- test_lesson_capacity_limit

# Edge Cases (10 cases)
- test_member_without_player_link
- test_inactive_member_checkin
- test_concurrent_checkin_same_student
- test_timezone_handling
```

**Estimated Tests**: 60 cases × 10 lines/test = **600 test lines**

---

### 🟡 HIGH PRIORITY (Core Features - Should Test)

#### 4. Server API Endpoints (`app/server.py`) - **~40% Coverage**
**Lines**: 2,818 lines (largest module)
**Complexity**: MEDIUM - Many endpoints
**Current Coverage**: Basic DE bracket transformation tests exist

**Missing Coverage**:
```python
# Supabase Integration (20 cases)
- test_load_competitions_from_supabase
- test_load_events_from_supabase
- test_load_players_from_supabase
- test_supabase_connection_error_handling
- test_supabase_query_timeout

# API Endpoints (25 cases)
- test_get_competition_list_with_filters
- test_get_competition_by_id
- test_get_event_details
- test_search_players_endpoint
- test_get_player_profile_endpoint
- test_ranking_endpoint_by_age_group
- test_ranking_endpoint_by_weapon

# Data Transformation (10 cases)
- test_transform_pool_results
- test_transform_final_rankings
- test_merge_competition_data

# Error Handling (10 cases)
- test_404_competition_not_found
- test_500_database_error
- test_malformed_query_params
```

**Estimated Tests**: 65 cases × 8 lines/test = **520 test lines**

---

#### 5. Full Scraper (`scraper/full_scraper.py`) - **~5% Coverage**
**Lines**: 3,061 lines (2nd largest)
**Complexity**: HIGH - Browser automation, dynamic content
**Business Impact**: CRITICAL - Data collection backbone

**Why High Priority**:
- Data source: All competition data comes from here
- Fragility: Website changes break scraper
- Complex logic: Pool + DE + Rankings collection

**Test Requirements** (Est. 50+ test cases):
```python
# Scraping Logic (20 cases)
- test_scrape_competition_list
- test_scrape_event_details
- test_scrape_pool_results
- test_scrape_de_bracket
- test_scrape_final_rankings
- test_scrape_participant_count

# Data Validation (15 cases)
- test_validate_scraped_pool_data
- test_validate_scraped_de_data
- test_validate_player_names (no empty strings)
- test_validate_scores (0-15 range)
- test_detect_incomplete_data

# Error Recovery (10 cases)
- test_retry_on_timeout
- test_skip_broken_event
- test_resume_from_checkpoint
- test_handle_missing_elements

# Integration (5 cases)
- test_scrape_to_supabase_upload
- test_scrape_with_data_pipeline_validation
```

**Estimated Tests**: 50 cases × 12 lines/test = **600 test lines**

---

#### 6. Player Identity Resolution (`app/player_identity.py`) - **~80% Coverage** ✅
**Lines**: ~600 lines
**Complexity**: HIGH
**Current Coverage**: GOOD - Comprehensive unit tests exist

**Remaining Gaps** (10 cases):
```python
# Performance Tests (5 cases)
- test_resolve_10000_players_performance
- test_search_with_large_dataset
- test_memory_usage_on_large_data

# Edge Cases (5 cases)
- test_player_with_100_team_changes
- test_player_name_with_unicode
- test_concurrent_identity_resolution
```

**Estimated Additional Tests**: 10 cases × 8 lines/test = **80 test lines**

---

### 🟢 MEDIUM PRIORITY (Important but Less Critical)

#### 7. Data Pipeline (`data_pipeline/`) - **~30% Coverage**
**Files**: normalizer.py (tested), validators.py (untested), monitoring.py (untested), sync.py (untested)
**Lines**: ~1,200 lines total

**Missing Coverage**:
```python
# Validators (20 cases)
- test_validate_event_technical (name, weapon, gender required)
- test_validate_event_business (age group progression)
- test_validate_player_data
- test_validate_match_data

# Monitoring (10 cases)
- test_quality_score_calculation
- test_alert_on_low_quality
- test_track_validation_stats

# Sync (15 cases)
- test_sync_player_to_members
- test_sync_on_identity_resolution
- test_sync_on_team_change
```

**Estimated Tests**: 45 cases × 10 lines/test = **450 test lines**

---

#### 8. Authentication System (`app/auth/`) - **~50% Coverage**
**Files**: router.py, models.py, verification.py, privacy.py
**Lines**: ~800 lines total

**Missing Coverage**:
```python
# OAuth Integration (15 cases)
- test_kakao_oauth_flow
- test_google_oauth_flow
- test_oauth_token_refresh
- test_oauth_error_handling

# Verification (10 cases)
- test_identity_verification_auto_approve (>0.85 confidence)
- test_identity_verification_auto_reject (<0.60 confidence)
- test_identity_verification_manual_review (0.60-0.85)
- test_link_player_to_member

# Privacy (10 cases)
- test_privacy_settings_update
- test_minor_consent_requirement
- test_data_export
```

**Estimated Tests**: 35 cases × 10 lines/test = **350 test lines**

---

#### 9. I18n System (`app/i18n/`) - **0% Coverage**
**Files**: manager.py, middleware.py
**Lines**: ~400 lines

**Test Requirements** (Est. 25 test cases):
```python
# Translation (10 cases)
- test_translate_korean_to_english
- test_translate_english_to_korean
- test_missing_translation_fallback
- test_pluralization
- test_template_variable_substitution

# Middleware (10 cases)
- test_detect_language_from_header
- test_detect_language_from_cookie
- test_detect_language_from_query_param
- test_fallback_to_default_language

# Integration (5 cases)
- test_multilingual_competition_page
- test_multilingual_player_profile
```

**Estimated Tests**: 25 cases × 8 lines/test = **200 test lines**

---

### 🔵 LOW PRIORITY (Nice to Have)

#### 10. Database Client (`database/supabase_client.py`) - **~20% Coverage**
**Lines**: 354 lines
**Complexity**: LOW - Thin wrapper

**Test Requirements** (Est. 15 test cases):
```python
# Connection (5 cases)
- test_connect_to_supabase
- test_connection_error_handling
- test_connection_retry

# Query (5 cases)
- test_execute_select_query
- test_execute_insert_query
- test_query_timeout

# Migration (5 cases)
- test_apply_migration
- test_rollback_migration
```

**Estimated Tests**: 15 cases × 8 lines/test = **120 test lines**

---

#### 11. Organization Identity (`app/organization_identity.py`) - **0% Coverage**
**Lines**: ~300 lines
**Complexity**: MEDIUM

**Test Requirements** (Est. 20 test cases):
```python
# Organization Resolution (10 cases)
- test_resolve_club_identity
- test_resolve_school_identity
- test_handle_organization_name_variants
- test_detect_organization_merge

# Search (10 cases)
- test_search_organization_by_name
- test_search_organization_by_address
```

**Estimated Tests**: 20 cases × 8 lines/test = **160 test lines**

---

#### 12. Terminology Module (`app/terminology.py`) - **0% Coverage**
**Lines**: ~150 lines
**Complexity**: LOW

**Test Requirements** (Est. 10 test cases):
```python
# Terminology Mapping (10 cases)
- test_map_korean_to_english
- test_map_english_to_korean
- test_normalize_weapon_names
- test_normalize_age_groups
```

**Estimated Tests**: 10 cases × 5 lines/test = **50 test lines**

---

## Coverage Goals & Timeline

### Phase 1: Critical Business Logic (Target: 60% Coverage)
**Duration**: 2-3 weeks
**Focus**: Modules 1-3 (Ranking, AI Chat, Club Management)

| Module | Test Lines | Priority | Est. Time |
|--------|-----------|----------|-----------|
| Ranking Calculator | 250 | 🔴 Critical | 3 days |
| AI Chat | 320 | 🔴 Critical | 4 days |
| Club Management | 600 | 🔴 Critical | 5 days |

**Total**: 1,170 test lines = ~12 working days

---

### Phase 2: Core Features (Target: 75% Coverage)
**Duration**: 2-3 weeks
**Focus**: Modules 4-6 (Server, Scraper, Player Identity)

| Module | Test Lines | Priority | Est. Time |
|--------|-----------|----------|-----------|
| Server API | 520 | 🟡 High | 5 days |
| Full Scraper | 600 | 🟡 High | 6 days |
| Player Identity (補) | 80 | 🟡 High | 1 day |

**Total**: 1,200 test lines = ~12 working days

---

### Phase 3: Polish & Integration (Target: 80% Coverage)
**Duration**: 2 weeks
**Focus**: Modules 7-9 (Data Pipeline, Auth, I18n)

| Module | Test Lines | Priority | Est. Time |
|--------|-----------|----------|-----------|
| Data Pipeline | 450 | 🟢 Medium | 4 days |
| Auth System | 350 | 🟢 Medium | 3 days |
| I18n | 200 | 🟢 Medium | 2 days |

**Total**: 1,000 test lines = ~9 working days

---

### Phase 4: Completion (Target: 85%+ Coverage)
**Duration**: 1 week
**Focus**: Modules 10-12 + Integration Tests

| Module | Test Lines | Priority | Est. Time |
|--------|-----------|----------|-----------|
| Database Client | 120 | 🔵 Low | 1 day |
| Organization | 160 | 🔵 Low | 1.5 days |
| Terminology | 50 | 🔵 Low | 0.5 day |
| Integration Tests | 200 | 🟢 Medium | 2 days |

**Total**: 530 test lines = ~5 working days

---

## Summary Statistics

### Overall Effort Estimation

| Phase | Test Lines | Working Days | Coverage Goal |
|-------|-----------|--------------|---------------|
| Phase 1 (Critical) | 1,170 | 12 | 60% |
| Phase 2 (Core) | 1,200 | 12 | 75% |
| Phase 3 (Polish) | 1,000 | 9 | 80% |
| Phase 4 (Complete) | 530 | 5 | 85% |
| **TOTAL** | **3,900** | **38 days** | **85%** |

### Coverage Breakdown by Module Type

| Type | Modules | Current % | Target % | Priority |
|------|---------|-----------|----------|----------|
| Business Logic | 3 | 5% | 85% | 🔴 Critical |
| API/Server | 2 | 35% | 80% | 🟡 High |
| Data Processing | 3 | 45% | 75% | 🟡 High |
| Infrastructure | 4 | 20% | 70% | 🟢 Medium |
| Utilities | 3 | 10% | 65% | 🔵 Low |

---

## Implementation Strategy

### 1. Test Infrastructure Setup
```bash
# Install coverage tools
pip install pytest-cov pytest-asyncio pytest-mock

# Create pytest.ini configuration
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

### 2. CI/CD Integration
```yaml
# .github/workflows/test.yml
- name: Run tests with coverage
  run: pytest --cov=app --cov=scraper --cov=ranking --cov-report=html --cov-report=term

- name: Enforce minimum coverage
  run: pytest --cov=app --cov-fail-under=80
```

### 3. Testing Standards
- **Unit Tests**: Test individual functions/classes in isolation
- **Integration Tests**: Test module interactions (e.g., scraper → database)
- **E2E Tests**: Test user workflows (already partially exist)
- **Fixtures**: Use pytest fixtures for common test data
- **Mocking**: Mock Supabase, external APIs, browser automation

### 4. Quality Gates
- Minimum 80% line coverage
- All critical paths (payment, ranking, auth) must have 95%+ coverage
- No new code merged without tests
- Coverage must not decrease in PRs

---

## Risk Assessment

### High-Risk Areas (Require Extra Testing)
1. **Ranking Calculator**: Wrong calculations = player complaints = reputation damage
2. **Club SaaS**: Payment/billing logic must be bulletproof
3. **Player Identity**: 동명이인 mis-merge = data corruption
4. **Scraper**: Breaks frequently due to website changes

### Medium-Risk Areas
1. **Auth System**: Security vulnerabilities possible
2. **Data Pipeline**: Silent data quality degradation
3. **AI Chat**: Poor UX if responses are wrong

### Low-Risk Areas
1. **I18n**: Translation errors are non-critical
2. **Terminology**: Mapping errors are cosmetic
3. **Database Client**: Thin wrapper, low complexity

---

## Conclusion

**Current Estimated Coverage**: 35-40%
**Target Coverage**: 80%
**Gap**: ~40% = 3,900 test lines
**Estimated Effort**: 38 working days (7.5 weeks)

### Recommended Approach
1. **Week 1-3**: Focus 100% on Phase 1 (Ranking, AI Chat, Club) - Critical business logic
2. **Week 4-6**: Phase 2 (Server, Scraper) - Core infrastructure
3. **Week 7-8**: Phase 3 (Data Pipeline, Auth, I18n) - Polish
4. **Week 9**: Phase 4 (Final modules, integration tests, CI/CD setup)

### Success Metrics
- ✅ 80% line coverage achieved
- ✅ All critical business logic at 95%+ coverage
- ✅ CI/CD pipeline enforces coverage thresholds
- ✅ Zero high-severity bugs in production for 3 months post-testing

---

**Document Version**: 1.0
**Last Updated**: 2026-01-09
**Next Review**: After Phase 1 completion
