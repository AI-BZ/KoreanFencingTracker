"""Tests for scripts/blade_labeling_server.py.

The behaviour worth protecting is resumption: a labelling session is hours of
human work, and a loader that quietly drops or mis-orders it is the one bug
that cannot be recovered from. Everything else here is HTTP surface.
"""

import json

import pytest
from fastapi.testclient import TestClient

from scripts.blade_labeling_server import (
    BladeLabelingState,
    FrameLabel,
    WindowLabel,
    create_app,
    flatten_frames,
    is_frame_done,
    load_frame_labels,
    load_window_labels,
    next_unlabeled_index,
    write_windows_csv,
)

MANIFEST = {
    "version": 1,
    "report_id": "r1",
    "source_fps": 60.0,
    "work_fps": 30,
    "windows": [
        {
            "window_id": "window_001",
            "reasons": ["touch_1"],
            "start_sec": 9.3667,
            "end_sec": 11.8667,
            "crop": {"x": 1681, "y": 1226, "w": 1996, "h": 696},
            "crop_source": "keypoints",
            "frames": [
                {"file": "frame_000562.jpg", "source_frame": 562, "work_frame": 281, "time_sec": 9.3667},
                {"file": "frame_000564.jpg", "source_frame": 564, "work_frame": 282, "time_sec": 9.4},
            ],
        },
        {
            "window_id": "window_002",
            "reasons": ["exchange_5"],
            "start_sec": 35.1667,
            "end_sec": 36.0,
            "crop": {"x": 0, "y": 1210, "w": 3840, "h": 750},
            "crop_source": "piste_fallback",
            "frames": [
                {"file": "frame_002110.jpg", "source_frame": 2110, "work_frame": 1055, "time_sec": 35.1667},
            ],
        },
    ],
}

FULL_POINTS = {"lg": [10.0, 20.0], "lt": [5.0, 21.0], "rg": [90.0, 22.0], "rt": [99.0, 23.0]}


@pytest.fixture
def data_dir(tmp_path):
    """A manifest plus one real JPEG per frame, so image serving is testable."""
    (tmp_path / "manifest.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    for window in MANIFEST["windows"]:
        wdir = tmp_path / window["window_id"]
        wdir.mkdir()
        for frame in window["frames"]:
            # Smallest thing that is unambiguously a JPEG on the wire.
            (wdir / frame["file"]).write_bytes(b"\xff\xd8\xff\xdb" + b"\x00" * 32 + b"\xff\xd9")
    return tmp_path


@pytest.fixture
def client(data_dir):
    return TestClient(create_app(BladeLabelingState(data_dir)))


# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------


def test_flatten_frames_preserves_manifest_order():
    rows = flatten_frames(MANIFEST)
    assert [r["frame"] for r in rows] == [562, 564, 2110]
    assert rows[0]["window_id"] == "window_001"
    assert rows[2]["window_id"] == "window_002"


def test_a_frame_with_all_four_points_is_done():
    assert is_frame_done({"points": FULL_POINTS, "not_visible": {"l": False, "r": False}})


def test_a_frame_missing_one_point_is_not_done():
    points = dict(FULL_POINTS, rt=None)
    assert not is_frame_done({"points": points, "not_visible": {"l": False, "r": False}})


def test_a_side_marked_not_visible_does_not_need_its_points():
    label = {
        "points": {"lg": [1.0, 2.0], "lt": [3.0, 4.0], "rg": None, "rt": None},
        "not_visible": {"l": False, "r": True},
    }
    assert is_frame_done(label)


def test_both_sides_hidden_still_counts_as_done():
    label = {"points": {}, "not_visible": {"l": True, "r": True}}
    assert is_frame_done(label)


def test_a_skipped_frame_is_done():
    assert is_frame_done({"skipped": True, "points": {}, "not_visible": {}})


def test_an_absent_label_is_not_done():
    assert not is_frame_done(None)


def test_next_unlabeled_skips_finished_frames_and_wraps():
    frames = flatten_frames(MANIFEST)
    labels = {562: {"points": FULL_POINTS, "not_visible": {}}}
    assert next_unlabeled_index(frames, labels, 0) == 1
    # From past the end of the list it wraps to the first unfinished frame.
    assert next_unlabeled_index(frames, labels, 3) == 1


def test_next_unlabeled_returns_the_start_when_everything_is_done():
    frames = flatten_frames(MANIFEST)
    labels = {f["frame"]: {"skipped": True} for f in frames}
    assert next_unlabeled_index(frames, labels, 1) == 1


def test_next_unlabeled_handles_an_empty_manifest():
    assert next_unlabeled_index([], {}, 5) == 0


# ----------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------


def test_load_frame_labels_keeps_the_last_row_for_a_frame(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text(
        json.dumps({"frame": 562, "points": {"lg": [1, 1]}}) + "\n"
        + json.dumps({"frame": 562, "points": {"lg": [9, 9]}}) + "\n",
        encoding="utf-8",
    )
    assert load_frame_labels(path)[562]["points"]["lg"] == [9, 9]


def test_load_frame_labels_survives_a_truncated_last_line(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text(
        json.dumps({"frame": 562, "points": {}}) + "\n" + '{"frame": 564, "poin',
        encoding="utf-8",
    )
    labels = load_frame_labels(path)
    assert 562 in labels
    assert 564 not in labels


def test_load_frame_labels_on_a_missing_file_is_empty(tmp_path):
    assert load_frame_labels(tmp_path / "nope.jsonl") == {}


def test_window_labels_round_trip_through_csv(tmp_path):
    path = tmp_path / "windows.csv"
    write_windows_csv(
        path, MANIFEST,
        {
            "window_001": {"window_id": "window_001", "contact_label": "contact"},
            "window_002": {"window_id": "window_002", "contact_label": "unclear"},
        },
        {"window_001": [564]},
    )
    assert "window_001,contact,564" in path.read_text(encoding="utf-8")
    loaded = load_window_labels(path)
    assert loaded["window_001"]["contact_label"] == "contact"
    assert loaded["window_002"]["contact_label"] == "unclear"


def test_marked_frames_make_a_window_a_contact_in_the_csv(tmp_path):
    """The frames are the specific claim, so they set the written verdict."""
    path = tmp_path / "windows.csv"
    write_windows_csv(
        path, MANIFEST,
        {"window_001": {"window_id": "window_001", "contact_label": "no_contact"}},
        {"window_001": [562, 564]},
    )
    assert "window_001,contact,562;564" in path.read_text(encoding="utf-8")


def test_windows_csv_is_written_in_manifest_order(tmp_path):
    path = tmp_path / "windows.csv"
    write_windows_csv(path, MANIFEST, {
        "window_002": {"window_id": "window_002", "contact_label": "contact"},
        "window_001": {"window_id": "window_001", "contact_label": "no_contact"},
    })
    rows = path.read_text(encoding="utf-8").strip().splitlines()
    assert rows[0] == "window_id,contact_label,contact_frames"
    assert rows[1].startswith("window_001")
    assert rows[2].startswith("window_002")


def test_state_resumes_from_disk_after_a_restart(data_dir):
    first = BladeLabelingState(data_dir)
    first.save_frame_label(FrameLabel(window_id="window_001", frame=562, points=FULL_POINTS))
    first.save_frame_label(FrameLabel(window_id="window_001", frame=564, points=FULL_POINTS, contact=True))

    second = BladeLabelingState(data_dir)
    assert second.stats()["frames_done"] == 2
    assert second.stats()["windows_judged"] == 1
    assert second.frame_info(0)["done"] is True
    assert second.frame_info(0)["window"]["label"]["contact_frames"] == [564]
    assert second.frame_info(0)["window"]["label"]["contact_label"] == "contact"
    # Resuming picks up at the first frame that is still unlabelled.
    assert next_unlabeled_index(second.frames, second.labels, 0) == 2


def test_saving_appends_rather_than_rewrites(data_dir):
    state = BladeLabelingState(data_dir)
    state.save_frame_label(FrameLabel(window_id="window_001", frame=562, points=FULL_POINTS))
    state.save_frame_label(FrameLabel(window_id="window_001", frame=562, points=FULL_POINTS, skipped=True))
    lines = state.labels_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[-1])["skipped"] is True


def test_state_needs_a_manifest(tmp_path):
    with pytest.raises(FileNotFoundError, match="manifest.json"):
        BladeLabelingState(tmp_path)


def test_saving_an_unknown_window_is_refused(data_dir):
    state = BladeLabelingState(data_dir)
    with pytest.raises(ValueError, match="unknown window"):
        state.save_frame_label(FrameLabel(window_id="window_999", frame=562))


def test_saving_an_unknown_frame_is_refused(data_dir):
    state = BladeLabelingState(data_dir)
    with pytest.raises(ValueError, match="unknown frame"):
        state.save_frame_label(FrameLabel(window_id="window_001", frame=99999))


def test_marking_contact_on_a_frame_makes_the_window_a_contact(data_dir):
    state = BladeLabelingState(data_dir)
    state.save_frame_label(
        FrameLabel(window_id="window_001", frame=564, points=FULL_POINTS, contact=True)
    )
    verdict = state.window_verdict("window_001")
    assert verdict["contact_label"] == "contact"
    assert verdict["contact_frames"] == [564]


def test_an_invalid_contact_label_is_refused(data_dir):
    state = BladeLabelingState(data_dir)
    with pytest.raises(ValueError, match="contact_label"):
        state.save_window_label(WindowLabel(window_id="window_001", contact_label="maybe"))


@pytest.mark.parametrize("label", ["no_contact", "unclear"])
def test_a_sweeping_verdict_cannot_erase_marked_contact_frames(data_dir, label):
    """The bug this guards: one verdict per window, last press wins.

    The labeller marks contact on the frame the blades meet, then keeps
    walking the same phrase and judges a later frame no_contact — which used
    to overwrite the whole window and silently drop the contact.
    """
    state = BladeLabelingState(data_dir)
    state.save_frame_label(
        FrameLabel(window_id="window_001", frame=564, points=FULL_POINTS, contact=True)
    )
    with pytest.raises(ValueError, match="clear those first"):
        state.save_window_label(WindowLabel(window_id="window_001", contact_label=label))
    assert state.window_verdict("window_001")["contact_frames"] == [564]


def test_clearing_the_frame_releases_the_window_for_a_new_verdict(data_dir):
    state = BladeLabelingState(data_dir)
    state.save_frame_label(
        FrameLabel(window_id="window_001", frame=564, points=FULL_POINTS, contact=True)
    )
    state.save_frame_label(
        FrameLabel(window_id="window_001", frame=564, points=FULL_POINTS, contact=False)
    )
    row = state.save_window_label(WindowLabel(window_id="window_001", contact_label="no_contact"))
    assert row["contact_label"] == "no_contact"
    assert state.window_verdict("window_001")["contact_frames"] == []


# ----------------------------------------------------------------------
# HTTP surface
# ----------------------------------------------------------------------


def test_index_serves_the_labelling_page(client):
    body = client.get("/").text
    assert "Blade labeling" in body
    assert "/api/label" in body


def test_frame_endpoint_carries_the_window_context(client):
    info = client.get("/api/frame/0").json()
    assert info["frame"] == 562
    assert info["image_url"] == "/image/window_001/frame_000562.jpg"
    assert info["window"]["reasons"] == ["touch_1"]
    assert info["window"]["position"] == 1
    assert info["window"]["frame_count"] == 2


def test_frame_endpoint_404s_past_the_end(client):
    assert client.get("/api/frame/999").status_code == 404


def test_images_are_served_from_the_manifest(client):
    response = client.get("/image/window_001/frame_000562.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_an_image_path_outside_the_manifest_is_refused(client):
    assert client.get("/image/window_001/../../manifest.json").status_code == 404
    assert client.get("/image/window_001/secrets.jpg").status_code == 404
    assert client.get("/image/window_999/frame_000562.jpg").status_code == 404


def test_posting_a_label_marks_the_frame_done(client):
    response = client.post("/api/label", json={
        "window_id": "window_001", "frame": 562, "points": FULL_POINTS,
        "not_visible": {"l": False, "r": False},
    })
    assert response.json() == {"ok": True, "label": response.json()["label"], "done": True}
    assert client.get("/api/stats").json()["frames_done"] == 1


def test_posting_a_partial_label_leaves_the_frame_in_the_queue(client):
    client.post("/api/label", json={"window_id": "window_001", "frame": 562, "points": {"lg": [1, 2]}})
    assert client.get("/api/stats").json()["frames_done"] == 0
    assert client.get("/api/next-unlabeled/0").json()["index"] == 0


def test_a_malformed_point_is_refused(client):
    response = client.post("/api/label", json={
        "window_id": "window_001", "frame": 562, "points": {"lg": [1, 2, 3]},
    })
    assert response.status_code == 400
    assert "point lg" in response.json()["error"]


def test_posting_a_window_judgement_updates_the_csv(client, data_dir):
    response = client.post("/api/window", json={
        "window_id": "window_001", "contact_label": "no_contact",
    })
    assert response.json()["ok"] is True
    assert "window_001,no_contact," in (data_dir / "windows.csv").read_text(encoding="utf-8")
    assert client.get("/api/stats").json()["contact_distribution"] == {"no_contact": 1}


def test_marking_a_frame_contact_updates_the_csv(client, data_dir):
    response = client.post("/api/label", json={
        "window_id": "window_001", "frame": 564, "points": FULL_POINTS, "contact": True,
    })
    assert response.json()["ok"] is True
    assert "window_001,contact,564" in (data_dir / "windows.csv").read_text(encoding="utf-8")
    stats = client.get("/api/stats").json()
    assert stats["contact_distribution"] == {"contact": 1}
    assert stats["contact_frames_total"] == 1


def test_a_later_no_contact_cannot_wipe_a_marked_frame_over_http(client):
    client.post("/api/label", json={
        "window_id": "window_001", "frame": 564, "points": FULL_POINTS, "contact": True,
    })
    response = client.post("/api/window", json={
        "window_id": "window_001", "contact_label": "no_contact",
    })
    assert response.status_code == 400
    assert "clear those first" in response.json()["error"]
    assert client.get("/api/frame/0").json()["window"]["label"]["contact_frames"] == [564]


def test_frames_endpoint_reports_progress_per_frame(client):
    client.post("/api/label", json={"window_id": "window_001", "frame": 562, "points": FULL_POINTS})
    frames = client.get("/api/frames").json()
    assert frames["total"] == 3
    assert frames["frames"][0]["done"] is True
    assert frames["frames"][1]["done"] is False


# ----------------------------------------------------------------------
# Missed parries
# ----------------------------------------------------------------------


def test_a_missed_parry_attempt_is_recorded_with_its_side(data_dir):
    state = BladeLabelingState(data_dir)
    row = state.save_frame_label(
        FrameLabel(window_id="window_001", frame=562, points=FULL_POINTS, parry_attempt="right")
    )
    assert row["parry_attempt"] == "right"
    assert state.stats()["parry_attempt_frames_total"] == 1


def test_a_missed_parry_does_not_make_the_window_a_contact(data_dir):
    """The blades never met, so there is nothing for a contact verdict to point at."""
    state = BladeLabelingState(data_dir)
    state.save_frame_label(
        FrameLabel(window_id="window_001", frame=562, points=FULL_POINTS, parry_attempt="left")
    )
    assert state.window_contact_frames("window_001") == []
    row = state.save_window_label(WindowLabel(window_id="window_001", contact_label="no_contact"))
    assert row["contact_label"] == "no_contact"


def test_a_frame_cannot_be_both_a_contact_and_a_missed_parry(data_dir):
    state = BladeLabelingState(data_dir)
    with pytest.raises(ValueError, match="both a contact and a missed parry"):
        state.save_frame_label(
            FrameLabel(window_id="window_001", frame=562, points=FULL_POINTS,
                       contact=True, parry_attempt="left")
        )


def test_an_unknown_parry_side_is_refused(data_dir):
    state = BladeLabelingState(data_dir)
    with pytest.raises(ValueError, match="parry_attempt must be"):
        state.save_frame_label(
            FrameLabel(window_id="window_001", frame=562, points=FULL_POINTS, parry_attempt="middle")
        )


def test_a_save_that_omits_contact_keeps_it(data_dir):
    """A tab open across a deploy must not clear what it does not know about.

    Two recorded parry attempts were lost exactly this way: the client sent a
    frame's points without the newer field, and the frame came back cleared.
    """
    state = BladeLabelingState(data_dir)
    state.save_frame_label(FrameLabel(window_id="window_001", frame=562, contact=True))
    row = state.save_frame_label(FrameLabel(window_id="window_001", frame=562, points=FULL_POINTS))
    assert row["contact"] is True
    assert state.window_contact_frames("window_001") == [562]


def test_a_save_that_omits_the_parry_attempt_keeps_it(data_dir):
    state = BladeLabelingState(data_dir)
    state.save_frame_label(FrameLabel(window_id="window_001", frame=562, parry_attempt="right"))
    row = state.save_frame_label(FrameLabel(window_id="window_001", frame=562, points=FULL_POINTS))
    assert row["parry_attempt"] == "right"


def test_sending_the_field_explicitly_still_clears_it(data_dir):
    state = BladeLabelingState(data_dir)
    state.save_frame_label(FrameLabel(window_id="window_001", frame=562, contact=True))
    row = state.save_frame_label(
        FrameLabel(window_id="window_001", frame=562, points=FULL_POINTS, contact=False)
    )
    assert row["contact"] is False
