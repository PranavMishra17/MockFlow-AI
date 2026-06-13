"""
evaluator — the reinvented hiring-lens feedback engine.

Replaces the legacy FEEDBACKSCORES (1-5 ad-hoc competencies + narrative essay).
The unit of feedback is a VERDICT from one interviewer's chair:

  "As a {archetype} {role} interviewer at {seniority}, would I advance you,
   and what evidence moves that call?"

Design rules (docs/EPIC_wingD_feedback_moat.md §1-3):
  - named signals per track x role, each judged into a 4-level band,
  - every band must cite a verbatim transcript quote (no quote -> cannot_determine),
  - the overall 7-point recommendation + scope/ownership level-read are computed
    deterministically (a FORMULA over per-signal bands, not an LLM gestalt),
  - countable delivery metrics are injected from code, never invented,
  - judged by the strongest, non-interviewer model.

The pure scoring/assembly logic lives here and is unit-tested; the LLM call
itself is thin and lives in the API layer.
"""

import copy
import os
from typing import Any, Dict, List, Optional

# 4-level ordinal band (Google's poor/borderline/solid/outstanding) and the
# 7-point overall recommendation scale (Strong No-Hire -> Strong Hire).
BANDS = ["poor", "borderline", "solid", "outstanding"]
RECOMMENDATIONS = [
    "strong_no_hire", "no_hire", "lean_no_hire",
    "on_fence", "lean_hire", "hire", "strong_hire",
]

_SCOPE_RANK = {"below_intern": 0, "intern": 1, "new_grad": 2, "mid": 3, "above_mid": 4}
_RANK_SCOPE = {v: k for k, v in _SCOPE_RANK.items()}


# ---------------------------------------------------------------- band math

def band_score(band: Optional[str]) -> Optional[int]:
    """poor=1 .. outstanding=4; anything else (incl. cannot_determine) -> None."""
    try:
        return BANDS.index(band) + 1
    except (ValueError, TypeError):
        return None


def rollup_recommendation(
    signals: List[Dict[str, Any]], weights: Optional[Dict[str, float]] = None
) -> str:
    """
    Weighted mean of scorable per-signal bands -> a 7-point recommendation.
    cannot_determine signals are excluded. No scorable signals -> on_fence.
    """
    pairs = []
    for s in signals:
        sc = band_score(s.get("band"))
        if sc is None:
            continue
        w = (weights or {}).get(s.get("name"), 1.0)
        pairs.append((sc, w))
    if not pairs:
        return "on_fence"
    avg = sum(sc * w for sc, w in pairs) / sum(w for _, w in pairs)
    idx = round((avg - 1.0) / 3.0 * 6)  # map 1..4 -> 0..6
    idx = max(0, min(len(RECOMMENDATIONS) - 1, idx))
    return RECOMMENDATIONS[idx]


def level_read(signals: List[Dict[str, Any]]) -> Optional[str]:
    """
    The scope/ownership level the candidate actually demonstrated — the median
    of per-signal scope_met (robust to one strong outlier; down-levels rather
    than rejects). None if no scope data.
    """
    ranks = sorted(
        _SCOPE_RANK[s["scope_met"]] for s in signals if s.get("scope_met") in _SCOPE_RANK
    )
    if not ranks:
        return None
    n = len(ranks)
    mid = n // 2
    median = ranks[mid] if n % 2 else (ranks[mid - 1] + ranks[mid]) // 2
    return _RANK_SCOPE[median]


def gap_to_next(signals: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The lowest scorable signal + the single move to raise it one band."""
    scorable = [(band_score(s.get("band")), s) for s in signals if band_score(s.get("band")) is not None]
    if not scorable:
        return None
    scorable.sort(key=lambda x: x[0])
    _, s = scorable[0]
    cur = s.get("band")
    nxt = BANDS[min(BANDS.index(cur) + 1, len(BANDS) - 1)] if cur in BANDS else None
    return {
        "signal": s.get("name"),
        "from_band": cur,
        "to_band": nxt,
        "move": s.get("to_raise", ""),
    }


# ------------------------------------------------------------- rubric blocks

# Each signal: what the interviewer is deciding + the quote-worthy positive and
# the no-hire negative (condensed from the research tables, §3.3-3.6).
SIGNAL_LIBRARY: Dict[str, Dict[str, str]] = {
    # behavioral
    "Ownership": {"decides": "Will they own outcomes?",
                  "positive": "First-person 'I', personally drove/uncovered the problem",
                  "negative": "Defaults to 'we'; unclear personal contribution"},
    "Impact & metrics": {"decides": "Are the stories real and quantified?",
                         "positive": "Specific situation, metric-backed result, survives a deep probe",
                         "negative": "No numbers; vague outcome; collapses under follow-up"},
    "Conflict & collaboration": {"decides": "Authentic, low-ego collaborator?",
                                 "positive": "Empathy for the other side, disagree-then-commit",
                                 "negative": "Avoids conflict, blames teammates, insists they were right"},
    "Communication & structure": {"decides": "Can they make a point land?",
                                  "positive": "Signposted, concise, easy to follow",
                                  "negative": "Rambles, no structure, buries the point"},
    "Authenticity": {"decides": "Internalized vs rehearsed?",
                     "positive": "Specific, un-scripted, real stakes",
                     "negative": "Clean but emotionally flat / recites principles verbatim"},
    # coding
    "Problem-solving": {"decides": "Decompose & strategize, not just recall?",
                        "positive": "States approach + complexity before coding; weighs alternatives",
                        "negative": "Jumps to code, no plan, stuck without hints"},
    "Coding": {"decides": "Correct, clean, idiomatic code?",
               "positive": "Clean naming, modular, mentally compiles",
               "negative": "Syntax flailing; can't translate plan to code"},
    "Testing & verification": {"decides": "Do they verify their own work?",
                               "positive": "Tests normal + corner cases unprompted; self-corrects",
                               "negative": "Declares done untested; misses an obvious edge case"},
    "Response to hints": {"decides": "Coachability",
                          "positive": "Integrates the hint and accelerates",
                          "negative": "Ignores it; repeats the stuck approach; defensive"},
    # technical voice (SWE)
    "Technical depth": {"decides": "Real understanding, not buzzwords?",
                        "positive": "Explains the 'why' (invariants, complexity) out loud",
                        "negative": "Surface-level; can't go one layer deeper"},
    "Trade-off reasoning": {"decides": "Engineering judgment?",
                            "positive": "Names alternatives and the cost of each",
                            "negative": "One answer, no awareness of trade-offs"},
    # PM
    "Product sense": {"decides": "Do they start from the user?",
                      "positive": "Segments users, prioritizes a real pain, scopes a v1",
                      "negative": "Jumps to features; vague segment; UI-as-strategy"},
    "Analytical / execution": {"decides": "Can they reason with metrics?",
                               "positive": "Defines the metric first; sets guardrail/counter-metrics",
                               "negative": "Vanity metrics; no guardrails; diagnoses before defining"},
    "Technical fluency": {"decides": "Can they work with engineers?",
                          "positive": "Sound technical intuition and trade-offs",
                          "negative": "Hand-waves feasibility"},
    # DS / MLE
    "Statistics & decision logic": {"decides": "Sound inference tied to a decision?",
                                    "positive": "States assumptions; sets success criteria before peeking",
                                    "negative": "Recites tests; can't connect to a decision"},
    "ML depth & evaluation rigor": {"decides": "Production thinking, not just algorithms?",
                                    "positive": "Bias-variance, leakage/drift/calibration, offline->online",
                                    "negative": "Names algorithms; ignores evaluation rigor"},
    "SQL & data fluency": {"decides": "Day-one productive with data?",
                           "positive": "Correct joins/window functions with clear intent",
                           "negative": "Shaky joins/cohorting (a frequent hard filter)"},
    "Experimentation": {"decides": "Can they design & read an A/B test?",
                        "positive": "Guardrails, power, awareness of novelty/Simpson's",
                        "negative": "No guardrails; ignores novelty/network effects"},
    "Stakeholder communication": {"decides": "Connect analysis to a decision?",
                                  "positive": "'This changes the ship/no-ship call because...'",
                                  "negative": "Correct number, no 'so what'"},
    # intro
    "Motivation & authenticity": {"decides": "Genuine interest and self-knowledge?",
                                  "positive": "Specific, credible 'why this / why now'",
                                  "negative": "Generic, rehearsed, role-agnostic"},
    "Role / company fit": {"decides": "Do they understand what they're signing up for?",
                           "positive": "Concrete grasp of the role and the company",
                           "negative": "No real grasp; could be any company"},
    "Self-awareness": {"decides": "Do they know their edges?",
                       "positive": "Honest about a gap + how they're closing it",
                       "negative": "No reflection; deflects"},
}

# Track -> signal name list. technical_voice is role-defined; others are
# role-flavored (the prompt adds role emphasis) but share a core set.
_SIGNALS_BY_TRACK = {
    "behavioral": ["Ownership", "Impact & metrics", "Conflict & collaboration",
                   "Communication & structure", "Authenticity"],
    "coding": ["Problem-solving", "Coding", "Testing & verification",
               "Response to hints", "Communication & structure"],
    "intro": ["Motivation & authenticity", "Communication & structure",
              "Role / company fit", "Self-awareness"],
}
_TECHNICAL_VOICE_BY_ROLE = {
    "swe": ["Technical depth", "Trade-off reasoning", "Communication & structure"],
    "pm": ["Product sense", "Analytical / execution", "Technical fluency",
           "Communication & structure"],
    "ds_mle": ["Statistics & decision logic", "ML depth & evaluation rigor",
               "SQL & data fluency", "Experimentation", "Stakeholder communication"],
}

# Coding weighting from the 100K-interview data: problem-solving + coding
# dominate at L3-L4; communication gates only at L5+ (the "mid" floor here).
_CODING_WEIGHTS = {"Problem-solving": 2.0, "Coding": 2.0, "Testing & verification": 1.5,
                   "Response to hints": 1.0, "Communication & structure": 1.0}

_SENIORITY_EXEMPLARS = {
    "intern": "Bar: can think and learn with guidance; potential over track record (class projects OK).",
    "new_grad": "Bar: executes a well-defined task autonomously; clear, communicated work.",
    "mid": "Bar: owns ambiguous problems end-to-end, makes & defends trade-offs, shows emergent leadership.",
}


def _signals_for(track: str, role: str) -> List[Dict[str, Any]]:
    if track == "technical_voice":
        names = _TECHNICAL_VOICE_BY_ROLE.get(role, _TECHNICAL_VOICE_BY_ROLE["swe"])
    else:
        names = _SIGNALS_BY_TRACK.get(track, _SIGNALS_BY_TRACK["intro"])
    out = []
    for n in names:
        meta = SIGNAL_LIBRARY.get(n, {})
        out.append({"name": n, "decides": meta.get("decides", ""),
                    "positive": meta.get("positive", ""), "negative": meta.get("negative", "")})
    return out


def _weighting(track: str, seniority: str) -> Dict[str, float]:
    if track == "coding":
        w = dict(_CODING_WEIGHTS)
        if seniority == "mid":
            w["Communication & structure"] = 1.5  # communication gates more at mid+
        return w
    return {}


def build_rubric(
    track: str, role: str, seniority: str, archetype: str = "big_tech"
) -> Dict[str, Any]:
    """Assemble the named signals + level exemplar + weighting for a cell."""
    return {
        "track": track,
        "role": role,
        "seniority": seniority,
        "archetype": archetype,
        "signals": _signals_for(track, role),
        "level_exemplar": _SENIORITY_EXEMPLARS.get(seniority, _SENIORITY_EXEMPLARS["new_grad"]),
        "weighting": _weighting(track, seniority),
        "bands": BANDS,
        "recommendations": RECOMMENDATIONS,
    }


# ------------------------------------------------------------- finalization

def finalize_verdict(
    raw: Dict[str, Any],
    speech: Optional[Dict[str, Any]] = None,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Turn the LLM's raw verdict into the trustworthy final verdict:
      - any signal lacking a transcript quote -> cannot_determine (never scored),
      - recompute the 7-point recommendation as a FORMULA over the per-signal
        bands (don't trust the model's gestalt),
      - recompute the level-read from per-signal scope,
      - inject the deterministic delivery block,
      - attach the constructive gap-to-next.
    Does not mutate the input.
    """
    from feedback_scoring import delivery_metrics

    out = copy.deepcopy(raw)
    sigs = out.get("signals", []) or []
    for s in sigs:
        if not s.get("evidence"):
            s["band"] = "cannot_determine"

    overall = dict(out.get("overall", {}) or {})
    overall["recommendation"] = rollup_recommendation(sigs, weights)
    lvl = level_read(sigs)
    if lvl:
        overall["level_read"] = lvl
    out["overall"] = overall
    out["signals"] = sigs
    out["delivery"] = delivery_metrics(speech or {})
    out["gap_to_next"] = gap_to_next(sigs)
    return out


def pick_evaluator_model() -> str:
    """
    The judge should be the strongest available model and distinct from the
    interviewer model. Configurable via EVALUATOR_MODEL.
    """
    return os.getenv("EVALUATOR_MODEL", "gpt-4o")


# ----------------------------------------------------- metadata inference

def infer_role(job_role: Optional[str]) -> str:
    """Map a free-text job title to swe | pm | ds_mle (default swe)."""
    t = (job_role or "").lower()
    if any(k in t for k in ("product manager", "product mgr", " pm", "apm", "rpm")):
        return "pm"
    if any(k in t for k in ("data scien", "machine learning", "ml engineer", "ml eng", "mle", "data analyst")):
        return "ds_mle"
    return "swe"


def infer_seniority(level: Optional[str]) -> str:
    """Map a free-text level to intern | new_grad | mid (our early-career ceiling)."""
    t = (level or "").lower()
    if "intern" in t:
        return "intern"
    if any(k in t for k in ("new grad", "new-grad", "newgrad", "entry", "junior", "grad", "l3", "e3", "sde-1", "sde 1")):
        return "new_grad"
    # mid covers L4/L5/E4/E5; senior is clamped to mid (we don't model staff+).
    return "mid" if t else "new_grad"


def infer_archetype(company: Optional[str]) -> str:
    """Big Tech vs high-bar startup (shifts weighting/values). Default big_tech."""
    t = (company or "").lower()
    startups = ("stripe", "openai", "anthropic", "databricks", "ramp", "figma",
                "notion", "vercel", "scale ai", "mistral", "perplexity")
    return "high_bar_startup" if any(s in t for s in startups) else "big_tech"


# ----------------------------------------------------- prompt assembly

_ARCHETYPE_LABEL = {"big_tech": "Big Tech", "high_bar_startup": "high-bar startup"}
_ROLE_LABEL = {"swe": "software engineer", "pm": "product manager", "ds_mle": "data scientist / ML engineer"}


def build_evaluator_messages(
    rubric: Dict[str, Any],
    candidate_profile: str,
    job_summary: str,
    transcript: str,
    speech_summary: str,
    coding_results: Optional[str] = None,
) -> List[Dict[str, str]]:
    """
    Assemble the [system, user] messages for the hiring-lens evaluator. Encodes
    the non-negotiables: judge from the hiring decision, one band per named
    signal ONLY with a verbatim quote (else cannot_determine), reasoning before
    band, scope per signal, reward process over the optimal answer.
    """
    role_label = _ROLE_LABEL.get(rubric["role"], "candidate")
    arch_label = _ARCHETYPE_LABEL.get(rubric["archetype"], "Big Tech")

    signal_lines = "\n".join(
        f'- "{s["name"]}" — deciding: {s["decides"]} '
        f'| strong-hire looks like: {s["positive"]} '
        f'| no-hire looks like: {s["negative"]}'
        for s in rubric["signals"]
    )
    signal_names = ", ".join(f'"{s["name"]}"' for s in rubric["signals"])

    system = f"""You are an experienced {arch_label} interviewer for a {role_label} role. \
You are NOT a friendly coach summarizing a performance — you are deciding a HIRING outcome: \
"Would I advance this candidate, and what evidence moves that call?"

Calibrate to this level — {rubric['level_exemplar']} The bar shifts on SCOPE/OWNERSHIP, not raw knowledge. \
If technical signal is strong but scope is thin, DOWN-LEVEL (say they clear new-grad, not mid) rather than reject. \
For early-career, reward HOW they got there (reasoning, structure, ownership) over whether they reached the optimal answer.

Score ONLY these named signals: {signal_names}.

For EACH signal:
{signal_lines}

RULES (non-negotiable):
1. Assign a band from {rubric['bands']} ONLY if you can cite a VERBATIM quote from the candidate's transcript that justifies it. \
If you cannot find supporting evidence in their words, set band to "cannot_determine" — never guess.
2. Write your reasoning BEFORE the band. Be skeptical and specific.
3. Put 1-2 verbatim candidate quotes in "evidence" for every band you assign.
4. Assess "scope_met" per signal: one of intern | new_grad | mid | above_mid.
5. Give a concrete one-line "to_raise": the single move that lifts this signal one band.
6. Do NOT compute or restate delivery numbers (pace/fillers) — those are measured separately.

Output ONLY valid JSON (no markdown) in this exact schema:
{{
  "overall": {{ "confidence": "low|medium|high", "headline": "one calm hiring-manager sentence" }},
  "signals": [
    {{ "name": "<one of the signal names above>", "reasoning": "...", "band": "poor|borderline|solid|outstanding|cannot_determine",
       "scope_met": "intern|new_grad|mid|above_mid", "evidence": ["verbatim candidate quote"], "to_raise": "the one move" }}
  ],
  "differentiators": ["what would make this candidate a STRONG hire, not just a hire"]
}}
The overall recommendation and level are computed from your per-signal bands — you only provide confidence + headline."""

    user_parts = [
        "<CANDIDATE_PROFILE>\n" + (candidate_profile or "") + "\n</CANDIDATE_PROFILE>",
        "<JOB_SUMMARY>\n" + (job_summary or "") + "\n</JOB_SUMMARY>",
        "<MEASURED_DELIVERY>\n" + (speech_summary or "") + "\n</MEASURED_DELIVERY>",
    ]
    if coding_results:
        user_parts.append("<CODING_RESULTS>\n" + coding_results + "\n</CODING_RESULTS>")
    user_parts.append("<INTERVIEW_TRANSCRIPT>\n" + (transcript or "") + "\n</INTERVIEW_TRANSCRIPT>")
    user_parts.append("Return ONLY the JSON verdict. Every band you assign MUST quote the candidate's own words.")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]
