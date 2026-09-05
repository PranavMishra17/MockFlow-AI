"""
MockFlow-AI Interview Agent Worker

Runs one interview, over either transport:

    direct    spawned per interview by worker_manager for one named room, which
              it connects to explicitly. The original behavior, still the default.
    dispatch  a resident worker registered with a LiveKit project, receiving
              rooms as jobs. See agent_mode.py and docs/AGENT_DISPATCH.md.

This file is only the parts that are genuinely about being in a room: resolving
the environment, minting a token, connecting, waiting for the participant,
building the voice plugins, and saving the interview when it ends. What differs
between the transports is exactly that — how the room, the HTTP session and the
config arrive — which is why the ownership flags below are the only branching
the interview itself ever sees.

The interview — the agent, its tools, the FSM wiring, command dispatch and the
transcript — lives in `interview_runtime.py`, which imports with no environment
at all so it can be driven without LiveKit.
"""

import asyncio
import logging
import os
import sys

import aiohttp

from livekit import api as livekit_api
from livekit.rtc import Room
from livekit.plugins import openai, deepgram, silero

import agent_mode
from interview_runtime import (
    CommandContext,
    InterviewAgent,
    RoomTransport,
    attach_handlers,
    build_interview_state,
    build_session,
    collect_interview_data,
    ensure_questions_generated,
    handle_command,
    stage_fallback_timer,
)
from tracks import get_track_config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("agent-worker")

# Suppress noisy logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Environment
#
# Resolved lazily rather than at import. When this ran at module scope, a bad
# AGENT_MODE or a missing key made `import agent_worker` a hard process exit,
# so nothing could import this file to test it.
# ---------------------------------------------------------------------------

_WORKER_ENV = None


def resolve_worker_env(env=None) -> dict:
    """Resolve transport mode and credentials, or exit with what is missing."""
    env = os.environ if env is None else env

    try:
        mode = agent_mode.resolve_mode(env)
    except ValueError as e:
        logger.error(f"[CONFIG] {e}")
        sys.exit(1)

    resolved = {
        'mode': mode,
        'openai_key': env.get('OPENAI_API_KEY'),
        'deepgram_key': env.get('DEEPGRAM_API_KEY'),
        'livekit_url': env.get('LIVEKIT_URL'),
        'livekit_api_key': env.get('LIVEKIT_API_KEY'),
        'livekit_api_secret': env.get('LIVEKIT_API_SECRET'),
        'room_name': env.get('INTERVIEW_ROOM_NAME'),
    }

    # In DISPATCH mode this process is the resident worker, and it must run on the
    # SAME credentials the web process compares against (agent_mode.system_keys_from_env),
    # or the BYOK guard is comparing against something that isn't us. So SYSTEM_* wins
    # here, falling back to the per-interview vars for a hand-run worker.
    if mode == agent_mode.MODE_DISPATCH:
        system = agent_mode.system_keys_from_env(env)
        if system:
            resolved.update({
                'livekit_url': system['livekit_url'],
                'livekit_api_key': system['livekit_api_key'],
                'livekit_api_secret': system['livekit_api_secret'],
                'openai_key': system['openai_key'],
                'deepgram_key': system['deepgram_key'],
            })
            # The plugins read these from the environment, so export them too.
            os.environ['OPENAI_API_KEY'] = system['openai_key']
            os.environ['DEEPGRAM_API_KEY'] = system['deepgram_key']
            logger.info("[CONFIG] Dispatch worker using SYSTEM_* credentials")
        else:
            logger.warning(
                "[CONFIG] AGENT_MODE=dispatch but the SYSTEM_* key set is incomplete; "
                "falling back to LIVEKIT_*/OPENAI_API_KEY/DEEPGRAM_API_KEY. The web "
                "process compares interviews against SYSTEM_*, so unless these are the "
                "same credentials, no dispatch will ever be routed to this worker."
            )

    # The room name is a per-job value in dispatch mode, so it is only required
    # when this process was spawned to serve one specific room.
    required = ['openai_key', 'deepgram_key', 'livekit_url',
                'livekit_api_key', 'livekit_api_secret']
    if mode == agent_mode.MODE_DIRECT:
        required.append('room_name')

    if not all(resolved[name] for name in required):
        logger.error("[CONFIG] Missing required API keys or room name in environment")
        logger.error(f"[CONFIG] Mode: {mode}")
        for name in required:
            logger.error(f"[CONFIG] {name}: {bool(resolved[name])}")
        sys.exit(1)

    logger.info(f"[CONFIG] API keys loaded from environment (mode={mode})")
    logger.info(f"[CONFIG] LiveKit URL: {resolved['livekit_url']}")
    if mode == agent_mode.MODE_DIRECT:
        logger.info(f"[CONFIG] Target Room: {resolved['room_name']}")
    else:
        logger.info(f"[CONFIG] Dispatch agent_name: {agent_mode.agent_name(env)}")

    return resolved


def worker_env() -> dict:
    """The resolved environment for this process, resolved once on first use."""
    global _WORKER_ENV
    if _WORKER_ENV is None:
        _WORKER_ENV = resolve_worker_env()
    return _WORKER_ENV


# ---------------------------------------------------------------------------
# Voice plugins and room lifecycle
# ---------------------------------------------------------------------------

def _build_voice_components(http_session):
    """Construct STT / LLM / TTS / VAD, or raise with which one failed.

    Only Deepgram STT needs the shared HTTP session when running outside
    `cli.run_app()`; the OpenAI plugins use their own client. Under dispatch
    `http_session` is None and the plugin resolves one from the job context.
    """
    try:
        stt = deepgram.STT(
            model="nova-2",
            language="en-US",
            smart_format=True,
            http_session=http_session
        )
        logger.info("[MAIN] Deepgram STT initialized")
    except Exception as e:
        logger.error(f"[MAIN] Deepgram STT init error: {e}", exc_info=True)
        raise RuntimeError(f"Failed to initialize Deepgram STT: {e}")

    try:
        llm = openai.LLM(
            model="gpt-4o-mini",
            temperature=0.7
        )
        logger.info("[MAIN] OpenAI LLM initialized")
    except Exception as e:
        logger.error(f"[MAIN] OpenAI LLM init error: {e}", exc_info=True)
        raise RuntimeError(f"Failed to initialize OpenAI LLM: {e}")

    try:
        tts = openai.TTS(
            voice="alloy",
            speed=1.0
        )
        logger.info("[MAIN] OpenAI TTS initialized")
    except Exception as e:
        logger.error(f"[MAIN] OpenAI TTS init error: {e}", exc_info=True)
        raise RuntimeError(f"Failed to initialize OpenAI TTS: {e}")

    try:
        # Silero VAD with optimized settings for lower CPU usage.
        # Default settings cause "inference is slower than realtime" on limited CPU.
        vad = silero.VAD.load(
            min_speech_duration=0.1,      # Minimum speech duration to detect (default: 0.05)
            min_silence_duration=0.3,     # Silence needed to end speech (default: 0.1)
            padding_duration=0.1,         # Padding around speech (default: 0.1)
            max_buffered_speech=30.0,     # Max buffered speech in seconds (default: 60)
            activation_threshold=0.5,     # Confidence threshold (default: 0.5)
            sample_rate=16000,            # Use 16kHz for lower CPU (matches Deepgram)
        )
        logger.info("[MAIN] Silero VAD initialized with optimized settings")
    except Exception as e:
        logger.error(f"[MAIN] Silero VAD init error: {e}", exc_info=True)
        raise RuntimeError(f"Failed to initialize Silero VAD: {e}")

    return stt, llm, tts, vad


async def _connect_to_room(env: dict) -> Room:
    """Mint an agent token for the configured room and connect to it (direct mode)."""
    room_name = env['room_name']

    token = livekit_api.AccessToken(env['livekit_api_key'], env['livekit_api_secret'])
    token.with_identity("interview-agent")
    token.with_name("AI Interviewer")
    token.with_grants(livekit_api.VideoGrants(
        room_join=True,
        room=room_name,
        can_publish=True,
        can_subscribe=True,
    ))
    agent_token = token.to_jwt()
    logger.info(f"[MAIN] Generated agent token for room: {room_name}")

    room = Room()
    logger.info(f"[MAIN] Connecting to LiveKit: {env['livekit_url']}")
    await room.connect(env['livekit_url'], agent_token)
    logger.info(f"[MAIN] Connected to room: {room.name}")
    return room


async def _wait_for_participant(room: Room, timeout: float = 60.0):
    """Wait for the candidate to join. Returns the participant, or None on timeout."""
    logger.info("[MAIN] Waiting for participant to join...")
    wait_start = asyncio.get_event_loop().time()
    while not room.remote_participants:
        if asyncio.get_event_loop().time() - wait_start > timeout:
            logger.error("[MAIN] Timeout waiting for participant")
            return None
        await asyncio.sleep(0.5)
    return list(room.remote_participants.values())[0]


def _candidate_name_from_room(room_name: str) -> str:
    """Recover the candidate's display name from the room name."""
    room_parts = room_name.split('-')
    return ' '.join(room_parts[1:-1]).title() if len(room_parts) > 2 else "Candidate"


async def run_interview(room=None, http_session=None, job_metadata=None, env=None):
    """
    Run one interview. Shared by both transports.

    direct mode (room=None, the default):
        Mints an agent token for INTERVIEW_ROOM_NAME, creates its own Room, and
        connects explicitly — bypassing LiveKit's dispatch system.

    dispatch mode (room supplied):
        The caller is `dispatch_entrypoint`, which hands over the already-
        connected `ctx.room` and lets the agents framework own the room and the
        HTTP session. `job_metadata` carries the interview config that direct
        mode reads off participant attributes.

    The interview body is identical in both cases; only how we obtain the room,
    the HTTP session and the config differs.
    """
    env = env if env is not None else worker_env()

    owns_room = room is None
    owns_http_session = http_session is None and owns_room

    interview_complete = asyncio.Event()
    fallback_task = None

    try:
        if owns_room:
            logger.info(f"[MAIN] Starting interview agent for room: {env['room_name']}")

            # Shared HTTP session for plugins, required when not using cli.run_app()
            http_session = aiohttp.ClientSession()
            logger.info("[MAIN] Created shared HTTP session for plugins")

            room = await _connect_to_room(env)
        else:
            # Dispatch: the framework connected the room before calling us, and
            # supplies the plugin HTTP session via the job context.
            logger.info(f"[MAIN] Dispatch job accepted for room: {room.name}")

        transport = RoomTransport(room)

        participant = await _wait_for_participant(room)
        if participant is None:
            if owns_room:
                await room.disconnect()
            return

        # Resolve interview config. Both transports funnel through the SAME
        # parser (agent_mode.merge_config) so defaults and list-splitting cannot
        # drift between direct and dispatch. Job metadata wins where present;
        # participant attributes fill the rest.
        attrs = getattr(participant, 'attributes', None) or None
        config = agent_mode.merge_config(metadata=job_metadata, attributes=attrs)

        candidate_name = _candidate_name_from_room(room.name)
        user_id = config['user_id']
        track_type = config['track']

        logger.info(f"[MAIN] Config source: metadata={bool(job_metadata)}, attributes={bool(attrs)}")
        logger.info(
            f"[MAIN] Role: {config['role']}, Level: {config['level']}, "
            f"Resume: {bool(config['resume_text'])}"
        )
        logger.info(
            f"[MAIN] Track: {track_type}, Framework: {config['framework']}, "
            f"Depth: {config['depth']}, Topics: {config['topics']}"
        )
        logger.info(
            f"[MAIN] Candidate: {candidate_name} "
            f"(Role: {config['role']}, Level: {config['level']})"
        )

        track_config = get_track_config(track_type)
        interview_state = build_interview_state(config, candidate_name=candidate_name)

        # Build the track's questions before the interview starts. This used to
        # depend on the model choosing to call a tool that no prompt asks it to
        # call, which is why behavioral interviews ran on improvised questions
        # with the configured framework and custom questions silently dropped.
        if await ensure_questions_generated(interview_state):
            logger.info(f"[MAIN] Question bank prepared for track: {track_type}")

        stt, llm, tts, vad = _build_voice_components(http_session)

        agent = InterviewAgent(
            transport=transport,
            candidate_info={'name': candidate_name, 'role': config['role']},
            track_type=track_type,
        )
        logger.info(f"[MAIN] InterviewAgent created for candidate: {candidate_name}")

        session = build_session(interview_state, llm=llm, stt=stt, tts=tts, vad=vad)

        async def finalize_and_disconnect():
            """Save the interview to the database and disconnect."""
            try:
                if not user_id:
                    logger.error("[FINALIZE] No user_id found")
                    await room.disconnect()
                    return

                logger.info(f"[FINALIZE] Saving interview to database for user: {user_id}")
                interview_data = collect_interview_data(
                    interview_state,
                    handles.conversation,
                    room_name=room.name,
                    ended_by='natural_completion',
                )

                # psycopg is synchronous, so the save goes to a thread. On the
                # loop it stalls the closing audio and the disconnect behind it.
                from supabase_client import supabase_client
                interview_id = await asyncio.to_thread(
                    supabase_client.save_interview, user_id, interview_data)

                if interview_id:
                    interview_state._interview_id = interview_id
                    interview_state._user_id = user_id
                    logger.info(f"[FINALIZE] Interview saved successfully: {interview_id}")

                    await transport.emit({
                        "type": "interview_saved",
                        "interview_id": interview_id,
                        "message": "Interview saved successfully",
                    })
                    await transport.emit({
                        "type": "interview_ending",
                        "message": "Interview Complete",
                    })
                else:
                    logger.error("[FINALIZE] Database save failed")
                    await transport.emit({
                        "type": "save_error",
                        "message": "Failed to save interview. Please contact support.",
                    })

                handles.closing_finalized["done"] = True
                interview_complete.set()

                await asyncio.sleep(2.0)
                await room.disconnect()
                logger.info("[FINALIZE] Disconnected from room")

            except Exception as e:
                logger.error(f"[FINALIZE] Error: {e}", exc_info=True)
                try:
                    await room.disconnect()
                except Exception:
                    pass
                interview_complete.set()

        handles = attach_handlers(
            session, interview_state, transport, on_closing=finalize_and_disconnect
        )

        command_ctx = CommandContext(
            session=session,
            state=interview_state,
            agent=agent,
            transport=transport,
            track_config=track_config,
        )

        @room.on("data_received")
        def on_data_received(data_packet):
            try:
                import json
                payload = json.loads(data_packet.data.decode('utf-8'))
                asyncio.create_task(handle_command(payload, command_ctx))
            except Exception as e:
                logger.error(f"[DATA] Error processing data: {e}", exc_info=True)

        async def save_transcript_on_disconnect():
            """Save the interview transcript when the room disconnects."""
            try:
                if handles.closing_finalized.get("done"):
                    logger.info("[HISTORY] Transcript already saved via finalize_and_disconnect")
                    return

                if not handles.conversation["agent"] and not handles.conversation["user"]:
                    logger.info("[HISTORY] No conversation to save")
                    return

                if not user_id:
                    logger.error("[HISTORY] No user_id found")
                    return

                interview_data = collect_interview_data(
                    interview_state,
                    handles.conversation,
                    room_name=room.name,
                    ended_by='user_disconnect',
                    candidate_name=candidate_name,
                )

                from supabase_client import supabase_client
                interview_id = await asyncio.to_thread(
                    supabase_client.save_interview, user_id, interview_data)

                if interview_id:
                    interview_state._interview_id = interview_id
                    interview_state._user_id = user_id
                    logger.info(f"[HISTORY] Saved transcript on disconnect: {interview_id}")
                    try:
                        await transport.emit({
                            "type": "interview_saved",
                            "interview_id": interview_id,
                        })
                    except Exception as e:
                        logger.warning(f"[HISTORY] Failed to emit interview_id: {e}")
                else:
                    logger.error("[HISTORY] Database save failed on disconnect")

            except Exception as e:
                logger.error(f"[HISTORY] Error saving on disconnect: {e}", exc_info=True)

        @room.on("disconnected")
        def on_room_disconnected():
            logger.info("[ROOM] Room disconnected")
            asyncio.create_task(save_transcript_on_disconnect())
            interview_complete.set()

        async def _disconnect_on_closing_timeout():
            try:
                await room.disconnect()
            except Exception:
                pass

        # Start fallback timer
        fallback_task = asyncio.create_task(
            stage_fallback_timer(
                session, interview_state, transport, agent, interview_complete,
                track_config, on_timeout=_disconnect_on_closing_timeout,
            )
        )

        # Start the agent session
        logger.info("[MAIN] Starting agent session...")
        await session.start(agent=agent, room=room)
        logger.info("[MAIN] Agent session started, waiting for interview to complete...")

        await interview_complete.wait()
        logger.info("[MAIN] Interview complete")

    except asyncio.CancelledError:
        logger.info("[MAIN] Interview cancelled")
    except Exception as e:
        logger.error(f"[MAIN] Error: {e}", exc_info=True)
    finally:
        logger.info("[MAIN] Starting cleanup...")

        # 1. Cancel fallback task if running
        if fallback_task and not fallback_task.done():
            fallback_task.cancel()
            try:
                await fallback_task
            except asyncio.CancelledError:
                pass

        # 2. Give the agent session time to finish any pending operations
        # This allows STT/TTS to complete gracefully
        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

        # 3. Disconnect from room (this triggers session cleanup).
        # Only when we opened it: in dispatch mode the agents framework owns the
        # room lifecycle and disconnecting here would race its own teardown.
        if room and owns_room:
            try:
                logger.info("[MAIN] Disconnecting from room...")
                await room.disconnect()
                logger.info("[MAIN] Room disconnected")
            except Exception as e:
                logger.warning(f"[MAIN] Room disconnect error (non-fatal): {e}")

        # 4. Wait a bit more for websockets to close gracefully
        try:
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass

        # 5. Close HTTP session LAST (after all plugins are done) — but only if
        # we created it. In dispatch mode it belongs to the job context, and
        # closing it would break the next job on this resident worker.
        if http_session and owns_http_session:
            try:
                logger.info("[MAIN] Closing HTTP session...")
                await http_session.close()
                logger.info("[MAIN] HTTP session closed")
            except Exception as e:
                logger.warning(f"[MAIN] HTTP session close error (non-fatal): {e}")

        logger.info("[MAIN] Cleanup complete")

        # A direct-mode process exists to serve exactly one interview, and exits
        # so worker_manager can reap it. A dispatch worker is RESIDENT and must
        # survive to accept the next job — exiting here would take the whole
        # agent pool down after a single interview.
        if owns_room:
            logger.info("[MAIN] Exiting worker process")
            sys.exit(0)


# ---------------------------------------------------------------------------
# Dispatch transport
# ---------------------------------------------------------------------------

async def dispatch_entrypoint(ctx):
    """
    LiveKit dispatch entrypoint. Called by the agents framework once per job.

    `ctx.room` arrives connected, `ctx.job.metadata` carries the interview config
    that direct mode reads off participant attributes, and the framework owns
    both the room lifecycle and the plugin HTTP session — so we hand all three to
    the shared `run_interview` body and let it skip the parts it does not own.
    """
    await ctx.connect()

    metadata = agent_mode.decode_job_metadata(getattr(ctx.job, 'metadata', None))
    logger.info(
        f"[DISPATCH] Job {getattr(ctx.job, 'id', '?')} for room {ctx.room.name} "
        f"(metadata keys: {sorted(metadata) or 'none'})"
    )

    # http_session stays None: under cli.run_app the plugins resolve their
    # session from the job context, which is why the direct-mode comment above
    # says one is only needed when running OUTSIDE cli.run_app.
    try:
        await run_interview(room=ctx.room, http_session=None, job_metadata=metadata)
    finally:
        # End the job explicitly. The framework waits on a shutdown future that is
        # only resolved by a room disconnect or this call — and the ownership
        # gating in run_interview deliberately skips room.disconnect() here. The
        # web client shows a modal at interview_ending but does not disconnect, so
        # without this the agent squats in the room with STT/TTS/VAD resident
        # after the interview has ended.
        try:
            ctx.shutdown(reason="interview complete")
        except Exception as e:
            logger.warning(f"[DISPATCH] ctx.shutdown failed (non-fatal): {e}")


def _run_dispatch_worker():
    """Run as a resident worker registered with a LiveKit project."""
    from livekit.agents import WorkerOptions, cli

    name = agent_mode.agent_name(os.environ)
    logger.info(f"[WORKER] Starting agent worker - DISPATCH MODE (agent_name={name})")

    # agent_name set => EXPLICIT dispatch: LiveKit only routes jobs created via
    # AgentDispatchService for this name, never every room in the project. That
    # matters because the web app also creates rooms it drives directly.
    cli.run_app(WorkerOptions(entrypoint_fnc=dispatch_entrypoint, agent_name=name))


def main():
    """Process entry point: resolve the environment, then serve this transport."""
    env = worker_env()
    if env['mode'] == agent_mode.MODE_DISPATCH:
        _run_dispatch_worker()
    else:
        logger.info("[WORKER] Starting agent worker - DIRECT ROOM CONNECTION MODE")
        asyncio.run(run_interview(env=env))


if __name__ == "__main__":
    main()
