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
    finalize_scores,
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


# ---- finalize_scores: the anti-hallucination override ----

def test_finalize_overrides_llm_filler_count_with_deterministic_value():
    llm_scores = {"overall_score": 3.5, "filler_word_count": 99, "competencies": []}
    speech = {"filler_total": 7, "avg_words_per_minute": 140.0,
              "total_speaking_duration_seconds": 60.0}
    out = finalize_scores(llm_scores, speech)
    # the model's invented 99 must be replaced by the real 7
    assert out["filler_word_count"] == 7

def test_finalize_attaches_delivery_block():
    out = finalize_scores({"overall_score": 3}, {"filler_total": 2,
                          "avg_words_per_minute": 145.0,
                          "total_speaking_duration_seconds": 60.0})
    assert "delivery" in out
    assert out["delivery"]["filler_band"] == "good"
    assert out["delivery"]["wpm_band"] == "ideal"

def test_finalize_preserves_other_scores():
    llm_scores = {"overall_score": 4.2, "summary_headline": "Strong",
                  "competencies": [{"name": "X", "score": 4}], "filler_word_count": 50}
    out = finalize_scores(llm_scores, {"filler_total": 1,
                          "avg_words_per_minute": 150.0,
                          "total_speaking_duration_seconds": 30.0})
    assert out["overall_score"] == 4.2
    assert out["summary_headline"] == "Strong"
    assert out["competencies"] == [{"name": "X", "score": 4}]

def test_finalize_does_not_mutate_input():
    llm_scores = {"filler_word_count": 99}
    finalize_scores(llm_scores, {"filler_total": 3})
    assert llm_scores["filler_word_count"] == 99  # original untouched


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
