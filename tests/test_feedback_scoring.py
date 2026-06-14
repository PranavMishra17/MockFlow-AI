"""
Tests for feedback_scoring — the pure, deterministic layer that grounds the
LLM's feedback in real speech analytics (no hallucinated counts) and applies
research-based delivery bands.

Research anchors (see docs/EPIC_wingD_feedback_moat.md §1.5):
  - filler rate: <=5/min is fine, ~12/min measurably hurts (Laske et al. 2024)
  - speech rate: ~130-160 wpm ideal for dense content, flag sustained >190 (Griffiths 1990)
"""

from feedback_scoring import (
    build_speech_summary,
    delivery_metrics,
    filler_band,
    wpm_band,
)


# ---- delivery bands ----

def test_filler_band_low_rate_is_good():
    assert filler_band(0.0) == "good"
    assert filler_band(5.0) == "good"

def test_filler_band_moderate_rate():
    assert filler_band(8.0) == "moderate"

def test_filler_band_high_rate_flags():
    assert filler_band(12.0) == "high"
    assert filler_band(20.0) == "high"

def test_wpm_band_ideal_range():
    assert wpm_band(140.0) == "ideal"
    assert wpm_band(130.0) == "ideal"
    assert wpm_band(160.0) == "ideal"

def test_wpm_band_too_fast_flags():
    assert wpm_band(200.0) == "fast"

def test_wpm_band_slow():
    assert wpm_band(90.0) == "slow"

def test_wpm_band_unknown_when_zero():
    assert wpm_band(0.0) == "unknown"


# ---- delivery_metrics: computes filler-per-minute from deterministic data ----

def test_delivery_metrics_computes_filler_per_minute():
    speech = {
        "filler_total": 10,
        "avg_words_per_minute": 150.0,
        "total_speaking_duration_seconds": 120.0,  # 2 minutes -> 5 fillers/min
        "word_count": 300,
    }
    d = delivery_metrics(speech)
    assert d["filler_per_min"] == 5.0
    assert d["filler_band"] == "good"
    assert d["wpm"] == 150.0
    assert d["wpm_band"] == "ideal"

def test_delivery_metrics_handles_empty_speech():
    d = delivery_metrics({})
    assert d["filler_per_min"] == 0.0
    assert d["wpm"] == 0.0
    assert d["wpm_band"] == "unknown"

def test_delivery_metrics_zero_duration_no_crash():
    d = delivery_metrics({"filler_total": 3, "total_speaking_duration_seconds": 0})
    assert d["filler_per_min"] == 0.0  # avoid divide-by-zero


# ---- richer personality metrics surfaced for the dashboard (Wing D C2) ----

def test_delivery_metrics_surfaces_top_crutch_word():
    speech = {"filler_breakdown": {"like": 3, "um": 5, "so": 1}}
    d = delivery_metrics(speech)
    assert d["top_crutch_word"] == {"word": "um", "count": 5}
    assert d["filler_breakdown"] == {"like": 3, "um": 5, "so": 1}

def test_delivery_metrics_surfaces_sentences_talk_ratio_monologue():
    speech = {"sentence_count": 42, "talk_ratio": 0.61, "longest_monologue_s": 33.4}
    d = delivery_metrics(speech)
    assert d["sentence_count"] == 42
    assert d["talk_ratio"] == 0.61
    assert d["longest_monologue_s"] == 33.4

def test_delivery_metrics_empty_has_safe_personality_defaults():
    d = delivery_metrics({})
    assert d["top_crutch_word"] is None
    assert d["sentence_count"] == 0
    assert d["talk_ratio"] == 0.0
    assert d["longest_monologue_s"] == 0.0
    assert d["filler_breakdown"] == {}


# ---- build_speech_summary: the text injected into the LLM prompt ----

def test_speech_summary_includes_real_numbers():
    s = build_speech_summary({"filler_total": 8, "avg_words_per_minute": 175.0,
                              "total_speaking_duration_seconds": 90.0, "word_count": 260})
    assert "8" in s          # filler total
    assert "175" in s        # wpm
    # it should tell the model these are measured, not to be estimated
    assert "measured" in s.lower() or "do not" in s.lower()

def test_speech_summary_empty_is_safe():
    s = build_speech_summary({})
    assert isinstance(s, str) and len(s) > 0
