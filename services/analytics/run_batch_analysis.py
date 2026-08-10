"""Batch OCR analysis for downloaded YouTube fencing bout videos.

Runs TVOverlayOCR + TVScoreTracker → tv_ocr_to_match_report for each video,
saves JSON reports, and prints summary.
"""

import json
import os
import time
import cv2

from analyzer.tv_overlay_ocr import TVOverlayOCR, TVScoreTracker
from app.tv_report_converter import tv_ocr_to_match_report
from app.metadata_parser import parse_fencing_metadata


VIDEOS = [
    {
        "path": "data/raw/jr_foil_final_li_lin_hKUXgUsDOKE.mp4",
        "title": "Final - Junior Men's Foil - (Li - Lin) -- April - Richmond, NC - 2026",
        "sample_interval": 5,
    },
    {
        "path": "data/raw/div1_epee_final_knysh_wimmer_UzQ8Ci7lft8.mp4",
        "title": "Final - Div I Men's Epee - (Knysh - Wimmer) -- April - Richmond, NC - 2026",
        "sample_interval": 5,
    },
    {
        "path": "data/raw/jr_saber_final_primus_kovalev_B6k6SoJFAr8.mp4",
        "title": "Final - Junior Men's Saber - (Primus - Kovalev) -- April - Richmond, NC - 2026",
        "sample_interval": 5,
    },
]


def analyze_video(video_info: dict) -> dict:
    """Run full OCR analysis pipeline on one video."""
    path = video_info["path"]
    title = video_info["title"]
    sample_interval = video_info.get("sample_interval", 5)

    print(f"\n{'='*70}")
    print(f"Analyzing: {title}")
    print(f"File: {path}")
    print(f"Sample interval: {sample_interval}")
    print(f"{'='*70}")

    # Parse metadata from title
    metadata = parse_fencing_metadata(title)
    print(f"Metadata: weapon={metadata['weapon']}, gender={metadata['gender']}, "
          f"age_group={metadata['age_group']}, bout_type={metadata['bout_type']}, "
          f"expected_final={metadata['expected_final_score']}")

    # Open video
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return {"error": f"Cannot open {path}"}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / fps

    print(f"Video: {width}x{height} @ {fps:.1f}fps, "
          f"{total_frames} frames, {duration:.1f}s ({duration/60:.1f}min)")
    print(f"OCR frames to process: ~{total_frames // sample_interval}")

    # Run OCR
    ocr = TVOverlayOCR(layout="usa_fencing")
    tracker = TVScoreTracker()

    start_time = time.time()
    frame_num = 0
    ocr_count = 0
    read_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_num += 1

        if frame_num % sample_interval != 0:
            continue

        data = ocr.read_overlay(frame)
        ocr_count += 1

        if data is not None:
            read_count += 1
            tracker.update(frame_num, data, fps=fps)

        if frame_num % 3000 == 0:
            elapsed = time.time() - start_time
            events_so_far = tracker.get_all_events()
            pct = (frame_num / total_frames) * 100
            print(f"  Frame {frame_num}/{total_frames} ({pct:.0f}%): "
                  f"{len(events_so_far)} touches, "
                  f"{elapsed:.0f}s elapsed, "
                  f"reads: {read_count}/{ocr_count}")

    cap.release()
    analysis_time = time.time() - start_time

    events = tracker.get_all_events()
    summary = tracker.get_summary()

    print(f"\n  Scan complete: {len(events)} touches in {frame_num} frames")
    print(f"  OCR success rate: {read_count}/{ocr_count} "
          f"({read_count/ocr_count*100:.0f}%)" if ocr_count > 0 else "")
    print(f"  Analysis time: {analysis_time:.1f}s ({analysis_time/60:.1f}min)")
    print(f"  Summary: {summary}")

    if not events:
        print("  WARNING: No touch events detected!")
        return {
            "video": path,
            "title": title,
            "metadata": metadata,
            "events": 0,
            "analysis_time_sec": analysis_time,
            "error": "No touch events detected",
        }

    # Extract names from tracker summary
    left_name = summary.get("left_name", "Left")
    right_name = summary.get("right_name", "Right")

    # Generate match report
    report = tv_ocr_to_match_report(
        events=events,
        summary=summary,
        left_name=left_name,
        right_name=right_name,
        video_path=path,
        analysis_time_sec=analysis_time,
        total_frames=total_frames,
        fps=fps,
        expected_final_score=metadata.get("expected_final_score"),
    )

    # Inject metadata
    report["summary"]["weapon"] = metadata.get("weapon", "unknown")
    report["summary"]["gender"] = metadata.get("gender", "unknown")
    report["summary"]["age_group"] = metadata.get("age_group", "unknown")
    report["summary"]["bout_type"] = metadata.get("bout_type", "unknown")

    # Print results
    print(f"\n  === RESULTS ===")
    print(f"  Left:  {left_name}")
    print(f"  Right: {right_name}")
    print(f"  Final score: {report['summary'].get('final_score', 'N/A')}")
    print(f"  Total touches: {report['summary'].get('total_touches', 0)}")
    print(f"  Weapon: {report['summary']['weapon']}")
    print(f"  Gender: {report['summary']['gender']}")
    print(f"  Age group: {report['summary']['age_group']}")
    print(f"  Bout type: {report['summary']['bout_type']}")

    if report.get("warnings"):
        for w in report["warnings"]:
            print(f"  WARNING: {w['message']}")

    if report.get("insights"):
        for insight in report["insights"]:
            print(f"  Insight [{insight['category']}]: {insight['message']}")

    # Print touch list
    print(f"\n  Touch list:")
    for i, t in enumerate(report.get("touches", []), 1):
        scorer = t.get("scorer_name", t.get("scorer", "?"))
        score = t.get("score_after", "?")
        match_time = t.get("match_time", "?")
        print(f"    {i:2d}. {scorer:20s} → {score:6s} (time: {match_time})")

    return {
        "video": path,
        "title": title,
        "metadata": metadata,
        "report": report,
        "analysis_time_sec": analysis_time,
        "ocr_success_rate": read_count / ocr_count if ocr_count > 0 else 0,
    }


def main():
    results = []
    total_start = time.time()

    for video_info in VIDEOS:
        result = analyze_video(video_info)
        results.append(result)

        # Save individual report
        report_name = os.path.splitext(os.path.basename(video_info["path"]))[0]
        report_path = f"data/raw/{report_name}_report.json"
        with open(report_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\n  Report saved: {report_path}")

    total_time = time.time() - total_start
    print(f"\n{'='*70}")
    print(f"BATCH ANALYSIS COMPLETE")
    print(f"Total time: {total_time:.1f}s ({total_time/60:.1f}min)")
    print(f"Videos analyzed: {len(results)}")
    print(f"{'='*70}")

    for r in results:
        title = r.get("title", "?")
        touches = r.get("report", {}).get("summary", {}).get("total_touches", 0)
        score = r.get("report", {}).get("summary", {}).get("final_score", "N/A")
        atime = r.get("analysis_time_sec", 0)
        ocr_rate = r.get("ocr_success_rate", 0)
        print(f"  {title[:60]:60s} | {touches:2d} touches | {score:6s} | "
              f"{atime:.0f}s | OCR {ocr_rate:.0%}")


if __name__ == "__main__":
    main()
