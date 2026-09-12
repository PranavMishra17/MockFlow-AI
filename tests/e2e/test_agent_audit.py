"""
The persona regression: what the audit measured, as assertions.

Level B - real model, real tokens: `python -m pytest -m level_b tests/e2e/test_agent_audit.py -x`.
Run it before merging any change to prompts.py, interview_turn.py or
interview_runtime.py. Each persona x track is one short interview.

Every assertion is one of the audit's findings stated as a rule
(docs/AGENT_AUDIT_2026-09.md). The thresholds are deliberately loose enough
to survive model variance and tight enough that the old agent fails all of
them.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_audit as aa  # noqa: E402  (tests/e2e/agent_audit.py, a script, not a package)

pytestmark = pytest.mark.level_b

OUT = Path(__file__).resolve().parents[2] / "docs" / "audit" / "_regression"
FULL_NAMES = {p.name for p in aa.PERSONAS.values()}
PROMISES = re.compile(r"\b(in touch|email|next steps)\b", re.I)

# The matrix: one run per persona per track. Sessions are cached per test
# module so each interview runs once even though several tests read it.
_CASES = [(t, p) for t in aa.TRACK_CONFIG for p in aa.PERSONAS]
_RESULTS: dict = {}


def _run(track: str, persona_key: str) -> dict:
    key = (track, persona_key)
    if key not in _RESULTS:
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")
        _RESULTS[key] = asyncio.run(aa.run_one(track, aa.PERSONAS[persona_key], OUT, aa._client()))
    return _RESULTS[key]


def _flow_turns(r):
    return [h for h in r["history"] if h["who"] == "flow"]


def _candidate_turns(r):
    return [h for h in r["history"] if h["who"] == "candidate"]


@pytest.mark.parametrize("track,persona", _CASES, ids=[f"{t}:{p}" for t, p in _CASES])
def test_no_silent_turns(track, persona):
    """F1: every candidate turn gets a reply (the closing line counts)."""
    r = _run(track, persona)
    hist = r["history"]
    for i, h in enumerate(hist):
        if h["who"] != "candidate":
            continue
        after = [x for x in hist[i + 1:] if x["who"] in ("flow", "candidate")]
        if not after:
            continue   # the last thing said; the run ended
        assert after[0]["who"] == "flow", f"silent turn after: {h['text'][:80]!r}"


@pytest.mark.parametrize("track,persona", _CASES, ids=[f"{t}:{p}" for t, p in _CASES])
def test_one_question_per_turn_and_short(track, persona):
    """F13 / F15-adjacent: one question mark, under 60 words (45 is the ask; 60 the hard line)."""
    r = _run(track, persona)
    for h in _flow_turns(r)[1:]:   # greeting is fixed
        if h.get("stage") == "closing":
            continue
        assert h["text"].count("?") <= 1, h["text"]
        assert len(h["text"].split()) <= 60, h["text"]


@pytest.mark.parametrize("track,persona", _CASES, ids=[f"{t}:{p}" for t, p in _CASES])
def test_no_meta_no_praise_no_full_name_no_promises(track, persona):
    """F10 F11 F12 F16."""
    r = _run(track, persona)
    for h in _flow_turns(r):
        t = h["text"]
        assert not aa.META.search(t), t
        assert not aa.SYCOPHANCY.search(t), t
        assert not any(n in t for n in FULL_NAMES), t
        assert not PROMISES.search(t), t


@pytest.mark.parametrize("track,persona", _CASES, ids=[f"{t}:{p}" for t, p in _CASES])
def test_flow_progresses_on_its_own(track, persona):
    """F4 / F5: no simulated skip was needed, and the interview reached closing."""
    r = _run(track, persona)
    assert r["stalls"] == [], r["stalls"]
    assert r["final_stage"] == "closing", r["final_stage"]


@pytest.mark.parametrize("track,persona", _CASES, ids=[f"{t}:{p}" for t, p in _CASES])
def test_candidate_questions_get_an_answer_not_a_counter_question(track, persona):
    """F9: when the candidate asks something, the reply's first sentence is not a question."""
    r = _run(track, persona)
    hist = r["history"]
    for i, h in enumerate(hist):
        if h["who"] != "candidate" or not h["text"].rstrip().endswith("?"):
            continue
        nxt = next((x for x in hist[i + 1:] if x["who"] == "flow"), None)
        if not nxt:
            continue
        first = re.split(r"(?<=[.!?])\s+", nxt["text"].strip())[0]
        assert not first.endswith("?"), f"{h['text'][:60]!r} -> {nxt['text'][:80]!r}"


@pytest.mark.parametrize("track,persona", _CASES, ids=[f"{t}:{p}" for t, p in _CASES])
def test_interview_has_enough_substance(track, persona):
    """F17: at least five exchanges before closing, and a verdict was produced."""
    r = _run(track, persona)
    assert len(_candidate_turns(r)) >= 5
    assert (r.get("verdict") or {}).get("overall", {}).get("recommendation")


@pytest.mark.parametrize("track,persona", _CASES, ids=[f"{t}:{p}" for t, p in _CASES])
def test_text_latency_is_bounded(track, persona):
    """F15: median text-only reply under 3.5 s (assessment included; TTS adds ~1 s)."""
    r = _run(track, persona)
    lat = sorted(h["latency"] for h in _flow_turns(r) if h.get("latency"))
    assert lat and lat[len(lat) // 2] <= 3.5, lat
