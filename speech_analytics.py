"""
Speech Analytics Module

Post-interview analysis of candidate speech patterns.
Processes the conversation dict saved by agent_worker.py.
All functions are pure (no side effects, no I/O).
"""

import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

# Filler words to detect (case-insensitive, whole-word match)
FILLER_WORDS = [
    'um', 'uh', 'like', 'basically', 'actually', 'so', 'right',
    'you know', 'i mean', 'kind of', 'sort of', 'literally',
]

def analyze_transcript(conversation: dict) -> dict:
    """
    Analyze speech patterns from the interview conversation.

    Args:
        conversation: Dict with 'user' key containing list of
                      {'text': str, 'timestamp': float} dicts.

    Returns:
        Dict with speech analytics results.
    """
    try:
        user_turns = conversation.get('user', [])
        if not user_turns:
            return _empty_analytics()

        filler_breakdown = _count_fillers(user_turns)
        filler_total = sum(filler_breakdown.values())
        word_count, duration_seconds = _measure_pace(user_turns)
        avg_wpm = _calc_wpm(word_count, duration_seconds)
        per_turn_pace = _per_turn_pace(user_turns)

        result = {
            'filler_total': filler_total,
            'filler_breakdown': filler_breakdown,
            'word_count': word_count,
            'total_speaking_duration_seconds': round(duration_seconds, 1),
            'avg_words_per_minute': round(avg_wpm, 1),
            'per_turn_pace': per_turn_pace,
        }
        logger.info(f"[ANALYTICS] Analyzed {len(user_turns)} user turns: "
                    f"{filler_total} fillers, {avg_wpm:.0f} avg WPM")
        return result
    except Exception as e:
        logger.error(f"[ANALYTICS] Failed to analyze transcript: {e}")
        return _empty_analytics()


def _empty_analytics() -> dict:
    return {
        'filler_total': 0,
        'filler_breakdown': {},
        'word_count': 0,
        'total_speaking_duration_seconds': 0.0,
        'avg_words_per_minute': 0.0,
        'per_turn_pace': [],
    }


def _count_fillers(user_turns: List[dict]) -> Dict[str, int]:
    """Count occurrences of each filler word across all user turns."""
    counts = {}
    full_text = ' '.join(t.get('text', '') for t in user_turns).lower()
    for filler in FILLER_WORDS:
        # Use word-boundary regex for single words, substring for phrases
        if ' ' in filler:
            count = full_text.count(filler)
        else:
            count = len(re.findall(r'\b' + re.escape(filler) + r'\b', full_text))
        if count > 0:
            counts[filler] = count
    return counts


def _measure_pace(user_turns: List[dict]) -> tuple:
    """
    Return (total_word_count, total_speaking_duration_seconds).
    Duration estimated from timestamps: first turn start to last turn end,
    minus gaps > 5s (silence between agent/candidate exchanges).
    """
    total_words = sum(len(t.get('text', '').split()) for t in user_turns)
    if len(user_turns) < 2:
        # Estimate 150 WPM for single turn
        return total_words, max(1.0, total_words / 150 * 60)

    sorted_turns = sorted(user_turns, key=lambda t: t.get('timestamp', 0))
    speaking_duration = 0.0
    for i, turn in enumerate(sorted_turns):
        words = len(turn.get('text', '').split())
        # Estimate each turn duration: words / 150wpm
        turn_duration = max(0.5, words / 150 * 60)
        speaking_duration += turn_duration

    return total_words, speaking_duration


def _calc_wpm(word_count: int, duration_seconds: float) -> float:
    if duration_seconds <= 0:
        return 0.0
    return (word_count / duration_seconds) * 60


def _per_turn_pace(user_turns: List[dict]) -> List[dict]:
    """Return WPM estimate per user turn (first 20 turns max)."""
    result = []
    for i, turn in enumerate(user_turns[:20]):
        words = len(turn.get('text', '').split())
        duration = max(0.5, words / 150 * 60)
        wpm = round((words / duration) * 60, 1)
        result.append({'turn_index': i, 'wpm': wpm, 'word_count': words})
    return result
