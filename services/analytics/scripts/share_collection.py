#!/usr/bin/env python3
"""Admin CLI to create the token-gated index page of a fencer's unlisted bouts.

``share_report.py`` hands out one link per bout. Fourteen of those in a chat
log is not something a coach can use at a competition, so a *collection* is one
link that opens a page listing them all, each row linking to that bout's own
existing token URL.

The collection gets its own token, not any report's. Holding it implies holding
every bout's link, since they are printed on the page — but a report token
opens exactly one bout and never the index. That asymmetry is the point: the
list is the more sensitive artefact, because it says in one place who this
fencer has fenced and when.

There is no id route to the page at all. ``/c/{token}`` is the only way in, so
unlike a report there is not even an id to guess.

    python3 scripts/share_collection.py soyun --title "박소윤 경기 분석" --fencer 박소윤
    python3 scripts/share_collection.py soyun --rotate    # new link, old one dies
    python3 scripts/share_collection.py --list
    python3 scripts/share_collection.py soyun --delete

The manifest is written to ``data/reports/private/collections/{name}.json``,
which is gitignored along with the rest of ``private/`` — it holds the token,
and a token in a public repository is not a token.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

# Import app.* regardless of cwd — an admin runs this from anywhere.
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

from app.collection import (  # noqa: E402
    build_entries,
    collections_dir,
    generate_collection_token,
    iter_collections,
)

REPORTS_DIR = _SERVICE_ROOT / "data" / "reports"
DEFAULT_BASE_URL = "https://analytics.fencingmind.ai"

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_MISSING = 2


def manifest_path(name: str) -> Path:
    return collections_dir(REPORTS_DIR) / f"{name}.json"


def write_manifest(path: Path, manifest: dict) -> None:
    """Write the manifest atomically, readable only by its owner.

    Same care as a report: the file holds a live credential, so it is written
    to a temporary file in the destination directory and renamed over the
    target, and its mode is set before anything is written into it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def collection_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/c/{token}"


def cmd_create(name: str, title: str, fencer: str, base_url: str, rotate: bool) -> int:
    path = manifest_path(name)
    existing = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        if not isinstance(existing, dict):
            existing = {}

    token = existing.get("share_token")
    if not token or rotate:
        token = generate_collection_token()

    manifest = {
        "name": name,
        "title": title or existing.get("title") or name,
        "fencer": fencer or existing.get("fencer") or "",
        "share_token": token,
        "created": existing.get("created") or date.today().isoformat(),
    }
    write_manifest(path, manifest)

    entries = build_entries(REPORTS_DIR, subject=manifest["fencer"] or None)
    linkable = [e for e in entries if e["url"]]

    verb = "rotated" if rotate else ("updated" if existing else "created")
    print(f"{name}: collection {verb}.")
    print(f"  title:  {manifest['title']}")
    print(f"  fencer: {manifest['fencer'] or '(none — no bout is filed as scouting)'}")
    print(f"  bouts:  {len(linkable)} linkable of {len(entries)} unlisted")
    print(f"  URL:    {collection_url(base_url, token)}")
    if rotate:
        print("  WARNING: the previous link no longer works.")
    return EXIT_OK


def cmd_delete(name: str) -> int:
    path = manifest_path(name)
    if not path.is_file():
        print(f"ERROR: no collection named {name!r}", file=sys.stderr)
        return EXIT_MISSING
    path.unlink()
    print(f"{name}: collection deleted. Its link no longer works.")
    print("  The reports themselves are untouched and their own links still work.")
    return EXIT_OK


def cmd_list(base_url: str) -> int:
    manifests = iter_collections(REPORTS_DIR)
    if not manifests:
        print("No collections.")
        return EXIT_OK
    for manifest in manifests:
        print(f"{manifest['name']}: {manifest.get('title', '')}")
        print(f"  fencer: {manifest.get('fencer') or '(none)'}")
        print(f"  URL:    {collection_url(base_url, manifest['share_token'])}")
    return EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", nargs="?", help="short slug for the collection, e.g. soyun")
    parser.add_argument("--title", default=None, help="heading shown on the page")
    parser.add_argument("--fencer", default=None,
                        help="whose collection this is; bouts without this name are "
                             "listed separately as scouting footage")
    parser.add_argument("--rotate", action="store_true", help="issue a new token, killing the existing link")
    parser.add_argument("--delete", action="store_true", help="remove the collection (reports are untouched)")
    parser.add_argument("--list", action="store_true", help="list existing collections and their links")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"default: {DEFAULT_BASE_URL}")
    args = parser.parse_args(argv)

    if args.list:
        return cmd_list(args.base_url)
    if not args.name:
        parser.error("a collection name is required (or --list)")
    if any(sep in args.name for sep in ("/", "\\", os.path.sep)) or args.name in (".", ".."):
        parser.error("name must be a single path-safe segment")
    if args.delete:
        return cmd_delete(args.name)
    return cmd_create(args.name, args.title, args.fencer, args.base_url, args.rotate)


if __name__ == "__main__":
    sys.exit(main())
