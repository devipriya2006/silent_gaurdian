"""
Unified scoring module.

Every detection mode (video, audio, image) converts its own internal
signal into a single 0-100 "risk/confidence indicator" and classifies
it with this one function, so the terminology and thresholds are
identical everywhere in the app.

Important framing (do not change without also updating the UI copy):
this score is a MODEL CONFIDENCE / RISK INDICATOR ONLY. It must never
be presented as proof that violence, abuse, or a crime occurred. All
HIGH/CRITICAL results route to human review rather than any automated
action.
"""

DISCLAIMER = (
    "This score reflects observable indicators picked up by an automated "
    "model. It is not proof that violence, abuse, or harassment occurred, "
    "and every flagged result is intended for human review, not as a "
    "final determination."
)

IMAGE_DISCLAIMER = (
    "A single still image is often ambiguous — the same pose or moment "
    "can look very different with context. This score cannot prove that "
    "violence occurred and should be treated as a prompt for human review."
)

AUDIO_DISCLAIMER = (
    "Loud, sudden, or high-pitched sound (shouting, alarms, excitement) "
    "does not by itself mean violence occurred. This score reflects "
    "acoustic intensity patterns only and is intended for human review."
)

_LEVELS = (
    (0, 30, "LOW", "Low observable indicators of potential violence or distress."),
    (30, 50, "MODERATE", "Some suspicious or potentially aggressive indicators are present."),
    (50, 75, "HIGH", "Strong observable indicators of potential physical aggression or distress."),
    (75, 101, "CRITICAL", "Very strong indicators. Marked for urgent human review."),
)


def classify(score_0_100):
    """
    Takes a 0-100 score and returns a dict with the clamped score,
    classification level, and a human-readable meaning string.
    """
    score = max(0.0, min(100.0, float(score_0_100)))
    for lo, hi, level, meaning in _LEVELS:
        if lo <= score < hi:
            return {"score": round(score, 1), "level": level, "meaning": meaning}
    # score == 100 falls through the last range's exclusive upper bound
    return {"score": round(score, 1), "level": "CRITICAL", "meaning": _LEVELS[-1][3]}


def is_reportable(level):
    """HIGH and CRITICAL are saved as incidents; LOW/MODERATE are not."""
    return level in ("HIGH", "CRITICAL")


def is_critical(level):
    return level == "CRITICAL"


def alert_tier(level):
    """
    Maps a classification level to the alert behavior required by spec:
      LOW      -> no alert
      MODERATE -> in-app warning only
      HIGH     -> strong in-app warning + saved for review (no external alert)
      CRITICAL -> prominent emergency alert + external notification (email/webhook)
    """
    return {
        "LOW": "none",
        "MODERATE": "warning",
        "HIGH": "strong_warning",
        "CRITICAL": "emergency",
    }.get(level, "none")
