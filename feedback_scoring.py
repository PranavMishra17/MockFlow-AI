"""
feedback_scoring — pure, deterministic feedback helpers.

The moat principle (docs/EPIC_wingD_feedback_moat.md): countable metrics are
computed in code and *injected* into / *override* the LLM, never invented by it.
This module owns:
  - research-based delivery bands (filler rate, words-per-minute),
  - the deterministic override that replaces any LLM-guessed filler count,
  - the speech summary text fed into the scoring prompt.

All functions are pure (no I/O, no mutation of inputs).

Research anchors (§1.5):
  - filler rate: <=5/min fine, ~12/min measurably hurts (Laske et al. 2024);
    coach toward a low *nonzero* rate, never zero.
  - speech rate: ~130-160 wpm ideal for dense content; flag sustained >190
    (Griffiths 1990; advisory, non-native-listener caveat).
"""

from typing import Any, Dict


def filler_band(per_min: float) -> str:
    """Bucket a filler-per-minute rate. <=5 good, <12 moderate, >=12 high."""
    if per_min <= 5.0:
        return "good"
    if per_min < 12.0:
        return "moderate"
    return "high"


def wpm_band(wpm: float) -> str:
    """Bucket a words-per-minute rate (advisory). Ideal 130-160, flag >190."""
    if wpm <= 0:
        return "unknown"
    if wpm < 110:
        return "slow"
    if wpm <= 160:
        return "ideal"
    if wpm <= 190:
        return "brisk"
    return "fast"


def delivery_metrics(speech: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the deterministic delivery block from speech_analytics output.

    Returns wpm + band and filler-per-minute + band, plus the human-readable
    target ranges so the UI can show "you: X / target: Y".
    """
    filler_total = float(speech.get("filler_total", 0) or 0)
    duration_s = float(speech.get("total_speaking_duration_seconds", 0) or 0)
    wpm = round(float(speech.get("avg_words_per_minute", 0) or 0), 1)

    filler_per_min = round(filler_total / (duration_s / 60.0), 1) if duration_s > 0 else 0.0

    return {
        "wpm": wpm,
        "wpm_band": wpm_band(wpm),
        "wpm_target": "130-160",
        "filler_total": int(filler_total),
        "filler_per_min": filler_per_min,
        "filler_band": filler_band(filler_per_min),
        "filler_target": "<=5/min",
        "word_count": int(speech.get("word_count", 0) or 0),
    }


def build_speech_summary(speech: Dict[str, Any]) -> str:
    """
    The measured-delivery block injected into the scoring prompt so the model
    references real numbers and never estimates them.
    """
    if not speech:
        return ("No speech analytics available for this transcript. Do not estimate "
                "filler counts or pace; omit numeric delivery claims.")
    d = delivery_metrics(speech)
    return (
        "MEASURED DELIVERY (computed deterministically from the transcript — "
        "use these exact numbers; do NOT estimate or invent them):\n"
        f"- Filler words (total): {d['filler_total']} "
        f"(~{d['filler_per_min']}/min; target <=5/min)\n"
        f"- Speaking pace: {d['wpm']} words/min (ideal 130-160)\n"
        f"- Words spoken: {d['word_count']}"
    )
