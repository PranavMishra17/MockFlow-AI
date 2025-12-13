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

from fsm import InterviewState, InterviewStage, STAGE_TIME_LIMITS, STAGE_MIN_QUESTIONS

# Load environment variables from .env file in project root
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
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
"Hi [CANDIDATE_NAME]! I'm Alex. Welcome to your interview. This will be structured in two parts: first, you'll introduce yourself; then we'll discuss your past experiences in detail. Let's begin - please introduce yourself."

STEP 2: After you finish speaking the greeting, IMMEDIATELY call transition_stage to move to self_intro.

Do NOT wait for the candidate's response before calling transition_stage.
""",

    InterviewStage.SELF_INTRO: """
You are conducting the self-introduction stage of a mock interview.

Your task:
1. Listen actively to the candidate's introduction (they've already been asked to introduce themselves)
2. After they respond, call assess_response to evaluate their response
3. Use follow-up questions naturally to learn more about their background
4. Before asking ANY question, you MUST call ask_question tool to verify it hasn't been asked before
5. Engage in genuine conversation - aim for quality interaction

CRITICAL RULES:
- Call assess_response AFTER EVERY candidate response
- Call ask_question BEFORE asking ANY question to prevent repetition
- Do NOT ask repetitive or similar questions
- You need at least 2 questions, but should transition once you have enough context
- Focus on learning about their background, education, experience, and interests

TRANSITION GUIDANCE:
- Once you have asked the minimum questions AND have a good understanding of their background, TRANSITION
- Do not linger unnecessarily - keep the interview moving
- When the tool tells you minimum is met, seriously consider transitioning
- Call transition_stage with a brief reason describing what you learned

Guidelines:
- Be encouraging and supportive but efficient
- Show genuine interest while being mindful of time
- Quality over quantity - good responses mean you can transition sooner
""",

    InterviewStage.PAST_EXPERIENCE: """
You are now discussing the candidate's past work experience in detail.

FIRST, acknowledge the topic change: "Great introduction! Now let's shift gears and talk about your past work experience, particularly as it relates to the [ROLE] role you're applying for."

Your task:
1. Start by acknowledging the stage change and mentioning the role they're applying for
2. Ask about specific past work experiences, projects, or accomplishments relevant to the [ROLE] role
3. Encourage detailed explanations using STAR method (Situation, Task, Action, Result)
4. IMPORTANT: After they respond, call assess_response to evaluate their response
5. Before asking ANY question, you MUST call ask_question tool to verify it hasn't been asked before

CRITICAL RULES:
- Call assess_response AFTER EVERY candidate response
- Call ask_question BEFORE asking ANY question to prevent repetition
- Do NOT ask repetitive or generic questions
- You need at least 5 questions minimum
- Focus on depth over breadth - understand a few experiences well

TRANSITION GUIDANCE:
- Once minimum questions are met AND you have solid understanding of their experience, TRANSITION
- Pay attention to time remaining - don't let the stage run too long
- When tool indicates minimum met and time is past 50%, strongly consider transitioning
- Do not ask unnecessary follow-ups just to fill time
- Call transition_stage when ready

Guidelines:
- Be genuinely curious but time-conscious
- Connect their experience to the role they're applying for
- Probe technical details and impact when relevant
- Move toward closing once you have enough signal
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
        self.candidate_info = candidate_info or {}
        self.candidate_name = self.candidate_info.get('name', 'Candidate')
        self.candidate_role = self.candidate_info.get('role', 'this position')

        personalized_greeting = INSTRUCTIONS[InterviewStage.GREETING].replace(
            "[CANDIDATE_NAME]",
            self.candidate_name
        )

        super().__init__(
            instructions=personalized_greeting
        )
        self.room = room

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

            # Minimum time gates (reduced for efficiency)
            MIN_TIMES = {
                InterviewStage.GREETING: 0,
                InterviewStage.SELF_INTRO: 30,
                InterviewStage.PAST_EXPERIENCE: 45,
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

            # Replace [ROLE] placeholder with actual role
            stage_instructions = stage_instructions.replace(
                "[ROLE]",
                ctx.userdata.job_role or "this position"
            )

            # Add role-specific context guidance
            role_context = self._get_role_context(ctx.userdata)

            personality_note = f"""

IMPORTANT: The candidate's name is {self.candidate_name}.
They are applying for: {ctx.userdata.job_role or 'a technical position'}
Experience level: {ctx.userdata.experience_level or 'mid-level'}

{role_context}

Use their name naturally during the conversation. Maintain a warm, professional tone consistent with Alex the AI interviewer. Be encouraging and supportive.
"""

            personalized_instructions = stage_instructions + personality_note

            await self.update_instructions(personalized_instructions)

            logger.info(
                f"[AGENT] Stage transition: {current_stage.value} -> {next_stage.value} "
                f"(reason: {reason}, time_in_stage: {time_in_stage:.1f}s)"
            )

            await self._emit_stage_change(ctx, next_stage)

            # Define explicit transition acknowledgements
            transition_acknowledgements = {
                InterviewStage.SELF_INTRO: (
                    f"Great! I'm looking forward to learning more about you, {self.candidate_name}. "
                    f"Please go ahead and tell me about yourself."
                ),
                InterviewStage.PAST_EXPERIENCE: (
                    f"Excellent introduction, thank you {self.candidate_name}! "
                    f"Now let's shift gears and discuss your past work experience, "
                    f"particularly as it relates to the {ctx.userdata.job_role or 'position'} role. "
                    f"Can you walk me through a specific project or experience you're particularly proud of?"
                ),
                InterviewStage.CLOSING: (
                    f"Thank you so much for sharing all of that, {self.candidate_name}. "
                    f"I really enjoyed learning about your background and experience. "
                    f"You've demonstrated great depth in your technical knowledge. "
                    f"We'll be in touch with next steps via email. Thank you again, and best of luck!"
                ),
            }

            acknowledgement = transition_acknowledgements.get(next_stage)

            # For CLOSING stage: Use session.say() directly since no tools will be called
            # For other stages: Queue acknowledgement to be delivered via ask_question tool
            if next_stage == InterviewStage.CLOSING:
                # Mark that closing has been initiated - the closing speech will be said directly
                ctx.userdata.closing_initiated = True
                logger.info(f"[AGENT] Closing stage initiated - will speak closing remarks")
                
                return (
                    f"Stage transitioned to closing. "
                    f"You MUST now deliver your closing remarks. Say: '{acknowledgement}' "
                    f"Do NOT ask any more questions. Just thank them and say goodbye."
                )
            
            else:
                # Queue the acknowledgement - it will be injected via ask_question tool
                if acknowledgement:
                    ctx.userdata.pending_acknowledgement = acknowledgement
                    ctx.userdata.pending_ack_stage = next_stage.value
                    logger.info(f"[AGENT] Queued transition acknowledgement for {next_stage.value}")

                return (
                    f"Stage transitioned to {next_stage.value}. "
                    f"IMPORTANT: You MUST start your next response by acknowledging the stage change. "
                    f"Say something like: '{acknowledgement}' before continuing with questions."
                )

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
        Returns approval with progress status including time remaining.
        """
        try:
            current_stage = ctx.userdata.stage.value
            stage_questions = ctx.userdata.questions_per_stage.get(current_stage, 0)
            minimum = STAGE_MIN_QUESTIONS.get(current_stage, 2)

            # Check for pending acknowledgement
            # Clear it ONLY if we're asking a question in the pending stage (proves transition happened)
            pending_ack = None
            should_clear_ack = False
            
            if ctx.userdata.pending_acknowledgement and not ctx.userdata.transition_acknowledged:
                pending_ack = ctx.userdata.pending_acknowledgement
                pending_stage = ctx.userdata.pending_ack_stage
                
                # If asking question in the new stage, this is the acknowledgement moment
                if current_stage == pending_stage:
                    should_clear_ack = True
                    logger.info(f"[AGENT] Acknowledgement will be delivered for {pending_stage} (question in new stage)")
                else:
                    logger.debug(f"[AGENT] Pending ack for {pending_stage}, but question in {current_stage}")

            # Get time status
            time_status = ctx.userdata.get_time_status()
            time_remaining_pct = time_status['remaining_pct']
            remaining_sec = time_status['remaining_seconds']

            # Normalize for comparison
            normalized = question.lower().strip().rstrip('?.,!')

            # Check duplicates
            for asked in ctx.userdata.questions_asked:
                asked_normalized = asked.lower().strip().rstrip('?.,!')

                if normalized == asked_normalized:
                    logger.warning(f"[AGENT] Rejected duplicate question: '{question}'")
                    return f"You already asked this exact question: '{asked}'. Please ask something different."

                if normalized in asked_normalized or asked_normalized in normalized:
                    logger.warning(f"[AGENT] Rejected similar question: '{question}'")
                    return f"You already asked a very similar question: '{asked}'. Please ask something different."

            # Approve and track
            ctx.userdata.questions_asked.append(question)
            ctx.userdata.questions_per_stage[current_stage] = stage_questions + 1
            new_count = stage_questions + 1

            logger.info(
                f"[AGENT] Approved question #{len(ctx.userdata.questions_asked)} "
                f"({new_count}/{minimum} in {current_stage}, {time_remaining_pct:.0f}% time remaining)"
            )

            # Build response with progress info
            response = f"Question approved ({new_count}/{minimum} questions). "
            response += f"Time remaining: {time_remaining_pct:.0f}% ({remaining_sec:.0f}s). "

            # Transition guidance based on progress
            if new_count >= minimum:
                if time_remaining_pct <= 25:
                    response += "MINIMUM MET + TIME LOW. You SHOULD transition soon after this response. "
                elif time_remaining_pct <= 50:
                    response += "Minimum questions met. Consider transitioning after getting a good response. "
                else:
                    response += "Minimum met. You may ask more or transition when ready. "
            else:
                remaining_q = minimum - new_count
                response += f"Need {remaining_q} more question(s) to meet minimum. "

            response += f"Now ask: '{question}'"

            # CRITICAL: If there's a pending acknowledgement, prepend it
            if pending_ack:
                response = (
                    f"STAGE TRANSITION - You MUST first say this to acknowledge the new stage: "
                    f"\"{pending_ack}\" "
                    f"Then ask your question.\n\n{response}"
                )
                
                # Clear the pending ack if this question is in the new stage
                if should_clear_ack:
                    ctx.userdata.transition_acknowledged = True
                    ctx.userdata.pending_acknowledgement = None
                    ctx.userdata.pending_ack_stage = None
                    logger.info(f"[AGENT] Transition acknowledgement cleared - agent proceeding in new stage")

            return response

        except Exception as e:
            logger.error(f"[AGENT] Question validation error: {e}", exc_info=True)
            return "Error validating question. Please try again."

    @function_tool
    async def assess_response(
        self,
        ctx: RunContext[InterviewState],
        depth_score: Annotated[int, Field(description="Response depth: 1=vague, 2=surface, 3=adequate, 4=detailed, 5=comprehensive")],
        key_points_covered: Annotated[list[str], Field(description="Key points mentioned by candidate")]
    ) -> str:
        """
        Assess response quality and provide guidance with time/progress context.
        """
        try:
            current_stage = ctx.userdata.stage

            # Store response
            response_summary = f"Depth: {depth_score}/5. Key points: {', '.join(key_points_covered)}"
            ctx.userdata.experience_responses.append(response_summary)

            # Check for pending acknowledgement - DON'T clear it here
            # It will be cleared when agent asks a question in the new stage
            pending_ack = None
            if ctx.userdata.pending_acknowledgement and not ctx.userdata.transition_acknowledged:
                pending_ack = ctx.userdata.pending_acknowledgement
                pending_stage = ctx.userdata.pending_ack_stage
                logger.debug(f"[AGENT] Pending acknowledgement active for {pending_stage}")

            # Get progress status
            q_status = ctx.userdata.get_question_status()
            time_status = ctx.userdata.get_time_status()

            time_remaining_pct = time_status['remaining_pct']
            remaining_sec = time_status['remaining_seconds']
            met_minimum = q_status['met_minimum']
            questions_asked = q_status['asked']
            questions_min = q_status['minimum']

            logger.info(
                f"[AGENT] Response assessment - Stage: {current_stage.value}, "
                f"Depth: {depth_score}/5, Questions: {questions_asked}/{questions_min}, "
                f"Time: {time_remaining_pct:.0f}% remaining"
            )

            # Build status line
            status_line = (
                f"[STATUS] Questions: {questions_asked}/{questions_min} | "
                f"Time: {time_remaining_pct:.0f}% ({remaining_sec:.0f}s remaining)"
            )

            # Determine transition urgency
            should_transition_now = False
            transition_hint = ""

            if time_remaining_pct <= 10:
                should_transition_now = True
                transition_hint = "TIME CRITICAL: Must transition NOW. Call transition_stage immediately."
            elif met_minimum and time_remaining_pct <= 25:
                should_transition_now = True
                transition_hint = "Minimum met + time running low. TRANSITION NOW."
            elif met_minimum and depth_score >= 3:
                transition_hint = "Good response + minimum met. Consider transitioning."
            elif met_minimum:
                transition_hint = "Minimum questions met. Can transition when ready."

            # Build guidance based on depth
            if should_transition_now:
                guidance = f"{status_line}\n{transition_hint}"
            elif depth_score >= 4:
                guidance = (
                    f"{status_line}\n"
                    f"Excellent response (depth {depth_score}/5). "
                    f"{transition_hint if transition_hint else 'You may explore further or transition.'}"
                )
            elif depth_score == 3:
                guidance = (
                    f"{status_line}\n"
                    f"Good response (depth {depth_score}/5). "
                    f"{transition_hint if transition_hint else 'Consider a brief follow-up or continue.'}"
                )
            elif depth_score == 2:
                if met_minimum and time_remaining_pct <= 40:
                    guidance = (
                        f"{status_line}\n"
                        f"Surface response, but minimum met and time is limited. Consider transitioning."
                    )
                else:
                    guidance = (
                        f"{status_line}\n"
                        f"Surface response. A follow-up using STAR method may help get more detail."
                    )
            else:
                guidance = (
                    f"{status_line}\n"
                    f"Brief response. Ask a follow-up to get more context."
                )

            # CRITICAL: If there's a pending acknowledgement, prepend it
            if pending_ack:
                guidance = (
                    f"IMPORTANT - STAGE CHANGE: You MUST first acknowledge the stage transition. "
                    f"Start your response by saying: \"{pending_ack}\" "
                    f"Then proceed with your question.\n\n{guidance}"
                )

            return guidance

        except Exception as e:
            logger.error(f"[AGENT] Response assessment error: {e}", exc_info=True)
            return "Error assessing response. Continue naturally."

    def _get_role_context(self, state: InterviewState) -> str:
        """Generate role-specific interview guidance."""
        role = state.job_role.lower() if state.job_role else ""
        level = state.experience_level.lower() if state.experience_level else "mid"

        role_keywords = {
            'engineer': 'technical skills, problem-solving approaches, system design decisions',
            'developer': 'coding practices, frameworks/tools used, debugging and optimization',
            'software': 'technical architecture, development process, code quality practices',
            'manager': 'team leadership, project planning, stakeholder communication',
            'product': 'product strategy, user research, roadmap prioritization',
            'designer': 'design process, user research methods, collaboration',
            'analyst': 'data analysis techniques, business insights, technical tools',
            'qa': 'testing strategies, automation, quality assurance processes',
            'devops': 'infrastructure, CI/CD pipelines, monitoring, cloud platforms',
        }

        level_expectations = {
            'entry': 'Focus on learning approach, academic/personal projects, foundational skills.',
            'junior': 'Focus on recent projects, technical growth, hands-on experience.',
            'mid': 'Focus on independent project ownership, technical decisions, collaboration.',
            'senior': 'Focus on system design, mentoring others, technical leadership.',
            'lead': 'Focus on architecture strategy, team guidance, cross-team impact.',
            'staff': 'Focus on organization-wide impact, technical strategy, mentoring leads.',
        }

        role_focus = "technical experience and problem-solving approaches"
        for key, focus in role_keywords.items():
            if key in role:
                role_focus = focus
                break

        level_guidance = level_expectations.get(level, level_expectations['mid'])

        return f"""
For this {state.job_role or 'position'} role ({level} level):
- Key focus areas: {role_focus}
- {level_guidance}
- Tailor questions to probe relevant experience for this role and level.
"""

    async def on_enter(self):
        """Called when agent becomes active - trigger the greeting."""
        logger.info(f"[AGENT] Agent activated - greeting {self.candidate_name}")
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

        await ctx.room.local_participant.publish_data(
            data_payload.encode('utf-8')
        )

        logger.debug(f"[UI] Emitted agent caption: {text[:50]}...")
    except Exception as e:
        logger.error(f"[UI] Failed to emit agent caption: {e}")


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
    interview_complete = asyncio.Event()

    try:
        await ctx.connect()
        logger.info(f"[SESSION] Connected to room: {ctx.room.name}")

        # Extract candidate info
        room_parts = ctx.room.name.split('-')
        candidate_name = ' '.join(room_parts[1:-1]).title() if len(room_parts) > 2 else "Candidate"

        role = 'this position'
        level = 'mid'
        email = ''

        if ctx.room.remote_participants:
            participant = list(ctx.room.remote_participants.values())[0]
            if hasattr(participant, 'attributes') and participant.attributes:
                role = participant.attributes.get('role', 'this position')
                level = participant.attributes.get('level', 'mid')
                email = participant.attributes.get('email', '')
                logger.info(f"[SESSION] Retrieved candidate metadata - Role: {role}, Level: {level}")

        candidate_info = {
            'name': candidate_name,
            'role': role
        }

        logger.info(f"[SESSION] Candidate: {candidate_name} (Role: {role}, Level: {level})")

        # Initialize interview state
        interview_state = InterviewState()
        interview_state.candidate_name = candidate_name
        interview_state.candidate_email = email
        interview_state.job_role = role
        interview_state.experience_level = level
        interview_state.transition_to(InterviewStage.GREETING)

        logger.info(f"[SESSION] Room participants: {[p.identity for p in ctx.room.remote_participants.values()]}")

        # Initialize components
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

        try:
            llm = openai.LLM(
                model="gpt-4o-mini",
                temperature=0.7,
            )
            logger.info("[SESSION] OpenAI LLM initialized")
        except Exception as e:
            logger.error(f"[SESSION] OpenAI LLM init error: {e}")
            raise

        try:
            tts = openai.TTS(
                voice="alloy",
                speed=1.0,
            )
            logger.info("[SESSION] OpenAI TTS initialized")
        except Exception as e:
            logger.error(f"[SESSION] OpenAI TTS init error: {e}")
            raise

        try:
            vad = silero.VAD.load()
            logger.info("[SESSION] Silero VAD initialized")
        except Exception as e:
            logger.error(f"[SESSION] Silero VAD init error: {e}")
            raise

        # Create agent
        agent = InterviewAgent(room=ctx.room, candidate_info=candidate_info)

        # Create session
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

        # Conversation history
        conversation_history = {
            "agent": [],
            "user": [],
        }

        # Closing finalization tracking
        closing_finalized = {"done": False}

        # Event handlers
        @session.on("user_input_transcribed")
        def on_user_speech(event):
            if event.is_final:
                import time
                transcript = event.transcript.strip()
                if not transcript:
                    return

                logger.info(f"[USER] {transcript}")

                user_message = {
                    "index": len(conversation_history["user"]),
                    "text": transcript,
                    "timestamp": time.time()
                }
                conversation_history["user"].append(user_message)

                asyncio.create_task(emit_user_caption(ctx, transcript))

        @session.on("conversation_item_added")
        def on_conversation_item(event):
            try:
                import time
                message = event.item

                if hasattr(message, 'role') and message.role == "assistant":
                    agent_text = message.text_content if hasattr(message, 'text_content') else None

                    if agent_text:
                        logger.info(f"[AGENT] {agent_text[:150]}...")

                        agent_message = {
                            "index": len(conversation_history["agent"]),
                            "text": agent_text,
                            "timestamp": time.time(),
                            "stage": interview_state.stage.value
                        }
                        conversation_history["agent"].append(agent_message)

                        asyncio.create_task(emit_agent_caption(ctx, agent_text))
                        
                        # Check for closing message delivery
                        if interview_state.stage == InterviewStage.CLOSING and not closing_finalized["done"]:
                            # Check if this is a proper closing message
                            text_lower = agent_text.lower()
                            closing_indicators = [
                                "thank you" in text_lower and ("luck" in text_lower or "best" in text_lower),
                                "good luck" in text_lower,
                                "best of luck" in text_lower,
                                "we'll be in touch" in text_lower,
                                "next steps" in text_lower and "email" in text_lower,
                            ]
                            
                            if any(closing_indicators) and len(agent_text) > 50:
                                logger.info(f"[SESSION] Closing message detected ({len(agent_text)} chars)")
                                interview_state.closing_message_delivered = True
                                
                                # Schedule finalization
                                async def schedule_finalization():
                                    if closing_finalized["done"]:
                                        return
                                    closing_finalized["done"] = True
                                    
                                    # Wait for TTS to finish speaking
                                    await asyncio.sleep(5.0)
                                    
                                    logger.info("[SESSION] Finalizing interview after closing message")
                                    await finalize_and_disconnect()
                                
                                asyncio.create_task(schedule_finalization())
                        
            except Exception as e:
                logger.error(f"[CONVERSATION] Error processing item: {e}", exc_info=True)

        async def finalize_and_disconnect():
            """Finalize interview and disconnect."""
            try:
                import json
                from datetime import datetime

                # Emit ending notification
                try:
                    data_payload = json.dumps({
                        "type": "interview_ending",
                        "message": "Interview Complete"
                    })
                    await ctx.room.local_participant.publish_data(
                        data_payload.encode('utf-8')
                    )
                    logger.info("[UI] Emitted interview ending notification")
                except Exception as e:
                    logger.warning(f"[UI] Failed to emit interview ending: {e}")

                # Save conversation
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

                os.makedirs("interviews", exist_ok=True)
                filename = f"interviews/{candidate_name.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

                with open(filename, 'w', encoding='utf-8') as f:
                    import json as json_module
                    json_module.dump(history_data, f, indent=2, ensure_ascii=False)

                logger.info(f"[HISTORY] Saved conversation to {filename}")

                # Signal interview complete
                interview_complete.set()

                # Disconnect after brief delay
                await asyncio.sleep(2.0)
                await ctx.room.disconnect()

            except Exception as e:
                logger.error(f"[FINALIZE] Error: {e}", exc_info=True)
                interview_complete.set()

        @session.on("agent_state_changed")
        def on_state_change(event):
            old_state = getattr(event, 'old_state', 'unknown')
            new_state = getattr(event, 'new_state', 'unknown')
            logger.info(f"[SESSION] Agent state: {old_state} -> {new_state}")

        # Handle room disconnect
        @ctx.room.on("disconnected")
        def on_room_disconnected():
            logger.info("[ROOM] Room disconnected event")
            interview_complete.set()

        # Start fallback timer AFTER session setup but BEFORE session.start()
        fallback_task = asyncio.create_task(
            stage_fallback_timer(session, interview_state, ctx, agent, interview_complete)
        )
        logger.info("[TIMER] Fallback timer task created")

        logger.info("[SESSION] Starting agent session")

        # Start the session (non-blocking)
        await session.start(
            agent=agent,
            room=ctx.room
        )

        logger.info("[SESSION] Session started, waiting for interview completion...")

        # CRITICAL: Wait for interview to actually complete
        # This keeps the entrypoint alive and prevents timer cancellation
        await interview_complete.wait()

        logger.info("[SESSION] Interview complete signal received")

    except asyncio.CancelledError:
        logger.info("[SESSION] Session cancelled")
    except Exception as e:
        logger.error(f"[SESSION] Agent error: {e}", exc_info=True)
    finally:
        if fallback_task and not fallback_task.done():
            fallback_task.cancel()
            try:
                await fallback_task
            except asyncio.CancelledError:
                pass
            logger.info("[FALLBACK] Fallback timer cancelled")
        logger.info("[SESSION] Session cleanup complete")


async def stage_fallback_timer(
    session: AgentSession,
    state: InterviewState,
    ctx: JobContext,
    agent: InterviewAgent,
    interview_complete: asyncio.Event
):
    """
    Timer that monitors stage progress and forces transitions when limits are exceeded.
    Only active for SELF_INTRO and PAST_EXPERIENCE stages.
    """
    # Monitor these stages for time limits
    MONITORED_STAGES = {InterviewStage.SELF_INTRO, InterviewStage.PAST_EXPERIENCE}
    
    # Closing stage has a separate safety timeout
    CLOSING_TIMEOUT = 60  # Force disconnect after 60s in closing if message not delivered

    logged_milestones = set()
    last_logged_stage = None
    closing_timeout_logged = False

    logger.info("[TIMER] Fallback timer started - monitoring SELF_INTRO, PAST_EXPERIENCE, and CLOSING")

    try:
        while not interview_complete.is_set():
            await asyncio.sleep(5)

            # Check if interview is done
            if interview_complete.is_set():
                break

            current_stage = state.stage
            
            # Special handling for CLOSING stage
            if current_stage == InterviewStage.CLOSING:
                elapsed = state.time_in_current_stage()
                
                if not closing_timeout_logged:
                    logger.info(f"[TIMER] Stage 'closing' STARTED - Safety timeout: {CLOSING_TIMEOUT}s")
                    closing_timeout_logged = True
                
                # Force finalization if closing takes too long
                if elapsed > CLOSING_TIMEOUT and not state.closing_message_delivered:
                    logger.warning(f"[FALLBACK] Closing stage timeout ({elapsed:.0f}s) - forcing finalization")
                    
                    # Try to say a brief closing message
                    try:
                        closing_msg = (
                            f"Thank you for your time, {agent.candidate_name}. "
                            f"We'll be in touch. Best of luck!"
                        )
                        await session.say(closing_msg, allow_interruptions=False)
                        await asyncio.sleep(3.0)
                    except Exception as e:
                        logger.warning(f"[FALLBACK] Failed to say closing: {e}")
                    
                    # Signal completion
                    interview_complete.set()
                    
                    try:
                        await ctx.room.disconnect()
                    except Exception as e:
                        logger.warning(f"[FALLBACK] Disconnect error: {e}")
                    
                    break
                
                continue

            # Only monitor specific stages for question/time limits
            if current_stage not in MONITORED_STAGES:
                if current_stage != last_logged_stage:
                    logger.debug(f"[TIMER] Stage '{current_stage.value}' not monitored, skipping")
                    last_logged_stage = current_stage
                    logged_milestones = set()
                continue

            # Get progress info
            time_status = state.get_time_status()
            q_status = state.get_question_status()

            elapsed = time_status['elapsed']
            limit = time_status['limit']
            elapsed_pct = time_status['elapsed_pct']
            remaining_pct = time_status['remaining_pct']

            # New stage detected
            if current_stage != last_logged_stage:
                logger.info(
                    f"[TIMER] Stage '{current_stage.value}' STARTED - "
                    f"Limit: {limit}s, Questions needed: {q_status['minimum']}"
                )
                logged_milestones = set()
                last_logged_stage = current_stage

            # Log milestones: 50%, 75%, 90%, 100%
            if elapsed_pct >= 50 and 50 not in logged_milestones:
                logger.info(
                    f"[TIMER] Stage '{current_stage.value}' at 50% - "
                    f"{elapsed:.0f}/{limit}s, Questions: {q_status['asked']}/{q_status['minimum']}"
                )
                logged_milestones.add(50)

            if elapsed_pct >= 75 and 75 not in logged_milestones:
                logger.warning(
                    f"[TIMER] Stage '{current_stage.value}' at 75% - "
                    f"{elapsed:.0f}/{limit}s, Questions: {q_status['asked']}/{q_status['minimum']}"
                )
                logged_milestones.add(75)

            if elapsed_pct >= 90 and 90 not in logged_milestones:
                logger.warning(
                    f"[TIMER] Stage '{current_stage.value}' at 90% - "
                    f"{elapsed:.0f}/{limit}s - APPROACHING LIMIT"
                )
                logged_milestones.add(90)

            if elapsed_pct >= 100 and 100 not in logged_milestones:
                logger.warning(
                    f"[TIMER] Stage '{current_stage.value}' at 100% - "
                    f"LIMIT EXCEEDED ({elapsed:.0f}/{limit}s)"
                )
                logged_milestones.add(100)

            # Force transition if limit exceeded
            if elapsed > limit:
                next_stage = state.get_next_stage()

                if next_stage:
                    logger.warning(
                        f"[FALLBACK] FORCING transition: {current_stage.value} -> {next_stage.value} "
                        f"(exceeded {limit}s limit, Questions: {q_status['asked']}/{q_status['minimum']})"
                    )

                    # Execute FSM transition
                    state.transition_to(next_stage, forced=True)

                    # Update agent instructions
                    try:
                        stage_instructions = INSTRUCTIONS[next_stage]
                        stage_instructions = stage_instructions.replace(
                            "[ROLE]",
                            state.job_role or "this position"
                        )

                        role_context = agent._get_role_context(state)

                        personality_note = f"""

IMPORTANT: The candidate's name is {agent.candidate_name}.
They are applying for: {state.job_role or 'a technical position'}
Experience level: {state.experience_level or 'mid-level'}

{role_context}

Use their name naturally. Maintain a warm, professional tone.
"""

                        personalized_instructions = stage_instructions + personality_note
                        await agent.update_instructions(personalized_instructions)

                        logger.info(f"[FALLBACK] Updated agent instructions to {next_stage.value}")
                    except Exception as e:
                        logger.error(f"[FALLBACK] Failed to update instructions: {e}", exc_info=True)

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
                        logger.error(f"[UI] Failed to emit stage change: {e}")

                    # Queue acknowledgement for graceful delivery after user stops
                    # This will be injected into the agent's next response via assess_response or ask_question
                    try:
                        transition_acknowledgements = {
                            InterviewStage.SELF_INTRO: (
                                f"Alright {agent.candidate_name}, let's get started. "
                                f"Please go ahead and introduce yourself."
                            ),
                            InterviewStage.PAST_EXPERIENCE: (
                                f"Thank you for that introduction, {agent.candidate_name}! "
                                f"Now let's shift gears and talk about your past work experience, "
                                f"particularly as it relates to the {state.job_role or 'position'} role you're applying for. "
                                f"Can you tell me about a specific project or accomplishment you're proud of?"
                            ),
                            InterviewStage.CLOSING: (
                                f"Thank you for sharing all of that with me, {agent.candidate_name}. "
                                f"I really appreciate you walking me through your experience. "
                                f"Let me wrap up our interview now."
                            ),
                        }

                        acknowledgement = transition_acknowledgements.get(next_stage)

                        if acknowledgement:
                            # Queue the acknowledgement - will be delivered on next agent turn
                            state.pending_acknowledgement = acknowledgement
                            state.pending_ack_stage = next_stage.value
                            logger.info(f"[FALLBACK] Queued acknowledgement for {next_stage.value}")

                            # Also try session.say as backup - if user is silent, this will work
                            # If user is speaking, it will be interrupted but the queued ack will still fire
                            try:
                                await session.say(acknowledgement)
                                logger.info(f"[FALLBACK] Announced forced transition to {next_stage.value}")
                            except Exception as say_err:
                                logger.warning(f"[FALLBACK] session.say failed (user may be speaking): {say_err}")
                                # Acknowledgement is still queued, will be delivered via tool response

                    except Exception as e:
                        logger.error(f"[FALLBACK] Error setting up transition acknowledgement: {e}", exc_info=True)

                    # Reset milestones for new stage
                    logged_milestones = set()
                    last_logged_stage = next_stage

    except asyncio.CancelledError:
        logger.info("[TIMER] Fallback timer cancelled")
    except Exception as e:
        logger.error(f"[TIMER] Fallback timer error: {e}", exc_info=True)


if __name__ == "__main__":
    logger.info("[MAIN] Starting MockFlow-AI Interview Agent")
    cli.run_app(server)