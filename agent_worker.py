"""
MockFlow-AI Interview Agent Worker

Standalone agent that runs as a subprocess with API keys passed via environment
variables. Uses an explicit room connection rather than LiveKit dispatch, and
terminates automatically after the interview ends.

This file is now only the parts that are genuinely about being in a room:
validating the environment, minting a token, connecting, waiting for the
participant, building the voice plugins, and saving the interview when it ends.

The interview itself — the agent, its tools, the FSM wiring, command dispatch
and the transcript — lives in `interview_runtime.py`, which imports with no
environment at all so it can be driven without LiveKit.
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

#: Environment this worker cannot start without.
REQUIRED_ENV = (
    'OPENAI_API_KEY',
    'DEEPGRAM_API_KEY',
    'LIVEKIT_URL',
    'LIVEKIT_API_KEY',
    'LIVEKIT_API_SECRET',
    'INTERVIEW_ROOM_NAME',
)


def validate_env() -> None:
    """Fail fast on missing configuration.

    Deliberately called from `main()` rather than at import. When this check ran
    at module scope, importing this file at all required a full LiveKit
    environment — which meant no test could import it, and the interview logic
    inside was unreachable from anything but a live room.
    """
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        logger.error("[CONFIG] Missing required API keys or room name in environment")
        for name in REQUIRED_ENV:
            logger.error(f"[CONFIG] {name}: {bool(os.getenv(name))}")
        sys.exit(1)

    logger.info("[CONFIG] API keys loaded from environment")
    logger.info(f"[CONFIG] LiveKit URL: {os.getenv('LIVEKIT_URL')}")
    logger.info(f"[CONFIG] Target Room: {os.getenv('INTERVIEW_ROOM_NAME')}")


def _build_voice_components(http_session: aiohttp.ClientSession):
    """Construct STT / LLM / TTS / VAD, or raise with which one failed.

    Only Deepgram STT needs the shared HTTP session when running outside
    `cli.run_app()`; the OpenAI plugins use their own client.
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


async def _connect_to_room() -> Room:
    """Mint an agent token for the configured room and connect to it."""
    room_name = os.getenv('INTERVIEW_ROOM_NAME')

    token = livekit_api.AccessToken(
        os.getenv('LIVEKIT_API_KEY'), os.getenv('LIVEKIT_API_SECRET')
    )
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
    logger.info(f"[MAIN] Connecting to LiveKit: {os.getenv('LIVEKIT_URL')}")
    await room.connect(os.getenv('LIVEKIT_URL'), agent_token)
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


async def run_interview():
    """Main entry point — connects explicitly to one room and runs one interview."""
    room_name = os.getenv('INTERVIEW_ROOM_NAME')
    logger.info(f"[MAIN] Starting interview agent for room: {room_name}")

    interview_complete = asyncio.Event()
    fallback_task = None
    http_session = None
    room = None

    try:
        # Shared HTTP session for plugins, required when not using cli.run_app()
        http_session = aiohttp.ClientSession()
        logger.info("[MAIN] Created shared HTTP session for plugins")

        room = await _connect_to_room()
        transport = RoomTransport(room)

        participant = await _wait_for_participant(room)
        if participant is None:
            await room.disconnect()
            return

        # One parser for both transports. Participant attributes are all strings;
        # normalize_config is what turns them into the interview's config shape.
        attributes = getattr(participant, 'attributes', None) or {}
        config = agent_mode.normalize_config(attributes)

        candidate_name = _candidate_name_from_room(room.name)
        user_id = config.get('user_id')
        track_type = config.get('track', 'intro')

        logger.info(
            f"[MAIN] Participant attributes - Role: {config.get('role')}, "
            f"Level: {config.get('level')}, Resume: {bool(config.get('resume_text'))}"
        )
        logger.info(
            f"[MAIN] Track: {track_type}, Framework: {config.get('framework')}, "
            f"Depth: {config.get('depth')}, Topics: {config.get('topics')}"
        )
        logger.info(
            f"[MAIN] Candidate: {candidate_name} "
            f"(Role: {config.get('role')}, Level: {config.get('level')})"
        )

        track_config = get_track_config(track_type)
        interview_state = build_interview_state(config, candidate_name=candidate_name)

        stt, llm, tts, vad = _build_voice_components(http_session)

        agent = InterviewAgent(
            transport=transport,
            candidate_info={'name': candidate_name, 'role': config.get('role')},
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

                from supabase_client import supabase_client
                interview_id = supabase_client.save_interview(user_id, interview_data)

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
                interview_id = supabase_client.save_interview(user_id, interview_data)

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

        # 3. Disconnect from room (this triggers session cleanup)
        if room:
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

        # 5. Close HTTP session LAST (after all plugins are done)
        if http_session:
            try:
                logger.info("[MAIN] Closing HTTP session...")
                await http_session.close()
                logger.info("[MAIN] HTTP session closed")
            except Exception as e:
                logger.warning(f"[MAIN] HTTP session close error (non-fatal): {e}")

        logger.info("[MAIN] Cleanup complete, exiting")
        sys.exit(0)


def main():
    """Process entry point: validate the environment, then run one interview."""
    validate_env()
    logger.info("[WORKER] Starting agent worker - DIRECT ROOM CONNECTION MODE")
    asyncio.run(run_interview())


if __name__ == "__main__":
    main()
