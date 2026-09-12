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
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol

from livekit.agents import (
    NOT_GIVEN,
    AgentSession,
    Agent,
    StopResponse,
)

from fsm import (InterviewState, InterviewStage, STAGE_TIME_LIMITS,
                  BehavioralStage, BehavioralInterviewState,
                  TechnicalVoiceStage, TechnicalVoiceInterviewState,
                  CodingStage, CodingInterviewState)
from tracks import get_track_config
from prompts import (
    build_stage_instructions,
    build_role_context,
    build_personality_note,
    get_greeting_line,
)
from interview_turn import (
    AssessFn,
    AssessInput,
    CLOSING_SENTINEL,
    MOVE_HEADER,
    Move,
    SAFE_NOTE,
    TurnAssessor,
    TurnInputs,
    _first_evidence,
    assess_turn_openai,
    bank_probes,
    build_closing_utterance,
    choose_move,
    first_move_for_stage,
    render_move_note,
    should_advance,
    stage_required_signals,
    star_applies,
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
# Stage pointers
# ---------------------------------------------------------------------------

def sync_stage_pointers(state: InterviewState, new_stage) -> None:
    """Point the per-track indices at the stage being entered.

    This used to live inline in `transition_stage` only, so any path that
    changed the stage WITHOUT going through that tool left the pointers behind.
    `execute_skip_transition` is such a path: skipping to `behavioral_q2` left
    `current_question_index` at 0 and the agent asked question 1 again, and
    skipping into a coding problem left `coding_stage_active` False with no
    start time recorded.

    Safe to call for any track and any stage; it only touches pointers that
    exist on the state it is given.
    """
    track_type = getattr(state, 'track_type', 'intro')
    stage_val = new_stage.value if hasattr(new_stage, 'value') else str(new_stage)

    if track_type == 'behavioral' and hasattr(state, 'current_question_index'):
        if stage_val.startswith('behavioral_q'):
            q_num = int(stage_val[-1]) - 1  # behavioral_q1 -> index 0
            state.current_question_index = q_num
            logger.info(f"[AGENT] Behavioral question index set to {q_num}")

    if track_type == 'coding' and hasattr(state, 'current_problem_index'):
        if stage_val.startswith('coding_problem_'):
            p_num = int(stage_val.split('_')[-1]) - 1  # coding_problem_1 -> 0
            state.current_problem_index = p_num
            state.coding_stage_active = True
            state.problem_start_times[str(p_num)] = state._now().isoformat()
            logger.info(f"[AGENT] Coding problem index set to {p_num}")
        elif stage_val in ('closing', 'warm_up', 'self_intro', 'greeting'):
            state.coding_stage_active = False


# ---------------------------------------------------------------------------
# The question bank
#
# Building the track's questions used to happen only if the model chose to call
# the `generate_interview_questions` tool — and no prompt on any track asks it
# to. The tool's own description was the entire instruction, which meant the
# behavioral track silently ran on improvised questions: no framework
# competencies, none of the candidate's custom questions, `generated_questions`
# left empty and `_get_stage_instructions` falling back to "Ask a relevant
# behavioral question". The differentiator of the track, absent with no error.
#
# So generation is a function the runtime calls, and the tool is a wrapper on
# it. The model may still call the tool; it is idempotent, so doing so is a
# no-op rather than a second bill.
# ---------------------------------------------------------------------------

#: Behavioral question count per depth setting. Previously the model chose this
#: by passing `count`, which is not a judgement it has any basis for.
_QUESTIONS_FOR_DEPTH = {'light': 2, 'medium': 3, 'deep': 3}


def _question_count_for_depth(depth: Optional[str]) -> int:
    return _QUESTIONS_FOR_DEPTH.get((depth or 'medium').lower(), 3)


async def _chat_json(prompt: str, *, max_tokens: int) -> dict:
    """One JSON-returning completion.

    Uses the ASYNC client. The tool this was extracted from used the blocking
    `OpenAI` client inside an async function, which stalls the event loop — and
    therefore the audio pipeline — for the whole generation.
    """
    import json as _json

    import openai as _openai

    client = _openai.AsyncOpenAI(api_key=_openai_api_key())
    response = await client.chat.completions.create(
        model='gpt-4o-mini',
        messages=[{'role': 'user', 'content': prompt}],
        temperature=0.7,
        max_tokens=max_tokens,
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[1].rsplit('```', 1)[0]
    return _json.loads(raw)


def _normalize_question(text: str) -> str:
    return ''.join(ch for ch in (text or '').lower() if ch.isalnum() or ch.isspace()).strip()


def _with_custom_questions(generated: list, custom: list) -> list:
    """Put the candidate's own questions in the bank, first and verbatim.

    The generation prompt asks the model to "include them as-is", and the model
    complies about half the time — otherwise it paraphrases them, or drops one.
    A question the candidate typed out is not a suggestion, so it is not left to
    the model: any custom question the generator did not reproduce is added
    here, and they lead the list so the three behavioral stages cannot fill up
    with generated questions before reaching them.
    """
    if not custom:
        return generated

    generated = list(generated or [])
    seen = {_normalize_question(q.get('main_question', '')) for q in generated}

    leading = []
    for question in custom:
        text = (question or '').strip()
        if not text:
            continue
        norm = _normalize_question(text)
        # Drop the model's version if it reproduced this one, so the candidate's
        # exact wording is the one that survives.
        generated = [
            q for q in generated
            if _normalize_question(q.get('main_question', '')) != norm
        ]
        if norm in seen:
            logger.info("[QUESTIONS] Custom question reproduced by the model; using the original")
        leading.append({
            'main_question': text,
            'competency': 'Candidate request',
            'follow_up_probes': [],
        })

    if leading:
        logger.info(f"[QUESTIONS] {len(leading)} custom question(s) placed at the front of the bank")
    return leading + generated


async def generate_questions_for(state: InterviewState, *, count: Optional[int] = None) -> str:
    """Populate this track's question or problem bank. Returns a summary line.

    Raises nothing: a failure here must degrade the interview, not end it. The
    caller gets a string describing what happened, which is also what the
    function tool returns to the model.
    """
    from prompts import QUESTION_GENERATION

    track_type = getattr(state, 'track_type', 'intro')
    if track_type not in ('behavioral', 'technical_voice', 'coding'):
        return "Question generation only available for behavioral, technical voice, and coding tracks."

    resume_snippet = (state.uploaded_resume_text or '')[:1500]
    jd_snippet = (state.job_description or '')[:800]

    try:
        if track_type == 'behavioral':
            framework = getattr(state, 'framework', 'amazon')
            depth = getattr(state, 'depth_setting', 'medium')
            custom_q = getattr(state, 'custom_questions', [])
            custom_q_str = '\n'.join(custom_q) if custom_q else 'None'
            competencies = QUESTION_GENERATION.behavioral_framework_competencies.get(
                framework, QUESTION_GENERATION.behavioral_framework_competencies['generic'])

            parsed = await _chat_json(
                QUESTION_GENERATION.behavioral_system.format(
                    count=count or _question_count_for_depth(depth),
                    framework=framework.title(),
                    role=state.job_role or 'Software Engineer',
                    level=state.experience_level or 'mid',
                    resume_snippet=resume_snippet or 'Not provided',
                    jd_snippet=jd_snippet or 'Not provided',
                    custom_questions=custom_q_str,
                    framework_competencies=competencies,
                ),
                max_tokens=1000,
            )
            questions = _with_custom_questions(parsed.get('questions', []), custom_q)
            state.generated_questions = questions
            state.active_question_count = min(len(questions), 3)
            logger.info(
                f"[QUESTIONS] Generated {len(questions)} behavioral questions "
                f"(framework={framework}, depth={depth}, custom={len(custom_q)})"
            )
            return (f"Generated {len(questions)} questions. Active question count: "
                    f"{state.active_question_count}. Now transition_stage when ready.")

        if track_type == 'technical_voice':
            topics = getattr(state, 'selected_topics', [])
            if not topics:
                return "No topics selected. Please transition to self_intro first."

            all_questions = []
            for topic in topics[:3]:
                parsed = await _chat_json(
                    QUESTION_GENERATION.technical_system.format(
                        topic=topic,
                        role=state.job_role or 'Software Engineer',
                        level=state.experience_level or 'mid',
                        resume_snippet=resume_snippet or 'Not provided',
                    ),
                    max_tokens=400,
                )
                all_questions.append({'topic': topic, 'questions': parsed.get('questions', [])})

            state.generated_questions = all_questions
            state.active_topic_count = len(topics[:3])
            logger.info(f"[QUESTIONS] Generated questions for {len(all_questions)} topics")
            return f"Generated questions for {len(all_questions)} topics. Now transition to self_intro."

        # Coding: the VETTED problem bank, not LLM-invented problems. Curated
        # problems ship test cases + reference solutions and are proven solvable.
        from coding import difficulty_for_level, select_problems
        problem_count = getattr(state, 'active_problem_count', 2)
        level = state.experience_level or 'mid'
        problems = select_problems(level=level, count=problem_count)
        state.generated_problems = problems
        state.active_problem_count = max(1, min(len(problems), 2))
        logger.info(
            f"[QUESTIONS] Selected {len(problems)} vetted coding problems "
            f"(difficulty: {difficulty_for_level(level)})"
        )
        return (f"Selected {len(problems)} vetted coding problems. Active problem count: "
                f"{state.active_problem_count}. Now transition_stage when ready to begin.")

    except Exception as e:
        logger.error(f"[QUESTIONS] Generation failed: {e}", exc_info=True)
        return f"Failed to generate questions: {e}. Proceed with general questions based on role."


def _has_questions(state: InterviewState) -> bool:
    track_type = getattr(state, 'track_type', 'intro')
    if track_type == 'coding':
        return bool(getattr(state, 'generated_problems', None))
    return bool(getattr(state, 'generated_questions', None))


async def ensure_questions_generated(state: InterviewState) -> bool:
    """Build the track's question bank if it is not already there.

    Idempotent, and safe to call on any track — the intro track has no bank and
    returns False without doing work. Call this before the interview starts;
    every stage that asks a generated question assumes it has already run.
    """
    track_type = getattr(state, 'track_type', 'intro')
    if track_type not in ('behavioral', 'technical_voice', 'coding'):
        return False
    if _has_questions(state):
        return False
    await generate_questions_for(state)
    return _has_questions(state)


# ---------------------------------------------------------------------------
# Stage navigation helpers shared by every path that changes the stage
# ---------------------------------------------------------------------------

def next_stage_for(state: InterviewState):
    """The stage after the current one on this track, or None at the end."""
    track_type = getattr(state, 'track_type', 'intro')
    if track_type == 'behavioral' and hasattr(state, 'get_next_behavioral_stage'):
        return state.get_next_behavioral_stage()
    if track_type == 'technical_voice' and hasattr(state, 'get_next_technical_voice_stage'):
        return state.get_next_technical_voice_stage()
    if track_type == 'coding' and hasattr(state, 'get_next_coding_stage'):
        return state.get_next_coding_stage()
    return state.get_next_stage()


def bank_item_for(state: InterviewState, stage) -> Optional[dict]:
    """This stage's entry in the pre-generated bank, whatever the track's shape.

    behavioral: {main_question, competency, follow_up_probes}
    technical_voice: {topic, questions}
    coding: the problem dict
    intro: nothing (no bank)
    """
    track_type = getattr(state, 'track_type', 'intro')
    stage_val = stage.value if hasattr(stage, 'value') else str(stage)
    try:
        if track_type == 'behavioral' and stage_val.startswith('behavioral_q'):
            idx = int(stage_val[-1]) - 1
            qs = getattr(state, 'generated_questions', []) or []
            return qs[idx] if idx < len(qs) else None
        if track_type == 'technical_voice' and stage_val.startswith('technical_concepts_'):
            idx = int(stage_val.split('_')[-1]) - 1
            qs = getattr(state, 'generated_questions', []) or []
            return qs[idx] if idx < len(qs) else None
        if track_type == 'coding' and stage_val.startswith('coding_problem_'):
            idx = int(stage_val.split('_')[-1]) - 1
            ps = getattr(state, 'generated_problems', []) or []
            return ps[idx] if idx < len(ps) else None
    except (ValueError, IndexError):
        return None
    return None


async def push_coding_problem(state: InterviewState, transport: "Transport", idx: int) -> bool:
    """Send problem `idx` to the editor. Returns False if there is no such problem."""
    problems = getattr(state, 'generated_problems', []) or []
    if idx >= len(problems):
        return False
    problem = problems[idx]
    attempts_done = state.get_attempts_for_problem(idx) if hasattr(state, 'get_attempts_for_problem') else 0
    try:
        await transport.emit({
            'type': 'coding_problem',
            'problem': problem,
            'problem_index': idx,
            'attempt_number': attempts_done + 1,
            'max_attempts': 3,
            'time_limit_minutes': problem.get('time_limit_minutes', 15),
        }, reliable=True)
        logger.info(f"[CODING] Pushed problem {idx} to the editor: {problem.get('title', '?')}")
    except Exception as e:
        logger.warning(f"[CODING] Failed to push problem {idx}: {e}")
    return True


async def advance_to(state: InterviewState, agent: "InterviewAgent", transport: "Transport", next_stage,
                     *, forced: bool = False, skipped: bool = False) -> None:
    """The one way the stage changes.

    Model-driven progression, the skip button and the wall-clock timer all
    used to carry their own copy of this sequence, and each copy drifted
    (skips left question pointers behind; the timer never pushed a coding
    problem). Now they call this. It changes state and instructions and tells
    the UI; it never speaks. Whoever advanced decides how the next utterance
    is produced.
    """
    current = state.stage
    state.transition_to(next_stage, forced=forced, skipped=skipped)
    sync_stage_pointers(state, next_stage)
    state.ledger.reset_stage_counters()
    try:
        await agent.update_instructions(agent._get_stage_instructions(state, next_stage))
    except Exception as e:
        logger.error(f"[STAGE] Instruction update failed entering {next_stage.value}: {e}")
    try:
        await transport.emit({"type": "stage_change", "stage": next_stage.value})
    except Exception as e:
        logger.error(f"[UI] Failed to emit stage change: {e}")
    stage_val = next_stage.value
    if getattr(state, 'track_type', 'intro') == 'coding' and stage_val.startswith('coding_problem_'):
        await push_coding_problem(state, transport, getattr(state, 'current_problem_index', 0))
    if stage_val == 'closing':
        state.closing_initiated = True
    logger.info(f"[STAGE] {current.value} -> {stage_val} (forced={forced}, skipped={skipped})")


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------

class InterviewAgent(Agent):
    """Flow. The FSM is driven by code; the model talks.

    There are no function tools. The 2026-09 audit traced the worst of Flow's
    behaviour to the tool protocol: the SDK's tool-step cap turned a long
    chain into a silent turn, and a queued acknowledgement was spoken a turn
    late. Per candidate turn, `prepare_turn` assesses the answer, updates the
    coverage ledger, decides the stage, picks one Move and hands the model a
    short note. See interview_turn.py.
    """

    def __init__(self, transport=None, candidate_info=None, track_type='intro', assess: Optional[AssessFn] = None):
        """Start in self_intro. The greeting is one fixed line spoken by code in
        `on_enter`, so the model's first instructions are the first stage's and
        the first thing it does is respond to the candidate's introduction.
        `on_enter` swaps in the fully-resolved instructions once state is bound."""
        self.candidate_info = candidate_info or {}
        self.candidate_name = self.candidate_info.get('name', 'Candidate')
        self.candidate_role = self.candidate_info.get('role', 'this position')
        self.track_type = track_type
        self._assessor = TurnAssessor(assess or assess_turn_openai)

        from fsm import BehavioralStage, TechnicalVoiceStage
        first_stage = {
            'behavioral': BehavioralStage.SELF_INTRO,
            'technical_voice': TechnicalVoiceStage.SELF_INTRO,
            'coding': CodingStage.SELF_INTRO,
        }.get(track_type, InterviewStage.SELF_INTRO)
        instructions = build_stage_instructions(first_stage)
        instructions = instructions.replace('[CANDIDATE_NAME]', self.candidate_name).replace('[ROLE]', self.candidate_role)
        super().__init__(instructions=instructions)
        self.transport = transport if transport is not None else NullTransport()

    @property
    def first_name(self) -> str:
        return (self.candidate_name or 'there').split()[0]

    # -- the turn ---------------------------------------------------------

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        await self.prepare_turn(turn_ctx, new_message)

    async def prepare_turn(self, turn_ctx, new_message) -> Move:
        """Decide this turn and leave one `[FLOW MOVE]` note in `turn_ctx`.

        Called by the SDK on the audio path (`on_user_turn_completed`) and by
        the harness directly, on a copy of the chat context in both cases.
        Must never raise anything but StopResponse: the SDK swallows other
        exceptions and skips the reply, which is the silent turn all over again.
        """
        state = self.session.userdata
        text = (getattr(new_message, 'text_content', None) or '').strip()
        stage_val = state.stage.value
        if state.closing_spoken:
            # The interview is over and the room is about to close. Anything
            # said now is a goodbye; answering it restarts the interview.
            try:
                self._chat_ctx.insert(new_message)
                self.session._conversation_item_added(new_message)
            except Exception:
                pass
            raise StopResponse()
        try:
            late = self._assessor.take_late()
            if late is not None:
                state.ledger.merge(late[0], late[1])

            inputs = self._turn_inputs(state)
            assessment = await self._assessor.finish(AssessInput(
                track=state.track_type, stage=stage_val,
                required_signals=stage_required_signals(state.track_type, stage_val, inputs.bank_item),
                last_question=state.last_question, answer=text,
                star_relevant=star_applies(state.track_type, stage_val),
                bank_probes=bank_probes(inputs.bank_item),
            ))
            state.ledger.merge(assessment, stage_val)

            reason = should_advance(inputs, state.ledger, assessment)
            pending = state.pending_move
            state.pending_move = None

            if reason and (inputs.next_stage in (None, 'closing')):
                await self._close(state, new_message)
                raise StopResponse()

            if reason:
                move = choose_move(inputs, state.ledger, assessment, advance_reason=reason)
                await advance_to(state, self, self.transport, self._stage_by_value(state, inputs.next_stage))
            elif pending is not None:
                # A forced/skipped transition already happened; its opening
                # question was parked for this reply so it lands with the
                # candidate's next words rather than as a cold interjection.
                move = pending
                move.ack_hint = move.ack_hint or _first_evidence(assessment)
            else:
                move = choose_move(inputs, state.ledger, assessment)

            if move.question:
                state.last_question = move.question
                state.questions_asked.append(move.question)
            note = render_move_note(move)
            logger.info(f"[TURN] stage={state.stage.value} move={move.kind} reason={move.reason} advance={reason}")
        except StopResponse:
            raise
        except Exception as e:
            logger.error(f"[TURN] prepare_turn failed, using the safe note: {e}", exc_info=True)
            note = SAFE_NOTE
            move = Move(kind='focus', focus='what they just said', reason='safe_note')
        turn_ctx.add_message(role='assistant', content=note)
        return move

    def _turn_inputs(self, state: InterviewState) -> TurnInputs:
        stage_val = state.stage.value
        nxt = next_stage_for(state)
        return TurnInputs(
            track=state.track_type, stage=stage_val,
            depth=getattr(state, 'depth_setting', 'medium') or 'medium',
            time_status=state.get_time_status(),
            bank_item=bank_item_for(state, state.stage),
            next_bank_item=bank_item_for(state, nxt) if nxt else None,
            next_stage=nxt.value if nxt else None,
            last_question=state.last_question,
            questions_asked=list(state.questions_asked),
            experience_level=state.experience_level or 'mid',
        )

    @staticmethod
    def _stage_by_value(state: InterviewState, value: str):
        stage = state.get_stage_by_name(value)
        if stage is None:
            raise ValueError(f"no stage {value!r} on this track")
        return stage

    async def _close(self, state: InterviewState, new_message) -> None:
        """End the interview: one scripted utterance spoken by code, no model turn."""
        closing = state.get_stage_by_name('closing')
        if closing is not None and state.stage != closing:
            await advance_to(state, self, self.transport, closing)
        # Keep the candidate's last words in the transcript even though no
        # reply is generated for them (mirrors what the SDK does on a reply).
        try:
            self._chat_ctx.insert(new_message)
            self.session._conversation_item_added(new_message)
        except Exception as e:
            logger.debug(f"[CLOSE] could not record final user turn: {e}")
        utterance = build_closing_utterance(state.ledger, self.first_name, state.track_type)
        state.closing_spoken = True
        self.session.say(utterance, allow_interruptions=False)
        logger.info("[CLOSE] closing utterance scheduled")

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

    # -- priming the assessment from interim transcripts ----------------------

    def _on_user_transcribed(self, event) -> None:
        """Start assessing while the candidate is still talking.

        The assessment call takes ~1.8 s warm; the endpointing delay is 0.8 s+.
        Starting on the last interim usually means the answer is already read
        by the time the turn ends. On the final we re-prime only if the text
        moved a lot, so the in-flight call is reused, not thrown away.
        """
        try:
            state = self.session.userdata
            text = (getattr(event, 'transcript', '') or '').strip()
            if not text:
                return
            stage_val = state.stage.value
            bank = bank_item_for(state, state.stage)
            self._assessor.prime(AssessInput(
                track=state.track_type, stage=stage_val,
                required_signals=stage_required_signals(state.track_type, stage_val, bank),
                last_question=state.last_question, answer=text,
                star_relevant=star_applies(state.track_type, stage_val),
                bank_probes=bank_probes(bank),
            ))
        except Exception as e:
            logger.debug(f"[TURN] prime failed (non-fatal): {e}")

    # -- lifecycle ----------------------------------------------------------

    async def on_enter(self):
        """Speak the fixed greeting and hand the floor to the candidate.

        Deliberately not `generate_reply()`: the audit found the model-written
        greeting was non-deterministic (sometimes skipped, sometimes doubled,
        sometimes narrated the FSM), and the stage walkthrough it used to carry
        now lives in the pre-join panel. One line, always the same, then wait.
        """
        logger.info(f"[AGENT] on_enter() called for candidate: {self.candidate_name}, track: {self.track_type}")
        state = getattr(self.session, 'userdata', None)
        if state is not None:
            try:
                await self.update_instructions(self._get_stage_instructions(state, state.stage))
            except Exception as e:
                logger.warning(f"[AGENT] Could not resolve first-stage instructions: {e}")
            try:
                await self._emit_stage_change(state.stage)
            except Exception as e:
                logger.warning(f"[AGENT] Could not emit initial stage: {e}")
        try:
            self.session.on("user_input_transcribed", self._on_user_transcribed)
        except Exception as e:
            logger.debug(f"[AGENT] could not subscribe to interim transcripts: {e}")
        self._assessor.warm_up()
        await self.session.say(get_greeting_line(self.track_type), allow_interruptions=False)

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


def opening_move_for(state: InterviewState) -> Move:
    """The first question of the stage the state is now in."""
    stage_val = state.stage.value
    inputs = TurnInputs(
        track=state.track_type, stage=stage_val,
        depth=getattr(state, 'depth_setting', 'medium') or 'medium',
        bank_item=bank_item_for(state, state.stage),
        questions_asked=list(state.questions_asked),
        experience_level=state.experience_level or 'mid',
    )
    return first_move_for_stage(inputs, state.ledger)


async def speak_closing(state: InterviewState, agent: "InterviewAgent", session, transport: "Transport") -> None:
    """Enter closing and say the one scripted line. Idempotent."""
    closing = state.get_stage_by_name('closing')
    if closing is not None and state.stage != closing:
        await advance_to(state, agent, transport, closing)
    if state.closing_spoken:
        return
    state.closing_spoken = True
    utterance = build_closing_utterance(state.ledger, agent.first_name, state.track_type)
    try:
        await session.say(utterance, allow_interruptions=False)
    except Exception as e:
        logger.warning(f"[CLOSE] say failed: {e}")


async def ask_opening_question(state: InterviewState, agent: "InterviewAgent", session, *, reason: str) -> None:
    """After a skip or a timer-forced transition: the next thing Flow says is
    the new stage's first question, produced by the model from a MOVE note.
    Never a canned acknowledgement."""
    move = opening_move_for(state)
    move.reason = reason
    if move.question:
        state.last_question = move.question
        state.questions_asked.append(move.question)
    state.pending_move = None
    try:
        session.generate_reply(instructions=render_move_note(move), allow_interruptions=True)
    except Exception as e:
        logger.warning(f"[STAGE] generate_reply after {reason} failed: {e}")


async def _async_skip_coding_problem(interview_state, transport, session, agent=None):
    """Handle skip_coding_problem: the next problem, or closing."""
    try:
        idx = getattr(interview_state, 'current_problem_index', 0)
        if hasattr(interview_state, 'skipped_problems') and idx not in interview_state.skipped_problems:
            interview_state.skipped_problems.append(idx)
        await advance_after_problem(interview_state, agent, session, transport)
    except Exception as e:
        logger.error(f"[CODE] _async_skip_coding_problem failed: {e}", exc_info=True)


async def advance_after_problem(state, agent, session, transport) -> None:
    """A problem is finished (passed, skipped, out of attempts, or timed out):
    push the next one, or close. Driven by the problem index, not the stage,
    so a submit that races a stage change still lands on the right problem.
    advance_to pushes the problem itself."""
    idx = getattr(state, 'current_problem_index', 0)
    active = getattr(state, 'active_problem_count', 0)
    problems = getattr(state, 'generated_problems', []) or []
    nxt = None
    if idx + 1 < active and idx + 1 < len(problems):
        nxt = state.get_stage_by_name(f'coding_problem_{idx + 2}')
    if nxt is None:
        await speak_closing(state, agent, session, transport)
        return
    await advance_to(state, agent, transport, nxt)
    if session is not None:
        try:
            title = (bank_item_for(state, state.stage) or {}).get('title', 'the next problem')
            await session.say(f"Next one's in your editor: {title}. Take a minute to read it, then talk me through your approach.",
                              allow_interruptions=True)
        except Exception as e:
            logger.warning(f"[CODE] say failed: {e}")


async def _async_handle_ready_for_problem(interview_state, transport, agent=None, session=None):
    """The candidate clicked "I'm Ready".

    Gated on stage: before the problems (self_intro / warm_up) it starts problem
    1; during a problem it re-pushes the current one (a reload); at any other
    time it is ignored. The audit found the old handler honoured the click in
    the greeting, pushed problem 1, and then Flow ran the intro script anyway
    and re-read problem 1 later as if new.
    """
    try:
        if not getattr(interview_state, 'generated_problems', None):
            await ensure_questions_generated(interview_state)
        if not getattr(interview_state, 'generated_problems', None):
            logger.warning("[CODING] ready_for_problem but no problems in the bank")
            return
        stage_val = interview_state.stage.value
        if stage_val in ('self_intro', 'warm_up'):
            first = interview_state.get_stage_by_name('coding_problem_1')
            await advance_to(interview_state, agent, transport, first)
            if session is not None:
                title = (bank_item_for(interview_state, interview_state.stage) or {}).get('title', 'the first problem')
                try:
                    await session.say(f"It's in your editor: {title}. Read it through, then tell me how you'd approach it before you write anything.",
                                      allow_interruptions=True)
                except Exception as e:
                    logger.warning(f"[CODING] say failed: {e}")
        elif stage_val.startswith('coding_problem_'):
            await push_coding_problem(interview_state, transport, getattr(interview_state, 'current_problem_index', 0))
        else:
            logger.info(f"[CODING] ready_for_problem ignored in stage {stage_val}")
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
    """The Skip button. Advance, then have the model ask the new stage's first
    question. No canned acknowledgement: the audit found those spoke the full
    name and narrated the FSM."""
    try:
        logger.info(f"[SKIP] {interview_state.stage.value} -> {target_stage.value}")
        await advance_to(interview_state, agent, transport, target_stage, skipped=True)
        if target_stage.value == 'closing':
            await speak_closing(interview_state, agent, session, transport)
            return
        await ask_opening_question(interview_state, agent, session, reason='skip')
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

        # Ground the evaluation in OBJECTIVE test results when the problem
        # ships test cases and hosted execution (Piston) is enabled. This used
        # to live only in the model-called tool; the editor's submit path never
        # ran it. There is one evaluation path now, and this is it.
        objective_summary = None
        try:
            from coding.piston_runner import PISTON_ENABLED, run_via_piston
            test_cases = problem.get('test_cases')
            entrypoint = problem.get('entrypoint')
            if PISTON_ENABLED and test_cases and entrypoint and language.lower().startswith('py'):
                # Off the event loop: run_via_piston is a blocking urlopen with
                # a 12s timeout, and this runs mid-interview.
                run = await asyncio.to_thread(run_via_piston, code, entrypoint, test_cases, language='python')
                if run.get('error') is None:
                    objective_summary = f"{run['passed']}/{run['total']} hidden test cases passed"
                    user_prompt += (
                        f"\n\nOBJECTIVE TEST RESULTS (ground truth - weight correctness on this): "
                        f"{objective_summary}."
                    )
                else:
                    logger.info(f"[CODE] Piston run skipped/failed: {run.get('error')}")
        except Exception as exec_err:
            logger.warning(f"[CODE] Objective execution error (continuing with LLM-only): {exec_err}")

        # Retry with backoff: the audit saw three 429s turn into no
        # evaluation_result at all, which left the editor on "Evaluating..."
        # forever. On exhaustion the UI gets evaluation_error instead of silence.
        response = None
        last_err: Optional[Exception] = None
        for attempt, delay in enumerate((0.0, 1.0, 2.5, 5.0)):
            if delay:
                await asyncio.sleep(delay)
            try:
                response = await client.chat.completions.create(
                    model='gpt-4o-mini',
                    messages=[
                        {'role': 'system', 'content': CODE_EVALUATOR.system},
                        {'role': 'user', 'content': user_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=600,
                )
                break
            except Exception as e:  # noqa: PERF203 - the retry is the point
                last_err = e
                logger.warning(f"[CODE] evaluation call failed (attempt {attempt + 1}): {type(e).__name__}: {e}")
        if response is None:
            await transport.emit({'type': 'evaluation_error', 'problem_index': problem_index,
                                  'message': 'The evaluator is unavailable right now. Please submit again.'}, reliable=True)
            raise RuntimeError(f"evaluation failed after retries: {last_err}")

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
            # Honest about provenance: without Piston nothing executed the
            # code, and correctness is an AI's reading of it.
            'executed': bool(objective_summary),
            'objective_tests': objective_summary,
        }, reliable=True)
        logger.info(f"[CODE] Evaluation sent to frontend for problem {problem_index}, attempt {attempt_num}")

        # Flow speaks the brief feedback, then code decides what is next: a
        # pass or the third attempt ends this problem. No model turn, no tool.
        verbal = evaluation.get('brief_verbal_feedback', '')
        passed = str(evaluation.get('correctness', '')).lower() == 'pass'
        done = passed or attempt_num >= 3
        if verbal and session:
            try:
                if done and not passed:
                    verbal = f"{verbal} That was the last attempt on this one."
                await session.say(verbal, allow_interruptions=True)
            except Exception as say_err:
                logger.warning(f"[CODE] session.say failed: {say_err}")
        if done:
            await advance_after_problem(state, _agent, session, transport)

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

    # The first stage is self_intro on every track; the greeting is spoken by
    # code in InterviewAgent.on_enter, not driven as a stage.
    if track_type == 'behavioral':
        state.transition_to(BehavioralStage.SELF_INTRO)
    elif track_type == 'technical_voice':
        state.transition_to(TechnicalVoiceStage.SELF_INTRO)
    elif track_type == 'coding':
        state.transition_to(CodingStage.SELF_INTRO)
    else:
        state.transition_to(InterviewStage.SELF_INTRO)

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
        # There are no tools in the speech path any more. Belt and braces: if
        # one ever returns, the SDK (1.3.6) drops the turn silently when this
        # cap is exceeded, so keep it where a single call cannot cross it.
        max_tool_steps=1,
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
                # MOVE notes live only in the per-turn copy of the context, but
                # if one ever surfaced here it must not become a transcript line.
                if agent_text and agent_text.lstrip().startswith(MOVE_HEADER):
                    return
                if agent_text:
                    logger.info(f"[AGENT] {agent_text[:150]}...")
                    conversation_history["agent"].append({
                        "index": len(conversation_history["agent"]),
                        "text": agent_text,
                        "timestamp": time.time(),
                        "stage": state.stage.value
                    })
                    asyncio.create_task(emit_agent_caption(transport, agent_text))

                    # What Flow actually asked, so "say that again?" repeats the
                    # spoken question, not the one the note intended.
                    asked = [q.strip() for q in agent_text.replace("!", ".").split("?") if q.strip()]
                    if "?" in agent_text and asked:
                        state.last_question = asked[-1].split(". ")[-1].strip() + "?"

                    if getattr(state.stage, 'value', '') == 'closing' and not closing_finalized["done"]:
                        text_lower = agent_text.lower()
                        closing_indicators = [
                            agent_text.rstrip().endswith(CLOSING_SENTINEL),
                            "thank you" in text_lower and "luck" in text_lower,
                            "good luck" in text_lower,
                            "best of luck" in text_lower,
                        ]
                        if any(closing_indicators) and len(agent_text) > 30:
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
        await _async_skip_coding_problem(ctx.state, ctx.transport, ctx.session, ctx.agent)


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
        logger.info("[CODING] ready_for_problem received")
        await _async_handle_ready_for_problem(ctx.state, ctx.transport, ctx.agent, ctx.session)


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
                        await speak_closing(state, agent, session, transport)
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
                next_stage = next_stage_for(state)
                if next_stage:
                    logger.warning(f"[FALLBACK] FORCING: {current_stage.value} -> {next_stage.value}")
                    is_problem = getattr(current_stage, 'value', '').startswith('coding_problem_')
                    if is_problem and hasattr(state, 'timed_out_problems'):
                        state.timed_out_problems.append(getattr(state, 'current_problem_index', 0))
                    if next_stage.value == 'closing':
                        await speak_closing(state, agent, session, transport)
                    elif is_problem:
                        try:
                            await session.say("Time's up on that one — I've moved you to the next problem.", allow_interruptions=False)
                        except Exception as e:
                            logger.warning(f"[FALLBACK] say failed: {e}")
                        await advance_to(state, agent, transport, next_stage, forced=True)
                    else:
                        await advance_to(state, agent, transport, next_stage, forced=True)
                        # Park the new stage's first question for the candidate's
                        # next turn so it lands as a reply, not an interjection;
                        # if they stay silent, ask it ourselves after a beat.
                        state.pending_move = opening_move_for(state)
                        state.pending_move.reason = 'forced'
                        await asyncio.sleep(6)
                        if state.pending_move is not None and getattr(session, 'current_speech', None) is None:
                            await ask_opening_question(state, agent, session, reason='forced')
                    logged_milestones = set()
                    last_logged_stage = state.stage

    except asyncio.CancelledError:
        logger.info("[TIMER] Fallback timer cancelled")
    except Exception as e:
        logger.error(f"[TIMER] Error: {e}", exc_info=True)
