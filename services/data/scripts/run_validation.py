"""Standalone validation: bypass full server startup, run DataValidator directly."""
import os
import sys
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client
from collections import defaultdict

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
sb = create_client(url, key)

print("이벤트 로드 중...")
t0 = time.time()

# Load all events with raw_data
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

# Load competitions
comps_resp = sb.table("competitions").select("id, comp_name, comp_idx, start_date").execute()
comp_map = {c["id"]: c for c in comps_resp.data}

print(f"로드 완료: {len(all_events)}개 이벤트, {len(comp_map)}개 대회 ({time.time()-t0:.1f}s)")

# Build competitions structure matching server format
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
        "events": []
    }
    for ev in events:
        raw = ev.get("raw_data") or {}
        comp_obj["events"].append({
            "sub_event_cd": ev.get("sub_event_cd", ""),
            "event_name": ev.get("event_name", ""),
            "de_bracket": raw.get("de_bracket", {}),
            "pool_rounds": raw.get("pool_rounds"),
            "pool_total_ranking": raw.get("pool_total_ranking", []),
            "final_rankings": raw.get("final_rankings"),
        })
    competitions.append(comp_obj)

print(f"검증 구조 구축 완료: {len(competitions)}개 대회")

# Load org region cache for R19/R20
print("조직 지역 캐시 로드 중...")
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
org_resp = sb.table("organizations").select("name, province, road_address, org_type").execute()
org_cache = {}
for org in (org_resp.data or []):
    name = org.get("name", "")
    if not name:
        continue
    prov_raw = (org.get("province", "") or "").strip()
    province = _PROVINCE_SHORT.get(prov_raw, prov_raw)
    org_type = org.get("org_type", "") or ""
    entry = {}
    if province:
        entry["province"] = province
    if org_type:
        entry["org_type"] = org_type
    if entry:
        org_cache[name] = entry
print(f"  조직 {len(org_cache)}개 캐시됨")

# Run validation
from app.data_validator import DataValidator

t1 = time.time()
validator = DataValidator(competitions, org_cache=org_cache)
issues = validator.validate_all()
t2 = time.time()

print(f"\n검증 완료 ({t2-t1:.1f}s)")

# Summary by rule_id
rule_counts = defaultdict(int)
for i in issues:
    rule_counts[i.rule_id] += 1

print(f"\n{'='*60}")
print(f"{'Rule':<8} {'Count':>8}  Description")
print(f"{'='*60}")

rule_descriptions = {
    "R1a": "Self-bout (player1 == player2)",
    "R1b": "Duplicate bout (same pair+round)",
    "R2": "Winner inconsistency",
    "R3": "Score anomaly",
    "R4": "Invalid round_name",
    "R5": "Bracket topology violation",
    "R6": "Final ranking mismatch",
    "R7": "Same-round duplicate (player in 2+ bouts)",
    "R8": "Round progression violation",
    "R9": "Pool bout count anomaly",
    "R10": "Gender inconsistency",
    "R11": "Age group regression",
    "R12": "3+ weapons (homonym suspect)",
    "R13": "Same date, different team (homonym)",
    "R14": "Same event, duplicate name",
    "R15": "Bracket size inconsistency",
    "R16": "Dual DE completeness",
    "R17": "Final ranking vs DE winner mismatch",
    "R19": "Event level vs org_type mismatch",
    "R20": "Same school level, different province",
    "R21": "3+ year activity gap, different team",
}

total = 0
for rule_id in sorted(rule_counts.keys()):
    cnt = rule_counts[rule_id]
    desc = rule_descriptions.get(rule_id, "")
    print(f"{rule_id:<8} {cnt:>8}  {desc}")
    total += cnt

print(f"{'='*60}")
print(f"{'TOTAL':<8} {total:>8}")

errors = [i for i in issues if i.severity == "ERROR"]
warnings = [i for i in issues if i.severity == "WARNING"]
print(f"\nERRORS: {len(errors)}, WARNINGS: {len(warnings)}")
