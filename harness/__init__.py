"""
Drive a real interview as pure text — no browser, no LiveKit room, no microphone.

This is not a reimplementation of the interview. It builds the same
`InterviewAgent`, the same FSM state and the same `AgentSession` that
`agent_worker.py` builds in production, and swaps only the parts that need
hardware: no STT, no TTS, no VAD, and a `NullTransport` in place of the room's
data channel.

What that buys: a developer or an AI agent can play the candidate across every
track, and a test can assert on FSM state, which tools the model called, what
the agent emitted to the UI, and the transcript that would have been scored.

What it deliberately does NOT cover — do not retire the e2e suite on its
account: VAD, endpointing and barge-in; STT errors and caption timing; TTS and
the audio cache; LiveKit connection and tokens; worker and dispatch lifecycle;
database persistence; real wall-clock races; and everything in interview.html.
"""

from .runtime import FakeClock, HarnessSession, start_interview

__all__ = ["FakeClock", "HarnessSession", "start_interview"]
