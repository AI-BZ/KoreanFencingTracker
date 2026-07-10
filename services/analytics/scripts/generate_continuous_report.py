"""
Generate a continuous analysis report from a full bout video.

Runs YOLO11-Pose → PoseAnalyzer.analyze_continuous() → FencerProfileBuilder
and saves the result as a report-compatible JSON for the web dashboard.

Usage:
    cd services/analytics
    PYTHONPATH=. .venv/bin/python3 scripts/generate_continuous_report.py data/raw/usa_fencing_sample_0HeqT9us5wA.mp4
    PYTHONPATH=. .venv/bin/python3 scripts/generate_continuous_report.py data/raw/usa_fencing_sample_0HeqT9us5wA.mp4 --my-fencer left
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import cv2
except ImportError:
    print("ERROR: opencv-python required.")
    sys.exit(1)


def format_timestamp(frame: int, fps: float) -> str:
    """Convert frame number to MM:SS string."""
    seconds = frame / fps
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def _distance_zone(bh: float) -> str:
    """Map BH distance to zone name."""
    if bh > 1.8:
        return "out_of_distance"
    elif bh > 1.5:
        return "advance_lunge"
    elif bh > 1.2:
        return "lunge"
    elif bh > 0.8:
        return "extension"
    else:
        return "infighting"


def main():
    parser = argparse.ArgumentParser(description="Generate continuous analysis report")
    parser.add_argument("video", type=str, help="Path to video file")
    parser.add_argument(
        "--my-fencer", type=str, default="left", choices=["left", "right"],
        help="Fencer side for perspective analysis",
    )
    parser.add_argument(
        "--sample-every", type=int, default=3,
        help="Frame sampling interval (default: 3)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="data/reports",
        help="Output directory for report JSON",
    )
    parser.add_argument(
        "--merge-ocr", type=str, default=None,
        help="Path to existing OCR report JSON to merge scoring data (auto-detected if not specified)",
    )
    parser.add_argument(
        "--with-overlays", action="store_true",
        help="Generate pose-overlay mp4 clips for each event after report generation",
    )
    parser.add_argument(
        "--overlays-all", action="store_true",
        help="Generate overlay clips for all exchanges (not just touches). Implies --with-overlays",
    )
    args = parser.parse_args()

    if args.overlays_all:
        args.with_overlays = True

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"ERROR: Video not found: {video_path}")
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Video info
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"ERROR: Cannot open video: {video_path}")
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps

    # Extract frames
    print(f"\n{'='*60}")
    print(f"  Continuous Analysis Report Generator")
    print(f"{'='*60}")
    print(f"  Video:       {video_path.name}")
    print(f"  Duration:    {int(duration_sec//60)}:{int(duration_sec%60):02d}")
    print(f"  FPS:         {fps:.1f}")
    print(f"  Total frames:{total_frames}")
    print(f"  Sample every:{args.sample_every}")
    print(f"  My fencer:   {args.my_fencer}")
    print(f"{'='*60}\n")

    print("Reading frames...", end=" ", flush=True)
    frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()
    print(f"{len(frames)} frames read.")

    # Import ML modules
    from ml.pose_estimator import PoseEstimator
    from ml.pose_analyzer import PoseAnalyzer
    from ml.fencer_profile import FencerProfileBuilder

    print("Loading YOLO11-Pose model...")
    estimator = PoseEstimator()
    analyzer = PoseAnalyzer()
    analyzer.fps = fps

    # Sample frames for batch processing
    sampled_frames = frames[::args.sample_every]
    print(f"Running pose estimation on {len(sampled_frames)} sampled frames...")

    t0 = time.time()
    pose_results = estimator.estimate_poses_batch(sampled_frames)

    # Load OCR report early so we can extract scoring_frames for analyze_continuous()
    ocr_report = None
    ocr_path = args.merge_ocr
    if ocr_path is None:
        video_id = video_path.stem
        for prefix in ("usaf_", "usa_fencing_sample_"):
            if video_id.startswith(prefix):
                video_id = video_id[len(prefix):]
                break
        for candidate in output_dir.glob("*_report.json"):
            if video_id in candidate.stem and "_continuous_report" not in candidate.stem:
                ocr_path = str(candidate)
                break

    scoring_frames_sampled: set = set()
    if ocr_path and Path(ocr_path).exists():
        print(f"  Loading OCR data from: {ocr_path}")
        with open(ocr_path, "r", encoding="utf-8") as f:
            ocr_report = json.load(f)
        ocr_touches = ocr_report.get("touches", [])
        if ocr_touches:
            # Extract scoring frame indices and convert to sampled indices
            scoring_frames_raw = {t.get("frame", 0) for t in ocr_touches}
            scoring_frames_sampled = {f // args.sample_every for f in scoring_frames_raw}
            print(f"  Scoring frames: {len(scoring_frames_sampled)} (from {len(ocr_touches)} OCR touches)")

    # Run continuous analysis
    print("Running continuous analysis...")
    continuous_result = analyzer.analyze_continuous(
        pose_sequence=pose_results,
        sample_every_n=1,  # Already sampled
        my_fencer=args.my_fencer,
        scoring_frames=scoring_frames_sampled if scoring_frames_sampled else None,
    )
    t_analysis = time.time() - t0

    print(f"  Exchanges detected: {continuous_result.total_exchanges}")
    print(f"  Analysis time: {t_analysis:.1f}s")

    # Build FencerProfile from continuous data
    builder_left = FencerProfileBuilder("left")
    builder_right = FencerProfileBuilder("right")
    builder_left.add_continuous(continuous_result)
    builder_right.add_continuous(continuous_result)
    profile_left = builder_left.build()
    profile_right = builder_right.build()

    # Detect handedness
    handedness_left, hconf_left = analyzer.detect_handedness(pose_results, "left")
    handedness_right, hconf_right = analyzer.detect_handedness(pose_results, "right")

    profile_left.handedness = handedness_left
    profile_left.handedness_confidence = hconf_left
    profile_right.handedness = handedness_right
    profile_right.handedness_confidence = hconf_right

    if handedness_left:
        hand_ko = "오른손잡이" if handedness_left == "right" else "왼손잡이"
        print(f"  Left fencer: {hand_ko} (confidence: {hconf_left})")
    if handedness_right:
        hand_ko = "오른손잡이" if handedness_right == "right" else "왼손잡이"
        print(f"  Right fencer: {hand_ko} (confidence: {hconf_right})")

    # Build exchange list for report
    exchanges_list = []
    event_type_ko = {
        "failed_attack": "실패한 공격",
        "successful_defense": "방어 성공",
        "mutual_retreat": "상호 후퇴",
        "off_target": "비유효면",
        "missed_entirely": "완전 빗나감",
        "unknown_exchange": "분류 미정",
        "neutral": "판정 보류",
    }

    for i, ex in enumerate(continuous_result.exchanges, 1):
        # Adjust frame numbers for sampling
        actual_start = ex.start_frame * args.sample_every
        actual_end = ex.end_frame * args.sample_every
        actual_min = ex.min_distance_frame * args.sample_every
        duration = (actual_end - actual_start) / fps

        ex_dict = {
            "exchange_number": i,
            "start_time": format_timestamp(actual_start, fps),
            "end_time": format_timestamp(actual_end, fps),
            "start_frame": actual_start,
            "end_frame": actual_end,
            "event_type": ex.event_type.value,
            "event_type_ko": event_type_ko.get(ex.event_type.value, ex.event_type.value),
            "duration_sec": round(duration, 1),
            "min_distance_bh": round(ex.min_distance_bh, 2),
        }

        # Add footwork info
        fw_left_val = None
        fw_right_val = None
        if ex.footwork_left is not None:
            fw_left_val = ex.footwork_left.footwork_type.value
            ex_dict["footwork_left"] = fw_left_val
        if ex.footwork_right is not None:
            fw_right_val = ex.footwork_right.footwork_type.value
            ex_dict["footwork_right"] = fw_right_val
        if ex.parry_left is not None and ex.parry_left.parry_detected:
            ex_dict["parry_left"] = True
        if ex.parry_right is not None and ex.parry_right.parry_detected:
            ex_dict["parry_right"] = True

        # Determine attacker/defender based on footwork
        aggressive = {"lunge", "fleche", "advance"}
        left_attacking = fw_left_val in aggressive
        right_attacking = fw_right_val in aggressive

        if left_attacking and not right_attacking:
            ex_dict["attacker"] = "left"
            ex_dict["defender"] = "right"
        elif right_attacking and not left_attacking:
            ex_dict["attacker"] = "right"
            ex_dict["defender"] = "left"
        elif left_attacking and right_attacking:
            ex_dict["attacker"] = "both"
            ex_dict["defender"] = "both"
        else:
            ex_dict["attacker"] = "unknown"
            ex_dict["defender"] = "unknown"

        exchanges_list.append(ex_dict)

    # Count exchange types
    from collections import Counter
    type_counts = Counter(ex.event_type.value for ex in continuous_result.exchanges)

    # Build per-fencer exchange stats from exchanges_list
    fencer_exchange_stats = {"left": {"attacks": 0, "defenses": 0}, "right": {"attacks": 0, "defenses": 0}}
    for ex in exchanges_list:
        att = ex.get("attacker")
        if att == "left":
            fencer_exchange_stats["left"]["attacks"] += 1
            fencer_exchange_stats["right"]["defenses"] += 1
        elif att == "right":
            fencer_exchange_stats["right"]["attacks"] += 1
            fencer_exchange_stats["left"]["defenses"] += 1
        elif att == "both":
            fencer_exchange_stats["left"]["attacks"] += 1
            fencer_exchange_stats["right"]["attacks"] += 1

    # Build report dict
    match_duration = f"{int(duration_sec//60)}:{int(duration_sec%60):02d}"
    video_stem = video_path.stem

    report_dict = {
        "summary": {
            "video_path": str(video_path),
            "final_score": "연속 분석",
            "total_touches": 0,
            "match_duration": match_duration,
            "total_frames_analyzed": len(sampled_frames),
            "analysis_time_sec": round(t_analysis, 1),
            "weapon": "epee",
            "bout_type": "de",
            "gender": None,
            "age_group": None,
        },
        "touches": [],
        "left_fencer": {
            "name": "Left Fencer",
            "club": "",
            "handedness": handedness_left,
            "handedness_confidence": hconf_left,
            "total_touches_scored": 0,
            "total_touches_conceded": 0,
            "most_common_action": None,
            "most_common_action_pct": 0,
            "action_distribution": [],
        },
        "right_fencer": {
            "name": "Right Fencer",
            "club": "",
            "handedness": handedness_right,
            "handedness_confidence": hconf_right,
            "total_touches_scored": 0,
            "total_touches_conceded": 0,
            "most_common_action": None,
            "most_common_action_pct": 0,
            "action_distribution": [],
        },
        "fencer_profile": {
            "left": profile_left.to_dict(),
            "right": profile_right.to_dict(),
        },
        "exchanges": exchanges_list,
        "continuous_summary": {
            "total_exchanges": continuous_result.total_exchanges,
            "scoring_exchanges": continuous_result.scoring_exchanges,
            "non_scoring_exchanges": continuous_result.non_scoring_exchanges,
            "type_distribution": dict(type_counts),
            "fencer_stats": fencer_exchange_stats,
        },
        "insights": [],
        "warnings": [],
        "meta": {
            "phase": 6,
            "pose_model": "YOLO11-Pose",
            "action_model": None,
            "pose_enabled": True,
            "action_enabled": False,
            "confidence_threshold": 0.0,
            "source_type": "tv_broadcast",
            "analysis_mode": "continuous_only",
            "fps": fps,
        },
    }

    # Add my_fencer_summary if available
    if continuous_result.my_fencer_summary is not None:
        report_dict["my_fencer_summary"] = continuous_result.my_fencer_summary.to_dict()

    # Add frame action state summary (not individual frames — too large)
    if continuous_result.frame_actions:
        from collections import Counter as _Ctr
        action_state_summary = {}
        for side in ("left", "right"):
            states = continuous_result.frame_actions.get(side, [])
            if states:
                state_counts = _Ctr(s.state.value for s in states)
                total = sum(state_counts.values())
                action_state_summary[side] = {
                    "total_frames": total,
                    "distribution": {
                        state: {"count": count, "pct": round(count / total * 100, 1)}
                        for state, count in state_counts.most_common()
                    },
                }
        if action_state_summary:
            report_dict["action_state_summary"] = action_state_summary

    # Store scoring frames for transparency
    if scoring_frames_sampled:
        report_dict["scoring_frames"] = sorted([f * args.sample_every for f in scoring_frames_sampled])

    # Merge OCR scoring data if available (ocr_report already loaded above)
    if ocr_report is not None:
        print(f"\n  Merging OCR data from: {ocr_path}")

        # Merge scoring data
        ocr_touches = ocr_report.get("touches", [])
        if ocr_touches:
            # Fix match_time: if all values are the same (e.g. "3:00"), OCR
            # failed to read the clock — fall back to video_timestamp
            match_times = [t.get("match_time") for t in ocr_touches]
            all_same = len(set(match_times)) <= 1
            if all_same:
                for t in ocr_touches:
                    t["match_time"] = t.get("video_timestamp", t.get("match_time", ""))

            # Enrich touches with nearest exchange pose data + derive action labels
            prev_scorer = None
            prev_frame = -99999
            for t in ocr_touches:
                touch_frame = t.get("frame", 0)
                scorer = t.get("scorer", "left")
                best_ex = None
                best_dist = float("inf")
                for ex in exchanges_list:
                    # Find exchange closest to this touch frame
                    mid = (ex["start_frame"] + ex["end_frame"]) // 2
                    d = abs(touch_frame - mid)
                    if d < best_dist:
                        best_dist = d
                        best_ex = ex
                if best_ex and best_dist < fps * 10:  # within 10 seconds
                    opponent = "right" if scorer == "left" else "left"
                    parry_detected = best_ex.get(f"parry_{opponent}", False)
                    fw_scorer = best_ex.get(f"footwork_{scorer}", None)
                    fw_opponent = best_ex.get(f"footwork_{opponent}", None)

                    t["pose_analysis"] = {
                        "distance_bh": best_ex.get("min_distance_bh", 0),
                        "distance_zone": _distance_zone(best_ex.get("min_distance_bh", 0)),
                        "footwork_scorer": fw_scorer,
                        "footwork_opponent": fw_opponent,
                        "parry_detected": parry_detected,
                    }

                    # Derive action label from pose analysis
                    is_remise = (
                        scorer == prev_scorer
                        and (touch_frame - prev_frame) / fps < 2.0
                    )
                    if is_remise:
                        action = "remise"
                        t["action_confidence"] = 0.8
                    elif parry_detected:
                        action = "riposte"
                        t["action_confidence"] = 0.85
                    else:
                        action = "attack"
                        t["action_confidence"] = 0.7
                    t["action_scorer"] = action
                    t["action_opponent"] = "parry" if parry_detected else "unknown"

                prev_scorer = scorer
                prev_frame = touch_frame

            report_dict["touches"] = ocr_touches
            report_dict["summary"]["total_touches"] = len(ocr_touches)
            report_dict["summary"]["final_score"] = ocr_report.get("summary", {}).get("final_score", "연속 분석")

        # Compute per-fencer action distribution from derived labels
        from collections import Counter as _Counter
        for side in ("left", "right"):
            side_key = f"{side}_fencer"
            scored = [t for t in ocr_touches if t.get("scorer") == side]
            conceded = [t for t in ocr_touches if t.get("scorer") != side]
            report_dict[side_key]["total_touches_scored"] = len(scored)
            report_dict[side_key]["total_touches_conceded"] = len(conceded)

            action_counts = _Counter(
                t.get("action_scorer", "unknown") for t in scored
            )
            total = sum(action_counts.values())
            if total > 0:
                most_common = action_counts.most_common(1)[0]
                report_dict[side_key]["most_common_action"] = most_common[0]
                report_dict[side_key]["most_common_action_pct"] = round(most_common[1] / total * 100)
                report_dict[side_key]["action_distribution"] = [
                    {"action": a, "count": c, "pct": round(c / total * 100)}
                    for a, c in action_counts.most_common()
                ]

        # Merge fencer names from OCR
        for side in ("left_fencer", "right_fencer"):
            ocr_fencer = ocr_report.get(side, {})
            if ocr_fencer.get("name") and ocr_fencer["name"] not in ("Left", "Right"):
                report_dict[side]["name"] = ocr_fencer["name"]
            if ocr_fencer.get("club"):
                report_dict[side]["club"] = ocr_fencer["club"]

        # Merge summary fields from OCR (weapon, bout_type, gender, age_group)
        ocr_summary = ocr_report.get("summary", {})
        for key in ("weapon", "bout_type", "gender", "age_group"):
            if ocr_summary.get(key):
                report_dict["summary"][key] = ocr_summary[key]

        # Merge metadata
        report_dict["meta"]["analysis_mode"] = "continuous_with_ocr"
        report_dict["meta"]["ocr_source"] = Path(ocr_path).name

        # Merge OCR warnings
        for w in ocr_report.get("warnings", []):
            report_dict["warnings"].append(w)

        # Store clock events (Allez/Halt proxy) from OCR if available
        clock_events = ocr_report.get("clock_events", [])
        if clock_events:
            report_dict["clock_events"] = clock_events
            print(f"  Clock events: {len(clock_events)} (allez/halt)")

        print(f"  OCR touches merged: {len(ocr_touches)}")
        print(f"  Final score: {report_dict['summary']['final_score']}")
    else:
        if args.merge_ocr and not ocr_report:
            print(f"\n  WARNING: OCR report not found: {args.merge_ocr}")

    # Auto-generate insights from continuous analysis
    insights = []
    if continuous_result.total_exchanges > 0:
        insights.append({
            "category": "exchange_summary",
            "target": "both",
            "message": f"총 {continuous_result.total_exchanges}회 교환 감지",
            "severity": "info",
            "evidence": f"실패 공격 {type_counts.get('failed_attack', 0)}회, "
                       f"방어 성공 {type_counts.get('successful_defense', 0)}회, "
                       f"상호 후퇴 {type_counts.get('mutual_retreat', 0)}회",
        })

    # Per-fencer attack/defense insights from exchange stats
    for side in ("left", "right"):
        side_ko = "왼쪽" if side == "left" else "오른쪽"
        stats = fencer_exchange_stats[side]
        if stats["attacks"] > 0:
            insights.append({
                "category": "attack_analysis",
                "target": side,
                "message": f"{side_ko} 선수: 비득점 교환 중 공격 시도 {stats['attacks']}회",
                "severity": "info",
                "evidence": f"적극적 풋워크(전진/런지/플레쉬) 기반 공격 감지",
            })
        if stats["defenses"] > 0:
            insights.append({
                "category": "defense_analysis",
                "target": side,
                "message": f"{side_ko} 선수: 상대 공격 방어 {stats['defenses']}회",
                "severity": "info",
                "evidence": f"상대의 적극적 접근에 대한 방어/후퇴 감지",
            })

    # Add FencerProfile insights
    for side, profile in [("left", profile_left), ("right", profile_right)]:
        for s in profile.strengths:
            insights.append({
                "category": "strength",
                "target": side,
                "message": s,
                "severity": "info",
                "evidence": "",
            })
        for w in profile.weaknesses:
            insights.append({
                "category": "weakness",
                "target": side,
                "message": w,
                "severity": "warning",
                "evidence": "",
            })

    report_dict["insights"] = insights

    # Add warnings
    report_dict["warnings"].append({
        "type": "continuous_only",
        "message": "이 리포트는 연속 포즈 분석 결과입니다. 득점 정보(OCR/LED)가 포함되지 않아 공격 성공률이 정확하지 않을 수 있습니다.",
        "severity": "info",
    })

    # Save
    report_id = f"{video_stem}_continuous_report"
    output_path = output_dir / f"{report_id}.json"

    # Store video_path in meta for clip generation
    report_dict["meta"]["video_path"] = str(video_path.resolve())

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2, ensure_ascii=False)

    # Generate overlay clips (optional)
    clip_results = []
    if args.with_overlays:
        print("\nGenerating pose-overlay clips...")
        from ml.clip_overlay import ClipOverlayGenerator
        clip_gen = ClipOverlayGenerator()
        clips_dir = Path("data/clips/overlay") / report_id
        touches_only = not args.overlays_all
        t_clips_start = time.time()
        clip_results = clip_gen.generate_clips_for_report(
            str(video_path), report_dict, str(clips_dir),
            touches_only=touches_only,
        )
        t_clips = time.time() - t_clips_start
        print(f"  {len(clip_results)} clips generated in {t_clips:.1f}s")

        # Add clip paths to report
        report_dict["clip_paths"] = clip_results
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"\n{'='*60}")
    print(f"  Report Generated")
    print(f"{'='*60}")
    print(f"  Output:      {output_path}")
    print(f"  Exchanges:   {continuous_result.total_exchanges}")
    for etype, count in sorted(type_counts.items()):
        print(f"    {etype}: {count}")
    my_stats = fencer_exchange_stats.get(args.my_fencer, {})
    if my_stats:
        print(f"  {args.my_fencer} fencer:")
        print(f"    Attacks:  {my_stats.get('attacks', 0)}")
        print(f"    Defenses: {my_stats.get('defenses', 0)}")
    print(f"  Duration:    {match_duration}")
    print(f"  Processing:  {t_analysis:.1f}s ({t_analysis/duration_sec:.2f}x realtime)")
    if clip_results:
        print(f"  Clips:       {len(clip_results)} generated")
    print(f"{'='*60}")
    print(f"\n  View at: http://localhost:76/report/saved/{report_id}")


if __name__ == "__main__":
    main()
