"""
Gemini Vision auto-labeler for fencing action clips.

Sends each clip to Gemini 2.5 Flash for 4-class blade action classification
(attack, riposte, counter_attack, remise) with direction (left/right).

Usage:
    GEMINI_API_KEY=... PYTHONPATH=. .venv/bin/python3 scripts/gemini_labeler.py
    GEMINI_API_KEY=... PYTHONPATH=. .venv/bin/python3 scripts/gemini_labeler.py --test
    GEMINI_API_KEY=... PYTHONPATH=. .venv/bin/python3 scripts/gemini_labeler.py --estimate
    GEMINI_API_KEY=... PYTHONPATH=. .venv/bin/python3 scripts/gemini_labeler.py --rpm 1000
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from ml.training.config import LABEL_TO_IDX

# Gemini classification prompt
CLASSIFICATION_PROMPT = """\
You are an expert fencing referee analyzing a slow-motion clip of a single touch.

Your task: classify the SCORING ACTION into one of 4 categories.

IMPORTANT ANALYSIS STEPS:

STEP 1 - WHO SCORED: Which fencer's light turned on? That is the scorer.

STEP 2 - WHAT DID THE NON-SCORER DO FIRST:
This is the KEY question. Focus on the NON-SCORING fencer's action BEFORE the touch:
- Did the non-scorer ATTACK FIRST (lunge/extend toward scorer)?
- Or was the non-scorer PASSIVE (standing, retreating, no offensive action)?

STEP 3 - CLASSIFY based on the non-scorer's action:

If non-scorer was PASSIVE/RETREATING (no attack):
  → ATTACK (scorer initiated, opponent did nothing offensive)

If non-scorer ATTACKED FIRST and scorer BLOCKED their blade then hit back:
  → RIPOSTE (parry then counter-hit; look for blade-on-blade deflection before scorer's hit)

If non-scorer ATTACKED FIRST and scorer hit WITHOUT blocking (no parry):
  → COUNTER_ATTACK (scorer hit into the incoming attack, both arms extending, no blade contact)

If scorer had ALREADY attacked once and hits again immediately:
  → REMISE (second attempt without withdrawing arm; two hitting motions in quick succession)

STEP 4 - ASSIGN PROBABILITIES for each class:

DIRECTION: LEFT = left-side fencer scored, RIGHT = right-side fencer scored.

Respond ONLY with valid JSON (no markdown):
{"action": "attack|riposte|counter_attack|remise", "direction": "left|right", "confidence": 0.0-1.0, "probabilities": {"attack": 0.0, "riposte": 0.0, "counter_attack": 0.0, "remise": 0.0}, "non_scorer_action": "describe what the NON-scoring fencer did", "reasoning": "full sequence description"}
"""

# Valid combined labels (must match LABEL_TO_IDX keys)
VALID_ACTIONS = {"attack", "riposte", "counter_attack", "remise"}
VALID_DIRECTIONS = {"left", "right"}


class GeminiLabeler:
    """Classify fencing clips using Gemini Vision API."""

    MAX_RETRIES = 3
    RETRY_DELAYS = [10, 30, 60]  # seconds

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
        rpm_limit: int = 15,
        results_path: Optional[Path] = None,
    ):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.rpm_limit = rpm_limit
        self.delay = 60.0 / rpm_limit
        self.results_path = results_path or Path("data/labeled/gemini_results.json")
        self.results: dict = {}
        self._load_existing()

    def _load_existing(self):
        """Load existing results for resume support."""
        if self.results_path.exists():
            with open(self.results_path, "r", encoding="utf-8") as f:
                self.results = json.load(f)
            print(f"Loaded {len(self.results)} existing results from {self.results_path}")

    def _save_results(self):
        """Save results to JSON."""
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.results_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

    def classify_clip(self, clip_path: Path) -> dict:
        """
        Upload a clip to Gemini and get action classification.
        Retries on transient errors (503, rate limit).

        Returns dict with: action, direction, combined_label, confidence, reasoning
        """
        uploaded = None

        for attempt in range(self.MAX_RETRIES):
            try:
                # Upload file (reuse if already uploaded)
                if uploaded is None:
                    uploaded = self.client.files.upload(
                        file=str(clip_path),
                        config=types.UploadFileConfig(mime_type="video/mp4"),
                    )

                    # Wait for processing
                    while uploaded.state == "PROCESSING":
                        time.sleep(2)
                        uploaded = self.client.files.get(name=uploaded.name)

                    if uploaded.state == "FAILED":
                        raise RuntimeError(f"Gemini file processing failed: {clip_path}")

                # Generate classification (disable thinking to save tokens)
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[uploaded, CLASSIFICATION_PROMPT],
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=1024,
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=0,
                        ),
                    ),
                )

                # Parse response
                result = self._parse_response(response.text)

                # Cleanup uploaded file
                try:
                    self.client.files.delete(name=uploaded.name)
                except Exception:
                    pass

                return result

            except Exception as e:
                err_str = str(e)
                is_retryable = any(k in err_str for k in ["503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded"])

                if is_retryable and attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_DELAYS[attempt]
                    print(f"    Retry {attempt+1}/{self.MAX_RETRIES} in {delay}s ({err_str[:80]})")
                    time.sleep(delay)
                    continue

                # Cleanup on final failure
                if uploaded:
                    try:
                        self.client.files.delete(name=uploaded.name)
                    except Exception:
                        pass
                raise

    def _parse_response(self, text: str) -> dict:
        """Parse Gemini JSON response, handling markdown code blocks and multiline."""
        if not text:
            return {
                "action": "attack",
                "direction": "left",
                "combined_label": "attack_left",
                "confidence": 0.0,
                "reasoning": "Empty response",
                "parse_error": True,
            }

        cleaned = text.strip()

        # Remove markdown code block wrapper (```json ... ```)
        md_match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL)
        if md_match:
            cleaned = md_match.group(1).strip()

        data = None

        # Try direct JSON parse first (most common case)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Extract first JSON object from text (handles surrounding text)
            brace_start = cleaned.find("{")
            if brace_start >= 0:
                # Find matching closing brace
                depth = 0
                for i in range(brace_start, len(cleaned)):
                    if cleaned[i] == "{":
                        depth += 1
                    elif cleaned[i] == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                data = json.loads(cleaned[brace_start:i+1])
                            except json.JSONDecodeError:
                                pass
                            break

        # Fallback: extract fields from truncated JSON via regex
        if data is None:
            data = {}
            action_m = re.search(r'"action"\s*:\s*"(\w+)"', cleaned, re.IGNORECASE)
            dir_m = re.search(r'"direction"\s*:\s*"(\w+)"', cleaned, re.IGNORECASE)
            conf_m = re.search(r'"confidence"\s*:\s*([\d.]+)', cleaned)
            reason_m = re.search(r'"reasoning"\s*:\s*"([^"]*)"', cleaned)

            if action_m:
                data["action"] = action_m.group(1)
            if dir_m:
                data["direction"] = dir_m.group(1)
            if conf_m:
                data["confidence"] = float(conf_m.group(1))
            if reason_m:
                data["reasoning"] = reason_m.group(1)

            if not data:
                return {
                    "action": "attack",
                    "direction": "left",
                    "combined_label": "attack_left",
                    "confidence": 0.0,
                    "reasoning": f"No JSON found: {text[:200]}",
                    "parse_error": True,
                }

        action = data.get("action", "attack").lower().strip()
        direction = data.get("direction", "left").lower().strip()
        confidence = float(data.get("confidence", 0.5))
        reasoning = data.get("reasoning", "")

        # Validate
        if action not in VALID_ACTIONS:
            action = "attack"
            confidence = 0.0
        if direction not in VALID_DIRECTIONS:
            direction = "left"
            confidence = 0.0

        combined = f"{action}_{direction}"

        return {
            "action": action,
            "direction": direction,
            "combined_label": combined,
            "confidence": round(confidence, 3),
            "reasoning": reasoning,
        }

    def estimate_cost(self, clip_count: int = 1011):
        """Estimate cost and time for labeling."""
        # Gemini 2.5 Flash pricing (as of 2025):
        # Input: $0.15/M tokens, Output: $0.60/M tokens (< 200K context)
        # Video: ~260 tokens/second of video, 4-6 sec clips ~ 1040-1560 tokens/clip
        avg_input_tokens = 1300 + 200  # video + prompt
        avg_output_tokens = 100  # JSON response

        total_input = clip_count * avg_input_tokens
        total_output = clip_count * avg_output_tokens

        cost_input = (total_input / 1_000_000) * 0.15
        cost_output = (total_output / 1_000_000) * 0.60
        total_cost = cost_input + cost_output

        time_minutes = (clip_count * self.delay) / 60

        print(f"\n=== Cost Estimate for {clip_count} clips ===")
        print(f"Input tokens:  ~{total_input:,} ({cost_input:.3f} USD)")
        print(f"Output tokens: ~{total_output:,} ({cost_output:.3f} USD)")
        print(f"Total cost:    ~${total_cost:.2f} USD")
        print(f"RPM limit:     {self.rpm_limit}")
        print(f"Delay/clip:    {self.delay:.1f}s")
        print(f"Est. time:     {time_minutes:.0f} min ({time_minutes/60:.1f} hr)")
        print(f"Already done:  {len(self.results)}")
        remaining = clip_count - len(self.results)
        if remaining > 0:
            remaining_min = (remaining * self.delay) / 60
            print(f"Remaining:     {remaining} clips ({remaining_min:.0f} min)")
        print()

    def run(
        self,
        clips_dir: Path,
        limit: Optional[int] = None,
    ):
        """
        Process all clips in directory. Supports resume.

        Args:
            clips_dir: Directory containing .mp4 clips
            limit: Max clips to process (for testing)
        """
        # Find all clips
        clip_files = sorted(clips_dir.glob("*.mp4"))
        if not clip_files:
            print(f"No .mp4 files found in {clips_dir}")
            return

        total = len(clip_files)
        if limit:
            clip_files = clip_files[:limit]

        # Filter already processed
        remaining = [
            c for c in clip_files if c.name not in self.results
        ]

        print(f"Total clips: {total}")
        print(f"Already processed: {len(self.results)}")
        print(f"To process: {len(remaining)}")
        if limit:
            print(f"Limit: {limit}")
        print()

        errors = 0
        for i, clip_path in enumerate(remaining):
            filename = clip_path.name
            progress = f"[{i+1}/{len(remaining)}]"

            try:
                result = self.classify_clip(clip_path)
                self.results[filename] = result

                conf_str = f"{result['confidence']:.0%}"
                label = result["combined_label"]
                print(f"{progress} {filename}: {label} ({conf_str}) - {result['reasoning'][:60]}")

                # Save periodically
                if (i + 1) % 10 == 0:
                    self._save_results()
                    print(f"  -> Saved {len(self.results)} results")

            except Exception as e:
                errors += 1
                print(f"{progress} ERROR {filename}: {e}")
                self.results[filename] = {
                    "action": "attack",
                    "direction": "left",
                    "combined_label": "attack_left",
                    "confidence": 0.0,
                    "reasoning": f"Error: {str(e)[:200]}",
                    "error": True,
                }

            # Rate limiting
            if i < len(remaining) - 1:
                time.sleep(self.delay)

        # Final save
        self._save_results()
        print(f"\nDone! {len(self.results)} total results saved to {self.results_path}")
        if errors:
            print(f"Errors: {errors}")

        self._print_distribution()

    def _print_distribution(self):
        """Print label distribution summary."""
        from collections import Counter
        dist = Counter(r["combined_label"] for r in self.results.values())
        print("\n=== Label Distribution ===")
        for label, count in sorted(dist.items(), key=lambda x: -x[1]):
            pct = count / len(self.results) * 100
            print(f"  {label:25s}: {count:4d} ({pct:.1f}%)")

        # Confidence stats
        confs = [r["confidence"] for r in self.results.values()]
        if confs:
            avg_conf = sum(confs) / len(confs)
            low_conf = sum(1 for c in confs if c < 0.5)
            print(f"\nAvg confidence: {avg_conf:.2f}")
            print(f"Low confidence (<0.5): {low_conf} ({low_conf/len(confs)*100:.1f}%)")

        # Error count
        errors = sum(1 for r in self.results.values() if r.get("error") or r.get("parse_error"))
        if errors:
            print(f"Errors/parse failures: {errors}")


def main():
    parser = argparse.ArgumentParser(description="Gemini Vision fencing clip labeler")
    parser.add_argument(
        "--clips-dir",
        type=Path,
        default=Path("data/clips"),
        help="Directory containing .mp4 clips (default: data/clips)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/labeled/gemini_results.json"),
        help="Output JSON path",
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Gemini model name",
    )
    parser.add_argument(
        "--rpm",
        type=int,
        default=15,
        help="Requests per minute limit (free=15, paid=1000)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: process only 3 clips",
    )
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="Print cost/time estimate only",
    )

    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: Set GEMINI_API_KEY environment variable")
        print("  Get a key at: https://aistudio.google.com/apikey")
        sys.exit(1)

    labeler = GeminiLabeler(
        api_key=api_key,
        model_name=args.model,
        rpm_limit=args.rpm,
        results_path=args.output,
    )

    if args.estimate:
        clip_count = len(list(args.clips_dir.glob("*.mp4"))) if args.clips_dir.exists() else 1011
        labeler.estimate_cost(clip_count)
        return

    limit = 3 if args.test else None
    labeler.run(clips_dir=args.clips_dir, limit=limit)


if __name__ == "__main__":
    main()
