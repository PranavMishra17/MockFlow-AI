"""
Delivery metrics must be MEASURED or absent — never fabricated.

The moat's non-negotiable (docs/EPIC_wingD_feedback_moat.md §1.5): countable
delivery metrics are computed in code and injected, precisely so nothing invents
them. These tests pin the two ways that was being violated.

1. Pace was a constant. Each turn's duration was estimated as `words/150*60`,
   then words were divided by that duration — so `avg_words_per_minute` was
   exactly 150.0 for EVERY transcript, `per_turn_pace` was 150.0 for every turn,
   and `longest_monologue_s` was a rescaled word count. All four are artifacts of
   the assumption, not observations, and are now reported as unavailable unless
   real timing exists.

2. The filler rate was mislabeled. `filler_per_min` divided by that same fake
   duration, making it fillers-per-150-words wearing a per-minute label — and it
   fed both the user-facing band and the judge prompt's "MEASURED DELIVERY ...
   use these exact numbers". It is now reported per 100 words, which is exactly
   measurable. The thresholds are rescaled from the same research anchors, so
   band assignments are unchanged; only the unit becomes truthful.
"""

import feedback_scoring as fs
import speech_analytics as sa


def _conv(user_texts, agent_texts=("ok tell me more",), durations=None):
    user = []
    for i, t in enumerate(user_texts):
        turn = {"text": t, "timestamp": i * 30}
        if durations is not None:
            turn["duration_s"] = durations[i]
        user.append(turn)
    return {
        "user": user,
        "agent": [{"text": t, "timestamp": i} for i, t in enumerate(agent_texts)],
    }


def _words(n):
    return " ".join(["word"] * n)


# --------------------------------------------------------------------------
# 1. Pace is not reported unless it was measured
# --------------------------------------------------------------------------

def test_pace_is_unavailable_without_timing_data():
    r = sa.analyze_transcript(_conv([_words(80), _words(120)]))
    assert r["pace_available"] is False
    assert r["avg_words_per_minute"] is None
    assert r["per_turn_pace"] == []
    assert r["longest_monologue_s"] is None
    assert r["total_speaking_duration_seconds"] is None


def test_pace_no_longer_collapses_to_the_same_number_for_every_transcript():
    """The original bug, stated as a test: wildly different transcripts produced
    an identical 150.0. Now they produce an identical *absence*, which is honest."""
    seen = set()
    for n in (2, 5, 13, 40):
        r = sa.analyze_transcript(_conv([_words(20 * i + 5) for i in range(n)]))
        seen.add(r["avg_words_per_minute"])
    assert seen == {None}


def test_word_based_metrics_are_still_real():
    """Only the time-derived family was fabricated; these were always measured."""
    r = sa.analyze_transcript(_conv([_words(100), _words(50)]))
    assert r["word_count"] == 150
    assert r["sentence_count"] >= 1
    assert 0.0 < r["talk_ratio"] <= 1.0


def test_real_durations_produce_a_real_pace():
    # 300 words spoken over 120s == 150 wpm, but arrived at by measurement.
    r = sa.analyze_transcript(_conv([_words(150), _words(150)], durations=[60.0, 60.0]))
    assert r["pace_available"] is True
    assert r["total_speaking_duration_seconds"] == 120.0
    assert r["avg_words_per_minute"] == 150.0
    assert r["longest_monologue_s"] == 60.0


def test_measured_pace_actually_varies_with_the_measurement():
    slow = sa.analyze_transcript(_conv([_words(100)], durations=[120.0]))
    fast = sa.analyze_transcript(_conv([_words(100)], durations=[20.0]))
    assert slow["avg_words_per_minute"] < fast["avg_words_per_minute"]
    assert slow["avg_words_per_minute"] == 50.0
    assert fast["avg_words_per_minute"] == 300.0


def test_partial_timing_is_not_treated_as_complete():
    """One timed turn among untimed ones must not be extrapolated to the whole."""
    r = sa.analyze_transcript(_conv([_words(100), _words(100)], durations=[60.0, None]))
    assert r["pace_available"] is False
    assert r["avg_words_per_minute"] is None


# --------------------------------------------------------------------------
# 2. The filler rate is measured in a unit we can actually measure
# --------------------------------------------------------------------------

def test_filler_rate_is_per_100_words_and_exact():
    r = sa.analyze_transcript(_conv([("um " * 6) + _words(194)]))
    assert r["filler_total"] == 6
    assert r["word_count"] == 200
    assert r["filler_per_100_words"] == 3.0


def test_filler_band_assignments_are_unchanged_by_the_unit_fix():
    """The old thresholds were 5 and 12 on a fillers-per-150-words quantity.
    Rescaled to per-100-words those are 3.33 and 8.0, so every transcript lands
    in the same band as before — the label changes, the judgement does not."""
    for fillers, words in ((2, 300), (6, 100), (20, 100), (5, 150), (12, 150)):
        old_per_150 = 150.0 * fillers / words           # what the old code computed
        old_band = fs.filler_band(old_per_150)
        new_band = fs.filler_band_per_100w(100.0 * fillers / words)
        assert new_band == old_band, (fillers, words, old_per_150)


def test_filler_per_minute_is_absent_without_timing():
    d = fs.delivery_metrics(sa.analyze_transcript(_conv([("um " * 3) + _words(100)])))
    assert d["filler_per_min"] is None
    assert d["filler_per_100w"] is not None


def test_filler_per_minute_appears_once_timing_is_real():
    d = fs.delivery_metrics(
        sa.analyze_transcript(_conv([("um " * 5) + _words(145)], durations=[60.0]))
    )
    assert d["filler_per_min"] == 5.0


# --------------------------------------------------------------------------
# 3. delivery_metrics + the judge prompt must not present absent as zero
# --------------------------------------------------------------------------

def test_delivery_metrics_marks_pace_unavailable_rather_than_zero():
    d = fs.delivery_metrics(sa.analyze_transcript(_conv([_words(120)])))
    assert d["pace_available"] is False
    assert d["wpm"] is None
    assert d["wpm_band"] == "unknown"
    assert d["longest_monologue_s"] is None
    # A zero here would be a fabricated measurement, which is the whole problem.
    assert d["wpm"] != 0


def test_speech_summary_omits_pace_when_it_was_not_measured():
    summary = fs.build_speech_summary(sa.analyze_transcript(_conv([("um " * 4) + _words(196)])))
    low = summary.lower()
    assert "words/min" not in low and "wpm" not in low
    assert "per 100 words" in low
    assert "4" in summary                       # the real filler count survives
    assert "not measured" in low or "not available" in low


def test_speech_summary_includes_pace_once_measured():
    summary = fs.build_speech_summary(
        sa.analyze_transcript(_conv([_words(150)], durations=[60.0]))
    )
    assert "150" in summary
    assert "words/min" in summary.lower()


def test_empty_analytics_does_not_claim_a_measured_pace():
    empty = sa.analyze_transcript({"user": [], "agent": []})
    assert empty["pace_available"] is False
    assert empty["avg_words_per_minute"] is None
    assert empty["filler_total"] == 0


def test_delivery_metrics_survives_an_old_row_with_the_legacy_shape():
    """Rows saved before this fix carry the fabricated numbers. They must not
    crash, and the fabricated pace must not be resurfaced as if measured."""
    legacy = {
        "filler_total": 7, "filler_breakdown": {"um": 7}, "word_count": 450,
        "total_speaking_duration_seconds": 180.0, "avg_words_per_minute": 150.0,
        "per_turn_pace": [{"turn_index": 0, "wpm": 150.0, "word_count": 450}],
        "sentence_count": 20, "agent_word_count": 300, "talk_ratio": 0.6,
        "longest_monologue_s": 44.0,
    }
    d = fs.delivery_metrics(legacy)
    assert d["filler_total"] == 7
    assert d["pace_available"] is False
    assert d["wpm"] is None
