"""Standalone validation: bypass full server startup, run DataValidator directly."""
import os, sys, time
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

# Run validation
from app.data_validator import DataValidator

t1 = time.time()
validator = DataValidator(competitions)
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
