"""
Differential test: agent_mode.normalize_config vs the ORIGINAL inline parser.

The claim this file exists to make reproducible: interview config parses
IDENTICALLY whether it arrives as LiveKit participant attributes (direct mode)
or job metadata (dispatch mode), because both funnel through one parser that
behaves exactly like the inline block that used to live in
`agent_worker.run_interview()`.

That claim was previously supported by a throwaway script that lived outside the
repo, so nobody could re-run it — and its sample values were all clean strings,
so it missed that `" true"` and `"true"` must parse DIFFERENTLY (the legacy rule
did not strip). Both problems are fixed here: the sweep is committed, and the
value space includes whitespace-padded, empty and separator-only inputs.

`legacy_parse` below is transcribed verbatim from `git show main:agent_worker.py`
and must not be "cleaned up" — its warts are the specification.
"""

import itertools

import pytest

import agent_mode as am


def legacy_parse(attrs):
    """Verbatim copy of the original inline parser. Do not tidy."""
    role = 'this position'
    level = 'mid'
    email = ''
    resume_text = None
    job_description = None
    include_profile = True
    user_id = None
    track_type = 'intro'
    framework = 'amazon'
    depth = 'medium'
    custom_questions = []
    topics = []
    custom_topics = []

    if attrs:
        role = attrs.get('role', 'this position')
        level = attrs.get('level', 'mid')
        email = attrs.get('email', '')
        resume_text = attrs.get('resume_text')
        job_description = attrs.get('job_description')
        include_profile = attrs.get('include_profile', 'true').lower() == 'true'
        user_id = attrs.get('user_id')
        track_type = attrs.get('track', 'intro')
        framework = attrs.get('framework', 'amazon')
        depth = attrs.get('depth', 'medium')
        cq = attrs.get('custom_questions', '')
        custom_questions = [q.strip() for q in cq.split('\n') if q.strip()] if cq else []
        tp = attrs.get('topics', '')
        topics = [t.strip() for t in tp.split(',') if t.strip()] if tp else []
        ct = attrs.get('custom_topics', '')
        custom_topics = [t.strip() for t in ct.split(',') if t.strip()] if ct else []

    return {
        'role': role, 'level': level, 'email': email,
        'resume_text': resume_text, 'job_description': job_description,
        'include_profile': include_profile, 'user_id': user_id,
        'track': track_type, 'framework': framework, 'depth': depth,
        'custom_questions': custom_questions, 'topics': topics,
        'custom_topics': custom_topics,
    }


# Deliberately includes the awkward inputs: whitespace padding, empty strings,
# separator-only values. These are where the two parsers can silently diverge.
VALUE_SPACE = {
    'include_profile': ['true', 'false', 'TRUE', 'False', '', ' true', 'true ', 'True\n'],
    'custom_questions': ['', 'Q one\nQ two', '  \n ', 'only one', '\n'],
    'topics': ['', 'kafka, redis', ' , , ', 'solo', ','],
    'custom_topics': ['', 'graphs,,tries', '  '],
    'role': ['Backend Engineer', '', '  '],
    'level': ['senior', ''],
}


def _all_combinations():
    keys = list(VALUE_SPACE)
    for combo in itertools.product(*(VALUE_SPACE[k] for k in keys)):
        yield dict(zip(keys, combo))


def test_parsers_agree_across_the_whole_value_space():
    """Exhaustive sweep. Any mismatch means direct and dispatch would differ."""
    mismatches = []
    checked = 0
    for attrs in _all_combinations():
        checked += 1
        old, new = legacy_parse(attrs), am.normalize_config(attrs)
        if old != new:
            mismatches.append((attrs, {k: (old[k], new[k]) for k in old if old[k] != new[k]}))

    assert checked > 2000, f"sweep collapsed to {checked} cases"
    assert not mismatches, (
        f"{len(mismatches)} of {checked} diverged; first 3: {mismatches[:3]}"
    )


@pytest.mark.parametrize("empty", [{}, None])
def test_parsers_agree_when_no_attributes_were_published(empty):
    assert legacy_parse(empty) == am.normalize_config(empty)


def test_the_sweep_would_actually_catch_a_regression():
    """Guard the guard: a parser that strips include_profile must be rejected.

    Without this, a future 'cleanup' that adds .strip() could pass unnoticed if
    the value space ever loses its whitespace entries.
    """
    padded = {'include_profile': ' true'}
    assert legacy_parse(padded)['include_profile'] is False
    assert am.normalize_config(padded)['include_profile'] is False
