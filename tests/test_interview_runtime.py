"""
The interview runtime's public surface.

This is the contract the parallel worktrees build on — transports, state
construction, command dispatch, the saved-interview shape — so it is pinned
here rather than left to be re-derived from a live room.

The single most load-bearing assertion in this file is
`test_imports_with_no_environment_at_all`. Everything else in the runtime is
only testable because that holds.
"""

import asyncio
import json
import os
import subprocess
import sys
import types
from datetime import datetime, timedelta

import pytest

import agent_mode
import interview_runtime as ir
from fsm import (
    BehavioralInterviewState,
    BehavioralStage,
    CodingInterviewState,
    CodingStage,
    InterviewStage,
    InterviewState,
    TechnicalVoiceInterviewState,
    TechnicalVoiceStage,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# The property the whole refactor exists for
# ---------------------------------------------------------------------------

def test_imports_with_no_environment_at_all():
    """A bare interpreter with no API keys must be able to import the runtime.

    This is what makes the interview testable without LiveKit. It is checked in
    a subprocess with a stripped environment because the test runner's own
    process has already inherited whatever the developer has set.
    """
    keep = ('PATH', 'SYSTEMROOT', 'TEMP', 'TMP', 'PATHEXT', 'COMSPEC',
            'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'HOMEDRIVE', 'HOMEPATH')
    env = {k: v for k, v in os.environ.items() if k in keep}
    env['PYTHONPATH'] = REPO_ROOT

    result = subprocess.run(
        [sys.executable, '-c', 'import interview_runtime; print("ok")'],
        env=env, cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert 'ok' in result.stdout


def test_agent_worker_does_not_validate_env_at_import():
    """Env validation belongs in main(), not module scope.

    When it ran at import, `import agent_worker` from a test was a hard exit.
    """
    import inspect

    import agent_worker

    src = inspect.getsource(agent_worker)
    before_first_def = src.split('\ndef ', 1)[0]
    assert 'sys.exit' not in before_first_def
    assert callable(agent_worker.validate_env)


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

class FakeParticipant:
    def __init__(self):
        self.published = []

    async def publish_data(self, data, reliable=True):
        self.published.append((data, reliable))


class FakeRoom:
    def __init__(self):
        self.local_participant = FakeParticipant()


def test_room_transport_publishes_json_bytes():
    room = FakeRoom()
    transport = ir.RoomTransport(room)

    asyncio.run(transport.emit({"type": "stage_change", "stage": "self_intro"}))

    data, reliable = room.local_participant.published[0]
    assert json.loads(data.decode('utf-8')) == {"type": "stage_change", "stage": "self_intro"}
    assert reliable is True


def test_room_transport_passes_reliable_through():
    room = FakeRoom()
    asyncio.run(ir.RoomTransport(room).emit({"type": "x"}, reliable=False))
    assert room.local_participant.published[0][1] is False


def test_room_transport_survives_a_room_with_no_participant():
    """A late emit after disconnect must not raise into the interview."""
    room = types.SimpleNamespace(local_participant=None)
    asyncio.run(ir.RoomTransport(room).emit({"type": "x"}))  # must not raise


def test_null_transport_records_decoded_payloads():
    transport = ir.NullTransport()
    asyncio.run(transport.emit({"type": "stage_change", "stage": "closing"}))
    asyncio.run(transport.emit({"type": "user_caption", "text": "hi"}))

    assert transport.of_type("stage_change") == [{"type": "stage_change", "stage": "closing"}]
    assert len(transport.events) == 2


# ---------------------------------------------------------------------------
# build_interview_state
# ---------------------------------------------------------------------------

def _config(**overrides):
    """A normalized config, built the way both transports build one."""
    return agent_mode.normalize_config(overrides)


def test_intro_track_builds_the_base_state():
    state = build = ir.build_interview_state(_config(track='intro'), candidate_name='Ada')
    assert type(state) is InterviewState
    assert state.stage == InterviewStage.WELCOME
    assert build.candidate_name == 'Ada'


def test_behavioral_track_carries_framework_depth_and_custom_questions():
    state = ir.build_interview_state(_config(
        track='behavioral', framework='google', depth='deep',
        custom_questions='Tell me about a conflict\nDescribe a failure',
    ))
    assert isinstance(state, BehavioralInterviewState)
    assert state.stage == BehavioralStage.GREETING
    assert state.framework == 'google'
    assert state.depth_setting == 'deep'
    assert state.custom_questions == ['Tell me about a conflict', 'Describe a failure']


def test_technical_voice_track_caps_topics_at_three():
    state = ir.build_interview_state(_config(
        track='technical_voice', topics='caching,indexing', custom_topics='sharding,queues',
    ))
    assert isinstance(state, TechnicalVoiceInterviewState)
    assert state.stage == TechnicalVoiceStage.GREETING
    assert state.selected_topics == ['caching', 'indexing', 'sharding']
    assert state.active_topic_count == 3


def test_coding_track_reads_language_and_problem_count_from_the_shared_parser():
    """These two used to be read off participant attributes outside the parser,
    which meant a metadata-only dispatch silently lost them."""
    state = ir.build_interview_state(_config(
        track='coding', preferred_language='javascript', problem_count='2',
    ))
    assert isinstance(state, CodingInterviewState)
    assert state.stage == CodingStage.GREETING
    assert state.preferred_language == 'javascript'
    assert state.active_problem_count == 2


@pytest.mark.parametrize('raw,expected', [
    ('1', 1), ('2', 2), ('5', 2), ('0', 1), (3, 2), ('not a number', 2),
])
def test_problem_count_is_clamped_to_one_or_two(raw, expected):
    state = ir.build_interview_state(_config(track='coding', problem_count=raw))
    assert state.active_problem_count == expected


def test_candidate_fields_are_copied_onto_the_state():
    state = ir.build_interview_state(
        _config(role='Staff Engineer', level='senior', email='a@b.co',
                resume_text='resume', job_description='jd'),
        candidate_name='Grace',
    )
    assert state.candidate_name == 'Grace'
    assert state.job_role == 'Staff Engineer'
    assert state.experience_level == 'senior'
    assert state.candidate_email == 'a@b.co'
    assert state.uploaded_resume_text == 'resume'
    assert state.job_description == 'jd'


# ---------------------------------------------------------------------------
# Injectable clock
# ---------------------------------------------------------------------------

def test_stage_timing_follows_an_injected_clock():
    """A harness must be able to age a stage without sleeping through it."""
    fake = {'t': datetime(2026, 1, 1, 12, 0, 0)}
    state = ir.build_interview_state(_config(track='intro'), now=lambda: fake['t'])

    assert state.time_in_current_stage() == 0.0
    fake['t'] += timedelta(minutes=7)
    assert state.time_in_current_stage() == pytest.approx(420.0)


def test_the_default_clock_is_real_time():
    state = ir.build_interview_state(_config(track='intro'))
    assert state.time_in_current_stage() < 5.0


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------

class StubAgent:
    """Stands in for InterviewAgent where only the skip path is under test."""

    candidate_name = 'Ada'

    def __init__(self):
        self.instructions = []

    def _get_stage_instructions(self, state, stage):
        return f"instructions for {stage.value}"

    async def update_instructions(self, text):
        self.instructions.append(text)


class StubSession:
    def __init__(self):
        self.said = []

    async def say(self, text, allow_interruptions=True):
        self.said.append(text)


def _ctx(state=None):
    state = state if state is not None else ir.build_interview_state(_config(track='intro'))
    transport = ir.NullTransport()
    return ir.CommandContext(
        session=StubSession(),
        state=state,
        agent=StubAgent(),
        transport=transport,
        track_config=None,
    )


def test_every_documented_client_command_has_a_handler():
    assert set(ir.COMMANDS) == {
        'skip_intro', 'code_submitted', 'skip_coding_problem',
        'skip_stage', 'ready_for_problem',
    }


def test_an_unknown_command_is_reported_unhandled_not_raised():
    ctx = _ctx()
    assert asyncio.run(ir.handle_command({'type': 'not_a_command'}, ctx)) is False
    assert asyncio.run(ir.handle_command({}, ctx)) is False


def test_a_failing_handler_does_not_take_the_interview_down():
    ctx = _ctx()

    async def boom(payload, ctx):
        raise RuntimeError('handler exploded')

    ir.COMMANDS['_boom'] = boom
    try:
        assert asyncio.run(ir.handle_command({'type': '_boom'}, ctx)) is True
    finally:
        del ir.COMMANDS['_boom']


def test_skip_stage_transitions_and_tells_the_ui():
    ctx = _ctx()
    asyncio.run(ir.handle_command(
        {'type': 'skip_stage', 'target_stage': 'past_experience'}, ctx))

    assert ctx.state.stage == InterviewStage.PAST_EXPERIENCE
    assert ctx.transport.of_type('stage_change')[0]['stage'] == 'past_experience'


def test_skip_stage_records_the_stage_it_skipped():
    ctx = _ctx()
    asyncio.run(ir.handle_command(
        {'type': 'skip_stage', 'target_stage': 'past_experience'}, ctx))
    assert ctx.state.skipped_stages == [InterviewStage.WELCOME.value]


def test_skip_stage_with_an_unknown_stage_name_does_nothing():
    ctx = _ctx()
    asyncio.run(ir.handle_command({'type': 'skip_stage', 'target_stage': 'nope'}, ctx))

    assert ctx.state.stage == InterviewStage.WELCOME
    assert ctx.transport.events == []


def test_skip_intro_advances_to_the_tracks_first_real_stage():
    """For the intro track that is past_experience — the greeting AND the
    self-intro are what 'skip intro' skips."""
    ctx = _ctx()
    asyncio.run(ir.handle_command({'type': 'skip_intro'}, ctx))

    assert ctx.state.stage == InterviewStage.PAST_EXPERIENCE
    assert ctx.transport.of_type('stage_change')[0]['stage'] == 'past_experience'


def test_skip_intro_is_a_no_op_once_past_the_greeting():
    ctx = _ctx()
    ctx.state.transition_to(InterviewStage.COMPANY_FIT)
    asyncio.run(ir.handle_command({'type': 'skip_intro'}, ctx))

    assert ctx.state.stage == InterviewStage.COMPANY_FIT
    assert ctx.transport.of_type('stage_change') == []


def test_ready_for_problem_is_ignored_off_the_coding_track():
    ctx = _ctx()
    asyncio.run(ir.handle_command({'type': 'ready_for_problem'}, ctx))
    assert ctx.transport.events == []


def test_code_submitted_refuses_a_fourth_attempt():
    state = ir.build_interview_state(_config(track='coding'))
    for _ in range(3):
        state.record_submission(0, 'x = 1', 'python', {})
    ctx = _ctx(state)

    asyncio.run(ir.handle_command(
        {'type': 'code_submitted', 'code': 'x = 1', 'language': 'python', 'problem_index': 0},
        ctx))

    assert ctx.transport.of_type('max_attempts_reached') == [
        {'type': 'max_attempts_reached', 'problem_index': 0}
    ]


# ---------------------------------------------------------------------------
# collect_interview_data
# ---------------------------------------------------------------------------

def _conversation():
    return {
        'agent': [{'index': 0, 'text': 'Tell me about yourself.', 'timestamp': 1, 'stage': 'self_intro'}],
        'user': [
            {'index': 0, 'text': 'Sure.', 'timestamp': 2, 'duration_s': 3.5, 'stage': 'self_intro'},
            {'index': 1, 'text': 'And also.', 'timestamp': 3, 'duration_s': None, 'stage': 'self_intro'},
        ],
    }


def test_collect_counts_both_sides_of_the_transcript():
    state = ir.build_interview_state(_config(track='intro'), candidate_name='Ada')
    row = ir.collect_interview_data(
        state, _conversation(), room_name='interview-ada-1', ended_by='natural_completion')

    assert row['total_messages'] == {'agent': 1, 'user': 2}
    assert row['conversation']['user'][0]['duration_s'] == 3.5


def test_collect_records_how_the_interview_ended():
    state = ir.build_interview_state(_config(track='intro'))
    for ended_by in ('natural_completion', 'user_disconnect'):
        row = ir.collect_interview_data(
            state, _conversation(), room_name='r', ended_by=ended_by)
        assert row['ended_by'] == ended_by


def test_collect_defaults_the_candidate_name_to_the_state():
    """The two finalize paths read the name from different variables; one
    function with one fallback is what stops them drifting again."""
    state = ir.build_interview_state(_config(track='intro'), candidate_name='Ada')
    from_state = ir.collect_interview_data(state, _conversation(), room_name='r', ended_by='x')
    overridden = ir.collect_interview_data(
        state, _conversation(), room_name='r', ended_by='x', candidate_name='Grace')

    assert from_state['candidate_name'] == 'Ada'
    assert overridden['candidate_name'] == 'Grace'


def test_collect_carries_the_track_configuration():
    state = ir.build_interview_state(_config(
        track='behavioral', framework='google', depth='deep'))
    row = ir.collect_interview_data(state, _conversation(), room_name='r', ended_by='x')

    assert row['track'] == 'behavioral'
    assert row['track_config']['framework'] == 'google'
    assert row['track_config']['depth'] == 'deep'


def test_collect_reports_which_documents_were_supplied():
    with_docs = ir.build_interview_state(
        _config(track='intro', resume_text='r', job_description='j'))
    without = ir.build_interview_state(_config(track='intro'))

    a = ir.collect_interview_data(with_docs, _conversation(), room_name='r', ended_by='x')
    b = ir.collect_interview_data(without, _conversation(), room_name='r', ended_by='x')

    assert (a['has_resume'], a['has_jd']) == (True, True)
    assert (b['has_resume'], b['has_jd']) == (False, False)


def test_collect_stamps_the_interview_with_the_state_clock():
    fixed = datetime(2026, 3, 1, 9, 30, 0)
    state = ir.build_interview_state(_config(track='intro'), now=lambda: fixed)
    row = ir.collect_interview_data(state, _conversation(), room_name='r', ended_by='x')
    assert row['interview_date'] == fixed.isoformat()
