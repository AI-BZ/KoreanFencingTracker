"""Tests for the two-camera pairing: offset measurement and report wiring."""

import json

import numpy as np
import pytest

from app.server import _zoom_video_info
from scripts.sync_camera_pair import (
    ENVELOPE_RATE,
    MIN_PEAK,
    SyncRejected,
    apply_to_config,
    correlate_envelopes,
    envelope,
    peak_sharpness,
)


# ------------------------------------------------------------------
# envelope + correlation
# ------------------------------------------------------------------


# Irregularly spaced and unevenly loud, like buzzers and applause in a hall.
# Evenly spaced identical bursts would correlate just as well one interval off,
# which is a property of that made-up signal and not of the method.
BURSTS = [(3.1, 1.0), (7.4, 0.5), (12.9, 0.9), (14.2, 0.3),
          (21.6, 1.0), (29.8, 0.6), (33.5, 0.85)]


def _burst_track(seconds: float, bursts, rate: int = 8000, gain: float = 1.0):
    """Room tone with short loud bursts at the given (time, loudness) points."""
    rng = np.random.default_rng(7)
    n = int(seconds * rate)
    x = rng.normal(0, 0.01, n).astype(np.float32)
    for t, amp in bursts:
        i = int(t * rate)
        if i < 0 or i >= n:
            continue
        width = min(rate // 4, n - i)
        x[i:i + width] += (gain * amp) * rng.normal(0, 0.5, width).astype(np.float32)
    return x


def _shifted(bursts, shift):
    """The same bursts as a second camera that started `shift` seconds later."""
    return [(t - shift, amp) for t, amp in bursts]


def test_envelope_is_normalised_and_decimated():
    env = envelope(_burst_track(10.0, [(2.0, 1.0), (5.0, 0.6), (8.0, 0.9)]))
    assert env.size == pytest.approx(10.0 * ENVELOPE_RATE, rel=0.02)
    assert env.mean() == pytest.approx(0.0, abs=1e-9)
    assert env.std() == pytest.approx(1.0, abs=1e-9)


def test_envelope_refuses_a_silent_track():
    with pytest.raises(RuntimeError, match="flat"):
        envelope(np.zeros(80_000, dtype=np.float32))


@pytest.mark.parametrize("shift", [3.0, 8.95, -4.5])
def test_correlation_recovers_a_known_shift(shift):
    """The zoom camera starting `shift` seconds late must read as -shift."""
    wide = envelope(_burst_track(45.0, BURSTS))
    # The second camera hears the same bursts, earlier in its own recording, and
    # at a different overall gain because it sits somewhere else in the hall.
    zoom = envelope(_burst_track(45.0, _shifted(BURSTS, shift), gain=0.4))

    offset, peak, _ = correlate_envelopes(wide, zoom)
    assert offset == pytest.approx(-shift, abs=1.0 / ENVELOPE_RATE + 1e-6)
    assert peak > MIN_PEAK


def test_unrelated_recordings_stay_under_the_threshold():
    """Two halls with nothing in common must not produce a usable offset."""
    wide = envelope(_burst_track(45.0, BURSTS))
    zoom = envelope(_burst_track(45.0, [(1.0, 0.4), (3.2, 1.0), (7.7, 0.7),
                                        (9.1, 0.2), (40.4, 0.9)]))
    _, peak, _ = correlate_envelopes(wide, zoom)
    assert peak < MIN_PEAK


def test_a_true_match_has_a_sharp_peak():
    wide = envelope(_burst_track(45.0, BURSTS))
    zoom = envelope(_burst_track(45.0, _shifted(BURSTS, 6.0)))
    _, _, scores = correlate_envelopes(wide, zoom)
    # The validated real pair spreads its top candidates over 0.087 s.
    assert peak_sharpness(scores) < 0.5


def test_apply_to_config_records_offset_and_provenance(tmp_path):
    config = {"work_files": {"piste": "data/raw/own/bout.mp4"}}
    sync = {"offset_sec": -8.95, "peak": 0.83, "spread_sec": 0.09,
            "method": "audio_envelope_xcorr", "min_peak": 0.4,
            "measured_at": "2026-08-31"}
    apply_to_config(config, tmp_path / "zoom.mov", sync, "data/raw/own/bout_zoom.mp4")

    assert config["zoom"]["offset_sec"] == -8.95
    assert config["zoom"]["work_file"] == "data/raw/own/bout_zoom.mp4"
    # The offset lives at the top of the block; how it was obtained sits beside
    # it, so a future reader can judge whether to trust it.
    assert config["zoom"]["sync"]["peak"] == 0.83
    assert "offset_sec" not in config["zoom"]["sync"]


def test_sync_rejected_is_an_error_not_a_return_value():
    assert issubclass(SyncRejected, RuntimeError)


# ------------------------------------------------------------------
# report wiring
# ------------------------------------------------------------------


def _write_pair(tmp_path, own_dir, monkeypatch, zoom_block):
    """A piste config plus the work file it names, wired into the server paths."""
    own_dir.mkdir(parents=True, exist_ok=True)
    (own_dir / "bout_zoom.mp4").write_bytes(b"not really an mp4")

    config = {"work_files": {"piste": "x.mp4"}}
    if zoom_block is not None:
        config["zoom"] = zoom_block
    cfg_path = tmp_path / "piste.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")

    import app.server as server
    monkeypatch.setattr(server, "_own_video_dir", own_dir)
    return {"meta": {"piste_config": str(cfg_path)}}


def test_zoom_info_returns_filename_and_offset(tmp_path, monkeypatch):
    own = tmp_path / "raw" / "own"
    report = _write_pair(tmp_path, own, monkeypatch, {
        "work_file": str(tmp_path / "raw" / "own" / "bout_zoom.mp4"),
        "offset_sec": -8.95,
    })
    assert _zoom_video_info(report) == ("own/bout_zoom.mp4", -8.95)


def test_zoom_info_accepts_a_zero_offset(tmp_path, monkeypatch):
    """0.0 is a real measurement — two cameras started together — not 'missing'."""
    own = tmp_path / "raw" / "own"
    report = _write_pair(tmp_path, own, monkeypatch, {
        "work_file": str(own / "bout_zoom.mp4"),
        "offset_sec": 0.0,
    })
    assert _zoom_video_info(report) == ("own/bout_zoom.mp4", 0.0)


def test_zoom_info_refuses_a_file_without_an_offset(tmp_path, monkeypatch):
    """Half a pair would put an unsynced frame beside the wide camera."""
    own = tmp_path / "raw" / "own"
    report = _write_pair(tmp_path, own, monkeypatch, {
        "work_file": str(own / "bout_zoom.mp4"),
    })
    assert _zoom_video_info(report) == (None, None)


def test_zoom_info_refuses_an_offset_without_a_file(tmp_path, monkeypatch):
    own = tmp_path / "raw" / "own"
    report = _write_pair(tmp_path, own, monkeypatch, {"offset_sec": -8.95})
    assert _zoom_video_info(report) == (None, None)


def test_zoom_info_refuses_a_missing_work_file(tmp_path, monkeypatch):
    own = tmp_path / "raw" / "own"
    report = _write_pair(tmp_path, own, monkeypatch, {
        "work_file": str(own / "never_encoded.mp4"),
        "offset_sec": -8.95,
    })
    assert _zoom_video_info(report) == (None, None)


def test_zoom_info_refuses_a_file_outside_the_served_directory(tmp_path, monkeypatch):
    """/videos/own is the only mount; anything else would render a dead player."""
    own = tmp_path / "raw" / "own"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "bout_zoom.mp4").write_bytes(b"x")
    report = _write_pair(tmp_path, own, monkeypatch, {
        "work_file": str(outside / "bout_zoom.mp4"),
        "offset_sec": -8.95,
    })
    assert _zoom_video_info(report) == (None, None)


def test_zoom_info_is_silent_for_reports_that_predate_the_feature(tmp_path, monkeypatch):
    own = tmp_path / "raw" / "own"
    # No zoom block at all — every report written before this existed.
    report = _write_pair(tmp_path, own, monkeypatch, None)
    assert _zoom_video_info(report) == (None, None)

    # And no piste config at all — every TV / YouTube report.
    assert _zoom_video_info({"meta": {}}) == (None, None)
    assert _zoom_video_info({}) == (None, None)


def test_zoom_info_survives_an_unreadable_config(tmp_path, monkeypatch):
    bad = tmp_path / "broken.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert _zoom_video_info({"meta": {"piste_config": str(bad)}}) == (None, None)
    assert _zoom_video_info({"meta": {"piste_config": str(tmp_path / "gone.json")}}) == (None, None)
