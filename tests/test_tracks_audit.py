"""
Multi-track audit: the 4 interview tracks (intro, behavioral, technical_voice,
coding) each get their own FSM stage machine (fsm.py), track config
(tracks/*.py), and agent prompt routing (prompts.py build_stage_instructions),
which together determine what the interviewer says and does. The evaluator
(evaluator.py) then grades from track-specific rubrics.

This file locks in track-parity: every track must behave consistently for the
same class of operation (stage lookup, skip validation, prompt routing) so a
bug fixed for one track (see tests/test_fsm_skip.py's technical_voice
regression) can't silently reappear for another.
"""

import pytest

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


# ---------------------------------------------------------------------------
# FSM parity: behavioral track (previously untested — technical_voice and
# intro had regression coverage in test_fsm_skip.py, behavioral did not)
# ---------------------------------------------------------------------------

def _behavioral(stage, question_count=2):
    s = BehavioralInterviewState()
    s.active_question_count = question_count
    s.stage = stage
    return s


def test_behavioral_get_stage_by_name_is_track_aware():
    s = _behavioral(BehavioralStage.BEHAVIORAL_Q1)
    assert s.get_stage_by_name("closing") == BehavioralStage.CLOSING
    assert s.get_stage_by_name("behavioral_q2") == BehavioralStage.BEHAVIORAL_Q2
    assert s.get_stage_by_name("nonsense") is None


def test_behavioral_skip_forward_does_not_raise():
    s = _behavioral(BehavioralStage.BEHAVIORAL_Q1)
    assert s.can_skip_to(BehavioralStage.CLOSING) is True


def test_behavioral_cannot_skip_backward():
    s = _behavioral(BehavioralStage.BEHAVIORAL_Q2)
    assert s.can_skip_to(BehavioralStage.SELF_INTRO) is False


def test_behavioral_foreign_track_stage_is_rejected_not_raised():
    s = _behavioral(BehavioralStage.BEHAVIORAL_Q1)
    assert s.can_skip_to(TechnicalVoiceStage.CLOSING) is False
    assert s.can_skip_to(InterviewStage.CLOSING) is False


def test_behavioral_active_stages_grow_with_question_count():
    two_q = _behavioral(BehavioralStage.GREETING, question_count=2)
    three_q = _behavioral(BehavioralStage.GREETING, question_count=3)
    assert BehavioralStage.BEHAVIORAL_Q3 not in two_q.get_active_stages()
    assert BehavioralStage.BEHAVIORAL_Q3 in three_q.get_active_stages()


def test_behavioral_cannot_skip_to_inactive_question_stage():
    # A 2-question session never activates BEHAVIORAL_Q3 — skipping to it
    # must be rejected, not silently accepted (it would strand the FSM).
    s = _behavioral(BehavioralStage.BEHAVIORAL_Q1, question_count=2)
    assert s.can_skip_to(BehavioralStage.BEHAVIORAL_Q3) is False


def test_behavioral_stage_time_limits_are_track_specific():
    s = _behavioral(BehavioralStage.BEHAVIORAL_Q1)
    assert s.get_stage_time_limit() == 300  # BEHAVIORAL_STAGE_TIME_LIMITS, not the 240s intro default


# ---------------------------------------------------------------------------
# FSM parity: coding track (previously untested)
# ---------------------------------------------------------------------------

def _coding(stage, problem_count=2):
    s = CodingInterviewState()
    s.active_problem_count = problem_count
    s.stage = stage
    return s


def test_coding_get_stage_by_name_is_track_aware():
    s = _coding(CodingStage.WARM_UP)
    assert s.get_stage_by_name("coding_problem_1") == CodingStage.CODING_PROBLEM_1
    assert s.get_stage_by_name("closing") == CodingStage.CLOSING
    assert s.get_stage_by_name("nonsense") is None


def test_coding_skip_forward_does_not_raise():
    s = _coding(CodingStage.WARM_UP)
    assert s.can_skip_to(CodingStage.CODING_PROBLEM_1) is True


def test_coding_cannot_skip_backward():
    s = _coding(CodingStage.CODING_PROBLEM_1)
    assert s.can_skip_to(CodingStage.WARM_UP) is False


def test_coding_foreign_track_stage_is_rejected_not_raised():
    s = _coding(CodingStage.WARM_UP)
    assert s.can_skip_to(BehavioralStage.CLOSING) is False
    assert s.can_skip_to(InterviewStage.CLOSING) is False


def test_coding_active_stages_shrink_for_single_problem_session():
    one_problem = _coding(CodingStage.GREETING, problem_count=1)
    two_problems = _coding(CodingStage.GREETING, problem_count=2)
    assert CodingStage.CODING_PROBLEM_2 not in one_problem.get_active_stages()
    assert CodingStage.CODING_PROBLEM_2 in two_problems.get_active_stages()


def test_coding_cannot_skip_to_inactive_second_problem():
    s = _coding(CodingStage.CODING_PROBLEM_1, problem_count=1)
    assert s.can_skip_to(CodingStage.CODING_PROBLEM_2) is False


def test_coding_stage_time_limits_are_track_specific():
    s = _coding(CodingStage.CODING_PROBLEM_1)
    assert s.get_stage_time_limit() == 900  # 15-minute problem window


def test_coding_record_submission_tracks_attempts_per_problem():
    s = CodingInterviewState()
    assert s.get_attempts_for_problem(0) == 0
    first = s.record_submission(0, "print(1)", "python", {"passed": True})
    second = s.record_submission(0, "print(2)", "python", {"passed": True})
    assert (first, second) == (1, 2)
    assert s.get_attempts_for_problem(0) == 2
    assert s.get_attempts_for_problem(1) == 0  # independent per problem


# ---------------------------------------------------------------------------
# Document-context stage-gating: each track injects resume/JD only at its own
# designated stage(s) — wrong-stage leakage would confuse the interviewer.
# ---------------------------------------------------------------------------

def test_intro_document_context_only_at_designated_stages():
    s = InterviewState(uploaded_resume_text="RESUME TEXT", job_description="JD TEXT")
    assert "RESUME" in s.get_document_context(stage=InterviewStage.PAST_EXPERIENCE)
    assert "JD" not in s.get_document_context(stage=InterviewStage.PAST_EXPERIENCE)
    assert "JD" in s.get_document_context(stage=InterviewStage.COMPANY_FIT)
    assert s.get_document_context(stage=InterviewStage.SELF_INTRO) == ""


def test_behavioral_document_context_only_at_question_stages():
    s = BehavioralInterviewState(uploaded_resume_text="RESUME TEXT", job_description="JD TEXT")
    assert s.get_document_context(stage=BehavioralStage.GREETING) == ""
    assert "RESUME" in s.get_document_context(stage=BehavioralStage.BEHAVIORAL_Q1)


def test_coding_document_context_only_at_warm_up():
    s = CodingInterviewState(uploaded_resume_text="RESUME TEXT")
    assert "RESUME" in s.get_document_context(stage=CodingStage.WARM_UP)
    assert s.get_document_context(stage=CodingStage.CODING_PROBLEM_1) == ""


# ---------------------------------------------------------------------------
# Track config factory (tracks/base.py): resolves each track's stage enum,
# timers, and falls back safely (not a crash) for an unknown track name.
# ---------------------------------------------------------------------------

def test_get_track_config_resolves_all_four_tracks():
    from tracks.base import get_track_config

    for track_type, stage_enum in (
        ("intro", InterviewStage),
        ("behavioral", BehavioralStage),
        ("technical_voice", TechnicalVoiceStage),
        ("coding", CodingStage),
    ):
        cfg = get_track_config(track_type)
        assert cfg.track_type == track_type
        assert cfg.stage_enum is stage_enum
        assert cfg.full_stage_sequence  # non-empty


def test_get_track_config_unknown_track_falls_back_to_intro_not_crash():
    from tracks.base import get_track_config

    cfg = get_track_config("some_future_track_nobody_wired_yet")
    assert cfg.track_type == "intro"


# ---------------------------------------------------------------------------
# Prompt routing (prompts.py build_stage_instructions): every reachable stage
# across all 4 tracks must resolve to non-empty instructions. A routing miss
# here means the agent goes SILENT at that stage in a live interview — the
# worst possible failure mode, and one with no other test coverage.
# ---------------------------------------------------------------------------

ALL_TRACK_STAGES = (
    [(InterviewStage, s) for s in InterviewStage]
    + [(BehavioralStage, s) for s in BehavioralStage]
    + [(TechnicalVoiceStage, s) for s in TechnicalVoiceStage]
    + [(CodingStage, s) for s in CodingStage]
)


@pytest.mark.parametrize("enum_cls,stage", ALL_TRACK_STAGES, ids=[s.value for _, s in ALL_TRACK_STAGES])
def test_build_stage_instructions_never_empty(enum_cls, stage):
    from prompts import build_stage_instructions

    instructions = build_stage_instructions(stage)
    assert instructions and instructions.strip(), (
        f"{enum_cls.__name__}.{stage.name} routed to empty instructions — "
        "the agent would go silent at this stage"
    )


# ---------------------------------------------------------------------------
# POST /api/skip-stage used to exist and skipped nothing. It validated the
# stage name, logged, and returned {"success": true} — while the actual skip
# travelled over the LiveKit data channel (templates/interview.html). Nothing
# ever called it. An endpoint that reports success for work it did not do is
# worse than no endpoint: the next person to find it will believe it.
# ---------------------------------------------------------------------------

def test_the_no_op_skip_stage_endpoint_is_gone(client):
    """Deleted deliberately. Do not reinstate it as a validation stub —
    mid-session commands reach the agent over the data channel, and there is no
    HTTP path to a running interview."""
    resp = client.post("/api/skip-stage",
                       json={"room_name": "interview-demo", "target_stage": "behavioral_q1"})
    assert resp.status_code == 404
