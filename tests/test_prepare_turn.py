"""
The wired turn loop: InterviewAgent.prepare_turn with a fake assessor.

These are the properties that make the audit's S1 findings impossible by
construction rather than unlikely:
- exactly one [FLOW MOVE] note, after the user message (F2: the transition is
  this reply, never the next one);
- the loop never raises anything but StopResponse, even when the assessor
  blows up (F1: the SDK swallows other exceptions and skips the reply);
- a stage advance emits one stage_change and speaks nothing (F3: no wasted
  "ready?" exchange, no canned acknowledgement);
- the agent exposes no function tools and the session caps tool steps at one
  (F1 at the root);
- the closing is one utterance spoken by code, ending with the sentinel (F14).
"""

import asyncio
from types import SimpleNamespace

import pytest
from livekit.agents import StopResponse, llm as lk_llm

import interview_runtime as ir
import interview_turn as it
from interview_coverage import TurnAssessment


def _config(**overrides):
    base = {'track': 'behavioral', 'role': 'Backend Engineer', 'level': 'mid', 'framework': 'amazon',
            'depth': 'medium', 'user_id': 'u'}
    base.update(overrides)
    return base


class StubSession:
    def __init__(self, state):
        self.userdata = state
        self.said = []
        self.generated = []
        self.items_added = []
        self.current_speech = None

    def say(self, text, allow_interruptions=True):
        self.said.append(text)

    def generate_reply(self, **kw):
        self.generated.append(kw)

    def _conversation_item_added(self, msg):
        self.items_added.append(msg)

    def on(self, *a, **k):
        pass


class FakeActivity:
    def __init__(self, session):
        self.session = session
        self.instructions = []

    async def update_instructions(self, text):
        self.instructions.append(text)


def make_agent(track='behavioral', assess=None, **cfg):
    state = ir.build_interview_state(_config(track=track, **cfg), candidate_name='Priya Raman')
    if track == 'behavioral':
        state.generated_questions = [
            {'main_question': 'Tell me about a time you dove deep on a hard bug.', 'competency': 'Dive Deep',
             'follow_up_probes': ['What tools did you use to diagnose it?', 'How did you make sure the fix stuck?']},
            {'main_question': 'Describe a time you balanced customer needs against constraints.', 'competency': 'Customer Obsession',
             'follow_up_probes': ['What did the customer actually get?']},
        ]
        state.active_question_count = 2
    transport = ir.NullTransport()
    agent = ir.InterviewAgent(transport=transport, candidate_info={'name': 'Priya Raman', 'role': 'Backend Engineer'},
                              track_type=track, assess=assess)
    session = StubSession(state)
    agent._activity = FakeActivity(session)
    return agent, state, session, transport


def full_star(**extra):
    async def assess(inp):
        return TurnAssessment.from_dict({
            'signals': [{'name': 'Ownership', 'level': 'demonstrated', 'evidence': 'I was the one on call'},
                        {'name': 'Impact & metrics', 'level': 'demonstrated', 'evidence': 'CTR recovered the next day'},
                        {'name': 'Communication & structure', 'level': 'demonstrated', 'evidence': 'first, then'}],
            'star': {k: 'demonstrated' for k in ('situation', 'task', 'action', 'result')},
            'answered_question': True, 'answer_style': 'normal', 'candidate_asked': 'none', 'said_dont_know': False,
            **extra})
    return assess


def turn(agent, text):
    msg = lk_llm.ChatMessage(role='user', content=[text])
    ctx = agent.chat_ctx.copy()
    ctx.insert(msg)
    move = asyncio.run(agent.prepare_turn(ctx, msg))
    return move, ctx


def notes(ctx):
    return [i.text_content for i in ctx.items if getattr(i, 'role', '') == 'assistant' and str(i.text_content).startswith(it.MOVE_HEADER)]


# ---------------------------------------------------------------------------

def test_exactly_one_note_lands_after_the_user_message():
    agent, state, session, transport = make_agent(assess=full_star())
    move, ctx = turn(agent, "Hi, I'm Priya. Eight years in payments; I led the sharding migration.")
    ns = notes(ctx)
    assert len(ns) == 1
    roles = [getattr(i, 'role', None) for i in ctx.items]
    assert roles[-2:] == ['user', 'assistant']
    assert 'word for word' in ns[0] or 'ONE concrete question' in ns[0]
    assert session.said == [] and session.generated == []   # the note is the whole turn


def test_a_star_story_in_self_intro_advances_without_a_canned_line_or_a_second_ask():
    agent, state, session, transport = make_agent(assess=full_star())
    turn(agent, "Hi, I'm Priya. Eight years in payments.")
    move, ctx = turn(agent, "Last November our ranking model degraded 8%... I found the root cause in six hours; CTR recovered.")
    # Communication & structure is demonstrated and the floor is met -> advance.
    assert state.stage.value == 'behavioral_q1'
    assert move.advanced_to == 'behavioral_q1'
    assert move.question == 'Tell me about a time you dove deep on a hard bug.'
    assert [e['stage'] for e in transport.of_type('stage_change')] == ['behavioral_q1']
    assert session.said == []                       # no acknowledgement spoken by code
    assert 'Great' not in notes(ctx)[0]
    # and the STAR story is already credited toward the behavioral stage's signals
    assert state.ledger.missing(it.stage_required_signals('behavioral', 'behavioral_q1', state.generated_questions[0])) == []


def test_assessor_failure_degrades_to_the_safe_note_never_to_silence():
    async def boom(inp):
        raise RuntimeError("openai is down")
    agent, state, session, transport = make_agent(assess=boom)
    move, ctx = turn(agent, "Hello there.")
    ns = notes(ctx)
    assert len(ns) == 1                              # a note was still written
    assert state.stage.value == 'self_intro'
    assert state.ledger.turns_in_stage == 1          # the turn counted, coverage did not move


def test_prepare_turn_never_raises_when_everything_is_broken():
    agent, state, session, transport = make_agent(assess=full_star())
    state.get_time_status = lambda: (_ for _ in ()).throw(RuntimeError("clock broke"))
    move, ctx = turn(agent, "anything")
    assert notes(ctx) == [it.SAFE_NOTE]


def test_repeat_request_repeats_the_spoken_question():
    async def asks_repeat(inp):
        return TurnAssessment.from_dict({'signals': [], 'star': {}, 'candidate_asked': 'repeat', 'answer_style': 'terse'})
    agent, state, session, transport = make_agent(assess=asks_repeat)
    state.last_question = "What broke first?"
    move, ctx = turn(agent, "Sorry, can you say that again?")
    assert move.kind == 'repeat' and move.question == "What broke first?"
    assert 'First say exactly: "Sure."' in notes(ctx)[0]


def test_closing_is_spoken_by_code_and_the_reply_is_suppressed():
    agent, state, session, transport = make_agent(assess=full_star())
    # Jump to the last behavioral stage so coverage ends the interview.
    asyncio.run(ir.advance_to(state, agent, transport, state.get_stage_by_name('behavioral_q2')))
    turn(agent, "Here is the situation and what I did.")
    msg = lk_llm.ChatMessage(role='user', content=['...and that shipped a week early.'])
    ctx = agent.chat_ctx.copy()
    with pytest.raises(StopResponse):
        asyncio.run(agent.prepare_turn(ctx, msg))
    assert state.stage.value == 'closing'
    assert len(session.said) == 1 and session.said[0].endswith(it.CLOSING_SENTINEL)
    assert 'CTR recovered the next day' in session.said[0]
    assert state.closing_spoken is True
    assert session.items_added and session.items_added[0].text_content == '...and that shipped a week early.'


def test_agent_exposes_no_function_tools():
    agent, *_ = make_agent(assess=full_star())
    assert agent.tools == []


def test_build_session_caps_tool_steps_at_one(monkeypatch):
    captured = {}

    class FakeSession:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr(ir, 'AgentSession', FakeSession)
    state = ir.build_interview_state(_config(track='intro'))
    ir.build_session(state, llm=object())
    assert captured['max_tool_steps'] == 1


def test_forced_transition_parks_a_question_that_the_next_turn_asks():
    """The fallback timer's contract: advance silently, park the opening
    question, and the candidate's next words get it as the reply."""
    agent, state, session, transport = make_agent(assess=full_star())
    asyncio.run(ir.advance_to(state, agent, transport, state.get_stage_by_name('behavioral_q1'), forced=True))
    state.pending_move = ir.opening_move_for(state)
    parked = state.pending_move.question
    assert parked == 'Tell me about a time you dove deep on a hard bug.'

    async def nothing_new(inp):
        return TurnAssessment.from_dict({'signals': [], 'star': {}})
    agent._assessor = it.TurnAssessor(nothing_new)
    move, ctx = turn(agent, "Okay.")
    assert move.question == parked and state.pending_move is None


def test_skip_asks_the_new_stages_first_question_not_an_acknowledgement():
    agent, state, session, transport = make_agent(assess=full_star())
    asyncio.run(ir.execute_skip_transition(session, state, state.get_stage_by_name('behavioral_q2'), agent, transport))
    assert state.stage.value == 'behavioral_q2'
    assert session.said == []
    assert len(session.generated) == 1
    note = session.generated[0]['instructions']
    assert note.startswith(it.MOVE_HEADER)
    assert 'Describe a time you balanced customer needs' in note
    assert "Let's move" not in note and 'Priya Raman' not in note


def test_after_the_closing_line_flow_stays_quiet():
    """The room disconnects a few seconds after the sentinel; a goodbye from
    the candidate in that window must not restart the interview."""
    agent, state, session, transport = make_agent(assess=full_star())
    state.closing_spoken = True
    msg = lk_llm.ChatMessage(role='user', content=['Thanks, you too.'])
    with pytest.raises(StopResponse):
        asyncio.run(agent.prepare_turn(agent.chat_ctx.copy(), msg))
    assert session.generated == [] and session.said == []


def test_the_intro_track_runs_the_real_loop_not_the_safe_note():
    """The base InterviewState had no track_type; prepare_turn raised on the
    intro track and every turn silently fell back to the safe note."""
    agent, state, session, transport = make_agent(track='intro', assess=full_star())
    move, ctx = turn(agent, "I'm Priya, eight years in payments.")
    assert notes(ctx) != [it.SAFE_NOTE]
    assert move.reason != 'safe_note'
    assert state.ledger.demonstrated()   # the assessment was merged
