from tracks.base import TrackConfig
from fsm import BehavioralStage, BEHAVIORAL_STAGE_TIME_LIMITS, BEHAVIORAL_STAGE_MIN_QUESTIONS

BEHAVIORAL_TRACK_CONFIG = TrackConfig(
    track_type='behavioral',
    display_name='Behavioral Interview',
    stage_enum=BehavioralStage,
    full_stage_sequence=[
        BehavioralStage.GREETING,
        BehavioralStage.SELF_INTRO,
        BehavioralStage.BEHAVIORAL_Q1,
        BehavioralStage.BEHAVIORAL_Q2,
        BehavioralStage.BEHAVIORAL_Q3,
        BehavioralStage.CLOSING
    ],
    time_limits=BEHAVIORAL_STAGE_TIME_LIMITS,
    min_questions=BEHAVIORAL_STAGE_MIN_QUESTIONS,
    welcome_audio_file='static/audio/welcome_behavioral.mp3',
    first_real_stage=BehavioralStage.BEHAVIORAL_Q1,
    is_available=True
)
