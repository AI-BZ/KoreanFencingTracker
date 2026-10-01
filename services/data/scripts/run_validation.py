"""전체 검증 배치 — 서버 기동 없이 DataValidator 를 직접 돌린다 (읽기 전용).

Guardian(`app/data_guardian.py`)은 **최근 N개 대회만** 본다(일일 점검 20, 그 외 50).
전 연도 전수 검증은 이 스크립트가 유일한 경로다. 두 숫자를 비교할 때 범위가
다르다는 것을 잊으면 "Guardian 은 2천건인데 배치는 6천건"처럼 읽혀 오해가 생긴다.

사용법:
    cd services/data
    PYTHONPATH=".:../../packages" python scripts/run_validation.py
    # DB 왕복을 줄이려면 이벤트 덤프를 캐시에 두고 반복 실행
    PYTHONPATH=".:../../packages" python scripts/run_validation.py --cache /tmp/ev.pkl
    # 특정 규칙 표본 열어보기 (트리아지)
    PYTHONPATH=".:../../packages" python scripts/run_validation.py --cache /tmp/ev.pkl --rule R8 --sample 10
출력: logs/validation_issues.json (--out 으로 변경)
"""
import argparse
import json
import os
import pickle
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(_ROOT, "logs", "validation_issues.json")

RULE_DESCRIPTIONS = {
    "R1a": "Self-bout (player1 == player2)",
    "R1b": "Duplicate bout (same pair+round)",
    "R1c": "Phantom bout (bracket capacity exceeded)",
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
    "R22": "Pool scrape failure (ptr without pool_rounds)",
    "R23": "Pool forfeit (Abandon) detection",
    "R24": "Dual DE shared round missing",
    "R25": "Dual DE de_phase missing",
    "R26": "Final rankings missing champion",
    "R27": "Final rankings name absent from event roster",
    "R28": "DE roster collapsed onto one name",
}

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


def load_raw(cache=None):
    """events / competitions / organizations 를 DB(또는 캐시)에서 읽는다."""
    if cache and os.path.exists(cache):
        d = pickle.load(open(cache, "rb"))
        return d["events"], d["comps"], d.get("orgs") or []

    from supabase import create_client

    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    events, off = [], 0
    while True:
        r = (sb.table("events").select(
            "id, competition_id, sub_event_cd, event_cd, event_name, category, weapon, gender, raw_data"
        ).range(off, off + 199).execute().data or [])
        events.extend(r)
        off += 200
        if len(r) < 200:
            break
    comps = sb.table("competitions").select("id, comp_idx, comp_name, start_date").execute().data or []
    orgs = sb.table("organizations").select("name, province, road_address, org_type").execute().data or []
    if cache:
        pickle.dump({"events": events, "comps": comps, "orgs": orgs}, open(cache, "wb"))
    return events, comps, orgs


def build_competitions(events, comps, limit_comps=None):
    """DataValidator 가 먹는 구조로 조립. Guardian 과 같은 키를 쓴다."""
    comp_map = {c["id"]: c for c in comps}
    if limit_comps:
        recent = sorted(comps, key=lambda c: (c.get("start_date") or ""), reverse=True)[:limit_comps]
        keep = {c["id"] for c in recent}
    else:
        keep = None

    by_comp = defaultdict(list)
    for ev in events:
        cid = ev.get("competition_id")
        if keep is not None and cid not in keep:
            continue
        by_comp[cid].append(ev)

    out = []
    for cid, evs in by_comp.items():
        info = comp_map.get(cid, {})
        comp_obj = {
            "competition": {
                "id": cid,
                # 🔴 competitions 테이블의 컬럼은 comp_name 이다. 'name' 으로 읽으면 전부 빈칸이 되어
                # 리포트에서 어느 대회인지 알 수 없게 된다 (Guardian 이 이 실수를 하고 있었다).
                "name": info.get("comp_name", ""),
                "event_cd": info.get("comp_idx", ""),
                "start_date": info.get("start_date", ""),
            },
            "events": [],
        }
        for ev in evs:
            raw = ev.get("raw_data") or {}
            if isinstance(raw, str):
                raw = json.loads(raw)
            comp_obj["events"].append({
                "sub_event_cd": ev.get("sub_event_cd", ""),
                "event_cd": ev.get("event_cd", ""),
                "event_name": ev.get("event_name", "") or "",
                # 🔴 `PlayerIdentityResolver` 는 종목명을 `name` 키로 읽는다(server.py 가 그렇게 넘긴다).
                #    여기서 빠뜨리면 리졸버의 모든 기록이 event_name="" 으로 들어가 **성별·나이그룹을
                #    전혀 못 읽고**, 그 상태로 만든 프로필로 R10/R11 을 판정하게 된다.
                #    (2026-09-29 실측: 이 누락 때문에 이서우 104개 기록 전부 성별 '' 이었고,
                #     동명이인 분리도 1,027개 → 639개로 줄어 있었다.)
                "name": ev.get("event_name", "") or "",
                "weapon": ev.get("weapon", ""),
                "gender": ev.get("gender", ""),
                "age_group": ev.get("age_group", ""),
                "event_type": ev.get("category") if ev.get("category") in ("개인", "단체") else "개인",
                "category": ev.get("category"),
                "de_bracket": raw.get("de_bracket", {}),
                "pool_rounds": raw.get("pool_rounds"),
                "pool_total_ranking": raw.get("pool_total_ranking", []),
                "final_rankings": raw.get("final_rankings"),
                # R26 의 '협회 표 자체 이상' 판정에 필요하다 (KFA_SOURCE_ANOMALIES 는
                # 출처가 협회 표일 때만 적용된다). 빠뜨리면 등록해도 ERROR 로 남는다.
                "final_rankings_source": raw.get("final_rankings_source"),
                "participants": raw.get("participants"),
            })
        out.append(comp_obj)
    return out


def build_org_cache(orgs):
    cache = {}
    for org in orgs or []:
        name = org.get("name", "")
        if not name:
            continue
        prov_raw = (org.get("province", "") or "").strip()
        entry = {}
        province = _PROVINCE_SHORT.get(prov_raw, prov_raw)
        if province:
            entry["province"] = province
        if org.get("org_type"):
            entry["org_type"] = org["org_type"]
        if entry:
            cache[name] = entry
    return cache


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="이벤트 덤프 pickle (있으면 읽고, 없으면 DB 에서 받아 저장)")
    ap.add_argument("--out", default=OUT, help="이슈 전량 JSON 저장 경로")
    ap.add_argument("--rule", action="append", help="이 규칙의 표본만 출력 (여러 번 지정 가능)")
    ap.add_argument("--sample", type=int, default=0, help="--rule 당 출력할 표본 수")
    ap.add_argument("--limit-comps", type=int,
                    help="최근 N개 대회만 (Guardian 범위 재현용: 일일 20, 그 외 50)")
    ap.add_argument("--no-org", action="store_true", help="org_cache 없이 실행 (R19/R20 비활성)")
    ap.add_argument("--no-identity", action="store_true",
                    help="선수 식별 리졸버 없이 검증 (동명이인 판정이 수동 등록 목록 기준으로 내려감)")
    args = ap.parse_args()

    print("이벤트 로드 중...")
    t0 = time.time()
    events, comps, orgs = load_raw(args.cache)
    print(f"로드 완료: {len(events)}개 이벤트, {len(comps)}개 대회 ({time.time() - t0:.1f}s)")

    competitions = build_competitions(events, comps, args.limit_comps)
    n_events = sum(len(c["events"]) for c in competitions)
    scope = f"최근 {args.limit_comps}개 대회" if args.limit_comps else "전 연도 전수"
    print(f"검증 범위: {scope} — 대회 {len(competitions)}개 / 종목 {n_events}개")

    org_cache = {} if args.no_org else build_org_cache(orgs)
    if org_cache:
        print(f"  조직 {len(org_cache)}개 캐시됨 (R19/R20 활성)")

    from app.data_validator import DataValidator

    # 동명이인 규칙(R10/R11/R13)은 "실제로 다른 프로필로 갈라졌는가"로 판정한다.
    # 그러려면 서버와 같은 선수 식별 결과가 필요하므로 여기서도 리졸버를 만든다
    # (전수 기준 약 40초). --no-identity 로 끄면 예전처럼 수동 등록 목록 기준이 된다.
    resolver = None
    if not args.no_identity:
        from app.player_identity import PlayerIdentityResolver
        t_id = time.time()
        resolver = PlayerIdentityResolver()
        if org_cache:
            resolver.set_org_region_cache(org_cache)
        for comp in competitions:
            resolver.add_competition_data(comp)
        resolver.resolve_identities()
        dup = sum(1 for v in resolver.name_to_profiles.values() if len(v) > 1)
        print(f"  선수 식별: 프로필 {len(resolver.profiles)}개 / 동명이인 분리 {dup}개 ({time.time() - t_id:.1f}s)")

    t1 = time.time()
    issues = DataValidator(competitions, org_cache=org_cache,
                           identity_resolver=resolver).validate_all()
    print(f"\n검증 완료 ({time.time() - t1:.1f}s)")

    by_rule = defaultdict(lambda: defaultdict(int))
    for i in issues:
        by_rule[i.rule_id][i.severity] += 1

    print(f"\n{'=' * 78}")
    print(f"{'Rule':<6} {'ERROR':>7} {'WARN':>7} {'INFO':>7} {'RESOLVED':>9}  Description")
    print(f"{'=' * 78}")
    totals = defaultdict(int)
    for rule_id in sorted(by_rule, key=lambda r: (len(r), r)):
        sev = by_rule[rule_id]
        for k, v in sev.items():
            totals[k] += v
        print(f"{rule_id:<6} {sev.get('ERROR', 0):>7} {sev.get('WARNING', 0):>7} "
              f"{sev.get('INFO', 0):>7} {sev.get('RESOLVED', 0):>9}  "
              f"{RULE_DESCRIPTIONS.get(rule_id, '')}")
    print(f"{'=' * 78}")
    print(f"{'TOTAL':<6} {totals['ERROR']:>7} {totals['WARNING']:>7} "
          f"{totals['INFO']:>7} {totals['RESOLVED']:>9}   (합계 {len(issues)})")

    if args.rule:
        for rule_id in args.rule:
            picked = [i for i in issues if i.rule_id == rule_id]
            print(f"\n--- {rule_id} 표본 ({len(picked)}건 중 {min(args.sample or 5, len(picked))}건) ---")
            for i in picked[: (args.sample or 5)]:
                print(f"  [{i.severity}] {i.competition_name} / {i.event_cd} / {i.player_name}")
                print(f"      {i.message}")
                if i.data:
                    print(f"      data={json.dumps(i.data, ensure_ascii=False)[:400]}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    json.dump({
        "scope": scope,
        "competitions": len(competitions),
        "events": n_events,
        "by_rule": {r: dict(s) for r, s in sorted(by_rule.items())},
        "totals": dict(totals),
        "issues": [i.to_dict() for i in issues],
    }, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n저장: {args.out}")


if __name__ == "__main__":
    main()
