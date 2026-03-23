from tracks.base import TrackConfig
from fsm import InterviewStage, STAGE_TIME_LIMITS, STAGE_MIN_QUESTIONS

INTRO_TRACK_CONFIG = TrackConfig(
    track_type='intro',
    display_name='Intro Call',
    stage_enum=InterviewStage,
    full_stage_sequence=[
        InterviewStage.WELCOME,
        InterviewStage.SELF_INTRO,
        InterviewStage.PAST_EXPERIENCE,
        InterviewStage.COMPANY_FIT,
        InterviewStage.CLOSING
    ],
    time_limits=STAGE_TIME_LIMITS,
    min_questions=STAGE_MIN_QUESTIONS,
    welcome_audio_file='static/audio/welcome_intro.mp3',
    first_real_stage=InterviewStage.PAST_EXPERIENCE,
    is_available=True
)
