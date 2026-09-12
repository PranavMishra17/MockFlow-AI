"""
The turn loop's decisions: what Flow should do next, decided in code.

Before: the model drove the interview through tools (assess_response,
ask_question, transition_stage) and the SDK's tool-step cap turned a long
chain into silence; the canned acknowledgement one tool queued for the next
was spoken a turn late; the STAR template probes were asked whether or not
the answer already had them. The 2026-09 audit traces all of that.

Now: per candidate turn, code (a) reads one structured assessment of the
answer, (b) merges it into the coverage ledger, (c) decides whether the stage
is done, (d) picks exactly one Move, and (e) hands the model a short
`[FLOW MOVE]` note saying what to acknowledge and what to ask. The model's
only job is to say it well. No tools in the speech path, so no silent turns;
the transition IS the reply, so no stale acknowledgements; the probe is
chosen from what is missing, so no template interrogation.

Everything here is pure except `assess_turn_openai`, which is the one network
call and is injectable so tests use a fake.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence

from interview_coverage import STAR_ELEMENTS, CoverageLedger, TurnAssessment

logger = logging.getLogger("interview-turn")

# Spoken by code at the end; attach_handlers fires on_closing when it hears it.
CLOSING_SENTINEL = "That's the end of the interview — take care."

# Per-stage turn cap by follow-up depth. A floor on signal, not on questions:
# these only bound how long Flow keeps probing one stage when coverage is not
# arriving, so a terse candidate is not held hostage.
MAX_TURNS_BY_DEPTH = {"light": 2, "medium": 3, "deep": 4}
MAX_TURNS_DEFAULT = 3
# Coverage alone must not end a stage after one good answer: an interview
# that is over in five turns has not interviewed anyone. Two exchanges per
# stage before "covered" counts; the caps above still bound the other side.
MIN_TURNS_BY_DEPTH = {"light": 1, "medium": 2, "deep": 2}
MIN_TURNS_DEFAULT = 2
ABSENT_STREAK_TO_ADVANCE = 2

ASSESS_MODEL = os.getenv("FLOW_ASSESS_MODEL", "gpt-4o-mini")
ASSESS_TIMEOUT_S = float(os.getenv("FLOW_ASSESS_TIMEOUT", "2.5"))


# ---------------------------------------------------------------------------
# Which signals a stage exists to surface
# ---------------------------------------------------------------------------

# Names are evaluator.SIGNAL_LIBRARY keys. Kept as literals here (not imported)
# so this module stays importable without the evaluator's OpenAI dependency;
# tests/test_interview_turn.py asserts every name exists in the library.
_STAGE_SIGNALS: Dict[str, Dict[str, List[str]]] = {
    "intro": {
        "self_intro": ["Motivation & authenticity"],
        "past_experience": ["Ownership", "Impact & metrics"],
        "company_fit": ["Role / company fit", "Self-awareness"],
    },
    "behavioral": {
        "self_intro": ["Communication & structure"],
        # behavioral_qN adds the question's own competency; see stage_required_signals.
        "behavioral_q1": ["Ownership", "Impact & metrics"],
        "behavioral_q2": ["Ownership", "Impact & metrics"],
        "behavioral_q3": ["Ownership", "Impact & metrics"],
    },
    "technical_voice": {
        "self_intro": ["Communication & structure"],
        "experience_discussion": ["Technical depth"],
        "technical_concepts_1": ["Technical depth", "Trade-off reasoning"],
        "technical_concepts_2": ["Technical depth", "Trade-off reasoning"],
        "technical_concepts_3": ["Technical depth", "Trade-off reasoning"],
    },
    "coding": {
        "self_intro": ["Communication & structure"],
        "warm_up": ["Communication & structure"],
        # coding_problem_N is not turn-driven; the submission flow owns it.
    },
}

_COMPETENCY_KEYWORDS = (
    (("conflict", "disagree", "team", "collaborat", "stakeholder", "influence", "trust"), "Conflict & collaboration"),
    (("own", "deliver", "bias for action", "accountab", "initiative", "drive"), "Ownership"),
    (("communicat", "explain", "present", "clarity"), "Communication & structure"),
    (("authentic", "motivat", "why", "value"), "Authenticity"),
)


def competency_signal(competency: Optional[str]) -> str:
    """Map a bank question's competency label ("Dive Deep", "Customer Obsession")
    to the verdict signal it most plausibly evidences. Default: impact."""
    c = (competency or "").lower()
    for keys, signal in _COMPETENCY_KEYWORDS:
        if any(k in c for k in keys):
            return signal
    return "Impact & metrics"


def stage_required_signals(track: str, stage: str, bank_item: Optional[Mapping[str, Any]] = None) -> List[str]:
    base = list(_STAGE_SIGNALS.get(track, _STAGE_SIGNALS["intro"]).get(stage, []))
    if track == "behavioral" and stage.startswith("behavioral_q") and bank_item:
        extra = competency_signal(bank_item.get("competency"))
        if extra not in base:
            base.append(extra)
    return base


def star_applies(track: str, stage: str) -> bool:
    """STAR completeness gates only the behavioral question stages."""
    return track == "behavioral" and stage.startswith("behavioral_q")


# ---------------------------------------------------------------------------
# Move: the one thing Flow does this turn
# ---------------------------------------------------------------------------

@dataclass
class Move:
    kind: str = "ask"          # ask | probe | focus | repeat | process | company | scaffold | wait | coding_reply | close
    question: str = ""         # asked word for word
    focus: str = ""            # or: ask ONE concrete question about this
    preface: str = ""          # a fixed sentence to say first (honest lines)
    ack_hint: str = ""         # a specific from their answer to acknowledge
    advanced_to: Optional[str] = None
    spoken_text: Optional[str] = None   # close: spoken by code, no LLM
    reason: str = ""           # why this move; logged, never spoken

    @property
    def is_question(self) -> bool:
        return self.kind not in ("close", "wait", "coding_reply")


PREFACE_PROCESS = "I can't give feedback mid-interview — it's written up on your dashboard afterwards."
PREFACE_COMPANY = "There's no real company behind this mock, so I can't speak for one — but that's a good question to ask in a real one."
PREFACE_DONT_KNOW = "Fair — that's better than guessing."
PREFACE_REPEAT = "Sure."

RAMBLE_PROBE = "In one sentence — what was the result?"
STAR_PROBES = {
    # Used only when the bank has no specific probe for the missing element.
    "situation": "What was going on that made this necessary?",
    "task": "And what were you on the hook for, specifically?",
    "action": "Walk me through what you did, step by step.",
    "result": "How did it turn out — what changed, in numbers if you have them?",
}
SCAFFOLD = "Start with what the task was, and just take it one step at a time."


@dataclass
class TurnInputs:
    """Everything choose_move / should_advance need, with no reference to the FSM."""

    track: str
    stage: str
    depth: str = "medium"                 # behavioral follow-up depth setting
    time_status: Mapping[str, Any] = field(default_factory=dict)
    bank_item: Optional[Mapping[str, Any]] = None       # this stage's bank question / topic
    next_bank_item: Optional[Mapping[str, Any]] = None  # the next stage's, for the transition question
    next_stage: Optional[str] = None
    last_question: str = ""
    questions_asked: Sequence[str] = ()
    experience_level: str = "mid"


def _norm(q: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (q or "").lower()).strip()


def _unasked(candidates: Sequence[str], asked: Sequence[str]) -> Optional[str]:
    seen = {_norm(a) for a in asked}
    for c in candidates:
        if c and _norm(c) not in seen:
            return c
    return None


def bank_main_question(item: Optional[Mapping[str, Any]], asked: Sequence[str] = ()) -> Optional[str]:
    """The next un-asked question this bank item carries, whatever its shape."""
    if not item:
        return None
    if item.get("main_question"):
        return _unasked([item["main_question"]], asked)
    if item.get("questions"):
        return _unasked(list(item["questions"]), asked)
    if item.get("title"):   # coding problem: never asked aloud
        return None
    return None


def bank_probes(item: Optional[Mapping[str, Any]]) -> List[str]:
    return list((item or {}).get("follow_up_probes") or [])


# ---------------------------------------------------------------------------
# Progression
# ---------------------------------------------------------------------------

def should_advance(inp: TurnInputs, ledger: CoverageLedger, assessment: TurnAssessment) -> Optional[str]:
    """Return the reason to leave this stage now, or None to stay.

    Coding problem stages are owned by the submission flow (step 5), never by
    the conversation loop.
    """
    if inp.track == "coding" and inp.stage.startswith("coding_problem"):
        return None
    if inp.stage == "closing":
        return None

    required = stage_required_signals(inp.track, inp.stage, inp.bank_item)
    star_ok = ledger.result_told(inp.stage) if star_applies(inp.track, inp.stage) else True
    floor = MIN_TURNS_BY_DEPTH.get(inp.depth, MIN_TURNS_DEFAULT) if inp.track == "behavioral" else MIN_TURNS_DEFAULT
    if required and ledger.covered(required) and star_ok and ledger.turns_in_stage >= floor:
        return "coverage"
    if inp.time_status.get("is_overtime"):
        return "overtime"
    if assessment.answer_style == "terse" and ledger.absent_streak >= ABSENT_STREAK_TO_ADVANCE:
        return "terse_no_signal"
    cap = MAX_TURNS_BY_DEPTH.get(inp.depth, MAX_TURNS_DEFAULT) if inp.track == "behavioral" else MAX_TURNS_DEFAULT
    if ledger.turns_in_stage >= cap:
        return "turn_cap"
    return None


# ---------------------------------------------------------------------------
# Choosing the move
# ---------------------------------------------------------------------------

def _first_evidence(assessment: TurnAssessment) -> str:
    for s in assessment.signals:
        if s.evidence and s.level != "absent":
            return s.evidence
    return ""


def first_move_for_stage(inp: TurnInputs, ledger: CoverageLedger) -> Move:
    """The opening question of a stage — used for transitions, skips and timer-forced moves."""
    q = bank_main_question(inp.bank_item, inp.questions_asked)
    if q:
        return Move(kind="ask", question=q, reason="stage_open_bank")
    required = stage_required_signals(inp.track, inp.stage, inp.bank_item)
    focus = _focus_for(required, ledger)
    if focus:
        return Move(kind="focus", focus=focus, reason="stage_open_focus")
    return Move(kind="focus", focus="what they have been working on recently and the part they owned", reason="stage_open_default")


_FOCUS_TEXT = {
    "Motivation & authenticity": "why they are pursuing this role now, in their own words",
    "Communication & structure": "one project, told from the problem to the outcome",
    "Ownership": "a piece of work they personally drove, and the decision that was theirs",
    "Impact & metrics": "the measurable outcome of something they built",
    "Conflict & collaboration": "a disagreement with a colleague and how it was resolved",
    "Authenticity": "a time something did not go to plan and what they would do differently",
    "Role / company fit": "what in this role's day-to-day they want more of than they have today",
    "Self-awareness": "a gap they know they have and what they are doing about it",
    "Technical depth": "how something they built works under the hood, and why it was designed that way",
    "Trade-off reasoning": "an alternative they considered and rejected, and the cost of each",
    "Problem-solving": "how they would approach the problem before writing code",
}


def _focus_for(required: Sequence[str], ledger: CoverageLedger) -> str:
    for name in ledger.missing(required):
        if name in _FOCUS_TEXT:
            return _FOCUS_TEXT[name]
    return ""


def choose_move(inp: TurnInputs, ledger: CoverageLedger, assessment: TurnAssessment, *, advance_reason: Optional[str] = None) -> Move:
    """Exactly one Move for this turn. Order encodes priority.

    Candidate's meta-question first (a repeat request must be honoured before
    anything else), then their honesty, then their style, then coverage.
    """
    ack = _first_evidence(assessment)

    # Coding problem stages: the candidate is thinking aloud at the editor.
    if inp.track == "coding" and inp.stage.startswith("coding_problem"):
        return Move(kind="coding_reply", ack_hint=ack, reason="coding_thinking_aloud")

    # 1. The candidate asked Flow something.
    if assessment.candidate_asked == "repeat" and inp.last_question:
        return Move(kind="repeat", preface=PREFACE_REPEAT, question=inp.last_question, reason="repeat")

    preface = ""
    if assessment.candidate_asked in ("process", "feedback"):
        preface = PREFACE_PROCESS
    elif assessment.candidate_asked == "company":
        preface = PREFACE_COMPANY

    # 2. Leaving the stage: the transition is this reply.
    if advance_reason and inp.next_stage:
        nxt = TurnInputs(track=inp.track, stage=inp.next_stage, depth=inp.depth, bank_item=inp.next_bank_item,
                         questions_asked=inp.questions_asked, experience_level=inp.experience_level)
        move = first_move_for_stage(nxt, ledger)
        move.advanced_to = inp.next_stage
        move.preface = preface
        move.ack_hint = ack
        move.reason = f"advance:{advance_reason}"
        return move

    required = stage_required_signals(inp.track, inp.stage, inp.bank_item)
    probes = bank_probes(inp.bank_item)

    # 3. "I don't know": one scaffold, then move on (the next absent read advances).
    if assessment.said_dont_know:
        if ledger.probes_used == 0:
            ledger.note_probe()
            return Move(kind="scaffold", preface=preface or PREFACE_DONT_KNOW, question=SCAFFOLD, ack_hint="", reason="dont_know_scaffold")
        q = bank_main_question(inp.bank_item, inp.questions_asked) or ""
        focus = "" if q else _focus_for(required, ledger)
        return Move(kind="ask" if q else "focus", preface=preface or PREFACE_DONT_KNOW, question=q, focus=focus, reason="dont_know_move_on")

    # 4. Style: rambling without an answer gets pinned to the result; terse gets a narrow, concrete question.
    if assessment.answer_style == "rambling" and not assessment.answered_question:
        ledger.note_probe()
        return Move(kind="probe", preface=preface, question=RAMBLE_PROBE, ack_hint=ack, reason="ramble_pin")
    if assessment.answer_style == "terse" and ack:
        ledger.note_probe()
        return Move(kind="focus", preface=preface, focus=f"the one specific thing they mentioned: {ack}", ack_hint=ack, reason="terse_narrow")

    # 5. Missing STAR element (behavioral question stages): the bank's specific probe, else a plain one.
    if star_applies(inp.track, inp.stage):
        missing = ledger.missing_star(inp.stage)
        if missing:
            # Once a story has begun, the result is what usually goes untold;
            # before it has, start from the top.
            begun = any(v != "absent" for v in ledger.star_for(inp.stage).values())
            el = "result" if ("result" in missing and begun) else missing[0]
            q = _unasked(probes, inp.questions_asked) or STAR_PROBES[el]
            ledger.note_probe()
            return Move(kind="probe", preface=preface, question=q, ack_hint=ack, reason=f"star_missing:{el}")

    # 6. Missing signal: the bank's main question if not yet asked, else a focus.
    q = bank_main_question(inp.bank_item, inp.questions_asked)
    if q:
        return Move(kind="ask", preface=preface, question=q, ack_hint=ack, reason="bank_main")
    p = _unasked(probes, inp.questions_asked)
    if p and ledger.missing(required):
        ledger.note_probe()
        return Move(kind="probe", preface=preface, question=p, ack_hint=ack, reason="bank_probe")
    focus = _focus_for(required, ledger)
    if focus:
        return Move(kind="focus", preface=preface, focus=focus, ack_hint=ack, reason="focus_missing_signal")

    # 7. Nothing missing and nowhere to go yet: a natural follow-up on what they said.
    return Move(kind="focus", preface=preface, focus="the most interesting specific in what they just said", ack_hint=ack, reason="follow_up")


# ---------------------------------------------------------------------------
# The note the model reads
# ---------------------------------------------------------------------------

MOVE_HEADER = "[FLOW MOVE — instructions, not speech]"
MOVE_FOOTER = ("One question only. Under 45 words total. No section, stage, framework or tool words. "
               "Do not say the candidate's name. No markdown.")


def render_move_note(move: Move) -> str:
    lines = [MOVE_HEADER]
    if move.preface:
        lines.append(f'First say exactly: "{move.preface}"')
    if move.kind == "coding_reply":
        lines.append("Answer what they asked in under 25 words, or say 'go ahead' if they were just thinking aloud. "
                     "Do not read or paraphrase the problem. Ask nothing unless they asked you something.")
        return "\n".join(lines)
    ack = "Pick up one specific from their answer in at most 12 words, no praise adjectives"
    if move.ack_hint:
        ack += f' (e.g. "{move.ack_hint[:80]}")'
    ack += ". Vary how you open: not \"You mentioned\" every time; sometimes skip the pickup and just ask"
    lines.append(ack + ".")
    if move.question:
        lines.append(f'Then ask exactly, word for word: "{move.question}"')
    else:
        lines.append(f"Then ask ONE concrete question about: {move.focus}. Answerable in under a minute.")
    lines.append(MOVE_FOOTER)
    return "\n".join(lines)


SAFE_NOTE = (f"{MOVE_HEADER}\nAsk one short follow-up question about what they just said. "
             "Under 45 words. One question. Do not say the candidate's name.")


# ---------------------------------------------------------------------------
# Closing
# ---------------------------------------------------------------------------

def build_closing_utterance(ledger: CoverageLedger, first_name: str, track: str) -> str:
    """One utterance, spoken by code: one concrete thing they did (their own
    words, not an adjective), where the feedback is, the sentinel."""
    quote = ledger.best_quote(max_words=14)
    if quote:
        opener = f"Thanks, {first_name}. The part about \"{quote}\" is the kind of specific that lands."
    else:
        opener = f"Thanks, {first_name}."
    return f"{opener} Your written feedback is on your dashboard in a minute. {CLOSING_SENTINEL}"


# ---------------------------------------------------------------------------
# The assessment call
# ---------------------------------------------------------------------------

@dataclass
class AssessInput:
    track: str
    stage: str
    required_signals: Sequence[str]
    last_question: str
    answer: str
    star_relevant: bool = False
    bank_probes: Sequence[str] = ()


AssessFn = Callable[[AssessInput], Awaitable[TurnAssessment]]

_ASSESS_SYSTEM = """You read one candidate answer in a mock interview and return a strict JSON assessment. You are not the interviewer; you never write questions.

For each listed signal, decide if this answer demonstrates it: "demonstrated" (specific, first-person, with a concrete outcome or mechanism), "partial" (mentioned but generic or unfinished), or "absent". Quote evidence VERBATIM from the answer (under 20 words), or leave evidence empty.

STAR: mark situation/task/action/result as demonstrated/partial/absent for THIS answer only.

answered_question: did they address the question asked? answer_style: terse (under ~20 words or a dodge), rambling (long, tangential, no clear point), or normal. candidate_asked: repeat (asked to hear the question again), process (how the interview works / how long), feedback (how am I doing), company (about the team, company, role, salary), or none. said_dont_know: they said they do not know or cannot answer.

Return only JSON matching the schema."""

_ASSESS_SCHEMA = {
    "name": "turn_assessment",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "signals": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"name": {"type": "string"},
                               "level": {"type": "string", "enum": ["absent", "partial", "demonstrated"]},
                               "evidence": {"type": "string"}},
                "required": ["name", "level", "evidence"]}},
            "star": {"type": "object", "additionalProperties": False,
                     "properties": {el: {"type": "string", "enum": ["absent", "partial", "demonstrated"]} for el in STAR_ELEMENTS},
                     "required": list(STAR_ELEMENTS)},
            "answered_question": {"type": "boolean"},
            "answer_style": {"type": "string", "enum": ["terse", "normal", "rambling"]},
            "candidate_asked": {"type": "string", "enum": ["none", "repeat", "process", "feedback", "company"]},
            "said_dont_know": {"type": "boolean"},
        },
        "required": ["signals", "star", "answered_question", "answer_style", "candidate_asked", "said_dont_know"],
    },
}


def _assess_user_prompt(inp: AssessInput) -> str:
    return (
        f"Track: {inp.track}. Stage: {inp.stage}.\n"
        f"Signals to read: {json.dumps(list(inp.required_signals))}\n"
        f"STAR relevant: {'yes' if inp.star_relevant else 'no'}\n"
        f"Question asked: {inp.last_question or '(the opening invitation to introduce themselves)'}\n"
        f"Candidate answer:\n{inp.answer}"
    )


async def assess_turn_openai(inp: AssessInput, *, timeout: float = ASSESS_TIMEOUT_S) -> TurnAssessment:
    """The production assessor. Raises on timeout/errors; the caller degrades."""
    import openai

    client = openai.AsyncOpenAI(max_retries=0)
    words = len((inp.answer or "").split())
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model=ASSESS_MODEL,
            temperature=0,
            max_tokens=350,
            messages=[{"role": "system", "content": _ASSESS_SYSTEM},
                      {"role": "user", "content": _assess_user_prompt(inp)}],
            response_format={"type": "json_schema", "json_schema": _ASSESS_SCHEMA},
        ),
        timeout=timeout,
    )
    raw = json.loads(resp.choices[0].message.content or "{}")
    return TurnAssessment.from_dict(raw, words=words)


# ---------------------------------------------------------------------------
# Running the assessment without holding up the reply
# ---------------------------------------------------------------------------

def _close_enough(a: str, b: str) -> bool:
    """Is the primed text substantially the final text? Deepgram interims grow
    by appending; a final that adds a few words is the same answer."""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return False
    if b.startswith(a) or a.startswith(b):
        return abs(len(a) - len(b)) <= max(40, len(b) // 5)
    return False


class TurnAssessor:
    """Owns the one network call per turn and keeps it off the critical path.

    `prime()` starts the call on an interim transcript while the candidate is
    still speaking. `finish()` reuses that call when the final text matches,
    else starts a fresh one, and waits at most `timeout`; on timeout it returns
    a neutral assessment and keeps the call running so the next turn can merge
    the late result (`take_late`). The reply is never blocked on assessment.
    """

    def __init__(self, assess: AssessFn, *, timeout: float = ASSESS_TIMEOUT_S):
        self._assess = assess
        self._timeout = timeout
        self._primed_text: str = ""
        self._task: Optional["asyncio.Task[TurnAssessment]"] = None
        self._late: Optional[tuple["asyncio.Task[TurnAssessment]", str]] = None
        self._warmed = False

    def prime(self, inp: AssessInput) -> None:
        if self._task and not self._task.done() and _close_enough(self._primed_text, inp.answer):
            return
        if self._task and not self._task.done():
            self._task.cancel()
        self._primed_text = inp.answer
        self._task = asyncio.create_task(self._assess(inp))

    async def finish(self, inp: AssessInput, *, timeout: Optional[float] = None) -> TurnAssessment:
        timeout = self._timeout if timeout is None else timeout
        words = len((inp.answer or "").split())
        task = self._task if (self._task and _close_enough(self._primed_text, inp.answer)) else None
        if task is None:
            if self._task and not self._task.done():
                self._task.cancel()
            task = asyncio.create_task(self._assess(inp))
        self._task, self._primed_text = None, ""
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout)
        except asyncio.TimeoutError:
            logger.warning(f"[ASSESS] timed out after {timeout:.1f}s; replying on the previous ledger")
            self._late = (task, inp.stage)
            return TurnAssessment.empty(words=words)
        except Exception as e:
            logger.warning(f"[ASSESS] failed ({type(e).__name__}: {e}); replying on the previous ledger")
            return TurnAssessment.empty(words=words)

    def take_late(self) -> Optional[tuple[TurnAssessment, str]]:
        """A previously timed-out assessment that has since finished, once."""
        if not self._late:
            return None
        task, stage = self._late
        if not task.done():
            return None
        self._late = None
        try:
            return task.result(), stage
        except Exception:
            return None

    def warm_up(self) -> None:
        """Open the HTTP connection before the first real turn (~3 s cold)."""
        if self._warmed:
            return
        self._warmed = True

        async def _go():
            try:
                await self._assess(AssessInput(track="intro", stage="self_intro", required_signals=["Communication & structure"],
                                               last_question="", answer="Hi, I'm ready."))
            except Exception:
                pass
        try:
            asyncio.create_task(_go())
        except RuntimeError:
            pass
