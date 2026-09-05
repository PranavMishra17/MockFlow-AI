"""
The harness's own tests — the parts that need no API key.

Driving a real interview needs a real model, so those runs live behind
`python -m harness run` and are not part of `pytest -q`. What IS pinned here:
the scenario format, the expectation checker, and the fact that the harness
composes the production runtime rather than a copy of it.
"""

import json
from pathlib import Path

import pytest

from harness.__main__ import ExpectationFailed, _check

REPO_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = sorted((REPO_ROOT / 'scenarios').glob('*.json'))


def test_there_are_scenarios_for_every_track():
    tracks = set()
    for path in SCENARIOS:
        tracks.add(json.loads(path.read_text(encoding='utf-8'))['config']['track'])
    assert tracks == {'intro', 'behavioral', 'technical_voice', 'coding'}


@pytest.mark.parametrize('path', SCENARIOS, ids=lambda p: p.stem)
def test_scenario_parses_and_only_uses_known_steps(path):
    scenario = json.loads(path.read_text(encoding='utf-8'))
    assert 'config' in scenario, "a scenario needs a config"
    assert scenario['config'].get('track'), "a scenario needs a track"

    known = {'say', 'command', 'clock', 'expect'}
    for i, step in enumerate(scenario.get('script', []), 1):
        assert len(step) == 1, f"step {i} must be exactly one action, got {sorted(step)}"
        action = next(iter(step))
        assert action in known, f"step {i}: unknown action {action!r}"


@pytest.mark.parametrize('path', SCENARIOS, ids=lambda p: p.stem)
def test_scenario_config_survives_the_shared_parser(path):
    """A scenario must not be able to express a config the real transports cannot.

    `normalize_config` drops unknown keys, so a typo'd field would silently do
    nothing in the harness AND in production. Catching it here keeps a scenario
    from quietly testing a default.
    """
    import agent_mode

    raw = json.loads(path.read_text(encoding='utf-8'))['config']
    unknown = set(raw) - set(agent_mode.CONFIG_FIELDS)
    assert not unknown, f"config keys not in agent_mode.CONFIG_FIELDS: {sorted(unknown)}"


class _FakeSession:
    """Enough surface for the checker; not a substitute for a real run."""

    def __init__(self, stage='self_intro', tools=(), events=(), user=(), agent=()):
        self.stage = stage
        self.tool_calls = list(tools)
        self.transport = type('T', (), {'events': list(events)})()
        self._user = list(user)
        self._agent = list(agent)

    def emitted(self, type_name):
        return [e for e in self.transport.events if e.get('type') == type_name]

    def transcript(self):
        return {'user': self._user, 'agent': self._agent}


def test_stage_expectation_passes_and_fails():
    sess = _FakeSession(stage='past_experience')
    assert _check({'stage': 'past_experience'}, sess, 1)
    with pytest.raises(ExpectationFailed, match='expected stage'):
        _check({'stage': 'closing'}, sess, 1)


def test_tool_expectation_names_what_was_actually_called():
    sess = _FakeSession(tools=['ask_question'])
    assert _check({'tool_called': 'ask_question'}, sess, 1)
    with pytest.raises(ExpectationFailed, match="called: \\['ask_question'\\]"):
        _check({'tool_called': 'generate_interview_questions'}, sess, 1)


def test_emitted_expectation_names_what_was_actually_emitted():
    sess = _FakeSession(events=[{'type': 'stage_change', 'stage': 'closing'}])
    assert _check({'emitted': 'stage_change'}, sess, 1)
    with pytest.raises(ExpectationFailed, match="emitted: \\['stage_change'\\]"):
        _check({'emitted': 'question_skipped'}, sess, 1)


def test_user_turn_count_expectation():
    sess = _FakeSession(user=[{'text': 'a'}, {'text': 'b'}])
    assert _check({'user_turns': 2}, sess, 1)
    with pytest.raises(ExpectationFailed, match='expected 3 user turns, got 2'):
        _check({'user_turns': 3}, sess, 1)


def test_an_unknown_expectation_is_an_error_not_a_silent_pass():
    """A typo'd expectation that quietly passed would be worse than no test."""
    with pytest.raises(ExpectationFailed, match='unknown expectation'):
        _check({'staeg': 'closing'}, _FakeSession(), 1)


def test_the_harness_composes_the_production_runtime():
    """If this ever imports a local copy instead, the harness stops proving
    anything about what ships."""
    import inspect

    from harness import runtime

    src = inspect.getsource(runtime)
    for name in ('build_interview_state', 'build_session', 'attach_handlers',
                 'handle_command', 'collect_interview_data', 'InterviewAgent'):
        assert f'{name},' in src or f'{name}(' in src, f'{name} not used'
    assert 'from interview_runtime import' in src
