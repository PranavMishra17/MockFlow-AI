"""
The coding track's command path after the redesign.

Audit findings covered: "I'm Ready" honoured in any stage (problem pushed
during the greeting, then re-read later); one submission evaluated twice
(tool + command); the interview closing with a problem still open; three
429s turning into no evaluation_result and an editor stuck on "Evaluating";
LLM-only grading presented as if the code had run.
"""

import asyncio
import json
import types

import pytest

import interview_runtime as ir
import interview_turn as it


class _Completions:
    def __init__(self, fail_times=0, correctness='pass'):
        self.calls = 0
        self.fail_times = fail_times
        self.correctness = correctness

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("429 rate limit")
        content = json.dumps({'brief_verbal_feedback': 'Works.', 'correctness': self.correctness, 'approach_quality': 'A'})
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])


class _Client:
    completions = None

    def __init__(self, api_key=None):
        self.chat = types.SimpleNamespace(completions=_Client.completions)


async def _no_sleep(_):
    return None


@pytest.fixture
def fake_openai(monkeypatch):
    def install(fail_times=0, correctness='pass'):
        _Client.completions = _Completions(fail_times, correctness)
        monkeypatch.setattr('openai.AsyncOpenAI', _Client)
        monkeypatch.setattr(ir.asyncio, 'sleep', _no_sleep)   # retries back off; tests do not wait
        return _Client.completions
    return install


class StubSession:
    def __init__(self):
        self.said = []
        self.generated = []

    async def say(self, text, allow_interruptions=True):
        self.said.append(text)

    def generate_reply(self, **kw):
        self.generated.append(kw)


def _ctx(problems=2):
    state = ir.build_interview_state({'track': 'coding', 'role': 'SWE', 'level': 'mid', 'user_id': 'u',
                                      'preferred_language': 'python', 'problem_count': str(problems)})
    state.generated_problems = [{'title': 'Two Sum', 'description': 'd', 'examples': [], 'constraints': []},
                                {'title': 'Valid Parentheses', 'description': 'd', 'examples': [], 'constraints': []}][:problems]
    state.active_problem_count = problems
    transport = ir.NullTransport()
    agent = ir.InterviewAgent(transport=transport, candidate_info={'name': 'Marcus Lee', 'role': 'SWE'}, track_type='coding',
                              assess=lambda inp: None)
    return ir.CommandContext(session=StubSession(), state=state, agent=agent, transport=transport, track_config=None)


def cmd(ctx, payload):
    return asyncio.run(ir.handle_command(payload, ctx))


def test_ready_before_the_problems_starts_problem_one_and_says_so():
    ctx = _ctx()
    assert ctx.state.stage.value == 'self_intro'
    cmd(ctx, {'type': 'ready_for_problem'})
    assert ctx.state.stage.value == 'coding_problem_1'
    pushed = ctx.transport.of_type('coding_problem')
    assert len(pushed) == 1 and pushed[0]['problem']['title'] == 'Two Sum'
    assert ctx.session.said and 'Two Sum' in ctx.session.said[0]


def test_ready_during_a_problem_only_repushes_it():
    ctx = _ctx()
    cmd(ctx, {'type': 'ready_for_problem'})
    cmd(ctx, {'type': 'ready_for_problem'})
    assert ctx.state.stage.value == 'coding_problem_1'
    assert [p['problem_index'] for p in ctx.transport.of_type('coding_problem')] == [0, 0]
    assert len(ctx.session.said) == 1


def test_ready_after_closing_is_ignored():
    ctx = _ctx()
    ctx.state.transition_to(ctx.state.get_stage_by_name('closing'))
    cmd(ctx, {'type': 'ready_for_problem'})
    assert ctx.transport.of_type('coding_problem') == []


def test_one_submission_is_evaluated_exactly_once_and_a_pass_advances(fake_openai):
    completions = fake_openai(correctness='pass')
    ctx = _ctx()
    cmd(ctx, {'type': 'ready_for_problem'})
    cmd(ctx, {'type': 'code_submitted', 'code': 'def two_sum(): ...', 'language': 'python', 'problem_index': 0})
    assert completions.calls == 1
    results = ctx.transport.of_type('evaluation_result')
    assert len(results) == 1 and results[0]['executed'] is False
    assert ctx.state.stage.value == 'coding_problem_2'
    assert [p['problem_index'] for p in ctx.transport.of_type('coding_problem')] == [0, 1]


def test_a_failed_attempt_stays_on_the_problem_until_the_third(fake_openai):
    fake_openai(correctness='fail')
    ctx = _ctx()
    cmd(ctx, {'type': 'ready_for_problem'})
    for n in range(1, 4):
        cmd(ctx, {'type': 'code_submitted', 'code': f'attempt {n}', 'language': 'python', 'problem_index': 0})
        if n < 3:
            assert ctx.state.stage.value == 'coding_problem_1', n
    assert ctx.state.stage.value == 'coding_problem_2'
    assert 'last attempt' in ' '.join(ctx.session.said).lower()


def test_closing_only_after_the_last_problem_is_resolved(fake_openai):
    fake_openai(correctness='pass')
    ctx = _ctx()
    cmd(ctx, {'type': 'ready_for_problem'})
    cmd(ctx, {'type': 'code_submitted', 'code': 'a', 'language': 'python', 'problem_index': 0})
    assert ctx.state.stage.value == 'coding_problem_2'      # not closing: a problem is open
    cmd(ctx, {'type': 'skip_coding_problem'})
    assert ctx.state.stage.value == 'closing'
    assert ctx.session.said[-1].endswith(it.CLOSING_SENTINEL)


def test_evaluator_outage_emits_evaluation_error_not_silence(fake_openai):
    completions = fake_openai(fail_times=10)
    ctx = _ctx()
    cmd(ctx, {'type': 'ready_for_problem'})
    cmd(ctx, {'type': 'code_submitted', 'code': 'a', 'language': 'python', 'problem_index': 0})
    assert completions.calls == 4                              # 1 try + 3 retries
    assert ctx.transport.of_type('evaluation_result') == []
    errs = ctx.transport.of_type('evaluation_error')
    assert len(errs) == 1 and errs[0]['problem_index'] == 0
    assert ctx.state.stage.value == 'coding_problem_1'         # nothing advanced on a failure to evaluate


def test_transient_429_is_retried_and_succeeds(fake_openai):
    completions = fake_openai(fail_times=2)
    ctx = _ctx()
    cmd(ctx, {'type': 'ready_for_problem'})
    cmd(ctx, {'type': 'code_submitted', 'code': 'a', 'language': 'python', 'problem_index': 0})
    assert completions.calls == 3
    assert len(ctx.transport.of_type('evaluation_result')) == 1


def test_grader_prompt_makes_contract_violations_a_fail():
    from prompts import CODE_EVALUATOR
    assert 'return contract' in CODE_EVALUATOR.system
    assert 'grade it fail, not partial' in CODE_EVALUATOR.system
