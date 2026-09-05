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


def test_agent_worker_does_not_resolve_env_at_import():
    """Env resolution belongs behind a function, not at module scope.

    Two separate module-level exits used to make `import agent_worker` fatal:
    the missing-key check, and `agent_mode.resolve_mode` rejecting a typo'd
    AGENT_MODE.
    """
    import inspect

    import agent_worker

    src = inspect.getsource(agent_worker)
    before_first_def = src.split('\ndef ', 1)[0]
    assert 'sys.exit' not in before_first_def
    assert 'resolve_mode' not in before_first_def
    assert callable(agent_worker.resolve_worker_env)


def test_a_typod_agent_mode_is_rejected_but_not_at_import():
    """resolve_mode raises rather than defaulting, so the operator gets a signal
    instead of silently running the other transport. That exit belongs to the
    call, not to the import."""
    import agent_worker

    with pytest.raises(SystemExit):
        agent_worker.resolve_worker_env({'AGENT_MODE': 'dsipatch'})


def test_direct_mode_requires_a_room_name_and_dispatch_does_not():
    """The room is a per-job value under dispatch, so it cannot be required."""
    import agent_worker

    keys = {
        'OPENAI_API_KEY': 'k', 'DEEPGRAM_API_KEY': 'k', 'LIVEKIT_URL': 'u',
        'LIVEKIT_API_KEY': 'k', 'LIVEKIT_API_SECRET': 's',
    }

    with pytest.raises(SystemExit):
        agent_worker.resolve_worker_env(dict(keys))          # direct, no room

    resolved = agent_worker.resolve_worker_env(dict(keys, INTERVIEW_ROOM_NAME='r'))
    assert resolved['mode'] == agent_mode.MODE_DIRECT
    assert resolved['room_name'] == 'r'


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
# One counter, two submit paths
#
# `record_submission` (the function_tool path) wrote string keys; the editor's
# `code_submitted` path incremented the same dict with INT keys, which the
# string-keyed reader could not see. Each path therefore kept its own private
# count, and the max-attempts guard never fired for editor submissions — a
# candidate could submit forever. These tests fail if a second writer returns.
# ---------------------------------------------------------------------------

class _FakeCompletions:
    """Stands in for the OpenAI client `_evaluate_code_async` builds itself."""

    def __init__(self):
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        content = json.dumps({
            'brief_verbal_feedback': 'Reasonable approach.',
            'correctness': 'fail',
        })
        message = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class _FakeOpenAI:
    def __init__(self, api_key=None):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions())


@pytest.fixture
def no_network(monkeypatch):
    """`_evaluate_code_async` constructs its own OpenAI client. Stub it out."""
    monkeypatch.setattr('openai.AsyncOpenAI', _FakeOpenAI)


def _coding_ctx():
    state = ir.build_interview_state(_config(track='coding'))
    state.generated_problems = [
        {'title': 'Two Sum', 'description': 'd', 'examples': [], 'constraints': []},
    ]
    return _ctx(state)


def _submit(ctx, code='x = 1'):
    asyncio.run(ir.handle_command(
        {'type': 'code_submitted', 'code': code, 'language': 'python', 'problem_index': 0},
        ctx))


def test_editor_submissions_are_counted_by_the_shared_reader(no_network):
    ctx = _coding_ctx()
    for _ in range(2):
        _submit(ctx)

    assert ctx.state.get_attempts_for_problem(0) == 2


def test_the_editor_path_hits_the_max_attempts_guard(no_network):
    """The guard is on the editor path; before the fix it could never fire."""
    ctx = _coding_ctx()
    for _ in range(3):
        _submit(ctx)
    assert ctx.transport.of_type('max_attempts_reached') == []

    _submit(ctx)

    assert ctx.transport.of_type('max_attempts_reached') == [
        {'type': 'max_attempts_reached', 'problem_index': 0}
    ]
    # A refused submission must not be evaluated or counted.
    assert ctx.state.get_attempts_for_problem(0) == 3


def test_both_submit_paths_share_one_counter(no_network):
    """A tool-recorded attempt and editor attempts add up to one total."""
    ctx = _coding_ctx()
    ctx.state.record_submission(0, 'first', 'python', {})
    _submit(ctx, 'second')
    _submit(ctx, 'third')

    assert ctx.state.get_attempts_for_problem(0) == 3
    _submit(ctx, 'fourth')
    assert ctx.transport.of_type('max_attempts_reached') != []


def test_the_attempt_counter_is_keyed_by_strings(no_network):
    """Int keys silently become strings across JSON; mixed keys split the count."""
    ctx = _coding_ctx()
    _submit(ctx)

    assert list(ctx.state.submissions_per_problem) == ['0']
    assert all(isinstance(k, str) for k in ctx.state.submissions_per_problem)


def test_every_submission_is_recorded_in_one_shape(no_network):
    """Both writers used to append to `submissions`; only one had a timestamp."""
    ctx = _coding_ctx()
    ctx.state.record_submission(0, 'first', 'python', {})
    _submit(ctx, 'second')

    assert len(ctx.state.submissions) == 2
    for entry in ctx.state.submissions:
        assert set(entry) == {
            'problem_index', 'attempt', 'code', 'language', 'evaluation', 'timestamp',
        }
    assert [e['attempt'] for e in ctx.state.submissions] == [1, 2]


def test_skipping_to_the_next_problem_reads_the_shared_counter(no_network):
    """The skip path reported an attempt number off its own int-keyed read."""
    ctx = _coding_ctx()
    ctx.state.generated_problems.append(
        {'title': 'Next', 'description': 'd', 'examples': [], 'constraints': []})
    ctx.state.active_problem_count = 2
    ctx.state.record_submission(1, 'earlier work', 'python', {})

    asyncio.run(ir.handle_command({'type': 'skip_coding_problem'}, ctx))

    pushed = ctx.transport.of_type('coding_problem')[-1]
    assert pushed['problem_index'] == 1
    assert pushed['attempt_number'] == 2


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


# ---------------------------------------------------------------------------
# Stage pointers
#
# The index block lived inline in `transition_stage`, so every other path that
# changed the stage left the pointers behind. Skipping to behavioral_q2 asked
# question 1 again; skipping into a coding problem left the stage inactive with
# no start time. These pin the shared helper both paths now call.
# ---------------------------------------------------------------------------

def test_skipping_to_a_later_behavioral_question_moves_the_index():
    state = ir.build_interview_state(_config(track='behavioral'))
    state.generated_questions = [
        {'main_question': 'Q one', 'competency': 'A'},
        {'main_question': 'Q two', 'competency': 'B'},
        {'main_question': 'Q three', 'competency': 'C'},
    ]
    ctx = _ctx(state)

    asyncio.run(ir.handle_command(
        {'type': 'skip_stage', 'target_stage': 'behavioral_q2'}, ctx))

    assert ctx.state.stage.value == 'behavioral_q2'
    assert ctx.state.current_question_index == 1, "skipping to Q2 must ask Q2, not Q1"


def test_the_pointer_helper_is_a_no_op_for_stages_without_an_index():
    state = ir.build_interview_state(_config(track='behavioral'))
    before = state.current_question_index
    ir.sync_stage_pointers(state, BehavioralStage.CLOSING)
    assert state.current_question_index == before


def test_entering_a_coding_problem_activates_it_and_stamps_a_start_time():
    fixed = datetime(2026, 5, 1, 10, 0, 0)
    state = ir.build_interview_state(_config(track='coding'), now=lambda: fixed)
    assert state.coding_stage_active is False

    ir.sync_stage_pointers(state, CodingStage.CODING_PROBLEM_2)

    assert state.current_problem_index == 1
    assert state.coding_stage_active is True
    assert state.problem_start_times['1'] == fixed.isoformat()


def test_leaving_the_coding_problems_deactivates_the_editor():
    state = ir.build_interview_state(_config(track='coding'))
    ir.sync_stage_pointers(state, CodingStage.CODING_PROBLEM_1)
    assert state.coding_stage_active is True

    ir.sync_stage_pointers(state, CodingStage.CLOSING)
    assert state.coding_stage_active is False


# ---------------------------------------------------------------------------
# The question bank
#
# Generation used to happen only if the model called a tool that no prompt asks
# it to call. The behavioral track therefore ran on improvised questions with
# the configured framework and the candidate's custom questions silently
# dropped. It is the runtime's job now.
# ---------------------------------------------------------------------------

def test_the_coding_bank_is_built_without_any_model_call():
    """The coding track selects from a vetted bank, so this needs no network."""
    state = ir.build_interview_state(_config(track='coding', problem_count='2'))
    assert not state.generated_problems

    assert asyncio.run(ir.ensure_questions_generated(state)) is True
    assert len(state.generated_problems) >= 1
    assert state.active_problem_count >= 1


def test_generating_twice_does_not_regenerate():
    """Idempotent, so the tool firing after startup costs nothing."""
    state = ir.build_interview_state(_config(track='coding'))
    asyncio.run(ir.ensure_questions_generated(state))
    first = state.generated_problems

    assert asyncio.run(ir.ensure_questions_generated(state)) is False
    assert state.generated_problems is first


def test_the_intro_track_has_no_bank_and_does_not_try_to_build_one():
    state = ir.build_interview_state(_config(track='intro'))
    assert asyncio.run(ir.ensure_questions_generated(state)) is False


@pytest.mark.parametrize('depth,expected', [
    ('light', 2), ('medium', 3), ('deep', 3), ('LIGHT', 2), (None, 3), ('nonsense', 3),
])
def test_question_count_follows_the_depth_setting(depth, expected):
    """The model used to choose this by passing `count`, which it has no basis for."""
    assert ir._question_count_for_depth(depth) == expected


def test_generation_failure_degrades_the_interview_rather_than_ending_it(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError('openai is down')

    monkeypatch.setattr(ir, '_chat_json', boom)
    state = ir.build_interview_state(_config(track='behavioral'))

    result = asyncio.run(ir.generate_questions_for(state))

    assert 'Failed to generate questions' in result
    assert state.generated_questions == []


# ---------------------------------------------------------------------------
# Custom questions
#
# The generation prompt asks the model to include the candidate's own questions
# "as-is". It complied in one run and paraphrased in the next, which meant a
# question someone typed out might simply never be asked.
# ---------------------------------------------------------------------------

def test_custom_questions_are_added_verbatim_when_the_model_drops_them():
    generated = [{'main_question': 'Tell me about a time you led a team', 'competency': 'Ownership'}]
    custom = ['Tell me about a time you rolled back a release']

    result = ir._with_custom_questions(generated, custom)

    assert [q['main_question'] for q in result] == [
        'Tell me about a time you rolled back a release',
        'Tell me about a time you led a team',
    ]


def test_custom_questions_lead_so_the_three_stages_cannot_fill_up_first():
    generated = [{'main_question': f'Generated {i}'} for i in range(3)]
    result = ir._with_custom_questions(generated, ['My own question'])
    assert result[0]['main_question'] == 'My own question'


def test_a_custom_question_the_model_reproduced_is_not_duplicated():
    generated = [
        {'main_question': 'Tell me about a time you rolled back a release.', 'competency': 'X'},
        {'main_question': 'Something else', 'competency': 'Y'},
    ]
    result = ir._with_custom_questions(generated, ['Tell me about a time you rolled back a release'])

    mains = [q['main_question'] for q in result]
    assert mains == ['Tell me about a time you rolled back a release', 'Something else']


def test_no_custom_questions_leaves_the_generated_list_untouched():
    generated = [{'main_question': 'A'}, {'main_question': 'B'}]
    assert ir._with_custom_questions(generated, []) is generated


def test_blank_custom_questions_are_ignored():
    result = ir._with_custom_questions([{'main_question': 'A'}], ['', '   '])
    assert [q['main_question'] for q in result] == ['A']
