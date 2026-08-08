"""
Action classification using VideoMAE for fencing technique recognition.

Classifies fencing actions from video clips using a sliding window
approach. Supports both pretrained Kinetics-400 and FACTS fine-tuned models.
"""

import numpy as np
from pathlib import Path
from typing import Optional, List

from analyzer.models import (
    FencingAction,
    ActionPrediction,
    ActionResult,
)
from analyzer.config import (
    ACTION_MODEL_NAME,
    ACTION_FINETUNED_PATH,
    ACTION_WINDOW_SIZE,
    ACTION_STRIDE,
    ACTION_CONFIDENCE_THRESHOLD,
    ACTION_LABEL_MAP,
    FACTS_TO_ACTION,
    DEVICE_PREFERENCE,
)


class ActionClassifier:
    """
    VideoMAE-based action classifier for fencing techniques.

    Uses lazy loading: model/processor loaded on first classify call.
    When ACTION_FINETUNED_PATH is set, loads the FACTS fine-tuned model
    instead of the pretrained Kinetics-400 model.
    """

    def __init__(
        self,
        model_name: str = ACTION_MODEL_NAME,
        finetuned_path: Optional[Path] = ACTION_FINETUNED_PATH,
        window_size: int = ACTION_WINDOW_SIZE,
        stride: int = ACTION_STRIDE,
        device: Optional[str] = None,
    ):
        self.model_name = model_name
        self.finetuned_path = Path(finetuned_path) if finetuned_path else None
        self.window_size = window_size
        self.stride = stride
        self.device = device or self._resolve_device()
        self._model = None
        self._processor = None

    @staticmethod
    def _resolve_device() -> str:
        """Auto-select best available device: MPS > CUDA > CPU."""
        try:
            import torch
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    def _load_model(self):
        """Load VideoMAE model and processor on first use."""
        if self._model is not None:
            return

        import torch
        from transformers import VideoMAEForVideoClassification, VideoMAEImageProcessor

        if self.finetuned_path and self.finetuned_path.exists():
            self._model = VideoMAEForVideoClassification.from_pretrained(
                str(self.finetuned_path)
            )
            self._processor = VideoMAEImageProcessor.from_pretrained(
                str(self.finetuned_path)
            )
        else:
            self._model = VideoMAEForVideoClassification.from_pretrained(
                self.model_name
            )
            self._processor = VideoMAEImageProcessor.from_pretrained(
                self.model_name
            )

        self._model.to(self.device)
        self._model.eval()

    def _sample_frames(self, frames: List[np.ndarray]) -> List[np.ndarray]:
        """
        Sample or pad frames to match window_size.

        If len(frames) > window_size: uniformly sample.
        If len(frames) < window_size: repeat last frame to pad.
        If len(frames) == window_size: return as-is.
        """
        n = len(frames)
        if n == 0:
            return []

        if n == self.window_size:
            return list(frames)

        if n > self.window_size:
            indices = np.linspace(0, n - 1, self.window_size, dtype=int)
            return [frames[i] for i in indices]

        # Pad by repeating last frame
        padded = list(frames)
        while len(padded) < self.window_size:
            padded.append(frames[-1])
        return padded

    def classify_action(
        self,
        clip_frames: List[np.ndarray],
        start_frame: int = 0,
    ) -> ActionResult:
        """
        Classify fencing action from a clip of frames.

        Args:
            clip_frames: List of BGR frames.
            start_frame: Frame index of the first frame in the clip.

        Returns:
            ActionResult with overall classification.
        """
        self._load_model()
        import torch

        sampled = self._sample_frames(clip_frames)
        if not sampled:
            return ActionResult(
                start_frame=start_frame,
                end_frame=start_frame,
            )

        # Convert BGR to RGB (.copy() avoids negative stride issue with PyTorch)
        rgb_frames = [frame[:, :, ::-1].copy() for frame in sampled]

        inputs = self._processor(rgb_frames, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self._model(**inputs)
            logits = outputs.logits[0]
            probs = torch.softmax(logits, dim=-1)

        # Map to fencing actions (using label map for fine-tuned,
        # or top-1 from Kinetics-400 for pretrained)
        if self.finetuned_path and self.finetuned_path.exists():
            prediction = self._map_finetuned_prediction(probs)
        else:
            prediction = self._map_kinetics_prediction(probs)

        end_frame = start_frame + len(clip_frames) - 1
        return ActionResult(
            start_frame=start_frame,
            end_frame=end_frame,
            left_fencer=prediction,
        )

    def classify_sliding_window(
        self,
        frames: List[np.ndarray],
        start_frame: int = 0,
        fps: float = 30.0,
    ) -> List[ActionResult]:
        """
        Classify actions using a sliding window over frames.

        Args:
            frames: Full list of BGR frames.
            start_frame: Frame index of frames[0].
            fps: Video frame rate (unused, reserved for future).

        Returns:
            List of ActionResult, one per window position.
        """
        results = []
        n = len(frames)

        if n == 0:
            return results

        if n <= self.window_size:
            result = self.classify_action(frames, start_frame)
            results.append(result)
            return results

        for i in range(0, n - self.window_size + 1, self.stride):
            window = frames[i : i + self.window_size]
            result = self.classify_action(window, start_frame + i)
            results.append(result)

        return results

    def classify_per_fencer(
        self,
        clip_frames: List[np.ndarray],
        bboxes: List[List[float]],
        start_frame: int = 0,
        side: str = "left",
    ) -> Optional[ActionPrediction]:
        """
        Classify action for a single fencer by cropping to their bbox.

        Args:
            clip_frames: List of BGR frames.
            bboxes: Per-frame bounding boxes [x1, y1, x2, y2].
            start_frame: Frame index of clip_frames[0].
            side: "left" or "right" fencer.

        Returns:
            ActionPrediction for the specified fencer, or None.
        """
        if not clip_frames or not bboxes:
            return None

        cropped = []
        for frame, bbox in zip(clip_frames, bboxes):
            x1, y1, x2, y2 = [int(v) for v in bbox]
            h, w = frame.shape[:2]
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(w, x2)
            y2 = min(h, y2)
            if x2 <= x1 or y2 <= y1:
                cropped.append(frame)
            else:
                cropped.append(frame[y1:y2, x1:x2])

        result = self.classify_action(cropped, start_frame)

        # Return the left_fencer prediction (from classify_action)
        return result.left_fencer

    def _map_finetuned_prediction(self, probs) -> Optional[ActionPrediction]:
        """Map fine-tuned model output to FencingAction.

        FACTS model outputs 8 classes with direction encoding
        (e.g. "attack_left", "attack_right"). We strip the direction
        and store it in ActionPrediction.direction.
        """
        top_idx = probs.argmax().item()
        top_conf = probs[top_idx].item()

        if top_conf < ACTION_CONFIDENCE_THRESHOLD:
            return ActionPrediction(
                action=FencingAction.UNKNOWN,
                confidence=top_conf,
            )

        label_str = ACTION_LABEL_MAP.get(top_idx, "unknown")

        # FACTS direction-encoded labels → strip direction
        if label_str in FACTS_TO_ACTION:
            action_value, direction = FACTS_TO_ACTION[label_str]
            try:
                action = FencingAction(action_value)
            except ValueError:
                action = FencingAction.UNKNOWN
            return ActionPrediction(
                action=action,
                confidence=top_conf,
                direction=direction,
            )

        # Fallback for non-FACTS labels
        try:
            action = FencingAction(label_str)
        except ValueError:
            action = FencingAction.UNKNOWN

        return ActionPrediction(action=action, confidence=top_conf)

    def _map_kinetics_prediction(self, probs) -> Optional[ActionPrediction]:
        """
        Map Kinetics-400 pretrained output to closest fencing action.

        Since Kinetics-400 doesn't have fencing-specific labels,
        we map related labels (fencing_sport, sword_fighting, etc.)
        and return UNKNOWN for unrecognized actions.
        """
        top_idx = probs.argmax().item()
        top_conf = probs[top_idx].item()

        # Kinetics-400 label → fencing action approximation
        kinetics_to_fencing = {
            89: FencingAction.ATTACK,   # "fencing (sport)" in Kinetics-400
            367: FencingAction.ATTACK,  # "sword fighting"
        }

        action = kinetics_to_fencing.get(top_idx, FencingAction.UNKNOWN)

        return ActionPrediction(action=action, confidence=top_conf)
