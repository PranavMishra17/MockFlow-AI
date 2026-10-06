import json

import interview_runtime as ir
from coding import get_problem


def _coding_state():
    state = ir.build_interview_state({'track': 'coding', 'role': 'SWE', 'level': 'mid', 'user_id': 'u',
                                      'preferred_language': 'python', 'problem_count': '2'})
    state.generated_problems = [get_problem('two-sum'), get_problem('merge-intervals')]
    state.record_submission(0, 'def two_sum(n, t): return []', 'python',
                            {'correctness': 'fail', 'approach_quality': 'C', 'executed': False})
    state.record_submission(0, 'def two_sum(n, t): ...', 'python',
                            {'correctness': 'pass', 'approach_quality': 'A', 'executed': False})
    return state


def test_saving_a_coding_interview_writes_its_submissions_where_the_verdict_reads():
    import db as db_module

    client = db_module.DB.__new__(db_module.DB)
    calls = []

    def fetchone(sql, params):
        calls.append((sql, params))
        return {'id': '00000000-0000-0000-0000-0000000000aa'}

    client._fetchone = fetchone
    row = ir.collect_interview_data(_coding_state(), {'agent': [], 'user': []}, room_name='r', ended_by='x')
    assert client.save_interview('user-1', row) == '00000000-0000-0000-0000-0000000000aa'

    subs = [p for sql, p in calls if 'INSERT INTO coding_submissions' in sql]
    assert len(subs) == 2
    user_id, interview_id, title, _desc, language, code, attempt, evaluation, _t = subs[1]
    assert (user_id, interview_id, title, language, attempt) == (
        'user-1', '00000000-0000-0000-0000-0000000000aa', 'Two Sum', 'python', 2)
    assert code == 'def two_sum(n, t): ...'
    assert evaluation.obj['correctness'] == 'pass'


def test_verdict_input_carries_the_evaluators_own_keys(auth_client, app_module, db_client, monkeypatch):
    import openai

    sent = {}

    class _FakeOpenAI:
        def __init__(self, **kw):
            self.chat = self
            self.completions = self

        def create(self, **kw):
            sent.update(kw)
            msg = type('M', (), {'content': json.dumps({'overall': {}, 'signals': []})})
            return type('R', (), {'choices': [type('C', (), {'message': msg})]})

    ctx = ("CANDIDATE: hi", "Name: T", "Role: SWE",
           {"candidate": "T", "track": "coding", "job_role": "Software Engineer", "experience_level": "mid"},
           [], {}, None)
    monkeypatch.setattr(app_module, "_load_interview_context", lambda iid: ctx)
    monkeypatch.setattr(app_module, "resolve_openai_key", lambda uid: "sk-test")
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(db_client, "save_feedback", lambda *a, **k: True)
    monkeypatch.setattr(db_client, "save_interview_scores", lambda **k: True)
    monkeypatch.setattr(db_client, "get_coding_submissions", lambda iid: [{
        'problem_title': 'Two Sum', 'language': 'python', 'attempt_number': 2,
        'evaluation_result': {'correctness': 'fail', 'approach_quality': 'C', 'time_complexity': 'O(n^2)',
                              'executed': True, 'objective_tests': '2/4 hidden test cases passed'},
    }])

    resp = auth_client.post("/api/feedback/verdict", json={"interview_id": "00000000-0000-0000-0000-000000000abc"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    user = sent['messages'][-1]['content']
    block = user.split('<CODING_RESULTS>')[1].split('</CODING_RESULTS>')[0]
    assert 'Two Sum' in block and 'attempt 2' in block
    assert 'correctness=fail' in block and 'approach=C' in block and 'O(n^2)' in block
    assert '2/4 hidden test cases passed' in block
    assert '?' not in block


def test_the_recorded_evaluation_keeps_its_execution_provenance(monkeypatch):
    import asyncio
    import types

    import coding.piston_runner as pr

    class _Completions:
        async def create(self, **kw):
            content = json.dumps({'correctness': 'partial', 'approach_quality': 'B', 'brief_verbal_feedback': 'ok'})
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])

    class _Client:
        def __init__(self, api_key=None):
            self.chat = types.SimpleNamespace(completions=_Completions())

    monkeypatch.setattr('openai.AsyncOpenAI', _Client)
    monkeypatch.setattr(pr, 'PISTON_ENABLED', False)
    state = _coding_state()
    state.submissions.clear()
    state.submissions_per_problem.clear()
    transport = ir.NullTransport()
    asyncio.run(ir._evaluate_code_async(None, None, state, transport, 0, 'def two_sum(n, t): ...', 'python'))
    evaluation = state.submissions[0]['evaluation']
    assert evaluation['executed'] is False
    assert evaluation['not_executed_reason']
