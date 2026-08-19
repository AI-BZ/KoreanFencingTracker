#!/usr/bin/env python3
"""Admin CLI to share a saved report by secret link (YouTube "unlisted" style).

Reports are public by default: anyone who knows the id can open
``/report/saved/{id}``. Marking one *unlisted* inverts that — the id stops
resolving entirely and the share token becomes the only way in. That matters
because report ids are derived from the video filename
(``260815_pool_home_vs_away_piste3_continuous_report``), so a guessable filename would
otherwise be a guessable private bout. Behind a token, guessing buys nothing.

Sharing also **moves the file**. ``data/reports/`` is committed to a *public*
GitHub repository, and the reports we filmed ourselves carry minors' names in
their filenames and their own ``share_token`` inside ``meta``. Committing one
would publish both the identity and the key that is supposed to guard it — the
access rule would still be enforced by the server while the token sat in plain
sight on github.com. So an unlisted report lives in ``data/reports/private/``,
which is gitignored: the access rule keeps it off the web, the directory keeps
it out of the repo, and neither alone is enough.

Revoking moves the file back into the tracked directory, which is the dangerous
direction — a filename carrying a fencer's name becomes committable again — so
``--revoke`` prints a warning saying exactly that.

    python3 scripts/share_report.py <report_id>            # share (idempotent)
    python3 scripts/share_report.py <report_id> --rotate    # new token, old links die
    python3 scripts/share_report.py <report_id> --revoke    # back to public
    python3 scripts/share_report.py --list                  # what is shared right now

The report is found in either directory, so an id works no matter where the file
currently sits. All token and meta-field logic lives in ``app/sharing.py``; this
file only loads, calls, writes back, and moves.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

# Import app.sharing regardless of cwd — an admin runs this from anywhere.
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from app.sharing import (  # noqa: E402
    build_token_index,
    get_share_token,
    is_unlisted,
    make_public,
    mark_unlisted,
    private_dir,
    resolve_report_path,
)

#: Resolved from the script's own location, not the cwd, for the same reason.
REPORTS_DIR = _SERVICE_ROOT / "data" / "reports"
PRIVATE_DIR = private_dir(REPORTS_DIR)
DEFAULT_BASE_URL = "https://analytics.fencingmind.ai"

EXIT_OK = 0
EXIT_NOT_FOUND = 2


def normalize_report_id(report_id: str) -> str:
    """Strip a typed-out ``.json`` so both spellings of an id work."""
    return report_id[:-5] if report_id.endswith(".json") else report_id


def load_report(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_report(path: Path, report: dict) -> None:
    """Write the report to ``path`` atomically, creating its directory.

    A share flip rewrites a file that can be several hundred KB. Writing in
    place would leave a truncated, unparseable report if the process died
    mid-write, so the new content lands in a sibling temp file first (same
    directory as the *destination*, so ``os.replace`` is a same-filesystem
    rename) and only then takes over the name.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_name, path)
    except BaseException:
        # Never leave a stray dot-file behind; both report dirs are scanned by
        # the server's token index and by --list.
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def save_report_to(src: Path, dest: Path, report: dict) -> None:
    """Persist ``report`` at ``dest``, removing ``src`` if it is elsewhere.

    Write first, delete second. The reverse order — unlink then write — has a
    window where a crash leaves no copy of the report at all; this order's worst
    case is a duplicate, which is recoverable and which ``resolve_report_path``
    already fails closed on (private wins, so a leftover public copy is never
    served ungated).
    """
    write_report(dest, report)
    if src.resolve() != dest.resolve():
        os.unlink(src)


def share_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/r/{token}"


def describe_location(path: Path) -> str:
    """Human label for which of the two directories a report sits in."""
    return "private" if path.parent.resolve() == PRIVATE_DIR.resolve() else "PUBLIC (git-tracked)"


def cmd_share(path: Path, base_url: str, rotate: bool) -> int:
    report = load_report(path)
    was_shared = is_unlisted(report) and get_share_token(report) is not None
    old_token = get_share_token(report)

    token = mark_unlisted(report, rotate=rotate)
    dest = PRIVATE_DIR / path.name
    moved = path.resolve() != dest.resolve()
    save_report_to(path, dest, report)

    if rotate and not was_shared:
        # --rotate on a public report has nothing to invalidate; say so rather
        # than let the operator believe old links were killed.
        print(f"{dest.stem}: was public, now shared with a fresh token (nothing to rotate).")
    elif rotate:
        print(f"{dest.stem}: token rotated — any link containing {old_token} is now dead.")
    elif was_shared:
        print(f"{dest.stem}: already shared; token unchanged, existing links still work.")
    else:
        print(f"{dest.stem}: now unlisted — the report id no longer resolves.")

    if moved:
        print(f"  moved out of the git-tracked directory → {dest}")
    else:
        print(f"  already private → {dest}")

    print(share_url(base_url, token))
    return EXIT_OK


def cmd_revoke(path: Path) -> int:
    report = load_report(path)
    dest = REPORTS_DIR / path.name
    already_public = not is_unlisted(report) and get_share_token(report) is None

    if already_public and path.resolve() == dest.resolve():
        print(f"{dest.stem}: already public and already in {REPORTS_DIR}, nothing to do.")
        return EXIT_OK

    make_public(report)
    moved = path.resolve() != dest.resolve()
    save_report_to(path, dest, report)

    if already_public:
        print(f"{dest.stem}: was already public; file moved back to the tracked directory.")
    else:
        print(f"{dest.stem}: revoked — public again, every share link is dead.")

    if moved:
        print("")
        print("  " + "!" * 72)
        print("  !! WARNING: this file is now in a directory that is COMMITTED to a")
        print("  !! PUBLIC GitHub repository.")
        print(f"  !!   {dest}")
        print("  !!")
        print("  !! The filename itself may identify a fencer, and these bouts involve")
        print("  !! minors. Committing it publishes that name to anyone on the internet,")
        print("  !! permanently and irreversibly (git history keeps it after deletion).")
        print("  !!")
        print("  !! Confirm this is intended BEFORE you commit. If it is not, re-share")
        print("  !! the report to move it back:")
        print(f"  !!   python3 scripts/share_report.py {dest.stem}")
        print("  " + "!" * 72)
        print("")

    return EXIT_OK


def cmd_list(base_url: str) -> int:
    # build_token_index already scans BOTH directories and applies the same
    # unlisted/token rules the server uses, so listing cannot drift from it.
    index = build_token_index(REPORTS_DIR)
    if not index:
        print("No reports are currently shared.")
        return EXIT_OK

    print(f"{len(index)} shared report(s):")
    exposed = 0
    for token, report_id in sorted(index.items(), key=lambda kv: kv[1]):
        path = resolve_report_path(REPORTS_DIR, report_id)
        if path is None:
            # Index entry with no file behind it — only reachable if the file
            # vanished between the scan and now. Say so rather than crash.
            location = "MISSING"
        else:
            location = describe_location(path)
            if path.parent.resolve() != PRIVATE_DIR.resolve():
                exposed += 1
        print(f"  {report_id}  [{location}]\n    {share_url(base_url, token)}")

    if exposed:
        print("")
        print(f"WARNING: {exposed} shared report(s) sit in the git-tracked directory.")
        print("Their filenames and share tokens will be published if committed.")
        print("Re-run the share command on each to move it into data/reports/private/.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "report_id",
        nargs="?",
        help="report JSON stem, in data/reports/ or data/reports/private/ (.json optional)",
    )
    parser.add_argument("--revoke", action="store_true", help="return the report to public access")
    parser.add_argument("--rotate", action="store_true", help="issue a new token, killing existing links")
    parser.add_argument("--list", action="store_true", help="list currently-shared reports and where they live")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"default: {DEFAULT_BASE_URL}")
    args = parser.parse_args(argv)

    if args.list:
        return cmd_list(args.base_url)
    if not args.report_id:
        parser.error("a report_id is required unless --list is given")
    if args.revoke and args.rotate:
        parser.error("--revoke and --rotate are mutually exclusive")

    report_id = normalize_report_id(args.report_id)
    path = resolve_report_path(REPORTS_DIR, report_id)
    if path is None:
        # Exit 2, never create: a typo must not conjure an empty report.
        print(
            f"error: no such report: {report_id} (looked in {PRIVATE_DIR} and {REPORTS_DIR})",
            file=sys.stderr,
        )
        return EXIT_NOT_FOUND

    if args.revoke:
        return cmd_revoke(path)
    return cmd_share(path, args.base_url, rotate=args.rotate)


if __name__ == "__main__":
    sys.exit(main())
