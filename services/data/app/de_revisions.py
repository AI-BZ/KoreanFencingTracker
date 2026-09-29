"""DE(대진표) 개정 이력 기록·조회.

풀과 같은 문제가 DE 에도 있다: KFA 는 대회 직전·진행 중에 DE 출전 인원과 대진을
다시 올리는데, 우리는 events.raw_data 를 덮어쓰기만 해서 "언제 무엇이 바뀌었는지"를
알 수 없었다. 대진이 틀리다는 제보가 와도 우리 쪽이 못 받아온 건지, 받았는데
그 사이 또 바뀐 건지 구분할 방법이 없다.

핵심 설계 — 해시를 둘로 나눈다 (pool_revisions 와 같은 사상):

    roster_hash   누가 대진에 있는가 (선수 집합)
    pairing_hash  누가 누구와, 어느 위상·라운드·경기번호에서 붙는가

**점수·승자는 어느 해시에도 넣지 않는다.** 경기가 진행되면 점수는 계속 변하는데
그건 대진 변경이 아니다 — 넣으면 스크래핑마다 새 개정이 쌓여 진짜 변경이 묻힌다.

위상(de_phase)은 반드시 키에 포함한다. 예선 64강과 본선 64강은 다른 경기다
(services/data/CLAUDE.md "Dual DE: 예선 64강 ≠ 본선 64강" 참조).
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

_KST = timezone(timedelta(hours=9))

# 목록은 표본으로만 저장한다(행이 수십 KB 가 되는 것을 막는다). 개수는 별도 컬럼.
_DIFF_SAMPLE_LIMIT = 60


def _to_kst_label(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    try:
        cleaned = text.replace("Z", "+00:00")
        if "." in cleaned:
            head, _, tail = cleaned.partition(".")
            digits = ""
            for ch in tail:
                if not ch.isdigit():
                    break
                digits += ch
            cleaned = f"{head}.{digits[:6]}{tail[len(digits):]}"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_KST).strftime("%m-%d %H:%M")
    except Exception:
        return text[5:16].replace("T", " ")


def _sha(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _person(name: Any, team: Any) -> str:
    n = str(name or "").strip()
    if not n:
        return ""
    return f"{n}|{str(team or '').strip()}"


def extract_pairings(de_bracket: Dict[str, Any]) -> List[Dict[str, Any]]:
    """de_bracket → 대진 목록 [{ph, rd, no, p1, t1, p2, t2, bye}]

    점수·승자는 담지 않는다. 부전승 여부는 대진의 성질이므로 담는다
    (부전승이 실경기로 바뀌면 상대가 생긴 것이라 대진 변경이 맞다).
    """
    out: List[Dict[str, Any]] = []
    for b in (de_bracket or {}).get("full_bouts") or []:
        out.append({
            "ph": b.get("de_phase") or "",
            "rd": b.get("round_name") or "",
            "no": b.get("match_number"),
            "p1": str(b.get("player1_name") or "").strip(),
            "t1": str(b.get("player1_team") or "").strip(),
            "p2": str(b.get("player2_name") or "").strip(),
            "t2": str(b.get("player2_team") or "").strip(),
            "bye": bool(b.get("is_bye")),
        })
    out.sort(key=lambda x: (x["ph"], x["rd"], x["no"] if x["no"] is not None else 0))
    return out


def roster_of(pairings: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """대진에 등장하는 선수 → {name, team, 최초 등장 위치}"""
    out: Dict[str, Dict[str, Any]] = {}
    for p in pairings:
        for who, team in ((p["p1"], p["t1"]), (p["p2"], p["t2"])):
            key = _person(who, team)
            if not key or key in out:
                continue
            out[key] = {"name": who, "team": team,
                        "at": f"{p['ph']}/{p['rd']}#{p['no']}"}
    return out


def fingerprint(de_bracket: Dict[str, Any]) -> Tuple[str, str, int, int, List[Dict]]:
    """(roster_hash, pairing_hash, 선수 수, 경기 수, pairings)"""
    pairings = extract_pairings(de_bracket)
    roster = roster_of(pairings)
    roster_hash = _sha(sorted(roster.keys()))
    pairing_hash = _sha([(p["ph"], p["rd"], p["no"],
                          _person(p["p1"], p["t1"]), _person(p["p2"], p["t2"]), p["bye"])
                         for p in pairings])
    return roster_hash, pairing_hash, len(roster), len(pairings), pairings


def summarize_bracket(de_bracket: Dict[str, Any]) -> Dict[str, Any]:
    """위상·라운드별 경기 수 요약 (사람이 읽는 용도)."""
    counts: Dict[str, int] = {}
    for b in (de_bracket or {}).get("full_bouts") or []:
        key = f"{b.get('de_phase') or '?'}/{b.get('round_name') or '?'}"
        counts[key] = counts.get(key, 0) + 1
    return {
        "format": (de_bracket or {}).get("format"),
        "first_de_size": ((de_bracket or {}).get("first_de") or {}).get("bracket_size"),
        "second_de_size": ((de_bracket or {}).get("second_de") or {}).get("bracket_size"),
        "rounds": counts,
    }


def diff_pairings(old: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> Dict[str, List]:
    """직전 개정 대비 추가/제외 선수, 그리고 '상대가 바뀐 경기'."""
    old_roster, new_roster = roster_of(old), roster_of(new)
    added = [{"name": new_roster[k]["name"], "team": new_roster[k]["team"],
              "at": new_roster[k]["at"]}
             for k in sorted(set(new_roster) - set(old_roster))]
    removed = [{"name": old_roster[k]["name"], "team": old_roster[k]["team"],
                "at": old_roster[k]["at"]}
               for k in sorted(set(old_roster) - set(new_roster))]

    def by_slot(rows):
        return {(r["ph"], r["rd"], r["no"]): r for r in rows}

    o, n = by_slot(old), by_slot(new)
    repaired = []
    for slot in sorted(set(o) & set(n), key=lambda s: (s[0], s[1], s[2] or 0)):
        a, b = o[slot], n[slot]
        if (_person(a["p1"], a["t1"]), _person(a["p2"], a["t2"])) != \
           (_person(b["p1"], b["t1"]), _person(b["p2"], b["t2"])):
            repaired.append({
                "at": f"{slot[0]}/{slot[1]}#{slot[2]}",
                "before": [a["p1"], a["p2"]],
                "after": [b["p1"], b["p2"]],
            })
    return {"added": added, "removed": removed, "repaired": repaired}


def record_revision(
    db,
    *,
    sub_event_cd: str,
    de_bracket: Dict[str, Any],
    event_id: Optional[int] = None,
    competition_id: Optional[int] = None,
    source: str = "scheduler",
    note: Optional[str] = None,
    previous_de_bracket: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """대진이 직전 개정과 다르면 새 개정을 남기고 그 행을 반환. 같으면 None.

    실패해도 예외를 밖으로 내보내지 않는다 — 부가 기능이 대회 데이터 저장을 막으면 안 된다.
    """
    if not de_bracket or not de_bracket.get("full_bouts"):
        return None

    try:
        roster_hash, pairing_hash, n_players, n_bouts, pairings = fingerprint(de_bracket)

        prev = (
            db.table("data_de_revisions")
            .select("revision_no, roster_hash, pairing_hash, pairings")
            .eq("sub_event_cd", sub_event_cd)
            .order("revision_no", desc=True)
            .limit(1)
            .execute()
        )
        prev_row = prev.data[0] if prev.data else None

        if prev_row and prev_row["roster_hash"] == roster_hash \
                and prev_row["pairing_hash"] == pairing_hash:
            return None   # 대진 그대로 — 점수만 갱신된 경우가 여기로 온다

        revision_no = (prev_row["revision_no"] + 1) if prev_row else 1

        added = removed = repaired = []
        if prev_row:
            prev_pairings = (extract_pairings(previous_de_bracket) if previous_de_bracket
                             else (prev_row.get("pairings") or []))
            if prev_pairings:
                d = diff_pairings(prev_pairings, pairings)
                added, removed, repaired = d["added"], d["removed"], d["repaired"]

        row = {
            "event_id": event_id,
            "competition_id": competition_id,
            "sub_event_cd": sub_event_cd,
            "revision_no": revision_no,
            "de_format": (de_bracket or {}).get("format"),
            "bracket_summary": summarize_bracket(de_bracket),
            "entrant_count": n_players,
            "bout_count": n_bouts,
            "roster_hash": roster_hash,
            "pairing_hash": pairing_hash,
            "pairings": pairings,
            "added_players": added[:_DIFF_SAMPLE_LIMIT],
            "removed_players": removed[:_DIFF_SAMPLE_LIMIT],
            "repaired": repaired[:_DIFF_SAMPLE_LIMIT],
            "added_count": len(added),
            "removed_count": len(removed),
            "repaired_count": len(repaired),
            "roster_changed": bool(prev_row) and prev_row["roster_hash"] != roster_hash,
            "pairing_changed": bool(prev_row) and prev_row["pairing_hash"] != pairing_hash,
            "source": source,
            "note": note,
        }

        db.table("data_de_revisions").insert(row).execute()
        logger.info(
            f"    🗂 DE 개정 {revision_no}차 기록: {sub_event_cd} "
            f"({n_players}명 {n_bouts}경기"
            + (f", 추가 {len(added)} 제외 {len(removed)} 대진변경 {len(repaired)}"
               if prev_row else ", 최초 관측")
            + ")"
        )
        return row

    except Exception as e:
        logger.warning(f"    DE 개정 기록 실패 ({sub_event_cd}): {e}")
        return None


def get_revisions(db, sub_event_cd: str) -> List[Dict[str, Any]]:
    try:
        res = (db.table("data_de_revisions")
               .select("id, revision_no, de_format, bracket_summary, entrant_count, bout_count,"
                       "added_players, removed_players, repaired,"
                       "added_count, removed_count, repaired_count,"
                       "roster_changed, pairing_changed, detected_at, source, note")
               .eq("sub_event_cd", sub_event_cd).order("revision_no").execute())
        return res.data or []
    except Exception as e:
        logger.debug(f"DE 개정 조회 실패 ({sub_event_cd}): {e}")
        return []


def summarize(revisions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """UI 표시용 요약. first_seen 은 '최초 게시'가 아니라 '우리가 처음 관측한 시각'."""
    if not revisions:
        return None
    first, last = revisions[0], revisions[-1]
    return {
        "revision_count": len(revisions),
        "first_seen": _to_kst_label(first.get("detected_at")),
        "last_changed": _to_kst_label(last.get("detected_at")),
        "first_entrant_count": first.get("entrant_count"),
        "current_entrant_count": last.get("entrant_count"),
        "first_bout_count": first.get("bout_count"),
        "current_bout_count": last.get("bout_count"),
        "baseline_is_backfill": first.get("source") == "backfill",
        "revisions": [
            {
                "no": r.get("revision_no"),
                "at": _to_kst_label(r.get("detected_at")),
                "entrants": r.get("entrant_count"),
                "bouts": r.get("bout_count"),
                "added": r.get("added_count") or 0,
                "removed": r.get("removed_count") or 0,
                "repaired": r.get("repaired_count") or 0,
                "roster_changed": r.get("roster_changed"),
                "pairing_changed": r.get("pairing_changed"),
                "added_players": r.get("added_players") or [],
                "removed_players": r.get("removed_players") or [],
                "repaired_sample": (r.get("repaired") or [])[:8],
                "source": r.get("source"),
                "note": r.get("note"),
            }
            for r in revisions
        ],
    }
