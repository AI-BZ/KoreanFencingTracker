"""Joint-keypoint sidecar: build, resolve, serve.

The pipeline already computes 17 joints per fencer on every sampled frame and
then throws them away once the report's aggregates are built. These tests cover
keeping them: the pure builder, where the file is allowed to live, and the route
that serves it.

The access matrix at the bottom is the part that matters. The sidecar is the
analysis in another form — every joint of two named fencers, frame by frame — so
it has to answer the token gate exactly the way the report page and the clip
endpoints do, or an unlisted bout leaks through the one route nobody checked.
"""

import inspect
import json

import pytest
from fastapi.testclient import TestClient

from analyzer.config import POSE_KEYPOINT_CONFIDENCE
from analyzer.models import FencerPose, PoseKeypoint, PoseResult
from app import server, sharing
from app.server import app, _BASE_DIR
from scripts.generate_continuous_report import (
    KEYPOINTS_CONF_SCALE,
    KEYPOINTS_SCHEMA_VERSION,
    build_keypoints_sidecar,
    preserve_existing_meta,
)


REPORTS_DIR = _BASE_DIR / "data" / "reports"

KP_PUBLIC_ID = "_pytest_kp_public_continuous_report"
KP_UNLISTED_ID = "_pytest_kp_unlisted_continuous_report"
KP_BARE_ID = "_pytest_kp_bare_continuous_report"


# ------------------------------------------------------------------
# Fixtures / builders
# ------------------------------------------------------------------


def _pose(side, *, conf=0.9, x0=100.0, y0=200.0, kp_conf=0.8, joints=17):
    """A FencerPose whose joints march diagonally from (x0, y0)."""
    return FencerPose(
        keypoints=[
            PoseKeypoint(x=x0 + i, y=y0 + i, confidence=kp_conf)
            for i in range(joints)
        ],
        bbox=[x0, y0, x0 + 50, y0 + 100],
        person_confidence=conf,
        side=side,
    )


def _frame(idx, fencers):
    return PoseResult(frame_idx=idx, fencers=list(fencers))


def _build(pose_results, **kwargs):
    params = dict(
        report_id="r_continuous_report",
        fps=30.0,
        sample_every=3,
        frame_width=1920,
        frame_height=1080,
    )
    params.update(kwargs)
    return build_keypoints_sidecar(pose_results, **params)


def _minimal_report() -> dict:
    """Just enough report for the access gate; these tests never render a page."""
    return {
        "summary": {"final_score": "5-3"},
        "touches": [],
        "exchanges": [],
        "meta": {"phase": 6, "fps": 30.0, "analysis_mode": "continuous_only"},
    }


def _sidecar(report_id: str) -> dict:
    return _build([_frame(0, [_pose("left"), _pose("right", x0=800.0)])],
                  report_id=report_id)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def keypoint_reports():
    """Three reports on disk: public+sidecar, unlisted+sidecar, public-no-sidecar.

    The server resolves data/reports/ from its own base dir rather than from a
    setting, so as in test_report_sharing these have to be real files next to
    the real reports. Every id is prefixed so a leaked one is obvious.
    """
    priv = sharing.private_dir(REPORTS_DIR)
    public_path = REPORTS_DIR / f"{KP_PUBLIC_ID}.json"
    bare_path = REPORTS_DIR / f"{KP_BARE_ID}.json"
    private_path = priv / f"{KP_UNLISTED_ID}.json"
    public_kp = sharing.keypoints_path_for_report(public_path)
    private_kp = sharing.keypoints_path_for_report(private_path)

    for p in (private_path, public_kp, private_kp):
        p.parent.mkdir(parents=True, exist_ok=True)

    public_path.write_text(json.dumps(_minimal_report()), encoding="utf-8")
    bare_path.write_text(json.dumps(_minimal_report()), encoding="utf-8")

    unlisted = _minimal_report()
    token = sharing.mark_unlisted(unlisted)
    private_path.write_text(json.dumps(unlisted), encoding="utf-8")

    public_kp.write_text(json.dumps(_sidecar(KP_PUBLIC_ID)), encoding="utf-8")
    private_kp.write_text(json.dumps(_sidecar(KP_UNLISTED_ID)), encoding="utf-8")

    sharing.reset_token_index()
    try:
        yield token
    finally:
        for p in (public_path, bare_path, private_path, public_kp, private_kp):
            p.unlink(missing_ok=True)
        sharing.reset_token_index()


# ------------------------------------------------------------------
# build_keypoints_sidecar — schema
# ------------------------------------------------------------------


class TestSidecarSchema:
    def test_declares_its_version_and_scale(self):
        doc = _build([])
        assert doc["version"] == KEYPOINTS_SCHEMA_VERSION
        assert doc["conf_scale"] == KEYPOINTS_CONF_SCALE

    def test_carries_the_playback_parameters(self):
        doc = _build([], report_id="abc", fps=59.94, sample_every=5,
                     frame_width=1280, frame_height=720)
        assert doc["report_id"] == "abc"
        assert doc["fps"] == pytest.approx(59.94)
        assert doc["sample_every"] == 5
        assert doc["frame_width"] == 1280
        assert doc["frame_height"] == 720

    def test_min_confidence_comes_from_the_analyser_config(self):
        # The page dims joints below this; hardcoding a different number here
        # would draw joints the analysis itself did not trust.
        assert _build([])["min_confidence"] == POSE_KEYPOINT_CONFIDENCE

    def test_no_frames_array_is_stored(self):
        # Sample i is frame i * sample_every; storing that would be a third of
        # the file for something the reader can compute.
        assert "frames" not in _build([_frame(0, [_pose("left")])])

    def test_empty_input_gives_empty_but_well_formed_sides(self):
        doc = _build([])
        assert doc["sample_count"] == 0
        assert doc["poses"] == {"left": [], "right": []}


class TestSidecarShape:
    def test_flat_array_is_51_ints(self):
        doc = _build([_frame(0, [_pose("left")])])
        arr = doc["poses"]["left"][0]
        assert len(arr) == 51
        assert all(isinstance(v, int) for v in arr)
        # Flat, not nested: nesting is what the flat form exists to avoid.
        assert not any(isinstance(v, list) for v in arr)

    def test_both_sides_have_one_entry_per_sample(self):
        results = [_frame(i, [_pose("left"), _pose("right", x0=800.0)])
                   for i in range(7)]
        doc = _build(results)
        assert doc["sample_count"] == 7
        assert len(doc["poses"]["left"]) == 7
        assert len(doc["poses"]["right"]) == 7

    def test_sample_count_matches_both_sides_when_only_one_is_detected(self):
        # The right side is never seen; it still needs an entry per sample or
        # the page's index i means a different moment on each side.
        results = [_frame(i, [_pose("left")]) for i in range(4)]
        doc = _build(results)
        assert doc["sample_count"] == 4
        assert len(doc["poses"]["right"]) == 4
        assert doc["poses"]["right"] == [None, None, None, None]


class TestSidecarValues:
    def test_coordinates_round_trip_within_half_a_pixel(self):
        fencer = FencerPose(
            keypoints=[PoseKeypoint(x=100.4, y=200.6, confidence=0.5)] * 17,
            bbox=[0, 0, 1, 1], person_confidence=0.9, side="left",
        )
        arr = _build([_frame(0, [fencer])])["poses"]["left"][0]
        assert arr[0] == pytest.approx(100.4, abs=0.5)
        assert arr[1] == pytest.approx(200.6, abs=0.5)

    def test_confidence_divides_back_to_the_original(self):
        fencer = FencerPose(
            keypoints=[PoseKeypoint(x=1.0, y=2.0, confidence=0.874)] * 17,
            bbox=[0, 0, 1, 1], person_confidence=0.9, side="left",
        )
        doc = _build([_frame(0, [fencer])])
        arr = doc["poses"]["left"][0]
        assert arr[2] == 87
        assert arr[2] / doc["conf_scale"] == pytest.approx(0.874, abs=0.005)

    def test_confidence_is_an_int_in_range(self):
        fencer = FencerPose(
            keypoints=[PoseKeypoint(x=1.0, y=2.0, confidence=1.0)] * 17,
            bbox=[0, 0, 1, 1], person_confidence=0.9, side="left",
        )
        arr = _build([_frame(0, [fencer])])["poses"]["left"][0]
        assert arr[2] == KEYPOINTS_CONF_SCALE

    def test_coordinates_stay_in_the_videos_own_pixel_space(self):
        # Not normalised: the page knows the video it overlays, and rescaling
        # here would bake in an assumption about the player's size.
        fencer = _pose("left", x0=1500.0, y0=900.0, joints=17)
        arr = _build([_frame(0, [fencer])], frame_width=1920, frame_height=1080)
        assert arr["poses"]["left"][0][0] == 1500
        assert arr["poses"]["left"][0][1] == 900


class TestSidecarMissingDetections:
    def test_missing_side_is_null(self):
        doc = _build([_frame(0, [_pose("left")])])
        assert doc["poses"]["right"][0] is None
        assert doc["poses"]["left"][0] is not None

    def test_frame_with_no_fencers_at_all_is_null_on_both_sides(self):
        doc = _build([_frame(0, [])])
        assert doc["poses"]["left"] == [None]
        assert doc["poses"]["right"] == [None]

    def test_fencer_without_a_side_is_skipped(self):
        # side is what the page keys the two skeletons on; guessing one would
        # draw the wrong fencer.
        doc = _build([_frame(0, [_pose(None)])])
        assert doc["poses"]["left"] == [None]
        assert doc["poses"]["right"] == [None]

    def test_gaps_do_not_shift_later_samples(self):
        results = [
            _frame(0, [_pose("left", x0=10.0)]),
            _frame(1, []),
            _frame(2, [_pose("left", x0=30.0)]),
        ]
        doc = _build(results)
        assert doc["poses"]["left"][0][0] == 10
        assert doc["poses"]["left"][1] is None
        assert doc["poses"]["left"][2][0] == 30


class TestSidecarSideCollision:
    def test_higher_person_confidence_wins(self):
        loser = _pose("left", conf=0.4, x0=10.0)
        winner = _pose("left", conf=0.95, x0=500.0)
        doc = _build([_frame(0, [loser, winner])])
        assert doc["poses"]["left"][0][0] == 500

    def test_order_does_not_decide_the_winner(self):
        winner = _pose("left", conf=0.95, x0=500.0)
        loser = _pose("left", conf=0.4, x0=10.0)
        doc = _build([_frame(0, [winner, loser])])
        assert doc["poses"]["left"][0][0] == 500

    def test_a_collision_on_one_side_leaves_the_other_alone(self):
        doc = _build([_frame(0, [
            _pose("left", conf=0.4, x0=10.0),
            _pose("left", conf=0.95, x0=500.0),
            _pose("right", conf=0.7, x0=900.0),
        ])])
        assert doc["poses"]["left"][0][0] == 500
        assert doc["poses"]["right"][0][0] == 900


# ------------------------------------------------------------------
# preserve_existing_meta
# ------------------------------------------------------------------


class TestPreserveExistingMeta:
    def test_share_token_and_visibility_survive_a_regeneration(self):
        fresh = {"phase": 6, "fps": 30.0}
        old = {"phase": 6, "fps": 30.0, "share_token": "abc123",
               "visibility": "unlisted"}
        merged = preserve_existing_meta(fresh, old)
        assert merged["share_token"] == "abc123"
        assert merged["visibility"] == "unlisted"

    def test_fresh_values_beat_stale_ones(self):
        merged = preserve_existing_meta(
            {"fps": 59.94, "source_type": "coach"},
            {"fps": 30.0, "source_type": "tv_broadcast"},
        )
        assert merged["fps"] == pytest.approx(59.94)
        assert merged["source_type"] == "coach"

    def test_unknown_hand_set_keys_survive(self):
        # The rule is "keep what the fresh run did not set", not a field list —
        # a list would have to grow every time another tool writes to meta.
        merged = preserve_existing_meta({"phase": 6}, {"reviewed_by": "coach"})
        assert merged["reviewed_by"] == "coach"

    def test_a_fresh_falsy_value_still_wins(self):
        merged = preserve_existing_meta({"pose_enabled": False},
                                        {"pose_enabled": True})
        assert merged["pose_enabled"] is False

    def test_input_is_not_mutated(self):
        fresh = {"phase": 6}
        preserve_existing_meta(fresh, {"share_token": "abc"})
        assert fresh == {"phase": 6}

    @pytest.mark.parametrize("bad", [None, {}, [], "meta", 7])
    def test_missing_or_malformed_previous_meta_is_a_no_op(self, bad):
        assert preserve_existing_meta({"phase": 6}, bad) == {"phase": 6}


# ------------------------------------------------------------------
# sharing — where the sidecar lives
# ------------------------------------------------------------------


class TestKeypointsPathForReport:
    def test_sits_in_a_keypoints_subdir_beside_the_report(self, tmp_path):
        path = sharing.keypoints_path_for_report(tmp_path / "r.json")
        assert path == tmp_path / sharing.KEYPOINTS_SUBDIR / "r.json"

    def test_follows_the_report_into_private(self, tmp_path):
        priv = sharing.private_dir(tmp_path)
        path = sharing.keypoints_path_for_report(priv / "r.json")
        assert path.parent == priv / sharing.KEYPOINTS_SUBDIR

    def test_sidecar_dir_is_invisible_to_the_report_walk(self, tmp_path):
        # The reason keypoints/ is a subdirectory and not a filename prefix:
        # iter_report_files globs *.json and every caller treats a hit as a
        # report, so a sidecar beside its report would be indexed as one.
        report = tmp_path / "r.json"
        report.write_text(json.dumps(_minimal_report()), encoding="utf-8")
        sidecar = sharing.keypoints_path_for_report(report)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps(_sidecar("r")), encoding="utf-8")

        found = list(sharing.iter_report_files(tmp_path))
        assert found == [report]

    def test_private_sidecar_is_invisible_too(self, tmp_path):
        priv = sharing.private_dir(tmp_path)
        priv.mkdir(parents=True, exist_ok=True)
        report = priv / "r.json"
        report.write_text(json.dumps(_minimal_report()), encoding="utf-8")
        sidecar = sharing.keypoints_path_for_report(report)
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps(_sidecar("r")), encoding="utf-8")

        assert list(sharing.iter_report_files(tmp_path)) == [report]


class TestResolveKeypointsPath:
    def _write(self, base, report_id):
        path = sharing.keypoints_dir(base) / f"{report_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_sidecar(report_id)), encoding="utf-8")
        return path

    def test_finds_a_public_sidecar(self, tmp_path):
        expected = self._write(tmp_path, "r")
        assert sharing.resolve_keypoints_path(tmp_path, "r") == expected

    def test_finds_a_private_sidecar(self, tmp_path):
        expected = self._write(sharing.private_dir(tmp_path), "r")
        assert sharing.resolve_keypoints_path(tmp_path, "r") == expected

    def test_private_wins_over_a_stale_public_copy(self, tmp_path):
        # Same fail-closed rule as resolve_report_path: resolving to the stale
        # public copy would serve an unlisted bout's skeleton ungated.
        self._write(tmp_path, "r")
        private = self._write(sharing.private_dir(tmp_path), "r")
        assert sharing.resolve_keypoints_path(tmp_path, "r") == private

    def test_none_when_absent(self, tmp_path):
        assert sharing.resolve_keypoints_path(tmp_path, "nope") is None

    def test_none_when_the_dir_does_not_exist(self, tmp_path):
        assert sharing.resolve_keypoints_path(tmp_path / "missing", "r") is None

    @pytest.mark.parametrize(
        "bad", ["", ".", "..", "../secret", "a/b", "a\\b", "a\x00b"],
    )
    def test_unsafe_ids_are_rejected(self, tmp_path, bad):
        assert sharing.resolve_keypoints_path(tmp_path, bad) is None

    def test_traversal_cannot_reach_a_sidecar_outside_the_dir(self, tmp_path):
        outside = tmp_path / "r.json"
        outside.write_text("{}", encoding="utf-8")
        kp = sharing.keypoints_dir(tmp_path)
        kp.mkdir(parents=True, exist_ok=True)
        assert sharing.resolve_keypoints_path(tmp_path, "../r") is None


# ------------------------------------------------------------------
# GET /api/analytics/keypoints/{report_id} — the access matrix
# ------------------------------------------------------------------


class TestKeypointsEndpoint:
    def test_public_report_with_a_sidecar_returns_200(self, client, keypoint_reports):
        resp = client.get(f"/api/analytics/keypoints/{KP_PUBLIC_ID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == KEYPOINTS_SCHEMA_VERSION
        assert body["report_id"] == KP_PUBLIC_ID
        assert len(body["poses"]["left"]) == body["sample_count"]

    def test_unlisted_report_is_404_without_a_token(self, client, keypoint_reports):
        resp = client.get(f"/api/analytics/keypoints/{KP_UNLISTED_ID}")
        assert resp.status_code == 404

    def test_unlisted_report_opens_with_its_token(self, client, keypoint_reports):
        token = keypoint_reports
        resp = client.get(f"/api/analytics/keypoints/{KP_UNLISTED_ID}?token={token}")
        assert resp.status_code == 200
        assert resp.json()["report_id"] == KP_UNLISTED_ID

    def test_wrong_token_is_404(self, client, keypoint_reports):
        resp = client.get(f"/api/analytics/keypoints/{KP_UNLISTED_ID}?token=wrong")
        assert resp.status_code == 404

    def test_hidden_and_missing_404s_are_byte_identical(self, client, keypoint_reports):
        # Probing ids must leak nothing: a bad token and an id that was never
        # there have to be indistinguishable.
        hidden = client.get(f"/api/analytics/keypoints/{KP_UNLISTED_ID}").json()["detail"]
        wrong = client.get(
            f"/api/analytics/keypoints/{KP_UNLISTED_ID}?token=wrong",
        ).json()["detail"]
        missing = client.get(
            f"/api/analytics/keypoints/{KP_UNLISTED_ID}",
        ).json()["detail"]
        assert hidden == wrong == missing
        assert hidden == f"Report not found: {KP_UNLISTED_ID}"

    def test_missing_report_uses_the_same_detail_string(self, client, keypoint_reports):
        gone = f"{KP_UNLISTED_ID}_nope"
        resp = client.get(f"/api/analytics/keypoints/{gone}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == f"Report not found: {gone}"

    def test_accessible_report_without_a_sidecar_says_so(self, client, keypoint_reports):
        # Only reachable after access is granted, so a distinct message leaks
        # nothing — and the page has to tell "not allowed" from "nothing to draw".
        resp = client.get(f"/api/analytics/keypoints/{KP_BARE_ID}")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Keypoints not found"

    def test_a_public_token_is_simply_ignored(self, client, keypoint_reports):
        resp = client.get(f"/api/analytics/keypoints/{KP_PUBLIC_ID}?token=whatever")
        assert resp.status_code == 200


# ------------------------------------------------------------------
# has_keypoints template flag
# ------------------------------------------------------------------


class TestHasKeypointsFlag:
    def test_true_for_a_report_with_a_sidecar(self, keypoint_reports):
        assert server._has_keypoints(KP_PUBLIC_ID) is True

    def test_true_for_an_unlisted_report(self, keypoint_reports):
        # The flag only decides whether the button renders; the endpoint does
        # the gating, and the page was already gated to get here.
        assert server._has_keypoints(KP_UNLISTED_ID) is True

    def test_false_for_a_report_without_one(self, keypoint_reports):
        assert server._has_keypoints(KP_BARE_ID) is False

    def test_false_for_an_unknown_id(self):
        assert server._has_keypoints("_pytest_kp_no_such_report") is False

    @pytest.mark.parametrize(
        "view", [server.report_page, server._render_saved_report],
    )
    def test_both_report_views_pass_the_flag(self, view):
        # /report/{job_id} and /report/saved/{id} render the same template, so
        # a flag added to only one leaves the toggle missing on half the routes.
        assert "has_keypoints" in inspect.getsource(view)


# ------------------------------------------------------------------
# Generator wiring
# ------------------------------------------------------------------


class TestGeneratorWiring:
    """Source checks on main(), which no unit test can call end to end.

    Running it needs a video, a YOLO model and minutes of inference, so the
    parts that are easy to drop in a refactor — writing the sidecar at all,
    building it from the streamed pose results rather than from buffered frames,
    preserving meta before the write — are asserted against the source instead.
    """

    def _main_source(self):
        import scripts.generate_continuous_report as module

        return inspect.getsource(module.main)

    def test_sidecar_is_written(self):
        src = self._main_source()
        assert "build_keypoints_sidecar(" in src
        assert "keypoints_path_for_report(" in src

    def test_sidecar_is_built_from_the_streamed_pose_results(self):
        # pose_results already holds joint coordinates for the whole bout (a few
        # KB per frame), so the sidecar costs nothing extra. Re-reading frames
        # to build it would reintroduce the buffer POSE_CHUNK_FRAMES exists to
        # bound.
        src = self._main_source()
        idx = src.index("build_keypoints_sidecar(")
        assert "pose_results" in src[idx:idx + 200]

    def test_chunked_streaming_survives(self):
        import scripts.generate_continuous_report as module

        assert module.POSE_CHUNK_FRAMES == 256
        assert "POSE_CHUNK_FRAMES" in self._main_source()

    def test_meta_is_preserved_before_the_report_is_written(self):
        src = self._main_source()
        assert "preserve_existing_meta(" in src
        assert src.index("_load_existing_meta(") < src.index(
            'with open(output_path, "w", encoding="utf-8") as f:',
        )

    def test_existing_report_is_resolved_through_the_private_aware_lookup(self):
        # A shared report has moved to data/reports/private/; a plain
        # output_dir/{id}.json probe would miss it and drop its share_token,
        # which is exactly the case preserving meta exists for.
        import scripts.generate_continuous_report as module

        assert "resolve_report_path(" in inspect.getsource(
            module._load_existing_meta,
        )
