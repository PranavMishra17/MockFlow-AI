"""
Stage skipping must be TRACK-AWARE. Regression test for the production crash:
  ValueError: TechnicalVoiceStage.EXPERIENCE_DISCUSSION is not in list
caused by can_skip_to / get_stage_by_name hardcoding the intro track's stages.
"""

import pytest

from fsm import (
    InterviewStage,
    InterviewState,
    TechnicalVoiceInterviewState,
    TechnicalVoiceStage,
)


def _tv(stage):
    s = TechnicalVoiceInterviewState()
    s.stage = stage
    return s


def test_get_stage_by_name_is_track_aware():
    s = _tv(TechnicalVoiceStage.EXPERIENCE_DISCUSSION)
    assert s.get_stage_by_name("closing") == TechnicalVoiceStage.CLOSING
    assert s.get_stage_by_name("experience_discussion") == TechnicalVoiceStage.EXPERIENCE_DISCUSSION
    assert s.get_stage_by_name("nonsense") is None


def test_skip_forward_in_technical_track_does_not_raise():
    s = _tv(TechnicalVoiceStage.EXPERIENCE_DISCUSSION)
    # This used to raise ValueError (not in the hardcoded intro list).
    assert s.can_skip_to(TechnicalVoiceStage.CLOSING) is True


def test_cannot_skip_backward():
    s = _tv(TechnicalVoiceStage.EXPERIENCE_DISCUSSION)
    assert s.can_skip_to(TechnicalVoiceStage.GREETING) is False


def test_foreign_track_stage_is_rejected_not_raised():
    s = _tv(TechnicalVoiceStage.EXPERIENCE_DISCUSSION)
    # An intro-enum target on a technical state must return False, never raise.
    assert s.can_skip_to(InterviewStage.CLOSING) is False


def test_intro_track_still_works():
    s = InterviewState()
    s.stage = InterviewStage.SELF_INTRO
    assert s.get_stage_by_name("company_fit") == InterviewStage.COMPANY_FIT
    assert s.can_skip_to(InterviewStage.CLOSING) is True
    assert s.can_skip_to(InterviewStage.WELCOME) is False
