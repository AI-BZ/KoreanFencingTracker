"""Unlisted report sharing — secret-link access, YouTube "unlisted" style.

A saved report is public by default: anyone who knows its id can open
``/report/saved/{id}``. Marking one *unlisted* stores two fields under
``meta`` — ``visibility: "unlisted"`` and a ``share_token`` — and flips the
access rule around: the id stops resolving entirely and the token becomes the
only way in.

That inversion is the point. Report ids are derived from the video filename
(``260815_pool_home_vs_away_piste3_continuous_report``), so anyone who can guess the
filename could otherwise read a private bout. Hiding the id behind a token
means guessing the filename buys nothing.

The same rule has to hold for every route that reads a report — the page, the
clip endpoints, the results API, the listing — or the analysis leaks through a
side door while the page itself stays shut.

Unlisted reports also live in a different directory. ``data/reports`` is
committed to a *public* repository, and these reports carry minors' names in
their filenames and their own share token in ``meta``. So sharing a report
moves the file to ``data/reports/private/``, which is gitignored: the access
rule keeps it off the web, and the directory keeps it out of the repo.
"""

import json
import os
import secrets
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

VISIBILITY_PUBLIC = "public"
VISIBILITY_UNLISTED = "unlisted"

#: Gitignored subdirectory of data/reports where unlisted reports live.
PRIVATE_SUBDIR = "private"

#: Bytes of entropy per token. 18 bytes → 24 url-safe characters, which is
#: past the point where guessing is feasible and still fits in a chat message.
TOKEN_BYTES = 18


def generate_share_token() -> str:
    """Return a fresh URL-safe share token."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def get_visibility(report: dict) -> str:
    """Return ``"unlisted"`` or ``"public"`` for a loaded report dict.

    Anything other than an explicit ``"unlisted"`` reads as public, so a
    report written before this feature existed keeps working unchanged.
    """
    meta = report.get("meta") or {}
    return VISIBILITY_UNLISTED if meta.get("visibility") == VISIBILITY_UNLISTED else VISIBILITY_PUBLIC


def is_unlisted(report: dict) -> bool:
    """True when the report may only be reached through its share token."""
    return get_visibility(report) == VISIBILITY_UNLISTED


def get_share_token(report: dict) -> Optional[str]:
    """Return the report's share token, or None if it has none."""
    meta = report.get("meta") or {}
    token = meta.get("share_token")
    return str(token) if token else None


def token_matches(report: dict, token: Optional[str]) -> bool:
    """Constant-time comparison of a supplied token against the report's own."""
    expected = get_share_token(report)
    if not expected or not token:
        return False
    return secrets.compare_digest(str(token), expected)


def is_accessible(report: dict, token: Optional[str] = None) -> bool:
    """Whether a request carrying ``token`` may read this report.

    Public reports ignore the token entirely; unlisted ones require an exact
    match.
    """
    return not is_unlisted(report) or token_matches(report, token)


# ------------------------------------------------------------------
# Mutation helpers (used by scripts/share_report.py)
# ------------------------------------------------------------------


def mark_unlisted(report: dict, rotate: bool = False) -> str:
    """Flip a report to unlisted and return its share token.

    Idempotent: an already-shared report keeps the token it has, so re-running
    the share command hands back the same URL instead of silently breaking
    every link already sent out. ``rotate=True`` is the explicit opt-in to
    invalidate those links.
    """
    meta = report.setdefault("meta", {})
    existing = get_share_token(report)
    if existing and not rotate:
        meta["visibility"] = VISIBILITY_UNLISTED
        return existing

    token = generate_share_token()
    meta["visibility"] = VISIBILITY_UNLISTED
    meta["share_token"] = token
    return token


def make_public(report: dict) -> None:
    """Revoke sharing: drop the token and return the report to public access."""
    meta = report.get("meta")
    if not isinstance(meta, dict):
        return
    meta.pop("visibility", None)
    meta.pop("share_token", None)


def redacted_for_client(report: dict) -> dict:
    """Return a shallow copy with the share token stripped from ``meta``.

    Anything serialised back to a browser or API caller goes through this. The
    token is the credential; echoing it inside the payload it protects would
    let anyone who reached the report once keep reaching it forever, and worse,
    an unauthenticated read of the report would hand out the key to every other
    route the token opens.
    """
    meta = report.get("meta")
    if not isinstance(meta, dict) or "share_token" not in meta:
        return report

    clean_meta = {k: v for k, v in meta.items() if k != "share_token"}
    return {**report, "meta": clean_meta}


# ------------------------------------------------------------------
# Where reports live: data/reports (public) + data/reports/private
# ------------------------------------------------------------------


def private_dir(reports_dir) -> Path:
    """Path to the gitignored directory holding unlisted reports."""
    return Path(reports_dir) / PRIVATE_SUBDIR


def is_safe_report_id(report_id: str) -> bool:
    """Reject ids that could climb out of the reports directory.

    Ids reach us from URL path segments and are pasted straight into a
    filename. Starlette will not match a ``/`` into a single segment, but this
    is the layer that actually opens the file, so it does not rely on that.
    """
    if not report_id or report_id in (".", ".."):
        return False
    if "/" in report_id or "\\" in report_id or "\x00" in report_id:
        return False
    # `(os.path.altsep or "") not in report_id` looks equivalent but is not:
    # altsep is None on POSIX, `or ""` turns that into the empty string, and
    # `"" in s` is True for every string — so every id was rejected on
    # macOS/Linux and every saved report 404'd. Guard the None explicitly.
    if os.path.altsep and os.path.altsep in report_id:
        return False
    return os.path.sep not in report_id


def resolve_report_path(reports_dir, report_id: str) -> Optional[Path]:
    """Find ``{report_id}.json`` in the private dir first, then the public one.

    Private wins on a tie. The two directories should never hold the same stem
    — sharing *moves* the file — but if a stale public copy is ever left
    behind, resolving to it would serve an unlisted report with no gate at all.
    Preferring private means the duplicate fails closed instead.
    """
    if not is_safe_report_id(report_id):
        return None

    reports_dir = Path(reports_dir)
    for candidate in (
        private_dir(reports_dir) / f"{report_id}.json",
        reports_dir / f"{report_id}.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def iter_report_files(reports_dir, include_private: bool = True) -> Iterator[Path]:
    """Yield report JSON paths, optionally including the private directory.

    ``include_private=False`` is for the public listing, and it means "reports
    that are actually public" rather than "files in the public folder". A
    public file whose id also exists in private is skipped: re-running an
    analysis writes its output back to data/reports, so a bout that was shared
    can reappear there, and listing it would republish the very id — fencers'
    names and all — that moving it to private was meant to withhold. The
    private copy is the real one either way; see resolve_report_path.
    """
    reports_dir = Path(reports_dir)
    priv = private_dir(reports_dir)
    private_stems = set()
    if priv.exists():
        private_stems = {p.stem for p in priv.glob("*.json")}

    if reports_dir.exists():
        for path in sorted(reports_dir.glob("*.json")):
            if path.stem not in private_stems:
                yield path

    if include_private and priv.exists():
        yield from sorted(priv.glob("*.json"))


# ------------------------------------------------------------------
# Token → report lookup
# ------------------------------------------------------------------

#: token → report id, plus the directory signature the map was built from.
_token_index: Dict[str, str] = {}
_index_signature: Optional[Tuple[Tuple[str, int], ...]] = None


def _dir_signature(reports_dir: Path) -> Tuple[Tuple[str, int], ...]:
    """Cheap fingerprint of both report directories (names + mtimes).

    Covers the private directory too, or moving a report into it would not
    invalidate the index and the fresh share link would 404.
    """
    entries = []
    for path in iter_report_files(reports_dir, include_private=True):
        try:
            entries.append((str(path), path.stat().st_mtime_ns))
        except OSError:
            continue
    return tuple(sorted(entries))


def build_token_index(reports_dir) -> Dict[str, str]:
    """Return the token → report-id map, rebuilding only when files change.

    Resolving a share link means finding which of ~90 report files carries the
    token. Parsing them all on every request would be wasteful, and stat-ing
    them is not, so the parse happens once per change to either directory.
    """
    global _token_index, _index_signature

    reports_dir = Path(reports_dir)
    if not reports_dir.exists():
        _token_index, _index_signature = {}, ()
        return {}

    signature = _dir_signature(reports_dir)
    if signature == _index_signature:
        return _token_index

    index: Dict[str, str] = {}
    for path in iter_report_files(reports_dir, include_private=True):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        token = get_share_token(data)
        if token and is_unlisted(data):
            index[token] = path.stem

    _token_index, _index_signature = index, signature
    return index


def reset_token_index() -> None:
    """Drop the cached index — for tests that rewrite reports in place."""
    global _token_index, _index_signature
    _token_index, _index_signature = {}, None


def find_report_by_token(reports_dir, token: Optional[str]) -> Optional[Tuple[str, dict]]:
    """Resolve a share token to ``(report_id, report_dict)``, or None.

    The loaded report is re-checked against the token so a stale index entry
    can never hand back a report whose token has since been rotated away.
    """
    if not token:
        return None

    reports_dir = Path(reports_dir)
    report_id = build_token_index(reports_dir).get(token)
    if not report_id:
        return None

    path = resolve_report_path(reports_dir, report_id)
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            report = json.load(fh)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None

    if not token_matches(report, token):
        return None
    return report_id, report
