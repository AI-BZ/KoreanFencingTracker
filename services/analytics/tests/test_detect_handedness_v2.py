"""Offline handedness detection from a keypoint sidecar.

The detector itself is covered in ``test_pose_analyzer.py``; these tests cover
the script that feeds it — decoding the sidecar's flat int arrays back into
poses, and the ``--write`` path that edits a saved report.

The write path is the part that matters. A report holds lamp readings, share
tokens and touch data that nothing else would put back, so the edit has to
touch three fields per fencer and leave every other byte, and every key's
position, exactly as it found them.
"""

import json

import pytest

from analyzer.config import (
    KP_LEFT_ANKLE, KP_RIGHT_ANKLE,
    KP_LEFT_WRIST, KP_RIGHT_WRIST,
    KP_LEFT_SHOULDER, KP_RIGHT_SHOULDER,
    KP_LEFT_HIP, KP_RIGHT_HIP,
)
from analyzer.models import PoseResult
from ml.pose_analysis.kinematics import detect_handedness_v2
import scripts.detect_handedness_v2 as module
from scripts.detect_handedness_v2 import (
    HANDEDNESS_SOURCE,
    apply_verdicts,
    decode_fencer,
    decode_sidecar,
    main,
    normalize_report_id,
    verdict_to_dict,
    write_report,
)


# Neutral stems only — never a real fencer's name, in any fixture.
REPORT_ID = "260815_pool_home_vs_away"
OTHER_REPORT_ID = "260816_venue2_bout"

CONF_SCALE = 100


# ------------------------------------------------------------------
# Fixtures / builders
# ------------------------------------------------------------------


def flat_pose(cx, lead, *, side, limb_conf=90, torso_conf=90):
    """One sidecar row: 17 joints as ``[x, y, c, ...]`` with ints, as written.

    Torso spans y=100..200 so the body scale is 100px; limbs sit 20px either
    side of centre, giving a separation ratio of 0.4.
    """
    toward_opponent = 1 if side == "left" else -1
    lead_dir = toward_opponent if lead == "left" else -toward_opponent

    joints = [(cx, 70, torso_conf)] * 17
    joints = list(joints)
    joints[KP_LEFT_SHOULDER] = (cx - 20, 100, torso_conf)
    joints[KP_RIGHT_SHOULDER] = (cx + 20, 100, torso_conf)
    joints[KP_LEFT_HIP] = (cx - 20, 200, torso_conf)
    joints[KP_RIGHT_HIP] = (cx + 20, 200, torso_conf)
    joints[KP_LEFT_ANKLE] = (cx + lead_dir * 20, 400, limb_conf)
    joints[KP_RIGHT_ANKLE] = (cx - lead_dir * 20, 400, limb_conf)
    joints[KP_LEFT_WRIST] = (cx + lead_dir * 20, 150, limb_conf)
    joints[KP_RIGHT_WRIST] = (cx - lead_dir * 20, 150, limb_conf)

    flat = []
    for x, y, c in joints:
        flat.extend([int(x), int(y), int(c)])
    return flat


def make_sidecar(n_samples=50, left_lead="left", right_lead="right", gaps=()):
    """A sidecar document; indices in ``gaps`` have no left-fencer detection."""
    left = []
    right = []
    for i in range(n_samples):
        left.append(None if i in gaps else flat_pose(200, left_lead, side="left"))
        right.append(flat_pose(600, right_lead, side="right"))
    return {
        "version": 1,
        "report_id": REPORT_ID,
        "fps": 30.0,
        "sample_every": 3,
        "frame_width": 1280,
        "frame_height": 330,
        "sample_count": n_samples,
        "min_confidence": 0.3,
        "conf_scale": CONF_SCALE,
        "poses": {"left": left, "right": right},
    }


def make_report():
    """A minimal report with the surrounding fields the writer must preserve."""
    return {
        "summary": {"final_score": "5-3"},
        "touches": [{"touch_number": 1, "lamp_pattern": "red"}],
        "left_fencer": {
            "name": "Home",
            "club": "",
            "handedness": None,
            "handedness_confidence": 0.038,
            "total_touches_scored": 5,
        },
        "right_fencer": {
            "name": "Away",
            "club": "",
            "handedness": None,
            "handedness_confidence": 0.041,
            "total_touches_scored": 3,
        },
        "meta": {"share_token": "abc123", "visibility": "unlisted"},
    }


@pytest.fixture
def reports_root(tmp_path, monkeypatch):
    """A throwaway reports tree, wired in place of the real one."""
    private = tmp_path / "private"
    (private / "keypoints").mkdir(parents=True)
    monkeypatch.setattr(module, "REPORTS_DIR", tmp_path)
    return tmp_path


def write_json(path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------
# Sidecar decoding
# ------------------------------------------------------------------


class TestDecodeFencer:

    def test_flat_list_becomes_seventeen_keypoints(self):
        f = decode_fencer(flat_pose(200, "left", side="left"), "left", CONF_SCALE)
        assert f is not None
        assert len(f.keypoints) == 17
        assert f.side == "left"

    def test_index_i_occupies_three_slots(self):
        """Joint i is at positions [3i, 3i+1, 3i+2], not interleaved otherwise."""
        flat = [0.0] * 51
        flat[3 * KP_LEFT_ANKLE] = 111.0
        flat[3 * KP_LEFT_ANKLE + 1] = 222.0
        flat[3 * KP_LEFT_ANKLE + 2] = 55.0
        f = decode_fencer(flat, "left", CONF_SCALE)
        assert (f.keypoints[KP_LEFT_ANKLE].x, f.keypoints[KP_LEFT_ANKLE].y) == (111.0, 222.0)

    def test_confidence_is_divided_by_conf_scale(self):
        """Stored as a small int; the reader restores the 0-1 float."""
        f = decode_fencer(flat_pose(200, "left", side="left", limb_conf=87), "left", CONF_SCALE)
        assert f.keypoints[KP_LEFT_ANKLE].confidence == pytest.approx(0.87)

    def test_null_row_is_not_a_pose(self):
        """A missed detection must not become a fencer standing at the origin."""
        assert decode_fencer(None, "left", CONF_SCALE) is None

    def test_wrong_length_row_is_dropped(self):
        assert decode_fencer([0.0] * 48, "left", CONF_SCALE) is None

    def test_non_numeric_row_is_dropped(self):
        flat = [0.0] * 51
        flat[7] = "x"
        assert decode_fencer(flat, "left", CONF_SCALE) is None

    def test_bbox_spans_the_joints(self):
        f = decode_fencer(flat_pose(200, "left", side="left"), "left", CONF_SCALE)
        xs = [kp.x for kp in f.keypoints]
        ys = [kp.y for kp in f.keypoints]
        assert f.bbox == [min(xs), min(ys), max(xs), max(ys)]


class TestDecodeSidecar:

    def test_one_pose_result_per_sample(self):
        seq = decode_sidecar(make_sidecar(n_samples=12))
        assert len(seq) == 12
        assert all(isinstance(pr, PoseResult) for pr in seq)
        assert [pr.frame_idx for pr in seq] == list(range(12))

    def test_both_sides_land_in_the_same_frame(self):
        """The two arrays are parallel, so index i is one moment in the bout."""
        seq = decode_sidecar(make_sidecar(n_samples=3))
        sides = {f.side for f in seq[0].fencers}
        assert sides == {"left", "right"}

    def test_null_entries_are_skipped_not_faked(self):
        seq = decode_sidecar(make_sidecar(n_samples=5, gaps={1, 3}))
        assert [f.side for f in seq[1].fencers] == ["right"]
        assert {f.side for f in seq[0].fencers} == {"left", "right"}

    def test_missing_poses_block_gives_empty_sequence(self):
        assert decode_sidecar({"conf_scale": 100}) == []

    def test_unequal_column_lengths_use_the_longer_one(self):
        doc = make_sidecar(n_samples=4)
        doc["poses"]["right"] = doc["poses"]["right"][:2]
        seq = decode_sidecar(doc)
        assert len(seq) == 4
        assert [f.side for f in seq[3].fencers] == ["left"]

    def test_absent_conf_scale_does_not_zero_every_confidence(self):
        """A missing or zero divisor falls back to 1, never to a divide-by-zero."""
        doc = make_sidecar(n_samples=1)
        doc["conf_scale"] = 0
        seq = decode_sidecar(doc)
        assert seq[0].fencers[0].keypoints[KP_LEFT_ANKLE].confidence == 90.0

    def test_decoded_sequence_feeds_the_detector(self):
        """End to end: a left-leading sidecar reads as a left-hander."""
        seq = decode_sidecar(make_sidecar(n_samples=50, left_lead="left"))
        v = detect_handedness_v2(seq, "left")
        assert v.handedness == "left"
        assert v.frames_used == 50

    def test_decoded_sequence_detects_the_right_fencer_too(self):
        seq = decode_sidecar(make_sidecar(n_samples=50, right_lead="right"))
        v = detect_handedness_v2(seq, "right")
        assert v.handedness == "right"


# ------------------------------------------------------------------
# Report editing
# ------------------------------------------------------------------


class TestApplyVerdicts:

    def _verdicts(self, doc=None):
        seq = decode_sidecar(doc or make_sidecar(n_samples=50))
        return {side: detect_handedness_v2(seq, side) for side in ("left", "right")}

    def test_sets_the_three_fields_on_both_fencers(self):
        report = make_report()
        apply_verdicts(report, self._verdicts())
        assert report["left_fencer"]["handedness"] == "left"
        assert report["right_fencer"]["handedness"] == "right"
        for key in ("left_fencer", "right_fencer"):
            assert report[key]["handedness_source"] == HANDEDNESS_SOURCE
            assert report[key]["handedness_confidence"] == 1.0

    def test_leaves_every_other_field_alone(self):
        report = make_report()
        before = json.loads(json.dumps(report))
        apply_verdicts(report, self._verdicts())

        assert report["summary"] == before["summary"]
        assert report["touches"] == before["touches"]
        assert report["meta"] == before["meta"]
        assert report["left_fencer"]["name"] == before["left_fencer"]["name"]
        assert report["left_fencer"]["total_touches_scored"] == 5

    def test_preserves_existing_key_order(self):
        """Assigning to a key keeps its slot; the new one lands at the end."""
        report = make_report()
        before = list(report["left_fencer"])
        apply_verdicts(report, self._verdicts())
        assert list(report["left_fencer"]) == before + ["handedness_source"]
        assert list(report) == list(make_report())

    def test_a_user_confirmed_handedness_is_never_overwritten(self):
        """A coach's statement outranks the detector; a re-run must not lose it."""
        report = make_report()
        report["left_fencer"].update({
            "handedness": "right",
            "handedness_confidence": 1.0,
            "handedness_source": module.USER_CONFIRMED_SOURCE,
        })

        skipped = apply_verdicts(report, self._verdicts())

        assert skipped == ["left"]
        assert report["left_fencer"]["handedness"] == "right"
        assert report["left_fencer"]["handedness_source"] == module.USER_CONFIRMED_SOURCE
        # The other side had no such claim on it and is still updated.
        assert report["right_fencer"]["handedness_source"] == HANDEDNESS_SOURCE

    def test_force_overwrites_a_user_confirmed_handedness(self):
        report = make_report()
        report["left_fencer"]["handedness_source"] = module.USER_CONFIRMED_SOURCE

        assert apply_verdicts(report, self._verdicts(), force=True) == []
        assert report["left_fencer"]["handedness_source"] == HANDEDNESS_SOURCE

    def test_a_detected_source_is_not_protected(self):
        """Only a human's claim is sticky — re-running over our own output is fine."""
        report = make_report()
        report["left_fencer"]["handedness_source"] = HANDEDNESS_SOURCE
        assert apply_verdicts(report, self._verdicts()) == []

    def test_undetermined_verdict_is_written_as_null(self):
        """A refusal is a result; masking it would leave a stale value in place."""
        report = make_report()
        report["left_fencer"]["handedness"] = "right"
        apply_verdicts(report, self._verdicts(make_sidecar(n_samples=5)))
        assert report["left_fencer"]["handedness"] is None
        assert report["left_fencer"]["handedness_confidence"] == 0.0


class TestWriteReport:

    def test_round_trips_through_the_file(self, tmp_path):
        path = tmp_path / f"{REPORT_ID}.json"
        report = make_report()
        write_report(path, report)
        assert json.loads(path.read_text(encoding="utf-8")) == report

    def test_formatting_matches_the_reports_on_disk(self, tmp_path):
        path = tmp_path / f"{REPORT_ID}.json"
        write_report(path, {"name": "한글", "n": 1})
        text = path.read_text(encoding="utf-8")
        assert text.endswith("\n")
        assert "한글" in text  # ensure_ascii=False
        assert '\n  "n": 1' in text  # indent=2

    def test_creates_the_directory(self, tmp_path):
        path = tmp_path / "private" / f"{REPORT_ID}.json"
        write_report(path, {"a": 1})
        assert path.is_file()

    def test_leaves_no_temp_file_behind(self, tmp_path):
        path = tmp_path / f"{REPORT_ID}.json"
        write_report(path, make_report())
        assert [p.name for p in tmp_path.iterdir()] == [path.name]

    def test_failed_write_does_not_truncate_the_original(self, tmp_path):
        """An unserialisable report leaves the previous file intact."""
        path = tmp_path / f"{REPORT_ID}.json"
        write_report(path, {"keep": "me"})
        with pytest.raises(TypeError):
            write_report(path, {"bad": object()})
        assert json.loads(path.read_text(encoding="utf-8")) == {"keep": "me"}
        assert [p.name for p in tmp_path.iterdir()] == [path.name]


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------


class TestCli:

    def test_missing_sidecar_exits_two(self, reports_root, capsys):
        assert main([REPORT_ID]) == 2
        assert "no keypoint sidecar" in capsys.readouterr().err

    def test_prints_both_sides_with_per_limb_breakdown(self, reports_root, capsys):
        write_json(reports_root / "private" / "keypoints" / f"{REPORT_ID}.json", make_sidecar())
        assert main([REPORT_ID]) == 0
        out = capsys.readouterr().out
        assert "left fencer" in out and "right fencer" in out
        assert "ankle" in out and "wrist" in out

    def test_json_output_carries_the_verdicts(self, reports_root, capsys):
        write_json(reports_root / "private" / "keypoints" / f"{REPORT_ID}.json", make_sidecar())
        assert main([REPORT_ID, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["report_id"] == REPORT_ID
        assert payload["written_to"] is None
        assert payload["fencers"]["left"]["handedness"] == "left"
        assert payload["fencers"]["right"]["per_limb"]["ankle"]["frames"] == 50

    def test_trailing_json_suffix_on_the_id_is_accepted(self, reports_root, capsys):
        write_json(reports_root / "private" / "keypoints" / f"{REPORT_ID}.json", make_sidecar())
        assert main([f"{REPORT_ID}.json"]) == 0
        assert normalize_report_id(f"{REPORT_ID}.json") == REPORT_ID

    def test_default_run_never_touches_the_report(self, reports_root, capsys):
        write_json(reports_root / "private" / "keypoints" / f"{REPORT_ID}.json", make_sidecar())
        report_path = reports_root / "private" / f"{REPORT_ID}.json"
        write_json(report_path, make_report())
        before = report_path.read_text(encoding="utf-8")

        assert main([REPORT_ID]) == 0
        assert report_path.read_text(encoding="utf-8") == before

    def test_write_updates_the_report(self, reports_root, capsys):
        write_json(reports_root / "private" / "keypoints" / f"{REPORT_ID}.json", make_sidecar())
        report_path = reports_root / "private" / f"{REPORT_ID}.json"
        write_json(report_path, make_report())

        assert main([REPORT_ID, "--write"]) == 0
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        assert saved["left_fencer"]["handedness"] == "left"
        assert saved["right_fencer"]["handedness"] == "right"
        assert saved["left_fencer"]["handedness_source"] == HANDEDNESS_SOURCE
        assert saved["meta"]["share_token"] == "abc123"
        assert saved["touches"] == make_report()["touches"]

    def _confirmed_report(self):
        report = make_report()
        for key, hand in (("left_fencer", "right"), ("right_fencer", "left")):
            report[key].update({
                "handedness": hand,
                "handedness_confidence": 1.0,
                "handedness_source": module.USER_CONFIRMED_SOURCE,
            })
        return report

    def test_write_leaves_a_fully_user_confirmed_report_untouched(self, reports_root, capsys):
        """Not even a rewrite with identical bytes — the file is not opened for writing."""
        write_json(reports_root / "private" / "keypoints" / f"{REPORT_ID}.json", make_sidecar())
        report_path = reports_root / "private" / f"{REPORT_ID}.json"
        write_json(report_path, self._confirmed_report())
        before = report_path.read_text(encoding="utf-8")

        assert main([REPORT_ID, "--write"]) == 0
        assert report_path.read_text(encoding="utf-8") == before
        out = capsys.readouterr().out
        assert module.USER_CONFIRMED_SOURCE in out and "--force" in out
        assert "wrote handedness" not in out

    def test_force_overwrites_a_user_confirmed_report(self, reports_root, capsys):
        write_json(reports_root / "private" / "keypoints" / f"{REPORT_ID}.json", make_sidecar())
        report_path = reports_root / "private" / f"{REPORT_ID}.json"
        write_json(report_path, self._confirmed_report())

        assert main([REPORT_ID, "--write", "--force"]) == 0
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        assert saved["left_fencer"]["handedness"] == "left"
        assert saved["left_fencer"]["handedness_source"] == HANDEDNESS_SOURCE

    def test_json_output_names_the_sides_it_kept(self, reports_root, capsys):
        write_json(reports_root / "private" / "keypoints" / f"{REPORT_ID}.json", make_sidecar())
        report_path = reports_root / "private" / f"{REPORT_ID}.json"
        write_json(report_path, self._confirmed_report())

        assert main([REPORT_ID, "--write", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["kept_user_confirmed"] == ["left", "right"]
        assert payload["written_to"] is None

    def test_write_without_a_report_exits_two(self, reports_root, capsys):
        write_json(reports_root / "private" / "keypoints" / f"{REPORT_ID}.json", make_sidecar())
        assert main([REPORT_ID, "--write"]) == 2
        assert "no such report" in capsys.readouterr().err

    def test_write_refuses_a_report_with_no_fencer_block(self, reports_root, capsys):
        write_json(reports_root / "private" / "keypoints" / f"{REPORT_ID}.json", make_sidecar())
        report_path = reports_root / "private" / f"{REPORT_ID}.json"
        report = make_report()
        del report["right_fencer"]
        write_json(report_path, report)

        assert main([REPORT_ID, "--write"]) == 1
        # Refused outright, so the other fencer is not half-updated either.
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        assert saved["left_fencer"]["handedness"] is None
        assert "handedness_source" not in saved["left_fencer"]

    def test_private_sidecar_wins_over_the_public_one(self, reports_root, capsys):
        """Same precedence as resolve_report_path: a stale public copy loses."""
        (reports_root / "keypoints").mkdir()
        write_json(
            reports_root / "keypoints" / f"{OTHER_REPORT_ID}.json",
            make_sidecar(n_samples=50, left_lead="right"),
        )
        write_json(
            reports_root / "private" / "keypoints" / f"{OTHER_REPORT_ID}.json",
            make_sidecar(n_samples=50, left_lead="left"),
        )
        assert main([OTHER_REPORT_ID, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["fencers"]["left"]["handedness"] == "left"

    def test_public_sidecar_is_found_when_there_is_no_private_one(self, reports_root, capsys):
        (reports_root / "keypoints").mkdir()
        write_json(reports_root / "keypoints" / f"{OTHER_REPORT_ID}.json", make_sidecar())
        assert main([OTHER_REPORT_ID]) == 0


class TestVerdictSerialization:

    def test_verdict_to_dict_shape(self):
        seq = decode_sidecar(make_sidecar(n_samples=50))
        d = verdict_to_dict(detect_handedness_v2(seq, "left"))
        assert set(d) == {
            "handedness", "confidence", "frames_used",
            "left_weight", "right_weight", "per_limb",
        }
        assert set(d["per_limb"]) == {"ankle", "wrist"}
        assert set(d["per_limb"]["ankle"]) == {"handedness", "confidence", "frames"}
        assert json.loads(json.dumps(d)) == d
