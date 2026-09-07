"""
Single-image potential-aggression indicator analysis.

Honesty note (read before changing thresholds): a single still image
carries far weaker evidence than a video clip or audio recording — there
is no motion or temporal pattern to analyze, only static visual texture.
This module intentionally caps its own output well below 100 and leans
conservative, because overclaiming on a single frame is easy to get
wrong and easy to weaponize. Treat this mode as the weakest signal of
the three, and lean on video/audio analysis where they're available.

What it measures:
  - edge density        : proportion of strong edges (Canny) — scenes
                            with tangled/overlapping subjects (a struggle,
                            a crowd) tend to have denser, messier edges
                            than a calm posed photo
  - local contrast        : global intensity variation — chaotic or
                            harshly lit scenes score higher than flat,
                            evenly-lit ones
  - texture complexity    : Laplacian variance — a coarse measure of
                            fine detail/sharp variation across the image

None of these detect violence directly (there is no reliable way to do
that from texture statistics alone); they are a weak proxy for visual
"chaos", included as a baseline the way the video/audio modules use
their own transparent heuristics. Swapping in a trained image
classifier (e.g. fine-tuned on a pose/action dataset) is the natural
upgrade path — see README "Future Scope".
"""

import cv2
import numpy as np

MAX_SCORE_CAP = 62.0  # deliberately conservative ceiling for a single frame


def analyze_image_bgr(image_bgr):
    if image_bgr is None:
        raise ValueError("Could not decode image")

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    edges = cv2.Canny(gray, 100, 200)
    edge_density = float(np.mean(edges > 0))

    contrast = float(np.std(gray)) / 255.0

    laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    texture_complexity = min(laplacian_var / 1500.0, 1.0)

    raw = 0.5 * min(edge_density * 4, 1.0) + 0.3 * min(contrast * 2, 1.0) + 0.2 * texture_complexity
    raw = max(0.0, min(1.0, raw))

    score = round(raw * MAX_SCORE_CAP, 1)

    return {
        "score": score,
        "stats": {
            "edge_density": round(edge_density, 3),
            "contrast": round(contrast, 3),
            "texture_complexity": round(texture_complexity, 3),
        },
    }
