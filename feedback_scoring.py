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


def filler_band_per_100w(per_100w: float) -> str:
    """Bucket a filler-per-100-words rate — the unit we can actually measure.

    Thresholds are the same research anchors as `filler_band`, converted at the
    130-160 wpm reference band's midpoint of ~150 wpm: 5/min -> 3.33/100 words,
    12/min -> 8.0/100 words. Because the old `filler_per_min` was in truth
    fillers-per-150-words, this conversion leaves every band assignment
    unchanged; only the label becomes truthful.
    """
    if per_100w <= (5.0 / 1.5):
        return "good"
    if per_100w < (12.0 / 1.5):
        return "moderate"
    return "high"


def wpm_band(wpm) -> str:
    """Bucket a words-per-minute rate (advisory). Ideal 130-160, flag >190.

    None means pace was never measured; that is reported as "unknown" rather
    than being bucketed as if it were a slow speaker.
    """
    if wpm is None or wpm <= 0:
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

    Every value here is measured or explicitly absent. `pace_available` is False
    unless the transcript carried real per-turn speaking durations; when it is
    False, wpm / filler_per_min / longest_monologue_s are None rather than 0,
    because a zero would be indistinguishable from a real measurement.

    Rows saved before this fix carry the old fabricated numbers and no
    `pace_available` key. They are treated as unmeasured — the fabricated pace is
    deliberately NOT resurfaced.
    """
    filler_total = float(speech.get("filler_total", 0) or 0)
    word_count = int(speech.get("word_count", 0) or 0)
    pace_available = bool(speech.get("pace_available", False))

    duration_s = speech.get("total_speaking_duration_seconds") if pace_available else None
    wpm = speech.get("avg_words_per_minute") if pace_available else None
    wpm = round(float(wpm), 1) if wpm is not None else None

    # Exact: fillers per 100 words. Falls back to recomputing from counts so an
    # older analytics dict still yields the honest rate.
    per_100w = speech.get("filler_per_100_words")
    if per_100w is None:
        per_100w = (100.0 * filler_total / word_count) if word_count else 0.0
    per_100w = round(float(per_100w), 2)

    # Only a real duration yields a real per-minute rate.
    filler_per_min = None
    if pace_available and duration_s:
        filler_per_min = round(filler_total / (float(duration_s) / 60.0), 1)

    breakdown = dict(speech.get("filler_breakdown") or {})
    top = max(breakdown.items(), key=lambda kv: kv[1]) if breakdown else None

    monologue = speech.get("longest_monologue_s") if pace_available else None

    return {
        "pace_available": pace_available,
        "wpm": wpm,
        "wpm_band": wpm_band(wpm),
        "wpm_target": "130-160",
        "filler_total": int(filler_total),
        "filler_per_100w": per_100w,
        "filler_per_min": filler_per_min,
        "filler_band": filler_band_per_100w(per_100w),
        "filler_target": "<=3.3/100 words",
        "word_count": word_count,
        "sentence_count": int(speech.get("sentence_count", 0) or 0),
        "filler_breakdown": breakdown,
        "top_crutch_word": {"word": top[0], "count": top[1]} if top else None,
        "talk_ratio": round(float(speech.get("talk_ratio", 0) or 0), 2),
        "longest_monologue_s": round(float(monologue), 1) if monologue is not None else None,
    }


def build_speech_summary(speech: Dict[str, Any]) -> str:
    """
    The measured-delivery block injected into the scoring prompt so the model
    references real numbers and never estimates them.

    Pace is stated only when it was actually measured. Previously this asserted a
    words-per-minute figure that was the constant 150 for every candidate, under
    a heading telling the model to treat it as exact.
    """
    if not speech:
        return ("No speech analytics available for this transcript. Do not estimate "
                "filler counts or pace; omit numeric delivery claims.")
    d = delivery_metrics(speech)
    lines = [
        "MEASURED DELIVERY (computed deterministically from the transcript — "
        "use these exact numbers; do NOT estimate or invent them):",
        f"- Filler words (total): {d['filler_total']} "
        f"(~{d['filler_per_100w']} per 100 words; target <={round(5.0 / 1.5, 1)})",
        f"- Words spoken: {d['word_count']}",
    ]
    if d["pace_available"] and d["wpm"] is not None:
        lines.append(f"- Speaking pace: {d['wpm']} words/min (ideal 130-160)")
    else:
        lines.append(
            "- Speaking pace: NOT MEASURED for this session. Say nothing about "
            "pace, speed, rushing or pausing, and do not infer them from length."
        )
    return "\n".join(lines)
