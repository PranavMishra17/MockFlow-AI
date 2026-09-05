"""
The speaking-window capture that makes delivery pace a real measurement.

`agent_worker.run_interview` is a ~600-line closure that cannot be imported
without full LiveKit env, so these tests exercise the same state machine in
isolation. The logic under test is small and self-contained; what matters is
that it produces a plausible measured duration, and that it yields None — never
a guess — whenever it cannot.
"""

import pytest


class SpeakingWindowTracker:
    """Mirror of the handler pair in agent_worker.run_interview.

    Kept in step with that code by test_matches_agent_worker_implementation
    below, which asserts the real source still contains the same guards.
    """

    MIN_S, MAX_S = 0.2, 600

    def __init__(self, clock):
        self.clock = clock
        self.window = {"started": None, "pending": None}

    def on_state(self, old, new):
        if new == "speaking":
            self.window["started"] = self.clock()
        elif old == "speaking" and self.window["started"] is not None:
            elapsed = self.clock() - self.window["started"]
            self.window["started"] = None
            if self.MIN_S <= elapsed <= self.MAX_S:
                self.window["pending"] = round(elapsed, 2)

    def on_final_transcript(self):
        d = self.window["pending"]
        if d is None and self.window["started"] is not None:
            elapsed = self.clock() - self.window["started"]
            if self.MIN_S <= elapsed <= self.MAX_S:
                d = round(elapsed, 2)
        self.window["pending"] = None
        return d


@pytest.fixture
def clock():
    class C:
        t = 1000.0

        def __call__(self):
            return self.t

        def advance(self, s):
            self.t += s
    return C()


def test_a_normal_turn_yields_its_measured_duration(clock):
    t = SpeakingWindowTracker(clock)
    t.on_state("listening", "speaking")
    clock.advance(12.5)
    t.on_state("speaking", "listening")
    assert t.on_final_transcript() == 12.5


def test_transcript_arriving_before_the_state_flip_still_measures(clock):
    """The final transcript can land while the user is still marked speaking."""
    t = SpeakingWindowTracker(clock)
    t.on_state("listening", "speaking")
    clock.advance(8.0)
    assert t.on_final_transcript() == 8.0


def test_no_speaking_window_yields_none_not_a_guess(clock):
    t = SpeakingWindowTracker(clock)
    assert t.on_final_transcript() is None


def test_each_turn_consumes_its_own_window(clock):
    t = SpeakingWindowTracker(clock)
    t.on_state("listening", "speaking")
    clock.advance(5.0)
    t.on_state("speaking", "listening")
    assert t.on_final_transcript() == 5.0
    # A second transcript with no new speech must not reuse the first duration.
    assert t.on_final_transcript() is None


def test_implausibly_short_windows_are_discarded(clock):
    t = SpeakingWindowTracker(clock)
    t.on_state("listening", "speaking")
    clock.advance(0.05)          # a blip, not an answer
    t.on_state("speaking", "listening")
    assert t.on_final_transcript() is None


def test_implausibly_long_windows_are_discarded(clock):
    """A stuck 'speaking' state must not become a 2-hour monologue."""
    t = SpeakingWindowTracker(clock)
    t.on_state("listening", "speaking")
    clock.advance(7200)
    t.on_state("speaking", "listening")
    assert t.on_final_transcript() is None


def test_away_state_does_not_start_a_window(clock):
    t = SpeakingWindowTracker(clock)
    t.on_state("listening", "away")
    clock.advance(30)
    t.on_state("away", "listening")
    assert t.on_final_transcript() is None


def test_measured_durations_flow_into_a_real_pace():
    """End-to-end with the analytics module: measured windows -> real WPM."""
    import speech_analytics as sa

    conv = {
        "user": [
            {"text": " ".join(["w"] * 100), "timestamp": 0, "duration_s": 60.0},
            {"text": " ".join(["w"] * 50), "timestamp": 90, "duration_s": 30.0},
        ],
        "agent": [{"text": "ok", "timestamp": 1}],
    }
    r = sa.analyze_transcript(conv)
    assert r["pace_available"] is True
    assert r["total_speaking_duration_seconds"] == 90.0
    assert r["avg_words_per_minute"] == 100.0      # 150 words / 1.5 min
    assert r["longest_monologue_s"] == 60.0


def test_a_turn_without_a_window_keeps_the_session_unmeasured():
    """One unmeasured turn must not be papered over by extrapolating the rest."""
    import speech_analytics as sa

    conv = {
        "user": [
            {"text": " ".join(["w"] * 100), "timestamp": 0, "duration_s": 60.0},
            {"text": " ".join(["w"] * 50), "timestamp": 90, "duration_s": None},
        ],
        "agent": [],
    }
    r = sa.analyze_transcript(conv)
    assert r["pace_available"] is False
    assert r["avg_words_per_minute"] is None


def test_matches_agent_worker_implementation():
    """Guard against this mirror drifting from the real handler."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1].joinpath("agent_worker.py").read_text(
        encoding="utf-8", errors="ignore"
    )
    assert 'speech_window = {"started": None, "pending": None}' in src
    assert '@session.on("user_state_changed")' in src
    assert "0.2 <= elapsed <= 600" in src
    assert '"duration_s": duration_s,' in src
