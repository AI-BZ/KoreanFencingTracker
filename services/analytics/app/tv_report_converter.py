"""
Convert TVScoreTracker output to MatchReport dict format.

Transforms TVTouchEvent list + match_summary into the same dict
structure used by app/demo.py, so report.html + report.js can
render OCR-based broadcast analysis results without any template changes.
"""

from __future__ import annotations

from typing import Optional


def tv_ocr_to_match_report(
    events: list,
    summary: dict,
    left_name: Optional[str],
    right_name: Optional[str],
    video_path: str,
    analysis_time_sec: float,
    total_frames: int,
    fps: float = 30.0,
    expected_final_score: Optional[int] = None,
) -> dict:
    """Convert TVScoreTracker results to a MatchReport dict.

    Args:
        events: List of TVTouchEvent objects from TVScoreTracker.
        summary: Dict from TVScoreTracker.get_match_summary().
        left_name: Left fencer name extracted by OCR (or None).
        right_name: Right fencer name extracted by OCR (or None).
        video_path: Path to the analyzed video file.
        analysis_time_sec: Wall-clock seconds spent on analysis.
        total_frames: Total frames in the video.
        fps: Video frames per second.

    Returns:
        MatchReport dict compatible with report.html template.
    """
    total_touches = summary.get("total_touches", 0)
    final_score = summary.get("final_score", "0-0")
    left_touches = summary.get("left_touches", 0)
    right_touches = summary.get("right_touches", 0)

    # Estimate match duration from last event timestamp
    match_duration = _format_duration(events[-1].timestamp if events else 0.0)

    # Build touches list
    touches = []
    for i, evt in enumerate(events, start=1):
        video_ts = _format_timestamp(evt.timestamp)
        match_ts = evt.match_time_remaining if hasattr(evt, "match_time_remaining") and evt.match_time_remaining else video_ts
        touches.append({
            "touch_number": i,
            "frame": evt.frame,
            "video_timestamp": video_ts,
            "match_time": match_ts,
            "scorer": evt.scorer,
            "score_after": evt.score_after,
            "action_scorer": "unknown",
            "action_confidence": 0.0,
            "action_opponent": "unknown",
            "opponent_confidence": 0.0,
            "description": _generate_touch_description(
                i, evt.scorer, evt.score_after,
                left_name or "Left", right_name or "Right",
            ),
        })

    # Fencer stats (no action distribution in OCR mode)
    left_fencer = {
        "side": "left",
        "name": left_name or "Left Fencer",
        "club": "",
        "total_touches_scored": left_touches,
        "total_touches_conceded": right_touches,
        "action_distribution": [],
        "most_common_action": "unknown",
        "most_common_action_pct": 0.0,
    }

    right_fencer = {
        "side": "right",
        "name": right_name or "Right Fencer",
        "club": "",
        "total_touches_scored": right_touches,
        "total_touches_conceded": left_touches,
        "action_distribution": [],
        "most_common_action": "unknown",
        "most_common_action_pct": 0.0,
    }

    # Generate OCR-based insights
    insights = _generate_ocr_insights(
        events, left_name or "Left", right_name or "Right",
        left_touches, right_touches, final_score,
    )

    # Generate analysis warnings
    warnings = _generate_warnings(final_score, expected_final_score)

    return {
        "summary": {
            "video_path": video_path,
            "final_score": final_score,
            "total_touches": total_touches,
            "match_duration": match_duration,
            "total_frames_analyzed": total_frames,
            "analysis_time_sec": round(analysis_time_sec, 1),
            "weapon": "unknown",
            "bout_type": "unknown",
            "gender": "unknown",
            "age_group": "unknown",
        },
        "touches": touches,
        "left_fencer": left_fencer,
        "right_fencer": right_fencer,
        "insights": insights,
        "warnings": warnings,
        "meta": {
            "phase": 5,
            "pose_model": None,
            "action_model": None,
            "pose_enabled": False,
            "action_enabled": False,
            "confidence_threshold": 0.0,
            "source_type": "tv_broadcast",
            "analysis_mode": "ocr_only",
        },
    }


def _format_timestamp(seconds: float) -> str:
    """Format seconds as M:SS."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


def _format_duration(seconds: float) -> str:
    """Format total duration as M:SS."""
    return _format_timestamp(seconds)


def _generate_touch_description(
    touch_num: int,
    scorer: str,
    score_after: str,
    left_name: str,
    right_name: str,
) -> str:
    """Generate a basic description for an OCR-detected touch."""
    scorer_name = left_name if scorer == "left" else right_name
    return f"Touch {touch_num}: {scorer_name} scores ({score_after})"


def _generate_ocr_insights(
    events: list,
    left_name: str,
    right_name: str,
    left_touches: int,
    right_touches: int,
    final_score: str,
) -> list:
    """Generate insights from OCR score flow data."""
    insights = []

    if not events:
        return insights

    # Scoring momentum analysis
    total = left_touches + right_touches
    if total > 0:
        left_pct = round(100 * left_touches / total, 1)
        right_pct = round(100 * right_touches / total, 1)

        # Determine winner or draw
        if left_touches > right_touches:
            winner = left_name
            msg = (
                f"{winner} won {final_score} "
                f"({left_name} {left_pct}% vs {right_name} {right_pct}% scoring rate)"
            )
        elif right_touches > left_touches:
            winner = right_name
            msg = (
                f"{winner} won {final_score} "
                f"({left_name} {left_pct}% vs {right_name} {right_pct}% scoring rate)"
            )
        else:
            winner = "both"
            msg = (
                f"Match ended in a draw {final_score} "
                f"({left_name} {left_pct}% vs {right_name} {right_pct}% scoring rate)"
            )
        insights.append({
            "category": "score_flow",
            "target": winner,
            "message": msg,
            "severity": "info",
            "evidence": (
                f"{left_name}: {left_touches} touches scored, "
                f"{right_name}: {right_touches} touches scored"
            ),
        })

    # Scoring runs (consecutive touches by same fencer)
    if len(events) >= 3:
        max_run, run_scorer, run_start = _find_longest_run(events)
        if max_run >= 3:
            run_name = left_name if run_scorer == "left" else right_name
            insights.append({
                "category": "momentum",
                "target": run_name,
                "message": (
                    f"{run_name} had a {max_run}-touch scoring run "
                    f"starting at touch {run_start}"
                ),
                "severity": "warning",
                "evidence": f"Consecutive {max_run} touches without opponent scoring",
            })

    # Comeback detection
    comeback = _detect_comeback(events, left_name, right_name)
    if comeback:
        insights.append(comeback)

    # OCR mode notice
    insights.append({
        "category": "analysis_mode",
        "target": "system",
        "message": (
            "This analysis uses TV overlay OCR only. "
            "Action classification (attack/riposte/counter) is not available "
            "in broadcast OCR mode."
        ),
        "severity": "info",
        "evidence": "OCR-based score tracking from TV broadcast overlay",
    })

    return insights


def _generate_warnings(
    final_score: str,
    expected_final_score: Optional[int],
) -> list:
    """Generate analysis warnings (e.g., video truncation)."""
    warnings = []

    if expected_final_score:
        parts = final_score.split("-")
        try:
            max_score = max(int(p) for p in parts if p.isdigit())
        except ValueError:
            max_score = 0

        if max_score < expected_final_score:
            warnings.append({
                "type": "video_truncated",
                "message": (
                    f"Video appears truncated. Final score {final_score} "
                    f"did not reach expected {expected_final_score} points."
                ),
                "severity": "warning",
            })

    return warnings


def _find_longest_run(events: list) -> tuple:
    """Find the longest consecutive scoring run by one fencer.

    Returns:
        (run_length, scorer, start_touch_number)
    """
    max_run = 1
    max_scorer = events[0].scorer
    max_start = 1
    current_run = 1
    current_scorer = events[0].scorer
    current_start = 1

    for i in range(1, len(events)):
        if events[i].scorer == current_scorer:
            current_run += 1
        else:
            if current_run > max_run:
                max_run = current_run
                max_scorer = current_scorer
                max_start = current_start
            current_run = 1
            current_scorer = events[i].scorer
            current_start = i + 1

    if current_run > max_run:
        max_run = current_run
        max_scorer = current_scorer
        max_start = current_start

    return max_run, max_scorer, max_start


def _detect_comeback(events: list, left_name: str, right_name: str) -> Optional[dict]:
    """Detect if a fencer came back from a 3+ point deficit to win."""
    if len(events) < 5:
        return None

    # Track score gap through match
    max_left_deficit = 0
    max_right_deficit = 0

    for evt in events:
        parts = evt.score_after.split("-")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            left_s, right_s = int(parts[0]), int(parts[1])
            gap = left_s - right_s
            if gap < 0:
                max_left_deficit = max(max_left_deficit, abs(gap))
            elif gap > 0:
                max_right_deficit = max(max_right_deficit, gap)

    # Check final score
    last = events[-1].score_after
    parts = last.split("-")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        final_left, final_right = int(parts[0]), int(parts[1])

        if final_left > final_right and max_left_deficit >= 3:
            return {
                "category": "momentum",
                "target": left_name,
                "message": (
                    f"{left_name} came back from a {max_left_deficit}-point deficit to win"
                ),
                "severity": "warning",
                "evidence": (
                    f"Was trailing by {max_left_deficit} points during the match, "
                    f"finished {last}"
                ),
            }
        elif final_right > final_left and max_right_deficit >= 3:
            return {
                "category": "momentum",
                "target": right_name,
                "message": (
                    f"{right_name} came back from a {max_right_deficit}-point deficit to win"
                ),
                "severity": "warning",
                "evidence": (
                    f"Was trailing by {max_right_deficit} points during the match, "
                    f"finished {last}"
                ),
            }

    return None
