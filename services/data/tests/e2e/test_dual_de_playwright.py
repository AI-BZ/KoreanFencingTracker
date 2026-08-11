"""
Playwright-based E2E Test for Dual DE UI Display
=================================================

Uses Playwright MCP to validate the Dual DE UI display.

Target Page: http://localhost:71/competition/COMPM00608?event=COMPS000000000003281
Event: 2025 전국남녀종목별오픈펜싱선수권대회 - 여자 플러레(개)

Test Requirements:
1. First DE section shows only 128강 and 64강 rounds (NO 32강)
2. Second DE section shows 64강, 32강, 16강, 8강, 준결승, 결승
3. The hardcoded summary section (48명, 64명, 112명) should NOT exist
4. Bracket round elements have correct data-round attributes

Author: Claude Code E2E Test Generator
Date: 2025-01-21
"""

# This file is designed to work with Playwright MCP integration
# The actual test execution happens through MCP commands

TEST_CONFIG = {
    "base_url": "http://localhost:71",
    "test_path": "/competition/COMPM00608?event=COMPS000000000003281",
    "event_name": "여자 플러레(개)",
    "competition_name": "2025 전국남·녀종목별오픈펜싱선수권대회 겸 국가대표선수 선발대회"
}


# ============================================================================
# TEST PLAN
# ============================================================================

TEST_PLAN = """
# Dual DE UI Display E2E Test Plan

## Overview
This test plan validates the Dual DE (Direct Elimination) UI display for
fencing competition results with a two-stage DE format.

## Test Environment
- URL: http://localhost:71/competition/COMPM00608?event=COMPS000000000003281
- Browser: Chrome (via Playwright MCP)
- Event: 여자 플러레(개) - 2025 전국남녀종목별오픈펜싱선수권대회

## Prerequisites
1. Local server running on port 71
2. Competition data loaded in database
3. Playwright MCP connected

## Test Cases

### TC-1: First DE Round Verification
**Objective**: Verify First DE section displays only 128강 and 64강 rounds

**Steps**:
1. Navigate to the test URL
2. Click on "Direct Elimination" tab
3. Click on "First DE" tab if not already selected
4. Locate all bracket-round elements with data-round attribute
5. Verify only "128강" and "64강" are present
6. Verify "32강" is NOT present in First DE section

**Expected Results**:
- First DE bracket contains exactly two rounds: 128강, 64강
- No 32강, 16강, 8강, 준결승, or 결승 rounds in First DE

**Playwright Commands**:
```
browser_navigate: url = http://localhost:71/competition/COMPM00608?event=COMPS000000000003281
browser_click: element = "Direct Elimination tab"
browser_click: element = "First DE tab"
browser_snapshot: (capture bracket structure)
browser_evaluate: document.querySelectorAll('[data-round]')
```

---

### TC-2: Second DE Round Verification
**Objective**: Verify Second DE section displays all main tournament rounds

**Steps**:
1. From test page, click on "Second DE" tab
2. Locate all bracket-round elements
3. Verify rounds include: 64강, 32강, 16강, 8강, 준결승, 결승

**Expected Results**:
- Second DE bracket contains: 64강, 32강, 16강, 8강, 준결승, 결승
- For in-progress events: at minimum 64강 and 32강

**Playwright Commands**:
```
browser_click: element = "Second DE tab"
browser_snapshot: (capture bracket structure)
```

---

### TC-3: No Hardcoded Summary Section
**Objective**: Verify the hardcoded summary (48명, 64명, 112명) does not exist

**Steps**:
1. Navigate to DE section
2. Look for summary elements with text content
3. Verify summary values are dynamically computed

**Expected Results**:
- Summary section should show actual participant counts
- No hardcoded "시드 선수 48명", "First DE 참가자 64명", "총 참가자 112명"

**Playwright Commands**:
```
browser_evaluate: document.querySelector('.dual-de-summary')?.textContent
```

---

### TC-4: Data-Round Attribute Validation
**Objective**: Verify all bracket rounds have valid data-round attributes

**Steps**:
1. For each bracket-round element
2. Extract data-round value
3. Validate it's one of: 128강, 64강, 32강, 16강, 8강, 준결승, 결승

**Expected Results**:
- All data-round values are valid Korean round names
- No undefined or invalid values

**Playwright Commands**:
```
browser_evaluate:
  Array.from(document.querySelectorAll('.bracket-round'))
    .map(el => el.dataset.round)
```

---

### TC-5: Tab Switching Behavior
**Objective**: Verify First DE and Second DE tabs switch correctly

**Steps**:
1. Click First DE tab
2. Verify First DE content is visible
3. Click Second DE tab
4. Verify Second DE content is visible
5. Verify only one section is visible at a time

**Expected Results**:
- Tab switching works correctly
- Appropriate content is shown/hidden
- Active tab is highlighted

**Playwright Commands**:
```
browser_click: ref = First DE tab
browser_snapshot: verify First DE visible
browser_click: ref = Second DE tab
browser_snapshot: verify Second DE visible
```

---

## Test Execution Checklist

- [ ] Server is running on localhost:71
- [ ] Navigate to test URL successfully
- [ ] TC-1: First DE shows only 128강 and 64강
- [ ] TC-2: Second DE shows 64강, 32강, etc.
- [ ] TC-3: No hardcoded summary values
- [ ] TC-4: All data-round attributes are valid
- [ ] TC-5: Tab switching works correctly

## Expected Test Results Summary

| Test Case | Expected Status | Criteria |
|-----------|-----------------|----------|
| TC-1 | PASS | First DE has 128강, 64강 only |
| TC-2 | PASS | Second DE has 64강, 32강, ... |
| TC-3 | PASS | No hardcoded 48/64/112 values |
| TC-4 | PASS | All rounds have valid names |
| TC-5 | PASS | Tab switching works |
"""


# ============================================================================
# PLAYWRIGHT MCP TEST COMMANDS
# ============================================================================

PLAYWRIGHT_TEST_COMMANDS = """
# Playwright MCP Commands for Dual DE Testing

## Setup
mcp__playwright__browser_navigate:
  url: http://localhost:71/competition/COMPM00608?event=COMPS000000000003281

## Click DE Tab
mcp__playwright__browser_click:
  element: "Direct Elimination tab"
  ref: (from snapshot)

## Take Snapshot
mcp__playwright__browser_snapshot: {}

## Evaluate JavaScript for Rounds
mcp__playwright__browser_evaluate:
  function: |
    () => {
      const firstDESection = document.querySelector('[aria-label*="First DE"]')?.closest('.bracket-tree');
      const secondDESection = document.querySelector('[aria-label*="Second DE"]')?.closest('.bracket-tree');

      const getDataRounds = (section) => {
        if (!section) return [];
        return Array.from(section.querySelectorAll('[data-round]'))
          .map(el => el.dataset.round);
      };

      return {
        firstDERounds: getDataRounds(firstDESection),
        secondDERounds: getDataRounds(secondDESection),
        allRounds: Array.from(document.querySelectorAll('[data-round]'))
          .map(el => el.dataset.round)
      };
    }

## Check Summary Section
mcp__playwright__browser_evaluate:
  function: |
    () => {
      const summary = document.querySelector('.dual-de-summary');
      if (!summary) return { exists: false };

      const text = summary.textContent;
      return {
        exists: true,
        content: text,
        hasHardcoded48: text.includes('48명') && text.includes('시드'),
        hasHardcoded64: text.includes('64명') && text.toLowerCase().includes('first de'),
        hasHardcoded112: text.includes('112명') && text.includes('총')
      };
    }
"""


def generate_test_script():
    """Generate a bash script for quick testing"""
    script = '''#!/bin/bash
# Quick Dual DE E2E Test Script
# Usage: ./test_dual_de.sh

URL="http://localhost:71/competition/COMPM00608?event=COMPS000000000003281"

echo "====================================="
echo "Dual DE UI Display E2E Test"
echo "====================================="
echo "URL: $URL"
echo ""

# Check if server is running
if ! curl -s --head "$URL" | head -n 1 | grep -q "200 OK"; then
    echo "[FAIL] Server not responding at $URL"
    exit 1
fi
echo "[OK] Server is running"

# Fetch HTML and run tests
HTML=$(curl -s "$URL")

# Test 1: Check for bracket-round elements in First DE
echo ""
echo "[Test 1] First DE rounds..."
FIRST_DE_ROUNDS=$(echo "$HTML" | grep -o 'data-round="[^"]*"' | head -10)
if echo "$FIRST_DE_ROUNDS" | grep -q '128강' && echo "$FIRST_DE_ROUNDS" | grep -q '64강'; then
    echo "  [PASS] First DE has 128강 and 64강"
else
    echo "  [FAIL] First DE missing expected rounds"
fi

# Test 2: Check all rounds present
echo ""
echo "[Test 2] All bracket rounds..."
ALL_ROUNDS=$(echo "$HTML" | grep -o 'data-round="[^"]*"' | sort | uniq)
echo "$ALL_ROUNDS"

# Test 3: Check for hardcoded summary
echo ""
echo "[Test 3] Hardcoded summary check..."
if echo "$HTML" | grep -q 'class="dual-de-summary"'; then
    SUMMARY=$(echo "$HTML" | grep -o -P 'dual-de-summary[^>]*>.*?</div>' | head -1)
    if echo "$SUMMARY" | grep -q '48명.*64명.*112명'; then
        echo "  [FAIL] Hardcoded summary found"
    else
        echo "  [PASS] No hardcoded summary"
    fi
else
    echo "  [PASS] No summary section found"
fi

echo ""
echo "====================================="
echo "Test completed"
echo "====================================="
'''
    return script


if __name__ == "__main__":
    print(TEST_PLAN)
    print("\n\n")
    print(PLAYWRIGHT_TEST_COMMANDS)
