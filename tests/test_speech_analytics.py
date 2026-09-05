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
    # Pace needs real per-turn durations. Without them it is reported absent,
    # not guessed — this used to assert a fabricated constant 150.0.
    assert result["pace_available"] is False
    assert result["avg_words_per_minute"] is None


def test_per_turn_pace_capped_at_twenty_turns():
    # Turns must carry measured durations to have a pace at all.
    convo = {"user": [
        {"text": "word", "timestamp": float(i), "duration_s": 1.0} for i in range(30)
    ]}
    result = analyze_transcript(convo)
    assert len(result["per_turn_pace"]) == 20


def test_per_turn_pace_is_empty_without_measured_durations():
    convo = {"user": [{"text": "word", "timestamp": float(i)} for i in range(30)]}
    assert analyze_transcript(convo)["per_turn_pace"] == []


def test_filler_matching_is_whole_word():
    # "summary" contains "um" and "so" as substrings but must not be counted.
    convo = {"user": [{"text": "summary personalities", "timestamp": 1.0}]}
    result = analyze_transcript(convo)
    assert "um" not in result["filler_breakdown"]


# ---- richer personality metrics (Wing D C2) ----

def test_sentence_count_uses_terminal_punctuation():
    convo = {"user": [
        {"text": "Hello there. How are you?", "timestamp": 1.0},
        {"text": "I am good", "timestamp": 5.0},  # no punctuation -> counts as 1
    ]}
    result = analyze_transcript(convo)
    assert result["sentence_count"] == 3


def test_talk_ratio_is_word_based():
    convo = {
        "user": [{"text": "one two three", "timestamp": 1.0}],          # 3 words
        "agent": [{"text": "a b c d e f g h i", "timestamp": 0.5}],     # 9 words
    }
    result = analyze_transcript(convo)
    assert result["agent_word_count"] == 9
    assert result["talk_ratio"] == 0.25  # 3 / (3 + 9)


def test_longest_monologue_tracks_biggest_turn():
    # Measured durations, not `words/150*60` — the old expectation of 30.0s was
    # that formula applied to a 75-word turn, i.e. a rescaled word count.
    convo = {"user": [
        {"text": " ".join(["w"] * 10), "timestamp": 1.0, "duration_s": 8.0},
        {"text": " ".join(["w"] * 75), "timestamp": 5.0, "duration_s": 30.0},
    ]}
    result = analyze_transcript(convo)
    assert result["longest_monologue_s"] == 30.0


def test_longest_monologue_is_absent_without_measured_durations():
    convo = {"user": [{"text": " ".join(["w"] * 75), "timestamp": 5.0}]}
    assert analyze_transcript(convo)["longest_monologue_s"] is None


def test_empty_conversation_zeroes_new_metrics():
    result = analyze_transcript({})
    assert result["sentence_count"] == 0
    assert result["agent_word_count"] == 0
    assert result["talk_ratio"] == 0.0
    # None, not 0.0: an absent measurement must be distinguishable from a real
    # zero, otherwise "we did not measure" reads as "you never spoke".
    assert result["longest_monologue_s"] is None
