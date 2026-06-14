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

# The "bar" per competency per target level (band_score 1-4), distilled from the
# §3.7 scope/ownership exemplars: intern ~ borderline (can do with guidance),
# new-grad ~ solid across (the canonical early-career bar), mid ~ outstanding on
# the level-defining axes (problem-solving / depth / ownership / domain) with
# communication gating at solid. Per-competency-per-level (not a flat polygon)
# and keyed off CANONICAL_COMPETENCIES (asserted in tests so the axes can't drift).
TARGET_BANDS_BY_LEVEL = {
    "intern":   {"communication": 2, "problem_solving": 2, "technical_depth": 2,
                 "ownership_impact": 2, "domain_rigor": 2},
    "new_grad": {"communication": 3, "problem_solving": 3, "technical_depth": 3,
                 "ownership_impact": 3, "domain_rigor": 3},
    "mid":      {"communication": 3, "problem_solving": 4, "technical_depth": 4,
                 "ownership_impact": 4, "domain_rigor": 4},
}


def signal_to_competency(name: str) -> Optional[str]:
    return SIGNAL_TO_COMPETENCY.get(name)


def _verdict(session: Dict[str, Any]) -> Dict[str, Any]:
    return ((session.get("scores") or {}).get("verdict") or {})


def _competency_bands(verdict: Dict[str, Any]) -> Dict[str, tuple]:
    """
    Reduce ONE verdict's per-signal bands to the best (band, score) per canonical
    competency. Shared by build_insights, the radar, and compare_verdicts so the
    signal->competency taxonomy can never drift between them. Unknown signals and
    unscorable bands (cannot_determine) are skipped.
    """
    best: Dict[str, tuple] = {}
    for sig in (verdict.get("signals") or []):
        comp = signal_to_competency(sig.get("name", ""))
        sc = band_score(sig.get("band"))
        if comp is None or sc is None:
            continue
        if comp not in best or sc > best[comp][1]:
            best[comp] = (sig.get("band"), sc)
    return best


def _trend(scores: List[int]) -> str:
    """improving / regressing / flat from a series of band-scores."""
    if len(scores) < 2:
        return "flat"
    if scores[-1] > scores[0]:
        return "improving"
    if scores[-1] < scores[0]:
        return "regressing"
    return "flat"


def _empty_lifetime() -> Dict[str, Any]:
    return {"sessions": 0, "words": 0, "sentences": 0, "fillers": 0,
            "great_answers": 0, "top_crutch_word": None}


def _target_polygon(level: Optional[str]) -> Dict[str, int]:
    """The 5 axis targets for a target level; defaults to the new-grad bar."""
    return dict(TARGET_BANDS_BY_LEVEL.get(level or "", TARGET_BANDS_BY_LEVEL["new_grad"]))


def build_insights(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate a user's verdict history into the personality/insights payload."""
    sessions = [h for h in history if _verdict(h).get("signals") is not None or _verdict(h).get("overall")]
    if not sessions:
        return {"total_sessions": 0, "latest": None, "competencies": [],
                "strongest": None, "weakest": None, "recommendation_trend": "flat",
                "by_track": {}, "lifetime": _empty_lifetime(), "best_lines": [],
                "reco_series": [], "competency_by_track": {}, "recurring_to_raise": [],
                "radar": None}

    by_track: Dict[str, int] = {}
    # competency_key -> ordered list of (band_str, score) across sessions that had it
    series: Dict[str, List[tuple]] = {c: [] for c in CANONICAL_COMPETENCIES}

    # richer personality aggregates — every read tolerates old rows that predate
    # the C2/C3 fields (graceful .get(...) so the dashboard never 500s).
    lt_words = lt_sentences = lt_fillers = lt_great = 0
    crutch_counts: Dict[str, int] = {}
    best_lines: List[Dict[str, Any]] = []
    reco_series: List[Dict[str, Any]] = []
    comp_by_track: Dict[str, Dict[str, tuple]] = {}
    gap_counts: Dict[str, Dict[str, Any]] = {}

    for h in sessions:
        v = _verdict(h)
        track = h.get("track", "intro")
        date = h.get("created_at")
        by_track[track] = by_track.get(track, 0) + 1

        # best band per competency in THIS session
        for comp, pair in _competency_bands(v).items():
            series[comp].append(pair)
            slot = comp_by_track.setdefault(comp, {})
            if track not in slot or pair[1] > slot[track][1]:
                slot[track] = pair  # best band for this competency within this track

        d = v.get("delivery") or {}
        lt_words += int(d.get("word_count") or 0)
        lt_sentences += int(d.get("sentence_count") or 0)
        lt_fillers += int(d.get("filler_total") or 0)
        for word, n in (d.get("filler_breakdown") or {}).items():
            crutch_counts[word] = crutch_counts.get(word, 0) + int(n or 0)

        sigs = v.get("signals") or []
        great = v.get("great_answers")
        if great is None:  # old row: recompute from the persisted signal bands
            great = sum(1 for s in sigs if s.get("band") == "outstanding")
        lt_great += int(great or 0)

        for s in sigs:  # collect best lines from strong, evidence-backed signals
            if s.get("band") not in ("outstanding", "solid"):
                continue
            comp = signal_to_competency(s.get("name", ""))
            for q in (s.get("evidence") or []):
                if q:
                    best_lines.append({
                        "quote": q, "signal": s.get("name"), "competency": comp,
                        "competency_label": _COMPETENCY_LABEL.get(comp, ""),
                        "band": s.get("band"), "track": track, "date": date,
                    })

        reco = (v.get("overall") or {}).get("recommendation")
        try:
            idx = RECOMMENDATIONS.index(reco)
        except (ValueError, TypeError):
            idx = None
        reco_series.append({"date": date, "track": track, "recommendation": reco, "index": idx})

        gap = v.get("gap_to_next") or {}
        gsig = gap.get("signal")
        if gsig:  # cluster recurring gaps by signal (stable across free-text moves)
            gcomp = signal_to_competency(gsig)
            slot = gap_counts.setdefault(gsig, {
                "signal": gsig, "competency": gcomp,
                "competency_label": _COMPETENCY_LABEL.get(gcomp, ""),
                "count": 0, "move": ""})
            slot["count"] += 1
            if gap.get("move"):
                slot["move"] = gap.get("move")  # keep the latest (oldest->newest)

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

    # best lines: outstanding before solid (stable sort keeps chronological order within a band)
    best_lines.sort(key=lambda b: 0 if b["band"] == "outstanding" else 1)
    competency_by_track = {c: {t: pair[0] for t, pair in tracks.items()}
                           for c, tracks in comp_by_track.items()}
    lifetime = {
        "sessions": len(sessions),
        "words": lt_words,
        "sentences": lt_sentences,
        "fillers": lt_fillers,
        "great_answers": lt_great,
        "top_crutch_word": ({"word": max(crutch_counts, key=crutch_counts.get),
                             "count": max(crutch_counts.values())} if crutch_counts else None),
    }

    # radar: your latest band per competency vs the bar for the level you're
    # AIMING at (context.seniority; level_read is what you DEMONSTRATED). An axis
    # with no data stays None (not 0) so the UI can dim it rather than imply "poor".
    you_by_comp = {c["key"]: c["latest_score"] for c in competencies}
    target_level = (last_v.get("context") or {}).get("seniority") or "new_grad"
    target = _target_polygon(target_level)
    radar = {
        "level": target_level,
        "level_read": last_overall.get("level_read"),
        "axes": [{"key": c, "label": _COMPETENCY_LABEL[c],
                  "you_score": you_by_comp.get(c), "target_score": target[c]}
                 for c in CANONICAL_COMPETENCIES],
    }

    return {
        "total_sessions": len(sessions),
        "latest": latest,
        "competencies": competencies,
        "strongest": strongest,
        "weakest": weakest,
        "recommendation_trend": rec_trend,
        "by_track": by_track,
        "lifetime": lifetime,
        "best_lines": best_lines[:6],
        "reco_series": reco_series,
        "competency_by_track": competency_by_track,
        "recurring_to_raise": sorted(gap_counts.values(), key=lambda g: g["count"], reverse=True),
        "radar": radar,
    }


def _delta(scores: List[Optional[int]]) -> Optional[int]:
    """last - first across a per-session score series; None if either end is missing."""
    if len(scores) < 2 or scores[0] is None or scores[-1] is None:
        return None
    return scores[-1] - scores[0]


def compare_verdicts(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Align 2+ sessions for a side-by-side compare. Competencies are mapped onto
    the canonical taxonomy so cross-track sessions still compare; signals align
    by name (union). Deltas are first->last via band_score and stay None when
    either end is unmeasured (never coerced to 0). Pure.
    """
    sessions = list(sessions or [])
    metas, comp_bands_per, sig_bands_per = [], [], []
    for h in sessions:
        v = _verdict(h)
        overall = v.get("overall") or {}
        metas.append({
            "interview_id": h.get("interview_id"),
            "track": h.get("track"),
            "date": h.get("created_at"),
            "recommendation": overall.get("recommendation"),
            "level_read": overall.get("level_read"),
        })
        comp_bands_per.append(_competency_bands(v))
        sig_bands_per.append({s.get("name"): s.get("band")
                              for s in (v.get("signals") or []) if s.get("name")})

    competencies = []
    for key in CANONICAL_COMPETENCIES:
        bands = [cb.get(key, (None, None))[0] for cb in comp_bands_per]
        scores = [cb.get(key, (None, None))[1] for cb in comp_bands_per]
        if any(b is not None for b in bands):
            competencies.append({"key": key, "label": _COMPETENCY_LABEL[key],
                                 "bands": bands, "scores": scores, "delta": _delta(scores)})

    seen, sig_names = set(), []
    for sb in sig_bands_per:
        for name in sb:
            if name not in seen:
                seen.add(name)
                sig_names.append(name)
    signals = []
    for name in sig_names:
        bands = [sb.get(name) for sb in sig_bands_per]
        signals.append({"name": name, "bands": bands,
                        "delta": _delta([band_score(b) for b in bands])})

    improved = [c["label"] for c in competencies if (c["delta"] or 0) > 0]
    lagged = [c["label"] for c in competencies
              if c["scores"][-1] is not None and c["scores"][-1] <= 2]

    return {"sessions": metas, "competencies": competencies,
            "signals": signals, "improved": improved, "lagged": lagged}
