"""
동명이인 종합 감사 스크립트 (Homonym Comprehensive Audit)

전체 ~11,786명의 선수를 4가지 카테고리로 분류:
  CLEAN       - 동명이인 위험 없음 (고유한 이름 또는 단일 팀/무기 이력)
  CONFIRMED   - KNOWN_HOMONYMS에 등록되어 분리 처리됨
  SUSPECTED   - 수동 검토 필요 (C1~C4 탐지 기준)
  INVESTIGATION - 데이터 이상 (3종 이상 무기, 성별 혼재 등)

탐지 기준 (C1~C4):
  C1: 같은 학교 레벨(중/고)이지만 다른 도/광역시 (Regional distance)
  C2: 3년 이상 활동 공백 후 다른 조직에서 재등장 (Time gap)
  C3: 2개 이상 다른 중/고등학교 (비동시, School level repeat)
  C4: 단일 프로필에 2종 무기 (Dual weapon, 정상일 수 있지만 검토 필요)

NOTE: team-event-agent의 Task 1/2 완료 후 실행하면 ~202개의 단체전 팀명
      오인 선수가 필터링되어 더 정확한 결과를 얻을 수 있습니다.

사용법:
  cd /Users/gyejinpark/Documents/GitHub/FencingMind-data/services/data
  PYTHONPATH="." python scripts/audit_homonyms.py
"""

import os
import sys
import json
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Set, Tuple, Optional

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

from app.player_identity import (
    PlayerIdentityResolver,
    get_team_type,
    extract_gender,
    get_age_group_level,
)


# ============================================================
# Province normalization (from server.py)
# ============================================================

_PROVINCE_SHORT = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구",
    "인천광역시": "인천", "광주광역시": "광주", "대전광역시": "대전",
    "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "강원도": "강원", "강원특별자치도": "강원",
    "충청북도": "충북", "충청남도": "충남",
    "전라북도": "전북", "전북특별자치도": "전북",
    "전라남도": "전남", "경상북도": "경북", "경상남도": "경남",
    "제주특별자치도": "제주",
}
_METRO_CITIES = {"서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종"}


def _normalize_province(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    if raw in _PROVINCE_SHORT:
        return _PROVINCE_SHORT[raw]
    if raw in _METRO_CITIES or raw in (
        "경기", "충북", "충남", "전북", "전남", "경북", "경남", "강원", "제주"
    ):
        return raw
    return raw


def _extract_city_from_address(road_address: str, province_short: str) -> str:
    if not road_address or province_short in _METRO_CITIES:
        return ""
    tokens = road_address.strip().split()
    if len(tokens) < 2:
        return ""
    city_token = tokens[1]
    for suffix in ("시", "군"):
        if city_token.endswith(suffix) and len(city_token) > 1:
            return city_token[:-1]
    return city_token


# ============================================================
# Data Loading
# ============================================================

def load_supabase_data():
    """Load all competition/event data and org region cache from Supabase."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_KEY not set in environment")
        sys.exit(1)

    sb = create_client(url, key)

    # --- Load events ---
    print("이벤트 로드 중...")
    t0 = time.time()
    all_events = []
    offset = 0
    while True:
        resp = sb.table("events").select(
            "id, event_name, sub_event_cd, event_cd, raw_data, competition_id"
        ).range(offset, offset + 199).execute()
        if not resp.data:
            break
        all_events.extend(resp.data)
        offset += 200
        if len(resp.data) < 200:
            break

    # --- Load competitions ---
    comps_resp = sb.table("competitions").select(
        "id, comp_name, comp_idx, start_date"
    ).execute()
    comp_map = {c["id"]: c for c in comps_resp.data}
    print(f"  이벤트 {len(all_events)}개, 대회 {len(comp_map)}개 ({time.time()-t0:.1f}s)")

    # --- Build competitions structure ---
    competitions_by_comp = defaultdict(list)
    for ev in all_events:
        cid = ev.get("competition_id")
        competitions_by_comp[cid].append(ev)

    competitions = []
    for cid, events in competitions_by_comp.items():
        comp_info = comp_map.get(cid, {})
        comp_obj = {
            "competition": {
                "name": comp_info.get("comp_name", ""),
                "event_cd": comp_info.get("comp_idx", ""),
                "start_date": comp_info.get("start_date", ""),
            },
            "events": [],
        }
        for ev in events:
            raw = ev.get("raw_data") or {}
            comp_obj["events"].append({
                "sub_event_cd": ev.get("sub_event_cd", ""),
                "event_name": ev.get("event_name", ""),
                "name": ev.get("event_name", ""),
                "de_bracket": raw.get("de_bracket", {}),
                "pool_rounds": raw.get("pool_rounds", []),
                "pool_total_ranking": raw.get("pool_total_ranking", []),
                "final_rankings": raw.get("final_rankings", []),
            })
        competitions.append(comp_obj)

    # --- Load org region cache ---
    print("조직 지역 캐시 로드 중...")
    org_resp = sb.table("organizations").select(
        "name, province, road_address, org_type"
    ).execute()

    org_region_cache: Dict[str, Dict[str, str]] = {}
    for org in (org_resp.data or []):
        name = org.get("name", "")
        if not name:
            continue
        province_raw = org.get("province", "") or ""
        province = _normalize_province(province_raw)
        city = _extract_city_from_address(
            org.get("road_address", "") or "", province
        )
        org_type = org.get("org_type", "") or ""
        entry = {}
        if province:
            entry["province"] = province
            entry["city"] = city
        if org_type:
            entry["org_type"] = org_type
        if entry:
            org_region_cache[name] = entry
    print(f"  조직 {len(org_region_cache)}개 캐시됨")

    return competitions, org_region_cache


# ============================================================
# Player Record Collection (per name)
# ============================================================

def collect_player_records(competitions: list) -> Dict[str, List[Dict]]:
    """Collect all records per player name from competitions data."""
    player_records: Dict[str, List[Dict]] = defaultdict(list)

    for comp in competitions:
        comp_info = comp.get("competition", {})
        comp_name = comp_info.get("name", "")
        comp_date = comp_info.get("start_date", "")
        comp_cd = comp_info.get("event_cd", "")

        for event in comp.get("events", []):
            event_cd = event.get("sub_event_cd", "")
            event_name = event.get("event_name", "") or event.get("name", "")

            seen_in_event: Set[str] = set()

            # pool_total_ranking
            for ranking in event.get("pool_total_ranking", []):
                name = (ranking.get("name") or "").strip()
                team = (ranking.get("team") or "").strip()
                if name:
                    player_records[name].append({
                        "event_cd": event_cd,
                        "event_name": event_name,
                        "comp_name": comp_name,
                        "comp_date": comp_date,
                        "comp_cd": comp_cd,
                        "team": team,
                        "rank": ranking.get("rank"),
                    })
                    seen_in_event.add(f"{name}_{event_cd}")

            # final_rankings (avoid duplicates from pool)
            for ranking in (event.get("final_rankings") or []):
                name = (ranking.get("name") or "").strip()
                team = (ranking.get("team") or "").strip()
                key = f"{name}_{event_cd}"
                if name and key not in seen_in_event:
                    player_records[name].append({
                        "event_cd": event_cd,
                        "event_name": event_name,
                        "comp_name": comp_name,
                        "comp_date": comp_date,
                        "comp_cd": comp_cd,
                        "team": team,
                        "rank": ranking.get("rank"),
                    })

    return player_records


# ============================================================
# Detection Criteria (C1~C4)
# ============================================================

def detect_c1_regional_distance(
    records: List[Dict],
    org_region_cache: Dict[str, Dict[str, str]],
) -> Optional[Dict]:
    """C1: Same school level (중/고) in different provinces.

    If a player has records at two different schools of the same level
    (e.g., both 중학교) but in different provinces, that's suspicious.
    """
    # Collect unique teams with their types and provinces
    team_info: Dict[str, Dict] = {}
    for r in records:
        team = r.get("team", "")
        if not team or team in team_info:
            continue
        team_type = get_team_type(team)
        province = org_region_cache.get(team, {}).get("province", "")
        team_info[team] = {"type": team_type, "province": province}

    # Check pairs of same school level in different provinces
    school_types = ("middle", "high")
    teams_by_type: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for team, info in team_info.items():
        if info["type"] in school_types and info["province"]:
            teams_by_type[info["type"]].append((team, info["province"]))

    for school_type, team_list in teams_by_type.items():
        if len(team_list) < 2:
            continue
        for i, (t1, p1) in enumerate(team_list):
            for t2, p2 in team_list[i + 1:]:
                if p1 != p2:
                    return {
                        "code": "C1",
                        "description": "같은 학교 레벨, 다른 도/광역시",
                        "team1": t1,
                        "team1_province": p1,
                        "team2": t2,
                        "team2_province": p2,
                        "school_type": school_type,
                    }
    return None


def detect_c2_time_gap(records: List[Dict]) -> Optional[Dict]:
    """C2: 3+ years activity gap then reappears at different organization."""
    if len(records) < 2:
        return None

    # Sort by date
    dated = sorted(
        [r for r in records if r.get("comp_date")],
        key=lambda x: x["comp_date"],
    )
    if len(dated) < 2:
        return None

    for i in range(len(dated) - 1):
        d1 = dated[i]["comp_date"][:10]
        d2 = dated[i + 1]["comp_date"][:10]
        t1 = dated[i].get("team", "")
        t2 = dated[i + 1].get("team", "")

        try:
            dt1 = datetime.strptime(d1, "%Y-%m-%d")
            dt2 = datetime.strptime(d2, "%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        gap_years = (dt2 - dt1).days / 365.25
        if gap_years >= 3.0 and t1 and t2 and t1 != t2:
            return {
                "code": "C2",
                "description": f"{gap_years:.1f}년 활동 공백 후 다른 조직에서 재등장",
                "last_active": d1,
                "reappeared": d2,
                "team_before": t1,
                "team_after": t2,
                "gap_years": round(gap_years, 1),
            }
    return None


def detect_c3_school_level_repeat(records: List[Dict]) -> Optional[Dict]:
    """C3: 2+ different middle/high schools (non-simultaneous).

    A player going to two different middle schools (at different times)
    is suspicious — students normally attend one middle school.
    """
    # Group teams by type, track time ranges
    team_type_groups: Dict[str, List[Dict]] = defaultdict(list)
    for r in records:
        team = r.get("team", "")
        if not team:
            continue
        ttype = get_team_type(team)
        if ttype in ("middle", "high"):
            team_type_groups[ttype].append({
                "team": team,
                "date": r.get("comp_date", ""),
            })

    for school_type, entries in team_type_groups.items():
        unique_teams = set(e["team"] for e in entries)
        if len(unique_teams) >= 2:
            # Check if they are non-simultaneous (sequential)
            team_dates: Dict[str, List[str]] = defaultdict(list)
            for e in entries:
                team_dates[e["team"]].append(e["date"])

            teams_list = list(unique_teams)
            # If any two teams have non-overlapping time ranges, flag it
            for i, t1 in enumerate(teams_list):
                dates_1 = sorted(team_dates[t1])
                for t2 in teams_list[i + 1:]:
                    dates_2 = sorted(team_dates[t2])
                    # Non-overlapping: last date of one < first date of other
                    if dates_1[-1] < dates_2[0] or dates_2[-1] < dates_1[0]:
                        return {
                            "code": "C3",
                            "description": f"2개의 다른 {school_type} 학교 (비동시)",
                            "school_type": school_type,
                            "team1": t1,
                            "team1_period": f"{dates_1[0][:10]}~{dates_1[-1][:10]}",
                            "team2": t2,
                            "team2_period": f"{dates_2[0][:10]}~{dates_2[-1][:10]}",
                        }
    return None


def detect_c4_dual_weapon(records: List[Dict]) -> Optional[Dict]:
    """C4: Single profile with 2 weapons (may be valid but review needed).

    Extract weapon from event_name. If a player has exactly 2 different
    weapons, flag for review. 3+ is handled by INVESTIGATION category.
    """
    weapons = set()
    weapon_examples: Dict[str, str] = {}
    for r in records:
        event_name = r.get("event_name", "")
        for w in ("플뢰레", "에페", "사브르"):
            if w in event_name:
                weapons.add(w)
                if w not in weapon_examples:
                    weapon_examples[w] = event_name

    if len(weapons) == 2:
        wlist = list(weapons)
        return {
            "code": "C4",
            "description": f"2종 무기 사용: {wlist[0]}, {wlist[1]}",
            "weapons": wlist,
            "examples": weapon_examples,
        }
    return None


# ============================================================
# INVESTIGATION detection (anomalies)
# ============================================================

def detect_investigation_anomalies(records: List[Dict]) -> List[Dict]:
    """Detect data anomalies that require investigation."""
    anomalies = []

    # 3+ weapons
    weapons = set()
    for r in records:
        event_name = r.get("event_name", "")
        for w in ("플뢰레", "에페", "사브르"):
            if w in event_name:
                weapons.add(w)
    if len(weapons) >= 3:
        anomalies.append({
            "code": "INV_WEAPON3",
            "description": f"3종 무기 사용: {', '.join(sorted(weapons))}",
            "weapons": list(weapons),
        })

    # Mixed gender
    genders = set()
    gender_examples = {}
    for r in records:
        g = extract_gender(r.get("event_name", ""))
        if g:
            genders.add(g)
            if g not in gender_examples:
                gender_examples[g] = r.get("event_name", "")
    if len(genders) > 1:
        anomalies.append({
            "code": "INV_GENDER",
            "description": "남/여 종목 동시 출전 (미등록 동명이인?)",
            "genders": list(genders),
            "examples": gender_examples,
        })

    # Age group regression
    dated = sorted(
        [r for r in records if r.get("comp_date")],
        key=lambda x: x["comp_date"],
    )
    for i in range(len(dated) - 1):
        age1 = ""
        age2 = ""
        for ag_key in ("초등부", "중등부", "고등부", "대학부", "일반부",
                       "여중", "남중", "여고", "남고", "여대", "남대"):
            if ag_key in dated[i].get("event_name", ""):
                age1 = ag_key
                break
        for ag_key in ("초등부", "중등부", "고등부", "대학부", "일반부",
                       "여중", "남중", "여고", "남고", "여대", "남대"):
            if ag_key in dated[i + 1].get("event_name", ""):
                age2 = ag_key
                break
        if age1 and age2:
            level1 = get_age_group_level(age1)
            level2 = get_age_group_level(age2)
            if level1 > 0 and level2 > 0 and level1 - level2 >= 2:
                d1 = dated[i]["comp_date"][:10]
                d2 = dated[i + 1]["comp_date"][:10]
                anomalies.append({
                    "code": "INV_AGE_REGRESS",
                    "description": f"나이그룹 역행: {age1}({d1}) → {age2}({d2})",
                    "from_age": age1,
                    "to_age": age2,
                    "from_date": d1,
                    "to_date": d2,
                })
                break

    return anomalies


# ============================================================
# Main Audit
# ============================================================

def run_audit(
    competitions: list,
    org_region_cache: Dict[str, Dict[str, str]],
) -> Dict:
    """Run the comprehensive homonym audit."""
    print("\n선수 레코드 수집 중...")
    player_records = collect_player_records(competitions)
    total_names = len(player_records)
    print(f"  고유 이름 {total_names}개")

    known_homonyms = PlayerIdentityResolver.KNOWN_HOMONYMS

    results = {
        "audit_date": datetime.now().strftime("%Y-%m-%d"),
        "total_unique_names": total_names,
        "total_records": sum(len(v) for v in player_records.values()),
        "summary": {"clean": 0, "confirmed": 0, "suspected": 0, "investigation": 0},
        "confirmed": [],
        "suspected": [],
        "investigation": [],
    }

    for name, records in player_records.items():
        # --- CONFIRMED: in KNOWN_HOMONYMS ---
        if name in known_homonyms:
            results["summary"]["confirmed"] += 1
            teams = set(r.get("team", "") for r in records if r.get("team"))
            results["confirmed"].append({
                "name": name,
                "record_count": len(records),
                "teams": sorted(teams),
                "homonym_groups": [
                    [sorted(a), sorted(b)]
                    for a, b in known_homonyms[name]
                ],
            })
            continue

        # --- INVESTIGATION: data anomalies ---
        anomalies = detect_investigation_anomalies(records)
        if anomalies:
            results["summary"]["investigation"] += 1
            teams = set(r.get("team", "") for r in records if r.get("team"))
            results["investigation"].append({
                "name": name,
                "record_count": len(records),
                "teams": sorted(teams),
                "anomalies": anomalies,
            })
            continue

        # --- SUSPECTED: C1~C4 detection ---
        suspicions = []

        c1 = detect_c1_regional_distance(records, org_region_cache)
        if c1:
            suspicions.append(c1)

        c2 = detect_c2_time_gap(records)
        if c2:
            suspicions.append(c2)

        c3 = detect_c3_school_level_repeat(records)
        if c3:
            suspicions.append(c3)

        c4 = detect_c4_dual_weapon(records)
        if c4:
            suspicions.append(c4)

        if suspicions:
            results["summary"]["suspected"] += 1
            teams = set(r.get("team", "") for r in records if r.get("team"))
            results["suspected"].append({
                "name": name,
                "record_count": len(records),
                "teams": sorted(teams),
                "suspicions": suspicions,
            })
            continue

        # --- CLEAN: no issues ---
        results["summary"]["clean"] += 1

    return results


def print_report(results: Dict):
    """Print human-readable audit report."""
    s = results["summary"]
    print(f"\n{'=' * 70}")
    print("동명이인 종합 감사 결과 (Homonym Comprehensive Audit)")
    print(f"{'=' * 70}")
    print(f"감사일: {results['audit_date']}")
    print(f"총 고유 이름: {results['total_unique_names']:,}명")
    print(f"총 레코드:   {results['total_records']:,}건")
    print(f"{'=' * 70}")
    print(f"  CLEAN         {s['clean']:>6,}  동명이인 위험 없음")
    print(f"  CONFIRMED     {s['confirmed']:>6,}  KNOWN_HOMONYMS 등록됨")
    print(f"  SUSPECTED     {s['suspected']:>6,}  수동 검토 필요 (C1~C4)")
    print(f"  INVESTIGATION {s['investigation']:>6,}  데이터 이상")
    print(f"{'=' * 70}")

    # SUSPECTED breakdown by code
    if results["suspected"]:
        code_counts: Dict[str, int] = defaultdict(int)
        for entry in results["suspected"]:
            for susp in entry["suspicions"]:
                code_counts[susp["code"]] += 1

        print("\nSUSPECTED 기준별 분포:")
        code_descs = {
            "C1": "같은 학교 레벨, 다른 도/광역시",
            "C2": "3년+ 활동 공백 후 다른 조직",
            "C3": "2개+ 다른 중/고등학교 (비동시)",
            "C4": "2종 무기 사용",
        }
        for code in sorted(code_counts.keys()):
            print(f"  {code}: {code_counts[code]:>4}  {code_descs.get(code, '')}")

    # Top 10 suspected
    if results["suspected"]:
        print("\nSUSPECTED 상위 10건:")
        for entry in results["suspected"][:10]:
            codes = ", ".join(s["code"] for s in entry["suspicions"])
            teams_str = ", ".join(entry["teams"][:4])
            if len(entry["teams"]) > 4:
                teams_str += f" (+{len(entry['teams']) - 4})"
            print(f"  {entry['name']:<8} [{codes}] 레코드:{entry['record_count']} 팀:{teams_str}")
            for susp in entry["suspicions"]:
                desc = susp.get("description", "")
                print(f"    -> {desc}")

    # INVESTIGATION breakdown
    if results["investigation"]:
        inv_counts: Dict[str, int] = defaultdict(int)
        for entry in results["investigation"]:
            for anom in entry["anomalies"]:
                inv_counts[anom["code"]] += 1

        print("\nINVESTIGATION 코드별 분포:")
        for code in sorted(inv_counts.keys()):
            print(f"  {code}: {inv_counts[code]:>4}")

    # Top 10 investigation
    if results["investigation"]:
        print("\nINVESTIGATION 상위 10건:")
        for entry in results["investigation"][:10]:
            codes = ", ".join(a["code"] for a in entry["anomalies"])
            teams_str = ", ".join(entry["teams"][:3])
            print(f"  {entry['name']:<8} [{codes}] 레코드:{entry['record_count']} 팀:{teams_str}")
            for anom in entry["anomalies"]:
                print(f"    -> {anom['description']}")


def main():
    t_start = time.time()

    # Load data
    competitions, org_region_cache = load_supabase_data()
    print(f"데이터 로드 완료 ({time.time() - t_start:.1f}s)")

    # Run audit
    t_audit = time.time()
    results = run_audit(competitions, org_region_cache)
    print(f"감사 완료 ({time.time() - t_audit:.1f}s)")

    # Print report
    print_report(results)

    # Save JSON report
    output_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "audit_homonyms_report.json"
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nJSON 보고서 저장: {output_path}")
    print(f"총 실행 시간: {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()
