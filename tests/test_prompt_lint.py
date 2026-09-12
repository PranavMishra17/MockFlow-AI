"""
Lint for everything Flow could be told before it speaks.

Two of the audit's findings were prompt bugs a linter would have caught: a
literal "[TOPIC_2]" spoken aloud (a placeholder nobody substituted) and a
closing script that promised "next steps via email". This resolves every
stage's instructions the way the runtime does — with a real state, name,
role, topics and question bank — and checks what comes out.
"""

import re

import pytest

import interview_runtime as ir
from fsm import BehavioralStage, CodingStage, InterviewStage, TechnicalVoiceStage
from prompts import GLOBAL_STYLE, MOVE_PROTOCOL, build_stage_instructions, get_greeting_line

# Words Flow must never be instructed to say. The list mirrors GLOBAL_STYLE's
# own ban list, so a stage block quoting a banned word as a positive example
# ("say something like 'Great!'") is caught.
BANNED_INSTRUCTED = re.compile(
    r"\b(we'll be in touch|next steps|via email|use their name naturally|say something like:? \"great)",
    re.I,
)
PLACEHOLDER = re.compile(r"\[(?!FLOW MOVE)[A-Z_ ]{3,}\]|\{[a-z_]+\}")

_CONFIGS = {
    'intro': {'track': 'intro', 'role': 'Backend Engineer', 'level': 'mid'},
    'behavioral': {'track': 'behavioral', 'role': 'Backend Engineer', 'level': 'senior', 'framework': 'amazon', 'depth': 'medium'},
    'technical_voice': {'track': 'technical_voice', 'role': 'Backend Engineer', 'level': 'mid', 'topics': 'caching,databases'},
    'coding': {'track': 'coding', 'role': 'Software Engineer', 'level': 'junior', 'preferred_language': 'python', 'problem_count': '2'},
}


def _resolved(track):
    state = ir.build_interview_state(dict(_CONFIGS[track], user_id='u'), candidate_name='Priya Raman')
    if track == 'behavioral':
        state.generated_questions = [
            {'main_question': 'Tell me about a time you dove deep.', 'competency': 'Dive Deep', 'follow_up_probes': ['What did you find?']},
            {'main_question': 'Tell me about a disagreement.', 'competency': 'Earn Trust', 'follow_up_probes': []},
            {'main_question': 'Tell me about ownership.', 'competency': 'Ownership', 'follow_up_probes': []},
        ]
        state.active_question_count = 3
    if track == 'technical_voice':
        state.generated_questions = [{'topic': 'caching', 'questions': ['How does an LRU cache work?']},
                                     {'topic': 'databases', 'questions': ['When would you denormalise?']}]
    if track == 'coding':
        state.generated_problems = [{'title': 'Two Sum', 'description': 'd', 'examples': [], 'constraints': []},
                                    {'title': 'Valid Parentheses', 'description': 'd', 'examples': [], 'constraints': []}]
    agent = ir.InterviewAgent(transport=ir.NullTransport(), candidate_info={'name': 'Priya Raman', 'role': 'Backend Engineer'},
                              track_type=track, assess=None)
    return [(stage, agent._get_stage_instructions(state, stage)) for stage in state.get_active_stages()]


ALL = [(t, stage, text) for t in _CONFIGS for stage, text in _resolved(t)]


@pytest.mark.parametrize("track,stage,text", ALL, ids=[f"{t}:{s.value}" for t, s, _ in ALL])
def test_resolved_instructions_have_no_placeholders_no_banned_lines_and_fit_the_budget(track, stage, text):
    leftover = PLACEHOLDER.findall(text)
    assert not leftover, f"unreplaced placeholders {leftover} in {track}:{stage.value}"
    # GLOBAL_STYLE names the banned phrases in order to ban them; lint the
    # part that could instruct Flow to say them, i.e. everything else.
    instructing = text.replace(GLOBAL_STYLE, "").replace(MOVE_PROTOCOL, "")
    banned = BANNED_INSTRUCTED.findall(instructing)
    assert not banned, f"instructed to say {banned!r} in {track}:{stage.value}"
    assert 'assess_response' not in text and 'ask_question' not in text and 'transition_stage' not in text
    tokens = len(text) / 4
    assert tokens < 700, f"{track}:{stage.value} is ~{tokens:.0f} tokens; keep stage prompts small"
    assert GLOBAL_STYLE.strip()[:40] in text and MOVE_PROTOCOL.strip()[:20] in text


def test_full_name_is_never_in_the_instructions_as_something_to_say():
    for track, stage, text in ALL:
        assert 'Priya Raman' not in text, f"{track}:{stage.value} carries the full name"
        assert 'do not say the name' in text


def test_greeting_lines_are_one_sentence_each_and_name_flow():
    for track in _CONFIGS:
        line = get_greeting_line(track)
        assert line.startswith("Hey, I'm Flow")
        assert line.count('.') <= 2 and len(line.split()) <= 26
        assert 'stage' not in line.lower()


def test_undriven_stages_are_rejected_loudly():
    with pytest.raises(ValueError):
        build_stage_instructions(InterviewStage.WELCOME)
    with pytest.raises(ValueError):
        build_stage_instructions(BehavioralStage.GREETING)
    with pytest.raises(ValueError):
        build_stage_instructions(TechnicalVoiceStage.GREETING)
    with pytest.raises(ValueError):
        build_stage_instructions(CodingStage.GREETING)
