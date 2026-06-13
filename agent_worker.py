"""
MockFlow-AI Interview Agent Worker

Standalone agent that runs as subprocess with API keys passed via environment variables.
FIXED: Uses explicit room connection instead of LiveKit dispatch system.
Terminates automatically after interview ends.
"""

import asyncio
import logging
import os
import sys
from typing import Annotated
from pydantic import Field
import aiohttp

from livekit import api as livekit_api
from livekit.agents import (
    AgentSession,
    Agent,
    RunContext,
    function_tool,
)
from livekit.rtc import Room, RoomOptions
from livekit.plugins import openai, deepgram, silero

from fsm import (InterviewState, InterviewStage, STAGE_TIME_LIMITS, STAGE_MIN_QUESTIONS,
                  BehavioralStage, BehavioralInterviewState,
                  TechnicalVoiceStage, TechnicalVoiceInterviewState,
                  CodingStage, CodingInterviewState)
from tracks import get_track_config
from audio_cache import get_welcome_audio_bytes, get_welcome_script
from prompts import (
    build_stage_instructions,
    get_transition_ack,
    get_fallback_ack,
    build_role_context,
    build_personality_note,
    WELCOME,
    SKIP_STAGE,
    CLOSING_FALLBACK,
)

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

# Get environment variables (passed by parent process)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')
LIVEKIT_URL = os.getenv('LIVEKIT_URL')
LIVEKIT_API_KEY = os.getenv('LIVEKIT_API_KEY')
LIVEKIT_API_SECRET = os.getenv('LIVEKIT_API_SECRET')
INTERVIEW_ROOM_NAME = os.getenv('INTERVIEW_ROOM_NAME')

if not all([OPENAI_API_KEY, DEEPGRAM_API_KEY, LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, INTERVIEW_ROOM_NAME]):
    logger.error("[CONFIG] Missing required API keys or room name in environment")
    logger.error(f"[CONFIG] OpenAI: {bool(OPENAI_API_KEY)}, Deepgram: {bool(DEEPGRAM_API_KEY)}")
    logger.error(f"[CONFIG] LiveKit URL: {bool(LIVEKIT_URL)}, Key: {bool(LIVEKIT_API_KEY)}, Secret: {bool(LIVEKIT_API_SECRET)}")
    logger.error(f"[CONFIG] Room Name: {bool(INTERVIEW_ROOM_NAME)}")
    sys.exit(1)

logger.info("[CONFIG] API keys loaded from environment")
logger.info(f"[CONFIG] LiveKit URL: {LIVEKIT_URL}")
logger.info(f"[CONFIG] Target Room: {INTERVIEW_ROOM_NAME}")


class InterviewAgent(Agent):
    """Mock interview agent with FSM-based stage management."""

    def __init__(self, room=None, candidate_info=None, track_type='intro'):
        """Initialize agent with track-aware greeting."""
        self.candidate_info = candidate_info or {}
        self.candidate_name = self.candidate_info.get('name', 'Candidate')
        self.candidate_role = self.candidate_info.get('role', 'this position')
        self.track_type = track_type

        if track_type == 'intro':
            personalized_greeting = WELCOME.greeting.replace(
                "[CANDIDATE_NAME]", self.candidate_name
            ).replace("[ROLE]", self.candidate_role)
            super().__init__(instructions=personalized_greeting)
        else:
            # New tracks: brief greeting, questions generated in on_enter
            from prompts import build_stage_instructions
            from fsm import BehavioralStage, TechnicalVoiceStage
            if track_type == 'behavioral':
                initial_stage = BehavioralStage.GREETING
            elif track_type == 'coding':
                initial_stage = CodingStage.GREETING
            else:
                initial_stage = TechnicalVoiceStage.GREETING
            greeting_instructions = build_stage_instructions(initial_stage)
            greeting_instructions = greeting_instructions.replace('[CANDIDATE_NAME]', self.candidate_name).replace('[ROLE]', self.candidate_role)
            super().__init__(instructions=greeting_instructions)
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
            track_type = getattr(ctx.userdata, 'track_type', 'intro')

            # Get next stage based on track
            if track_type == 'behavioral' and hasattr(ctx.userdata, 'get_next_behavioral_stage'):
                next_stage = ctx.userdata.get_next_behavioral_stage()
            elif track_type == 'technical_voice' and hasattr(ctx.userdata, 'get_next_technical_voice_stage'):
                next_stage = ctx.userdata.get_next_technical_voice_stage()
            elif track_type == 'coding' and hasattr(ctx.userdata, 'get_next_coding_stage'):
                next_stage = ctx.userdata.get_next_coding_stage()
            else:
                next_stage = ctx.userdata.get_next_stage()

            if not next_stage:
                return f"Cannot transition from {current_stage.value} - interview complete"

            time_in_stage = ctx.userdata.time_in_current_stage()

            # Minimum time gates — relaxed for new tracks (greeting is brief)
            if track_type == 'intro':
                MIN_TIMES = {
                    InterviewStage.WELCOME: 0,
                    InterviewStage.SELF_INTRO: 30,
                    InterviewStage.PAST_EXPERIENCE: 45,
                    InterviewStage.COMPANY_FIT: 30,
                }
                min_time = MIN_TIMES.get(current_stage, 0)
            else:
                min_time = 0  # New tracks: agent decides when ready

            if min_time > 0 and time_in_stage < min_time:
                return (
                    f"Please spend more time in this stage. "
                    f"Current: {time_in_stage:.0f}s, Minimum: {min_time}s"
                )

            ctx.userdata.transition_to(next_stage, forced=False, skipped=False)

            # Update question index for behavioral track
            if track_type == 'behavioral' and hasattr(ctx.userdata, 'current_question_index'):
                stage_val = next_stage.value if hasattr(next_stage, 'value') else str(next_stage)
                if stage_val.startswith('behavioral_q'):
                    q_num = int(stage_val[-1]) - 1  # behavioral_q1 -> index 0
                    ctx.userdata.current_question_index = q_num
                    logger.info(f"[AGENT] Behavioral question index set to {q_num}")

            # Update problem index and activate coding mode for coding track
            if track_type == 'coding' and hasattr(ctx.userdata, 'current_problem_index'):
                stage_val = next_stage.value if hasattr(next_stage, 'value') else str(next_stage)
                if stage_val.startswith('coding_problem_'):
                    p_num = int(stage_val.split('_')[-1]) - 1  # coding_problem_1 -> 0
                    ctx.userdata.current_problem_index = p_num
                    ctx.userdata.coding_stage_active = True
                    from datetime import datetime
                    ctx.userdata.problem_start_times[str(p_num)] = datetime.now().isoformat()
                    logger.info(f"[AGENT] Coding problem index set to {p_num}")
                elif stage_val in ('closing', 'warm_up', 'self_intro', 'greeting'):
                    ctx.userdata.coding_stage_active = False

            stage_instructions = self._get_stage_instructions(ctx.userdata, next_stage)
            await self.update_instructions(stage_instructions)

            logger.info(
                f"[AGENT] Stage transition: {current_stage.value} -> {next_stage.value} "
                f"(reason: {reason}, time_in_stage: {time_in_stage:.1f}s)"
            )

            await self._emit_stage_change(next_stage)

            acknowledgement = get_transition_ack(
                next_stage,
                self.candidate_name,
                ctx.userdata.job_role or 'this position'
            )

            # Detect closing for any track
            is_closing = (next_stage.value == 'closing')

            if is_closing:
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

    def _get_stage_instructions(self, state: InterviewState, stage) -> str:
        """Build personalized stage instructions with track-aware document context."""
        track_type = getattr(state, 'track_type', 'intro')
        stage_val = stage.value if hasattr(stage, 'value') else str(stage)

        base_instructions = build_stage_instructions(stage)

        # Inject behavioral question template variables
        if track_type == 'behavioral' and stage_val.startswith('behavioral_q'):
            idx = getattr(state, 'current_question_index', 0)
            questions = getattr(state, 'generated_questions', [])
            q_text = questions[idx]['main_question'] if questions and idx < len(questions) else 'Ask a relevant behavioral question'
            competency = questions[idx].get('competency', 'General') if questions and idx < len(questions) else 'General'
            total = getattr(state, 'active_question_count', 2)
            depth = getattr(state, 'depth_setting', 'medium')
            base_instructions = base_instructions.replace('{question_index}', str(idx + 1))
            base_instructions = base_instructions.replace('{total_questions}', str(total))
            base_instructions = base_instructions.replace('{question_text}', q_text)
            base_instructions = base_instructions.replace('{competency}', competency)
            base_instructions = base_instructions.replace('{depth_setting}', depth)

        # Inject technical voice topic variables
        elif track_type == 'technical_voice' and 'technical_concepts' in stage_val:
            try:
                idx = int(stage_val.split('_')[-1]) - 1
            except (ValueError, IndexError):
                idx = 0
            topics = getattr(state, 'selected_topics', [])
            topic_name = topics[idx] if topics and idx < len(topics) else 'this topic'
            base_instructions = base_instructions.replace('{topic_name}', topic_name)
            base_instructions = base_instructions.replace('{experience_level}', state.experience_level or 'mid')

        # Replace common placeholders
        base_instructions = base_instructions.replace('[ROLE]', state.job_role or 'this position')
        base_instructions = base_instructions.replace('[CANDIDATE_NAME]', self.candidate_name)
        topics_str = ', '.join(getattr(state, 'selected_topics', [])) or 'the selected topics'
        base_instructions = base_instructions.replace('[TOPICS]', topics_str)

        # Document context
        placeholder = "[DOCUMENT_CONTEXT]"
        doc_context = ""
        if track_type == 'intro':
            if stage in [InterviewStage.PAST_EXPERIENCE, InterviewStage.COMPANY_FIT]:
                doc_context = state.get_document_context(stage=stage)
        else:
            doc_context = state.get_document_context(stage=stage)

        if doc_context:
            base_instructions = base_instructions.replace(placeholder, f"\n{doc_context}\n")
        else:
            base_instructions = base_instructions.replace(placeholder, "")

        role_context = build_role_context(
            state.job_role or "this position",
            state.experience_level or "mid"
        )
        personality_note = build_personality_note(
            self.candidate_name,
            state.job_role or "a technical position",
            state.experience_level or "mid-level",
            role_context
        )

        return base_instructions + personality_note

    async def _emit_stage_change(self, new_stage: InterviewStage):
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

            pending_ack = None
            should_clear_ack = False

            if ctx.userdata.pending_acknowledgement and not ctx.userdata.transition_acknowledged:
                pending_ack = ctx.userdata.pending_acknowledgement
                pending_stage = ctx.userdata.pending_ack_stage

                if current_stage == pending_stage:
                    should_clear_ack = True

            time_status = ctx.userdata.get_time_status()
            time_remaining_pct = time_status['remaining_pct']
            remaining_sec = time_status['remaining_seconds']

            normalized = question.lower().strip().rstrip('?.,!')

            for asked in ctx.userdata.questions_asked:
                asked_normalized = asked.lower().strip().rstrip('?.,!')
                if normalized == asked_normalized or normalized in asked_normalized or asked_normalized in normalized:
                    return f"You already asked a similar question: '{asked}'. Please ask something different."

            ctx.userdata.questions_asked.append(question)
            ctx.userdata.questions_per_stage[current_stage] = stage_questions + 1
            new_count = stage_questions + 1

            logger.info(f"[AGENT] Approved question #{len(ctx.userdata.questions_asked)} ({new_count}/{minimum} in {current_stage})")

            response = f"Question approved ({new_count}/{minimum}). Time: {time_remaining_pct:.0f}% ({remaining_sec:.0f}s). "

            if new_count >= minimum:
                if time_remaining_pct <= 25:
                    response += "MINIMUM MET + TIME LOW. Transition soon. "
                else:
                    response += "Minimum met. May transition when ready. "
            else:
                response += f"Need {minimum - new_count} more. "

            response += f"Now ask: '{question}'"

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
    async def generate_interview_questions(
        self,
        ctx: RunContext[InterviewState],
        count: Annotated[int, Field(description="Number of main questions to generate (2 for light, 3 for medium/deep)")]
    ) -> str:
        """Generate interview questions via LLM based on track, framework, and candidate context. Call this ONCE at the start of the interview."""
        try:
            track_type = getattr(ctx.userdata, 'track_type', 'intro')
            if track_type not in ('behavioral', 'technical_voice', 'coding'):
                return "Question generation only available for behavioral, technical voice, and coding tracks."

            from openai import OpenAI
            from prompts import QUESTION_GENERATION
            import json as _json

            client = OpenAI(api_key=OPENAI_API_KEY)
            resume_snippet = (ctx.userdata.uploaded_resume_text or '')[:1500]
            jd_snippet = (ctx.userdata.job_description or '')[:800]

            if track_type == 'behavioral':
                framework = getattr(ctx.userdata, 'framework', 'amazon')
                depth = getattr(ctx.userdata, 'depth_setting', 'medium')
                custom_q = getattr(ctx.userdata, 'custom_questions', [])
                custom_q_str = '\n'.join(custom_q) if custom_q else 'None'
                competencies = QUESTION_GENERATION.behavioral_framework_competencies.get(framework, QUESTION_GENERATION.behavioral_framework_competencies['generic'])

                prompt = QUESTION_GENERATION.behavioral_system.format(
                    count=count,
                    framework=framework.title(),
                    role=ctx.userdata.job_role or 'Software Engineer',
                    level=ctx.userdata.experience_level or 'mid',
                    resume_snippet=resume_snippet or 'Not provided',
                    jd_snippet=jd_snippet or 'Not provided',
                    custom_questions=custom_q_str,
                    framework_competencies=competencies,
                )

                response = client.chat.completions.create(
                    model='gpt-4o-mini',
                    messages=[{'role': 'user', 'content': prompt}],
                    temperature=0.7,
                    max_tokens=1000,
                )
                raw = response.choices[0].message.content.strip()
                parsed = _json.loads(raw)
                questions = parsed.get('questions', [])

                ctx.userdata.generated_questions = questions
                ctx.userdata.active_question_count = min(len(questions), 3)
                logger.info(f"[AGENT] Generated {len(questions)} behavioral questions for framework: {framework}")
                return f"Generated {len(questions)} questions. Active question count: {ctx.userdata.active_question_count}. Now transition_stage when ready."

            elif track_type == 'technical_voice':
                topics = getattr(ctx.userdata, 'selected_topics', [])
                if not topics:
                    return "No topics selected. Please transition to self_intro first."

                all_questions = []
                for topic in topics[:3]:
                    prompt = QUESTION_GENERATION.technical_system.format(
                        topic=topic,
                        role=ctx.userdata.job_role or 'Software Engineer',
                        level=ctx.userdata.experience_level or 'mid',
                        resume_snippet=resume_snippet or 'Not provided',
                    )
                    response = client.chat.completions.create(
                        model='gpt-4o-mini',
                        messages=[{'role': 'user', 'content': prompt}],
                        temperature=0.7,
                        max_tokens=400,
                    )
                    raw = response.choices[0].message.content.strip()
                    parsed = _json.loads(raw)
                    q_list = parsed.get('questions', [])
                    all_questions.append({'topic': topic, 'questions': q_list})

                ctx.userdata.generated_questions = all_questions
                ctx.userdata.active_topic_count = len(topics[:3])
                logger.info(f"[AGENT] Generated questions for {len(all_questions)} topics")
                return f"Generated questions for {len(all_questions)} topics. Now transition to self_intro."

            elif track_type == 'coding':
                from prompts import QUESTION_GENERATION
                problem_count = getattr(ctx.userdata, 'active_problem_count', 2)
                preferred_language = getattr(ctx.userdata, 'preferred_language', 'python')
                difficulty = 'medium'  # Could be passed from form later

                # Adjust difficulty based on experience level
                level = ctx.userdata.experience_level or 'mid'
                if level in ('entry', 'junior'):
                    difficulty = 'easy'
                elif level in ('senior', 'lead', 'staff'):
                    difficulty = 'hard'

                prompt = QUESTION_GENERATION.coding_system.format(
                    count=problem_count,
                    role=ctx.userdata.job_role or 'Software Engineer',
                    level=level,
                    resume_snippet=(ctx.userdata.uploaded_resume_text or '')[:1000] or 'Not provided',
                    language=preferred_language,
                    difficulty=difficulty,
                    time_limit_minutes=15,
                )

                response = client.chat.completions.create(
                    model='gpt-4o-mini',
                    messages=[{'role': 'user', 'content': prompt}],
                    temperature=0.7,
                    max_tokens=1500,
                )
                raw = response.choices[0].message.content.strip()
                parsed = _json.loads(raw)
                problems = parsed.get('problems', [])

                ctx.userdata.generated_problems = problems
                ctx.userdata.active_problem_count = min(len(problems), 2)
                logger.info(f"[AGENT] Generated {len(problems)} coding problems (difficulty: {difficulty})")
                return f"Generated {len(problems)} coding problems. Active problem count: {ctx.userdata.active_problem_count}. Now transition_stage when ready to begin."

        except Exception as e:
            logger.error(f"[AGENT] Question generation error: {e}", exc_info=True)
            return f"Failed to generate questions: {e}. Proceed with general questions based on role."

    @function_tool
    async def get_current_question(
        self,
        ctx: RunContext[InterviewState]
    ) -> str:
        """Get the main question for the current stage. Call this when entering a new question stage."""
        try:
            track_type = getattr(ctx.userdata, 'track_type', 'intro')
            stage_val = ctx.userdata.stage.value if hasattr(ctx.userdata.stage, 'value') else ''

            if track_type == 'behavioral' and stage_val.startswith('behavioral_q'):
                idx = getattr(ctx.userdata, 'current_question_index', 0)
                questions = getattr(ctx.userdata, 'generated_questions', [])
                if not questions:
                    return "No questions generated yet. Ask a general behavioral question based on the framework."
                if idx >= len(questions):
                    return "All questions covered. Transition to closing."
                q = questions[idx]
                return (
                    f"Main question: \"{q.get('main_question', 'Tell me about a relevant experience.')}\"\n"
                    f"Competency: {q.get('competency', 'General')}\n"
                    f"Follow-up probes if needed: {q.get('follow_up_probes', [])}"
                )

            elif track_type == 'technical_voice' and 'technical_concepts' in stage_val:
                # technical_concepts_1 -> index 0, etc.
                try:
                    idx = int(stage_val.split('_')[-1]) - 1
                except (ValueError, IndexError):
                    idx = 0
                all_q = getattr(ctx.userdata, 'generated_questions', [])
                if not all_q or idx >= len(all_q):
                    return "No questions available for this topic. Ask general conceptual questions."
                topic_data = all_q[idx]
                topic = topic_data.get('topic', 'this topic')
                questions = topic_data.get('questions', [])
                return (
                    f"Topic: {topic}\n"
                    f"Questions to ask: {questions}\n"
                    f"Ask them one at a time, adapting based on responses."
                )
            elif track_type == 'coding' and stage_val.startswith('coding_problem_'):
                idx = getattr(ctx.userdata, 'current_problem_index', 0)
                problems = getattr(ctx.userdata, 'generated_problems', [])
                if not problems or idx >= len(problems):
                    return "No problems generated yet. Generate problems first with generate_interview_questions."
                problem = problems[idx]
                attempts_done = ctx.userdata.get_attempts_for_problem(idx) if hasattr(ctx.userdata, 'get_attempts_for_problem') else 0
                max_attempts = 3

                # Emit problem to frontend via data channel
                try:
                    import json
                    problem_payload = json.dumps({
                        'type': 'coding_problem',
                        'problem': problem,
                        'problem_index': idx,
                        'attempt_number': attempts_done + 1,
                        'max_attempts': max_attempts,
                        'time_limit_minutes': problem.get('time_limit_minutes', 15),
                    })
                    if self.room and self.room.local_participant:
                        import asyncio
                        asyncio.create_task(
                            self.room.local_participant.publish_data(problem_payload.encode('utf-8'))
                        )
                        logger.info(f"[AGENT] Emitted coding problem {idx} to frontend")
                except Exception as emit_err:
                    logger.warning(f"[AGENT] Failed to emit problem to UI: {emit_err}")

                examples_str = '\n'.join([
                    f"  Input: {ex.get('input', '')} -> Output: {ex.get('output', '')}"
                    for ex in problem.get('examples', [])[:2]
                ])
                return (
                    f"Problem {idx + 1}: {problem.get('title', 'Untitled')}\n"
                    f"Description: {problem.get('description', '')}\n"
                    f"Examples:\n{examples_str}\n"
                    f"Constraints: {', '.join(problem.get('constraints', []))}\n"
                    f"Time limit: {problem.get('time_limit_minutes', 15)} minutes\n"
                    f"Attempt: {attempts_done + 1} of {max_attempts}\n"
                    f"Problem has been sent to the candidate's editor."
                )
            else:
                return "get_current_question is only for behavioral_q, technical_concepts, and coding_problem stages."
        except Exception as e:
            logger.error(f"[AGENT] get_current_question error: {e}", exc_info=True)
            return "Error getting question. Proceed with a general question."

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

    @function_tool
    async def evaluate_code_submission(
        self,
        ctx: RunContext[InterviewState],
        problem_index: Annotated[int, Field(description="0-based index of the problem being evaluated")],
        code: Annotated[str, Field(description="The candidate's submitted code")],
        language: Annotated[str, Field(description="Programming language used")]
    ) -> str:
        """Evaluate submitted code using a separate LLM call. Call when code is submitted or timer expires."""
        try:
            from prompts import CODE_EVALUATOR
            from openai import OpenAI
            import json as _json

            problems = getattr(ctx.userdata, 'generated_problems', [])
            if not problems or problem_index >= len(problems):
                return "No problem found for this index. Proceed naturally."

            problem = problems[problem_index]

            client = OpenAI(api_key=OPENAI_API_KEY)

            user_prompt = CODE_EVALUATOR.user_template.format(
                problem_title=problem.get('title', 'Coding Problem'),
                problem_description=problem.get('description', ''),
                problem_examples=str(problem.get('examples', [])),
                problem_constraints=', '.join(problem.get('constraints', [])),
                language=language,
                code=code,
            )

            response = client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[
                    {'role': 'system', 'content': CODE_EVALUATOR.system},
                    {'role': 'user', 'content': user_prompt}
                ],
                temperature=0.3,
                max_tokens=600,
            )

            raw = response.choices[0].message.content.strip()
            evaluation = _json.loads(raw)

            # Record submission in state
            attempt_num = 1
            if hasattr(ctx.userdata, 'record_submission'):
                attempt_num = ctx.userdata.record_submission(problem_index, code, language, evaluation)

            # Emit evaluation result to frontend
            try:
                import json
                max_attempts = 3
                eval_payload = json.dumps({
                    'type': 'evaluation_result',
                    'evaluation': evaluation,
                    'attempt': attempt_num,
                    'max_attempts': max_attempts,
                    'problem_index': problem_index,
                })
                if self.room and self.room.local_participant:
                    await self.room.local_participant.publish_data(eval_payload.encode('utf-8'))
            except Exception as emit_err:
                logger.warning(f"[AGENT] Failed to emit evaluation to UI: {emit_err}")

            # Persist submission via HTTP (fire and forget)
            try:
                from supabase_client import supabase_client
                user_id = getattr(ctx.userdata, '_user_id', None)
                interview_id = getattr(ctx.userdata, '_interview_id', None)
                if user_id and interview_id:
                    supabase_client.save_coding_submission(
                        user_id=user_id,
                        interview_id=interview_id,
                        problem_title=problem.get('title', 'Coding Problem'),
                        problem_description=problem.get('description', ''),
                        language=language,
                        code_submitted=code,
                        attempt_number=attempt_num,
                        evaluation_result=evaluation,
                    )
            except Exception as db_err:
                logger.warning(f"[AGENT] Failed to save submission to DB: {db_err}")

            verbal_feedback = evaluation.get('brief_verbal_feedback', 'Interesting approach. Let me share some observations.')
            logger.info(f"[AGENT] Code evaluated: correctness={evaluation.get('correctness')}, approach={evaluation.get('approach_quality')}")

            attempts_remaining = max_attempts - attempt_num
            if attempts_remaining > 0 and evaluation.get('correctness') != 'pass':
                return f"Evaluation complete. Verbal feedback: {verbal_feedback}\nAttempts remaining: {attempts_remaining}. Ask if they want to revise."
            else:
                return f"Evaluation complete. Verbal feedback: {verbal_feedback}\nNo more attempts for this problem. Transition when ready."

        except Exception as e:
            logger.error(f"[AGENT] evaluate_code_submission error: {e}", exc_info=True)
            return "Could not evaluate code automatically. Give feedback based on what you observed of their approach."

    @function_tool
    async def skip_coding_problem(
        self,
        ctx: RunContext[InterviewState]
    ) -> str:
        """Skip the current coding problem and move to the next one or closing."""
        try:
            current_stage = ctx.userdata.stage
            current_idx = getattr(ctx.userdata, 'current_problem_index', 0)

            # Mark as skipped
            if hasattr(ctx.userdata, 'skipped_problems'):
                ctx.userdata.skipped_problems.append(current_idx)
            ctx.userdata.coding_stage_active = False

            logger.info(f"[AGENT] Skipping coding problem {current_idx} at stage {current_stage.value}")
            return "Problem skipped. Now call transition_stage to move to the next problem or closing."

        except Exception as e:
            logger.error(f"[AGENT] skip_coding_problem error: {e}", exc_info=True)
            return "Error skipping problem. Call transition_stage manually."

    async def on_enter(self):
        """Called when agent becomes active."""
        logger.info(f"[AGENT] on_enter() called for candidate: {self.candidate_name}, track: {self.track_type}")
        if self.track_type == 'intro':
            # Original behavior: LLM generates the greeting
            logger.info("[AGENT] Triggering intro greeting generation...")
            self.session.generate_reply()
        else:
            # New tracks: Play cached welcome audio, then LLM takes over
            audio_bytes = get_welcome_audio_bytes(self.track_type)
            if audio_bytes:
                try:
                    logger.info(f"[AGENT] Playing cached welcome audio for track: {self.track_type}")
                    await self.session.say(get_welcome_script(self.track_type), allow_interruptions=False)
                except Exception as e:
                    logger.warning(f"[AGENT] Failed to play cached audio, using LLM: {e}")
                    self.session.generate_reply()
            else:
                # No cached audio: LLM generates greeting
                logger.warning(f"[AGENT] No cached audio for track {self.track_type}, using LLM greeting")
                self.session.generate_reply()

    async def on_exit(self):
        """Called when agent is deactivated."""
        logger.info("[AGENT] Agent deactivating")


async def emit_user_caption(room: Room, text: str):
    """Emit user caption to the UI."""
    try:
        import json
        data_payload = json.dumps({"type": "user_caption", "text": text})
        await room.local_participant.publish_data(data_payload.encode('utf-8'))
    except Exception as e:
        logger.error(f"[UI] Failed to emit user caption: {e}")


async def _async_skip_coding_problem(interview_state, room, session):
    """Handle skip_coding_problem: advance to next problem or closing."""
    import json as _json
    try:
        from fsm import CodingStage
        current_idx = getattr(interview_state, 'current_problem_index', 0)
        problems = getattr(interview_state, 'generated_problems', [])
        active_count = getattr(interview_state, 'active_problem_count', len(problems))

        next_idx = current_idx + 1
        if next_idx < active_count and next_idx < len(problems):
            # Push next problem
            interview_state.current_problem_index = next_idx
            problem = problems[next_idx]
            attempts_done = getattr(interview_state, 'submissions_per_problem', {}).get(next_idx, 0)
            payload_out = _json.dumps({
                'type': 'coding_problem',
                'problem': problem,
                'problem_index': next_idx,
                'attempt_number': attempts_done + 1,
                'max_attempts': 3,
                'time_limit_minutes': problem.get('time_limit_minutes', 15),
            })
            await room.local_participant.publish_data(payload_out.encode('utf-8'), reliable=True)
            logger.info(f"[CODE] Skipped to problem {next_idx}: {problem.get('title', '?')}")
        else:
            # Move to closing
            interview_state.stage = CodingStage.CLOSING
            interview_state.coding_stage_active = False
            closing_payload = _json.dumps({'type': 'stage_update', 'stage': 'closing'})
            await room.local_participant.publish_data(closing_payload.encode('utf-8'), reliable=True)
            if session:
                try:
                    await session.say("Great work on the coding problems. Let's wrap up.", allow_interruptions=True)
                except Exception:
                    pass
            logger.info("[CODE] All problems done, moved to closing")
    except Exception as e:
        logger.error(f"[CODE] _async_skip_coding_problem failed: {e}", exc_info=True)


async def _async_handle_ready_for_problem(interview_state, room):
    """Handle ready_for_problem signal: generate problems if needed, then push to frontend."""
    import json as _json
    try:
        # Generate problems on-demand if not yet generated
        if not getattr(interview_state, 'generated_problems', None):
            logger.info("[CODING] Generating problems on-demand for ready_for_problem")
            try:
                import openai as _openai
                from prompts import QUESTION_GENERATION
                _client = _openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
                role = getattr(interview_state, 'job_role', 'Software Engineer')
                level = getattr(interview_state, 'experience_level', 'mid')
                count = getattr(interview_state, 'active_problem_count', 1)
                difficulty = 'easy' if level in ('entry', 'junior') else ('hard' if level in ('senior', 'lead') else 'medium')
                resp = await _client.chat.completions.create(
                    model='gpt-4o-mini',
                    messages=[
                        {'role': 'system', 'content': QUESTION_GENERATION.coding_system},
                        {'role': 'user', 'content': f'Generate {count} {difficulty} coding problem(s) for a {level} {role}. Return valid JSON only.'}
                    ],
                    temperature=0.7,
                    max_tokens=1500,
                )
                raw = resp.choices[0].message.content.strip()
                if raw.startswith('```'):
                    raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
                parsed = _json.loads(raw)
                interview_state.generated_problems = parsed.get('problems', [])
                interview_state.active_problem_count = min(len(interview_state.generated_problems), count)
                logger.info(f"[CODING] Generated {len(interview_state.generated_problems)} problems on-demand")
            except Exception as _e:
                logger.error(f"[CODING] Problem generation failed: {_e}")
                interview_state.generated_problems = []

        # Push first problem to frontend
        problems = getattr(interview_state, 'generated_problems', [])
        if problems:
            problem = problems[0]
            interview_state.current_problem_index = 0
            interview_state.coding_stage_active = True
            payload_out = _json.dumps({
                'type': 'coding_problem',
                'problem': problem,
                'problem_index': 0,
                'attempt_number': 1,
                'max_attempts': 3,
                'time_limit_minutes': problem.get('time_limit_minutes', 15),
            })
            await room.local_participant.publish_data(payload_out.encode('utf-8'), reliable=True)
            logger.info(f"[CODING] Pushed problem to frontend: {problem.get('title', '?')}")
        else:
            logger.warning("[CODING] No problems to push after generation attempt")
    except Exception as e:
        logger.error(f"[CODING] _async_handle_ready_for_problem failed: {e}", exc_info=True)


async def emit_agent_caption(room: Room, text: str):
    """Emit agent caption to the UI."""
    try:
        import json
        data_payload = json.dumps({"type": "agent_caption", "text": text})
        await room.local_participant.publish_data(data_payload.encode('utf-8'))
    except Exception as e:
        logger.error(f"[UI] Failed to emit agent caption: {e}")


async def execute_skip_transition(
    session: AgentSession,
    interview_state: InterviewState,
    target_stage: InterviewStage,
    agent: InterviewAgent,
    room: Room
):
    """Execute a skip transition directly without relying on LLM tool calls."""
    try:
        current_stage = interview_state.stage
        logger.info(f"[SKIP] Executing forced skip: {current_stage.value} -> {target_stage.value}")

        interview_state.transition_to(target_stage, forced=False, skipped=True)

        stage_instructions = agent._get_stage_instructions(interview_state, target_stage)
        await agent.update_instructions(stage_instructions)

        try:
            import json
            data_payload = json.dumps({
                "type": "stage_change",
                "stage": target_stage.value
            })
            await room.local_participant.publish_data(data_payload.encode('utf-8'))
            logger.info(f"[SKIP] UI notified of stage change to {target_stage.value}")
        except Exception as e:
            logger.error(f"[SKIP] Failed to emit stage change: {e}")

        ack = get_transition_ack(
            target_stage,
            agent.candidate_name,
            interview_state.job_role or 'this position'
        )

        if ack:
            logger.info(f"[SKIP] Delivering acknowledgement: {ack[:50]}...")
            try:
                await session.say(ack, allow_interruptions=False)
            except Exception as e:
                logger.warning(f"[SKIP] Failed to deliver acknowledgement: {e}")

        logger.info(f"[SKIP] Skip transition complete to {target_stage.value}")

    except Exception as e:
        logger.error(f"[SKIP] Error executing skip transition: {e}", exc_info=True)


async def _evaluate_code_async(
    session: AgentSession,
    _agent,
    state,
    room: Room,
    problem_index: int,
    code: str,
    language: str
):
    """Evaluate code submission asynchronously and have agent speak feedback."""
    try:
        from prompts import CODE_EVALUATOR
        import openai as _openai
        import json as _json

        problems = getattr(state, 'generated_problems', [])
        if not problems or problem_index >= len(problems):
            logger.warning(f"[CODE] No problem at index {problem_index}")
            return

        problem = problems[problem_index]

        client = _openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
        user_prompt = CODE_EVALUATOR.user_template.format(
            problem_title=problem.get('title', 'Coding Problem'),
            problem_description=problem.get('description', ''),
            problem_examples=str(problem.get('examples', [])),
            problem_constraints=', '.join(problem.get('constraints', [])),
            language=language,
            code=code,
        )

        response = await client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': CODE_EVALUATOR.system},
                {'role': 'user', 'content': user_prompt}
            ],
            temperature=0.3,
            max_tokens=600,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith('```'):
            raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
        try:
            evaluation = _json.loads(raw)
        except Exception:
            evaluation = {'brief_verbal_feedback': 'Thanks for your submission. Let me review it.'}

        # Record submission in state
        attempt_num = 1
        if hasattr(state, 'submissions_per_problem'):
            state.submissions_per_problem[problem_index] = state.submissions_per_problem.get(problem_index, 0) + 1
            attempt_num = state.submissions_per_problem[problem_index]
        if hasattr(state, 'submissions'):
            state.submissions.append({
                'problem_index': problem_index,
                'attempt': attempt_num,
                'code': code,
                'language': language,
                'evaluation': evaluation,
            })

        # Push evaluation result to frontend
        eval_payload = _json.dumps({
            'type': 'evaluation_result',
            'evaluation': evaluation,
            'attempt': attempt_num,
            'max_attempts': 3,
            'problem_index': problem_index,
        })
        await room.local_participant.publish_data(eval_payload.encode('utf-8'), reliable=True)
        logger.info(f"[CODE] Evaluation sent to frontend for problem {problem_index}, attempt {attempt_num}")

        # Agent speaks brief feedback
        verbal = evaluation.get('brief_verbal_feedback', '')
        if verbal and session:
            try:
                await session.say(verbal, allow_interruptions=True)
            except Exception as say_err:
                logger.warning(f"[CODE] session.say failed: {say_err}")

    except Exception as e:
        logger.error(f"[CODE] _evaluate_code_async failed: {e}", exc_info=True)


async def run_interview():
    """
    Main entry point - EXPLICITLY connects to specific room.
    
    This bypasses LiveKit's dispatch system entirely.
    The worker connects directly to the room it was spawned for.
    """
    logger.info(f"[MAIN] Starting interview agent for room: {INTERVIEW_ROOM_NAME}")
    
    interview_complete = asyncio.Event()
    fallback_task = None
    http_session = None
    room = None
    
    try:
        # Create shared HTTP session for plugins
        # This is required when not using cli.run_app()
        http_session = aiohttp.ClientSession()
        logger.info("[MAIN] Created shared HTTP session for plugins")
        
        # Generate agent token for this specific room
        token = livekit_api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        token.with_identity("interview-agent")
        token.with_name("AI Interviewer")
        token.with_grants(livekit_api.VideoGrants(
            room_join=True,
            room=INTERVIEW_ROOM_NAME,
            can_publish=True,
            can_subscribe=True,
        ))
        agent_token = token.to_jwt()
        
        logger.info(f"[MAIN] Generated agent token for room: {INTERVIEW_ROOM_NAME}")
        
        # Create room and connect DIRECTLY (no dispatch)
        room = Room()
        
        logger.info(f"[MAIN] Connecting to LiveKit: {LIVEKIT_URL}")
        await room.connect(LIVEKIT_URL, agent_token)
        logger.info(f"[MAIN] Connected to room: {room.name}")
        
        # Wait for participant to join
        logger.info("[MAIN] Waiting for participant to join...")
        
        # Extract candidate info from room name or wait for participant
        room_parts = room.name.split('-')
        candidate_name = ' '.join(room_parts[1:-1]).title() if len(room_parts) > 2 else "Candidate"
        
        role = 'this position'
        level = 'mid'
        email = ''
        resume_text = None
        job_description = None
        include_profile = True
        user_id = None
        track_type = 'intro'
        framework = 'amazon'
        depth = 'medium'
        custom_questions = []
        topics = []
        custom_topics = []
        
        # Wait for remote participant with timeout
        wait_start = asyncio.get_event_loop().time()
        while not room.remote_participants:
            if asyncio.get_event_loop().time() - wait_start > 60:
                logger.error("[MAIN] Timeout waiting for participant")
                await room.disconnect()
                return
            await asyncio.sleep(0.5)
        
        # Get participant attributes
        participant = list(room.remote_participants.values())[0]
        if hasattr(participant, 'attributes') and participant.attributes:
            attrs = participant.attributes
            role = attrs.get('role', 'this position')
            level = attrs.get('level', 'mid')
            email = attrs.get('email', '')
            resume_text = attrs.get('resume_text')
            job_description = attrs.get('job_description')
            include_profile = attrs.get('include_profile', 'true').lower() == 'true'
            user_id = attrs.get('user_id')
            track_type = attrs.get('track', 'intro')
            framework = attrs.get('framework', 'amazon')
            depth = attrs.get('depth', 'medium')
            custom_questions_str = attrs.get('custom_questions', '')
            custom_questions = [q.strip() for q in custom_questions_str.split('\n') if q.strip()] if custom_questions_str else []
            topics_str = attrs.get('topics', '')
            topics = [t.strip() for t in topics_str.split(',') if t.strip()] if topics_str else []
            custom_topics_str = attrs.get('custom_topics', '')
            custom_topics = [t.strip() for t in custom_topics_str.split(',') if t.strip()] if custom_topics_str else []
            logger.info(f"[MAIN] Participant attributes - Role: {role}, Level: {level}, Resume: {bool(resume_text)}")
            logger.info(f"[MAIN] Track: {track_type}, Framework: {framework}, Depth: {depth}, Topics: {topics}")
        
        candidate_info = {'name': candidate_name, 'role': role}
        logger.info(f"[MAIN] Candidate: {candidate_name} (Role: {role}, Level: {level})")

        # Initialize interview state based on track
        track_config = get_track_config(track_type)

        if track_type == 'behavioral':
            interview_state = BehavioralInterviewState()
            interview_state.framework = framework
            interview_state.depth_setting = depth
            interview_state.custom_questions = custom_questions
        elif track_type == 'technical_voice':
            interview_state = TechnicalVoiceInterviewState()
            all_topics = topics + custom_topics
            interview_state.selected_topics = all_topics[:3]  # Max 3 topics
            interview_state.active_topic_count = len(interview_state.selected_topics)
        elif track_type == 'coding':
            interview_state = CodingInterviewState()
            preferred_lang = attrs.get('preferred_language', 'python') if 'attrs' in dir() else 'python'
            interview_state.preferred_language = preferred_lang
            problem_count = int(attrs.get('problem_count', '2')) if 'attrs' in dir() else 2
            interview_state.active_problem_count = min(max(problem_count, 1), 2)
        else:
            interview_state = InterviewState()

        interview_state.candidate_name = candidate_name
        interview_state.candidate_email = email
        interview_state.job_role = role
        interview_state.experience_level = level
        interview_state.uploaded_resume_text = resume_text
        interview_state.job_description = job_description
        interview_state.include_profile = include_profile
        interview_state.track = track_type

        if track_type == 'intro':
            interview_state.transition_to(InterviewStage.WELCOME)
        elif track_type == 'behavioral':
            interview_state.transition_to(BehavioralStage.GREETING)
        elif track_type == 'technical_voice':
            interview_state.transition_to(TechnicalVoiceStage.GREETING)
        elif track_type == 'coding':
            interview_state.transition_to(CodingStage.GREETING)
        else:
            interview_state.transition_to(InterviewStage.WELCOME)

        logger.info(f"[MAIN] Interview state initialized: track={track_type}, stage={interview_state.stage.value}")
        
        # Initialize components
        # Note: Only Deepgram STT requires http_session when running outside cli.run_app()
        # OpenAI plugins use their own internal client
        stt = None
        llm = None
        tts = None
        vad = None
        
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
            # Silero VAD with optimized settings for lower CPU usage
            # Default settings cause "inference is slower than realtime" on limited CPU
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
        
        # Create agent
        agent = InterviewAgent(room=room, candidate_info=candidate_info, track_type=track_type)
        logger.info(f"[MAIN] InterviewAgent created for candidate: {candidate_name}")
        
        # Create session with optimized settings for Render's limited CPU
        session = AgentSession(
            userdata=interview_state,
            stt=stt,
            llm=llm,
            tts=tts,
            vad=vad,
            allow_interruptions=True,
            min_endpointing_delay=0.8,   # Increased from 0.5 - more tolerance for pauses
            max_endpointing_delay=4.0,   # Increased from 3.0 - wait longer before cutting off
        )
        logger.info("[MAIN] AgentSession created with optimized settings")
        
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
                asyncio.create_task(emit_user_caption(room, transcript))
        
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
                        asyncio.create_task(emit_agent_caption(room, agent_text))

                        if getattr(interview_state.stage, 'value', '') == 'closing' and not closing_finalized["done"]:
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
        
        @room.on("data_received")
        def on_data_received(data_packet):
            try:
                import json
                payload = json.loads(data_packet.data.decode('utf-8'))

                if payload.get('type') == 'skip_intro':
                    logger.info("[SKIP] Received skip_intro request")
                    track_cfg = get_track_config(getattr(interview_state, 'track_type', 'intro'))
                    first_real_stage = track_cfg.first_real_stage
                    stage_order = track_cfg.full_stage_sequence
                    current_idx = stage_order.index(interview_state.stage) if interview_state.stage in stage_order else 0
                    target_idx = stage_order.index(first_real_stage) if first_real_stage in stage_order else 0
                    if target_idx > current_idx:
                        asyncio.create_task(
                            execute_skip_transition(
                                session=session,
                                interview_state=interview_state,
                                target_stage=first_real_stage,
                                agent=agent,
                                room=room
                            )
                        )
                    else:
                        logger.warning(f"[SKIP] Cannot skip intro - already past greeting stages")
                    return

                if payload.get('type') == 'code_submitted':
                    code = payload.get('code', '')
                    language = payload.get('language', 'python')
                    problem_idx = payload.get('problem_index', 0)
                    logger.info(f"[CODE] Received code submission for problem {problem_idx}, language: {language}")

                    # Check max retries
                    attempts_done = interview_state.get_attempts_for_problem(problem_idx) if hasattr(interview_state, 'get_attempts_for_problem') else 0
                    if attempts_done >= 3:
                        logger.warning(f"[CODE] Max attempts reached for problem {problem_idx}")
                        try:
                            import json
                            asyncio.create_task(
                                room.local_participant.publish_data(
                                    json.dumps({'type': 'max_attempts_reached', 'problem_index': problem_idx}).encode('utf-8')
                                )
                            )
                        except Exception:
                            pass
                        return

                    # Trigger evaluation
                    asyncio.create_task(
                        _evaluate_code_async(session, agent, interview_state, room, problem_idx, code, language)
                    )
                    return

                if payload.get('type') == 'skip_coding_problem':
                    logger.info("[CODE] skip_coding_problem received")
                    track_type = getattr(interview_state, 'track', 'intro')
                    if track_type == 'coding':
                        asyncio.create_task(_async_skip_coding_problem(interview_state, room, session))
                    return

                if payload.get('type') == 'skip_stage':
                    target_stage_name = payload.get('target_stage')
                    logger.info(f"[SKIP] Received skip request to: {target_stage_name}")
                    
                    target_stage = interview_state.get_stage_by_name(target_stage_name)
                    
                    if not target_stage:
                        logger.warning(f"[SKIP] Invalid stage name: {target_stage_name}")
                        return
                    
                    if not interview_state.can_skip_to(target_stage):
                        logger.warning(f"[SKIP] Cannot skip to {target_stage_name} from {interview_state.stage.value}")
                        return
                    
                    logger.info(f"[SKIP] Initiating forced skip to {target_stage.value}")
                    asyncio.create_task(
                        execute_skip_transition(
                            session=session,
                            interview_state=interview_state,
                            target_stage=target_stage,
                            agent=agent,
                            room=room
                        )
                    )
                    return

                if payload.get('type') == 'ready_for_problem':
                    track_type = getattr(interview_state, 'track', 'intro')
                    if track_type == 'coding':
                        logger.info("[CODING] ready_for_problem received — scheduling async problem push")
                        asyncio.create_task(_async_handle_ready_for_problem(interview_state, room))
            except Exception as e:
                logger.error(f"[DATA] Error processing data: {e}", exc_info=True)
        
        async def finalize_and_disconnect():
            """Save interview to database and disconnect"""
            try:
                import json as json_module
                from datetime import datetime
                
                if not user_id:
                    logger.error("[FINALIZE] No user_id found")
                    await room.disconnect()
                    return
                
                logger.info(f"[FINALIZE] Saving interview to database for user: {user_id}")
                
                now = datetime.now()
                interview_data = {
                    'candidate_name': interview_state.candidate_name,
                    'interview_date': now.isoformat(),
                    'room_name': room.name,
                    'job_role': interview_state.job_role,
                    'experience_level': interview_state.experience_level,
                    'conversation': conversation_history,
                    'total_messages': {
                        'agent': len(conversation_history.get('agent', [])),
                        'user': len(conversation_history.get('user', []))
                    },
                    'skipped_stages': interview_state.skipped_stages,
                    'final_stage': interview_state.stage.value,
                    'ended_by': 'natural_completion',
                    'has_resume': bool(interview_state.uploaded_resume_text),
                    'has_jd': bool(interview_state.job_description),
                    'track': getattr(interview_state, 'track', 'intro'),
                    'track_config': {
                        'framework': getattr(interview_state, 'framework', ''),
                        'depth': getattr(interview_state, 'depth_setting', ''),
                        'topics': getattr(interview_state, 'selected_topics', []),
                        'generated_questions': getattr(interview_state, 'generated_questions', []),
                        'generated_problems': getattr(interview_state, 'generated_problems', []),
                        'preferred_language': getattr(interview_state, 'preferred_language', ''),
                        'submissions': getattr(interview_state, 'submissions', []),
                    }
                }

                from supabase_client import supabase_client
                interview_id = supabase_client.save_interview(user_id, interview_data)

                if interview_id:
                    interview_state._interview_id = interview_id
                    interview_state._user_id = user_id
                    logger.info(f"[FINALIZE] Interview saved successfully: {interview_id}")
                    
                    data_payload = json_module.dumps({
                        "type": "interview_saved",
                        "interview_id": interview_id,
                        "message": "Interview saved successfully"
                    })
                    await room.local_participant.publish_data(data_payload.encode('utf-8'))
                    
                    data_payload = json_module.dumps({
                        "type": "interview_ending",
                        "message": "Interview Complete"
                    })
                    await room.local_participant.publish_data(data_payload.encode('utf-8'))
                else:
                    logger.error("[FINALIZE] Database save failed")
                    data_payload = json_module.dumps({
                        "type": "save_error",
                        "message": "Failed to save interview. Please contact support."
                    })
                    await room.local_participant.publish_data(data_payload.encode('utf-8'))
                
                closing_finalized["done"] = True
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
        
        @room.on("disconnected")
        def on_room_disconnected():
            logger.info("[ROOM] Room disconnected")
            asyncio.create_task(save_transcript_on_disconnect())
            interview_complete.set()
        
        async def save_transcript_on_disconnect():
            """Save interview transcript when room disconnects"""
            try:
                if closing_finalized.get("done"):
                    logger.info("[HISTORY] Transcript already saved via finalize_and_disconnect")
                    return
                
                if not conversation_history["agent"] and not conversation_history["user"]:
                    logger.info("[HISTORY] No conversation to save")
                    return
                
                if not user_id:
                    logger.error("[HISTORY] No user_id found")
                    return
                
                import json as json_module
                from datetime import datetime
                
                now = datetime.now()
                interview_data = {
                    'candidate_name': candidate_name,
                    'interview_date': now.isoformat(),
                    'room_name': room.name,
                    'job_role': interview_state.job_role,
                    'experience_level': interview_state.experience_level,
                    'conversation': conversation_history,
                    'total_messages': {
                        'agent': len(conversation_history['agent']),
                        'user': len(conversation_history['user'])
                    },
                    'skipped_stages': interview_state.skipped_stages,
                    'final_stage': interview_state.stage.value,
                    'ended_by': 'user_disconnect',
                    'has_resume': bool(interview_state.uploaded_resume_text),
                    'has_jd': bool(interview_state.job_description),
                    'track': getattr(interview_state, 'track', 'intro'),
                    'track_config': {
                        'framework': getattr(interview_state, 'framework', ''),
                        'depth': getattr(interview_state, 'depth_setting', ''),
                        'topics': getattr(interview_state, 'selected_topics', []),
                        'generated_questions': getattr(interview_state, 'generated_questions', []),
                        'generated_problems': getattr(interview_state, 'generated_problems', []),
                        'preferred_language': getattr(interview_state, 'preferred_language', ''),
                        'submissions': getattr(interview_state, 'submissions', []),
                    }
                }

                from supabase_client import supabase_client
                interview_id = supabase_client.save_interview(user_id, interview_data)

                if interview_id:
                    interview_state._interview_id = interview_id
                    interview_state._user_id = user_id
                    logger.info(f"[HISTORY] Saved transcript on disconnect: {interview_id}")
                    try:
                        data_payload = json_module.dumps({
                            "type": "interview_saved",
                            "interview_id": interview_id
                        })
                        await room.local_participant.publish_data(data_payload.encode('utf-8'))
                    except Exception as e:
                        logger.warning(f"[HISTORY] Failed to emit interview_id: {e}")
                else:
                    logger.error("[HISTORY] Database save failed on disconnect")
                    
            except Exception as e:
                logger.error(f"[HISTORY] Error saving on disconnect: {e}", exc_info=True)
        
        # Start fallback timer
        fallback_task = asyncio.create_task(
            stage_fallback_timer(session, interview_state, room, agent, interview_complete, track_config)
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


async def stage_fallback_timer(
    session: AgentSession,
    state: InterviewState,
    room: Room,
    agent: InterviewAgent,
    interview_complete: asyncio.Event,
    track_config=None
):
    """Timer that monitors stage progress and forces transitions when limits exceeded."""
    # Build monitored stages from track config (exclude greeting and closing)
    if track_config:
        MONITORED_STAGES = set(
            s for s in track_config.full_stage_sequence
            if s.value not in ('greeting', 'welcome', 'closing')
        )
        time_limits = track_config.time_limits
    else:
        MONITORED_STAGES = {
            InterviewStage.SELF_INTRO,
            InterviewStage.PAST_EXPERIENCE,
            InterviewStage.COMPANY_FIT
        }
        time_limits = STAGE_TIME_LIMITS

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

            if getattr(current_stage, 'value', '') == 'closing':
                elapsed = state.time_in_current_stage()
                if not closing_timeout_logged:
                    logger.info(f"[TIMER] Closing stage - timeout: {CLOSING_TIMEOUT}s")
                    closing_timeout_logged = True
                
                if elapsed > CLOSING_TIMEOUT and not state.closing_message_delivered:
                    logger.warning("[FALLBACK] Closing timeout - forcing finalization")
                    try:
                        closing_msg = CLOSING_FALLBACK.message.replace("[CANDIDATE_NAME]", agent.candidate_name)
                        await session.say(closing_msg, allow_interruptions=False)
                        await asyncio.sleep(3.0)
                    except Exception as e:
                        logger.warning(f"[FALLBACK] Closing say failed: {e}")
                    interview_complete.set()
                    try:
                        await room.disconnect()
                    except Exception:
                        pass
                    break
                continue
            
            if current_stage not in MONITORED_STAGES:
                if current_stage != last_logged_stage:
                    last_logged_stage = current_stage
                    logged_milestones = set()
                continue

            # Get time limit from track config for current stage
            current_time_limit = time_limits.get(current_stage, 600) if time_limits else state.get_stage_time_limit()
            elapsed = state.time_in_current_stage()
            elapsed_pct = min(100.0, (elapsed / current_time_limit) * 100) if current_time_limit > 0 else 0

            if current_stage != last_logged_stage:
                logger.info(f"[TIMER] Stage '{current_stage.value}' - Limit: {current_time_limit}s")
                logged_milestones = set()
                last_logged_stage = current_stage

            for pct in [50, 75, 90, 100]:
                if elapsed_pct >= pct and pct not in logged_milestones:
                    logger.info(f"[TIMER] {current_stage.value} at {pct}% ({elapsed:.0f}/{current_time_limit}s)")
                    logged_milestones.add(pct)

            if elapsed > current_time_limit:
                # Get next stage - track-aware
                track_type = getattr(state, 'track_type', 'intro')
                if track_type == 'behavioral' and hasattr(state, 'get_next_behavioral_stage'):
                    next_stage = state.get_next_behavioral_stage()
                elif track_type == 'technical_voice' and hasattr(state, 'get_next_technical_voice_stage'):
                    next_stage = state.get_next_technical_voice_stage()
                else:
                    next_stage = state.get_next_stage()
                if next_stage:
                    logger.warning(f"[FALLBACK] FORCING: {current_stage.value} -> {next_stage.value}")
                    
                    state.transition_to(next_stage, forced=True)
                    
                    try:
                        instructions = agent._get_stage_instructions(state, next_stage)
                        await agent.update_instructions(instructions)
                    except Exception as e:
                        logger.error(f"[FALLBACK] Instruction update error: {e}")
                    
                    try:
                        import json
                        await room.local_participant.publish_data(
                            json.dumps({"type": "stage_change", "stage": next_stage.value}).encode('utf-8')
                        )
                    except Exception as e:
                        logger.error(f"[UI] Stage change emit error: {e}")
                    
                    ack = get_fallback_ack(next_stage, agent.candidate_name)
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
    logger.info("[WORKER] Starting agent worker - DIRECT ROOM CONNECTION MODE")
    asyncio.run(run_interview())