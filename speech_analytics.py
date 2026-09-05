"""
Speech Analytics Module

Post-interview analysis of candidate speech patterns.
Processes the conversation dict saved by agent_worker.py.
All functions are pure (no side effects, no I/O).
"""

import re
import logging
from typing import List, Dict, Optional

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

        agent_turns = conversation.get('agent', [])

        filler_breakdown = _count_fillers(user_turns)
        filler_total = sum(filler_breakdown.values())
        word_count, duration_seconds = _measure_pace(user_turns)
        avg_wpm = _calc_wpm(word_count, duration_seconds)
        per_turn_pace = _per_turn_pace(user_turns)

        # Richer personality metrics (Wing D): sentences spoken and how much of
        # the conversation the candidate held (both word-based, so exact).
        sentence_count = _count_sentences(user_turns)
        agent_word_count = sum(len((t.get('text') or '').split()) for t in agent_turns)
        total_words = word_count + agent_word_count
        talk_ratio = round(word_count / total_words, 2) if total_words > 0 else 0.0

        pace_available = duration_seconds is not None

        # Longest single stretch of talking. Only meaningful with real per-turn
        # timing — it used to be `words/150*60`, i.e. a rescaled word count.
        longest_monologue_s = None
        if pace_available:
            measured = [
                float(t['duration_s']) for t in user_turns
                if t.get('duration_s') and (t.get('text') or '').strip()
            ]
            longest_monologue_s = round(max(measured), 1) if measured else None

        # Filler rate per 100 WORDS. Exactly measurable, unlike a per-minute rate.
        # The old filler_per_min divided by the fabricated duration, which made it
        # fillers-per-150-words wearing a per-minute label — and it fed both the
        # user-facing band and the judge prompt's "MEASURED DELIVERY" block.
        filler_per_100_words = round(100.0 * filler_total / word_count, 2) if word_count else 0.0

        result = {
            'filler_total': filler_total,
            'filler_breakdown': filler_breakdown,
            'filler_per_100_words': filler_per_100_words,
            'word_count': word_count,
            'pace_available': pace_available,
            'total_speaking_duration_seconds': round(duration_seconds, 1) if pace_available else None,
            'avg_words_per_minute': round(avg_wpm, 1) if avg_wpm is not None else None,
            'per_turn_pace': per_turn_pace,
            'sentence_count': sentence_count,
            'agent_word_count': agent_word_count,
            'talk_ratio': talk_ratio,
            'longest_monologue_s': longest_monologue_s,
        }
        logger.info(
            f"[ANALYTICS] Analyzed {len(user_turns)} user turns: {filler_total} fillers "
            f"({filler_per_100_words}/100w), pace="
            + (f"{avg_wpm:.0f} wpm" if pace_available else "not measured")
        )
        return result
    except Exception as e:
        logger.error(f"[ANALYTICS] Failed to analyze transcript: {e}")
        return _empty_analytics()


def _empty_analytics() -> dict:
    """No transcript to measure. Absent metrics are None, never 0 — a zero here
    would be a fabricated measurement, which is exactly what this module must
    not produce."""
    return {
        'filler_total': 0,
        'filler_breakdown': {},
        'filler_per_100_words': 0.0,
        'word_count': 0,
        'pace_available': False,
        'total_speaking_duration_seconds': None,
        'avg_words_per_minute': None,
        'per_turn_pace': [],
        'sentence_count': 0,
        'agent_word_count': 0,
        'talk_ratio': 0.0,
        'longest_monologue_s': None,
    }


def _count_sentences(user_turns: List[dict]) -> int:
    """
    Count spoken sentences across user turns. Uses terminal punctuation
    (. ! ?) when the STT punctuates; falls back to 1 per non-empty turn so an
    unpunctuated transcript still yields a sane, non-zero count.
    """
    total = 0
    for t in user_turns:
        text = (t.get('text') or '').strip()
        if not text:
            continue
        marks = len(re.findall(r'[.!?]+', text))
        total += max(1, marks)
    return total


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
    Return (total_word_count, measured_speaking_seconds | None).

    Speaking duration is only knowable if the turns carry a real per-turn
    `duration_s` (the candidate's speaking window, captured by the agent). When
    any turn lacks one, duration is None and every time-derived metric is
    reported as unavailable rather than guessed.

    This previously estimated each turn as `words / 150 * 60` and then divided
    words by that sum, which made the resulting WPM exactly 150 for every
    transcript ever produced — a constant presented to users as a measurement.
    The single timestamp a turn carries records when it ENDED; it cannot
    separate speaking time from thinking pauses, so it is not a substitute.
    """
    total_words = sum(len(t.get('text', '').split()) for t in user_turns)

    durations = [t.get('duration_s') for t in user_turns]
    if not durations or any(d is None for d in durations):
        return total_words, None
    try:
        measured = float(sum(float(d) for d in durations))
    except (TypeError, ValueError):
        return total_words, None
    return total_words, (measured if measured > 0 else None)


def _calc_wpm(word_count: int, duration_seconds) -> Optional[float]:
    """Words per minute, or None when the duration was never measured."""
    if not duration_seconds or duration_seconds <= 0:
        return None
    return (word_count / duration_seconds) * 60


def _per_turn_pace(user_turns: List[dict]) -> List[dict]:
    """Per-turn WPM — only for turns carrying a measured duration.

    Previously computed `words / (words/150*60) * 60`, i.e. 150.0 for every turn
    regardless of input.
    """
    result = []
    for i, turn in enumerate(user_turns[:20]):
        duration = turn.get('duration_s')
        try:
            duration = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration = None
        if not duration or duration <= 0:
            continue
        words = len(turn.get('text', '').split())
        result.append({
            'turn_index': i,
            'wpm': round((words / duration) * 60, 1),
            'word_count': words,
        })
    return result


