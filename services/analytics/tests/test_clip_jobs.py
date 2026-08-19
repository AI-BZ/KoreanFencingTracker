"""On-demand clip generation as a job, not as a blocking request.

Rendering one pose-overlay clip takes 2-4 minutes since the piste gate raised
the pose input to 1280, and Cloudflare's tunnel gives up at ~100s — so the old
"generate inside the GET" design returned a 504 every single time. These tests
pin the replacement: the read route never generates, /start schedules at most
one job per clip, and /status is the only thing that ever waits.

The access gate is re-asserted here rather than assumed. A job endpoint that
skipped it would both confirm an unlisted report exists and spend our GPU on
it, so each of the three routes has to answer with the same 404 the report page
does.
"""

import json
import shutil
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import server, sharing
from app.server import app, _BASE_DIR

from tests.test_report_sharing import _minimal_report


REPORTS_DIR = _BASE_DIR / "data" / "reports"
CLIPS_ROOT = _BASE_DIR / "data" / "clips" / "overlay"
RAW_DIR = _BASE_DIR / "data" / "raw"

PUBLIC_ID = "_pytest_clipjob_public_continuous_report"
UNLISTED_ID = "_pytest_clipjob_unlisted_continuous_report"
FAKE_VIDEO = RAW_DIR / "_pytest_clipjob_source.mp4"


def _report_with_a_touch(video_path: str) -> dict:
    """A report the clip routes can resolve all the way to a video path.

    The sharing fixtures use a report with no touches on purpose (it pins the
    "Touch #1 not found" answer); these tests need the opposite — a request that
    gets past every validation step so the job machinery is what is under test.
    """
    report = _minimal_report()
    report["touches"] = [{
        "touch_number": 1,
        "frame": 300,
        "scorer": "left",
        "time": "00:10",
    }]
    report["summary"]["total_touches"] = 1
    report["meta"]["video_path"] = video_path
    return report


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def clip_reports():
    """One public and one unlisted report, both resolvable to a source video.

    The video only has to exist — every test patches generation out, because a
    real render is the minutes-long operation this whole feature exists to move
    off the request path.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    FAKE_VIDEO.write_bytes(b"\x00" * 64)

    public_path = REPORTS_DIR / f"{PUBLIC_ID}.json"
    private_path = sharing.private_dir(REPORTS_DIR) / f"{UNLISTED_ID}.json"
    private_path.parent.mkdir(parents=True, exist_ok=True)

    public_path.write_text(
        json.dumps(_report_with_a_touch(str(FAKE_VIDEO))), encoding="utf-8"
    )

    unlisted = _report_with_a_touch(str(FAKE_VIDEO))
    token = sharing.mark_unlisted(unlisted)
    private_path.write_text(json.dumps(unlisted), encoding="utf-8")

    sharing.reset_token_index()
    try:
        yield token
    finally:
        public_path.unlink(missing_ok=True)
        private_path.unlink(missing_ok=True)
        FAKE_VIDEO.unlink(missing_ok=True)
        shutil.rmtree(CLIPS_ROOT / PUBLIC_ID, ignore_errors=True)
        shutil.rmtree(CLIPS_ROOT / UNLISTED_ID, ignore_errors=True)
        with server._CLIP_JOBS_LOCK:
            server._CLIP_JOBS.clear()
        sharing.reset_token_index()


def _start_url(report_id, event_type="touch", number=1):
    return f"/api/analytics/clips/{report_id}/{event_type}/{number}/start"


def _status_url(report_id, event_type="touch", number=1):
    return f"/api/analytics/clips/{report_id}/{event_type}/{number}/status"


def _clip_url(report_id, event_type="touch", number=1):
    return f"/api/analytics/clips/{report_id}/{event_type}/{number}"


def _write_cached_clip(report_id, event_type="touch", number=1) -> Path:
    path = server._clip_cache_path(report_id, event_type, number)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Comfortably over the 1000-byte floor the cache check uses.
    path.write_bytes(b"\x00" * 4096)
    return path


def _never_generates(monkeypatch):
    """Make any generation attempt a loud failure instead of a slow one."""
    def _boom(*args, **kwargs):
        raise AssertionError("clip generation ran during a request")

    monkeypatch.setattr(server, "_generate_event_clip", _boom)


# ------------------------------------------------------------------
# The gate: all three routes answer like the report page
# ------------------------------------------------------------------


def test_start_hidden_for_unlisted_without_token(client, clip_reports):
    resp = client.post(_start_url(UNLISTED_ID))

    assert resp.status_code == 404
    assert resp.json()["detail"] == f"Report not found: {UNLISTED_ID}"


def test_start_with_token_gets_past_the_gate(client, clip_reports, monkeypatch):
    token = clip_reports
    monkeypatch.setattr(
        server, "_generate_event_clip",
        lambda *a, **k: a[-1].write_bytes(b"\x00" * 4096),
    )

    resp = client.post(f"{_start_url(UNLISTED_ID)}?token={token}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["cached"] is False
    assert body["job_id"]


def test_status_hidden_for_unlisted_without_token(client, clip_reports):
    resp = client.get(_status_url(UNLISTED_ID))

    assert resp.status_code == 404
    assert resp.json()["detail"] == f"Report not found: {UNLISTED_ID}"


def test_status_with_token_gets_past_the_gate(client, clip_reports):
    token = clip_reports

    resp = client.get(f"{_status_url(UNLISTED_ID)}?token={token}")

    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"


def test_wrong_token_is_indistinguishable_from_a_missing_report(client, clip_reports):
    """The 404 detail must not tell "wrong token" apart from "no such id"."""
    bad = client.get(f"{_status_url(UNLISTED_ID)}?token=deadbeefdeadbeef")
    missing = client.get(_status_url("_pytest_clipjob_no_such_report"))

    assert bad.status_code == missing.status_code == 404
    assert bad.json()["detail"] == f"Report not found: {UNLISTED_ID}"


# ------------------------------------------------------------------
# The read route no longer generates
# ------------------------------------------------------------------


def test_uncached_clip_fetch_returns_202_instead_of_blocking(
    client, clip_reports, monkeypatch
):
    _never_generates(monkeypatch)

    started = time.monotonic()
    resp = client.get(_clip_url(PUBLIC_ID))
    elapsed = time.monotonic() - started

    assert resp.status_code == 202
    body = resp.json()
    assert body["start_url"] == _start_url(PUBLIC_ID)
    assert body["status_url"] == _status_url(PUBLIC_ID)
    assert body["status"] == "idle"
    # Not a timing assertion so much as a guard: generation is minutes long, so
    # anything near it here means the old inline path came back.
    assert elapsed < 5


def test_uncached_fetch_creates_no_job(client, clip_reports, monkeypatch):
    _never_generates(monkeypatch)

    client.get(_clip_url(PUBLIC_ID))

    assert client.get(_status_url(PUBLIC_ID)).json()["status"] == "idle"


def test_missing_touch_still_404s_before_any_job_talk(client, clip_reports, monkeypatch):
    """Validation order survives: a bad event number is a 404, not a 202."""
    _never_generates(monkeypatch)

    for url in (_clip_url(PUBLIC_ID, number=99), _start_url(PUBLIC_ID, number=99)):
        resp = client.request("POST" if url.endswith("start") else "GET", url)
        assert resp.status_code == 404, url
        assert resp.json()["detail"] == "Touch #99 not found"


def test_invalid_event_type_is_rejected_on_the_job_routes(client, clip_reports):
    assert client.post(_start_url(PUBLIC_ID, "parry")).status_code == 400
    assert client.get(_status_url(PUBLIC_ID, "parry")).status_code == 400


# ------------------------------------------------------------------
# Cached clips short-circuit everything
# ------------------------------------------------------------------


def test_cached_clip_starts_ready_and_streams(client, clip_reports, monkeypatch):
    _never_generates(monkeypatch)
    _write_cached_clip(PUBLIC_ID)

    start = client.post(_start_url(PUBLIC_ID))
    assert start.status_code == 200
    assert start.json() == {"status": "ready", "cached": True, "job_id": None}

    status = client.get(_status_url(PUBLIC_ID))
    assert status.json()["status"] == "ready"
    assert status.json()["queue_position"] is None

    fetched = client.get(_clip_url(PUBLIC_ID))
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "video/mp4"


def test_cached_clip_reports_ready_even_with_no_job(client, clip_reports):
    """The file is the truth — batch-generated clips never had a job at all."""
    _write_cached_clip(PUBLIC_ID)

    body = client.get(_status_url(PUBLIC_ID)).json()

    assert body["status"] == "ready"
    assert body["error"] is None


# ------------------------------------------------------------------
# Dedupe
# ------------------------------------------------------------------


def test_duplicate_start_joins_the_running_job(client, clip_reports, monkeypatch):
    """Two clicks on one row must not become two four-minute YOLO passes."""
    calls = []
    release = threading.Event()

    def _slow_stub(report_dict, event_type, event, video_path,
                   start_frame, end_frame, clip_path):
        calls.append(clip_path)
        release.wait(20)
        clip_path.write_bytes(b"\x00" * 4096)

    monkeypatch.setattr(server, "_generate_event_clip", _slow_stub)

    # The first request stays open for as long as its background task runs, so
    # it has to be issued from another thread to overlap with the second.
    first_client = TestClient(app, raise_server_exceptions=False)
    first = {}

    def _run_first():
        first["resp"] = first_client.post(_start_url(PUBLIC_ID))

    thread = threading.Thread(target=_run_first)
    thread.start()
    try:
        key = f"{PUBLIC_ID}/touch/1"
        deadline = time.monotonic() + 20
        snap = None
        while time.monotonic() < deadline:
            snap = server._clip_job_snapshot(key)
            if snap is not None and snap["status"] == "running":
                break
            time.sleep(0.01)
        assert snap is not None and snap["status"] == "running", "job never started"

        second = client.post(_start_url(PUBLIC_ID))
        assert second.status_code == 200
        body = second.json()
        assert body["job_id"] == snap["job_id"]
        assert body["cached"] is False
        assert body["status"] in ("queued", "running")
    finally:
        release.set()
        thread.join(30)

    assert len(calls) == 1, "generation was scheduled more than once"
    assert first["resp"].json()["job_id"] == snap["job_id"]


def test_start_after_a_failure_gets_a_fresh_job(client, clip_reports, monkeypatch):
    """A finished job is not joined — asking again means asking for a retry."""
    monkeypatch.setattr(
        server, "_generate_event_clip",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope")),
    )

    first = client.post(_start_url(PUBLIC_ID)).json()["job_id"]
    second = client.post(_start_url(PUBLIC_ID)).json()["job_id"]

    assert first != second


# ------------------------------------------------------------------
# Failure handling
# ------------------------------------------------------------------


def test_failed_generation_surfaces_an_error_and_leaves_no_cache_file(
    client, clip_reports, monkeypatch
):
    """A truncated mp4 would pass the size check forever, so it must be removed."""
    def _write_then_fail(report_dict, event_type, event, video_path,
                         start_frame, end_frame, clip_path):
        clip_path.write_bytes(b"\x00" * 8192)  # over the cache floor: poison
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(server, "_generate_event_clip", _write_then_fail)

    start = client.post(_start_url(PUBLIC_ID))
    assert start.json()["status"] == "queued"

    body = client.get(_status_url(PUBLIC_ID)).json()
    assert body["status"] == "failed"
    assert "ffmpeg exploded" in body["error"]
    assert body["elapsed_sec"] >= 0

    assert not server._clip_cache_path(PUBLIC_ID, "touch", 1).exists()
    # And the read route must not serve the wreckage.
    assert client.get(_clip_url(PUBLIC_ID)).status_code == 202


def test_generation_that_writes_nothing_is_a_failure_not_a_ready(
    client, clip_reports, monkeypatch
):
    monkeypatch.setattr(server, "_generate_event_clip", lambda *a, **k: None)

    client.post(_start_url(PUBLIC_ID))

    body = client.get(_status_url(PUBLIC_ID)).json()
    assert body["status"] == "failed"
    assert body["error"]


def test_successful_generation_ends_ready_and_streams(client, clip_reports, monkeypatch):
    monkeypatch.setattr(
        server, "_generate_event_clip",
        lambda *a, **k: a[-1].write_bytes(b"\x00" * 4096),
    )

    client.post(_start_url(PUBLIC_ID))

    assert client.get(_status_url(PUBLIC_ID)).json()["status"] == "ready"
    assert client.get(_clip_url(PUBLIC_ID)).status_code == 200


# ------------------------------------------------------------------
# Queueing
# ------------------------------------------------------------------


def test_queued_jobs_report_their_position(clip_reports):
    """Position is 1-based and ordered by arrival, so a waiting user sees movement."""
    with server._CLIP_JOBS_LOCK:
        server._CLIP_JOBS.clear()

    keys = [f"{PUBLIC_ID}/touch/{n}" for n in (1, 2, 3)]
    for key in keys:
        server._claim_clip_job(key)

    positions = [server._clip_job_snapshot(k)["queue_position"] for k in keys]
    assert positions == [1, 2, 3]

    # Once the first is running it stops occupying a queue slot.
    server._finish_clip_job(keys[0], server._clip_job_snapshot(keys[0])["job_id"],
                            "running", None)
    assert server._clip_job_snapshot(keys[1])["queue_position"] == 1
    assert server._clip_job_snapshot(keys[0])["queue_position"] is None


def test_concurrency_cap_is_small_enough_to_not_thrash():
    """Ten clicked rows must not become ten simultaneous YOLO passes."""
    assert server._CLIP_MAX_CONCURRENT == 2
