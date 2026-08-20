"""Pure-logic tests for scripts/extract_blade_windows.py.

Nothing here decodes video. What is worth pinning down is the arithmetic that
silently produces *wrong* frames rather than an error: the work-frame-to-time
bridge, the merge, and the crop-coordinate inversion.
"""

import json

import pytest

from scripts.extract_blade_windows import (
    MANIFEST_VERSION,
    Window,
    build_extract_command,
    build_manifest,
    crop_box_for_points,
    decode_pose_sample,
    keypoints_in_window,
    merge_windows,
    parry_windows,
    piste_fallback_box,
    sampling_step,
    seconds_to_source_frame,
    touch_windows,
    window_source_frames,
    work_frame_to_seconds,
    work_to_source_scale,
    work_to_source_xy,
)

PISTE_CROP = {"x": 0, "y": 1210, "w": 3840, "h": 750}
SCALE_WIDTH = 1280
SOURCE_RES = (3840, 2160)


# ----------------------------------------------------------------------
# Frame / time mapping
# ----------------------------------------------------------------------


def test_work_frame_to_seconds_matches_the_verified_touch_times():
    # Touch 1 of 260716_de64_s1_piste3 sits on work frame 341; the 4K source
    # frame at that instant was confirmed pixel-for-pixel to be 682.
    assert work_frame_to_seconds(341, 30) == pytest.approx(11.3667, abs=1e-4)
    assert seconds_to_source_frame(work_frame_to_seconds(341, 30), 60) == 682


def test_frame_mapping_stays_exact_at_the_end_of_a_long_bout():
    # A count-based mapping through the container's 59.97 average fps drifts
    # ~8 frames by here; the time-based one must not.
    assert seconds_to_source_frame(work_frame_to_seconds(8753, 30), 60) == 17506


def test_work_frame_to_seconds_rejects_a_nonsense_rate():
    with pytest.raises(ValueError):
        work_frame_to_seconds(100, 0)


def test_sampling_step_divides_evenly():
    assert sampling_step(60.0, 30) == 2
    assert sampling_step(60.0, 60) == 1
    assert sampling_step(60.0, 15) == 4


def test_sampling_step_refuses_a_non_divisor():
    with pytest.raises(ValueError, match="does not divide"):
        sampling_step(60.0, 25)


def test_window_source_frames_lands_on_the_sampling_grid():
    frames = window_source_frames(Window(9.3667, 11.8667), 60.0, 30)
    assert frames[0] == 562
    assert frames[-1] == 712
    assert all(f % 2 == 0 for f in frames)
    assert len(frames) == 76


def test_window_source_frames_snaps_a_ragged_start_forward():
    # A window starting on an odd source frame must round up to the grid, not
    # down: rounding down would emit a frame before the window began.
    frames = window_source_frames(Window(561 / 60, 565 / 60), 60.0, 30)
    assert frames[0] == 562


def test_window_source_frames_clamps_to_the_end_of_the_source():
    frames = window_source_frames(Window(312.0, 320.0), 60.0, 30, total_source_frames=18743)
    assert frames
    assert max(frames) < 18743


# ----------------------------------------------------------------------
# Window construction and merging
# ----------------------------------------------------------------------


def test_touch_windows_span_lead_and_tail():
    windows = touch_windows([{"touch_number": 4, "frame": 3061}], 30)
    assert len(windows) == 1
    assert windows[0].start_sec == pytest.approx(100.0333, abs=1e-4)
    assert windows[0].end_sec == pytest.approx(102.5333, abs=1e-4)
    assert windows[0].reasons == ["touch_4"]


def test_touch_window_near_the_start_clamps_at_zero():
    windows = touch_windows([{"touch_number": 1, "frame": 15}], 30)
    assert windows[0].start_sec == 0.0


def test_touch_without_a_frame_is_skipped():
    assert touch_windows([{"touch_number": 1}], 30) == []


def test_parry_windows_only_take_exchanges_flagged_with_a_parry():
    exchanges = [
        {"exchange_number": 1, "start_frame": 99, "end_frame": 198, "parry_left": True, "parry_right": False},
        {"exchange_number": 2, "start_frame": 300, "end_frame": 400, "parry_left": False, "parry_right": False},
        {"exchange_number": 3, "start_frame": 500, "end_frame": 560, "parry_left": False, "parry_right": True},
    ]
    windows = parry_windows(exchanges, 30)
    assert [w.reasons[0] for w in windows] == ["exchange_1", "exchange_3"]
    assert windows[0].start_sec == pytest.approx(3.3)
    assert windows[0].end_sec == pytest.approx(6.6)


def test_merge_windows_unions_overlaps_and_keeps_every_reason():
    merged = merge_windows([
        Window(10.0, 12.0, ["touch_1"]),
        Window(11.0, 15.0, ["exchange_3"]),
        Window(20.0, 21.0, ["exchange_9"]),
    ])
    assert len(merged) == 2
    assert (merged[0].start_sec, merged[0].end_sec) == (10.0, 15.0)
    assert merged[0].reasons == ["touch_1", "exchange_3"]
    assert merged[1].reasons == ["exchange_9"]


def test_merge_windows_joins_spans_that_only_touch():
    merged = merge_windows([Window(1.0, 2.0, ["a"]), Window(2.0, 3.0, ["b"])])
    assert len(merged) == 1
    assert merged[0].reasons == ["a", "b"]


def test_merge_windows_absorbs_a_fully_contained_span():
    merged = merge_windows([Window(0.0, 10.0, ["outer"]), Window(3.0, 4.0, ["inner"])])
    assert len(merged) == 1
    assert (merged[0].start_sec, merged[0].end_sec) == (0.0, 10.0)
    assert merged[0].reasons == ["outer", "inner"]


def test_merge_windows_does_not_mutate_its_input():
    original = Window(1.0, 2.0, ["a"])
    merge_windows([original, Window(1.5, 5.0, ["b"])])
    assert original.end_sec == 2.0
    assert original.reasons == ["a"]


def test_merge_windows_dedupes_a_repeated_reason():
    merged = merge_windows([Window(1.0, 3.0, ["touch_1"]), Window(2.0, 4.0, ["touch_1"])])
    assert merged[0].reasons == ["touch_1"]


# ----------------------------------------------------------------------
# Coordinates
# ----------------------------------------------------------------------


def test_work_to_source_scale_is_the_crop_over_the_scale_width():
    assert work_to_source_scale(PISTE_CROP, SCALE_WIDTH) == 3.0


def test_work_to_source_xy_inverts_crop_then_scale():
    # Work origin maps to the crop's own origin.
    assert work_to_source_xy(0, 0, PISTE_CROP, SCALE_WIDTH) == (0.0, 1210.0)
    # A joint mid-band: x scales by 3, y scales by 3 then shifts by crop.y.
    assert work_to_source_xy(640, 125, PISTE_CROP, SCALE_WIDTH) == (1920.0, 1585.0)


def test_work_to_source_xy_honours_a_nonzero_crop_x():
    crop = {"x": 500, "y": 100, "w": 2560, "h": 500}
    assert work_to_source_xy(10, 10, crop, 1280) == (520.0, 120.0)


def test_decode_pose_sample_drops_low_confidence_joints():
    flat = [100, 50, 90, 200, 60, 10, 300, 70, 35]
    points = decode_pose_sample(flat, conf_scale=100, min_conf=0.3)
    assert points == [(100.0, 50.0), (300.0, 70.0)]


def test_decode_pose_sample_handles_a_missing_detection():
    assert decode_pose_sample(None, 100, 0.3) == []


def test_keypoints_in_window_reads_both_sides_across_the_span():
    sidecar = {
        "sample_every": 3,
        "conf_scale": 100,
        "poses": {
            "left": [[10, 20, 90], None, [12, 22, 90], [14, 24, 90]],
            "right": [[110, 30, 90], [111, 31, 90], None, [113, 33, 90]],
        },
    }
    # Work frames 0..6 cover samples 0..2 on each side.
    points = keypoints_in_window(sidecar, 0, 6)
    assert (10.0, 20.0) in points
    assert (12.0, 22.0) in points
    assert (111.0, 31.0) in points
    assert (14.0, 24.0) not in points  # sample 3 is work frame 9, outside


def test_keypoints_in_window_is_empty_when_nothing_was_detected():
    sidecar = {"sample_every": 3, "conf_scale": 100, "poses": {"left": [None], "right": [None]}}
    assert keypoints_in_window(sidecar, 0, 3) == []


def test_crop_box_pads_for_blade_reach_and_stays_even():
    box = crop_box_for_points(
        [(400.0, 60.0), (500.0, 200.0)], PISTE_CROP, SCALE_WIDTH, SOURCE_RES,
        margin_x=320, margin_top=260, margin_bottom=100,
    )
    # x: 400..500 work -> 1200..1500 source, padded by 320 each side.
    assert box["x"] == 880
    assert box["w"] == 940
    # y: 60..200 work -> 1390..1810 source, padded 260 above / 100 below.
    assert box["y"] == 1130
    assert box["h"] == 780
    assert box["w"] % 2 == 0 and box["h"] % 2 == 0


def test_crop_box_clamps_to_the_source_frame():
    box = crop_box_for_points(
        [(5.0, 5.0)], PISTE_CROP, SCALE_WIDTH, SOURCE_RES,
        margin_x=320, margin_top=260, margin_bottom=100,
    )
    assert box["x"] == 0
    assert box["y"] == 965  # 1225 - 260, still inside the frame
    assert box["x"] + box["w"] <= SOURCE_RES[0]
    assert box["y"] + box["h"] <= SOURCE_RES[1]


def test_crop_box_returns_none_without_points_so_the_caller_can_fall_back():
    assert crop_box_for_points([], PISTE_CROP, SCALE_WIDTH, SOURCE_RES) is None


def test_piste_fallback_box_is_the_whole_band():
    box = piste_fallback_box(PISTE_CROP, SOURCE_RES)
    assert box == {"x": 0, "y": 1210, "w": 3840, "h": 750}


# ----------------------------------------------------------------------
# ffmpeg command
# ----------------------------------------------------------------------


def test_extract_command_seeks_by_time_and_subsamples_with_select():
    cmd = build_extract_command(
        source="/tmp/src.MOV", first_source_frame=562, frame_count=76, step=2,
        crop={"x": 1681, "y": 1226, "w": 1996, "h": 696}, source_fps=60.0,
        out_pattern="/tmp/out_%05d.jpg",
    )
    assert cmd[cmd.index("-ss") + 1] == f"{562 / 60.0:.6f}"
    assert cmd[cmd.index("-frames:v") + 1] == "76"
    filters = cmd[cmd.index("-vf") + 1]
    assert "select='not(mod(n\\,2))'" in filters
    assert "crop=1996:696:1681:1226" in filters
    # The fps filter drifted off the grid in testing; it must not come back.
    assert "fps=" not in filters


def test_extract_command_keeps_every_frame_when_step_is_one():
    cmd = build_extract_command(
        source="/tmp/src.MOV", first_source_frame=0, frame_count=10, step=1,
        crop={"x": 0, "y": 0, "w": 100, "h": 100}, source_fps=60.0,
        out_pattern="/tmp/out_%05d.jpg",
    )
    assert "select=1" in cmd[cmd.index("-vf") + 1]


# ----------------------------------------------------------------------
# Manifest
# ----------------------------------------------------------------------


def test_manifest_records_every_frame_of_reference(tmp_path):
    manifest = build_manifest(
        report_id="r1",
        source=tmp_path / "src.MOV",
        source_info={"width": 3840, "height": 2160, "fps": 60.0, "nb_frames": 18743},
        config={"work_fps": 30, "piste": {"crop": PISTE_CROP, "scale_width": SCALE_WIDTH}},
        sample_fps=30,
        step=2,
        window_records=[{"window_id": "window_001", "frames": []}],
    )
    assert manifest["version"] == MANIFEST_VERSION
    assert manifest["source_fps"] == 60.0
    assert manifest["work_fps"] == 30
    assert manifest["work_to_source_scale"] == 3.0
    assert manifest["sampling_step"] == 2
    # Round-trips through JSON: the labelling server reads this file back.
    assert json.loads(json.dumps(manifest))["windows"][0]["window_id"] == "window_001"
