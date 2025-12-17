"""
MockFlow-AI Interview Agent

LiveKit-based voice interview agent with FSM-driven stage management.
Implements structured interview stages with explicit state transitions,
fallback mechanisms, and document-aware questioning.

Stage Flow: WELCOME -> SELF_INTRO -> PAST_EXPERIENCE -> COMPANY_FIT -> CLOSING
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

# Load environment variables
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("interview-agent")

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
    InterviewStage.WELCOME: """
You are a friendly interviewer named Alex.

STEP 1: Say EXACTLY this greeting (nothing more):
"Hi [CANDIDATE_NAME]! I'm Alex. Welcome to your mock interview. This will be structured in stages: you'll introduce yourself, we'll discuss your past experience, talk about company fit, and then wrap up. Let's begin - please introduce yourself."

STEP 2: After you finish speaking the greeting, IMMEDIATELY call transition_stage to move to self_intro.

Do NOT wait for the candidate's response before calling transition_stage.
""",

    InterviewStage.SELF_INTRO: """
You are conducting the self-introduction stage of a mock interview.

Your task:
1. Listen actively to the candidate's introduction
2. After they respond, call assess_response to evaluate
3. Ask conversational follow-up questions about their background
4. Before asking ANY question, call ask_question tool to verify it hasn't been asked
5. Engage in genuine, natural conversation

FOCUS AREAS:
- Educational background (what they studied, why)
- Current situation (what they're doing now)
- Interests and motivations
- Career aspirations

DO NOT ASK ABOUT:
- Specific past work experience details (save for next stage)
- Technical deep-dives into previous roles

CONVERSATION STYLE:
- Be warm and conversational
- Acknowledge interesting points naturally
- Ask open-ended questions
- DO NOT give live feedback on responses
- DO NOT mention "STAR method"

CRITICAL RULES:
- Call assess_response AFTER EVERY candidate response
- Call ask_question BEFORE asking ANY question
- Need at least 2 questions before transitioning

TRANSITION: Once you understand their background, call transition_stage.
""",

    InterviewStage.PAST_EXPERIENCE: """
You are now discussing the candidate's past work experience in detail.

Your task:
1. Ask about their past work, projects, and accomplishments
2. Listen carefully and ask natural follow-ups
3. Call assess_response AFTER they respond
4. Call ask_question BEFORE asking ANY question

[DOCUMENT_CONTEXT]

CONVERSATION STYLE:
- Be conversational and genuinely curious
- DO NOT say "Can you describe that using the STAR method?"
- Naturally probe for details: "What was the situation?", "How did you approach that?"
- Acknowledge interesting points

FOCUS AREAS:
- Specific projects relevant to [ROLE]
- Technical challenges solved
- Team collaboration
- Impact of their work

CRITICAL RULES:
- Call assess_response AFTER EVERY response
- Call ask_question BEFORE asking ANY question
- Need at least 5 questions minimum

TRANSITION: When minimum met and you have good understanding, call transition_stage.
""",

    InterviewStage.COMPANY_FIT: """
You are now assessing company and role fit.

[DOCUMENT_CONTEXT]

Your task:
1. Ask ~3 focused, open-ended questions about company/role fit
2. Use any available resume and job description context to tailor questions
3. Call assess_response AFTER each candidate response
4. Call ask_question BEFORE asking ANY question
5. Keep tone conversational - DO NOT give live feedback

QUESTION THEMES:
- Why this company/role interests them
- How their skills align with role requirements
- Culture fit and work style preferences
- Long-term career alignment
- What they'd bring to the team

If job description available, reference specific requirements.
If resume available, connect their experience to the role.

CRITICAL RULES:
- Call assess_response AFTER EVERY response
- Call ask_question BEFORE asking ANY question
- Need at least 3 questions
- DO NOT provide feedback during interview

TRANSITION: After 3+ quality exchanges about fit, call transition_stage to closing.
""",

    InterviewStage.CLOSING: """
You are wrapping up the interview.

Your task:
- Thank the candidate sincerely for their time
- Mention 1-2 positive observations (brief)
- Let them know next steps via email
- Say a warm goodbye: "Thank you again, and best of luck!"
- Keep this VERY brief (under 30 seconds)

After saying goodbye, the interview will automatically end.

Style: Warm, professional, encouraging.
"""
}


class InterviewAgent(Agent):
    """Mock interview agent with FSM-based stage management."""

    def __init__(self, room=None, candidate_info=None):
        """Initialize agent with welcome stage instructions."""
        self.candidate_info = candidate_info or {}
        self.candidate_name = self.candidate_info.get('name', 'Candidate')
        self.candidate_role = self.candidate_info.get('role', 'this position')

        personalized_greeting = INSTRUCTIONS[InterviewStage.WELCOME].replace(
            "[CANDIDATE_NAME]",
            self.candidate_name
        )

        super().__init__(instructions=personalized_greeting)
        self.room = room

    @function_tool
    async def transition_stage(
        self,
        ctx: RunContext[InterviewState],
        reason: Annotated[str, Field(description="Brief reason for stage transition")]
    ) -> str:
        """Explicit stage transition called by LLM when ready to move forward."""
        try:
            current_stage = ctx.userdata.stage
            
            # Check for skip queue first
            skip_target = ctx.userdata.process_skip_queue()
            if skip_target:
                next_stage = skip_target
                logger.info(f"[AGENT] Processing skip request to {next_stage.value}")
            else:
                next_stage = ctx.userdata.get_next_stage()

            if not next_stage:
                return f"Cannot transition from {current_stage.value} - interview complete"

            time_in_stage = ctx.userdata.time_in_current_stage()

            # Minimum time gates (reduced for efficiency)
            MIN_TIMES = {
                InterviewStage.WELCOME: 0,
                InterviewStage.SELF_INTRO: 30,
                InterviewStage.PAST_EXPERIENCE: 45,
                InterviewStage.COMPANY_FIT: 30,
            }

            min_time = MIN_TIMES.get(current_stage, 0)
            if time_in_stage < min_time and not skip_target:
                return (
                    f"Please spend more time in this stage. "
                    f"Current: {time_in_stage:.0f}s, Minimum: {min_time}s"
                )

            # Execute transition
            ctx.userdata.transition_to(next_stage, forced=False, skipped=bool(skip_target))

            # Get stage instructions
            stage_instructions = self._get_stage_instructions(ctx.userdata, next_stage)

            await self.update_instructions(stage_instructions)

            logger.info(
                f"[AGENT] Stage transition: {current_stage.value} -> {next_stage.value} "
                f"(reason: {reason}, time_in_stage: {time_in_stage:.1f}s)"
            )

            await self._emit_stage_change(ctx, next_stage)

            # Transition acknowledgements
            transition_acks = {
                InterviewStage.SELF_INTRO: (
                    f"Great! I'm looking forward to learning more about you, {self.candidate_name}. "
                    f"Please go ahead and tell me about yourself."
                ),
                InterviewStage.PAST_EXPERIENCE: (
                    f"Excellent introduction, thank you {self.candidate_name}! "
                    f"Now let's discuss your past work experience, "
                    f"particularly as it relates to the {ctx.userdata.job_role or 'position'} role."
                ),
                InterviewStage.COMPANY_FIT: (
                    f"Great insights into your experience, {self.candidate_name}! "
                    f"Now let's talk about company and role fit. "
                    f"I'd like to understand what draws you to this opportunity."
                ),
                InterviewStage.CLOSING: (
                    f"Thank you so much for sharing all of that, {self.candidate_name}. "
                    f"I really enjoyed learning about your background and experience. "
                    f"We'll be in touch with next steps via email. Thank you again, and best of luck!"
                ),
            }

            acknowledgement = transition_acks.get(next_stage)

            if next_stage == InterviewStage.CLOSING:
                ctx.userdata.closing_initiated = True
                return (
                    f"Stage transitioned to closing. "
                    f"You MUST now deliver your closing remarks. Say: '{acknowledgement}' "
                    f"Do NOT ask any more questions."
                )
            else:
                if acknowledgement:
                    ctx.userdata.pending_acknowledgement = acknowledgement
                    ctx.userdata.pending_ack_stage = next_stage.value
                    logger.info(f"[AGENT] Queued transition acknowledgement for {next_stage.value}")

                return (
                    f"Stage transitioned to {next_stage.value}. "
                    f"Start your next response by acknowledging the stage change."
                )

        except Exception as e:
            logger.error(f"[AGENT] Transition error: {e}", exc_info=True)
            return f"Error during transition: {str(e)}"

    def _get_stage_instructions(self, state: InterviewState, stage: InterviewStage) -> str:
        """Build personalized stage instructions with document context."""
        base_instructions = INSTRUCTIONS[stage]
        
        # Replace placeholders
        instructions = base_instructions.replace("[ROLE]", state.job_role or "this position")
        
        # Add document context for relevant stages
        doc_context = ""
        if stage in [InterviewStage.PAST_EXPERIENCE, InterviewStage.COMPANY_FIT]:
            if state.include_profile:
                doc_context = state.get_document_context()
                
        if doc_context:
            instructions = instructions.replace("[DOCUMENT_CONTEXT]", f"\nDOCUMENT CONTEXT:\n{doc_context}\n")
        else:
            instructions = instructions.replace("[DOCUMENT_CONTEXT]", "")
        
        # Add role context
        role_context = self._get_role_context(state)
        
        personality_note = f"""

IMPORTANT: The candidate's name is {self.candidate_name}.
They are applying for: {state.job_role or 'a technical position'}
Experience level: {state.experience_level or 'mid-level'}

{role_context}

Use their name naturally. Maintain a warm, professional tone.
"""
        return instructions + personality_note

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
        except Exception as e:
            logger.error(f"[UI] Failed to emit stage change: {e}")

    @function_tool
    async def ask_question(
        self,
        ctx: RunContext[InterviewState],
        question: Annotated[str, Field(description="The exact question you want to ask")]
    ) -> str:
        """Validate and track questions before asking to prevent repetition."""
        try:
            current_stage = ctx.userdata.stage.value
            stage_questions = ctx.userdata.questions_per_stage.get(current_stage, 0)
            minimum = STAGE_MIN_QUESTIONS.get(current_stage, 2)

            # Check for pending acknowledgement
            pending_ack = None
            should_clear_ack = False
            
            if ctx.userdata.pending_acknowledgement and not ctx.userdata.transition_acknowledged:
                pending_ack = ctx.userdata.pending_acknowledgement
                pending_stage = ctx.userdata.pending_ack_stage
                
                if current_stage == pending_stage:
                    should_clear_ack = True

            # Get time status
            time_status = ctx.userdata.get_time_status()
            time_remaining_pct = time_status['remaining_pct']
            remaining_sec = time_status['remaining_seconds']

            # Normalize for comparison
            normalized = question.lower().strip().rstrip('?.,!')

            # Check duplicates
            for asked in ctx.userdata.questions_asked:
                asked_normalized = asked.lower().strip().rstrip('?.,!')
                if normalized == asked_normalized or normalized in asked_normalized or asked_normalized in normalized:
                    return f"You already asked a similar question: '{asked}'. Please ask something different."

            # Approve and track
            ctx.userdata.questions_asked.append(question)
            ctx.userdata.questions_per_stage[current_stage] = stage_questions + 1
            new_count = stage_questions + 1

            logger.info(f"[AGENT] Approved question #{len(ctx.userdata.questions_asked)} ({new_count}/{minimum} in {current_stage})")

            # Build response
            response = f"Question approved ({new_count}/{minimum}). Time: {time_remaining_pct:.0f}% ({remaining_sec:.0f}s). "

            if new_count >= minimum:
                if time_remaining_pct <= 25:
                    response += "MINIMUM MET + TIME LOW. Transition soon. "
                else:
                    response += "Minimum met. May transition when ready. "
            else:
                response += f"Need {minimum - new_count} more. "

            response += f"Now ask: '{question}'"

            # Prepend pending acknowledgement
            if pending_ack:
                response = f"STAGE TRANSITION - First say: \"{pending_ack}\" Then ask your question.\n\n{response}"
                if should_clear_ack:
                    ctx.userdata.transition_acknowledged = True
                    ctx.userdata.pending_acknowledgement = None
                    ctx.userdata.pending_ack_stage = None

            return response

        except Exception as e:
            logger.error(f"[AGENT] Question validation error: {e}", exc_info=True)
            return "Error validating question. Please try again."

    @function_tool
    async def assess_response(
        self,
        ctx: RunContext[InterviewState],
        depth_score: Annotated[int, Field(description="Response depth: 1=vague, 2=surface, 3=adequate, 4=detailed, 5=comprehensive")],
        key_points_covered: Annotated[list[str], Field(description="Key points mentioned")]
    ) -> str:
        """Assess response quality and provide guidance."""
        try:
            current_stage = ctx.userdata.stage

            response_summary = f"Depth: {depth_score}/5. Points: {', '.join(key_points_covered)}"
            ctx.userdata.experience_responses.append(response_summary)

            pending_ack = None
            if ctx.userdata.pending_acknowledgement and not ctx.userdata.transition_acknowledged:
                pending_ack = ctx.userdata.pending_acknowledgement

            q_status = ctx.userdata.get_question_status()
            time_status = ctx.userdata.get_time_status()

            time_remaining_pct = time_status['remaining_pct']
            remaining_sec = time_status['remaining_seconds']
            met_minimum = q_status['met_minimum']

            logger.info(
                f"[AGENT] Response assessment - Stage: {current_stage.value}, "
                f"Depth: {depth_score}/5, Questions: {q_status['asked']}/{q_status['minimum']}"
            )

            status_line = f"[STATUS] Q: {q_status['asked']}/{q_status['minimum']} | Time: {time_remaining_pct:.0f}% ({remaining_sec:.0f}s)"

            # Transition guidance
            if time_remaining_pct <= 10:
                guidance = f"{status_line}\nTIME CRITICAL: Transition NOW."
            elif met_minimum and time_remaining_pct <= 25:
                guidance = f"{status_line}\nMinimum met + time low. TRANSITION NOW."
            elif met_minimum and depth_score >= 3:
                guidance = f"{status_line}\nGood response + minimum met. Consider transitioning."
            elif depth_score >= 4:
                guidance = f"{status_line}\nExcellent response (depth {depth_score}/5)."
            elif depth_score <= 2 and not met_minimum:
                guidance = f"{status_line}\nBrief response. Ask follow-up for more context."
            else:
                guidance = f"{status_line}\nContinue with next question."

            if pending_ack:
                guidance = f"STAGE CHANGE: First say: \"{pending_ack}\" Then proceed.\n\n{guidance}"

            return guidance

        except Exception as e:
            logger.error(f"[AGENT] Response assessment error: {e}", exc_info=True)
            return "Error assessing response. Continue naturally."

    @function_tool
    async def record_response(
        self,
        ctx: RunContext[InterviewState],
        response_summary: Annotated[str, Field(description="Brief summary of candidate's key points")]
    ) -> str:
        """Record key points from candidate's response."""
        try:
            ctx.userdata.experience_responses.append(response_summary)
            logger.info(f"[AGENT] Recorded response: {response_summary[:100]}...")
            return "Response recorded. Continue naturally."
        except Exception as e:
            logger.error(f"[AGENT] Record response error: {e}", exc_info=True)
            return "Error recording response"

    def _get_role_context(self, state: InterviewState) -> str:
        """Generate role-specific interview guidance."""
        role = state.job_role.lower() if state.job_role else ""
        level = state.experience_level.lower() if state.experience_level else "mid"

        role_keywords = {
            'engineer': 'technical skills, problem-solving, system design',
            'developer': 'coding practices, frameworks, debugging',
            'software': 'architecture, development process, code quality',
            'manager': 'team leadership, project planning, stakeholder communication',
            'product': 'product strategy, user research, roadmap',
            'designer': 'design process, user research, collaboration',
            'analyst': 'data analysis, business insights, technical tools',
            'devops': 'infrastructure, CI/CD, monitoring',
        }

        level_expectations = {
            'entry': 'Focus on learning approach, academic/personal projects.',
            'junior': 'Focus on recent projects, technical growth.',
            'mid': 'Focus on independent ownership, technical decisions.',
            'senior': 'Focus on system design, mentoring, leadership.',
            'lead': 'Focus on architecture strategy, team guidance.',
            'staff': 'Focus on org-wide impact, technical strategy.',
        }

        role_focus = "technical experience and problem-solving"
        for key, focus in role_keywords.items():
            if key in role:
                role_focus = focus
                break

        level_guidance = level_expectations.get(level, level_expectations['mid'])

        return f"""
For this {state.job_role or 'position'} role ({level} level):
- Key focus: {role_focus}
- {level_guidance}
"""

    async def on_enter(self):
        """Called when agent becomes active."""
        logger.info(f"[AGENT] Agent activated - greeting {self.candidate_name}")
        self.session.generate_reply(
            instructions=f"Greet the candidate and then immediately call transition_stage."
        )

    async def on_exit(self):
        """Called when agent is deactivated."""
        logger.info("[AGENT] Agent deactivating")


async def emit_user_caption(ctx: JobContext, text: str):
    """Emit user caption to the UI."""
    try:
        import json
        data_payload = json.dumps({"type": "user_caption", "text": text})
        await ctx.room.local_participant.publish_data(data_payload.encode('utf-8'))
    except Exception as e:
        logger.error(f"[UI] Failed to emit user caption: {e}")


async def emit_agent_caption(ctx: JobContext, text: str):
    """Emit agent caption to the UI."""
    try:
        import json
        data_payload = json.dumps({"type": "agent_caption", "text": text})
        await ctx.room.local_participant.publish_data(data_payload.encode('utf-8'))
    except Exception as e:
        logger.error(f"[UI] Failed to emit agent caption: {e}")


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    """Main entry point for LiveKit agent."""
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
        resume_text = None
        job_description = None
        include_profile = True

        if ctx.room.remote_participants:
            participant = list(ctx.room.remote_participants.values())[0]
            if hasattr(participant, 'attributes') and participant.attributes:
                attrs = participant.attributes
                role = attrs.get('role', 'this position')
                level = attrs.get('level', 'mid')
                email = attrs.get('email', '')
                resume_text = attrs.get('resume_text')
                job_description = attrs.get('job_description')
                include_profile = attrs.get('include_profile', 'true').lower() == 'true'
                logger.info(f"[SESSION] Metadata - Role: {role}, Level: {level}, Resume: {bool(resume_text)}")

        candidate_info = {'name': candidate_name, 'role': role}
        logger.info(f"[SESSION] Candidate: {candidate_name} (Role: {role}, Level: {level})")

        # Initialize interview state
        interview_state = InterviewState()
        interview_state.candidate_name = candidate_name
        interview_state.candidate_email = email
        interview_state.job_role = role
        interview_state.experience_level = level
        interview_state.uploaded_resume_text = resume_text
        interview_state.job_description = job_description
        interview_state.include_profile = include_profile
        interview_state.transition_to(InterviewStage.WELCOME)

        # Initialize components
        try:
            stt = deepgram.STT(model="nova-2", language="en-US", smart_format=True)
            logger.info("[SESSION] Deepgram STT initialized")
        except Exception as e:
            logger.error(f"[SESSION] Deepgram STT init error: {e}")
            raise

        try:
            llm = openai.LLM(model="gpt-4o-mini", temperature=0.7)
            logger.info("[SESSION] OpenAI LLM initialized")
        except Exception as e:
            logger.error(f"[SESSION] OpenAI LLM init error: {e}")
            raise

        try:
            tts = openai.TTS(voice="alloy", speed=1.0)
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

        # Conversation history
        conversation_history = {"agent": [], "user": []}
        closing_finalized = {"done": False}

        @session.on("user_input_transcribed")
        def on_user_speech(event):
            if event.is_final:
                import time
                transcript = event.transcript.strip()
                if not transcript:
                    return
                logger.info(f"[USER] {transcript}")
                conversation_history["user"].append({
                    "index": len(conversation_history["user"]),
                    "text": transcript,
                    "timestamp": time.time()
                })
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
                        conversation_history["agent"].append({
                            "index": len(conversation_history["agent"]),
                            "text": agent_text,
                            "timestamp": time.time(),
                            "stage": interview_state.stage.value
                        })
                        asyncio.create_task(emit_agent_caption(ctx, agent_text))
                        
                        # Check for closing message
                        if interview_state.stage == InterviewStage.CLOSING and not closing_finalized["done"]:
                            text_lower = agent_text.lower()
                            closing_indicators = [
                                "thank you" in text_lower and "luck" in text_lower,
                                "good luck" in text_lower,
                                "best of luck" in text_lower,
                            ]
                            if any(closing_indicators) and len(agent_text) > 50:
                                interview_state.closing_message_delivered = True
                                async def schedule_finalization():
                                    if closing_finalized["done"]:
                                        return
                                    closing_finalized["done"] = True
                                    await asyncio.sleep(5.0)
                                    await finalize_and_disconnect()
                                asyncio.create_task(schedule_finalization())
            except Exception as e:
                logger.error(f"[CONVERSATION] Error: {e}", exc_info=True)

        # Handle skip stage requests via data channel
        @ctx.room.on("data_received")
        def on_data_received(data_packet):
            try:
                import json
                payload = json.loads(data_packet.data.decode('utf-8'))
                
                if payload.get('type') == 'skip_stage':
                    target_stage_name = payload.get('target_stage')
                    logger.info(f"[SKIP] Received skip request to: {target_stage_name}")
                    
                    target_stage = interview_state.get_stage_by_name(target_stage_name)
                    if target_stage and interview_state.can_skip_to(target_stage):
                        interview_state.queue_skip_to(target_stage)
                        logger.info(f"[SKIP] Queued skip to {target_stage.value}")
                        
                        # Trigger agent to process skip
                        session.generate_reply(
                            instructions=f"The candidate has requested to skip ahead. Call transition_stage immediately with reason 'candidate requested skip'."
                        )
            except Exception as e:
                logger.error(f"[DATA] Error processing: {e}")

        async def finalize_and_disconnect():
            """Finalize interview and disconnect."""
            try:
                import json
                from datetime import datetime

                # Emit ending notification
                try:
                    data_payload = json.dumps({"type": "interview_ending", "message": "Interview Complete"})
                    await ctx.room.local_participant.publish_data(data_payload.encode('utf-8'))
                except Exception as e:
                    logger.warning(f"[UI] Failed to emit ending: {e}")

                # Save conversation
                history_data = {
                    "candidate": candidate_name,
                    "interview_date": datetime.now().isoformat(),
                    "room_name": ctx.room.name,
                    "conversation": conversation_history,
                    "total_messages": {
                        "agent": len(conversation_history['agent']),
                        "user": len(conversation_history['user'])
                    },
                    "skipped_stages": interview_state.skipped_stages,
                }

                os.makedirs("interviews", exist_ok=True)
                filename = f"interviews/{candidate_name.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

                with open(filename, 'w', encoding='utf-8') as f:
                    import json as json_module
                    json_module.dump(history_data, f, indent=2, ensure_ascii=False)

                logger.info(f"[HISTORY] Saved to {filename}")
                interview_complete.set()
                await asyncio.sleep(2.0)
                await ctx.room.disconnect()

            except Exception as e:
                logger.error(f"[FINALIZE] Error: {e}", exc_info=True)
                interview_complete.set()

        @ctx.room.on("disconnected")
        def on_room_disconnected():
            logger.info("[ROOM] Room disconnected")
            interview_complete.set()

        # Start fallback timer
        fallback_task = asyncio.create_task(
            stage_fallback_timer(session, interview_state, ctx, agent, interview_complete)
        )

        await session.start(agent=agent, room=ctx.room)
        logger.info("[SESSION] Session started")

        await interview_complete.wait()
        logger.info("[SESSION] Interview complete")

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
        logger.info("[SESSION] Cleanup complete")


async def stage_fallback_timer(
    session: AgentSession,
    state: InterviewState,
    ctx: JobContext,
    agent: InterviewAgent,
    interview_complete: asyncio.Event
):
    """Timer that monitors stage progress and forces transitions when limits exceeded."""
    MONITORED_STAGES = {
        InterviewStage.SELF_INTRO,
        InterviewStage.PAST_EXPERIENCE,
        InterviewStage.COMPANY_FIT
    }
    CLOSING_TIMEOUT = 60

    logged_milestones = set()
    last_logged_stage = None
    closing_timeout_logged = False

    logger.info("[TIMER] Fallback timer started")

    try:
        while not interview_complete.is_set():
            await asyncio.sleep(5)

            if interview_complete.is_set():
                break

            current_stage = state.stage

            # Handle CLOSING stage timeout
            if current_stage == InterviewStage.CLOSING:
                elapsed = state.time_in_current_stage()
                if not closing_timeout_logged:
                    logger.info(f"[TIMER] Closing stage - timeout: {CLOSING_TIMEOUT}s")
                    closing_timeout_logged = True
                
                if elapsed > CLOSING_TIMEOUT and not state.closing_message_delivered:
                    logger.warning(f"[FALLBACK] Closing timeout - forcing finalization")
                    try:
                        await session.say(
                            f"Thank you for your time, {agent.candidate_name}. Best of luck!",
                            allow_interruptions=False
                        )
                        await asyncio.sleep(3.0)
                    except Exception as e:
                        logger.warning(f"[FALLBACK] Closing say failed: {e}")
                    interview_complete.set()
                    try:
                        await ctx.room.disconnect()
                    except Exception:
                        pass
                    break
                continue

            if current_stage not in MONITORED_STAGES:
                if current_stage != last_logged_stage:
                    last_logged_stage = current_stage
                    logged_milestones = set()
                continue

            time_status = state.get_time_status()
            q_status = state.get_question_status()
            elapsed = time_status['elapsed']
            limit = time_status['limit']
            elapsed_pct = time_status['elapsed_pct']

            if current_stage != last_logged_stage:
                logger.info(f"[TIMER] Stage '{current_stage.value}' - Limit: {limit}s")
                logged_milestones = set()
                last_logged_stage = current_stage

            # Log milestones
            for pct in [50, 75, 90, 100]:
                if elapsed_pct >= pct and pct not in logged_milestones:
                    logger.info(f"[TIMER] {current_stage.value} at {pct}% ({elapsed:.0f}/{limit}s)")
                    logged_milestones.add(pct)

            # Force transition if limit exceeded
            if elapsed > limit:
                next_stage = state.get_next_stage()
                if next_stage:
                    logger.warning(f"[FALLBACK] FORCING: {current_stage.value} -> {next_stage.value}")

                    state.transition_to(next_stage, forced=True)

                    try:
                        instructions = agent._get_stage_instructions(state, next_stage)
                        await agent.update_instructions(instructions)
                    except Exception as e:
                        logger.error(f"[FALLBACK] Instruction update error: {e}")

                    # Emit stage change
                    try:
                        import json
                        await ctx.room.local_participant.publish_data(
                            json.dumps({"type": "stage_change", "stage": next_stage.value}).encode('utf-8')
                        )
                    except Exception as e:
                        logger.error(f"[UI] Stage change emit error: {e}")

                    # Queue acknowledgement
                    ack_map = {
                        InterviewStage.SELF_INTRO: f"Alright {agent.candidate_name}, please introduce yourself.",
                        InterviewStage.PAST_EXPERIENCE: f"Thank you {agent.candidate_name}! Let's discuss your experience.",
                        InterviewStage.COMPANY_FIT: f"Great insights! Let's talk about company and role fit.",
                        InterviewStage.CLOSING: f"Thank you for sharing. Let me wrap up now.",
                    }

                    ack = ack_map.get(next_stage)
                    if ack:
                        state.pending_acknowledgement = ack
                        state.pending_ack_stage = next_stage.value
                        try:
                            await session.say(ack)
                        except Exception as e:
                            logger.warning(f"[FALLBACK] Say failed: {e}")

                    logged_milestones = set()
                    last_logged_stage = next_stage

    except asyncio.CancelledError:
        logger.info("[TIMER] Fallback timer cancelled")
    except Exception as e:
        logger.error(f"[TIMER] Error: {e}", exc_info=True)


if __name__ == "__main__":
    logger.info("[MAIN] Starting MockFlow-AI Interview Agent")
    cli.run_app(server)