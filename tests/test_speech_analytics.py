"""Characterization tests for the pure speech-analytics logic."""

from speech_analytics import analyze_transcript


def test_empty_conversation_returns_zeroed_analytics():
    result = analyze_transcript({})
    assert result["filler_total"] == 0
    assert result["word_count"] == 0
    assert result["filler_breakdown"] == {}
    assert result["per_turn_pace"] == []


def test_counts_filler_words_including_phrases():
    convo = {
        "user": [
            {"text": "um so like you know um", "timestamp": 1.0},
            {"text": "actually I think so", "timestamp": 5.0},
        ]
    }
    result = analyze_transcript(convo)
    assert result["filler_breakdown"]["um"] == 2
    assert result["filler_breakdown"]["you know"] == 1
    assert result["filler_breakdown"]["so"] == 2
    assert result["filler_total"] >= 6


def test_word_count_matches_total_spoken_words():
    convo = {
        "user": [
            {"text": "one two three", "timestamp": 1.0},
            {"text": "four five", "timestamp": 4.0},
        ]
    }
    result = analyze_transcript(convo)
    assert result["word_count"] == 5
    assert result["avg_words_per_minute"] > 0


def test_per_turn_pace_capped_at_twenty_turns():
    convo = {"user": [{"text": "word", "timestamp": float(i)} for i in range(30)]}
    result = analyze_transcript(convo)
    assert len(result["per_turn_pace"]) == 20


def test_filler_matching_is_whole_word():
    # "summary" contains "um" and "so" as substrings but must not be counted.
    convo = {"user": [{"text": "summary personalities", "timestamp": 1.0}]}
    result = analyze_transcript(convo)
    assert "um" not in result["filler_breakdown"]
