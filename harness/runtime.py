"""The harness session: the production runtime with its voice I/O removed."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

import agent_mode
from interview_runtime import (
    CommandContext,
    InterviewAgent,
    NullTransport,
    attach_handlers,
    build_interview_state,
    build_session,
    collect_interview_data,
    ensure_questions_generated,
    handle_command,
)
from tracks import get_track_config

logger = logging.getLogger("harness")


class FakeClock:
    """A clock the scenario drives, so a ten-minute stage ages instantly.

    `InterviewState` reads every wall-clock value through the callable it is
    given, so advancing this is indistinguishable from waiting.
    """

    def __init__(self, start: Optional[datetime] = None):
        self.now = start or datetime(2026, 1, 1, 9, 0, 0)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@dataclass
class HarnessSession:
    """One interview, driven by text."""

    state: Any
    agent: InterviewAgent
    session: Any
    transport: NullTransport
    handles: Any
    clock: FakeClock
    command_ctx: CommandContext
    tool_calls: list = field(default_factory=list)
    closed: bool = False

    # -- driving ----------------------------------------------------------

    async def say(self, text: str):
        """Speak as the candidate, through the same turn loop the room uses.

        `session.run(user_input=)` cannot be used: it never calls
        `on_user_turn_completed`, so the harness would test a turn loop the
        room does not run. This mirrors the SDK's own end-of-turn sequence
        (agent_activity.py, 1.3.6): build the user message, copy the chat
        context, let the agent prepare the turn on the copy (that is where
        the [FLOW MOVE] note lands), then generate the reply from that copy.
        If the agent closes the interview it raises StopResponse and there is
        no reply to wait for.
        """
        from livekit.agents import StopResponse, llm as lk_llm

        msg = lk_llm.ChatMessage(role="user", content=[text])
        turn_ctx = self.agent.chat_ctx.copy()
        try:
            await self.agent.prepare_turn(turn_ctx, msg)
        except StopResponse:
            await self.settle(timeout=15, quiet_for=0.5)
            return None
        handle = self.session._activity._generate_reply(user_message=msg, chat_ctx=turn_ctx)
        await handle
        await self.settle(timeout=15, quiet_for=0.3)
        return handle

    async def settle(self, timeout: float = 30.0, quiet_for: float = 0.6) -> None:
        """Wait until the agent stops producing turns.

        Needed after `start()`: `on_enter` generates the greeting, and on the
        generated-question tracks it also calls `generate_interview_questions`
        and transitions — all of it after `start()` has returned. Asserting
        before that settles reads a half-built interview.
        """
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout
        last_count = -1
        quiet_since = None
        while asyncio.get_event_loop().time() < deadline:
            count = len(self.handles.conversation['agent']) + len(self.tool_calls)
            now = asyncio.get_event_loop().time()
            if count != last_count:
                last_count = count
                quiet_since = now
            elif quiet_since is not None and now - quiet_since >= quiet_for and count > 0:
                return
            await asyncio.sleep(0.1)

    async def command(self, payload: Mapping[str, Any]) -> bool:
        """Send a client->agent command, as the browser's data channel would."""
        return await handle_command(payload, self.command_ctx)

    def advance(self, seconds: float) -> None:
        self.clock.advance(seconds)

    # -- reading ----------------------------------------------------------

    @property
    def stage(self) -> str:
        return self.state.stage.value

    def emitted(self, type_name: str) -> list:
        return self.transport.of_type(type_name)

    def transcript(self) -> dict:
        return self.handles.conversation

    def question_bank(self) -> list:
        """The generated questions (or coding problems) for this track.

        Asserting on this rather than on "did the model call the tool" is
        deliberate: generation moved into the runtime, so the tool firing is no
        longer the thing that matters — the bank existing is.
        """
        if getattr(self.state, 'track_type', 'intro') == 'coding':
            return list(getattr(self.state, 'generated_problems', []) or [])
        return list(getattr(self.state, 'generated_questions', []) or [])

    def question_bank_text(self) -> str:
        """Everything in the bank as one lowercased blob, for substring checks."""
        return json.dumps(self.question_bank(), default=str).lower()

    def interview_row(self, ended_by: str = 'natural_completion') -> dict:
        """The row that would have been written to the database."""
        return collect_interview_data(
            self.state,
            self.handles.conversation,
            room_name='harness',
            ended_by=ended_by,
        )

    async def aclose(self) -> None:
        if not self.closed:
            self.closed = True
            await self.session.aclose()


async def start_interview(
    config: Mapping[str, Any],
    *,
    llm,
    candidate_name: str = "Ada Lovelace",
    clock: Optional[FakeClock] = None,
    assess=None,
) -> HarnessSession:
    """Build and start an interview with no room attached.

    `config` is a raw mapping; it goes through `agent_mode.normalize_config`
    exactly as participant attributes do in production, so a scenario cannot
    accidentally exercise a config shape the real transports cannot produce.
    """
    clock = clock or FakeClock()
    normalized = agent_mode.normalize_config(config)

    state = build_interview_state(normalized, candidate_name=candidate_name, now=clock)
    transport = NullTransport()
    track_type = normalized['track']

    # `assess` is the per-turn assessment call; tests pass a fake, the CLI
    # leaves it None and gets the real one.
    agent = InterviewAgent(
        transport=transport,
        candidate_info={'name': candidate_name, 'role': normalized['role']},
        track_type=track_type,
        assess=assess,
    )

    # No stt/tts/vad: this is the whole difference from production. `say()`
    # still works with no TTS as long as no audio output is attached, so the
    # cached-welcome and skip-acknowledgement paths execute for real.
    session = build_session(state, llm=llm)

    # The production driver builds the question bank before starting; the
    # harness must too, or every scenario silently tests the improvised path.
    await ensure_questions_generated(state)

    handles = attach_handlers(session, state, transport)

    # There are no function tools any more (the turn loop is code; see
    # interview_turn.py). The list stays so a scenario that still expects a
    # tool fails loudly rather than silently passing.
    tool_calls: list = []

    # capture_run makes `session.run()` available; no room means eval mode.
    await session.start(agent, capture_run=True)

    return HarnessSession(
        state=state,
        agent=agent,
        session=session,
        transport=transport,
        handles=handles,
        clock=clock,
        tool_calls=tool_calls,
        command_ctx=CommandContext(
            session=session,
            state=state,
            agent=agent,
            transport=transport,
            track_config=get_track_config(track_type),
        ),
    )
