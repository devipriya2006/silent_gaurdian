"""
Motion-based violence detection engine.

This module is the "AI core" of Silent Guardian. It is intentionally
built as a transparent, dependency-light pipeline (OpenCV + NumPy only)
so the project runs anywhere, including free-tier cloud deployments,
without needing a GPU or a bundled multi-hundred-MB model file.

Pipeline
--------
1. MotionFeatureExtractor: computes dense optical flow (Farneback)
   between consecutive frames and reduces it to a handful of
   interpretable statistics:
     - motion_energy        : average motion magnitude across the frame
     - motion_std           : spread of motion magnitude (how uneven it is)
     - high_motion_ratio     : fraction of pixels moving much faster than average
     - direction_entropy      : how chaotic/multi-directional the motion is
                                 (a shove/struggle moves limbs in many
                                 directions at once; walking does not)

2. ViolenceScorer: keeps an adaptive rolling baseline of "normal" motion
   for the current scene and scores each frame by how far it deviates
   from that baseline, then smooths the score over a short sliding
   window to avoid single-frame false triggers (e.g. someone briefly
   waving).

Swapping in a trained deep model
---------------------------------
For a stronger classifier (recommended future work / extension),
implement a class with the same `.extract()` / `.update()` interface
that wraps a trained 3D-CNN or ST-GCN (e.g. trained on the RWF-2000 or
Hockey Fight datasets) and swap it into app.py. Because app.py only
depends on this interface (not on optical flow specifically), the rest
of the system — alerts, storage, dashboard — needs no changes.
"""

from collections import deque

import cv2
import numpy as np


class MotionFeatureExtractor:
    """Extracts interpretable motion statistics between consecutive frames."""

    def __init__(self, resize_width=320):
        self.resize_width = resize_width
        self.prev_gray = None

    def _prep(self, frame):
        h, w = frame.shape[:2]
        scale = self.resize_width / float(w)
        resized = cv2.resize(frame, (self.resize_width, max(1, int(h * scale))))
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        return gray

    def extract(self, frame):
        """Returns a dict of motion features, or None for the first frame
        (optical flow needs a previous frame to compare against)."""
        gray = self._prep(frame)

        if self.prev_gray is None:
            self.prev_gray = gray
            return None

        flow = cv2.calcOpticalFlowFarneback(
            self.prev_gray, gray, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )
        self.prev_gray = gray

        mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1])

        motion_energy = float(np.mean(mag))
        motion_std = float(np.std(mag))
        high_motion_ratio = float(
            np.mean(mag > (motion_energy + 2 * motion_std + 1e-6))
        )

        # Directional entropy: how spread out (chaotic) the motion
        # directions are among the fastest-moving pixels.
        fast_mask = mag > motion_energy
        if np.any(fast_mask):
            angles = np.mod(ang[fast_mask].astype(np.float64), 2 * np.pi)
            bin_idx = np.clip((angles / (2 * np.pi) * 16).astype(int), 0, 15)
            hist = np.bincount(bin_idx, minlength=16)
            total = hist.sum()
            if total > 0:
                p = hist / total
                p = p[p > 0]
                direction_entropy = float(-np.sum(p * np.log2(p)))
            else:
                direction_entropy = 0.0
        else:
            direction_entropy = 0.0

        return {
            "motion_energy": motion_energy,
            "motion_std": motion_std,
            "high_motion_ratio": high_motion_ratio,
            "direction_entropy": direction_entropy,
        }


class ViolenceScorer:
    """
    Converts a stream of motion features into a smoothed violence
    probability score in [0, 1], adapting to each scene's normal
    activity level via a rolling baseline.
    """

    def __init__(self, window_size=20, baseline_size=150, threshold=0.55):
        self.window = deque(maxlen=window_size)
        self.baseline = deque(maxlen=baseline_size)
        self.threshold = threshold

    def update(self, features):
        if features is None:
            return 0.0 if not self.window else float(np.mean(self.window))

        self.baseline.append(features["motion_energy"])
        baseline_mean = float(np.mean(self.baseline)) if self.baseline else 0.0
        baseline_std = float(np.std(self.baseline)) if self.baseline else 1.0
        baseline_std = max(baseline_std, 1e-3)

        z = (features["motion_energy"] - baseline_mean) / baseline_std

        raw_score = (
            0.45 * _clip01(z / 4.0)
            + 0.25 * _clip01(features["high_motion_ratio"] * 5)
            + 0.20 * _clip01(features["direction_entropy"] / 4.0)
            + 0.10 * _clip01(features["motion_std"] / 5.0)
        )
        raw_score = float(np.clip(raw_score, 0, 1))

        self.window.append(raw_score)
        return float(np.mean(self.window))

    def is_violent(self, smoothed_score):
        return smoothed_score >= self.threshold


def _clip01(x):
    return max(0.0, min(1.0, x))
