---
target: FencingMind data core pages + design system
total_score: 26
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
timestamp: 2026-07-30T04-12-33Z
slug: services-data-core-pages
---
# Combined Critique — FencingMind Tracker (core pages + shared design system)

Method: dual-agent (A: design review · B: detector + browser evidence). Targets: Home, /ko/rankings, /ko/competitions, player profile, event result (Pool/DE). Desktop 1440 + mobile 390, ko/light (primary) + en/dark.

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Home shows raw "데이터를 불러올 수 없습니다" + blank "Event를 선택하세요" on first paint |
| 2 | Match System / Real World | 3 | Rich fencing vocab, but English leaks into KO ("Event를 선택하세요", "as of Jul 30, 2026", filter words) |
| 3 | User Control & Freedom | 3 | Chips ×, breadcrumbs, Tree/List, zoom; forced onboarding modal dims page |
| 4 | Consistency & Standards | 3 | Cohesive tokens; minor KO/EN mix + duplicate CTAs |
| 5 | Error Prevention | 3 | Dropdown-constrained filters, autocomplete disambiguation |
| 6 | Recognition rather than Recall | 3 | Autocomplete/visible filters; undermined by unexplained A26/SR/HS/NT |
| 7 | Flexibility & Efficiency | 3 | My-Player, route selector, Tree/List, zoom; no keyboard shortcuts / Esc |
| 8 | Aesthetic & Minimalist | 2 | Home cluttered: modal + blur + 2 banners + empty state + error at once |
| 9 | Error Recovery | 2 | Home "cannot load data" is a dead end (no retry) |
| 10 | Help & Documentation | 2 | No legend/tooltips for A26, ratings, points, 선발/NT |
| **Total** | | **26/40** | **Acceptable (borderline Good)** |

## Design Specificity — product-specific core, category-interchangeable shell
Interior surfaces (DE bracket with seeds/scores/route selector, player profile with team-history timeline + dual ranking cards, pool/medal vocab) are unmistakably fencing-authored. The shell (home, rankings header) reads like a generic admin dashboard. Detector corroborates a generic shell: Inter-only (single-font + overused-font on all 5 pages), flat-type-hierarchy on player.

## Priority Issues
- **[P1] Homepage first-load is a confused wall** (Persuade surface). Modal dims the hero search; raw "데이터를 불러올 수 없습니다" error + blank "Event를 선택하세요" + two heavy promo banners all on first paint. Detector adds: home throws a 500 + JS exception loading the FencingLab guest demo (fencinglab.js:183). Fix: non-blocking onboarding, sensible default results (saved league / recent comps), replace/soften the error, fix the 500. → layout + onboard + clarify + optimize
- **[P1] Non-Korean languages leak untranslated Korean.** /en/rankings renders 개인 랭킹, 팀 랭킹, 필터, 필터 변경, 적용하기, 상위 랭킹 선수를 확인하세요, 로그인하여 선발 포인트 보기, 꿈나무·청소년... in KO. en/fr/it/tr default to dark, so this hits the default-dark audience. Fix: populate missing _t keys; audit fallbacks per language. → clarify
- **[P2] Light-theme muted text fails WCAG AA.** --fm-text-muted #8b95a1 on white ≈3.0:1 (dates, "소속 이력", counts, helpers). Dark #6b6b7b on #0a0a0f ≈3.6:1. Fix: light ~#6b7280 (≈4.6:1), dark ~#9a9aad. → colorize/harden
- **[P2] Competitions mobile horizontal overflow** — body scrollWidth 515 vs 390 viewport (verified: nav/menu panel bleeds in from right). Fix: contain the overflowing element. → adapt
- **[P2] Domain codes ship with no legend + English-in-Korean.** A26 rating, "as of Jul 30, 2026", SR/HS/NT, Pool/DE, "8 /57" format unexplained. Fix: tap/hover tooltip + localize date + translate residual English. → clarify
- **[P2] Peak-end deflates into a double paywall.** Profile ends with two identical "로그인하여 전체 보기" buttons over heavy blur. Fix: single CTA + distinct copy, lighter teaser. → distill/clarify
- **[P2] Unlabeled form controls (a11y).** Rankings has 7 filter <select>s + search inputs with placeholder only, no label/aria-label. → harden
- **[P3] Stale footer** "© 2024-2025" (it's 2026); English footer has a data-accuracy disclaimer the Korean one omits. → clarify

## Detector (Assessment B) — exit 2, 38 warnings
side-tab ×21 (home 2, event 19 — event ones are intentional QF-group/seed colors, largely FALSE POSITIVE), overused-font Inter ×5, single-font ×5 (same root fact as overused, double-counted), dark-glow ×4, layout-transition ×2 (animating width/max-height), flat-type-hierarchy ×1 (player). Real runtime: home 500 + fencinglab.js:183 exception; competitions 390px overflow; ubiquitous 401 on guest sessions. FALSE POSITIVE: event "64 no-text controls" (all have textContent).

## What's working
1. DE bracket = category-non-interchangeable craft (seeds, scores, win/loss borders, Tree/List+zoom, 선수 루트, mobile round-tab collapse).
2. Player-profile IA (team-history timeline honoring single-current-team rule; dual ranking cards).
3. Cohesive shared design system (calm light theme; consistent navbar/footer/cards/medal palette).

## Persona red flags
- Alex: no keyboard shortcuts; modal no Esc; 6 clicks to an event. (route selector/zoom/My-Player are real accelerators.)
- Sam: muted text fails 4.5:1; win/loss reinforced by score but color does work; dark blurred guest preview near-unreadable; focus states unverified.
- Casey (mobile parent): great bottom nav + mobile bracket, but modal covers hero and 2 banners push content below the fold.
- Jordan: lands on "Event를 선택하세요" behind a modal, then A26/SR/HS/Pool/DE with no inline help.
