"""
The caption reducer behind live captions in interview.html.

`static/captions.js` turns LiveKit `lk.transcription` text streams into the
text the caption element shows. The agents SDK frames those streams two ways —
the agent's speech as ONE delta stream per reply, the candidate's STT as a NEW
full-text stream per interim result with the same segment id — and the page
must show the right text under both without knowing which it is getting.

The reducer is plain JS with no DOM, so these tests run it under node. They
are skipped, not failed, where node is absent (the Python CI image may not
have it); the browser-level check is harness/caption_probe.py.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CAPTIONS_JS = REPO / "static" / "captions.js"

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def run_script(steps):
    """Feed a list of (op, args...) to a fresh CaptionTrack; return caption after each."""
    js = f"""
    const CaptionTrack = require({json.dumps(str(CAPTIONS_JS))});
    const t = new CaptionTrack();
    const out = [];
    for (const [op, ...args] of {json.dumps(steps)}) {{
        t[op](...args);
        out.push(t.caption());
    }}
    process.stdout.write(JSON.stringify({{captions: out, final: t.final, segmentId: t.segmentId}}));
    """
    proc = subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def test_agent_delta_stream_grows_word_by_word():
    """One stream per reply; each chunk is the next word(s), as the SDK sends it."""
    r = run_script([
        ["open", "SG_1"],
        ["append", "SG_1", "Hi"],
        ["append", "SG_1", " Candidate!"],
        ["append", "SG_1", " I'm"],
        ["append", "SG_1", " Alex."],
        ["close", "SG_1", True],
    ])
    assert r["captions"] == [
        "", "Hi", "Hi Candidate!", "Hi Candidate! I'm", "Hi Candidate! I'm Alex.", "Hi Candidate! I'm Alex.",
    ]
    assert r["final"] is True


def test_candidate_replace_stream_shows_latest_full_text():
    """STT interims each open a NEW stream with the FULL text and the SAME segment id.

    Reopening must reset, not append — otherwise the caption reads
    'I have I have three I have three years'.
    """
    r = run_script([
        ["open", "SG_u"], ["append", "SG_u", "I have"], ["close", "SG_u", False],
        ["open", "SG_u"], ["append", "SG_u", "I have three"], ["close", "SG_u", False],
        ["open", "SG_u"], ["append", "SG_u", "I have three years"], ["close", "SG_u", True],
    ])
    assert r["captions"][-1] == "I have three years"
    assert all("I have I have" not in c for c in r["captions"])
    assert r["final"] is True


def test_new_segment_replaces_previous_reply():
    r = run_script([
        ["open", "SG_1"], ["append", "SG_1", "First reply."], ["close", "SG_1", True],
        ["open", "SG_2"], ["append", "SG_2", "Second"],
    ])
    assert r["captions"][-1] == "Second"
    assert r["segmentId"] == "SG_2"
    assert r["final"] is False


def test_late_chunk_for_superseded_segment_is_ignored():
    """A straggling chunk from an interrupted reply must not corrupt the new one."""
    r = run_script([
        ["open", "SG_1"], ["append", "SG_1", "Old"],
        ["open", "SG_2"], ["append", "SG_2", "New"],
        ["append", "SG_1", " stale"],
        ["close", "SG_1", True],
    ])
    assert r["captions"][-1] == "New"
    assert r["final"] is False  # SG_1's close does not finalize SG_2


def test_caption_collapses_whitespace():
    """The LLM emits paragraph breaks; a one-line caption should not."""
    r = run_script([
        ["open", "SG_1"], ["append", "SG_1", "Let's begin."], ["append", "SG_1", "\n\nNow,"], ["append", "SG_1", " tell me."],
    ])
    assert r["captions"][-1] == "Let's begin. Now, tell me."


def test_live_flips_on_first_text_and_stays():
    """`live` gates the data-channel fallback per speaker: false until real stream
    text lands (an open alone is not enough), then true for the session."""
    js = f"""
    const CaptionTrack = require({json.dumps(str(CAPTIONS_JS))});
    const t = new CaptionTrack();
    const out = [t.live];
    t.open("SG_1"); out.push(t.live);
    t.append("SG_1", "Hi"); out.push(t.live);
    t.close("SG_1", true); t.open("SG_2"); out.push(t.live);
    process.stdout.write(JSON.stringify(out));
    """
    proc = subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True)
    assert json.loads(proc.stdout) == [False, False, True, True]
