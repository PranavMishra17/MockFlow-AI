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
You are a friendly interviewer named Alex.

STEP 1: Say EXACTLY this greeting (nothing more):
"Hello! This interview will be divided into 2 stages: self-introduction and past experiences. Let's begin - tell me about yourself."

STEP 2: After you finish speaking the greeting, IMMEDIATELY call transition_stage to move to self_intro.

Do NOT wait for the candidate's response before calling transition_stage.
""",

    InterviewStage.SELF_INTRO: """
You are conducting the self-introduction stage of a mock interview.

Your task:
1. First, ask the candidate to introduce themselves (background, education, current role)
2. Listen actively to their response
3. IMPORTANT: After they respond, call assess_response to evaluate the depth and quality of their introduction
4. Based on the assessment result:
   - If adequate (depth >= 3): Ask ONE brief clarifying question, then call transition_stage
   - If insufficient (depth < 3): Ask 1-2 specific follow-up questions to get more detail
5. Before asking ANY question, you MUST call ask_question tool to verify it hasn't been asked before
6. Keep this stage SHORT (2-3 minutes maximum)

CRITICAL RULES:
- Call assess_response AFTER EVERY candidate response to determine next action
- Call ask_question BEFORE asking ANY question to prevent repetition
- Do NOT ask repetitive or similar questions
- Do NOT transition until you have adequate context (assessed depth >= 3)
- Maximum 3 questions total in this stage (including initial introduction request)

When to transition:
- Candidate has provided adequate introduction (assessed at depth >= 3)
- You've asked clarifying questions based on assessment
- Call transition_stage with reason: "Candidate provided sufficient introduction"

Guidelines:
- Be encouraging and supportive
- Show genuine interest in their background
- Focus on understanding their experience relevant to the role
- Keep questions focused and avoid repetition
""",

    InterviewStage.PAST_EXPERIENCE: """
You are now discussing the candidate's past experience in detail.

Your task:
1. Reference something specific from their introduction
2. Ask about ONE specific project or experience that's relevant to the role they're applying for
3. Let them explain the project, their role, challenges faced, and solutions implemented
4. IMPORTANT: After they respond, call assess_response to evaluate the depth and detail of their explanation
5. Based on the assessment result:
   - If detailed (depth >= 4): Ask ONE final question about impact/results, then call transition_stage
   - If surface-level (depth 2-3): Ask follow-up about their role, challenges, or technical decisions
   - If vague (depth < 2): Ask detailed STAR method question to probe deeper
6. Before asking ANY question, you MUST call ask_question tool to verify it hasn't been asked before
7. Keep this stage focused (3-4 minutes maximum)

CRITICAL RULES:
- Call assess_response AFTER EVERY candidate response to determine next action
- Call ask_question BEFORE asking ANY question to prevent repetition
- Do NOT ask repetitive or generic questions
- Do NOT transition until adequate detail is provided (assessed depth >= 4)
- Maximum 3 questions total in this stage (including initial project question)
- Use STAR method (Situation, Task, Action, Result) to probe depth when needed

When to transition:
- Candidate has explained ONE project in sufficient detail (assessed depth >= 4)
- They've covered their role, challenges, approach, and results
- Call transition_stage with reason: "Candidate shared detailed project experience"

Guidelines:
- Be genuinely curious about their work
- Reference the specific role they're applying for
- Probe technical details and decision-making when relevant
- Focus on understanding one project deeply, not multiple projects superficially
- Show appreciation for detailed explanations
""",

    InterviewStage.CLOSING: """
You are wrapping up the interview.

Your task:
- Thank the candidate sincerely for their time
- Provide brief positive feedback on 1-2 strengths you noticed
- Let them know next steps will be communicated via email
- Say a warm goodbye: "Thank you again, and best of luck!"
- Keep this VERY brief (under 30 seconds)

After saying goodbye, the interview will automatically end.

Style: Warm, professional, encouraging.
"""
}


class InterviewAgent(Agent):
    """
    Mock interview agent with FSM-based stage management.
    """

    def __init__(self, room=None, candidate_info=None):
        """Initialize agent with greeting stage instructions."""
        # Store candidate info
        self.candidate_info = candidate_info or {}
        self.candidate_name = self.candidate_info.get('name', 'Candidate')
        self.candidate_role = self.candidate_info.get('role', 'this position')

        # Build personalized greeting instruction
        personalized_greeting = INSTRUCTIONS[InterviewStage.GREETING].replace(
            "tell me about yourself",
            f"tell me about yourself, {self.candidate_name}"
        )

        super().__init__(
            instructions=personalized_greeting
            # Tools are auto-registered via @function_tool decorator
        )
        self.room = room  # Store room reference for data emission

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
                InterviewStage.GREETING: 0,   # No minimum - transition immediately after greeting
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

            # Get base stage instructions
            stage_instructions = INSTRUCTIONS[next_stage]

            # Add role-specific context guidance
            role_context = self._get_role_context(ctx.userdata)

            # Add consistent personality note with role/level context
            personality_note = f"""

IMPORTANT: The candidate's name is {self.candidate_name}.
They are applying for: {ctx.userdata.job_role or 'a technical position'}
Experience level: {ctx.userdata.experience_level or 'mid-level'}

{role_context}

Use their name naturally during the conversation. Maintain a warm, professional tone consistent with Alex the AI interviewer. Be encouraging and supportive.
"""

            personalized_instructions = stage_instructions + personality_note

            # Update agent instructions for new stage
            await self.update_instructions(personalized_instructions)

            logger.info(
                f"[AGENT] Stage transition: {current_stage.value} -> {next_stage.value} "
                f"(reason: {reason}, time_in_stage: {time_in_stage:.1f}s)"
            )

            # Emit stage change to UI
            await self._emit_stage_change(ctx, next_stage)

            # Trigger agent to speak based on new stage instructions
            transition_prompts = {
                InterviewStage.SELF_INTRO: f"Stage transitioned successfully. The greeting has been said. Now immediately respond by acknowledging {self.candidate_name}'s upcoming introduction. You don't need to ask them to introduce themselves again - they are already speaking or about to speak.",
                InterviewStage.PAST_EXPERIENCE: f"Stage transitioned successfully. Now immediately ask {self.candidate_name} about ONE specific project or experience they mentioned in their introduction. Be specific and reference something they said.",
                InterviewStage.CLOSING: f"Stage transitioned successfully. Now immediately thank {self.candidate_name} warmly, provide 1-2 specific positive observations from the interview, and say goodbye.",
            }

            prompt = transition_prompts.get(next_stage, "Continue with the interview.")

            # Return prompt to trigger agent response
            return prompt

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

            # Use room stored in agent instance
            if self.room and self.room.local_participant:
                await self.room.local_participant.publish_data(
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

    @function_tool
    async def ask_question(
        self,
        ctx: RunContext[InterviewState],
        question: Annotated[str, Field(description="The exact question you want to ask the candidate")]
    ) -> str:
        """
        Validate and track questions before asking to prevent repetition.

        This tool MUST be called before asking any question to the candidate.
        Returns approval if question is new, or rejection if similar question was already asked.
        """
        try:
            # Normalize for comparison (case-insensitive, ignore punctuation)
            normalized = question.lower().strip().rstrip('?.,!')

            # Check if similar question already asked
            for asked in ctx.userdata.questions_asked:
                asked_normalized = asked.lower().strip().rstrip('?.,!')

                # Check for exact match
                if normalized == asked_normalized:
                    logger.warning(f"[AGENT] Rejected duplicate question: '{question}'")
                    return f"You already asked this exact question: '{asked}'. Please ask something different to avoid repetition."

                # Check if new question is substring of previous (too similar)
                if normalized in asked_normalized or asked_normalized in normalized:
                    logger.warning(f"[AGENT] Rejected similar question: '{question}' (similar to: '{asked}')")
                    return f"You already asked a very similar question: '{asked}'. Please ask something different."

            # Question is unique - track it
            ctx.userdata.questions_asked.append(question)
            logger.info(f"[AGENT] Approved question #{len(ctx.userdata.questions_asked)}: {question}")

            return f"Question approved. You may now ask the candidate: '{question}'"

        except Exception as e:
            logger.error(f"[AGENT] Question validation error: {e}", exc_info=True)
            return "Error validating question. Please try again."

    @function_tool
    async def assess_response(
        self,
        ctx: RunContext[InterviewState],
        depth_score: Annotated[int, Field(description="Response depth rating: 1=very vague, 2=surface-level, 3=adequate, 4=detailed, 5=comprehensive")],
        key_points_covered: Annotated[list[str], Field(description="List of key points mentioned by candidate in their response")]
    ) -> str:
        """
        Assess the quality and depth of candidate's response to determine next action.

        Use this tool AFTER the candidate responds to evaluate if you need follow-up questions
        or if you can proceed to the next stage.

        Returns guidance on whether to ask follow-up questions or transition stages.
        """
        try:
            current_stage = ctx.userdata.stage

            # Store response summary for analysis
            response_summary = f"Depth: {depth_score}/5. Key points: {', '.join(key_points_covered)}"
            ctx.userdata.experience_responses.append(response_summary)

            logger.info(
                f"[AGENT] Response assessment - Stage: {current_stage.value}, "
                f"Depth: {depth_score}/5, Points: {len(key_points_covered)}"
            )

            # Decision logic based on stage and quality
            if current_stage == InterviewStage.SELF_INTRO:
                if depth_score >= 3:
                    # Adequate introduction - can transition after one brief follow-up
                    return (
                        "Response was adequate (depth 3+). The candidate provided sufficient context. "
                        "Ask ONE brief clarifying question to show engagement, then call transition_stage."
                    )
                elif depth_score == 2:
                    # Surface-level - need one focused follow-up
                    return (
                        "Response was surface-level (depth 2). Ask ONE specific follow-up question "
                        "to get more detail about their background, key skills, or career goals. "
                        "Do NOT transition yet."
                    )
                else:  # depth_score == 1
                    # Very vague - need detailed follow-up
                    return (
                        "Response was too vague (depth 1). Ask ONE detailed question to understand "
                        "their background, education, or current role better. Do NOT transition yet."
                    )

            elif current_stage == InterviewStage.PAST_EXPERIENCE:
                if depth_score >= 4:
                    # Detailed project explanation - can transition
                    return (
                        "Response was detailed (depth 4+). Ask ONE final clarifying question "
                        "about the impact or results of their work, then call transition_stage."
                    )
                elif depth_score == 3:
                    # Adequate but could use more depth
                    return (
                        "Response was adequate (depth 3) but could be deeper. Ask ONE follow-up "
                        "about their specific role, challenges they faced, or technical decisions made. "
                        "Do NOT transition yet."
                    )
                elif depth_score == 2:
                    # Surface-level - need STAR method prompting
                    return (
                        "Response was surface-level (depth 2). Ask ONE detailed question using STAR "
                        "method to probe their role (Task), the challenges (Situation), their approach "
                        "(Action), and outcomes (Result). Do NOT transition yet."
                    )
                else:  # depth_score == 1
                    # Very vague - need much more detail
                    return (
                        "Response was too vague (depth 1). Ask a detailed question about a specific "
                        "project: What was the project? What was your role? What challenges did you face? "
                        "Do NOT transition yet."
                    )

            # Default for other stages
            return "Assessment recorded. Continue with the interview naturally."

        except Exception as e:
            logger.error(f"[AGENT] Response assessment error: {e}", exc_info=True)
            return "Error assessing response. Continue with the interview."

    def _get_role_context(self, state: InterviewState) -> str:
        """
        Generate role-specific interview guidance based on job role and experience level.

        Returns a formatted string with focus areas and expectations for the specific role/level.
        """
        role = state.job_role.lower() if state.job_role else ""
        level = state.experience_level.lower() if state.experience_level else "mid"

        # Role-specific focus areas (what to probe in questions)
        role_keywords = {
            'engineer': 'technical skills, problem-solving approaches, system design decisions',
            'developer': 'coding practices, frameworks/tools used, debugging and optimization',
            'software': 'technical architecture, development process, code quality practices',
            'manager': 'team leadership, project planning, stakeholder communication, conflict resolution',
            'product': 'product strategy, user research, roadmap prioritization, cross-functional collaboration',
            'designer': 'design process, user research methods, collaboration with engineers, design systems',
            'analyst': 'data analysis techniques, business insights, technical tools proficiency, reporting',
            'qa': 'testing strategies, automation, bug tracking, quality assurance processes',
            'devops': 'infrastructure, CI/CD pipelines, monitoring, cloud platforms, automation',
        }

        # Level-specific expectations (depth and scope of questions)
        level_expectations = {
            'entry': 'Focus on learning approach, academic/personal projects, foundational skills, and willingness to learn.',
            'junior': 'Focus on recent projects, technical growth, mentorship received, and hands-on experience.',
            'mid': 'Focus on independent project ownership, technical decisions, collaboration, and problem-solving.',
            'senior': 'Focus on system design, mentoring others, technical leadership, and architectural decisions.',
            'lead': 'Focus on architecture strategy, team guidance, cross-team impact, and technical vision.',
            'staff': 'Focus on organization-wide impact, technical strategy, mentoring leads, and long-term planning.',
        }

        # Find matching role guidance
        role_focus = "technical experience and problem-solving approaches"
        for key, focus in role_keywords.items():
            if key in role:
                role_focus = focus
                break

        # Get level guidance
        level_guidance = level_expectations.get(level, level_expectations['mid'])

        return f"""
For this {state.job_role or 'position'} role ({level} level):
- Key focus areas: {role_focus}
- {level_guidance}
- Tailor your questions to probe relevant experience for this specific role and level.
- Reference their role and level naturally in questions when appropriate.
"""

    async def on_enter(self):
        """Called when agent becomes active - trigger the greeting."""
        logger.info(f"[AGENT] Agent activated - greeting {self.candidate_name}")
        # This triggers the LLM to generate a greeting based on instructions
        self.session.generate_reply(
            instructions=f"Say: 'Hello! This interview will be divided into 2 stages: self-introduction and past experiences. Let's begin - tell me about yourself, {self.candidate_name}.' Then immediately call transition_stage."
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

        logger.info(f"[UI] Attempting to emit agent caption: {text[:50]}...")

        await ctx.room.local_participant.publish_data(
            data_payload.encode('utf-8')
        )

        logger.info(f"[UI] Successfully emitted agent caption")
    except Exception as e:
        logger.error(f"[UI] Failed to emit agent caption: {e}", exc_info=True)


async def delayed_disconnect(room, delay: float = 2.0):
    """Disconnect from the room after a brief delay."""
    try:
        await asyncio.sleep(delay)
        logger.info(f"[SESSION] Disconnecting after {delay}s delay")
        await room.disconnect()
    except Exception as e:
        logger.error(f"[SESSION] Error during delayed disconnect: {e}", exc_info=True)


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

        # Extract candidate info from room name (format: interview-name-timestamp)
        room_parts = ctx.room.name.split('-')
        candidate_name = ' '.join(room_parts[1:-1]).title() if len(room_parts) > 2 else "Candidate"

        # Try to get candidate info from remote participant attributes
        # Wait a moment for participant to join if not already present
        role = 'this position'
        level = 'mid'
        email = ''

        if ctx.room.remote_participants:
            # Get first remote participant (should be the candidate)
            participant = list(ctx.room.remote_participants.values())[0]
            if hasattr(participant, 'attributes') and participant.attributes:
                role = participant.attributes.get('role', 'this position')
                level = participant.attributes.get('level', 'mid')
                email = participant.attributes.get('email', '')
                logger.info(f"[SESSION] Retrieved candidate metadata - Role: {role}, Level: {level}")
            else:
                logger.warning("[SESSION] Participant has no attributes, using defaults")
        else:
            logger.warning("[SESSION] No remote participants yet, using defaults")

        # Create candidate info dict
        candidate_info = {
            'name': candidate_name,
            'role': role
        }

        logger.info(f"[SESSION] Candidate: {candidate_name} (Role: {role}, Level: {level})")

        # Initialize interview state with full candidate context
        interview_state = InterviewState()
        interview_state.candidate_name = candidate_name
        interview_state.candidate_email = email
        interview_state.job_role = role
        interview_state.experience_level = level
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

        # Create agent with room reference and candidate info
        agent = InterviewAgent(room=ctx.room, candidate_info=candidate_info)

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

        # Conversation history storage for analysis
        conversation_history = {
            "agent": [],  # List of agent messages: [{"index": 0, "text": "...", "timestamp": ...}, ...]
            "user": [],   # List of user messages: [{"index": 0, "text": "...", "timestamp": ...}, ...]
        }

        # Event handlers for logging and caption emission
        @session.on("user_input_transcribed")
        def on_user_speech(event):
            # Only process FINAL transcripts to avoid fragmentation
            if event.is_final:
                import time
                transcript = event.transcript.strip()

                # Skip empty transcripts
                if not transcript:
                    return

                logger.info(f"[USER] {transcript}")

                # Store user message in conversation history (only final, complete transcripts)
                user_message = {
                    "index": len(conversation_history["user"]),
                    "text": transcript,
                    "timestamp": time.time()
                }
                conversation_history["user"].append(user_message)

                # Emit user caption to UI
                asyncio.create_task(emit_user_caption(ctx, transcript))

        @session.on("conversation_item_added")
        def on_conversation_item(event):
            """Handle both user and agent messages from the conversation."""
            try:
                import time
                message = event.item

                # Only process agent messages (skip user messages as they're handled by user_input_transcribed)
                if hasattr(message, 'role') and message.role == "assistant":
                    # Get agent's text using text_content property
                    agent_text = message.text_content if hasattr(message, 'text_content') else None

                    if agent_text:
                        logger.info(f"[AGENT] {agent_text[:150]}...")

                        # Store agent message in conversation history
                        agent_message = {
                            "index": len(conversation_history["agent"]),
                            "text": agent_text,
                            "timestamp": time.time(),
                            "stage": interview_state.stage.value
                        }
                        conversation_history["agent"].append(agent_message)

                        # Emit agent caption to UI (this happens after speech is generated)
                        asyncio.create_task(emit_agent_caption(ctx, agent_text))
                        logger.info(f"[HISTORY] Stored agent message #{agent_message['index']} ({len(agent_text)} chars)")
                    else:
                        logger.warning("[AGENT] No text_content in message")
            except Exception as e:
                logger.error(f"[CONVERSATION] Error processing conversation item: {e}", exc_info=True)

        # Track closing stage speech timing
        closing_speech_start = {"time": None, "has_spoken": False}

        @session.on("agent_state_changed")
        def on_state_change(event):
            old_state = getattr(event, 'old_state', 'unknown')
            new_state = getattr(event, 'new_state', 'unknown')
            logger.info(f"[SESSION] Agent state: {old_state} -> {new_state}")

            # Track when agent starts speaking in closing stage
            if interview_state.stage == InterviewStage.CLOSING:
                if new_state == 'speaking' and not closing_speech_start["has_spoken"]:
                    import time
                    closing_speech_start["time"] = time.time()
                    closing_speech_start["has_spoken"] = True
                    logger.info("[SESSION] Agent started closing remarks")

            # Auto-disconnect after agent finishes speaking closing remarks
            if interview_state.stage == InterviewStage.CLOSING and closing_speech_start["has_spoken"]:
                if old_state == 'speaking' and new_state in ('idle', 'listening'):
                    import time
                    speech_duration = time.time() - closing_speech_start["time"]

                    # Only disconnect if agent spoke for at least 3 seconds (to ensure full message was delivered)
                    if speech_duration >= 3.0:
                        logger.info(f"[SESSION] Closing speech completed (duration: {speech_duration:.1f}s) - scheduling disconnect in 3 seconds")

                        # Emit "interview ending" message to UI
                        async def emit_interview_ending():
                            try:
                                import json
                                data_payload = json.dumps({
                                    "type": "interview_ending",
                                    "message": "Interview Complete"
                                })
                                await ctx.room.local_participant.publish_data(
                                    data_payload.encode('utf-8')
                                )
                                logger.info("[UI] Emitted interview ending notification")
                            except Exception as e:
                                logger.error(f"[UI] Failed to emit interview ending: {e}")

                        asyncio.create_task(emit_interview_ending())

                        # Save conversation history for analysis
                        try:
                            import json
                            from datetime import datetime

                            history_data = {
                                "candidate": candidate_name,
                                "interview_date": datetime.now().isoformat(),
                                "room_name": ctx.room.name,
                                "conversation": conversation_history,
                                "total_messages": {
                                    "agent": len(conversation_history['agent']),
                                    "user": len(conversation_history['user'])
                                }
                            }

                            # Save to interviews directory
                            import os
                            os.makedirs("interviews", exist_ok=True)
                            filename = f"interviews/{candidate_name.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

                            with open(filename, 'w', encoding='utf-8') as f:
                                json.dump(history_data, f, indent=2, ensure_ascii=False)

                            logger.info(f"[HISTORY] Saved conversation to {filename}")
                            logger.info(f"[HISTORY] Interview complete - Agent: {len(conversation_history['agent'])} messages, User: {len(conversation_history['user'])} messages")
                        except Exception as e:
                            logger.error(f"[HISTORY] Failed to save conversation: {e}", exc_info=True)

                        # Give a brief moment for the audio to fully play out, then disconnect
                        asyncio.create_task(delayed_disconnect(ctx.room, delay=3.0))
                    else:
                        logger.info(f"[SESSION] Closing speech too short ({speech_duration:.1f}s), waiting for complete message...")

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
        InterviewStage.CLOSING: 60,   # 1 minute for closing, then auto-disconnect
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