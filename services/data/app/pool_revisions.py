"""풀(예선 조편성) 개정 이력 기록·조회.

KFA 는 대회 직전 풀을 여러 차례 다시 올린다. 우리는 events.raw_data 를 덮어쓰기만
해서 "몇 번 바뀌었는지"를 알 수 없었다(2026-08-27 확인). 이 모듈이 조편성이 실제로
달라진 순간마다 data_pool_revisions 에 한 행을 남긴다.

핵심 설계 — 해시를 둘로 나눈다:

    roster_hash  누가 참가하는가 (선수 집합)
    layout_hash  누가 어느 조 몇 번인가 (배정)

둘을 나눠야 나중에 변경 사유를 판별할 수 있다:

    로스터 동일 + 배정 변경  → 순수 재추첨
    로스터 감소 + 배정 변경  → 참가자가 빠져서 다시 돌림
    로스터 -16  + 배정 변경  → 시드(풀 면제) 16명을 잘못 넣었다가 뺌

점수(V/D)는 어느 해시에도 넣지 않는다. 경기가 시작되면 점수는 계속 변하는데
그건 조편성 변경이 아니다 — 넣으면 매 5분 스크래핑마다 새 개정이 쌓인다.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

# Supabase 는 timestamptz 를 UTC ISO 로 돌려준다. 이 표를 읽는 사람(학부모·운영자)은
# 대회 현장 시각으로 보므로 표시 직전에 KST 로 바꾼다. 그냥 문자열을 잘라 쓰면
# 20:07 에 기록한 개정이 11:07 로 보인다.
_KST = timezone(timedelta(hours=9))


def _to_kst_label(value: Any) -> str:
    """ISO 타임스탬프 → 'MM-DD HH:MM' (KST). 못 읽으면 원본을 그대로 돌려준다."""
    if not value:
        return ""
    text = str(value)
    try:
        cleaned = text.replace("Z", "+00:00")
        # Postgres 는 소수점 이하를 6자리보다 길게 줄 때가 있고, 그러면
        # fromisoformat 이 거부한다. 소수부만 6자리로 자른다.
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


def _person_key(entry: Dict[str, Any]) -> str:
    """선수 1명의 식별 키. 동명이인 때문에 소속을 함께 쓴다."""
    name = str(entry.get("name") or "").strip()
    team = str(entry.get("team") or "").strip()
    return f"{name}|{team}"


def extract_layout(pool_rounds: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """pool_rounds → {선수키: {name, team, pool, position, round}}

    점수·승패·순위는 일부러 버린다(위 모듈 설명 참조).
    같은 선수가 여러 라운드에 나오면 (라운드, 풀) 을 모두 담아 배정을 표현한다.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for pool in pool_rounds or []:
        pool_no = pool.get("pool_number")
        round_no = pool.get("round_number", 1)
        for row in pool.get("results", []) or []:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            key = _person_key(row)
            if round_no != 1 and key in out:
                # 2라운드 이상은 배정 표기에만 덧붙인다(1라운드 배정을 덮지 않음)
                out[key].setdefault("extra_rounds", []).append((round_no, pool_no))
                continue
            out[key] = {
                "name": name,
                "team": str(row.get("team") or "").strip(),
                "pool": pool_no,
                "position": row.get("position"),
                "round": round_no,
            }
    return out


def _sha(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprint(pool_rounds: List[Dict[str, Any]]) -> Tuple[str, str, int, int]:
    """(roster_hash, layout_hash, pool_count, fencer_count)"""
    layout = extract_layout(pool_rounds)
    roster = sorted(layout.keys())
    roster_hash = _sha(roster)
    layout_hash = _sha(
        sorted(
            (k, v.get("round"), v.get("pool"), v.get("position"))
            for k, v in layout.items()
        )
    )
    pool_count = len({str(p.get("pool_number")) for p in (pool_rounds or [])})
    return roster_hash, layout_hash, pool_count, len(layout)


def pack_layout(layout: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """배정 스냅샷을 표에 담을 형태로 압축. 키를 짧게 쓴다(146명 × 21풀 규모).

    이걸 저장해 두는 이유: 다음 개정의 diff 기준이 된다. 스케줄러 경로는 저장 직전
    DB 값을 갖고 있어 diff 가 되지만, 그 경로 밖에서 raw_data 가 바뀌면 직전 조편성을
    복원할 길이 없다 — 도입 당일 실제로 그 일이 났다(2026-08-27 여자 플러레 재추첨).
    """
    return [
        {"n": v["name"], "t": v["team"], "p": v.get("pool"), "s": v.get("position")}
        for v in sorted(layout.values(), key=lambda x: (x.get("pool") or 0, x.get("position") or 0))
    ]


def unpack_layout(packed: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """pack_layout 의 역변환. 없으면 빈 dict (diff 불가 → 개수만 기록)."""
    out: Dict[str, Dict[str, Any]] = {}
    for row in packed or []:
        name = str(row.get("n") or "").strip()
        if not name:
            continue
        team = str(row.get("t") or "").strip()
        out[f"{name}|{team}"] = {
            "name": name, "team": team,
            "pool": row.get("p"), "position": row.get("s"), "round": 1,
        }
    return out


def diff_layouts(
    old: Dict[str, Dict[str, Any]],
    new: Dict[str, Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """직전 개정 대비 추가/제외/이동 선수."""
    old_keys, new_keys = set(old), set(new)

    added = [
        {"name": new[k]["name"], "team": new[k]["team"], "pool": new[k]["pool"]}
        for k in sorted(new_keys - old_keys)
    ]
    removed = [
        {"name": old[k]["name"], "team": old[k]["team"], "pool": old[k]["pool"]}
        for k in sorted(old_keys - new_keys)
    ]
    moved = []
    for k in sorted(old_keys & new_keys):
        o, n = old[k], new[k]
        if o.get("pool") != n.get("pool") or o.get("position") != n.get("position"):
            moved.append({
                "name": n["name"],
                "team": n["team"],
                "from": {"pool": o.get("pool"), "position": o.get("position")},
                "to": {"pool": n.get("pool"), "position": n.get("position")},
            })
    return {"added": added, "removed": removed, "moved": moved}


# 진단용 상한. 전원이 바뀐 재추첨이면 moved 가 200건이 되는데, 그걸 통째로
# 저장하면 행 하나가 수십 KB 가 된다. 개수는 별도로 남기므로 목록은 잘라도 된다.
_DIFF_SAMPLE_LIMIT = 60


def record_revision(
    db,
    *,
    sub_event_cd: str,
    pool_rounds: List[Dict[str, Any]],
    event_id: Optional[int] = None,
    competition_id: Optional[int] = None,
    entry_count: Optional[int] = None,
    source: str = "scheduler",
    note: Optional[str] = None,
    previous_pool_rounds: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """조편성이 직전 개정과 다르면 새 개정을 남기고 그 행을 반환. 같으면 None.

    실패해도 예외를 밖으로 내보내지 않는다 — 이 기록은 부가 기능이고,
    여기서 터져서 대회 데이터 저장을 막으면 안 된다.
    """
    if not pool_rounds:
        return None

    try:
        roster_hash, layout_hash, pool_count, fencer_count = fingerprint(pool_rounds)

        prev = (
            db.table("data_pool_revisions")
            .select("revision_no, roster_hash, layout_hash, layout")
            .eq("sub_event_cd", sub_event_cd)
            .order("revision_no", desc=True)
            .limit(1)
            .execute()
        )
        prev_row = prev.data[0] if prev.data else None

        if prev_row and prev_row["roster_hash"] == roster_hash \
                and prev_row["layout_hash"] == layout_hash:
            return None   # 조편성 그대로 — 점수만 갱신된 경우가 여기로 온다

        revision_no = (prev_row["revision_no"] + 1) if prev_row else 1

        new_layout = extract_layout(pool_rounds)

        # 직전 배정을 구하는 순서:
        #   ① 호출자가 넘긴 저장 직전 DB 값 (스케줄러 경로)
        #   ② 직전 개정 행에 저장해 둔 스냅샷 (그 외 모든 경로)
        # 둘 다 없으면 diff 없이 개수만 남긴다 — 지어내지 않는다(제1원칙).
        added = removed = moved = []
        if prev_row:
            prev_layout = (
                extract_layout(previous_pool_rounds) if previous_pool_rounds
                else unpack_layout(prev_row.get("layout"))
            )
            if prev_layout:
                d = diff_layouts(prev_layout, new_layout)
                added, removed, moved = d["added"], d["removed"], d["moved"]

        row = {
            "event_id": event_id,
            "competition_id": competition_id,
            "sub_event_cd": sub_event_cd,
            "revision_no": revision_no,
            "pool_count": pool_count,
            "fencer_count": fencer_count,
            "entry_count": entry_count,
            "roster_hash": roster_hash,
            "layout_hash": layout_hash,
            "layout": pack_layout(new_layout),
            # 목록은 표본, 개수는 별도 컬럼. 목록 길이를 개수로 읽으면 상한에 잘린
            # 값이 그대로 화면에 나간다(도입 당일 78명 이동이 60으로 표시된 사고).
            "added_players": added[:_DIFF_SAMPLE_LIMIT],
            "removed_players": removed[:_DIFF_SAMPLE_LIMIT],
            "moved_players": moved[:_DIFF_SAMPLE_LIMIT],
            "added_count": len(added),
            "removed_count": len(removed),
            "moved_count": len(moved),
            "roster_changed": bool(prev_row) and prev_row["roster_hash"] != roster_hash,
            "layout_changed": bool(prev_row) and prev_row["layout_hash"] != layout_hash,
            "source": source,
            "note": note,
        }
        if len(moved) > _DIFF_SAMPLE_LIMIT or len(added) > _DIFF_SAMPLE_LIMIT \
                or len(removed) > _DIFF_SAMPLE_LIMIT:
            row["note"] = " / ".join(filter(None, [
                note,
                f"목록 일부만 저장 (추가 {len(added)} 제외 {len(removed)} 이동 {len(moved)})",
            ]))

        db.table("data_pool_revisions").insert(row).execute()
        logger.info(
            f"    📋 풀 개정 {revision_no}차 기록: {sub_event_cd} "
            f"({pool_count}풀 {fencer_count}명"
            + (f", 추가 {len(added)} 제외 {len(removed)} 이동 {len(moved)}" if prev_row else ", 최초 관측")
            + ")"
        )
        return row

    except Exception as e:
        logger.warning(f"    풀 개정 기록 실패 ({sub_event_cd}): {e}")
        return None


def get_revisions(db, sub_event_cd: str) -> List[Dict[str, Any]]:
    """개정 이력 (오래된 순). 실패 시 빈 목록."""
    try:
        res = (
            db.table("data_pool_revisions")
            .select("*")
            .eq("sub_event_cd", sub_event_cd)
            .order("revision_no")
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.debug(f"풀 개정 조회 실패 ({sub_event_cd}): {e}")
        return []


def summarize(revisions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """UI 표시용 요약.

    first_seen 은 '최초 게시 시각'이 아니라 '우리가 처음 관측한 시각'이다.
    source='backfill' 인 1차 개정은 이 기능을 넣기 전부터 있던 풀이라
    그 전에 몇 번 바뀌었는지 알 수 없다 — UI 가 그 사실을 밝히도록 플래그를 준다.
    """
    if not revisions:
        return None
    first, last = revisions[0], revisions[-1]
    return {
        "revision_count": len(revisions),
        "first_seen": _to_kst_label(first.get("detected_at")),
        "last_changed": _to_kst_label(last.get("detected_at")),
        "first_pool_count": first.get("pool_count"),
        "first_fencer_count": first.get("fencer_count"),
        "first_entry_count": first.get("entry_count"),
        "current_pool_count": last.get("pool_count"),
        "current_fencer_count": last.get("fencer_count"),
        "current_entry_count": last.get("entry_count"),
        "baseline_is_backfill": first.get("source") == "backfill",
        "revisions": [
            {
                "no": r.get("revision_no"),
                "at": _to_kst_label(r.get("detected_at")),
                "pool_count": r.get("pool_count"),
                "fencer_count": r.get("fencer_count"),
                "entry_count": r.get("entry_count"),
                "roster_changed": r.get("roster_changed"),
                "layout_changed": r.get("layout_changed"),
                # *_count 가 실제 인원. *_players 는 상한에 잘린 표본이라
                # 길이를 개수로 쓰면 안 된다. (구 행은 count 가 0이라 표본으로 폴백)
                "added": r.get("added_count") or len(r.get("added_players") or []),
                "removed": r.get("removed_count") or len(r.get("removed_players") or []),
                "moved": r.get("moved_count") or len(r.get("moved_players") or []),
                "added_players": r.get("added_players") or [],
                "removed_players": r.get("removed_players") or [],
                "note": r.get("note"),
                "source": r.get("source"),
            }
            for r in revisions
        ],
    }
