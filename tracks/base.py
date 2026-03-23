import logging
from dataclasses import dataclass, field
from typing import Any, List

logger = logging.getLogger(__name__)

@dataclass
class TrackConfig:
    track_type: str                    # 'intro'|'behavioral'|'technical_voice'|'coding'
    display_name: str                  # Human-readable name
    stage_enum: type                   # The Enum class for this track
    full_stage_sequence: list          # All possible stages in order
    time_limits: dict                  # stage -> seconds
    min_questions: dict                # stage_value_string -> int
    welcome_audio_file: str            # path e.g. 'static/audio/welcome_behavioral.mp3'
    first_real_stage: Any              # Stage to jump to on skip-intro
    is_available: bool = True          # False for placeholder tracks (coding)

def get_track_config(track_type: str) -> TrackConfig:
    """Factory: returns TrackConfig for the given track type string."""
    from tracks.intro import INTRO_TRACK_CONFIG
    from tracks.behavioral import BEHAVIORAL_TRACK_CONFIG
    from tracks.technical_voice import TECHNICAL_VOICE_TRACK_CONFIG
    from tracks.technical_coding import CODING_TRACK_CONFIG

    configs = {
        'intro': INTRO_TRACK_CONFIG,
        'behavioral': BEHAVIORAL_TRACK_CONFIG,
        'technical_voice': TECHNICAL_VOICE_TRACK_CONFIG,
        'coding': CODING_TRACK_CONFIG,
    }
    config = configs.get(track_type)
    if config is None:
        logger.warning(f"[TRACKS] Unknown track type '{track_type}', defaulting to intro")
        return INTRO_TRACK_CONFIG
    logger.info(f"[TRACKS] Loaded config for track: {track_type}")
    return config
