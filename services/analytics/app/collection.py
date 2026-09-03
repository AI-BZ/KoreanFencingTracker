"""A token-gated index of one fencer's unlisted bouts.

A coach picking a bout out of fourteen should not have to scroll a chat log for
fourteen links. This builds the shelf those links sit on — and the shelf is the
part that needs care, because a *list* of private bouts leaks more than any one
of them does. The report ids already carry minors' names; an index adds who
they fenced, when, and how it ended, all in one place. So the page answers to
the same rule as the reports it points at, arrived at from the other side:

* ``app.sharing`` inverts id access for a report — the id stops resolving and a
  token is the only way in.
* A collection has **no id at all**. ``/c/{token}`` is its only route, so there
  is nothing to guess and no ``?token=`` to omit. A wrong token and a
  collection that was never created come back byte-identical.

The collection's token is its own secret, deliberately not any report's. Every
row on the page links to ``/r/{that report's token}``, so holding the
collection token implies holding all of them — but not the reverse. Handing
someone one bout must not hand them the roster.

Which bouts appear is not a list anyone maintains. A collection is every
unlisted report in ``data/reports/private/`` that carries a share token, which
is the same set the token index is built from. Two consequences worth stating:
a bout analysed tomorrow shows up without anyone editing a manifest, and a
private report with no token is *skipped* rather than listed without a link —
there is no way to open it, so a row for it would be a dead end that named a
minor for nothing.

The manifest itself (``data/reports/private/collections/{name}.json``) holds
only the token, the title and whose collection it is. It lives one directory
below the report glob for the same structural reason ``keypoints/`` does:
``iter_report_files`` globs ``*.json`` non-recursively, so a manifest written
beside the reports would be parsed as one.
"""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Callable, Dict, List, Optional

from app.sharing import (
    TOKEN_BYTES,
    get_share_token,
    is_private_path,
    is_unlisted_at,
    iter_report_files,
    private_dir,
)

#: Subdirectory of data/reports/private holding collection manifests.
COLLECTIONS_SUBDIR = "collections"

#: Report id suffixes, longest first — ``_continuous_report`` has to be tried
#: before ``_report`` or the stem keeps a stray ``_continuous``.
_ID_SUFFIXES = ("_continuous_report", "_report")

#: What ReportGenerator writes when nobody has told it the fencers' names.
#: These are not names and must not be shown as one, nor matched against the
#: collection's subject — all four 08-28 bouts carry them, and treating them as
#: real would file every one of them as somebody else's bout.
_PLACEHOLDER_NAMES = frozenset({"left fencer", "right fencer", "unknown", "", "-"})

#: Segments of a report id that describe the bout's format rather than name a
#: competition. Matched case-insensitively.
_STRUCTURAL_SEGMENTS = frozenset({
    "pool", "de", "scout", "full", "전체", "a", "b", "c", "d", "e", "f", "g",
})

_RE_DATE8 = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_RE_DATE6 = re.compile(r"^(\d{2})(\d{2})(\d{2})$")
_RE_PISTE = re.compile(r"^piste(\d+)$", re.IGNORECASE)
_RE_SET = re.compile(r"^s(\d+)$", re.IGNORECASE)
_RE_DE = re.compile(r"^de(\d+)$", re.IGNORECASE)
_RE_VS = re.compile(r"vs", re.IGNORECASE)

#: A score the page may print as a score. ``final_score`` is sometimes the
#: literal label "연속 분석" on a report whose scoreboard could not be read, and
#: printing that in the score slot would read as a bout that ended 0-0.
_RE_SCORE = re.compile(r"^\d{1,2}-\d{1,2}$")


# ------------------------------------------------------------------
# Manifests
# ------------------------------------------------------------------


def collections_dir(reports_dir) -> Path:
    """Directory holding collection manifests."""
    return private_dir(reports_dir) / COLLECTIONS_SUBDIR


def generate_collection_token() -> str:
    """Return a fresh URL-safe collection token.

    Same width as a report's, from the same generator — the two are used
    interchangeably in a URL bar and there is no reason for one to be weaker.
    """
    return secrets.token_urlsafe(TOKEN_BYTES)


def iter_collections(reports_dir) -> List[dict]:
    """Load every manifest, skipping anything unreadable or tokenless."""
    directory = collections_dir(reports_dir)
    if not directory.is_dir():
        return []

    found = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not data.get("share_token"):
            continue
        found.append({**data, "name": data.get("name") or path.stem})
    return found


def find_collection_by_token(reports_dir, token: Optional[str]) -> Optional[dict]:
    """Resolve a collection token to its manifest, or None.

    Compared in constant time and only against manifests that actually have a
    token, so an empty or absent token can never match by falsiness.
    """
    if not token:
        return None
    for manifest in iter_collections(reports_dir):
        if secrets.compare_digest(str(manifest["share_token"]), str(token)):
            return manifest
    return None


# ------------------------------------------------------------------
# Reading a bout out of its id and its report
# ------------------------------------------------------------------


def strip_report_suffix(report_id: str) -> str:
    """``260716_de32_s1_piste9_continuous_report`` → ``260716_de32_s1_piste9``."""
    for suffix in _ID_SUFFIXES:
        if report_id.endswith(suffix):
            return report_id[: -len(suffix)]
    return report_id


def _parse_date(segment: str) -> Optional[str]:
    """Return ``YYYY-MM-DD`` for an 8- or 6-digit leading date segment.

    Our own footage is named both ways (``20260828_…`` and ``260716_…``). The
    two-digit year is read as 20xx, which is true of every recording this
    service will ever hold and wrong only for footage from 1926.
    """
    match = _RE_DATE8.match(segment)
    if match:
        year, month, day = match.groups()
    else:
        match = _RE_DATE6.match(segment)
        if not match:
            return None
        year, month, day = match.groups()
        year = f"20{year}"
    if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
        return None
    return f"{year}-{month}-{day}"


def _split_matchup(segment: str) -> Optional[tuple]:
    """``소율vs박소윤`` → ``("소율", "박소윤")``, or None if there is no ``vs``."""
    parts = _RE_VS.split(segment)
    if len(parts) != 2:
        return None
    left, right = parts[0].strip(), parts[1].strip()
    if not left or not right:
        return None
    return left, right


def _is_structural(segment: str) -> bool:
    lowered = segment.lower()
    if lowered in _STRUCTURAL_SEGMENTS:
        return True
    return bool(
        _RE_PISTE.match(segment) or _RE_SET.match(segment) or _RE_DE.match(segment)
    )


def parse_bout_id(report_id: str) -> dict:
    """Pull date, competition, round, piste and filename names out of an id.

    The filename is the only place some of this exists — a report knows its
    ``bout_type`` but not that it was the second period, nor which piste, nor
    that the day's competition was 김창환배. Everything here is best-effort and
    every field is optional: an id that follows no convention yields a row with
    a date it could read and nothing else, rather than a wrong label.

    A segment counts as the competition name when it is neither a format word
    (``pool``, ``de64``, ``piste3``, ``s2``) nor a matchup (anything containing
    ``vs``). That is what separates 김창환배 from ``pool`` in the second slot.
    """
    stem = strip_report_suffix(report_id)
    segments = stem.split("_")

    parsed = {
        "date": None,
        "competition": None,
        "piste": None,
        "round_label": None,
        "set_number": None,
        "is_scout": False,
        "filename_names": None,
    }
    if not segments:
        return parsed

    parsed["date"] = _parse_date(segments[0])
    rest = segments[1:] if parsed["date"] else segments

    round_parts: List[str] = []
    for segment in rest:
        piste = _RE_PISTE.match(segment)
        if piste:
            parsed["piste"] = int(piste.group(1))
            continue

        set_no = _RE_SET.match(segment)
        if set_no:
            parsed["set_number"] = int(set_no.group(1))
            continue

        de_round = _RE_DE.match(segment)
        if de_round:
            round_parts.append(f"{de_round.group(1)}강")
            continue

        if segment.lower() == "scout":
            parsed["is_scout"] = True
            round_parts.append("정찰")
            continue

        if segment.lower() == "pool":
            round_parts.append("예선")
            continue

        matchup = _split_matchup(segment)
        if matchup and parsed["filename_names"] is None:
            parsed["filename_names"] = matchup
            continue

        # A bare letter after "pool" is the pool's own name (pool_a → 예선 A).
        if len(segment) == 1 and segment.isalpha():
            round_parts.append(segment.upper())
            continue

        if not _is_structural(segment) and not matchup and parsed["competition"] is None:
            parsed["competition"] = segment

    if parsed["set_number"]:
        round_parts.append(f"{parsed['set_number']}세트")
    parsed["round_label"] = " ".join(round_parts) or None
    return parsed


def _clean_name(name) -> Optional[str]:
    if not isinstance(name, str):
        return None
    stripped = name.strip()
    if not stripped or stripped.lower() in _PLACEHOLDER_NAMES:
        return None
    return stripped


def fencer_names(report: dict, parsed: dict) -> tuple:
    """``(left, right)`` display names, preferring the report over the filename.

    The report's names are the ones a human confirmed, and on
    ``260815_Pool_Soyun,ParkVsDahee,Jung`` they are also the ones in the right
    order — the filename has the two sides the other way round. But four of the
    08-28 bouts were never named and still carry ``Left Fencer``/``Right
    Fencer``, so the filename is the fallback rather than the ignored copy.
    """
    left = _clean_name((report.get("left_fencer") or {}).get("name"))
    right = _clean_name((report.get("right_fencer") or {}).get("name"))
    from_name = parsed.get("filename_names")
    if from_name:
        left = left or _clean_name(from_name[0])
        right = right or _clean_name(from_name[1])
    return left, right


def _score_fields(summary: dict) -> dict:
    """What the page prints in the score slot, and what it prints beneath it.

    ``official_final_score`` is a human's record of how the bout ended and wins
    the headline when present; ``final_score`` is what the scoreboard read in
    the footage we have and sits underneath, exactly as on the report page. When
    the reader could not produce a score at all, ``final_score`` holds a label
    rather than digits — that case gets no score and says so instead.
    """
    observed = summary.get("final_score")
    official = summary.get("official_final_score")

    observed_is_score = isinstance(observed, str) and bool(_RE_SCORE.match(observed))
    official_is_score = isinstance(official, str) and bool(_RE_SCORE.match(official))

    if official_is_score:
        headline = official
    elif observed_is_score:
        headline = observed
    else:
        headline = None

    return {
        "score": headline,
        "score_is_official": official_is_score,
        "observed_score": observed if observed_is_score else None,
        "score_unread": headline is None or (official_is_score and not observed_is_score),
    }


def build_entry(
    report_id: str,
    report: dict,
    subject: Optional[str],
    zoom_probe: Optional[Callable[[dict], bool]] = None,
) -> dict:
    """One row of the collection page.

    ``zoom_probe`` is injected rather than imported so this stays testable
    without a video tree: whether a bout has a second camera is a fact about
    files on disk, and the server is the layer that already knows how to ask.
    """
    parsed = parse_bout_id(report_id)
    summary = report.get("summary") or {}
    left, right = fencer_names(report, parsed)

    names = [n for n in (left, right) if n]
    is_subject_bout = bool(subject) and any(subject in n for n in names)
    opponent = None
    if subject and is_subject_bout:
        opponent = next((n for n in names if subject not in n), None)

    entry = {
        "report_id": report_id,
        "token": get_share_token(report),
        "date": parsed["date"],
        "competition": parsed["competition"],
        "piste": parsed["piste"],
        "round_label": parsed["round_label"],
        "left_name": left,
        "right_name": right,
        "opponent": opponent,
        "is_subject_bout": is_subject_bout,
        "is_scout": parsed["is_scout"] or not is_subject_bout,
        "bout_type": summary.get("bout_type"),
        "weapon": summary.get("weapon"),
        "duration": summary.get("match_duration"),
        "touches": summary.get("total_touches") or 0,
        "recording_note": summary.get("recording_note") or None,
        "has_zoom": bool(zoom_probe(report)) if zoom_probe else False,
        "exchanges": (report.get("continuous_summary") or {}).get("total_exchanges") or 0,
    }
    entry.update(_score_fields(summary))
    entry["url"] = f"/r/{entry['token']}" if entry["token"] else None
    return entry


def build_entries(
    reports_dir,
    subject: Optional[str] = None,
    zoom_probe: Optional[Callable[[dict], bool]] = None,
) -> List[dict]:
    """Every linkable unlisted bout, newest day first.

    Reports with no share token are skipped: the row would have nowhere to go,
    and a dead row that names a minor is worse than no row. Within a day the
    order is the id's own, which puts DE periods in the order they were fenced.
    """
    reports_dir = Path(reports_dir)
    entries = []
    for path in iter_report_files(reports_dir, include_private=True):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(report, dict):
            continue
        if not is_unlisted_at(report, in_private=is_private_path(reports_dir, path)):
            continue
        if not get_share_token(report):
            continue
        entries.append(build_entry(path.stem, report, subject, zoom_probe))

    entries.sort(key=lambda e: (e["date"] or "", e["report_id"]))
    entries.reverse()
    return entries


def group_by_day(entries: List[dict]) -> List[dict]:
    """Fold the flat list into day sections, preserving order within each.

    Reversing in :func:`build_entries` puts the newest day first but also
    reverses the bouts inside it; the per-day list is flipped back so a DE's
    first period is still listed before its second.
    """
    groups: List[dict] = []
    index: Dict[str, dict] = {}
    for entry in entries:
        key = entry["date"] or ""
        group = index.get(key)
        if group is None:
            group = {
                "date": entry["date"],
                "competition": entry.get("competition"),
                "entries": [],
            }
            index[key] = group
            groups.append(group)
        if group["competition"] is None:
            group["competition"] = entry.get("competition")
        group["entries"].append(entry)

    for group in groups:
        group["entries"].reverse()
    return groups
