"""Demo gallery - curated real analysis reports."""

import json
import os
import re
from pathlib import Path

REPORTS_DIR = Path(__file__).parent.parent / "data" / "reports"

DEMO_REPORTS = [
    {
        "id": "usaf_hKUXgUsDOKE_continuous_report",
        "title_ko": "주니어 플뢰레 결승 (USA Fencing)",
        "title_en": "Junior Foil Final (USA Fencing)",
        "weapon": "foil",
        "bout_type": "de",
        "score": "15-7",
        "touches": 22,
        "exchanges": 224,
        "duration": "11:49",
        "youtube_id": "hKUXgUsDOKE",
        "description_ko": "22개 터치와 224개 교환을 AI가 분석한 플뢰레 DE 결승전",
        "description_en": "AI analysis of foil DE final with 22 touches and 224 exchanges",
    },
    {
        "id": "usaf_Jiq1kQLftjw_continuous_report",
        "title_ko": "사브르 DE 접전 (15-14)",
        "title_en": "Sabre DE Thriller (15-14)",
        "weapon": "sabre",
        "bout_type": "de",
        "score": "15-14",
        "touches": 29,
        "exchanges": 88,
        "duration": "14:18",
        "youtube_id": "Jiq1kQLftjw",
        "description_ko": "29개 터치와 88개 교환을 AI가 분석한 사브르 DE 접전 (포즈 분석 포함)",
        "description_en": "AI analysis of sabre DE thriller with 29 touches and 88 exchanges (with pose analysis)",
    },
    {
        "id": "gdOdpDyaWrw_report",
        "title_ko": "여자 Y14 플뢰레 (15-13)",
        "title_en": "Women's Y14 Foil (15-13)",
        "weapon": "foil",
        "bout_type": "de",
        "score": "15-13",
        "touches": 28,
        "exchanges": 0,
        "duration": "19:36",
        "youtube_id": "gdOdpDyaWrw",
        "description_ko": "28개 터치가 벌어진 여자 유소년 플뢰레 DE 경기 분석",
        "description_en": "Analysis of women's youth foil DE with 28 touches",
    },
    {
        "id": "VzlH8O7EsCM_report",
        "title_ko": "사브르 역전극 (14-15)",
        "title_en": "Sabre Comeback (14-15)",
        "weapon": "sabre",
        "bout_type": "de",
        "score": "14-15",
        "touches": 27,
        "exchanges": 0,
        "duration": "9:37",
        "youtube_id": "VzlH8O7EsCM",
        "description_ko": "역전으로 끝난 사브르 DE 경기 — 27개 터치 분석",
        "description_en": "Sabre DE comeback match — 27 touches analyzed",
    },
    {
        "id": "usaf_UzQ8Ci7lft8_continuous_report",
        "title_ko": "Div 1 에페 결승 — KNYSH vs WIMMER (13-15)",
        "title_en": "Div 1 Epee Final — KNYSH vs WIMMER (13-15)",
        "weapon": "epee",
        "bout_type": "de",
        "score": "13-15",
        "touches": 22,
        "exchanges": 334,
        "duration": "15:59",
        "youtube_id": "UzQ8Ci7lft8",
        "description_ko": "22개 터치와 334개 교환을 AI가 분석한 에페 DE 결승전 (포즈 분석 포함)",
        "description_en": "AI analysis of epee DE final with 22 touches and 334 exchanges (with pose analysis)",
    },
    {
        "id": "usaf_B6k6SoJFAr8_continuous_report",
        "title_ko": "주니어 사브르 결승 — PRIMUS vs KOVALEV (10-15)",
        "title_en": "Junior Sabre Final — PRIMUS vs KOVALEV (10-15)",
        "weapon": "sabre",
        "bout_type": "de",
        "score": "10-15",
        "touches": 22,
        "exchanges": 63,
        "duration": "9:35",
        "youtube_id": "B6k6SoJFAr8",
        "description_ko": "22개 터치와 63개 교환 — 포즈 기반 풋워크/빠라드 분석 + 선수 프로필 포함",
        "description_en": "22 touches and 63 exchanges — pose-based footwork/parry analysis with fencer profiles",
    },
]


def extract_youtube_id(report_id: str) -> str | None:
    """Extract YouTube video ID from a report ID.

    Patterns:
      usaf_{youtube_id}_continuous_report  → youtube_id
      {youtube_id}_report                  → youtube_id
    """
    # Check DEMO_REPORTS first
    for r in DEMO_REPORTS:
        if r["id"] == report_id and r.get("youtube_id"):
            return r["youtube_id"]
    # Fallback: parse from ID
    m = re.match(r"^(?:usaf_)?(.+?)(?:_continuous)?_report$", report_id)
    if m:
        candidate = m.group(1)
        # YouTube IDs are typically 11 chars, alphanumeric + - + _
        if re.match(r"^[\w-]{8,15}$", candidate):
            return candidate
    return None


def get_demo_reports(lang: str = "ko") -> list[dict]:
    """Return gallery-ready report list with localized titles."""
    result = []
    for r in DEMO_REPORTS:
        report_path = REPORTS_DIR / f"{r['id']}.json"
        if not report_path.exists():
            continue
        result.append({
            "id": r["id"],
            "title": r[f"title_{lang}"] if f"title_{lang}" in r else r["title_ko"],
            "description": r[f"description_{lang}"] if f"description_{lang}" in r else r["description_ko"],
            "weapon": r["weapon"],
            "bout_type": r["bout_type"],
            "score": r["score"],
            "touches": r["touches"],
            "exchanges": r["exchanges"],
            "duration": r["duration"],
            "youtube_id": r.get("youtube_id"),
        })
    return result


def get_demo_report(report_id: str) -> dict | None:
    """Load a specific demo report JSON."""
    report_path = REPORTS_DIR / f"{report_id}.json"
    if not report_path.exists():
        return None
    with open(report_path) as f:
        return json.load(f)
