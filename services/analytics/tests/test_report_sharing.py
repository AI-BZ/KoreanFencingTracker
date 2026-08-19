"""Unlisted report sharing + own-footage video resolution.

Two features share this file because they meet on the same routes: a report
filmed by us plays from /videos/own, and an unlisted one is reachable only
through /r/{token}. The access matrix at the bottom is the part that matters —
every route that can read a report has to answer the same way, or the analysis
leaks through whichever one was forgotten.
"""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app import sharing
from app import server
from app.server import app, _BASE_DIR, _own_video_filename


REPORTS_DIR = _BASE_DIR / "data" / "reports"

PUBLIC_ID = "_pytest_share_public_continuous_report"
UNLISTED_ID = "_pytest_share_unlisted_continuous_report"


def _fencer(name: str) -> dict:
    return {
        "name": name,
        "club": "",
        "handedness": None,
        "total_touches_scored": 0,
        "total_touches_conceded": 0,
        "most_common_action": None,
        "most_common_action_pct": 0,
        "action_distribution": [],
    }


def _minimal_report() -> dict:
    """Smallest report the template actually renders, with no touches.

    Keep this renderable: if it goes stale the page tests start failing on a
    template error rather than on the access rule they exist to check.
    """
    return {
        "summary": {
            "final_score": "5-3",
            "total_touches": 0,
            "match_duration": "00:30",
            "total_frames_analyzed": 900,
            "analysis_time_sec": 1.0,
            "weapon": "foil",
            "bout_type": "pool",
            "gender": None,
            "age_group": None,
        },
        "touches": [],
        "exchanges": [],
        "continuous_summary": {
            "total_exchanges": 0,
            "scoring_exchanges": 0,
            "non_scoring_exchanges": 0,
            "type_distribution": {},
            "fencer_stats": {
                "left": {"attacks": 0, "defenses": 0},
                "right": {"attacks": 0, "defenses": 0},
            },
        },
        "left_fencer": _fencer("Left Fencer"),
        "right_fencer": _fencer("Right Fencer"),
        "insights": [],
        "warnings": [],
        "meta": {"phase": 6, "fps": 30.0, "analysis_mode": "continuous_only"},
    }


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def shared_reports():
    """Write one public and one unlisted report, yield (token), then clean up.

    The server resolves data/reports/ from its own base dir rather than a
    setting, so these have to be real files next to the real reports. Both ids
    are prefixed so a leaked one is obvious.

    The unlisted one goes in data/reports/private/, mirroring where
    share_report.py actually puts it — the repo is public, so a shared report
    must not sit in the committed directory.
    """
    public_path = REPORTS_DIR / f"{PUBLIC_ID}.json"
    private_path = sharing.private_dir(REPORTS_DIR) / f"{UNLISTED_ID}.json"
    private_path.parent.mkdir(parents=True, exist_ok=True)

    public_path.write_text(json.dumps(_minimal_report()), encoding="utf-8")

    unlisted = _minimal_report()
    token = sharing.mark_unlisted(unlisted)
    private_path.write_text(json.dumps(unlisted), encoding="utf-8")

    sharing.reset_token_index()
    try:
        yield token
    finally:
        public_path.unlink(missing_ok=True)
        private_path.unlink(missing_ok=True)
        shutil.rmtree(_BASE_DIR / "data" / "clips" / "overlay" / UNLISTED_ID, ignore_errors=True)
        shutil.rmtree(_BASE_DIR / "data" / "clips" / "overlay" / PUBLIC_ID, ignore_errors=True)
        sharing.reset_token_index()


def _get_page(client, url):
    """Request a template page, surfacing a render error instead of hiding it.

    test_integration skips on 500 for the Jinja2/Py3.14 cache bug, but the
    server sets cache_size=0 on 3.14 precisely so these render — so a 500 here
    is a real break (a stale fixture, usually) and must not pass as a skip.
    """
    resp = client.get(url)
    assert resp.status_code != 500, f"{url} failed to render:\n{resp.text[:2000]}"
    return resp


# ------------------------------------------------------------------
# sharing module — visibility and tokens
# ------------------------------------------------------------------


def test_report_without_meta_visibility_is_public():
    assert sharing.get_visibility(_minimal_report()) == sharing.VISIBILITY_PUBLIC
    assert not sharing.is_unlisted(_minimal_report())


def test_report_with_no_meta_at_all_is_public():
    assert not sharing.is_unlisted({})


def test_mark_unlisted_sets_visibility_and_token():
    report = _minimal_report()
    token = sharing.mark_unlisted(report)

    assert report["meta"]["visibility"] == sharing.VISIBILITY_UNLISTED
    assert report["meta"]["share_token"] == token
    assert sharing.is_unlisted(report)
    assert len(token) >= 20


def test_tokens_are_unique():
    tokens = {sharing.generate_share_token() for _ in range(50)}
    assert len(tokens) == 50


def test_mark_unlisted_is_idempotent():
    """Re-sharing must not silently invalidate links already handed out."""
    report = _minimal_report()
    first = sharing.mark_unlisted(report)
    second = sharing.mark_unlisted(report)

    assert first == second


def test_rotate_replaces_the_token():
    report = _minimal_report()
    first = sharing.mark_unlisted(report)
    rotated = sharing.mark_unlisted(report, rotate=True)

    assert rotated != first
    assert sharing.get_share_token(report) == rotated
    assert not sharing.token_matches(report, first)


def test_make_public_clears_both_fields():
    report = _minimal_report()
    sharing.mark_unlisted(report)
    sharing.make_public(report)

    assert not sharing.is_unlisted(report)
    assert sharing.get_share_token(report) is None
    assert "visibility" not in report["meta"]


@pytest.mark.parametrize("bad", [None, "", "wrong-token", "  "])
def test_token_matches_rejects_bad_tokens(bad):
    report = _minimal_report()
    sharing.mark_unlisted(report)
    assert not sharing.token_matches(report, bad)


def test_public_report_is_accessible_without_a_token():
    assert sharing.is_accessible(_minimal_report(), None)
    assert sharing.is_accessible(_minimal_report(), "irrelevant")


def test_unlisted_report_needs_its_token():
    report = _minimal_report()
    token = sharing.mark_unlisted(report)

    assert not sharing.is_accessible(report, None)
    assert not sharing.is_accessible(report, "nope")
    assert sharing.is_accessible(report, token)


# ------------------------------------------------------------------
# sharing module — token → report lookup
# ------------------------------------------------------------------


def test_find_report_by_token_resolves_the_right_file(tmp_path):
    sharing.reset_token_index()
    report = _minimal_report()
    token = sharing.mark_unlisted(report)
    (tmp_path / "wanted.json").write_text(json.dumps(report), encoding="utf-8")
    (tmp_path / "other.json").write_text(json.dumps(_minimal_report()), encoding="utf-8")

    found = sharing.find_report_by_token(tmp_path, token)

    assert found is not None
    assert found[0] == "wanted"
    sharing.reset_token_index()


@pytest.mark.parametrize("bad", [None, "", "not-a-real-token"])
def test_find_report_by_token_returns_none_for_bad_tokens(tmp_path, bad):
    sharing.reset_token_index()
    report = _minimal_report()
    sharing.mark_unlisted(report)
    (tmp_path / "r.json").write_text(json.dumps(report), encoding="utf-8")

    assert sharing.find_report_by_token(tmp_path, bad) is None
    sharing.reset_token_index()


def test_index_notices_a_rotated_token(tmp_path):
    """A stale cache must not keep a revoked link alive."""
    sharing.reset_token_index()
    path = tmp_path / "r.json"
    report = _minimal_report()
    old = sharing.mark_unlisted(report)
    path.write_text(json.dumps(report), encoding="utf-8")

    assert sharing.find_report_by_token(tmp_path, old) is not None

    new = sharing.mark_unlisted(report, rotate=True)
    path.write_text(json.dumps(report), encoding="utf-8")

    assert sharing.find_report_by_token(tmp_path, old) is None
    assert sharing.find_report_by_token(tmp_path, new) is not None
    sharing.reset_token_index()


def test_a_public_report_carrying_a_token_is_not_indexed(tmp_path):
    """Visibility, not the presence of a token, decides indexing."""
    sharing.reset_token_index()
    report = _minimal_report()
    token = sharing.mark_unlisted(report)
    report["meta"].pop("visibility")
    (tmp_path / "r.json").write_text(json.dumps(report), encoding="utf-8")

    assert sharing.find_report_by_token(tmp_path, token) is None
    sharing.reset_token_index()


def test_index_skips_unparseable_files(tmp_path):
    sharing.reset_token_index()
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    report = _minimal_report()
    token = sharing.mark_unlisted(report)
    (tmp_path / "good.json").write_text(json.dumps(report), encoding="utf-8")

    found = sharing.find_report_by_token(tmp_path, token)

    assert found is not None and found[0] == "good"
    sharing.reset_token_index()


# ------------------------------------------------------------------
# Own-footage video resolution
# ------------------------------------------------------------------


@pytest.fixture
def fake_own_dir(tmp_path, monkeypatch):
    """Redirect the own-video directory into tmp_path.

    The real data/raw/own holds multi-gigabyte transcodes that take minutes to
    regenerate and are shared with other work in this tree, so the tests never
    write there — not even a probe file they clean up afterwards.
    """
    own = tmp_path / "own"
    own.mkdir()
    monkeypatch.setattr(server, "_own_video_dir", own)
    return own


def test_own_video_resolves_to_the_own_prefix(fake_own_dir):
    probe = fake_own_dir / "clip.mp4"
    probe.write_bytes(b"x")

    assert _own_video_filename(str(probe)) == "own/clip.mp4"


def test_own_video_ignores_paths_outside_own(tmp_path):
    outside = tmp_path / "usaf_broadcast.mp4"
    outside.write_bytes(b"x")
    assert _own_video_filename(str(outside)) is None


def test_own_video_ignores_a_missing_file(fake_own_dir):
    assert _own_video_filename(str(fake_own_dir / "absent.mp4")) is None


def test_own_video_ignores_empty_path():
    assert _own_video_filename("") is None
    assert _own_video_filename(None) is None


def test_own_video_does_not_accept_traversal_out_of_own(fake_own_dir):
    """A ../ segment must not read as "inside own" just because it starts there."""
    escaped = str(fake_own_dir / ".." / "usaf_broadcast.mp4")
    assert _own_video_filename(escaped) is None


def test_own_videos_mount_is_registered_before_the_gated_one():
    mounts = [r.path for r in app.routes if getattr(r, "name", "") in ("videos_own", "videos")]
    assert "/videos/own" in mounts
    if "/videos" in mounts:
        assert mounts.index("/videos/own") < mounts.index("/videos")


# ------------------------------------------------------------------
# Access matrix — every route that can read a report
# ------------------------------------------------------------------


def test_public_report_opens_by_id(client, shared_reports):
    assert _get_page(client, f"/report/saved/{PUBLIC_ID}").status_code == 200


def test_unlisted_report_is_404_by_id(client, shared_reports):
    resp = client.get(f"/report/saved/{UNLISTED_ID}")
    assert resp.status_code == 404


def test_unlisted_report_404_detail_is_the_same_as_a_missing_one(client, shared_reports):
    """A wrong id and a hidden id must be indistinguishable to a prober."""
    hidden = client.get(f"/report/saved/{UNLISTED_ID}").json()["detail"]
    missing = client.get(f"/report/saved/{UNLISTED_ID}_nope").json()["detail"]

    assert hidden.replace(UNLISTED_ID, "X") == missing.replace(f"{UNLISTED_ID}_nope", "X")


def test_unlisted_report_opens_by_id_with_its_token(client, shared_reports):
    token = shared_reports
    assert _get_page(client, f"/report/saved/{UNLISTED_ID}?token={token}").status_code == 200


def test_unlisted_report_opens_by_share_url(client, shared_reports):
    token = shared_reports
    assert _get_page(client, f"/r/{token}").status_code == 200


def test_share_url_rejects_a_wrong_token(client, shared_reports):
    assert client.get("/r/definitely-not-a-token").status_code == 404


def test_share_page_carries_the_token_into_the_page(client, shared_reports):
    token = shared_reports
    resp = _get_page(client, f"/r/{token}")
    assert token in resp.text


def test_public_report_page_carries_no_token(client, shared_reports):
    resp = _get_page(client, f"/report/saved/{PUBLIC_ID}")
    assert "CLIP_TOKEN = null" in resp.text


def test_report_route_disk_fallback_hides_unlisted(client, shared_reports):
    """/report/{id} falls back to disk, so it is a second door on the same file."""
    token = shared_reports
    assert client.get(f"/report/{UNLISTED_ID}").status_code == 404
    assert _get_page(client, f"/report/{UNLISTED_ID}?token={token}").status_code == 200


def test_reports_listing_omits_unlisted(client, shared_reports):
    ids = [r["video_id"] for r in client.get("/reports").json()["reports"]]

    assert PUBLIC_ID in ids
    assert UNLISTED_ID not in ids


# ---- clip sub-resources ----


def test_clip_status_open_for_public(client, shared_reports):
    resp = client.get(f"/api/analytics/clips/{PUBLIC_ID}/status")
    assert resp.status_code == 200


def test_clip_status_hidden_for_unlisted(client, shared_reports):
    assert client.get(f"/api/analytics/clips/{UNLISTED_ID}/status").status_code == 404
    assert client.get(f"/api/analytics/clips/{UNLISTED_ID}/status?token=wrong").status_code == 404


def test_clip_status_open_with_token(client, shared_reports):
    token = shared_reports
    resp = client.get(f"/api/analytics/clips/{UNLISTED_ID}/status?token={token}")

    assert resp.status_code == 200
    assert resp.json()["cached"] == {"touch": [], "exchange": []}


def test_clip_status_still_empty_for_a_report_that_does_not_exist(client):
    """Polling before the report is written must not start 404-ing."""
    resp = client.get("/api/analytics/clips/_pytest_no_such_report/status")

    assert resp.status_code == 200
    assert resp.json()["cached"] == {"touch": [], "exchange": []}


def test_clip_fetch_hidden_for_unlisted(client, shared_reports):
    resp = client.get(f"/api/analytics/clips/{UNLISTED_ID}/touch/1")

    assert resp.status_code == 404
    assert resp.json()["detail"] == f"Report not found: {UNLISTED_ID}"


def test_clip_fetch_with_token_gets_past_the_gate(client, shared_reports):
    """The fixture report has no touches, so a valid token fails *later*."""
    token = shared_reports
    resp = client.get(f"/api/analytics/clips/{UNLISTED_ID}/touch/1?token={token}")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Touch #1 not found"


def test_clip_generate_hidden_for_unlisted(client, shared_reports):
    resp = client.post(f"/api/analytics/clips/{UNLISTED_ID}/generate")

    assert resp.status_code == 404
    assert resp.json()["detail"] == f"Report not found: {UNLISTED_ID}"


# ------------------------------------------------------------------
# Private directory: data/reports/private
# ------------------------------------------------------------------


@pytest.mark.parametrize("report_id", [
    "0mVCrw0clFk_report",
    "260815_pool_home_vs_away_piste3_continuous_report",
    "a_b-c.d,e",
])
def test_ordinary_report_ids_are_accepted(report_id):
    """Regression: `(os.path.altsep or "") not in id` is False for every id.

    altsep is None on POSIX, `or ""` makes it the empty string, and `"" in s`
    is always True — so that spelling rejected every id and every saved report
    404'd. The bug is invisible unless a real id is asserted to pass.
    """
    assert sharing.is_safe_report_id(report_id)


@pytest.mark.parametrize("report_id", [
    "", ".", "..", "../secret", "/etc/passwd", "a/b", "a\\b", "a\x00b",
])
def test_unsafe_report_ids_are_rejected(report_id):
    assert not sharing.is_safe_report_id(report_id)


def test_resolve_finds_a_report_in_the_public_dir(tmp_path):
    (tmp_path / "r.json").write_text(json.dumps(_minimal_report()), encoding="utf-8")
    assert sharing.resolve_report_path(tmp_path, "r") == tmp_path / "r.json"


def test_resolve_finds_a_report_in_the_private_dir(tmp_path):
    priv = sharing.private_dir(tmp_path)
    priv.mkdir()
    (priv / "r.json").write_text(json.dumps(_minimal_report()), encoding="utf-8")

    assert sharing.resolve_report_path(tmp_path, "r") == priv / "r.json"


def test_resolve_prefers_private_over_a_stale_public_copy(tmp_path):
    """A leftover public duplicate must not un-gate an unlisted report."""
    priv = sharing.private_dir(tmp_path)
    priv.mkdir()
    unlisted = _minimal_report()
    sharing.mark_unlisted(unlisted)
    (priv / "r.json").write_text(json.dumps(unlisted), encoding="utf-8")
    (tmp_path / "r.json").write_text(json.dumps(_minimal_report()), encoding="utf-8")

    resolved = sharing.resolve_report_path(tmp_path, "r")

    assert resolved == priv / "r.json"
    assert sharing.is_unlisted(json.loads(resolved.read_text(encoding="utf-8")))


def test_resolve_rejects_traversal(tmp_path):
    assert sharing.resolve_report_path(tmp_path, "../etc/passwd") is None


def test_iter_report_files_can_exclude_private(tmp_path):
    priv = sharing.private_dir(tmp_path)
    priv.mkdir()
    (tmp_path / "pub.json").write_text("{}", encoding="utf-8")
    (priv / "sec.json").write_text("{}", encoding="utf-8")

    public_only = [p.stem for p in sharing.iter_report_files(tmp_path, include_private=False)]
    both = [p.stem for p in sharing.iter_report_files(tmp_path, include_private=True)]

    assert public_only == ["pub"]
    assert sorted(both) == ["pub", "sec"]


def test_token_index_finds_a_report_in_the_private_dir(tmp_path):
    sharing.reset_token_index()
    priv = sharing.private_dir(tmp_path)
    priv.mkdir()
    report = _minimal_report()
    token = sharing.mark_unlisted(report)
    (priv / "hidden.json").write_text(json.dumps(report), encoding="utf-8")

    found = sharing.find_report_by_token(tmp_path, token)

    assert found is not None and found[0] == "hidden"
    sharing.reset_token_index()


def test_unlisted_left_in_the_public_dir_is_still_gated(client):
    """Directory placement is defence in depth; the access rule is the gate."""
    stray_id = "_pytest_stray_unlisted_report"
    path = REPORTS_DIR / f"{stray_id}.json"
    report = _minimal_report()
    sharing.mark_unlisted(report)
    path.write_text(json.dumps(report), encoding="utf-8")
    sharing.reset_token_index()
    try:
        assert client.get(f"/report/saved/{stray_id}").status_code == 404
        assert client.get(f"/api/analytics/results/{stray_id}").status_code == 404
        ids = [r["video_id"] for r in client.get("/reports").json()["reports"]]
        assert stray_id not in ids
    finally:
        path.unlink(missing_ok=True)
        sharing.reset_token_index()


# ------------------------------------------------------------------
# The results/report/jobs APIs must not leak an unlisted report
# ------------------------------------------------------------------


def test_redacted_for_client_strips_the_token():
    report = _minimal_report()
    token = sharing.mark_unlisted(report)
    clean = sharing.redacted_for_client(report)

    assert "share_token" not in clean["meta"]
    assert clean["meta"]["visibility"] == sharing.VISIBILITY_UNLISTED
    # the original is untouched, so the server can still check the token
    assert report["meta"]["share_token"] == token


def test_redacted_for_client_passes_through_a_public_report():
    report = _minimal_report()
    assert sharing.redacted_for_client(report) is report


@pytest.mark.parametrize("route", [
    "/api/analytics/results/{id}",
    "/api/analytics/report/{id}",
    "/api/analytics/jobs/{id}",
])
def test_report_apis_hide_an_unlisted_report(client, shared_reports, route):
    """These served the whole report — token included — with no check at all."""
    assert client.get(route.format(id=UNLISTED_ID)).status_code == 404
    assert client.get(route.format(id=UNLISTED_ID) + "?token=wrong").status_code == 404


@pytest.mark.parametrize("route", [
    "/api/analytics/results/{id}",
    "/api/analytics/report/{id}",
    "/api/analytics/jobs/{id}",
])
def test_report_apis_open_with_the_token(client, shared_reports, route):
    token = shared_reports
    resp = client.get(route.format(id=UNLISTED_ID) + f"?token={token}")
    assert resp.status_code == 200


def test_results_api_never_returns_the_share_token(client, shared_reports):
    token = shared_reports
    body = client.get(f"/api/analytics/results/{UNLISTED_ID}?token={token}").text

    assert token not in body
    assert "share_token" not in body


def test_report_page_json_never_embeds_the_share_token(client, shared_reports):
    """The page needs the token for clip URLs, but not inside report_json."""
    token = shared_reports
    body = _get_page(client, f"/r/{token}").text

    assert f'CLIP_TOKEN = "{token}"' in body
    assert '"share_token"' not in body


def test_public_report_apis_are_unaffected(client, shared_reports):
    for route in ("/api/analytics/results/{id}", "/api/analytics/report/{id}",
                  "/api/analytics/jobs/{id}"):
        assert client.get(route.format(id=PUBLIC_ID)).status_code == 200


def test_public_listing_skips_an_id_that_also_exists_in_private(tmp_path):
    """Re-analysis rewrites into data/reports, resurrecting a shared id there.

    The content stays unreachable because resolve_report_path prefers private,
    but enumerating the id would still republish the fencers' names it carries.
    """
    priv = sharing.private_dir(tmp_path)
    priv.mkdir()
    (priv / "shared.json").write_text("{}", encoding="utf-8")
    (tmp_path / "shared.json").write_text("{}", encoding="utf-8")
    (tmp_path / "ordinary.json").write_text("{}", encoding="utf-8")

    public_only = [p.stem for p in sharing.iter_report_files(tmp_path, include_private=False)]

    assert public_only == ["ordinary"]


def test_iter_with_private_yields_the_private_copy_once(tmp_path):
    priv = sharing.private_dir(tmp_path)
    priv.mkdir()
    (priv / "shared.json").write_text("{}", encoding="utf-8")
    (tmp_path / "shared.json").write_text("{}", encoding="utf-8")

    paths = list(sharing.iter_report_files(tmp_path, include_private=True))

    assert paths == [priv / "shared.json"]
