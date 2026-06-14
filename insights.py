"""
insights — longitudinal aggregation behind the rebuilt "Interview Personality".

Takes a user's persisted verdict history (oldest -> newest, as
db.get_user_score_history returns) and maps each session's per-signal bands onto
a stable canonical-competency taxonomy so sessions are comparable across tracks.
Derives per-competency latest band + trend, the strongest/weakest competency,
the overall recommendation trajectory, and the latest delivery.

Pure (no I/O). Replaces the legacy 1-5 average that the dashboard used to show
(retired with the legacy scorer — which is why it rendered "Average Score —").
"""

from typing import Any, Dict, List, Optional

from evaluator import RECOMMENDATIONS, band_score

# Stable competencies that span tracks (docs §4). `delivery` is surfaced
# separately (it's deterministic), not derived from signal bands.
CANONICAL_COMPETENCIES = [
    "communication", "problem_solving", "technical_depth",
    "ownership_impact", "domain_rigor",
]

# Map each evaluator signal name onto a canonical competency.
SIGNAL_TO_COMPETENCY = {
    "Ownership": "ownership_impact",
    "Impact & metrics": "ownership_impact",
    "Conflict & collaboration": "communication",
    "Communication & structure": "communication",
    "Authenticity": "communication",
    "Stakeholder communication": "communication",
    "Self-awareness": "communication",
    "Problem-solving": "problem_solving",
    "Trade-off reasoning": "problem_solving",
    "Analytical / execution": "problem_solving",
    "Response to hints": "problem_solving",
    "Coding": "technical_depth",
    "Testing & verification": "technical_depth",
    "Technical depth": "technical_depth",
    "Technical fluency": "technical_depth",
    "ML depth & evaluation rigor": "technical_depth",
    "SQL & data fluency": "technical_depth",
    "Product sense": "domain_rigor",
    "Statistics & decision logic": "domain_rigor",
    "Experimentation": "domain_rigor",
    "Motivation & authenticity": "domain_rigor",
    "Role / company fit": "domain_rigor",
}

_COMPETENCY_LABEL = {
    "communication": "Communication",
    "problem_solving": "Problem-solving",
    "technical_depth": "Technical depth",
    "ownership_impact": "Ownership & impact",
    "domain_rigor": "Role & domain rigor",
}


def signal_to_competency(name: str) -> Optional[str]:
    return SIGNAL_TO_COMPETENCY.get(name)


def _verdict(session: Dict[str, Any]) -> Dict[str, Any]:
    return ((session.get("scores") or {}).get("verdict") or {})


def _trend(scores: List[int]) -> str:
    """improving / regressing / flat from a series of band-scores."""
    if len(scores) < 2:
        return "flat"
    if scores[-1] > scores[0]:
        return "improving"
    if scores[-1] < scores[0]:
        return "regressing"
    return "flat"


def build_insights(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate a user's verdict history into the personality/insights payload."""
    sessions = [h for h in history if _verdict(h).get("signals") is not None or _verdict(h).get("overall")]
    if not sessions:
        return {"total_sessions": 0, "latest": None, "competencies": [],
                "strongest": None, "weakest": None, "recommendation_trend": "flat",
                "by_track": {}}

    by_track: Dict[str, int] = {}
    # competency_key -> ordered list of (band_str, score) across sessions that had it
    series: Dict[str, List[tuple]] = {c: [] for c in CANONICAL_COMPETENCIES}

    for h in sessions:
        v = _verdict(h)
        track = h.get("track", "intro")
        by_track[track] = by_track.get(track, 0) + 1

        # best band per competency in THIS session
        best: Dict[str, tuple] = {}
        for sig in (v.get("signals") or []):
            comp = signal_to_competency(sig.get("name", ""))
            sc = band_score(sig.get("band"))
            if comp is None or sc is None:
                continue
            if comp not in best or sc > best[comp][1]:
                best[comp] = (sig.get("band"), sc)
        for comp, pair in best.items():
            series[comp].append(pair)

    competencies = []
    for key in CANONICAL_COMPETENCIES:
        s = series[key]
        if not s:
            continue
        latest_band, latest_score = s[-1]
        competencies.append({
            "key": key,
            "label": _COMPETENCY_LABEL[key],
            "latest_band": latest_band,
            "latest_score": latest_score,
            "trend": _trend([sc for _, sc in s]),
            "sessions": len(s),
        })

    ranked = sorted(competencies, key=lambda c: c["latest_score"], reverse=True)
    strongest = ranked[0] if ranked else None
    weakest = ranked[-1] if ranked else None

    first_v, last_v = _verdict(sessions[0]), _verdict(sessions[-1])
    rec_trend = "flat"
    try:
        fi = RECOMMENDATIONS.index((first_v.get("overall") or {}).get("recommendation"))
        li = RECOMMENDATIONS.index((last_v.get("overall") or {}).get("recommendation"))
        rec_trend = "improving" if li > fi else "regressing" if li < fi else "flat"
    except (ValueError, TypeError):
        pass

    last_overall = last_v.get("overall") or {}
    latest = {
        "recommendation": last_overall.get("recommendation"),
        "level_read": last_overall.get("level_read"),
        "headline": last_overall.get("headline"),
        "track": sessions[-1].get("track"),
        "date": sessions[-1].get("created_at"),
        "delivery": last_v.get("delivery") or {},
    }

    return {
        "total_sessions": len(sessions),
        "latest": latest,
        "competencies": competencies,
        "strongest": strongest,
        "weakest": weakest,
        "recommendation_trend": rec_trend,
        "by_track": by_track,
    }
