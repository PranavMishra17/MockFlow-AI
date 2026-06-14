"""
Tests for calibration — the weighted Cohen's kappa math and the harness wiring.
The kappa math is asserted on known fixtures; the harness is driven with a mock
scorer so CI stays offline (no real model calls). The live gpt-4o run is the
manual `python calibration.py` path.
"""

import json
from pathlib import Path

from calibration import cohens_kappa, collect_band_pairs, run_calibration
from evaluator import BANDS


# ---- weighted Cohen's kappa ----

def test_kappa_perfect_agreement_is_one():
    pairs = [("poor", "poor"), ("solid", "solid"), ("outstanding", "outstanding")]
    assert cohens_kappa(pairs, BANDS) == 1.0

def test_kappa_perfect_anti_agreement_is_negative_one():
    # raters disagree in equal-and-opposite directions with balanced marginals
    # => maximal disagreement, worse than chance => kappa = -1.0
    pairs = [("poor", "borderline"), ("borderline", "poor")]
    assert abs(cohens_kappa(pairs, BANDS) - (-1.0)) < 1e-9

def test_kappa_none_when_no_pairs():
    assert cohens_kappa([], BANDS) is None

def test_kappa_weighted_rewards_near_misses():
    # one off-by-one error vs one off-by-three error: linear-weighted kappa for
    # the near miss must be higher (less penalised) than for the far miss.
    near = [("solid", "solid"), ("solid", "borderline"), ("poor", "poor")]
    far = [("solid", "solid"), ("outstanding", "poor"), ("poor", "poor")]
    assert cohens_kappa(near, BANDS) > cohens_kappa(far, BANDS)

def test_kappa_ignores_non_band_values():
    pairs = [("solid", "solid"), ("cannot_determine", "solid"), ("solid", "x")]
    # only the first pair is scorable -> degenerate single class -> 1.0
    assert cohens_kappa(pairs, BANDS) == 1.0


# ---- pairing + harness ----

def test_collect_band_pairs_aligns_by_signal_name():
    item = {"signals": [{"name": "Ownership", "band": "solid"}, {"name": "Coding", "band": "poor"}]}
    verdict = {"signals": [{"name": "Ownership", "band": "solid"}, {"name": "Coding", "band": "borderline"}]}
    pairs = collect_band_pairs(item, verdict)
    assert ("solid", "solid") in pairs
    assert ("poor", "borderline") in pairs

def test_run_calibration_with_mock_scorer():
    gold = [
        {"id": "g1", "signals": [{"name": "Ownership", "band": "solid"}], "expected_recommendation": "lean_hire"},
        {"id": "g2", "signals": [{"name": "Coding", "band": "outstanding"}], "expected_recommendation": "hire"},
    ]

    def score_fn(item):  # a perfect judge
        return {"signals": item["signals"],
                "overall": {"recommendation": item["expected_recommendation"]}}

    out = run_calibration(gold, score_fn)
    assert out["n_items"] == 2
    assert out["n_band_pairs"] == 2
    assert out["kappa"] == 1.0
    assert out["exact_band_agreement"] == 1.0
    assert out["recommendation_accuracy"] == 1.0

def test_run_calibration_counts_disagreement():
    gold = [{"id": "g1", "signals": [{"name": "Ownership", "band": "solid"}], "expected_recommendation": "hire"}]

    def score_fn(item):  # disagrees on band and recommendation
        return {"signals": [{"name": "Ownership", "band": "poor"}], "overall": {"recommendation": "no_hire"}}

    out = run_calibration(gold, score_fn)
    assert out["exact_band_agreement"] == 0.0
    assert out["recommendation_accuracy"] == 0.0


# ---- the shipped seed gold set is well-formed ----

def test_gold_set_is_valid():
    path = Path(__file__).resolve().parents[1] / "gold_set.json"
    gold = json.loads(path.read_text(encoding="utf-8"))
    assert len(gold) >= 5
    for item in gold:
        assert item.get("track") and item.get("role") and item.get("seniority")
        assert item.get("transcript")
        assert item.get("signals")
        for sig in item["signals"]:
            assert sig["band"] in BANDS
            assert sig.get("name")
