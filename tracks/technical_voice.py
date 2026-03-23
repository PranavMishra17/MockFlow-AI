from tracks.base import TrackConfig
from fsm import TechnicalVoiceStage, TECHNICAL_VOICE_STAGE_TIME_LIMITS, TECHNICAL_VOICE_STAGE_MIN_QUESTIONS

TECHNICAL_VOICE_TRACK_CONFIG = TrackConfig(
    track_type='technical_voice',
    display_name='Technical Voice Interview',
    stage_enum=TechnicalVoiceStage,
    full_stage_sequence=[
        TechnicalVoiceStage.GREETING,
        TechnicalVoiceStage.SELF_INTRO,
        TechnicalVoiceStage.EXPERIENCE_DISCUSSION,
        TechnicalVoiceStage.TECHNICAL_CONCEPTS_1,
        TechnicalVoiceStage.TECHNICAL_CONCEPTS_2,
        TechnicalVoiceStage.TECHNICAL_CONCEPTS_3,
        TechnicalVoiceStage.CLOSING
    ],
    time_limits=TECHNICAL_VOICE_STAGE_TIME_LIMITS,
    min_questions=TECHNICAL_VOICE_STAGE_MIN_QUESTIONS,
    welcome_audio_file='static/audio/welcome_technical_voice.mp3',
    first_real_stage=TechnicalVoiceStage.EXPERIENCE_DISCUSSION,
    is_available=True
)
