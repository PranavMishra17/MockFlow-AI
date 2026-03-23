"""
Technical Coding Interview Track Configuration

Provides problem-solving interviews with Monaco editor, code evaluation,
per-problem timers, and retry logic.
"""

from tracks.base import TrackConfig
from fsm import CodingStage, CODING_STAGE_TIME_LIMITS, CODING_STAGE_MIN_QUESTIONS

CODING_TRACK_CONFIG = TrackConfig(
    track_type='coding',
    display_name='Technical Coding Interview',
    stage_enum=CodingStage,
    full_stage_sequence=[
        CodingStage.GREETING,
        CodingStage.SELF_INTRO,
        CodingStage.WARM_UP,
        CodingStage.CODING_PROBLEM_1,
        CodingStage.CODING_PROBLEM_2,
        CodingStage.CLOSING,
    ],
    time_limits=CODING_STAGE_TIME_LIMITS,
    min_questions=CODING_STAGE_MIN_QUESTIONS,
    welcome_audio_file='static/audio/welcome_coding.mp3',
    first_real_stage=CodingStage.WARM_UP,
    is_available=True,
)
