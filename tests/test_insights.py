"""
Tests for insights — the longitudinal aggregation behind the rebuilt
"Interview Personality" (docs/EPIC_wingD_feedback_moat.md §4, Phase 3).

Maps each session's per-signal verdict bands onto a stable canonical-competency
taxonomy so sessions are comparable across tracks, then derives trends, the
strongest/weakest competency, and the recommendation trajectory.
"""

from insights import (
    CANONICAL_COMPETENCIES,
    _competency_bands,
    build_insights,
    signal_to_competency,
)


def _session(reco, level, signals, track="intro", date="2026-06-13T10:00:00",
             delivery=None, gap=None, great=None):
    """A row shaped like get_user_score_history() returns."""
    verdict = {
        "overall": {"recommendation": reco, "level_read": level, "headline": "h"},
        "signals": signals,
        "delivery": delivery or {},
    }
    if gap is not None:
        verdict["gap_to_next"] = gap
    if great is not None:
        verdict["great_answers"] = great
    return {
        "track": track,
        "created_at": date,
        "scores": {"verdict": verdict},
    }


def _sig(name, band):
    return {"name": name, "band": band, "evidence": ["q"]}


# ---- canonical mapping ----

def test_signal_maps_to_canonical_competency():
    assert signal_to_competency("Problem-solving") == "problem_solving"
    assert signal_to_competency("Communication & structure") == "communication"
    assert signal_to_competency("Ownership") == "ownership_impact"
    assert signal_to_competency("Coding") == "technical_depth"

def test_unknown_signal_maps_to_none():
    assert signal_to_competency("Totally Unknown Signal") is None

def test_canonical_list_is_stable():
    assert "communication" in CANONICAL_COMPETENCIES
    assert "problem_solving" in CANONICAL_COMPETENCIES


# ---- _competency_bands reducer (shared by build_insights, radar, compare) ----

def test_competency_bands_keeps_best_per_competency():
    # Problem-solving AND Trade-off reasoning both map to problem_solving;
    # the reducer keeps the strongest band for that competency.
    verdict = {"signals": [
        _sig("Problem-solving", "solid"),
        _sig("Trade-off reasoning", "outstanding"),
        _sig("Communication & structure", "borderline"),
    ]}
    bands = _competency_bands(verdict)
    assert bands["problem_solving"] == ("outstanding", 4)
    assert bands["communication"] == ("borderline", 2)

def test_competency_bands_skips_unscored_and_unknown():
    verdict = {"signals": [
        _sig("Totally Unknown Signal", "solid"),       # unknown -> no competency
        {"name": "Ownership", "band": "cannot_determine", "evidence": []},  # unscored
    ]}
    assert _competency_bands(verdict) == {}

def test_competency_bands_handles_missing_signals():
    assert _competency_bands({}) == {}


# ---- empty / single session ----

def test_empty_history_is_safe():
    out = build_insights([])
    assert out["total_sessions"] == 0
    assert out["latest"] is None
    assert out["competencies"] == []

def test_single_session_latest_and_competencies():
    h = [_session("lean_hire", "new_grad",
                  [_sig("Problem-solving", "solid"), _sig("Communication & structure", "borderline")])]
    out = build_insights(h)
    assert out["total_sessions"] == 1
    assert out["latest"]["recommendation"] == "lean_hire"
    assert out["latest"]["level_read"] == "new_grad"
    comp = {c["key"]: c for c in out["competencies"]}
    assert comp["problem_solving"]["latest_band"] == "solid"
    assert comp["communication"]["latest_band"] == "borderline"


# ---- trends across sessions ----

def test_competency_trend_improving():
    h = [
        _session("on_fence", "new_grad", [_sig("Problem-solving", "borderline")], date="2026-06-01T10:00:00"),
        _session("lean_hire", "new_grad", [_sig("Problem-solving", "solid")], date="2026-06-08T10:00:00"),
        _session("hire", "mid", [_sig("Problem-solving", "outstanding")], date="2026-06-13T10:00:00"),
    ]
    out = build_insights(h)
    comp = {c["key"]: c for c in out["competencies"]}
    assert comp["problem_solving"]["trend"] == "improving"

def test_competency_trend_regressing():
    h = [
        _session("hire", "mid", [_sig("Communication & structure", "outstanding")], date="2026-06-01T10:00:00"),
        _session("on_fence", "new_grad", [_sig("Communication & structure", "borderline")], date="2026-06-13T10:00:00"),
    ]
    out = build_insights(h)
    comp = {c["key"]: c for c in out["competencies"]}
    assert comp["communication"]["trend"] == "regressing"

def test_recommendation_trend_and_strength():
    h = [
        _session("on_fence", "new_grad", [_sig("Problem-solving", "borderline"), _sig("Ownership", "poor")]),
        _session("lean_hire", "new_grad", [_sig("Problem-solving", "outstanding"), _sig("Ownership", "borderline")]),
    ]
    out = build_insights(h)
    # strongest = highest latest band, weakest = lowest
    assert out["strongest"]["key"] == "problem_solving"
    assert out["weakest"]["key"] == "ownership_impact"
    # recommendation improved on_fence -> lean_hire
    assert out["recommendation_trend"] == "improving"

def test_by_track_counts():
    h = [
        _session("hire", "mid", [_sig("Problem-solving", "solid")], track="intro"),
        _session("hire", "mid", [_sig("Coding", "solid")], track="coding"),
        _session("hire", "mid", [_sig("Coding", "solid")], track="coding"),
    ]
    out = build_insights(h)
    assert out["by_track"]["coding"] == 2
    assert out["by_track"]["intro"] == 1

def test_latest_delivery_surfaced():
    h = [_session("lean_hire", "new_grad", [_sig("Problem-solving", "solid")],
                  delivery={"wpm": 150.0, "wpm_band": "ideal", "filler_per_min": 4.0, "filler_band": "good"})]
    out = build_insights(h)
    assert out["latest"]["delivery"]["wpm"] == 150.0


# ---- richer personality aggregation (Wing D C4) ----

def test_lifetime_aggregates_across_sessions():
    h = [
        _session("hire", "mid", [_sig("Coding", "outstanding"), _sig("Problem-solving", "solid")],
                 delivery={"word_count": 200, "sentence_count": 20, "filler_total": 10,
                           "filler_breakdown": {"like": 4, "um": 2}}),
        _session("hire", "mid", [_sig("Coding", "outstanding")],
                 delivery={"word_count": 100, "sentence_count": 12, "filler_total": 3,
                           "filler_breakdown": {"like": 1}}),
    ]
    lt = build_insights(h)["lifetime"]
    assert lt["words"] == 300
    assert lt["sentences"] == 32
    assert lt["fillers"] == 13
    assert lt["great_answers"] == 2  # one outstanding per session (recomputed from signals)
    assert lt["top_crutch_word"] == {"word": "like", "count": 5}

def test_best_lines_prefers_outstanding_with_quotes():
    h = [_session("hire", "mid", [
        {"name": "Coding", "band": "outstanding", "evidence": ["I refactored the loop into O(n)"]},
        {"name": "Problem-solving", "band": "solid", "evidence": ["I clarified the inputs first"]},
        {"name": "Ownership", "band": "borderline", "evidence": ["we shipped it"]},
    ])]
    bl = build_insights(h)["best_lines"]
    assert bl[0]["quote"] == "I refactored the loop into O(n)"   # outstanding ranks first
    assert all(line["band"] in ("outstanding", "solid") for line in bl)
    assert all(line["quote"] != "we shipped it" for line in bl)  # borderline excluded

def test_reco_series_is_chronological_with_indices():
    h = [
        _session("on_fence", "new_grad", [_sig("Coding", "borderline")], date="2026-06-01T10:00:00"),
        _session("hire", "mid", [_sig("Coding", "outstanding")], date="2026-06-08T10:00:00"),
    ]
    rs = build_insights(h)["reco_series"]
    assert [r["recommendation"] for r in rs] == ["on_fence", "hire"]
    assert rs[0]["index"] == 3 and rs[1]["index"] == 5  # positions in the 7-point scale

def test_competency_by_track_records_best_band_per_track():
    h = [
        _session("hire", "mid", [_sig("Communication & structure", "solid")], track="behavioral"),
        _session("hire", "mid", [_sig("Communication & structure", "borderline")], track="coding"),
    ]
    cbt = build_insights(h)["competency_by_track"]
    assert cbt["communication"]["behavioral"] == "solid"
    assert cbt["communication"]["coding"] == "borderline"

def test_recurring_to_raise_ranks_by_signal_frequency():
    h = [
        _session("on_fence", "new_grad", [_sig("Ownership", "poor")],
                 gap={"signal": "Ownership", "move": "Lead with 'I', quantify the result"}),
        _session("lean_hire", "new_grad", [_sig("Ownership", "borderline")],
                 gap={"signal": "Ownership", "move": "Name the metric you moved"}),
        _session("hire", "mid", [_sig("Coding", "solid")],
                 gap={"signal": "Coding", "move": "Add tests"}),
    ]
    rtr = build_insights(h)["recurring_to_raise"]
    assert rtr[0]["signal"] == "Ownership" and rtr[0]["count"] == 2
    assert rtr[0]["competency"] == "ownership_impact"
    assert rtr[0]["move"]  # latest move text carried through

def test_mixed_old_and_new_history_does_not_crash():
    # An OLD row (pre-C2/C3): delivery has only the original fields, no
    # sentence_count / filler_breakdown / great_answers / gap_to_next.
    old = {
        "track": "behavioral", "created_at": "2026-05-01T10:00:00",
        "scores": {"verdict": {
            "overall": {"recommendation": "lean_hire", "level_read": "new_grad", "headline": "h"},
            "signals": [{"name": "Ownership", "band": "outstanding", "evidence": ["I drove it end to end"]}],
            "delivery": {"wpm": 150.0, "filler_total": 5, "word_count": 300},
        }},
    }
    new = _session("hire", "mid", [_sig("Coding", "outstanding")], track="coding",
                   delivery={"word_count": 120, "sentence_count": 14, "filler_total": 2,
                             "filler_breakdown": {"um": 2}},
                   gap={"signal": "Coding", "move": "add tests"}, great=1)
    out = build_insights([old, new])  # must not raise
    assert out["total_sessions"] == 2
    lt = out["lifetime"]
    assert lt["words"] == 420            # 300 + 120
    assert lt["sentences"] == 14         # old row had none -> 0 + 14
    assert lt["great_answers"] == 2      # old recomputed from signals (1) + new stored (1)
    assert lt["top_crutch_word"] == {"word": "um", "count": 2}  # old had no breakdown

def test_empty_history_has_personality_keys():
    out = build_insights([])
    assert out["lifetime"]["words"] == 0
    assert out["lifetime"]["top_crutch_word"] is None
    assert out["best_lines"] == []
    assert out["reco_series"] == []
    assert out["competency_by_track"] == {}
    assert out["recurring_to_raise"] == []
