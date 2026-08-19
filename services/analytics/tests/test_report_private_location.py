"""Living in data/reports/private is itself the access rule.

test_report_sharing.py covers the rule as it was: ``meta.visibility`` decides,
and the private directory is where a report is *moved* once someone runs
scripts/share_report.py. That left a window. A freshly generated report lands in
private with the fencers' names in its id and nothing in ``meta`` — so until a
human remembered to run the share command, anyone who guessed the filename could
read a minor's bout. Protection that depends on a manual step is protection that
eventually is not there.

So location now decides too: a report resolved from under private is unlisted
whatever ``meta`` says. These tests pin that down from both ends — the reports
that must close (private, unmarked) and the ones that must not change (the ~90
public reports with no visibility field, which have always been readable).
"""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app import sharing
from app.server import app, _BASE_DIR

from tests.test_report_sharing import _minimal_report, _get_page


REPORTS_DIR = _BASE_DIR / "data" / "reports"

#: Private, carries a token, but no `visibility` — exactly what the generator
#: writes before anyone shares it.
UNMARKED_ID = "_pytest_private_unmarked_continuous_report"
#: Private with neither visibility nor token: nothing can open it.
TOKENLESS_ID = "_pytest_private_tokenless_continuous_report"
#: Public dir, no visibility — the shape of every ordinary saved report.
PLAIN_PUBLIC_ID = "_pytest_public_plain_continuous_report"


def _write(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report), encoding="utf-8")


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def located_reports():
    """Three reports whose ``meta`` says nothing about visibility.

    Written next to the real ones because the server resolves data/reports from
    its own base dir, so tmp_path cannot stand in for the HTTP tests. Every id
    is prefixed, so a leaked one is obvious in a listing.
    """
    unmarked_path = sharing.private_dir(REPORTS_DIR) / f"{UNMARKED_ID}.json"
    tokenless_path = sharing.private_dir(REPORTS_DIR) / f"{TOKENLESS_ID}.json"
    public_path = REPORTS_DIR / f"{PLAIN_PUBLIC_ID}.json"

    token = sharing.generate_share_token()
    unmarked = _minimal_report()
    unmarked["meta"]["share_token"] = token
    assert "visibility" not in unmarked["meta"]

    _write(unmarked_path, unmarked)
    _write(tokenless_path, _minimal_report())
    _write(public_path, _minimal_report())

    sharing.reset_token_index()
    try:
        yield token
    finally:
        unmarked_path.unlink(missing_ok=True)
        tokenless_path.unlink(missing_ok=True)
        public_path.unlink(missing_ok=True)
        for report_id in (UNMARKED_ID, TOKENLESS_ID, PLAIN_PUBLIC_ID):
            shutil.rmtree(_BASE_DIR / "data" / "clips" / "overlay" / report_id, ignore_errors=True)
        sharing.reset_token_index()


# ------------------------------------------------------------------
# The regression: private + unmarked is closed
# ------------------------------------------------------------------


def test_unmarked_private_report_is_404_by_id(client, located_reports):
    """The gap this file exists for: generated into private, never shared.

    Before location counted, `meta.visibility` was absent so `is_accessible`
    said public and the page rendered a named minor's bout to anyone who
    guessed the filename.
    """
    resp = client.get(f"/report/saved/{UNMARKED_ID}")

    assert resp.status_code == 404


def test_unmarked_private_report_opens_with_its_token(client, located_reports):
    """Closing it by location must not orphan it — the token still works."""
    token = located_reports
    resp = _get_page(client, f"/report/saved/{UNMARKED_ID}?token={token}")

    assert resp.status_code == 200


def test_unmarked_private_report_rejects_a_wrong_token_identically(client, located_reports):
    """A wrong token and a nonexistent id must be indistinguishable.

    If they differed, probing ids would confirm which private bouts exist —
    which is the fencers' names, since the id is the filename.
    """
    wrong = client.get(f"/report/saved/{UNMARKED_ID}?token=wrong")
    missing = client.get(f"/report/saved/{UNMARKED_ID}_nope")

    assert wrong.status_code == 404
    assert wrong.json()["detail"] == f"Report not found: {UNMARKED_ID}"
    assert missing.json()["detail"] == f"Report not found: {UNMARKED_ID}_nope"


def test_private_report_without_a_token_cannot_be_opened_at_all(client, located_reports):
    """Fail closed: no token in the file means no token can match it.

    Being unreachable is the right answer for a report we cannot prove is
    shareable — better a report nobody can read than a minor's bout everybody
    can.
    """
    assert client.get(f"/report/saved/{TOKENLESS_ID}").status_code == 404
    assert client.get(f"/report/saved/{TOKENLESS_ID}?token=anything").status_code == 404


def test_public_report_without_visibility_still_opens(client, located_reports):
    """No regression for the ~90 saved reports that carry no meta.visibility."""
    resp = _get_page(client, f"/report/saved/{PLAIN_PUBLIC_ID}")

    assert resp.status_code == 200


# ------------------------------------------------------------------
# The token index has to agree with the gate
# ------------------------------------------------------------------


def test_share_link_resolves_for_an_unmarked_private_report(client, located_reports):
    """The two rules must agree, or the report is stranded.

    build_token_index used to index only reports whose meta said "unlisted". An
    unmarked private report would then be unreachable by id (right) *and* by the
    token printed in its own file (wrong) — reachable by nothing at all.
    """
    token = located_reports
    resp = _get_page(client, f"/r/{token}")

    assert resp.status_code == 200


def test_token_index_covers_a_private_report_with_no_visibility(tmp_path):
    sharing.reset_token_index()
    report = _minimal_report()
    report["meta"]["share_token"] = "tok_location_only"
    _write(sharing.private_dir(tmp_path) / "hidden.json", report)

    index = sharing.build_token_index(tmp_path)

    assert index.get("tok_location_only") == "hidden"
    sharing.reset_token_index()


def test_token_index_ignores_an_unmarked_public_report(tmp_path):
    """A public report is not made unlisted by happening to carry a token."""
    sharing.reset_token_index()
    report = _minimal_report()
    report["meta"]["share_token"] = "tok_public_only"
    _write(tmp_path / "open.json", report)

    assert sharing.build_token_index(tmp_path) == {}
    sharing.reset_token_index()


# ------------------------------------------------------------------
# is_private_path
# ------------------------------------------------------------------


def test_is_private_path_accepts_a_file_in_private(tmp_path):
    assert sharing.is_private_path(tmp_path, sharing.private_dir(tmp_path) / "r.json")


def test_is_private_path_rejects_a_file_in_the_public_dir(tmp_path):
    assert not sharing.is_private_path(tmp_path, tmp_path / "r.json")


def test_is_private_path_rejects_a_traversal_that_only_looks_private(tmp_path):
    """`private/../r.json` is in the public dir; a string test would say private.

    Getting this backwards is not cosmetic — it would hand the protection of the
    private directory to a file sitting in the committed public one.
    """
    looks_private = sharing.private_dir(tmp_path) / ".." / "r.json"

    assert not sharing.is_private_path(tmp_path, looks_private)


def test_is_private_path_does_not_raise_on_a_path_that_does_not_exist(tmp_path):
    """Callers ask about files about to be written, and about junk paths."""
    assert sharing.is_private_path(tmp_path, sharing.private_dir(tmp_path) / "never_written.json")
    assert not sharing.is_private_path(tmp_path, tmp_path / "no" / "such" / "r.json")


# ------------------------------------------------------------------
# Predicates
# ------------------------------------------------------------------


def test_is_unlisted_at_is_true_from_location_alone():
    assert sharing.is_unlisted_at(_minimal_report(), in_private=True)


def test_is_unlisted_at_still_honours_meta_outside_private():
    marked = _minimal_report()
    sharing.mark_unlisted(marked)

    assert sharing.is_unlisted_at(marked, in_private=False)
    assert not sharing.is_unlisted_at(_minimal_report(), in_private=False)


def test_is_accessible_at_needs_a_token_in_private():
    report = _minimal_report()
    report["meta"]["share_token"] = "tok"

    assert not sharing.is_accessible_at(report, None, in_private=True)
    assert not sharing.is_accessible_at(report, "nope", in_private=True)
    assert sharing.is_accessible_at(report, "tok", in_private=True)
    assert sharing.is_accessible_at(report, None, in_private=False)


def test_is_accessible_stays_meta_only():
    """Kept unchanged deliberately — other callers and tests still use it."""
    assert sharing.is_accessible(_minimal_report(), None)


# ------------------------------------------------------------------
# Every gated route, not just the page
# ------------------------------------------------------------------


#: (method, url template, 404 detail template). One per gate that can be
#: reached by id; a side door left open is as bad as the front one.
GATED_ROUTES = [
    ("get", "/report/saved/{id}", "Report not found: {id}"),
    ("get", "/api/analytics/results/{id}", "Job not found: {id}"),
    ("get", "/api/analytics/report/{id}", "Job not found: {id}"),
    ("get", "/api/analytics/jobs/{id}", "Job not found: {id}"),
    ("get", "/api/analytics/keypoints/{id}", "Report not found: {id}"),
    ("get", "/api/analytics/clips/{id}/touch/1", "Report not found: {id}"),
    ("post", "/api/analytics/clips/{id}/touch/1/start", "Report not found: {id}"),
    ("get", "/api/analytics/clips/{id}/touch/1/status", "Report not found: {id}"),
    ("post", "/api/analytics/clips/{id}/generate", "Report not found: {id}"),
]


@pytest.mark.parametrize("method,route,detail", GATED_ROUTES)
def test_every_gated_route_hides_an_unmarked_private_report(
    client, located_reports, method, route, detail,
):
    resp = getattr(client, method)(route.format(id=UNMARKED_ID))

    assert resp.status_code == 404
    assert resp.json()["detail"] == detail.format(id=UNMARKED_ID)


@pytest.mark.parametrize("method,route,detail", GATED_ROUTES)
def test_every_gated_route_gives_a_wrong_token_the_same_404(
    client, located_reports, method, route, detail,
):
    resp = getattr(client, method)(route.format(id=UNMARKED_ID) + "?token=wrong")

    assert resp.status_code == 404
    assert resp.json()["detail"] == detail.format(id=UNMARKED_ID)


def test_clips_status_hides_an_unmarked_private_report(client, located_reports):
    """Listing cached clips confirms the report exists, so it gates too."""
    resp = client.get(f"/api/analytics/clips/{UNMARKED_ID}/status")

    assert resp.status_code == 404
    assert resp.json()["detail"] == f"Report not found: {UNMARKED_ID}"


def test_clips_status_still_answers_for_a_report_that_does_not_exist(client):
    """Deliberate carve-out: pollers run before the report is written.

    An absent report keeps its old answer — an empty listing, not a 404 — and
    the location rule must not have quietly turned that into an error.
    """
    resp = client.get("/api/analytics/clips/_pytest_no_such_report_at_all/status")

    assert resp.status_code == 200
    assert resp.json()["cached"] == {"touch": [], "exchange": []}
