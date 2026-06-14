"""
Tests for evaluator — the reinvented hiring-lens verdict (docs/EPIC_wingD_feedback_moat.md).

The verdict is a FORMULA over evidence-cited per-signal bands, not an LLM gestalt:
  - each signal is judged into a 4-level band (poor/borderline/solid/outstanding),
  - a signal with no transcript evidence is downgraded to cannot_determine and
    excluded from the roll-up (we never score what we can't quote),
  - the overall 7-point recommendation + the scope/ownership level-read are
    computed deterministically from the per-signal bands.
"""

import pytest

from evaluator import (
    BANDS,
    RECOMMENDATIONS,
    band_score,
    build_rubric,
    finalize_verdict,
    gap_to_next,
    level_read,
    rollup_recommendation,
)


# ---- band -> score ----

def test_band_score_ordinal():
    assert band_score("poor") == 1
    assert band_score("borderline") == 2
    assert band_score("solid") == 3
    assert band_score("outstanding") == 4

def test_band_score_unknown_is_none():
    assert band_score("cannot_determine") is None
    assert band_score("") is None
    assert band_score(None) is None


# ---- roll-up: per-signal bands -> 7-point recommendation ----

def _sig(band, scope="new_grad", ev=("quote",)):
    return {"name": "X", "band": band, "scope_met": scope, "evidence": list(ev)}

def test_rollup_all_outstanding_is_strong_hire():
    sigs = [_sig("outstanding"), _sig("outstanding")]
    assert rollup_recommendation(sigs) == "strong_hire"

def test_rollup_all_poor_is_strong_no_hire():
    assert rollup_recommendation([_sig("poor"), _sig("poor")]) == "strong_no_hire"

def test_rollup_all_solid_is_lean_hire():
    # avg band 3.0 -> index round((3-1)/3*6)=4 -> lean_hire
    assert rollup_recommendation([_sig("solid"), _sig("solid"), _sig("solid")]) == "lean_hire"

def test_rollup_all_borderline_is_lean_no_hire():
    assert rollup_recommendation([_sig("borderline"), _sig("borderline")]) == "lean_no_hire"

def test_rollup_midpoint_is_on_fence():
    # one borderline(2) + one solid(3) -> avg 2.5 -> index 3 -> on_fence
    assert rollup_recommendation([_sig("borderline"), _sig("solid")]) == "on_fence"

def test_rollup_excludes_cannot_determine():
    # the cannot_determine signal must not drag the average
    sigs = [_sig("outstanding"), _sig("outstanding"), _sig("cannot_determine")]
    assert rollup_recommendation(sigs) == "strong_hire"

def test_rollup_no_scorable_signals_defaults_on_fence():
    assert rollup_recommendation([_sig("cannot_determine")]) == "on_fence"

def test_rollup_respects_weights():
    # heavy weight on the strong signal pulls the recommendation up
    sigs = [
        {"name": "Problem-solving", "band": "outstanding", "scope_met": "mid", "evidence": ["q"]},
        {"name": "Communication", "band": "borderline", "scope_met": "new_grad", "evidence": ["q"]},
    ]
    weights = {"Problem-solving": 3.0, "Communication": 1.0}
    unweighted = rollup_recommendation(sigs)
    weighted = rollup_recommendation(sigs, weights)
    assert RECOMMENDATIONS.index(weighted) >= RECOMMENDATIONS.index(unweighted)


# ---- level read (scope/ownership axis, robust to one outlier) ----

def test_level_read_all_mid():
    sigs = [_sig("solid", "mid"), _sig("solid", "mid"), _sig("solid", "mid")]
    assert level_read(sigs) == "mid"

def test_level_read_median_down_levels():
    # strong on one, but scope mostly new_grad -> reads new_grad, not mid
    sigs = [_sig("solid", "mid"), _sig("solid", "new_grad"), _sig("solid", "new_grad")]
    assert level_read(sigs) == "new_grad"

def test_level_read_none_when_no_scope():
    assert level_read([{"name": "X", "band": "solid"}]) is None


# ---- rubric assembly: signals per track x role ----

def test_coding_rubric_has_core_signals():
    r = build_rubric("coding", "swe", "new_grad")
    names = [s["name"].lower() for s in r["signals"]]
    assert any("problem" in n for n in names)
    assert any("coding" in n for n in names)
    assert any("test" in n for n in names)

def test_behavioral_rubric_has_ownership():
    r = build_rubric("behavioral", "swe", "new_grad")
    names = [s["name"].lower() for s in r["signals"]]
    assert any("ownership" in n for n in names)

def test_technical_voice_pm_is_product_sense():
    r = build_rubric("technical_voice", "pm", "new_grad")
    names = [s["name"].lower() for s in r["signals"]]
    assert any("product" in n for n in names)

def test_technical_voice_ds_mle_has_stats():
    r = build_rubric("technical_voice", "ds_mle", "mid")
    names = [s["name"].lower() for s in r["signals"]]
    assert any("stat" in n or "experiment" in n for n in names)

def test_rubric_signals_carry_indicators():
    r = build_rubric("coding", "swe", "mid")
    for s in r["signals"]:
        assert s.get("positive") and s.get("negative")  # evidence-anchored

def test_rubric_includes_seniority_exemplar_and_scales():
    assert build_rubric("coding", "swe", "intern")["level_exemplar"] != \
           build_rubric("coding", "swe", "mid")["level_exemplar"]


# ---- gap to next band: the constructive "to raise this" ----

def test_gap_to_next_points_to_lowest_scorable_signal():
    sigs = [_sig("solid"), {"name": "Conflict", "band": "borderline", "scope_met": "new_grad", "evidence": ["q"]}]
    g = gap_to_next(sigs)
    assert g["signal"] == "Conflict"

def test_gap_to_next_handles_empty():
    assert gap_to_next([]) is None


# ---- finalize_verdict: the deterministic spine ----

def _raw_verdict():
    return {
        "overall": {"recommendation": "strong_hire", "confidence": "high",
                    "level_read": "mid", "headline": "Great"},  # LLM gestalt — will be recomputed
        "signals": [
            {"name": "Problem-solving", "band": "borderline", "scope_met": "new_grad",
             "evidence": ["I'd start by clarifying inputs"], "reasoning": "ok", "to_raise": "state complexity"},
            {"name": "Coding", "band": "borderline", "scope_met": "new_grad",
             "evidence": ["wrote a loop"], "reasoning": "ok", "to_raise": "cleaner"},
        ],
        "differentiators": ["a real point of view"],
    }

def test_finalize_recomputes_recommendation_from_bands_not_llm_gestalt():
    speech = {"filler_total": 3, "avg_words_per_minute": 150.0, "total_speaking_duration_seconds": 60.0}
    out = finalize_verdict(_raw_verdict(), speech)
    # LLM claimed strong_hire, but two borderline signals must roll up to lean_no_hire
    assert out["overall"]["recommendation"] == "lean_no_hire"

def test_finalize_drops_evidence_less_signals_to_cannot_determine():
    raw = _raw_verdict()
    raw["signals"].append({"name": "Testing", "band": "outstanding", "scope_met": "mid",
                           "evidence": [], "reasoning": "no quote"})
    out = finalize_verdict(raw, {})
    testing = [s for s in out["signals"] if s["name"] == "Testing"][0]
    assert testing["band"] == "cannot_determine"

def test_finalize_attaches_delivery_block():
    out = finalize_verdict(_raw_verdict(), {"filler_total": 2, "avg_words_per_minute": 145.0,
                                            "total_speaking_duration_seconds": 60.0})
    assert out["delivery"]["wpm_band"] == "ideal"

def test_finalize_attaches_gap_to_next():
    out = finalize_verdict(_raw_verdict(), {})
    assert "gap_to_next" in out and out["gap_to_next"] is not None

def test_finalize_sets_level_read_from_signals():
    out = finalize_verdict(_raw_verdict(), {})
    assert out["overall"]["level_read"] == "new_grad"  # both signals new_grad, not the LLM's "mid"

def test_finalize_does_not_mutate_input():
    raw = _raw_verdict()
    finalize_verdict(raw, {})
    assert raw["overall"]["recommendation"] == "strong_hire"  # original untouched


def test_finalize_counts_great_answers_post_downgrade():
    raw = _raw_verdict()
    # one genuine outstanding (has a quote) + one "outstanding" with no evidence
    # (gets downgraded to cannot_determine and must NOT count as a great answer).
    raw["signals"].append({"name": "Testing & verification", "band": "outstanding",
                           "scope_met": "mid", "evidence": ["I tested the edge cases first"], "reasoning": "ok"})
    raw["signals"].append({"name": "Communication & structure", "band": "outstanding",
                           "scope_met": "mid", "evidence": [], "reasoning": "no quote"})
    out = finalize_verdict(raw, {})
    assert out["great_answers"] == 1

def test_finalize_great_answers_zero_when_none_outstanding():
    out = finalize_verdict(_raw_verdict(), {})  # two borderline signals
    assert out["great_answers"] == 0

def test_recommendations_scale_is_seven_points_ordered():
    assert len(RECOMMENDATIONS) == 7
    assert RECOMMENDATIONS[0] == "strong_no_hire"
    assert RECOMMENDATIONS[-1] == "strong_hire"
    assert BANDS == ["poor", "borderline", "solid", "outstanding"]


# ---- role / seniority / archetype inference from interview metadata ----

from evaluator import (  # noqa: E402
    build_evaluator_messages,
    infer_archetype,
    infer_role,
    infer_seniority,
)

def test_infer_role_maps_keywords():
    assert infer_role("Senior Software Engineer") == "swe"
    assert infer_role("Product Manager") == "pm"
    assert infer_role("Data Scientist") == "ds_mle"
    assert infer_role("Machine Learning Engineer") == "ds_mle"

def test_infer_role_defaults_to_swe():
    assert infer_role("") == "swe"
    assert infer_role(None) == "swe"

def test_infer_seniority_maps_levels():
    assert infer_seniority("Intern") == "intern"
    assert infer_seniority("New Grad") == "new_grad"
    assert infer_seniority("entry-level") == "new_grad"
    assert infer_seniority("Mid-level") == "mid"
    assert infer_seniority("Senior") == "mid"  # clamp to our early-career ceiling

def test_infer_seniority_defaults_new_grad():
    assert infer_seniority("") == "new_grad"

def test_infer_archetype():
    assert infer_archetype("Stripe") == "high_bar_startup"
    assert infer_archetype("Google") == "big_tech"
    assert infer_archetype("") == "big_tech"


# ---- evaluator prompt assembly ----

def test_evaluator_messages_demand_evidence_and_json():
    rubric = build_rubric("coding", "swe", "new_grad")
    msgs = build_evaluator_messages(rubric, candidate_profile="P", job_summary="J",
                                    transcript="T", speech_summary="S")
    assert len(msgs) == 2 and msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
    blob = (msgs[0]["content"] + msgs[1]["content"]).lower()
    # the moat rules must be in the prompt
    assert "verbatim" in blob or "quote" in blob
    assert "cannot_determine" in blob
    assert "json" in blob
    # the actual signal names must appear so the model scores the right things
    assert "problem-solving" in blob

def test_evaluator_messages_include_transcript_and_delivery():
    rubric = build_rubric("behavioral", "swe", "mid")
    msgs = build_evaluator_messages(rubric, candidate_profile="CP", job_summary="JD",
                                    transcript="TRANSCRIPT_HERE", speech_summary="DELIVERY_HERE")
    user = msgs[1]["content"]
    assert "TRANSCRIPT_HERE" in user and "DELIVERY_HERE" in user
