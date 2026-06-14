"""
Tests for insights — the longitudinal aggregation behind the rebuilt
"Interview Personality" (docs/EPIC_wingD_feedback_moat.md §4, Phase 3).

Maps each session's per-signal verdict bands onto a stable canonical-competency
taxonomy so sessions are comparable across tracks, then derives trends, the
strongest/weakest competency, and the recommendation trajectory.
"""

from insights import (
    CANONICAL_COMPETENCIES,
    build_insights,
    signal_to_competency,
)


def _session(reco, level, signals, track="intro", date="2026-06-13T10:00:00",
             delivery=None):
    """A row shaped like get_user_score_history() returns."""
    return {
        "track": track,
        "created_at": date,
        "scores": {"verdict": {
            "overall": {"recommendation": reco, "level_read": level, "headline": "h"},
            "signals": signals,
            "delivery": delivery or {},
        }},
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
