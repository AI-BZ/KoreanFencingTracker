"""
Tests for scripts/prepare_piste_video.py (piste work-file preparation).

Pure logic only — no cv2 GUI, no ffmpeg execution, no YOLO weights, no video files.
Everything here runs headless.
"""

import argparse
import json

import pytest

from scripts.prepare_piste_video import (
    CROP_MARGIN_PX,
    POSE_CONF,
    POSE_IMGSZ,
    POSE_MAX_DET,
    SCALE_WIDTH,
    SCHEMA_VERSION,
    SCOREBOARD_PAD_PX,
    SCOREBOARD_ROI_KEYS,
    WORK_FPS,
    build_config,
    build_ffmpeg_command,
    build_preview_timestamps,
    classify_foot_y,
    config_decode_path,
    derive_piste_crop,
    derive_scoreboard_crop,
    even_down,
    foot_band_to_work,
    parse_band,
    parse_rect,
    parse_scoreboard_roi,
    preview_label,
    work_file_paths,
)

# The plan's worked example (plan 1.2). Numbers are the operator's real 4K
# measurements for the validation video, not schema placeholders.
SOURCE_W, SOURCE_H = 3840, 2160
CROP_BAND = (950, 1700)
FOOT_BAND = (1340, 1595)
SCOREBOARD_RECT = (1800, 960, 480, 280)
SOURCE_VIDEO = "/Volumes/Film/DCIM/100APPLE/260815_pool_home_vs_away.mov"
STEM = "260815_pool_home_vs_away"


@pytest.fixture
def sample_config():
    return build_config(
        source_video=SOURCE_VIDEO,
        piste_number=3,
        source_fps=120.0,
        source_resolution=(SOURCE_W, SOURCE_H),
        crop_band=CROP_BAND,
        foot_band=FOOT_BAND,
        scoreboard_rect=SCOREBOARD_RECT,
        scoreboard_rois={
            "lamp_left": (40, 60, 120, 90),
            "lamp_right": (560, 60, 120, 90),
            "score_left": (80, 200, 140, 160),
            "score_right": (500, 200, 140, 160),
            "clock": (260, 180, 200, 140),
        },
    )


# ------------------------------------------------------------------
# Argument parsing
# ------------------------------------------------------------------

def test_parse_band_valid():
    assert parse_band("950:1700") == (950, 1700)


def test_parse_band_accepts_zero_start():
    assert parse_band("0:120") == (0, 120)


@pytest.mark.parametrize("bad", [
    "950",              # missing second value
    "950:1700:20",      # too many values
    "950-1700",         # wrong separator
    "a:1700",           # non-integer
    "950:950",          # not increasing
    "1700:950",         # inverted
    "-10:100",          # negative
    "",                 # empty
])
def test_parse_band_malformed(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_band(bad)


def test_parse_rect_valid():
    assert parse_rect("1800:960:480:280") == (1800, 960, 480, 280)


@pytest.mark.parametrize("bad", [
    "1800:960:480",     # too few
    "1800:960:480:280:5",  # too many
    "1800:960:0:280",   # zero width
    "1800:960:480:0",   # zero height
    "1800:960:-4:280",  # negative size
    "-1:960:480:280",   # negative origin
    "x:960:480:280",    # non-integer
    "",                 # empty
])
def test_parse_rect_malformed(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_rect(bad)


def test_parse_scoreboard_roi_valid():
    key, rect = parse_scoreboard_roi("lamp_left=40:60:120:90")
    assert key == "lamp_left"
    assert rect == (40, 60, 120, 90)


def test_parse_scoreboard_roi_accepts_every_documented_key():
    for key in SCOREBOARD_ROI_KEYS:
        parsed_key, rect = parse_scoreboard_roi(f"{key}=1:2:3:4")
        assert parsed_key == key
        assert rect == (1, 2, 3, 4)


@pytest.mark.parametrize("bad", [
    "lamp_left:40:60:120:90",   # missing '='
    "bogus_key=40:60:120:90",   # unknown key
    "lamp_left=40:60:120",      # malformed rect
    "=40:60:120:90",            # empty key
])
def test_parse_scoreboard_roi_malformed(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_scoreboard_roi(bad)


# ------------------------------------------------------------------
# Even-dimension forcing
# ------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [(0, 0), (1, 0), (2, 2), (991, 990), (3840, 3840)])
def test_even_down(value, expected):
    assert even_down(value) == expected


# ------------------------------------------------------------------
# Piste crop derivation
# ------------------------------------------------------------------

def test_derive_piste_crop_matches_plan_example():
    """crop-band 950:1700 with +-120px drift margin -> y=830, h=990, full width."""
    crop = derive_piste_crop(CROP_BAND, SOURCE_W, SOURCE_H)
    assert crop == {"x": 0, "y": 830, "w": 3840, "h": 990}


def test_derive_piste_crop_applies_margin_both_sides():
    crop = derive_piste_crop((1000, 1400), SOURCE_W, SOURCE_H)
    assert crop["y"] == 1000 - CROP_MARGIN_PX
    assert crop["h"] == (1400 - 1000) + 2 * CROP_MARGIN_PX


def test_derive_piste_crop_clamps_at_top_edge():
    crop = derive_piste_crop((50, 600), SOURCE_W, SOURCE_H)
    assert crop["y"] == 0
    assert crop["h"] == 600 + CROP_MARGIN_PX


def test_derive_piste_crop_clamps_at_bottom_edge():
    crop = derive_piste_crop((1900, 2100), SOURCE_W, SOURCE_H)
    assert crop["y"] == 1900 - CROP_MARGIN_PX
    assert crop["y"] + crop["h"] <= SOURCE_H


def test_derive_piste_crop_clamps_both_edges_on_a_short_frame():
    crop = derive_piste_crop((10, 190), 1920, 200)
    assert crop == {"x": 0, "y": 0, "w": 1920, "h": 200}


def test_derive_piste_crop_forces_even_dimensions():
    """Odd source width and an odd resulting height must both round down."""
    crop = derive_piste_crop((121, 500), 3839, 2159)
    assert crop["w"] % 2 == 0
    assert crop["h"] % 2 == 0
    assert crop["w"] == 3838


def test_derive_piste_crop_forces_even_y_offset():
    """ffmpeg's crop filter rounds odd offsets for subsampled video — do it here instead."""
    crop = derive_piste_crop((121, 500), SOURCE_W, SOURCE_H)
    assert crop["y"] % 2 == 0
    assert crop["y"] == 0  # 121-120=1 -> even_down -> 0


def test_derive_piste_crop_rejects_inverted_band():
    with pytest.raises(ValueError):
        derive_piste_crop((1700, 950), SOURCE_W, SOURCE_H)


# ------------------------------------------------------------------
# Scoreboard crop derivation
# ------------------------------------------------------------------

def test_derive_scoreboard_crop_matches_plan_example():
    """1800:960:480:280 padded by 120 on all four sides -> 1680,840,720,520."""
    crop = derive_scoreboard_crop(SCOREBOARD_RECT, SOURCE_W, SOURCE_H)
    assert crop == {"x": 1680, "y": 840, "w": 720, "h": 520}


def test_derive_scoreboard_crop_pads_all_four_sides():
    crop = derive_scoreboard_crop((1000, 1000, 200, 100), SOURCE_W, SOURCE_H)
    assert crop["x"] == 1000 - SCOREBOARD_PAD_PX
    assert crop["y"] == 1000 - SCOREBOARD_PAD_PX
    assert crop["w"] == 200 + 2 * SCOREBOARD_PAD_PX
    assert crop["h"] == 100 + 2 * SCOREBOARD_PAD_PX


def test_derive_scoreboard_crop_clamps_at_frame_corners():
    crop = derive_scoreboard_crop((10, 10, 200, 100), SOURCE_W, SOURCE_H)
    assert crop["x"] == 0 and crop["y"] == 0

    crop = derive_scoreboard_crop((3700, 2050, 120, 100), SOURCE_W, SOURCE_H)
    assert crop["x"] + crop["w"] <= SOURCE_W
    assert crop["y"] + crop["h"] <= SOURCE_H


def test_derive_scoreboard_crop_forces_even_dimensions():
    crop = derive_scoreboard_crop((121, 121, 201, 101), SOURCE_W, SOURCE_H)
    assert crop["x"] % 2 == 0 and crop["y"] % 2 == 0
    assert crop["w"] % 2 == 0 and crop["h"] % 2 == 0


# ------------------------------------------------------------------
# 4K -> work-file foot band conversion (the ONLY coordinate conversion)
# ------------------------------------------------------------------

def test_foot_band_to_work_matches_plan_worked_example():
    """source 3840 wide, crop.y=830, 4K band [1340,1595], scale 1280 -> [170,255]."""
    crop = derive_piste_crop(CROP_BAND, SOURCE_W, SOURCE_H)
    assert foot_band_to_work(FOOT_BAND, crop, SCALE_WIDTH, SOURCE_W) == [170, 255]


def test_foot_band_to_work_is_relative_to_crop_top():
    crop = {"x": 0, "y": 600, "w": 3840, "h": 900}
    assert foot_band_to_work((600, 1200), crop, 1280, 3840) == [0, 200]


def test_foot_band_to_work_rounds_to_ints():
    crop = {"x": 0, "y": 0, "w": 3840, "h": 2160}
    band = foot_band_to_work((5, 7), crop, 1280, 3840)
    assert band == [2, 2]
    assert all(isinstance(v, int) for v in band)


def test_foot_band_to_work_scales_with_scale_width():
    crop = {"x": 0, "y": 0, "w": 3840, "h": 2160}
    assert foot_band_to_work((0, 2160), crop, 1920, 3840) == [0, 1080]
    assert foot_band_to_work((0, 2160), crop, 960, 3840) == [0, 540]


def test_foot_band_to_work_rejects_band_outside_crop():
    crop = derive_piste_crop(CROP_BAND, SOURCE_W, SOURCE_H)  # covers 830..1820
    with pytest.raises(ValueError):
        foot_band_to_work((700, 900), crop, SCALE_WIDTH, SOURCE_W)
    with pytest.raises(ValueError):
        foot_band_to_work((1700, 1900), crop, SCALE_WIDTH, SOURCE_W)


# ------------------------------------------------------------------
# Work-file naming and preview timestamps
# ------------------------------------------------------------------

def test_work_file_paths_carry_the_piste_number():
    paths = work_file_paths(STEM, 3, "data/work")
    assert paths["piste"] == f"data/work/{STEM}_piste3.mp4"
    assert paths["scoreboard"] == f"data/work/{STEM}_piste3_scoreboard.mp4"


def test_build_preview_timestamps_uses_10s_edges():
    assert build_preview_timestamps(166.0) == [10.0, 83.0, 156.0]


def test_build_preview_timestamps_handles_short_clips():
    stamps = build_preview_timestamps(8.0)
    assert len(stamps) == 3
    assert stamps[0] == 0.0
    assert all(0.0 <= t <= 8.0 for t in stamps)


def test_preview_label():
    assert preview_label(83.0) == "t83"
    assert preview_label(9.6) == "t10"


# ------------------------------------------------------------------
# Config building / schema
# ------------------------------------------------------------------

def test_build_config_matches_plan_schema(sample_config):
    cfg = sample_config
    assert cfg["schema_version"] == SCHEMA_VERSION
    assert cfg["source"] == "manual"
    assert cfg["source_video"] == SOURCE_VIDEO
    assert cfg["piste_number"] == 3
    assert cfg["source_fps"] == 120.0
    assert cfg["source_resolution"] == [3840, 2160]
    assert cfg["work_fps"] == WORK_FPS == 30


def test_build_config_piste_block(sample_config):
    piste = sample_config["piste"]
    assert piste["crop"] == {"x": 0, "y": 830, "w": 3840, "h": 990}
    assert piste["scale_width"] == SCALE_WIDTH == 1280
    assert piste["foot_band_work"] == [170, 255]
    assert piste["pose_imgsz"] == POSE_IMGSZ == 1280
    assert piste["pose_max_det"] == POSE_MAX_DET == 8
    assert piste["pose_conf"] == POSE_CONF == 0.35


def test_build_config_scoreboard_rois_stay_in_crop_coords(sample_config):
    """ROIs are measured on the scoreboard crop and must NOT be converted."""
    sb = sample_config["scoreboard"]
    assert sb["crop"] == {"x": 1680, "y": 840, "w": 720, "h": 520}
    assert sb["rois"]["lamp_left"] == [40, 60, 120, 90]
    assert set(sb["rois"]) == set(SCOREBOARD_ROI_KEYS)


def test_build_config_work_files_use_source_stem(sample_config):
    assert sample_config["work_files"]["piste"] == f"data/work/{STEM}_piste3.mp4"
    assert sample_config["work_files"]["scoreboard"] == f"data/work/{STEM}_piste3_scoreboard.mp4"


def test_build_config_honours_work_dir():
    cfg = build_config(
        source_video="/tmp/a.mov", piste_number=2, source_fps=60.0,
        source_resolution=(3840, 2160), crop_band=CROP_BAND, foot_band=FOOT_BAND,
        work_dir="/somewhere/else",
    )
    assert cfg["work_files"]["piste"] == "/somewhere/else/a_piste2.mp4"


def test_build_config_without_scoreboard():
    cfg = build_config(
        source_video="/tmp/a.mov", piste_number=1, source_fps=120.0,
        source_resolution=(3840, 2160), crop_band=CROP_BAND, foot_band=FOOT_BAND,
    )
    assert cfg["scoreboard"] is None
    assert cfg["work_files"]["scoreboard"] is None


def test_build_config_records_source_override():
    """The config must never let anything believe the original was decoded."""
    cfg = build_config(
        source_video=SOURCE_VIDEO, piste_number=3, source_fps=120.0,
        source_resolution=(SOURCE_W, SOURCE_H), crop_band=CROP_BAND, foot_band=FOOT_BAND,
        scoreboard_rect=SCOREBOARD_RECT, source_override="/tmp/intermediate.mp4",
    )
    assert cfg["source_video"] == SOURCE_VIDEO
    assert cfg["source_override"] == "/tmp/intermediate.mp4"
    assert config_decode_path(cfg) == "/tmp/intermediate.mp4"


def test_build_config_omits_source_override_key_when_unused(sample_config):
    assert "source_override" not in sample_config
    assert config_decode_path(sample_config) == SOURCE_VIDEO


def test_config_round_trips_as_json(sample_config, tmp_path):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(sample_config, indent=2, ensure_ascii=False), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == sample_config
    assert build_ffmpeg_command(loaded) == build_ffmpeg_command(sample_config)


# ------------------------------------------------------------------
# ffmpeg command construction
# ------------------------------------------------------------------

def _filter_complex(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def test_ffmpeg_command_single_decode_two_outputs(sample_config):
    cmd = build_ffmpeg_command(sample_config)
    assert cmd[:4] == ["ffmpeg", "-y", "-i", SOURCE_VIDEO]
    assert cmd.count("-i") == 1
    fc = _filter_complex(cmd)
    assert fc.startswith("[0:v]split=2[p][s];")


def test_ffmpeg_command_filters_come_from_config(sample_config):
    fc = _filter_complex(sample_config and build_ffmpeg_command(sample_config))
    assert "crop=3840:990:0:830" in fc      # piste crop, 4K coords
    assert "scale=1280:-2" in fc            # -2 keeps the height even
    assert "crop=720:520:1680:840" in fc    # scoreboard crop, native resolution
    assert fc.count("fps=30") == 2          # both branches share the frame index


def test_ffmpeg_command_filters_track_config_changes():
    cfg = build_config(
        source_video="/tmp/a.mov", piste_number=1, source_fps=50.0,
        source_resolution=(1920, 1080), crop_band=(300, 700), foot_band=(400, 600),
        scoreboard_rect=(200, 100, 300, 200),
    )
    fc = _filter_complex(build_ffmpeg_command(cfg))
    assert "crop=1920:640:0:180" in fc
    # y padding clamps at the top edge (100-120 -> 0), so h is 420 not 440
    assert "crop=540:420:80:0" in fc


def test_ffmpeg_command_maps_and_audio(sample_config):
    cmd = build_ffmpeg_command(sample_config)
    assert cmd.count("-map") == 3
    assert "[piste]" in cmd and "[sb]" in cmd and "0:a?" in cmd

    piste_out = sample_config["work_files"]["piste"]
    sb_out = sample_config["work_files"]["scoreboard"]

    # Audio is preserved on the piste output (roadmap 8-8) ...
    assert cmd.index("0:a?") < cmd.index(piste_out)
    assert cmd.index("aac") < cmd.index(piste_out)
    assert cmd.index("96k") < cmd.index(piste_out)
    # ... and stripped from the scoreboard output.
    assert cmd.index(piste_out) < cmd.index("-an") < cmd.index(sb_out)
    assert "-an" not in cmd[: cmd.index(piste_out)]


def test_ffmpeg_command_codec_settings(sample_config):
    cmd = build_ffmpeg_command(sample_config)
    piste_out = sample_config["work_files"]["piste"]
    head, tail = cmd[: cmd.index(piste_out)], cmd[cmd.index(piste_out):]
    assert "20" in head and "libx264" in head and "fast" in head   # piste: crf 20
    assert "18" in tail and "libx264" in tail                       # scoreboard: crf 18


def test_ffmpeg_command_uses_source_override_for_decoding():
    cfg = build_config(
        source_video=SOURCE_VIDEO, piste_number=3, source_fps=120.0,
        source_resolution=(SOURCE_W, SOURCE_H), crop_band=CROP_BAND, foot_band=FOOT_BAND,
        scoreboard_rect=SCOREBOARD_RECT, source_override="/tmp/intermediate.mp4",
    )
    cmd = build_ffmpeg_command(cfg)
    assert cmd[cmd.index("-i") + 1] == "/tmp/intermediate.mp4"
    assert SOURCE_VIDEO not in cmd


def test_ffmpeg_command_without_scoreboard_has_no_split():
    cfg = build_config(
        source_video="/tmp/a.mov", piste_number=1, source_fps=120.0,
        source_resolution=(3840, 2160), crop_band=CROP_BAND, foot_band=FOOT_BAND,
    )
    cmd = build_ffmpeg_command(cfg)
    fc = _filter_complex(cmd)
    assert "split" not in fc
    assert "[sb]" not in cmd
    assert cmd.count("-map") == 2
    assert cmd[-1] == "data/work/a_piste1.mp4"


# ------------------------------------------------------------------
# Gate classification helper
# ------------------------------------------------------------------

@pytest.mark.parametrize("foot_y,expected", [
    (None, False),
    (169, False),
    (170, True),
    (210, True),
    (255, True),
    (256, False),
])
def test_classify_foot_y(foot_y, expected):
    assert classify_foot_y(foot_y, [170, 255]) is expected
