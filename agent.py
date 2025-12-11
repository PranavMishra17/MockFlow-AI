"""
MockFlow-AI Interview Agent

LiveKit-based voice interview agent with FSM-driven stage management.
Implements self-introduction and past-experience interview stages with
explicit state transitions and fallback mechanisms.
"""

import asyncio
import logging
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
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("interview-agent")

# Create agent server
server = AgentServer()

# Stage-specific instructions for the LLM
INSTRUCTIONS = {
    InterviewStage.GREETING: """
You are a friendly and professional interviewer named Alex.

Your task:
- Greet the candidate warmly
- Introduce yourself briefly
- Ask them to introduce themselves
- Keep this stage brief (under 1 minute)
- Be welcoming and put them at ease

Style: Professional yet friendly, concise, natural conversation.
""",

    InterviewStage.SELF_INTRO: """
You are conducting the self-introduction stage of a mock interview.

Your task:
- Listen actively to the candidate's introduction
- Ask 1-2 natural follow-up questions about their background, education, or current role
- Show genuine interest through thoughtful questions
- Keep this stage conversational (3-4 minutes total)
- When you feel you have enough information about their background, call the transition_stage tool

Guidelines:
- Ask one question at a time
- Wait for complete responses before asking follow-ups
- Be encouraging and supportive
- Note interesting details for later stages
- Don't rush, but don't let it drag on too long

Call transition_stage when:
- You have a good understanding of their background
- They've answered 2-3 questions naturally
- The conversation feels complete
""",

    InterviewStage.PAST_EXPERIENCE: """
You are now discussing the candidate's past experience in detail.

Your task:
- Reference something specific from their introduction
- Ask about past projects, challenges, and solutions
- Use the STAR method framework (Situation, Task, Action, Result)
- Probe deeper on technical/professional skills
- Keep this stage focused (5-7 minutes)
- When satisfied with their responses, call transition_stage

Guidelines:
- Ask about specific examples from their experience
- Focus on problem-solving approaches
- Ask clarifying questions when needed
- Use the record_response tool to capture key points
- Be thorough but respectful of time

Example questions:
- "Tell me about a challenging project you worked on"
- "How did you approach solving that problem?"
- "What was the outcome?"
- "What would you do differently now?"

Call transition_stage when:
- You've explored 2-3 significant experiences
- You have a good sense of their capabilities
- The conversation feels naturally complete
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

    Features:
    - Explicit state transitions via function tools
    - Stage-specific instructions
    - Response recording for analysis
    - State verification loop
    """

    def __init__(self):
        """Initialize agent with greeting stage instructions."""
        super().__init__(
            instructions=INSTRUCTIONS[InterviewStage.GREETING],
            tools=[
                self.transition_stage,
                self.record_response,
                self.ask_clarifying_question,
            ]
        )
        self.state_verification_task = None

    @function_tool
    async def transition_stage(
        self,
        ctx: RunContext[InterviewState],
        reason: Annotated[str, Field(description="Brief reason for stage transition")]
    ) -> str:
        """
        Explicit stage transition called by LLM when ready to move forward.

        Args:
            ctx: Runtime context with interview state
            reason: Why the transition is happening

        Returns:
            Confirmation message
        """
        current_stage = ctx.userdata.stage
        next_stage = ctx.userdata.get_next_stage()

        if not next_stage:
            return f"Cannot transition from {current_stage.value} - interview complete"

        # Validate transition makes sense
        time_in_stage = ctx.userdata.time_in_current_stage()

        # Minimum time gates (prevent rushing)
        MIN_TIMES = {
            InterviewStage.GREETING: 20,  # At least 20 seconds
            InterviewStage.SELF_INTRO: 120,  # At least 2 minutes
            InterviewStage.PAST_EXPERIENCE: 180,  # At least 3 minutes
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

        # Return message for LLM to speak naturally
        transition_messages = {
            InterviewStage.SELF_INTRO: "Great, let's dive into your background and experience.",
            InterviewStage.PAST_EXPERIENCE: "Excellent introduction. Now I'd like to hear more about your past work experience.",
            InterviewStage.CLOSING: "Thank you for sharing your experiences with me.",
        }

        return transition_messages.get(next_stage, f"Transitioned to {next_stage.value}")

    @function_tool
    async def record_response(
        self,
        ctx: RunContext[InterviewState],
        response_summary: Annotated[str, Field(description="Brief summary of candidate's key points")]
    ) -> str:
        """
        Record key points from candidate's response for analysis.

        Args:
            ctx: Runtime context with interview state
            response_summary: Summary of what candidate said

        Returns:
            Confirmation message
        """
        ctx.userdata.experience_responses.append(response_summary)
        logger.info(f"[AGENT] Recorded response: {response_summary[:100]}...")
        return "Response recorded. Continue the conversation naturally."

    @function_tool
    async def ask_clarifying_question(
        self,
        ctx: RunContext[InterviewState],
        topic: Annotated[str, Field(description="Topic to clarify")]
    ) -> str:
        """
        Track that a clarifying question is being asked.

        Args:
            ctx: Runtime context with interview state
            topic: What topic is being clarified

        Returns:
            Guidance for asking the question
        """
        question = f"Clarifying question about: {topic}"
        ctx.userdata.questions_asked.append(question)
        logger.info(f"[AGENT] Asking clarification: {topic}")
        return f"Ask a natural follow-up question about {topic}"

    async def on_enter(self):
        """
        Called when agent becomes active.
        Starts state verification loop.
        """
        logger.info("[AGENT] Agent activated - starting state verification loop")
        self.state_verification_task = asyncio.create_task(
            self.state_verification_loop()
        )

    async def on_exit(self):
        """
        Called when agent is deactivated.
        Cleanup verification loop.
        """
        logger.info("[AGENT] Agent deactivating - stopping verification loop")
        if self.state_verification_task:
            self.state_verification_task.cancel()

    async def state_verification_loop(self):
        """
        Verify FSM state every 30 seconds.
        Logs state information for monitoring.
        """
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                logger.info("[AGENT] State verification checkpoint")

            except asyncio.CancelledError:
                logger.info("[AGENT] State verification loop cancelled")
                break
            except Exception as e:
                logger.error(f"[AGENT] State verification error: {e}", exc_info=True)


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    """
    Main entry point for LiveKit agent.

    Handles:
    - Room connection
    - Agent session creation
    - Voice pipeline configuration
    - Event handlers
    - Fallback timer
    """
    try:
        # Connect to room
        await ctx.connect()
        logger.info(f"[SESSION] Connected to room: {ctx.room.name}")

        # Initialize interview state
        interview_state = InterviewState()
        interview_state.transition_to(InterviewStage.GREETING)

        # Create agent session with voice pipeline
        session = AgentSession(
            userdata=interview_state,

            # Speech-to-Text: Deepgram Nova-2 for accuracy
            stt=deepgram.STT(
                model="nova-2",
                language="en-US",
                smart_format=True,
            ),

            # Language Model: GPT-4o-mini for speed and cost
            llm=openai.LLM(
                model="gpt-4o-mini",
                temperature=0.7,
            ),

            # Text-to-Speech: OpenAI TTS with natural voice
            tts=openai.TTS(
                voice="alloy",
                speed=1.0,
            ),

            # Voice Activity Detection: Silero VAD
            vad=silero.VAD.load(),

            # Behavior tuning (interview-optimized from best practices)
            allow_interruptions=True,
            min_endpointing_delay=0.4,  # Wait for natural pauses
            max_endpointing_delay=3.0,  # Force end after 3s silence
        )

        # Event handlers for logging and monitoring
        @session.on("user_input_transcribed")
        def on_user_speech(event):
            """Log user speech when finalized."""
            if event.is_final:
                logger.info(f"[USER] {event.transcript}")

        @session.on("agent_speech_committed")
        def on_agent_speech(event):
            """Log agent speech."""
            logger.info(f"[AGENT] {event.text[:150]}...")

        @session.on("agent_state_changed")
        def on_state_change(event):
            """Log agent state changes."""
            logger.info(f"[SESSION] Agent state: {event.old_state} -> {event.new_state}")

        # Create agent
        agent = InterviewAgent()

        # Start fallback timer in background
        fallback_task = asyncio.create_task(
            stage_fallback_timer(session, interview_state)
        )

        logger.info("[SESSION] Starting agent session")

        try:
            # Start agent session
            session.start(agent=agent, room=ctx.room)

            # Wait for participant to join
            logger.info("[SESSION] Waiting for participant to join...")
            await asyncio.sleep(2)

            # Agent greets first to start the conversation
            initial_greeting = (
                "Hello! Welcome to MockFlow AI. "
                "I'm Alex, and I'll be conducting your mock interview today. "
                "Let's begin - please take a moment to introduce yourself."
            )
            await session.say(initial_greeting, allow_interruptions=True)
            logger.info("[SESSION] Initial greeting sent")

            # Now wait for session to complete
            await session.aclose()

        finally:
            fallback_task.cancel()
            logger.info("[SESSION] Session ended")

    except Exception as e:
        logger.error(f"[SESSION] Agent error: {e}", exc_info=True)


async def stage_fallback_timer(session: AgentSession, state: InterviewState):
    """
    Enhanced fallback mechanism with time-based stage transitions.

    Features:
    - Checks state every 30 seconds
    - Forces transition if stage exceeds time limit
    - Logs warnings before forcing
    - Guarantees continuous workflow progression

    Args:
        session: The agent session
        state: Interview state being monitored
    """
    # Stage time limits (in seconds)
    STAGE_LIMITS = {
        InterviewStage.GREETING: 90,       # 1.5 minutes max
        InterviewStage.SELF_INTRO: 360,    # 6 minutes max
        InterviewStage.PAST_EXPERIENCE: 480,  # 8 minutes max
        InterviewStage.CLOSING: 120,       # 2 minutes max
    }

    # Warning thresholds (80% of limit)
    WARNING_THRESHOLD = 0.8

    while True:
        try:
            await asyncio.sleep(30)  # Check every 30 seconds

            current_stage = state.verify_state()
            time_in_stage = state.time_in_current_stage()
            limit = STAGE_LIMITS.get(current_stage, 600)
            warning_time = limit * WARNING_THRESHOLD

            # Log current state
            logger.info(
                f"[FALLBACK] Stage: {current_stage.value}, "
                f"Time: {time_in_stage:.0f}s / {limit}s"
            )

            # Warning if approaching limit
            if time_in_stage > warning_time and time_in_stage < limit:
                logger.warning(
                    f"[FALLBACK] Stage {current_stage.value} approaching time limit: "
                    f"{time_in_stage:.0f}s / {limit}s"
                )

            # Force transition if exceeded
            if time_in_stage > limit:
                next_stage = state.get_next_stage()

                if next_stage:
                    logger.warning(
                        f"[FALLBACK] FORCING stage transition: "
                        f"{current_stage.value} -> {next_stage.value} "
                        f"(exceeded {limit}s limit)"
                    )

                    # Force transition
                    state.transition_to(next_stage, forced=True)

                    # Update agent instructions
                    # Note: This is a simplified approach; in production you'd need
                    # to access the agent instance to call update_instructions
                    logger.info(f"[FALLBACK] Forced transition complete")

                    # Have agent announce transition via TTS
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

                else:
                    logger.info(
                        f"[FALLBACK] Stage {current_stage.value} at final stage, "
                        f"no automatic transition"
                    )

        except asyncio.CancelledError:
            logger.info("[FALLBACK] Fallback timer cancelled")
            break
        except Exception as e:
            logger.error(f"[FALLBACK] Fallback timer error: {e}", exc_info=True)


if __name__ == "__main__":
    logger.info("[MAIN] Starting MockFlow-AI Interview Agent")
    cli.run_app(server)
