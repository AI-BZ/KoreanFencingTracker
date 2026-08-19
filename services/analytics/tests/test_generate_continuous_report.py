"""Unit tests for pure logic in scripts/generate_continuous_report.py.

Covers the side-effect-free helpers:
- format_timestamp(): frame -> "M:SS"
- _distance_zone(): bell-guard distance -> fencing zone name
- find_ocr_report(): video stem -> matching OCR report path
- piste mode: config loading/validation, estimator kwargs, source_type,
  gate-audit frame selection and annotation
"""

import json

import numpy as np
import pytest

from analyzer.models import FencerPose, PoseKeypoint
from analyzer.touch_matching import (
    ATTACK_OUTCOME_KO,
    NO_PRIORITY_CALL,
    lamp_scorer_conflict,
    summarize_attack_outcomes,
)
from scripts.generate_continuous_report import (
    PisteConfigError,
    promote_supplied_lamp_outcomes,
    report_carries_lamp_fields,
    annotate_gate_frame,
    audit_frame_indices,
    format_piste_banner,
    format_timestamp,
    gate_audit_path,
    load_piste_config,
    piste_estimator_kwargs,
    report_source_type,
    resolve_gate_audit,
    _distance_zone,
    find_ocr_report,
)


def _write_config(tmp_path, piste, name="cfg.json"):
    path = tmp_path / name
    path.write_text(
        json.dumps({"schema_version": 1, "piste": piste}), encoding="utf-8",
    )
    return path


class TestFormatTimestamp:
    """format_timestamp(frame, fps) -> 'M:SS'."""

    def test_zero_frame(self):
        assert format_timestamp(0, 30.0) == "0:00"

    def test_one_second(self):
        assert format_timestamp(30, 30.0) == "0:01"

    def test_exactly_one_minute(self):
        assert format_timestamp(1800, 30.0) == "1:00"

    def test_one_minute_one_second(self):
        assert format_timestamp(1830, 30.0) == "1:01"

    def test_seconds_zero_padded(self):
        # 3 seconds -> "0:03" (two-digit seconds)
        assert format_timestamp(90, 30.0) == "0:03"

    def test_fractional_second_truncates(self):
        # 45 frames @ 30fps = 1.5s -> truncated to 1s
        assert format_timestamp(45, 30.0) == "0:01"

    def test_non_integer_fps(self):
        # 60 frames @ 24fps = 2.5s -> "0:02"
        assert format_timestamp(60, 24.0) == "0:02"


class TestDistanceZone:
    """_distance_zone(bh) maps bell-guard-height distance to a zone name."""

    def test_out_of_distance(self):
        assert _distance_zone(3.0) == "out_of_distance"

    def test_just_above_out_of_distance_threshold(self):
        assert _distance_zone(1.9) == "out_of_distance"

    def test_boundary_1_8_is_advance_lunge(self):
        # 1.8 is NOT > 1.8, so falls to the next bucket
        assert _distance_zone(1.8) == "advance_lunge"

    def test_advance_lunge(self):
        assert _distance_zone(1.6) == "advance_lunge"

    def test_boundary_1_5_is_lunge(self):
        assert _distance_zone(1.5) == "lunge"

    def test_lunge(self):
        assert _distance_zone(1.3) == "lunge"

    def test_boundary_1_2_is_extension(self):
        assert _distance_zone(1.2) == "extension"

    def test_extension(self):
        assert _distance_zone(1.0) == "extension"

    def test_boundary_0_8_is_infighting(self):
        assert _distance_zone(0.8) == "infighting"

    def test_infighting(self):
        assert _distance_zone(0.5) == "infighting"

    def test_zero_distance(self):
        assert _distance_zone(0.0) == "infighting"

    @pytest.mark.parametrize("bh,expected", [
        (2.5, "out_of_distance"),
        (1.81, "out_of_distance"),
        (1.51, "advance_lunge"),
        (1.21, "lunge"),
        (0.81, "extension"),
        (0.79, "infighting"),
    ])
    def test_parametrized_boundaries(self, bh, expected):
        assert _distance_zone(bh) == expected


class TestFindOcrReport:
    """find_ocr_report(video_stem, output_dir) -> Path | None.

    Regression: a video named '<description>_<youtubeID>.mp4' used to find
    nothing, because the old matcher only stripped known prefixes and then
    required the whole stem to be a substring of the candidate. The OCR merge
    was then skipped silently and the report came out with touches=0.
    """

    def _dir(self, tmp_path, *names):
        for n in names:
            (tmp_path / n).write_text("{}", encoding="utf-8")
        return tmp_path

    def test_arbitrary_prefix_before_youtube_id(self, tmp_path):
        d = self._dir(tmp_path, "hKUXgUsDOKE_report.json")
        found = find_ocr_report("jr_foil_final_li_lin_hKUXgUsDOKE", d)
        assert found is not None and found.name == "hKUXgUsDOKE_report.json"

    def test_exact_stem_match(self, tmp_path):
        d = self._dir(tmp_path, "0HeqT9us5wA_report.json")
        found = find_ocr_report("0HeqT9us5wA", d)
        assert found.name == "0HeqT9us5wA_report.json"

    def test_known_prefix_stripped(self, tmp_path):
        d = self._dir(tmp_path, "7Amgqc5HJR0_report.json")
        assert find_ocr_report("usaf_7Amgqc5HJR0", d).name == "7Amgqc5HJR0_report.json"
        assert find_ocr_report("usa_fencing_sample_7Amgqc5HJR0", d).name == "7Amgqc5HJR0_report.json"

    def test_continuous_reports_never_matched(self, tmp_path):
        d = self._dir(tmp_path, "hKUXgUsDOKE_continuous_report.json")
        assert find_ocr_report("jr_foil_final_li_lin_hKUXgUsDOKE", d) is None

    def test_no_candidates_returns_none(self, tmp_path):
        assert find_ocr_report("anything_hKUXgUsDOKE", tmp_path) is None

    def test_unrelated_report_not_matched(self, tmp_path):
        d = self._dir(tmp_path, "3XTpDrDSvUs_report.json")
        assert find_ocr_report("jr_foil_final_li_lin_hKUXgUsDOKE", d) is None

    def test_exact_match_wins_over_substring(self, tmp_path):
        """Directory order must not decide: the exact base wins even though the
        looser candidate sorts first."""
        d = self._dir(
            tmp_path,
            "0000_hKUXgUsDOKE_extra_report.json",   # sorts first, substring-ish
            "hKUXgUsDOKE_report.json",              # exact YouTube ID
        )
        assert find_ocr_report("hKUXgUsDOKE", d).name == "hKUXgUsDOKE_report.json"

    def test_descriptive_report_name_matching_full_stem(self, tmp_path):
        d = self._dir(tmp_path, "jr_foil_final_li_lin_hKUXgUsDOKE_report.json")
        found = find_ocr_report("jr_foil_final_li_lin_hKUXgUsDOKE", d)
        assert found.name == "jr_foil_final_li_lin_hKUXgUsDOKE_report.json"

    def test_short_base_not_substring_matched(self, tmp_path):
        """A too-short base must not match by substring alone."""
        d = self._dir(tmp_path, "li_report.json")
        assert find_ocr_report("jr_foil_final_li_lin_hKUXgUsDOKE", d) is None

    def test_partial_token_not_matched(self, tmp_path):
        """A base that only partially overlaps the trailing token is no match:
        it is neither an 11-char YouTube ID nor aligned on an underscore."""
        d = self._dir(tmp_path, "short_report.json")
        assert find_ocr_report("some_video_shortx", d) is None

    def test_boundary_aligned_trailing_base_matches(self, tmp_path):
        """A base that does align on the trailing underscore matches, even when
        it is not an 11-char YouTube ID."""
        d = self._dir(tmp_path, "short_report.json")
        assert find_ocr_report("some_video_short", d).name == "short_report.json"


class TestExchangeAttackerIsAssigned:
    """The script must actually call classify_exchange_sides, not just import it.

    A refactor once dropped the ``ex_dict["attacker"], ex_dict["defender"] =
    classify_exchange_sides(...)`` line while leaving the import in place. Every
    exchange then serialised with ``attacker: None``, which zeroes
    ``continuous_summary.fencer_stats`` and renders as "0 attacks, 0 defenses"
    for both fencers. Nothing raised, no test failed, and the reports shipped
    that way.

    Checking the parsed AST rather than the source text keeps this from breaking
    on reformatting while still catching a deletion.
    """

    def test_classify_exchange_sides_is_called(self):
        import ast
        import inspect

        import scripts.generate_continuous_report as module

        tree = ast.parse(inspect.getsource(module))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "classify_exchange_sides" in called, (
            "generate_continuous_report imports classify_exchange_sides but never "
            "calls it — every exchange will serialise with attacker=None and the "
            "per-fencer attack/defense counts will silently read zero."
        )


class TestLoadPisteConfig:
    """load_piste_config(path) -> dict, or PisteConfigError with a clear reason.

    Piste mode decides *which people in the frame are analysed at all*. A config
    that silently fails to load would produce a confident-looking report built
    from referees and background fencers, so every failure path raises instead
    of degrading to normal mode.
    """

    def test_valid_config_returns_dict(self, tmp_path):
        path = _write_config(tmp_path, {"foot_band_work": [170, 255]})
        config = load_piste_config(path)
        assert config["piste"]["foot_band_work"] == [170, 255]

    def test_accepts_str_path(self, tmp_path):
        path = _write_config(tmp_path, {"foot_band_work": [170, 255]})
        assert load_piste_config(str(path))["schema_version"] == 1

    def test_missing_file_raises_with_path(self, tmp_path):
        missing = tmp_path / "nope.json"
        with pytest.raises(PisteConfigError) as exc:
            load_piste_config(missing)
        assert "not found" in str(exc.value)
        assert "nope.json" in str(exc.value)

    def test_malformed_json_raises(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text('{"piste": {', encoding="utf-8")
        with pytest.raises(PisteConfigError) as exc:
            load_piste_config(path)
        assert "not valid JSON" in str(exc.value)

    def test_non_object_json_raises(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(PisteConfigError) as exc:
            load_piste_config(path)
        assert "JSON object" in str(exc.value)

    def test_missing_piste_block_raises(self, tmp_path):
        path = tmp_path / "no_piste.json"
        path.write_text(json.dumps({"scoreboard": {}}), encoding="utf-8")
        with pytest.raises(PisteConfigError) as exc:
            load_piste_config(path)
        assert "'piste' block" in str(exc.value)

    def test_piste_block_wrong_type_raises(self, tmp_path):
        path = tmp_path / "bad_piste.json"
        path.write_text(json.dumps({"piste": [170, 255]}), encoding="utf-8")
        with pytest.raises(PisteConfigError) as exc:
            load_piste_config(path)
        assert "must be an object" in str(exc.value)

    def test_scoreboard_block_is_optional(self, tmp_path):
        """A pose-only run has no scoreboard crop; that must not be an error."""
        path = _write_config(tmp_path, {"foot_band_work": [10, 20]})
        assert "scoreboard" not in load_piste_config(path)


class TestPisteEstimatorKwargs:
    """piste_estimator_kwargs(config) -> PoseEstimator constructor arguments.

    Tested at the dict level so no YOLO model is ever instantiated.
    """

    def test_defaults_applied(self):
        kw = piste_estimator_kwargs({"piste": {"foot_band_work": [170, 255]}})
        assert kw == {
            "confidence": 0.35,
            "imgsz": 1280,
            "max_det": 8,
            "foot_band_work": (170.0, 255.0),
        }

    def test_config_values_override_defaults(self):
        kw = piste_estimator_kwargs({"piste": {
            "foot_band_work": [130, 215],
            "pose_conf": 0.4,
            "pose_imgsz": 960,
            "pose_max_det": 12,
        }})
        assert kw == {
            "confidence": 0.4,
            "imgsz": 960,
            "max_det": 12,
            "foot_band_work": (130.0, 215.0),
        }

    def test_band_is_floats_regardless_of_json_ints(self):
        kw = piste_estimator_kwargs({"piste": {"foot_band_work": [170, 255]}})
        assert all(isinstance(v, float) for v in kw["foot_band_work"])

    def test_missing_band_raises(self):
        with pytest.raises(PisteConfigError) as exc:
            piste_estimator_kwargs({"piste": {"pose_conf": 0.35}})
        assert "foot_band_work" in str(exc.value)

    @pytest.mark.parametrize("band", [[170], [170, 200, 255], []])
    def test_wrong_length_band_raises(self, band):
        with pytest.raises(PisteConfigError) as exc:
            piste_estimator_kwargs({"piste": {"foot_band_work": band}})
        assert "2 values" in str(exc.value)

    def test_non_list_band_raises(self):
        with pytest.raises(PisteConfigError) as exc:
            piste_estimator_kwargs({"piste": {"foot_band_work": "170:255"}})
        assert "[y_min, y_max]" in str(exc.value)

    def test_non_numeric_band_raises(self):
        with pytest.raises(PisteConfigError) as exc:
            piste_estimator_kwargs({"piste": {"foot_band_work": ["170", "255"]}})
        assert "numbers" in str(exc.value)

    def test_inverted_band_raises(self):
        """A band written high-to-low would reject every detection silently."""
        with pytest.raises(PisteConfigError) as exc:
            piste_estimator_kwargs({"piste": {"foot_band_work": [255, 170]}})
        assert "y_min < y_max" in str(exc.value)

    def test_degenerate_band_raises(self):
        with pytest.raises(PisteConfigError):
            piste_estimator_kwargs({"piste": {"foot_band_work": [200, 200]}})

    @pytest.mark.parametrize("conf", [0, -0.1])
    def test_non_positive_conf_raises(self, conf):
        with pytest.raises(PisteConfigError) as exc:
            piste_estimator_kwargs({"piste": {
                "foot_band_work": [170, 255], "pose_conf": conf,
            }})
        assert "pose_conf" in str(exc.value)

    def test_conf_above_one_raises(self):
        with pytest.raises(PisteConfigError) as exc:
            piste_estimator_kwargs({"piste": {
                "foot_band_work": [170, 255], "pose_conf": 35,
            }})
        assert "(0, 1]" in str(exc.value)

    def test_non_integer_imgsz_raises(self):
        with pytest.raises(PisteConfigError) as exc:
            piste_estimator_kwargs({"piste": {
                "foot_band_work": [170, 255], "pose_imgsz": "1280",
            }})
        assert "pose_imgsz" in str(exc.value)

    def test_zero_max_det_raises(self):
        """max_det=0 is a YOLO call argument: it would return nothing at all."""
        with pytest.raises(PisteConfigError) as exc:
            piste_estimator_kwargs({"piste": {
                "foot_band_work": [170, 255], "pose_max_det": 0,
            }})
        assert "pose_max_det" in str(exc.value)

    def test_end_to_end_from_file(self, tmp_path):
        path = _write_config(tmp_path, {
            "crop": {"x": 0, "y": 830, "w": 3840, "h": 990},
            "scale_width": 1280,
            "foot_band_work": [170, 255],
            "pose_conf": 0.35,
            "pose_imgsz": 1280,
            "pose_max_det": 8,
        })
        kw = piste_estimator_kwargs(load_piste_config(path))
        assert kw["foot_band_work"] == (170.0, 255.0)
        assert kw["max_det"] == 8


class TestReportSourceType:
    """meta.source_type must flip to 'coach' only in piste mode."""

    def test_piste_mode_is_coach(self):
        assert report_source_type("data/piste_configs/x_piste3.json") == "coach"

    def test_no_config_stays_tv_broadcast(self):
        assert report_source_type(None) == "tv_broadcast"

    def test_empty_string_stays_tv_broadcast(self):
        assert report_source_type("") == "tv_broadcast"


class TestFormatPisteBanner:
    """The banner is the operator's only visual confirmation the gate is on."""

    def test_contains_settings(self):
        banner = format_piste_banner("cfg.json", {
            "confidence": 0.35, "imgsz": 1280, "max_det": 8,
            "foot_band_work": (170.0, 255.0),
        })
        assert "PISTE MODE ACTIVE" in banner
        assert "cfg.json" in banner
        assert "170" in banner and "255" in banner
        assert "1280" in banner
        assert "0.35" in banner

    def test_band_units_are_stated(self):
        """Three coordinate systems coexist; the banner must say which is shown."""
        banner = format_piste_banner("cfg.json", {
            "confidence": 0.35, "imgsz": 1280, "max_det": 8,
            "foot_band_work": (170.0, 255.0),
        })
        assert "work-file" in banner


class TestResolveGateAudit:
    """--gate-audit visualises the gate, so it needs --piste-config to mean anything."""

    def test_enabled_with_piste_config(self):
        count, note = resolve_gate_audit(30, "cfg.json")
        assert count == 30 and note is None

    def test_ignored_without_piste_config(self):
        count, note = resolve_gate_audit(30, None)
        assert count == 0
        assert note is not None and "--piste-config" in note

    def test_zero_is_off_and_silent(self):
        assert resolve_gate_audit(0, "cfg.json") == (0, None)

    def test_zero_without_config_is_silent(self):
        """Not passing the flag at all must not print a warning."""
        assert resolve_gate_audit(0, None) == (0, None)

    def test_negative_is_off(self):
        assert resolve_gate_audit(-5, "cfg.json") == (0, None)

    def test_none_is_off(self):
        assert resolve_gate_audit(None, "cfg.json") == (0, None)


class TestAuditFrameIndices:
    """audit_frame_indices spreads N samples over the video."""

    def test_count_and_spread(self):
        idx = audit_frame_indices(1000, 5, 1)
        assert idx == [100, 300, 500, 700, 900]

    def test_indices_are_multiples_of_sample_every(self):
        """Audited frames must be frames the pipeline actually posed."""
        idx = audit_frame_indices(1000, 7, 3)
        assert all(i % 3 == 0 for i in idx)

    def test_never_out_of_range(self):
        idx = audit_frame_indices(10, 10, 1)
        assert idx and max(idx) <= 9 and min(idx) >= 0

    def test_deduplicated_and_sorted(self):
        idx = audit_frame_indices(10, 30, 3)
        assert idx == sorted(set(idx))

    def test_zero_count_returns_empty(self):
        assert audit_frame_indices(1000, 0, 3) == []

    def test_empty_video_returns_empty(self):
        assert audit_frame_indices(0, 5, 3) == []

    def test_sample_every_zero_treated_as_one(self):
        assert audit_frame_indices(100, 2, 0) == [25, 75]


class TestGateAuditPath:
    def test_filename_shape(self, tmp_path):
        p = gate_audit_path(tmp_path, "bout_piste3", 1234)
        assert p.parent == tmp_path
        assert p.name == "bout_piste3_gate_001234.jpg"

    def test_zero_padded_sorts_chronologically(self, tmp_path):
        names = [gate_audit_path(tmp_path, "s", i).name for i in (5, 40, 300)]
        assert names == sorted(names)


def _fencer(side, x, foot_y, conf=0.8):
    kps = [PoseKeypoint(x=float(x), y=float(foot_y - 40), confidence=0.9)
           for _ in range(17)]
    kps[15] = PoseKeypoint(x=float(x), y=float(foot_y), confidence=0.9)
    kps[16] = PoseKeypoint(x=float(x + 5), y=float(foot_y - 2), confidence=0.9)
    return FencerPose(
        keypoints=kps,
        bbox=[float(x - 20), float(foot_y - 80), float(x + 20), float(foot_y)],
        person_confidence=conf,
        side=side,
    )


class TestAnnotateGateFrame:
    """annotate_gate_frame draws the kept fencers and the band, without mutating."""

    def _blank(self):
        return np.zeros((240, 320, 3), dtype=np.uint8)

    def test_does_not_mutate_input(self):
        frame = self._blank()
        annotate_gate_frame(frame, [_fencer("left", 100, 180)], (150, 210))
        assert not frame.any()

    def test_draws_something(self):
        out = annotate_gate_frame(
            self._blank(), [_fencer("left", 100, 180)], (150, 210),
        )
        assert out.any()

    def test_band_rows_are_drawn(self):
        out = annotate_gate_frame(self._blank(), [], (150, 210))
        assert out[150].any() and out[210].any()

    def test_no_fencers_still_returns_frame(self):
        out = annotate_gate_frame(self._blank(), [], (150, 210))
        assert out.shape == (240, 320, 3)

    def test_sides_drawn_in_different_colors(self):
        """Left/right must be distinguishable by eye — that is the whole check."""
        left = annotate_gate_frame(
            self._blank(), [_fencer("left", 100, 180)], (150, 210),
        )
        right = annotate_gate_frame(
            self._blank(), [_fencer("right", 100, 180)], (150, 210),
        )
        assert not np.array_equal(left, right)

    def test_unassigned_side_does_not_crash(self):
        out = annotate_gate_frame(
            self._blank(), [_fencer(None, 100, 180)], (150, 210),
        )
        assert out.any()

    def test_band_outside_frame_is_clipped_not_crashing(self):
        out = annotate_gate_frame(self._blank(), [], (-50, 9999))
        assert out.shape == (240, 320, 3)

    def test_two_fencers_drawn(self):
        one = annotate_gate_frame(
            self._blank(), [_fencer("left", 80, 180)], (150, 210),
        )
        two = annotate_gate_frame(
            self._blank(),
            [_fencer("left", 80, 180), _fencer("right", 240, 190)],
            (150, 210),
        )
        assert two.any() and not np.array_equal(one, two)


class TestPisteWiringInMain:
    """AST checks that main() keeps the two branches the design requires.

    The default branch must stay a bare ``PoseEstimator()``: the piste work
    (gate, imgsz, max_det, conf) must not leak into TV-broadcast runs, and this
    is the kind of line a later refactor merges "for tidiness" without any test
    noticing.
    """

    def _tree(self):
        import ast
        import inspect

        import scripts.generate_continuous_report as module

        return ast.parse(inspect.getsource(module))

    def test_bare_pose_estimator_call_survives(self):
        import ast

        calls = [
            node for node in ast.walk(self._tree())
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "PoseEstimator"
        ]
        assert calls, "PoseEstimator is never constructed"
        assert any(not c.args and not c.keywords for c in calls), (
            "the non-piste branch must stay a bare PoseEstimator() — passing "
            "piste settings there would change TV-broadcast results"
        )

    def test_piste_branch_passes_gate(self):
        import ast

        gated = [
            node for node in ast.walk(self._tree())
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "PoseEstimator"
            and any(kw.arg == "piste_gate" for kw in node.keywords)
        ]
        assert gated, "piste mode must construct PoseEstimator with piste_gate="

    def test_source_type_goes_through_helper(self):
        import ast

        called = {
            node.func.id
            for node in ast.walk(self._tree())
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "report_source_type" in called, (
            "meta.source_type must come from report_source_type(), otherwise a "
            "piste report is labelled tv_broadcast and the dashboard branches "
            "on the wrong source"
        )


class TestSuppliedLampPromotion:
    """The LED-scoreboard path supplies its own lamp fields.

    detect_touch_lamps.py cannot serve that path — it reads the lamp bar off the
    analysed video, which in piste mode is the piste crop, with no scoreboard in
    frame — so the unclear -> no_priority_call promotion has to happen during the
    merge. Without it the lamp fields reach the report but attack_outcome_detail
    stays None and no_priority_call_touches reads 0.
    """

    def _touch(self, pattern, scorer="left", outcome="unclear", **extra):
        t = {
            "touch_number": 1,
            "frame": 300,
            "scorer": scorer,
            "attack_outcome": outcome,
            "attack_outcome_ko": ATTACK_OUTCOME_KO[outcome],
            "attacker_side": extra.pop("attacker_side", None),
            "defender_side": None,
            "matched_exchange_number": None,
            "lamp_red": pattern in ("single_left", "double"),
            "lamp_green": pattern in ("single_right", "double"),
            "lamp_pattern": pattern,
            "lamp_confidence": 0.9 if pattern else 0.0,
            "lamp_scorer_conflict": lamp_scorer_conflict(pattern, scorer),
        }
        t.update(extra)
        return t

    def test_single_lamp_unclear_is_promoted(self):
        touches = [self._touch("single_left", scorer="left")]
        assert promote_supplied_lamp_outcomes(touches) == 1
        assert touches[0]["attack_outcome"] == NO_PRIORITY_CALL
        assert touches[0]["attack_outcome_detail"] == "single_lamp_no_priority_call"
        assert touches[0]["attack_outcome_detail_ko"]

    def test_promotion_reaches_the_summary(self):
        """The end the gap was actually observed at: the published counter."""
        touches = [
            self._touch("single_left", scorer="left"),
            self._touch("single_right", scorer="right"),
        ]
        before = summarize_attack_outcomes(touches)
        assert before["no_priority_call_touches"] == 0

        promote_supplied_lamp_outcomes(touches)
        after = summarize_attack_outcomes(touches)
        assert after["no_priority_call_touches"] == 2
        assert after["unclear_touches"] == 0

    def test_double_lamp_unclear_is_not_promoted(self):
        """Both lamps lit means the referee *did* rule on priority."""
        touches = [self._touch("double", scorer="left")]
        assert promote_supplied_lamp_outcomes(touches) == 0
        assert touches[0]["attack_outcome"] == "unclear"
        assert touches[0]["attack_outcome_detail"] == "double_lamp_referee_gave_scorer"

    def test_lamp_scorer_conflict_makes_the_lamp_ignored(self):
        """A green-only lamp cannot produce a left-side point: one read is wrong."""
        touches = [self._touch("single_right", scorer="left")]
        assert promote_supplied_lamp_outcomes(touches) == 0
        assert touches[0]["attack_outcome"] == "unclear"
        assert touches[0]["attack_outcome_detail"] is None
        assert touches[0]["lamp_scorer_conflict"] is True

    def test_conflict_survives_into_the_summary(self):
        touches = [self._touch("single_right", scorer="left")]
        promote_supplied_lamp_outcomes(touches)
        summary = summarize_attack_outcomes(touches)
        assert summary["lamp"]["conflict"] == 1
        assert summary["no_priority_call_touches"] == 0

    def test_decided_outcome_is_never_downgraded(self):
        touches = [self._touch(
            "single_left", scorer="left", outcome="attack_success",
            attacker_side="left",
        )]
        assert promote_supplied_lamp_outcomes(touches) == 0
        assert touches[0]["attack_outcome"] == "attack_success"
        assert touches[0]["attack_outcome_detail"] == "clean_hit"

    def test_touch_without_lamp_still_gets_uniform_shape(self):
        """Mixed reports must not have touches with different key sets."""
        touches = [self._touch(None, scorer="left")]
        assert promote_supplied_lamp_outcomes(touches) == 0
        assert touches[0]["attack_outcome"] == "unclear"
        for key in (
            "lamp_pattern", "lamp_confidence", "lamp_detail",
            "lamp_scorer_conflict", "attack_outcome_detail",
            "attack_outcome_detail_ko",
        ):
            assert key in touches[0]

    def test_lamp_detail_records_the_source_without_inventing_metrics(self):
        """A physical box yields no fill/duration measurements — none are faked."""
        touches = [self._touch("single_left", scorer="left")]
        promote_supplied_lamp_outcomes(touches)
        detail = touches[0]["lamp_detail"]
        assert detail["source"] == "led_scoreboard"
        assert detail["pattern"] == "single_left"
        assert "peak_fill" not in detail
        assert detail.get("lead_frames") is None

    def test_unreadable_confidence_does_not_raise(self):
        touches = [self._touch("single_left", scorer="left", lamp_confidence=None)]
        promote_supplied_lamp_outcomes(touches)
        assert touches[0]["lamp_confidence"] == 0.0
        assert touches[0]["attack_outcome"] == NO_PRIORITY_CALL

    def test_idempotent(self):
        """Re-running must not flip a promoted touch back or double-count."""
        touches = [self._touch("single_left", scorer="left")]
        promote_supplied_lamp_outcomes(touches)
        first = dict(touches[0])
        assert promote_supplied_lamp_outcomes(touches) == 0
        assert touches[0] == first

    def test_empty_and_none_inputs(self):
        assert promote_supplied_lamp_outcomes([]) == 0
        assert promote_supplied_lamp_outcomes(None) == 0


class TestReportCarriesLampFields:
    """The guard that keeps this a no-op for TV-broadcast reports."""

    def test_tv_shaped_touches_have_no_lamp_fields(self):
        """TV OCR reports get their lamps later, from detect_touch_lamps.py."""
        tv_touches = [
            {"touch_number": 1, "frame": 300, "scorer": "left",
             "video_timestamp": "0:10", "match_time": "2:50"},
        ]
        assert report_carries_lamp_fields(tv_touches) is False

    def test_led_shaped_touches_are_detected(self):
        assert report_carries_lamp_fields([{"lamp_pattern": "single_left"}]) is True

    def test_explicit_null_pattern_still_counts_as_supplied(self):
        """The LED converter writes lamp_pattern=None when no lamp fired."""
        assert report_carries_lamp_fields([{"lamp_pattern": None}]) is True

    def test_empty_inputs(self):
        assert report_carries_lamp_fields([]) is False
        assert report_carries_lamp_fields(None) is False

    def test_tv_shaped_report_is_untouched_by_the_guarded_path(self):
        """End-to-end no-op check: guard False -> touches identical."""
        import copy

        tv_touches = [
            {"touch_number": 1, "frame": 300, "scorer": "left",
             "attack_outcome": "unclear", "attacker_side": None},
            {"touch_number": 2, "frame": 900, "scorer": "right",
             "attack_outcome": "attack_success", "attacker_side": "right"},
        ]
        original = copy.deepcopy(tv_touches)
        if report_carries_lamp_fields(tv_touches):
            promote_supplied_lamp_outcomes(tv_touches)
        assert tv_touches == original
        assert summarize_attack_outcomes(tv_touches) == summarize_attack_outcomes(original)


class TestLampPromotionWiredIntoMerge:
    """AST guard: the promotion must stay in the merge block.

    It has no visible effect on a TV report, so a later cleanup could delete the
    call and every existing test would still pass — while LED reports silently
    went back to reporting no_priority_call_touches=0.
    """

    def test_promotion_is_called(self):
        import ast
        import inspect

        import scripts.generate_continuous_report as module

        tree = ast.parse(inspect.getsource(module))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "promote_supplied_lamp_outcomes" in called
        assert "report_carries_lamp_fields" in called


class TestWeaponOverrideAppliesWithoutOcr:
    """``--weapon`` must win in pose-only runs, not just when OCR is merged.

    The override used to sit inside ``if ocr_report is not None:``. A piste
    work file has no OCR report in the normal case, so the flag looked accepted
    while ``summary.weapon`` kept the hardcoded ``"epee"`` default — and foil
    priority estimation, which is gated on the weapon, stayed off silently.
    Measured on the 260815 pool bout: ``--weapon foil`` produced a report
    reading ``weapon: epee``.
    """

    def _assignment(self):
        import ast
        import inspect

        import scripts.generate_continuous_report as module

        tree = ast.parse(inspect.getsource(module))
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not (isinstance(node.value, ast.Attribute)
                    and node.value.attr == "weapon"
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "args"):
                continue
            found.append(node)
        return tree, found

    def test_override_exists(self):
        _, found = self._assignment()
        assert found, "no `... = args.weapon` assignment found in the module"

    def test_override_is_not_nested_under_the_ocr_branch(self):
        import ast

        tree, found = self._assignment()

        def owns(stmt, target):
            for node in ast.walk(stmt):
                if node is target:
                    return True
            return False

        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = ast.dump(node.test)
            if "ocr_report" not in test and "ocr_touches" not in test:
                continue
            for target in found:
                assert not any(owns(s, target) for s in node.body), (
                    "the --weapon override is nested inside an OCR branch; "
                    "pose-only runs would ignore the flag"
                )
