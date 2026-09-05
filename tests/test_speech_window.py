"""
The speaking-window capture that makes delivery pace a real measurement.

These tests used to exercise a hand-copied *mirror* of the handlers, because
`agent_worker.run_interview` was a ~600-line closure that could not be imported
without full LiveKit env — and a source-grep guard tried to keep the copy in
step with the original. Both are gone: `interview_runtime.attach_handlers` is
importable with no environment, so these drive the real handlers directly and
the copy cannot drift because there is no copy.

What matters is unchanged: a plausible measured duration when one exists, and
None — never a guess — whenever one does not.
"""

import asyncio
import types

import pytest

import interview_runtime as ir
from fsm import InterviewState, InterviewStage


class FakeSession:
    """Just enough AgentSession to register and fire the events we listen for."""

    def __init__(self):
        self.handlers = {}

    def on(self, event):
        def register(fn):
            self.handlers.setdefault(event, []).append(fn)
            return fn
        return register

    def fire(self, event, payload):
        for fn in self.handlers.get(event, []):
            fn(payload)


def _state_event(old, new):
    return types.SimpleNamespace(old_state=old, new_state=new)


def _transcript_event(text, is_final=True):
    return types.SimpleNamespace(transcript=text, is_final=is_final)


def _item_event(role, text):
    item = types.SimpleNamespace(role=role, text_content=text)
    return types.SimpleNamespace(item=item)


@pytest.fixture
def clock(monkeypatch):
    """A controllable stand-in for time.time, which the handlers read."""
    class C:
        t = 1000.0

        def __call__(self):
            return self.t

        def advance(self, s):
            self.t += s

    c = C()
    monkeypatch.setattr("time.time", c)
    return c


def drive(script):
    """Run `script(session, handles, transport)` inside an event loop.

    The handlers spawn caption tasks, so they need a running loop, and the loop
    has to be given a turn before assertions about emitted captions.
    """
    result = {}

    async def _go():
        session = FakeSession()
        state = InterviewState()
        state.transition_to(InterviewStage.SELF_INTRO)
        transport = ir.NullTransport()
        handles = ir.attach_handlers(session, state, transport)
        script(session, handles, transport)
        await asyncio.sleep(0)
        result['handles'] = handles
        result['transport'] = transport
        result['state'] = state

    asyncio.run(_go())
    return result


def user_turns(res):
    return res['handles'].conversation['user']


def test_a_normal_turn_yields_its_measured_duration(clock):
    def script(session, handles, transport):
        session.fire("user_state_changed", _state_event("listening", "speaking"))
        clock.advance(12.5)
        session.fire("user_state_changed", _state_event("speaking", "listening"))
        session.fire("user_input_transcribed", _transcript_event("an answer"))

    res = drive(script)
    assert [t["duration_s"] for t in user_turns(res)] == [12.5]


def test_transcript_arriving_before_the_state_flip_still_measures(clock):
    """The final transcript can land while the user is still marked speaking."""
    def script(session, handles, transport):
        session.fire("user_state_changed", _state_event("listening", "speaking"))
        clock.advance(8.0)
        session.fire("user_input_transcribed", _transcript_event("an answer"))

    res = drive(script)
    assert [t["duration_s"] for t in user_turns(res)] == [8.0]


def test_no_speaking_window_yields_none_not_a_guess(clock):
    def script(session, handles, transport):
        session.fire("user_input_transcribed", _transcript_event("an answer"))

    res = drive(script)
    assert [t["duration_s"] for t in user_turns(res)] == [None]


def test_each_turn_consumes_its_own_window(clock):
    def script(session, handles, transport):
        session.fire("user_state_changed", _state_event("listening", "speaking"))
        clock.advance(5.0)
        session.fire("user_state_changed", _state_event("speaking", "listening"))
        session.fire("user_input_transcribed", _transcript_event("first"))
        # A second transcript with no new speech must not reuse the first duration.
        session.fire("user_input_transcribed", _transcript_event("second"))

    res = drive(script)
    assert [t["duration_s"] for t in user_turns(res)] == [5.0, None]


def test_implausibly_short_windows_are_discarded(clock):
    def script(session, handles, transport):
        session.fire("user_state_changed", _state_event("listening", "speaking"))
        clock.advance(0.05)          # a blip, not an answer
        session.fire("user_state_changed", _state_event("speaking", "listening"))
        session.fire("user_input_transcribed", _transcript_event("hm"))

    res = drive(script)
    assert [t["duration_s"] for t in user_turns(res)] == [None]


def test_implausibly_long_windows_are_discarded(clock):
    """A stuck 'speaking' state must not become a 2-hour monologue."""
    def script(session, handles, transport):
        session.fire("user_state_changed", _state_event("listening", "speaking"))
        clock.advance(7200)
        session.fire("user_state_changed", _state_event("speaking", "listening"))
        session.fire("user_input_transcribed", _transcript_event("an answer"))

    res = drive(script)
    assert [t["duration_s"] for t in user_turns(res)] == [None]


def test_away_state_does_not_start_a_window(clock):
    def script(session, handles, transport):
        session.fire("user_state_changed", _state_event("listening", "away"))
        clock.advance(30)
        session.fire("user_state_changed", _state_event("away", "listening"))
        session.fire("user_input_transcribed", _transcript_event("an answer"))

    res = drive(script)
    assert [t["duration_s"] for t in user_turns(res)] == [None]


def test_turns_are_tagged_with_the_stage_they_were_answered_in(clock):
    def script(session, handles, transport):
        session.fire("user_input_transcribed", _transcript_event("an answer"))

    res = drive(script)
    assert user_turns(res)[0]["stage"] == InterviewStage.SELF_INTRO.value


def test_interim_transcripts_caption_but_do_not_record(clock):
    def script(session, handles, transport):
        session.fire("user_input_transcribed", _transcript_event("partial", is_final=False))

    res = drive(script)
    assert user_turns(res) == []
    assert [e["text"] for e in res['transport'].of_type("user_caption")] == ["partial"]


# --------------------------------------------------------------------------
# Typed turns. Before the runtime extraction, a typed answer reached the model
# and never reached the transcript, so it could not be scored.
# --------------------------------------------------------------------------

def test_a_typed_turn_is_recorded(clock):
    def script(session, handles, transport):
        session.fire("conversation_item_added", _item_event("user", "I typed this"))

    res = drive(script)
    assert [t["text"] for t in user_turns(res)] == ["I typed this"]


def test_a_typed_turn_has_no_speaking_duration(clock):
    """Nothing was spoken, so the honest answer is None — not zero."""
    def script(session, handles, transport):
        session.fire("conversation_item_added", _item_event("user", "I typed this"))

    res = drive(script)
    assert user_turns(res)[0]["duration_s"] is None


def test_a_spoken_turn_is_not_recorded_twice(clock):
    """The chat item that follows a voice turn must not duplicate it."""
    def script(session, handles, transport):
        session.fire("user_state_changed", _state_event("listening", "speaking"))
        clock.advance(4.0)
        session.fire("user_state_changed", _state_event("speaking", "listening"))
        session.fire("user_input_transcribed", _transcript_event("I said this"))
        session.fire("conversation_item_added", _item_event("user", "I said this"))

    res = drive(script)
    assert [t["text"] for t in user_turns(res)] == ["I said this"]
    assert user_turns(res)[0]["duration_s"] == 4.0


def test_a_turn_split_across_two_finals_is_not_tripled(clock):
    """One spoken turn can arrive as several finals and one concatenated item."""
    def script(session, handles, transport):
        session.fire("user_input_transcribed", _transcript_event("first half"))
        session.fire("user_input_transcribed", _transcript_event("second half"))
        session.fire("conversation_item_added", _item_event("user", "first half second half"))

    res = drive(script)
    assert [t["text"] for t in user_turns(res)] == ["first half", "second half"]


def test_typing_after_speaking_still_records_both(clock):
    def script(session, handles, transport):
        session.fire("user_input_transcribed", _transcript_event("spoken"))
        session.fire("conversation_item_added", _item_event("user", "spoken"))
        session.fire("conversation_item_added", _item_event("user", "typed"))

    res = drive(script)
    assert [t["text"] for t in user_turns(res)] == ["spoken", "typed"]


def test_an_empty_typed_item_is_ignored(clock):
    def script(session, handles, transport):
        session.fire("conversation_item_added", _item_event("user", "   "))

    res = drive(script)
    assert user_turns(res) == []


def test_agent_turns_are_recorded_and_captioned(clock):
    def script(session, handles, transport):
        session.fire("conversation_item_added", _item_event("assistant", "Tell me about yourself."))

    res = drive(script)
    assert [t["text"] for t in res['handles'].conversation["agent"]] == ["Tell me about yourself."]
    assert [e["text"] for e in res['transport'].of_type("agent_caption")] == [
        "Tell me about yourself."
    ]


# --------------------------------------------------------------------------
# End-to-end with the analytics module
# --------------------------------------------------------------------------

def test_measured_durations_flow_into_a_real_pace():
    """End-to-end with the analytics module: measured windows -> real WPM."""
    import speech_analytics as sa

    conv = {
        "user": [
            {"text": " ".join(["w"] * 100), "timestamp": 0, "duration_s": 60.0},
            {"text": " ".join(["w"] * 50), "timestamp": 90, "duration_s": 30.0},
        ],
        "agent": [{"text": "ok", "timestamp": 1}],
    }
    r = sa.analyze_transcript(conv)
    assert r["pace_available"] is True
    assert r["total_speaking_duration_seconds"] == 90.0
    assert r["avg_words_per_minute"] == 100.0      # 150 words / 1.5 min
    assert r["longest_monologue_s"] == 60.0


def test_a_turn_without_a_window_keeps_the_session_unmeasured():
    """One unmeasured turn must not be papered over by extrapolating the rest."""
    import speech_analytics as sa

    conv = {
        "user": [
            {"text": " ".join(["w"] * 100), "timestamp": 0, "duration_s": 60.0},
            {"text": " ".join(["w"] * 50), "timestamp": 90, "duration_s": None},
        ],
        "agent": [],
    }
    r = sa.analyze_transcript(conv)
    assert r["pace_available"] is False
    assert r["avg_words_per_minute"] is None
