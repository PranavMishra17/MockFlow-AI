"""
calibration — measure how well the evaluator agrees with a human gold set.

The moat doc (§1.4.7) is explicit: a feedback product that leans on scores
publicly must first show its judge agrees with humans (Cohen's kappa, target
~75-90%). This module is the lightweight harness for that:

  - cohens_kappa(): pure, WEIGHTED Cohen's kappa over ordinal bands. Bands are
    ordinal (poor < borderline < solid < outstanding), so an off-by-one
    disagreement must count less than off-by-three — plain kappa over-penalises
    and understates real agreement.
  - run_calibration(): runs a (injected) scorer over a gold set, aligns
    per-signal bands by name, and reports kappa + exact-agreement +
    recommendation accuracy. The scorer is injected so the pure logic is unit
    tested offline; the LIVE run (real gpt-4o calls) is the manual __main__ path.

Until the measured kappa lands in the target band we do NOT surface a
"calibrated" claim to users (the product copy stays "today's-practice read").

Run the real thing manually:  python calibration.py [path/to/gold_set.json]
"""

import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from evaluator import BANDS


def cohens_kappa(
    pairs: List[Tuple[str, str]],
    categories: List[str],
    weights: str = "linear",
) -> Optional[float]:
    """
    Weighted Cohen's kappa over (rater_a, rater_b) ordinal-category pairs.
    `weights`: "linear" (default) or "quadratic". Returns None if no usable
    pairs, 1.0 if there is no possible disagreement (degenerate single class).
    """
    idx = {c: i for i, c in enumerate(categories)}
    pairs = [(a, b) for a, b in pairs if a in idx and b in idx]
    n = len(pairs)
    if n == 0:
        return None
    k = len(categories)

    observed = [[0] * k for _ in range(k)]
    for a, b in pairs:
        observed[idx[a]][idx[b]] += 1
    rows = [sum(observed[i]) for i in range(k)]
    cols = [sum(observed[i][j] for i in range(k)) for j in range(k)]

    def w(i: int, j: int) -> float:
        if k == 1:
            return 0.0
        if weights == "quadratic":
            return ((i - j) / (k - 1)) ** 2
        return abs(i - j) / (k - 1)

    do = sum(observed[i][j] * w(i, j) for i in range(k) for j in range(k)) / n
    de = sum((rows[i] * cols[j] / n) * w(i, j) for i in range(k) for j in range(k)) / n
    if de == 0:
        return 1.0  # no expected disagreement (all one category) -> perfect by convention
    return 1.0 - do / de


def collect_band_pairs(gold_item: Dict[str, Any], verdict: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Align the gold per-signal bands with the model's, by signal name."""
    model_by_name = {s.get("name"): s.get("band") for s in (verdict.get("signals") or [])}
    pairs = []
    for sig in gold_item.get("signals", []):
        gold_band = sig.get("band")
        model_band = model_by_name.get(sig.get("name"))
        if gold_band in BANDS and model_band in BANDS:
            pairs.append((gold_band, model_band))
    return pairs


def run_calibration(
    gold_set: List[Dict[str, Any]],
    score_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
    weights: str = "linear",
) -> Dict[str, Any]:
    """
    Score each gold item with `score_fn` (item -> finalized verdict) and report
    agreement. Pure given a pure score_fn — the live model call is injected.
    """
    all_pairs: List[Tuple[str, str]] = []
    reco_hits = reco_total = 0
    rows = []
    for item in gold_set:
        verdict = score_fn(item) or {}
        pairs = collect_band_pairs(item, verdict)
        all_pairs.extend(pairs)
        exp_reco = item.get("expected_recommendation")
        got_reco = (verdict.get("overall") or {}).get("recommendation")
        if exp_reco:
            reco_total += 1
            if exp_reco == got_reco:
                reco_hits += 1
        rows.append({"id": item.get("id"), "pairs": pairs, "expected_reco": exp_reco, "got_reco": got_reco})

    exact = (sum(1 for a, b in all_pairs if a == b) / len(all_pairs)) if all_pairs else None
    return {
        "n_items": len(gold_set),
        "n_band_pairs": len(all_pairs),
        "kappa": cohens_kappa(all_pairs, BANDS, weights),
        "weights": weights,
        "exact_band_agreement": exact,
        "recommendation_accuracy": (reco_hits / reco_total) if reco_total else None,
        "rows": rows,
    }


def _live_score_fn(item: Dict[str, Any]) -> Dict[str, Any]:
    """Real evaluator path: rubric -> messages -> gpt-4o -> finalize. Manual run only."""
    from openai import OpenAI

    from evaluator import (
        build_evaluator_messages, build_rubric, finalize_verdict, pick_evaluator_model,
    )

    rubric = build_rubric(item["track"], item["role"], item["seniority"], item.get("archetype", "big_tech"))
    messages = build_evaluator_messages(
        rubric, item.get("candidate_profile", ""), item.get("job_summary", ""),
        item.get("transcript", ""), item.get("speech_summary", ""),
    )
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.chat.completions.create(
        model=pick_evaluator_model(), messages=messages,
        temperature=0, response_format={"type": "json_object"}, max_tokens=2200,
    )
    raw = json.loads(resp.choices[0].message.content)
    return finalize_verdict(raw, {}, weights=rubric.get("weighting"))


def _print_report(report: Dict[str, Any]) -> None:
    k = report["kappa"]
    print("=" * 56)
    print("MockFlow evaluator calibration")
    print(f"  items                : {report['n_items']}")
    print(f"  signal band pairs    : {report['n_band_pairs']}")
    print(f"  weighted kappa ({report['weights']}) : {k:.3f}" if k is not None else "  weighted kappa       : n/a")
    ex = report["exact_band_agreement"]
    print(f"  exact band agreement : {ex:.1%}" if ex is not None else "  exact band agreement : n/a")
    ra = report["recommendation_accuracy"]
    print(f"  recommendation match : {ra:.1%}" if ra is not None else "  recommendation match : n/a")
    if k is not None:
        verdict = "OK — within target" if 0.75 <= k <= 0.90 else ("above target (re-check items)" if k > 0.90 else "BELOW target — do not surface scores publicly yet")
        print(f"  -> {verdict}  (target 0.75–0.90)")
    print("=" * 56)


if __name__ == "__main__":  # pragma: no cover - manual, makes live model calls
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "gold_set.json")
    with open(path, "r", encoding="utf-8") as fh:
        gold = json.load(fh)
    _print_report(run_calibration(gold, _live_score_fn))
