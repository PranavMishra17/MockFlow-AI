"""
How an interview ends, and how a forced or skipped transition speaks.

Audit F14: the closing used to be detected by a "good luck" heuristic on a
model turn, so it fired on turns that merely said "luck" and never fired on
closings that did not; and a skip or a timed-out stage spoke a canned line
with the full name. Now the closing is one utterance spoken by code that
ends in a sentinel, and forced transitions arrive as the next stage's first
question.
"""

import asyncio
import types

import interview_runtime as ir
import interview_turn as it
from interview_coverage import TurnAssessment


class FakeSession:
    def __init__(self, state=None):
        self.handlers = {}
        self.userdata = state
        self.said = []
        self.generated = []
        self.current_speech = None

    def on(self, event, fn=None):
        if fn is not None:
            self.handlers.setdefault(event, []).append(fn)
            return fn

        def register(f):
            self.handlers.setdefault(event, []).append(f)
            return f
        return register

    def fire(self, event, payload):
        for fn in self.handlers.get(event, []):
            fn(payload)

    async def say(self, text, allow_interruptions=True):
        self.said.append(text)

    def generate_reply(self, **kw):
        self.generated.append(kw)


def _item(role, text):
    msg = types.SimpleNamespace(role=role, text_content=text)
    return types.SimpleNamespace(item=msg)


def _config(track='behavioral'):
    return {'track': track, 'role': 'Backend Engineer', 'level': 'mid', 'framework': 'amazon', 'depth': 'medium', 'user_id': 'u'}


def test_only_the_sentinel_finalizes_the_interview():
    state = ir.build_interview_state(_config())
    state.transition_to(state.get_stage_by_name('closing'))
    session = FakeSession(state)
    fired = []

    async def on_closing():
        fired.append(True)

    async def run():
        ir.attach_handlers(session, state, ir.NullTransport(), on_closing=on_closing)
        session.fire("conversation_item_added", _item("assistant", "Thank you so much, and best of luck with everything ahead!"))
        await asyncio.sleep(0.05)
        assert fired == [], "a 'good luck' line must not end the interview"
        session.fire("conversation_item_added", _item("assistant", it.build_closing_utterance(state.ledger, "Priya", "behavioral")))
        await asyncio.sleep(0.05)
        assert state.closing_message_delivered is True
    asyncio.run(run())


def test_closing_utterance_is_what_speak_closing_says():
    state = ir.build_interview_state(_config())
    agent = ir.InterviewAgent(transport=ir.NullTransport(), candidate_info={'name': 'Priya Raman', 'role': 'x'}, track_type='behavioral',
                              assess=lambda inp: None)
    session = FakeSession(state)
    transport = ir.NullTransport()
    asyncio.run(ir.speak_closing(state, agent, session, transport))
    asyncio.run(ir.speak_closing(state, agent, session, transport))   # idempotent
    assert state.stage.value == 'closing'
    assert len(session.said) == 1 and session.said[0].endswith(it.CLOSING_SENTINEL)
    assert "Priya" in session.said[0] and "Priya Raman" not in session.said[0]
    assert transport.of_type('stage_change')[-1]['stage'] == 'closing'


def test_skip_to_closing_speaks_the_closing_not_a_question():
    state = ir.build_interview_state(_config())
    agent = ir.InterviewAgent(transport=ir.NullTransport(), candidate_info={'name': 'Priya Raman', 'role': 'x'}, track_type='behavioral',
                              assess=lambda inp: None)
    session = FakeSession(state)
    asyncio.run(ir.execute_skip_transition(session, state, state.get_stage_by_name('closing'), agent, ir.NullTransport()))
    assert session.generated == []
    assert session.said and session.said[0].endswith(it.CLOSING_SENTINEL)


def test_ask_opening_question_uses_the_banks_question_and_records_it():
    state = ir.build_interview_state(_config())
    state.generated_questions = [{'main_question': 'Tell me about a time you dove deep.', 'competency': 'Dive Deep', 'follow_up_probes': []}]
    state.active_question_count = 1
    agent = ir.InterviewAgent(transport=ir.NullTransport(), candidate_info={'name': 'Priya Raman', 'role': 'x'}, track_type='behavioral',
                              assess=lambda inp: None)
    session = FakeSession(state)
    asyncio.run(ir.advance_to(state, agent, ir.NullTransport(), state.get_stage_by_name('behavioral_q1'), forced=True))
    asyncio.run(ir.ask_opening_question(state, agent, session, reason='forced'))
    note = session.generated[0]['instructions']
    assert 'Tell me about a time you dove deep.' in note and note.startswith(it.MOVE_HEADER)
    assert state.last_question == 'Tell me about a time you dove deep.'
    assert state.questions_asked == ['Tell me about a time you dove deep.']
    assert state.pending_move is None


def test_transcript_records_the_full_spoken_question_for_repeat():
    state = ir.build_interview_state(_config())
    session = FakeSession(state)

    async def run():
        ir.attach_handlers(session, state, ir.NullTransport())
        session.fire("conversation_item_added", _item("assistant", "Got it. What did you decide? And what did it cost you?"))
        await asyncio.sleep(0)
    asyncio.run(run())
    assert state.last_question == "What did you decide? And what did it cost you?"


def test_move_notes_never_reach_the_transcript():
    state = ir.build_interview_state(_config())
    session = FakeSession(state)
    handles = ir.attach_handlers(session, state, ir.NullTransport())
    session.fire("conversation_item_added", _item("assistant", it.render_move_note(it.Move(kind='ask', question='x?'))))
    assert handles.conversation['agent'] == []
