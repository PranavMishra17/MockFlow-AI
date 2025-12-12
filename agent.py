"""
MockFlow-AI Interview Agent

LiveKit-based voice interview agent with FSM-driven stage management.
Implements self-introduction and past-experience interview stages with
explicit state transitions and fallback mechanisms.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Annotated
from dotenv import load_dotenv
from pydantic import Field

from livekit.agents import (
    AgentServer,
    AgentSession,
    JobContext,
    cli,
    Agent,
    RunContext,
    function_tool,
)
from livekit.plugins import openai, deepgram, silero

from fsm import InterviewState, InterviewStage

# Load environment variables from .env file in project root
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG for troubleshooting
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("interview-agent")

# Reduce noise from other loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Verify environment variables
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')
LIVEKIT_URL = os.getenv('LIVEKIT_URL')
LIVEKIT_API_KEY = os.getenv('LIVEKIT_API_KEY')
LIVEKIT_API_SECRET = os.getenv('LIVEKIT_API_SECRET')

if not OPENAI_API_KEY:
    logger.error("[CONFIG] Missing OPENAI_API_KEY environment variable")
if not DEEPGRAM_API_KEY:
    logger.error("[CONFIG] Missing DEEPGRAM_API_KEY environment variable")
if not LIVEKIT_URL:
    logger.error("[CONFIG] Missing LIVEKIT_URL environment variable")

logger.info(f"[CONFIG] LiveKit URL: {LIVEKIT_URL}")
logger.info(f"[CONFIG] OpenAI API Key present: {bool(OPENAI_API_KEY)}")
logger.info(f"[CONFIG] Deepgram API Key present: {bool(DEEPGRAM_API_KEY)}")

# Create agent server
server = AgentServer()

# Stage-specific instructions for the LLM
INSTRUCTIONS = {
    InterviewStage.GREETING: """
You are a friendly and professional interviewer named Alex conducting a mock interview.

Your task right now:
1. Greet the candidate warmly
2. Introduce yourself as Alex, an AI interviewer
3. EXPLAIN THE INTERVIEW STRUCTURE:
   - "This interview has 3 main stages:"
   - "Stage 1: Self-introduction - tell me about yourself (2-3 minutes)"
   - "Stage 2: Past experience - discuss your projects and work (3-4 minutes)"
   - "Stage 3: Closing - wrap up and next steps (1 minute)"
4. Ask if they're ready to begin
5. Once they confirm, transition immediately to self_intro stage using the transition_stage tool

Keep this entire greeting under 45 seconds. Be concise and clear.

IMPORTANT: As soon as the candidate says they're ready (e.g., "yes", "sure", "let's start", "I'm ready"),
call transition_stage immediately to move to self_intro.
""",

    InterviewStage.SELF_INTRO: """
You are conducting the self-introduction stage of a mock interview.

Your task:
- Ask the candidate to introduce themselves (background, education, current role)
- Listen actively to their response
- Ask ONE brief follow-up question to show engagement
- Keep this stage SHORT (2-3 minutes maximum)

TIMING RULES (CRITICAL):
- After hearing their introduction (about 1-2 minutes of them speaking), ask ONE follow-up
- After they answer that follow-up, IMMEDIATELY call transition_stage
- Do NOT ask multiple follow-ups
- Do NOT extend this stage beyond 2-3 minutes

When to transition:
- They've shared their background
- You've asked ONE follow-up and they've answered
- Call transition_stage with reason: "Candidate provided introduction"

Guidelines:
- Be encouraging but brief
- Focus on moving forward efficiently
""",

    InterviewStage.PAST_EXPERIENCE: """
You are now discussing the candidate's past experience in detail.

Your task:
- Reference something specific from their introduction
- Ask about ONE specific project or experience
- Let them explain the project, challenges, and solutions
- Keep this stage focused (3-4 minutes maximum)

TIMING RULES (CRITICAL):
- Ask about ONE project/experience
- Listen to their full explanation
- Ask ONE clarifying or follow-up question
- After they answer, IMMEDIATELY call transition_stage
- Do NOT ask about multiple projects
- Do NOT extend beyond 4 minutes

When to transition:
- They've described one project in detail
- They've explained challenges and solutions
- Call transition_stage with reason: "Candidate shared project experience"

Guidelines:
- Use STAR method prompts (Situation, Task, Action, Result)
- Focus on ONE specific example
- Be efficient with time
""",

    InterviewStage.CLOSING: """
You are wrapping up the interview.

Your task:
- Thank the candidate sincerely for their time
- Provide brief positive feedback on 1-2 strengths you noticed
- Let them know next steps will be communicated via email
- Wish them well
- Keep this brief (under 1 minute)

Style: Warm, professional, encouraging.
"""
}


class InterviewAgent(Agent):
    """
    Mock interview agent with FSM-based stage management.
    """

    def __init__(self):
        """Initialize agent with greeting stage instructions."""
        super().__init__(
            instructions=INSTRUCTIONS[InterviewStage.GREETING]
            # Tools are auto-registered via @function_tool decorator
        )

    @function_tool
    async def transition_stage(
        self,
        ctx: RunContext[InterviewState],
        reason: Annotated[str, Field(description="Brief reason for stage transition")]
    ) -> str:
        """
        Explicit stage transition called by LLM when ready to move forward.
        """
        try:
            current_stage = ctx.userdata.stage
            next_stage = ctx.userdata.get_next_stage()

            if not next_stage:
                return f"Cannot transition from {current_stage.value} - interview complete"

            time_in_stage = ctx.userdata.time_in_current_stage()

            # Minimum time gates (prevent rushing) - reduced for faster interviews
            MIN_TIMES = {
                InterviewStage.GREETING: 10,   # Reduced from 15
                InterviewStage.SELF_INTRO: 45,  # Reduced from 60
                InterviewStage.PAST_EXPERIENCE: 60,  # Reduced from 120
            }

            min_time = MIN_TIMES.get(current_stage, 0)
            if time_in_stage < min_time:
                return (
                    f"Please spend more time in this stage. "
                    f"Current: {time_in_stage:.0f}s, Minimum: {min_time}s"
                )

            # Execute transition
            ctx.userdata.transition_to(next_stage, forced=False)

            # Update agent instructions for new stage
            await self.update_instructions(INSTRUCTIONS[next_stage])

            logger.info(
                f"[AGENT] Stage transition: {current_stage.value} -> {next_stage.value} "
                f"(reason: {reason}, time_in_stage: {time_in_stage:.1f}s)"
            )

            # Emit stage change to UI
            await self._emit_stage_change(ctx, next_stage)

            transition_messages = {
                InterviewStage.SELF_INTRO: "Great, let's dive into your background and experience.",
                InterviewStage.PAST_EXPERIENCE: "Excellent introduction. Now I'd like to hear more about your past work experience.",
                InterviewStage.CLOSING: "Thank you for sharing your experiences with me.",
            }

            return transition_messages.get(next_stage, f"Transitioned to {next_stage.value}")

        except Exception as e:
            logger.error(f"[AGENT] Transition error: {e}", exc_info=True)
            return f"Error during transition: {str(e)}"

    async def _emit_stage_change(self, ctx: RunContext[InterviewState], new_stage: InterviewStage):
        """Emit stage change event to the room for UI updates."""
        try:
            import json

            data_payload = json.dumps({
                "type": "stage_change",
                "stage": new_stage.value
            })

            # Access room through the session
            room = ctx.session.room if hasattr(ctx.session, 'room') else None
            if room and room.local_participant:
                await room.local_participant.publish_data(
                    data_payload.encode('utf-8')
                )
                logger.info(f"[UI] Emitted stage change: {new_stage.value}")
            else:
                logger.warning(f"[UI] Cannot emit stage change - no room available")
        except Exception as e:
            logger.error(f"[UI] Failed to emit stage change: {e}")

    @function_tool
    async def record_response(
        self,
        ctx: RunContext[InterviewState],
        response_summary: Annotated[str, Field(description="Brief summary of candidate's key points")]
    ) -> str:
        """Record key points from candidate's response for analysis."""
        try:
            ctx.userdata.experience_responses.append(response_summary)
            logger.info(f"[AGENT] Recorded response: {response_summary[:100]}...")
            return "Response recorded. Continue the conversation naturally."
        except Exception as e:
            logger.error(f"[AGENT] Record response error: {e}", exc_info=True)
            return "Error recording response"

    async def on_enter(self):
        """Called when agent becomes active - trigger the greeting."""
        logger.info("[AGENT] Agent activated - generating greeting")
        # This triggers the LLM to generate a greeting based on instructions
        self.session.generate_reply(
            instructions="Greet the candidate warmly. Introduce yourself as Alex, an AI interviewer. Ask them to introduce themselves and tell you about their background."
        )

    async def on_exit(self):
        """Called when agent is deactivated."""
        logger.info("[AGENT] Agent deactivating")


async def emit_user_caption(ctx: JobContext, text: str):
    """Emit user caption to the UI."""
    try:
        import json

        data_payload = json.dumps({
            "type": "user_caption",
            "text": text
        })

        await ctx.room.local_participant.publish_data(
            data_payload.encode('utf-8')
        )

        logger.debug(f"[UI] Emitted user caption: {text[:50]}...")
    except Exception as e:
        logger.error(f"[UI] Failed to emit user caption: {e}")


async def emit_agent_caption(ctx: JobContext, text: str):
    """Emit agent caption to the UI."""
    try:
        import json

        data_payload = json.dumps({
            "type": "agent_caption",
            "text": text
        })

        await ctx.room.local_participant.publish_data(
            data_payload.encode('utf-8')
        )

        logger.debug(f"[UI] Emitted agent caption: {text[:50]}...")
    except Exception as e:
        logger.error(f"[UI] Failed to emit agent caption: {e}")


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    """
    Main entry point for LiveKit agent.
    """
    fallback_task = None
    
    try:
        # Connect to room
        await ctx.connect()
        logger.info(f"[SESSION] Connected to room: {ctx.room.name}")

        # Initialize interview state
        interview_state = InterviewState()
        interview_state.transition_to(InterviewStage.GREETING)

        # Log room participants
        logger.info(f"[SESSION] Room participants: {[p.identity for p in ctx.room.remote_participants.values()]}")

        # Create STT
        try:
            stt = deepgram.STT(
                model="nova-2",
                language="en-US",
                smart_format=True,
            )
            logger.info("[SESSION] Deepgram STT initialized")
        except Exception as e:
            logger.error(f"[SESSION] Deepgram STT init error: {e}")
            raise

        # Create LLM
        try:
            llm = openai.LLM(
                model="gpt-4o-mini",
                temperature=0.7,
            )
            logger.info("[SESSION] OpenAI LLM initialized")
        except Exception as e:
            logger.error(f"[SESSION] OpenAI LLM init error: {e}")
            raise

        # Create TTS
        try:
            tts = openai.TTS(
                voice="alloy",
                speed=1.0,
            )
            logger.info("[SESSION] OpenAI TTS initialized")
        except Exception as e:
            logger.error(f"[SESSION] OpenAI TTS init error: {e}")
            raise

        # Create VAD
        try:
            vad = silero.VAD.load()
            logger.info("[SESSION] Silero VAD initialized")
        except Exception as e:
            logger.error(f"[SESSION] Silero VAD init error: {e}")
            raise

        # Create agent
        agent = InterviewAgent()

        # Create agent session
        session = AgentSession(
            userdata=interview_state,
            stt=stt,
            llm=llm,
            tts=tts,
            vad=vad,
            allow_interruptions=True,
            min_endpointing_delay=0.5,
            max_endpointing_delay=3.0,
        )

        logger.info("[SESSION] AgentSession created")

        # Event handlers for logging and caption emission
        @session.on("user_input_transcribed")
        def on_user_speech(event):
            if event.is_final:
                logger.info(f"[USER] {event.transcript}")
                # Emit user caption to UI
                asyncio.create_task(emit_user_caption(ctx, event.transcript))

        @session.on("agent_speech_committed")
        def on_agent_speech(event):
            text = getattr(event, 'text', str(event))
            logger.info(f"[AGENT SPEECH] {text[:150]}...")
            # Emit agent caption to UI
            asyncio.create_task(emit_agent_caption(ctx, text))

        @session.on("agent_state_changed")
        def on_state_change(event):
            old_state = getattr(event, 'old_state', 'unknown')
            new_state = getattr(event, 'new_state', 'unknown')
            logger.info(f"[SESSION] Agent state: {old_state} -> {new_state}")

        # Start fallback timer
        fallback_task = asyncio.create_task(
            stage_fallback_timer(session, interview_state, ctx)
        )

        logger.info("[SESSION] Starting agent session")

        # Start the session - this MUST be awaited
        # The agent's on_enter() will trigger the greeting via generate_reply()
        await session.start(
            agent=agent, 
            room=ctx.room
        )
        
        logger.info("[SESSION] Session ended normally")

    except asyncio.CancelledError:
        logger.info("[SESSION] Session cancelled")
    except Exception as e:
        logger.error(f"[SESSION] Agent error: {e}", exc_info=True)
    finally:
        if fallback_task:
            fallback_task.cancel()
            try:
                await fallback_task
            except asyncio.CancelledError:
                pass
        logger.info("[SESSION] Session cleanup complete")


async def stage_fallback_timer(session: AgentSession, state: InterviewState, ctx: JobContext):
    """
    Enhanced fallback mechanism with time-based stage transitions.
    More aggressive timing for efficient interviews.
    """
    STAGE_LIMITS = {
        InterviewStage.GREETING: 60,   # Reduced from 90 - should transition quickly after explaining
        InterviewStage.SELF_INTRO: 180,  # Reduced from 360 - 3 minutes max
        InterviewStage.PAST_EXPERIENCE: 240,  # Reduced from 480 - 4 minutes max
        InterviewStage.CLOSING: 90,   # Reduced from 120
    }

    WARNING_THRESHOLD = 0.75  # Warn earlier (75% instead of 80%)

    try:
        while True:
            await asyncio.sleep(20)  # Check more frequently (every 20s instead of 30s)

            current_stage = state.verify_state()
            time_in_stage = state.time_in_current_stage()
            limit = STAGE_LIMITS.get(current_stage, 600)
            warning_time = limit * WARNING_THRESHOLD

            logger.info(
                f"[FALLBACK] Stage: {current_stage.value}, "
                f"Time: {time_in_stage:.0f}s / {limit}s"
            )

            if time_in_stage > warning_time and time_in_stage < limit:
                logger.warning(
                    f"[FALLBACK] Stage {current_stage.value} approaching time limit "
                    f"({time_in_stage:.0f}s / {limit}s)"
                )

            if time_in_stage > limit:
                next_stage = state.get_next_stage()

                if next_stage:
                    logger.warning(
                        f"[FALLBACK] FORCING stage transition: "
                        f"{current_stage.value} -> {next_stage.value} "
                        f"(exceeded {limit}s limit)"
                    )
                    state.transition_to(next_stage, forced=True)

                    # Emit stage change to UI
                    try:
                        import json

                        data_payload = json.dumps({
                            "type": "stage_change",
                            "stage": next_stage.value
                        })

                        await ctx.room.local_participant.publish_data(
                            data_payload.encode('utf-8')
                        )

                        logger.info(f"[UI] Emitted forced stage change: {next_stage.value}")
                    except Exception as e:
                        logger.error(f"[UI] Failed to emit forced stage change: {e}")

                    # Announce transition
                    try:
                        transition_announcements = {
                            InterviewStage.SELF_INTRO: "Let's move on to discuss your background.",
                            InterviewStage.PAST_EXPERIENCE: "Now, tell me about your past work experience.",
                            InterviewStage.CLOSING: "Let's wrap up the interview.",
                        }
                        announcement = transition_announcements.get(
                            next_stage,
                            "Let's continue to the next part."
                        )
                        await session.say(announcement)
                    except Exception as e:
                        logger.error(f"[FALLBACK] Error announcing transition: {e}")

    except asyncio.CancelledError:
        logger.info("[FALLBACK] Fallback timer cancelled")
    except Exception as e:
        logger.error(f"[FALLBACK] Fallback timer error: {e}", exc_info=True)


if __name__ == "__main__":
    logger.info("[MAIN] Starting MockFlow-AI Interview Agent")
    cli.run_app(server)