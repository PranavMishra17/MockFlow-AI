"""
Interview runtime — the interview, with no transport attached.

`agent_worker.py` used to fuse six concerns into one ~630-line function: room
lifecycle, config parsing, state construction, plugin construction, event
wiring, command dispatch and finalize. Nothing in it could be imported without a
full LiveKit environment, so nothing in it could be tested without one either.

This module holds everything that is *not* about being in a room. The rules that
keep it that way:

- No module-level environment reads and no `sys.exit`. Importing this module
  with an empty environment must succeed; that is what makes a text harness
  possible.
- Nothing here touches `room` directly. Every outbound message goes through a
  `Transport`, of which `RoomTransport` is the production one and
  `NullTransport` is the one a test asserts against.
- Wall-clock reads go through `InterviewState._now`, so a harness can advance
  time instead of sleeping through a ten-minute stage.

`agent_worker.py` keeps what genuinely is about the room: env validation, token
minting, connecting, waiting for the participant, and the database finalize.

Behavior is meant to be unchanged by the extraction itself. The two places it is
knowingly *not* identical are called out at their definitions: `attach_handlers`
(user turns are now also recorded for typed input) and `handle_command` (the
if/elif chain became a registry).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Awaitable, Callable, Mapping, Optional, Protocol

from pydantic import Field

from livekit.agents import (
    NOT_GIVEN,
    AgentSession,
    Agent,
    RunContext,
    function_tool,
)

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

logger = logging.getLogger("interview-runtime")


def _openai_api_key() -> Optional[str]:
    """Read the OpenAI key at call time, not import time.

    The tools that build their own OpenAI client used to close over a module
    global captured during import, which is exactly what made this file
    un-importable without a populated environment.
    """
    return os.getenv('OPENAI_API_KEY')


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

class Transport(Protocol):
    """Where agent -> client messages go.

    One method, because that is genuinely all the interview needs: it never
    reads from the room, only publishes to it. Inbound commands arrive through
    `handle_command`, which the caller feeds.
    """

    async def emit(self, payload: Mapping[str, Any], *, reliable: bool = True) -> None:
        ...


class RoomTransport:
    """Production transport: publish JSON on the LiveKit data channel.

    `reliable` defaults to True because that is `publish_data`'s own default,
    which is what every call site got before this indirection existed.
    """

    def __init__(self, room):
        self.room = room

    async def emit(self, payload: Mapping[str, Any], *, reliable: bool = True) -> None:
        import json
        if not (self.room and self.room.local_participant):
            logger.warning("[TRANSPORT] No room participant; dropped %s", payload.get('type'))
            return
        await self.room.local_participant.publish_data(
            json.dumps(payload).encode('utf-8'), reliable=reliable
        )


class NullTransport:
    """Test transport: keep the payloads so a test can assert on them.

    Holds decoded dicts rather than bytes — an assertion should read
    `events[0]["stage"]`, not re-parse JSON the runtime just serialised.
    """

    def __init__(self):
        self.events: list[dict] = []

    async def emit(self, payload: Mapping[str, Any], *, reliable: bool = True) -> None:
        self.events.append(dict(payload))

    def of_type(self, type_name: str) -> list[dict]:
        """Every emitted payload with this `type`, in order."""
        return [e for e in self.events if e.get('type') == type_name]


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------

class InterviewAgent(Agent):
    """Mock interview agent with FSM-based stage management."""

    def __init__(self, transport=None, candidate_info=None, track_type='intro'):
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
        self.transport = transport if transport is not None else NullTransport()

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
                    ctx.userdata.problem_start_times[str(p_num)] = ctx.userdata._now().isoformat()
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
        """Emit stage change event to the UI."""
        try:
            await self.transport.emit({
                "type": "stage_change",
                "stage": new_stage.value,
            })
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

            client = OpenAI(api_key=_openai_api_key())
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
                # Use the VETTED problem bank instead of LLM-invented problems.
                # Curated problems ship test cases + reference solutions and are
                # proven solvable (no unsolvable/ambiguous generations).
                from coding import select_problems, difficulty_for_level
                problem_count = getattr(ctx.userdata, 'active_problem_count', 2)
                level = ctx.userdata.experience_level or 'mid'
                difficulty = difficulty_for_level(level)

                problems = select_problems(level=level, count=problem_count)
                ctx.userdata.generated_problems = problems
                ctx.userdata.active_problem_count = max(1, min(len(problems), 2))
                logger.info(f"[AGENT] Selected {len(problems)} vetted coding problems (difficulty: {difficulty})")
                return f"Selected {len(problems)} vetted coding problems. Active problem count: {ctx.userdata.active_problem_count}. Now transition_stage when ready to begin."

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
                    asyncio.create_task(self.transport.emit({
                        'type': 'coding_problem',
                        'problem': problem,
                        'problem_index': idx,
                        'attempt_number': attempts_done + 1,
                        'max_attempts': max_attempts,
                        'time_limit_minutes': problem.get('time_limit_minutes', 15),
                    }))
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

            client = OpenAI(api_key=_openai_api_key())

            user_prompt = CODE_EVALUATOR.user_template.format(
                problem_title=problem.get('title', 'Coding Problem'),
                problem_description=problem.get('description', ''),
                problem_examples=str(problem.get('examples', [])),
                problem_constraints=', '.join(problem.get('constraints', [])),
                language=language,
                code=code,
            )

            # Ground the evaluation in OBJECTIVE test results when the problem
            # ships test cases and hosted execution (Piston) is enabled. The LLM
            # then judges approach/quality on top of real pass/fail.
            objective_summary = None
            try:
                from coding.piston_runner import PISTON_ENABLED, run_via_piston
                test_cases = problem.get('test_cases')
                entrypoint = problem.get('entrypoint')
                if PISTON_ENABLED and test_cases and entrypoint and language.lower().startswith('py'):
                    run = run_via_piston(code, entrypoint, test_cases, language='python')
                    if run.get('error') is None:
                        objective_summary = f"{run['passed']}/{run['total']} hidden test cases passed"
                        user_prompt += (
                            f"\n\nOBJECTIVE TEST RESULTS (ground truth — weight correctness on this): "
                            f"{objective_summary}."
                        )
                    else:
                        logger.info(f"[CODE] Piston run skipped/failed: {run.get('error')}")
            except Exception as exec_err:
                logger.warning(f"[CODE] Objective execution error (continuing with LLM-only): {exec_err}")

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

            # Emit evaluation result to frontend. max_attempts is bound before
            # the try because the code after this block reads it; inside the
            # try it was one raised import away from being unbound.
            max_attempts = 3
            try:
                await self.transport.emit({
                    'type': 'evaluation_result',
                    'evaluation': evaluation,
                    'attempt': attempt_num,
                    'max_attempts': max_attempts,
                    'problem_index': problem_index,
                    'objective_tests': objective_summary,
                })
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
            if objective_summary:
                verbal_feedback = f"{verbal_feedback} ({objective_summary})"
            logger.info(f"[AGENT] Code evaluated: correctness={evaluation.get('correctness')}, approach={evaluation.get('approach_quality')}, tests={objective_summary}")

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


# ---------------------------------------------------------------------------
# Out-of-band actions (skips, coding pushes, code evaluation)
# ---------------------------------------------------------------------------

async def emit_user_caption(transport: "Transport", text: str):
    """Emit user caption to the UI."""
    try:
        await transport.emit({"type": "user_caption", "text": text})
    except Exception as e:
        logger.error(f"[UI] Failed to emit user caption: {e}")


async def _async_skip_coding_problem(interview_state, transport, session):
    """Handle skip_coding_problem: advance to next problem or closing."""
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
            attempts_done = (
                interview_state.get_attempts_for_problem(next_idx)
                if hasattr(interview_state, 'get_attempts_for_problem') else 0
            )
            await transport.emit({
                'type': 'coding_problem',
                'problem': problem,
                'problem_index': next_idx,
                'attempt_number': attempts_done + 1,
                'max_attempts': 3,
                'time_limit_minutes': problem.get('time_limit_minutes', 15),
            }, reliable=True)
            logger.info(f"[CODE] Skipped to problem {next_idx}: {problem.get('title', '?')}")
        else:
            # Move to closing
            interview_state.stage = CodingStage.CLOSING
            interview_state.coding_stage_active = False
            await transport.emit({'type': 'stage_update', 'stage': 'closing'}, reliable=True)
            if session:
                try:
                    await session.say("Great work on the coding problems. Let's wrap up.", allow_interruptions=True)
                except Exception:
                    pass
            logger.info("[CODE] All problems done, moved to closing")
    except Exception as e:
        logger.error(f"[CODE] _async_skip_coding_problem failed: {e}", exc_info=True)


async def _async_handle_ready_for_problem(interview_state, transport):
    """Handle ready_for_problem signal: generate problems if needed, then push to frontend."""
    import json as _json
    try:
        # Generate problems on-demand if not yet generated
        if not getattr(interview_state, 'generated_problems', None):
            logger.info("[CODING] Generating problems on-demand for ready_for_problem")
            try:
                import openai as _openai
                from prompts import QUESTION_GENERATION
                _client = _openai.AsyncOpenAI(api_key=_openai_api_key())
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
            await transport.emit({
                'type': 'coding_problem',
                'problem': problem,
                'problem_index': 0,
                'attempt_number': 1,
                'max_attempts': 3,
                'time_limit_minutes': problem.get('time_limit_minutes', 15),
            }, reliable=True)
            logger.info(f"[CODING] Pushed problem to frontend: {problem.get('title', '?')}")
        else:
            logger.warning("[CODING] No problems to push after generation attempt")
    except Exception as e:
        logger.error(f"[CODING] _async_handle_ready_for_problem failed: {e}", exc_info=True)


async def emit_agent_caption(transport: "Transport", text: str):
    """Emit agent caption to the UI."""
    try:
        await transport.emit({"type": "agent_caption", "text": text})
    except Exception as e:
        logger.error(f"[UI] Failed to emit agent caption: {e}")


async def execute_skip_transition(
    session: AgentSession,
    interview_state: InterviewState,
    target_stage: InterviewStage,
    agent: InterviewAgent,
    transport: "Transport"
):
    """Execute a skip transition directly without relying on LLM tool calls."""
    try:
        current_stage = interview_state.stage
        logger.info(f"[SKIP] Executing forced skip: {current_stage.value} -> {target_stage.value}")

        interview_state.transition_to(target_stage, forced=False, skipped=True)

        stage_instructions = agent._get_stage_instructions(interview_state, target_stage)
        await agent.update_instructions(stage_instructions)

        try:
            await transport.emit({
                "type": "stage_change",
                "stage": target_stage.value,
            })
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
    transport: "Transport",
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

        client = _openai.AsyncOpenAI(api_key=_openai_api_key())
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

        # Record submission in state. This goes through record_submission rather
        # than incrementing the counter here: this path used to write int keys
        # while record_submission and get_attempts_for_problem used string keys,
        # so the two submit paths kept independent counts and the max-attempts
        # guard never saw the ones made from the editor.
        attempt_num = 1
        if hasattr(state, 'record_submission'):
            attempt_num = state.record_submission(problem_index, code, language, evaluation)

        # Push evaluation result to frontend
        await transport.emit({
            'type': 'evaluation_result',
            'evaluation': evaluation,
            'attempt': attempt_num,
            'max_attempts': 3,
            'problem_index': problem_index,
        }, reliable=True)
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


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_interview_state(
    config: Mapping[str, Any],
    *,
    candidate_name: str = "Candidate",
    now: Optional[Callable[[], datetime]] = None,
) -> InterviewState:
    """Construct the per-track state from a normalized config.

    `config` must already have been through `agent_mode.normalize_config`, which
    is now the single parser for both transports. Everything this function reads
    is a key in `agent_mode.CONFIG_FIELDS`; it never touches participant
    attributes or job metadata itself.

    `now` is the clock the state will use for every stage timing decision. A
    harness passes a controllable one; production leaves it None and gets
    `datetime.now`.
    """
    track_type = config.get('track', 'intro')

    if track_type == 'behavioral':
        state: InterviewState = BehavioralInterviewState()
        state.framework = config.get('framework', 'amazon')
        state.depth_setting = config.get('depth', 'medium')
        state.custom_questions = list(config.get('custom_questions') or [])
    elif track_type == 'technical_voice':
        state = TechnicalVoiceInterviewState()
        all_topics = list(config.get('topics') or []) + list(config.get('custom_topics') or [])
        state.selected_topics = all_topics[:3]  # Max 3 topics
        state.active_topic_count = len(state.selected_topics)
    elif track_type == 'coding':
        state = CodingInterviewState()
        state.preferred_language = config.get('preferred_language', 'python')
        # problem_count arrives as a string over participant attributes and as an
        # int over job metadata; both reach the same clamp.
        try:
            problem_count = int(config.get('problem_count', 2))
        except (TypeError, ValueError):
            problem_count = 2
        state.active_problem_count = min(max(problem_count, 1), 2)
    else:
        state = InterviewState()

    if now is not None:
        state._now = now

    state.candidate_name = candidate_name
    state.candidate_email = config.get('email', '')
    state.job_role = config.get('role', 'this position')
    state.experience_level = config.get('level', 'mid')
    state.uploaded_resume_text = config.get('resume_text')
    state.job_description = config.get('job_description')
    state.include_profile = config.get('include_profile', True)
    state.track = track_type

    if track_type == 'behavioral':
        state.transition_to(BehavioralStage.GREETING)
    elif track_type == 'technical_voice':
        state.transition_to(TechnicalVoiceStage.GREETING)
    elif track_type == 'coding':
        state.transition_to(CodingStage.GREETING)
    else:
        state.transition_to(InterviewStage.WELCOME)

    logger.info(f"[RUNTIME] Interview state initialized: track={track_type}, stage={state.stage.value}")
    return state


def build_session(
    state: InterviewState,
    *,
    llm,
    stt=None,
    tts=None,
    vad=None,
    turn_detection=NOT_GIVEN,
) -> AgentSession:
    """Build the AgentSession around an already-constructed state.

    Every voice component is optional and injected. A text harness passes an llm
    and nothing else; production passes all four. `turn_detection` is threaded
    through — untouched here, but it is the one knob push-to-talk needs, and
    leaving it out would force that work to reopen this signature.

    The endpointing delays are the values tuned for constrained CPU; they are
    inert when no VAD is attached.

    Note: the agent is deliberately NOT a parameter. AgentSession does not take
    one — the agent is bound in `session.start(agent=...)` — and accepting one
    here only to ignore it would imply a coupling that does not exist.
    """
    session = AgentSession(
        userdata=state,
        stt=stt,
        llm=llm,
        tts=tts,
        vad=vad,
        allow_interruptions=True,
        min_endpointing_delay=0.8,   # more tolerance for pauses
        max_endpointing_delay=4.0,   # wait longer before cutting off
        turn_detection=turn_detection,
    )
    logger.info("[RUNTIME] AgentSession created")
    return session


@dataclass
class RuntimeHandles:
    """The mutable containers `attach_handlers` wires up, for the caller to read.

    `conversation` is the transcript that becomes the saved interview.
    `closing_finalized` guards against finalizing twice.
    `speech_window` is the in-flight speaking measurement.
    """

    conversation: dict = field(default_factory=lambda: {"agent": [], "user": []})
    closing_finalized: dict = field(default_factory=lambda: {"done": False})
    speech_window: dict = field(default_factory=lambda: {"started": None, "pending": None})


def attach_handlers(
    session: AgentSession,
    state: InterviewState,
    transport: "Transport",
    *,
    on_closing: Optional[Callable[[], Awaitable[None]]] = None,
) -> RuntimeHandles:
    """Wire transcript, caption and speaking-window capture onto a session.

    ## Why user turns are recorded twice-sourced

    Turns used to be recorded only from `user_input_transcribed`, which is an STT
    event. A typed answer never produces one, so with text input the answer would
    reach the model and never reach the transcript — or the verdict.

    The obvious fix is to record from `conversation_item_added(role="user")`
    instead, since both voice and typed turns pass through it. That single
    source is rejected for a different reason than it might appear. The gate in
    `_pipeline_reply_task_impl` is
    `if new_message is not None and speech_handle.scheduled`
    (livekit-agents 1.3.6, `voice/agent_activity.py`), and `scheduled` is
    already true by then — `_schedule_speech` calls `_mark_scheduled()`
    synchronously before the task body can run, and `interrupt()` does not clear
    it. So interrupted turns are NOT at risk, and anyone reading this to justify
    a rewrite should know that.

    The reason to keep the STT path authoritative is narrower and more useful:
    it is the only source that carries `duration_s`. A turn recorded from the
    chat item alone has no measured speaking window, and delivery metrics would
    silently degrade to "not measured" for voice sessions.

    So both events are used, and the STT path stays authoritative for voice:

    - `user_input_transcribed` (final) records the turn, exactly as before,
      with its measured `duration_s`.
    - `conversation_item_added(role="user")` records a turn ONLY when no STT
      final has arrived since the last one. An empty buffer means nothing was
      spoken, which means the text came from somewhere else — i.e. it was typed.

    Buffer-emptiness is the discriminator rather than comparing text, because a
    single turn can arrive as several STT finals and reach the chat context as
    one concatenated message; text comparison would double-record it.

    **Known limit, and a hard requirement on whoever adds text input.**
    Buffer-emptiness is an inference, not a fact. It holds today because nothing
    types: with no text path, an empty buffer can only mean "no speech". Once a
    `user_text` command exists, a stray STT final — a cough on a live mic — will
    make the buffer non-empty and the typed turn will be DISCARDED here, which
    is the very failure this function exists to prevent, reintroduced silently.

    So text input must do both of these, not either:
      1. `session.input.set_audio_enabled(False)` when entering text mode, so no
         final can arrive; and
      2. set an explicit "the next user item is typed" flag that this handler
         prefers over buffer-emptiness. A flag set by the handler that injected
         the text is fact; an empty buffer is a guess.

    Two library paths also emit a user item with no STT final behind it
    (`agent_activity.py`, the `_closing` branches), so without that flag a voice
    turn can be recorded as typed — and once `mode` is tagged, mislabelled in
    the one field that decides whether delivery is reported at all.
    """
    handles = RuntimeHandles()
    conversation_history = handles.conversation
    closing_finalized = handles.closing_finalized
    speech_window = handles.speech_window

    # Finals seen since the last user chat item. See the docstring: non-empty
    # means the pending chat item is the voice turn we already recorded.
    stt_finals_pending: list[str] = []

    @session.on("user_state_changed")
    def on_user_state(event):
        """Track how long the candidate actually spoke. Never fatal."""
        import time
        try:
            old = getattr(event.old_state, "value", event.old_state)
            new = getattr(event.new_state, "value", event.new_state)
            if new == "speaking":
                speech_window["started"] = time.time()
            elif old == "speaking" and speech_window["started"] is not None:
                elapsed = time.time() - speech_window["started"]
                speech_window["started"] = None
                # Ignore implausible windows rather than record a bad number.
                if 0.2 <= elapsed <= 600:
                    speech_window["pending"] = round(elapsed, 2)
        except Exception as e:
            logger.warning(f"[ANALYTICS] Speaking-window capture failed (non-fatal): {e}")

    @session.on("user_input_transcribed")
    def on_user_speech(event):
        import time
        transcript = event.transcript.strip()
        if not transcript:
            return
        # Live caption: stream interim transcripts as the candidate speaks,
        # not just the final one — so the caption updates in real time.
        asyncio.create_task(emit_user_caption(transport, transcript))
        if event.is_final:
            logger.info(f"[USER] {transcript}")
            # Attach the just-finished speaking window if we have one. If the
            # final transcript lands before the state flips, fall back to the
            # window still in progress. None means "not measured" downstream,
            # which is honest — it is never substituted with an estimate.
            duration_s = speech_window["pending"]
            if duration_s is None and speech_window["started"] is not None:
                elapsed = time.time() - speech_window["started"]
                if 0.2 <= elapsed <= 600:
                    duration_s = round(elapsed, 2)
            speech_window["pending"] = None

            stt_finals_pending.append(transcript)
            conversation_history["user"].append({
                "index": len(conversation_history["user"]),
                "text": transcript,
                "timestamp": time.time(),
                # Measured speaking seconds for this turn, or None. Consumed
                # by speech_analytics._measure_pace.
                "duration_s": duration_s,
                # Tag with the stage the candidate was answering in, so the
                # evaluator can attribute evidence per stage (Wing D).
                "stage": state.stage.value,
            })

    @session.on("conversation_item_added")
    def on_conversation_item(event):
        try:
            import time
            message = event.item
            role = getattr(message, 'role', None)

            if role == "user":
                # See the docstring: a user item with no STT final behind it is
                # text input, and is the only case that needs recording here.
                if stt_finals_pending:
                    stt_finals_pending.clear()
                    return
                typed_text = message.text_content if hasattr(message, 'text_content') else None
                if not typed_text or not typed_text.strip():
                    return
                logger.info(f"[USER:text] {typed_text[:150]}")
                conversation_history["user"].append({
                    "index": len(conversation_history["user"]),
                    "text": typed_text.strip(),
                    "timestamp": time.time(),
                    # Nothing was spoken, so there is no speaking duration.
                    # None reads as "not measured" downstream, which is the
                    # honest answer; a 0 would be a fabricated measurement.
                    "duration_s": None,
                    "stage": state.stage.value,
                })
                return

            if role == "assistant":
                agent_text = message.text_content if hasattr(message, 'text_content') else None
                if agent_text:
                    logger.info(f"[AGENT] {agent_text[:150]}...")
                    conversation_history["agent"].append({
                        "index": len(conversation_history["agent"]),
                        "text": agent_text,
                        "timestamp": time.time(),
                        "stage": state.stage.value
                    })
                    asyncio.create_task(emit_agent_caption(transport, agent_text))

                    if getattr(state.stage, 'value', '') == 'closing' and not closing_finalized["done"]:
                        text_lower = agent_text.lower()
                        closing_indicators = [
                            "thank you" in text_lower and "luck" in text_lower,
                            "good luck" in text_lower,
                            "best of luck" in text_lower,
                        ]
                        if any(closing_indicators) and len(agent_text) > 50:
                            state.closing_message_delivered = True
                            if on_closing is not None:
                                async def schedule_finalization():
                                    if closing_finalized["done"]:
                                        return
                                    closing_finalized["done"] = True
                                    await asyncio.sleep(5.0)
                                    await on_closing()
                                asyncio.create_task(schedule_finalization())
        except Exception as e:
            logger.error(f"[CONVERSATION] Error: {e}", exc_info=True)

    return handles


# ---------------------------------------------------------------------------
# Command dispatch
# ---------------------------------------------------------------------------

@dataclass
class CommandContext:
    """Everything a client->agent command may need, and nothing about the room."""

    session: AgentSession
    state: InterviewState
    agent: "InterviewAgent"
    transport: "Transport"
    track_config: Any = None


async def _cmd_skip_intro(payload: Mapping[str, Any], ctx: CommandContext) -> None:
    logger.info("[SKIP] Received skip_intro request")
    track_cfg = get_track_config(getattr(ctx.state, 'track_type', 'intro'))
    first_real_stage = track_cfg.first_real_stage
    stage_order = track_cfg.full_stage_sequence
    current_idx = stage_order.index(ctx.state.stage) if ctx.state.stage in stage_order else 0
    target_idx = stage_order.index(first_real_stage) if first_real_stage in stage_order else 0
    if target_idx > current_idx:
        await execute_skip_transition(
            session=ctx.session,
            interview_state=ctx.state,
            target_stage=first_real_stage,
            agent=ctx.agent,
            transport=ctx.transport,
        )
    else:
        logger.warning("[SKIP] Cannot skip intro - already past greeting stages")


async def _cmd_code_submitted(payload: Mapping[str, Any], ctx: CommandContext) -> None:
    code = payload.get('code', '')
    language = payload.get('language', 'python')
    problem_idx = payload.get('problem_index', 0)
    logger.info(f"[CODE] Received code submission for problem {problem_idx}, language: {language}")

    attempts_done = (
        ctx.state.get_attempts_for_problem(problem_idx)
        if hasattr(ctx.state, 'get_attempts_for_problem') else 0
    )
    if attempts_done >= 3:
        logger.warning(f"[CODE] Max attempts reached for problem {problem_idx}")
        try:
            await ctx.transport.emit({'type': 'max_attempts_reached', 'problem_index': problem_idx})
        except Exception:
            pass
        return

    await _evaluate_code_async(
        ctx.session, ctx.agent, ctx.state, ctx.transport, problem_idx, code, language
    )


async def _cmd_skip_coding_problem(payload: Mapping[str, Any], ctx: CommandContext) -> None:
    logger.info("[CODE] skip_coding_problem received")
    if getattr(ctx.state, 'track', 'intro') == 'coding':
        await _async_skip_coding_problem(ctx.state, ctx.transport, ctx.session)


async def _cmd_skip_stage(payload: Mapping[str, Any], ctx: CommandContext) -> None:
    target_stage_name = payload.get('target_stage')
    logger.info(f"[SKIP] Received skip request to: {target_stage_name}")

    target_stage = ctx.state.get_stage_by_name(target_stage_name)
    if not target_stage:
        logger.warning(f"[SKIP] Invalid stage name: {target_stage_name}")
        return

    if not ctx.state.can_skip_to(target_stage):
        logger.warning(f"[SKIP] Cannot skip to {target_stage_name} from {ctx.state.stage.value}")
        return

    logger.info(f"[SKIP] Initiating forced skip to {target_stage.value}")
    await execute_skip_transition(
        session=ctx.session,
        interview_state=ctx.state,
        target_stage=target_stage,
        agent=ctx.agent,
        transport=ctx.transport,
    )


async def _cmd_ready_for_problem(payload: Mapping[str, Any], ctx: CommandContext) -> None:
    if getattr(ctx.state, 'track', 'intro') == 'coding':
        logger.info("[CODING] ready_for_problem received — pushing problem")
        await _async_handle_ready_for_problem(ctx.state, ctx.transport)


#: Client -> agent commands. A registry rather than an if/elif chain so that
#: parallel work (skip-the-question, input modes) adds entries instead of
#: editing the same block and colliding on merge.
COMMANDS: dict[str, Callable[[Mapping[str, Any], CommandContext], Awaitable[None]]] = {
    'skip_intro': _cmd_skip_intro,
    'code_submitted': _cmd_code_submitted,
    'skip_coding_problem': _cmd_skip_coding_problem,
    'skip_stage': _cmd_skip_stage,
    'ready_for_problem': _cmd_ready_for_problem,
}


async def handle_command(payload: Mapping[str, Any], ctx: CommandContext) -> bool:
    """Dispatch one decoded client command. Returns whether it was handled.

    Every handler is a coroutine, where the old chain did part of its work
    synchronously inside the data-channel callback and part in a spawned task.
    Ordering is preserved: data packets arrive in order and each is dispatched as
    its own task, so handlers still start in arrival order.

    Errors are logged, never raised — a malformed command from the client must
    not take the interview down.
    """
    command_type = payload.get('type')
    handler = COMMANDS.get(command_type)
    if handler is None:
        return False
    try:
        await handler(payload, ctx)
    except Exception as e:
        logger.error(f"[COMMAND] {command_type} failed: {e}", exc_info=True)
    return True


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------

def collect_interview_data(
    state: InterviewState,
    conversation: Mapping[str, Any],
    *,
    room_name: str,
    ended_by: str,
    candidate_name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Build the row that gets saved for this interview.

    There were two copies of this dict — one in `finalize_and_disconnect`, one in
    `save_transcript_on_disconnect` — differing only in `ended_by` and in which
    variable they read the candidate name from. They had already drifted once;
    a field added to one and not the other is a silent data loss on whichever
    path the interview happens to end on.
    """
    stamp = now or state._now()
    agent_turns = conversation.get('agent', []) or []
    user_turns = conversation.get('user', []) or []
    return {
        'candidate_name': candidate_name if candidate_name is not None else state.candidate_name,
        'interview_date': stamp.isoformat(),
        'room_name': room_name,
        'job_role': state.job_role,
        'experience_level': state.experience_level,
        'conversation': conversation,
        'total_messages': {
            'agent': len(agent_turns),
            'user': len(user_turns),
        },
        'skipped_stages': state.skipped_stages,
        'final_stage': state.stage.value,
        'ended_by': ended_by,
        'has_resume': bool(state.uploaded_resume_text),
        'has_jd': bool(state.job_description),
        'track': getattr(state, 'track', 'intro'),
        'track_config': {
            'framework': getattr(state, 'framework', ''),
            'depth': getattr(state, 'depth_setting', ''),
            'topics': getattr(state, 'selected_topics', []),
            'generated_questions': getattr(state, 'generated_questions', []),
            'generated_problems': getattr(state, 'generated_problems', []),
            'preferred_language': getattr(state, 'preferred_language', ''),
            'submissions': getattr(state, 'submissions', []),
        },
    }


# ---------------------------------------------------------------------------
# Stage fallback timer
# ---------------------------------------------------------------------------

async def stage_fallback_timer(
    session: AgentSession,
    state: InterviewState,
    transport: "Transport",
    agent: InterviewAgent,
    interview_complete: asyncio.Event,
    track_config=None,
    on_timeout=None,
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
                    if on_timeout is not None:
                        try:
                            await on_timeout()
                        except Exception as e:
                            logger.warning(f"[FALLBACK] on_timeout hook failed: {e}")
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
                        await transport.emit({"type": "stage_change", "stage": next_stage.value})
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
