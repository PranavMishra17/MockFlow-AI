# The interview runtime contract

Frozen by WT0 (`refactor/interview-runtime`). Seven worktrees fan out from here
and several of them touch the same three files, so the shapes below are the
agreement that keeps them from inventing incompatible versions of the same
thing. `docs/HANDOFF_harness_skip_inputmodes.md` §6 is where this list comes
from; this file is the version with real signatures in it.

Two kinds of entry appear below:

- **Live** — exists in `interview_runtime.py` today, pinned by
  `tests/test_interview_runtime.py`. Change it only with a reason.
- **Reserved** — does not exist yet. The owning worktree builds it, and builds
  it in this shape. Reserved names are already spoken for; do not reuse them for
  anything else.

---

## 0. How a turn works — LIVE since 2026-09-12

There are **no function tools in the speech path**. The model does not call
`assess_response`, `ask_question` or `transition_stage`; those are gone, along
with the canned transition acknowledgements. `docs/AGENT_AUDIT_2026-09.md`
records why (silent turns at the SDK's tool-step cap; acknowledgements spoken
one turn late; template probes; no memory across stages).

Per candidate turn, `InterviewAgent.prepare_turn(turn_ctx, new_message)` runs
in code — from `on_user_turn_completed` on the audio path, and directly from
`HarnessSession.say` in the harness (the SDK's `session.run(user_input=)`
never calls the hook, so the harness mirrors the SDK's end-of-turn sequence:
copy the chat context, prepare the turn on the copy, generate from it):

1. **Assess** — one structured call (`interview_turn.assess_turn_openai`,
   strict JSON; primed from the last STT interim while the candidate is still
   talking; 2.5 s budget; a late result merges on the next turn).
2. **Ledger** — `state.ledger` (`interview_coverage.CoverageLedger`), keyed by
   the verdict's signal names (`evaluator.SIGNAL_LIBRARY`). Monotone and
   cross-stage: a STAR story told in self_intro credits the behavioral stage.
3. **Progress** — `interview_turn.should_advance`: required signals covered
   (after a two-turn floor per stage), stage overtime, two empty reads from a
   terse candidate, or the depth's turn cap. Advancing is `advance_to()`, the
   single path for every stage change (model-driven, skip, timer): it changes
   state and instructions, emits `stage_change`, pushes a coding problem when
   entering one, and never speaks.
4. **Move** — `interview_turn.choose_move`: repeat / process / company
   questions get a fixed honest preface; "I don't know" gets one scaffold;
   a rambler is pinned to the result; a terse candidate gets a narrow
   question; a missing STAR element gets the bank's own follow-up probe;
   else the bank's next question.
5. **Note** — one `[FLOW MOVE — instructions, not speech]` message appended to
   the turn's chat context (never persisted, never a transcript line). The
   reply IS the transition.

`prepare_turn` never raises anything but `StopResponse`; on any failure it
leaves `SAFE_NOTE`. `AgentSession(max_tool_steps=1)` as belt and braces.

**Greeting**: one fixed line per track (`prompts.GREETING_LINES`), spoken by
code in `on_enter`, never generated. Interviews start in `self_intro`.
**Closing**: one utterance built by code (`build_closing_utterance`) that
quotes the candidate's strongest evidence and ends with
`interview_turn.CLOSING_SENTINEL`; `attach_handlers` finalizes on that
sentinel and on nothing else. After it, `prepare_turn` stays quiet.

## 1. Module surface — LIVE

```python
# Transport
class Transport(Protocol):
    async def emit(self, payload: Mapping[str, Any], *, reliable: bool = True) -> None: ...

class RoomTransport:                      # production: publishes JSON on the data channel
    def __init__(self, room): ...

class NullTransport:                      # tests: collects decoded dicts
    events: list[dict]
    def of_type(self, type_name: str) -> list[dict]: ...

# Construction
def build_interview_state(
    config: Mapping[str, Any],            # already through agent_mode.normalize_config
    *,
    candidate_name: str = "Candidate",
    now: Optional[Callable[[], datetime]] = None,
) -> InterviewState: ...

def build_session(
    state: InterviewState,
    *,
    llm,
    stt=None, tts=None, vad=None,
    turn_detection=NOT_GIVEN,
) -> AgentSession: ...                    # sets max_tool_steps=1

# The turn loop (interview_turn.py)
async def InterviewAgent.prepare_turn(turn_ctx, new_message) -> Move
async def advance_to(state, agent, transport, next_stage, *, forced=False, skipped=False) -> None
async def speak_closing(state, agent, session, transport) -> None
async def ask_opening_question(state, agent, session, *, reason) -> None

# Event wiring
@dataclass
class RuntimeHandles:
    conversation: dict                    # {"agent": [...], "user": [...]}
    closing_finalized: dict               # {"done": bool}
    speech_window: dict                   # {"started": float|None, "pending": float|None}

def attach_handlers(
    session: AgentSession,
    state: InterviewState,
    transport: Transport,
    *,
    on_closing: Optional[Callable[[], Awaitable[None]]] = None,
) -> RuntimeHandles: ...

# Command dispatch
@dataclass
class CommandContext:
    session: AgentSession
    state: InterviewState
    agent: InterviewAgent
    transport: Transport
    track_config: Any = None

COMMANDS: dict[str, Callable[[Mapping[str, Any], CommandContext], Awaitable[None]]]

async def handle_command(payload: Mapping[str, Any], ctx: CommandContext) -> bool: ...

# Finalize
def collect_interview_data(
    state: InterviewState,
    conversation: Mapping[str, Any],
    *,
    room_name: str,
    ended_by: str,                        # 'natural_completion' | 'user_disconnect'
    candidate_name: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict: ...

# Timer
async def stage_fallback_timer(
    session, state, transport, agent, interview_complete,
    track_config=None, on_timeout=None,
) -> None: ...
```

**`build_session` takes no `agent`.** The handoff sketched one. `AgentSession`
does not accept an agent — it is bound in `session.start(agent=...)` — so a
parameter here could only be accepted and ignored, implying a coupling that does
not exist.

**`stage_fallback_timer` takes `on_timeout`.** It used to call
`room.disconnect()` directly on the closing timeout, which is the one thing in
it that was about the room. The caller supplies that now.

### Adding a command

Add an entry to `COMMANDS`. Do not edit another worktree's handler, and do not
add a second dispatch path — this registry exists specifically so that WT2 and
WT5, which both add commands, touch different lines.

```python
async def _cmd_my_thing(payload: Mapping[str, Any], ctx: CommandContext) -> None:
    ...

COMMANDS['my_thing'] = _cmd_my_thing
```

`handle_command` returns False for an unknown type and swallows handler
exceptions — a malformed client message must not end the interview.

---

## 2. Client → agent payloads

Everything goes over `publishData`. The frontend runs `livekit-client@2.22.3`
(bumped from 2.5.0 for live captions, see §3); commands stay on `publishData`.

| `type` | Fields | Owner | Status |
|---|---|---|---|
| `skip_intro` | — | WT0 | LIVE |
| `skip_stage` | `target_stage` | WT0 | LIVE |
| `code_submitted` | `code`, `language`, `problem_index` | WT0 | LIVE |
| `skip_coding_problem` | — | WT0 | LIVE |
| `ready_for_problem` | — | WT0 | LIVE |
| `skip_question` | — | WT2 | RESERVED |
| `set_input_mode` | `mode`: `"voice"｜"ptt"｜"text"` | WT5 | RESERVED |
| `ptt_start` / `ptt_end` / `ptt_cancel` | — | WT5 | RESERVED |
| `user_text` | `text` | WT5 | RESERVED |

---

## 3. Agent → client events

| `type` | Fields | Owner | Status |
|---|---|---|---|
| `stage_change` | `stage` | WT0 | LIVE |
| `stage_update` | `stage` | WT0 | LIVE (coding close-out only) |
| `user_caption` / `agent_caption` | `text` | WT0 | LIVE — **fallback only** |
| `coding_problem` | `problem`, `problem_index`, `attempt_number`, `max_attempts`, `time_limit_minutes` | WT0 | LIVE |
| `evaluation_result` | `evaluation`, `attempt`, `max_attempts`, `problem_index`, `objective_tests?` | WT0 | LIVE |
| `max_attempts_reached` | `problem_index` | WT0 | LIVE |
| `interview_saved` | `interview_id`, `message?` | WT0 | LIVE |
| `interview_ending` / `save_error` | `message` | WT0 | LIVE |

**Live captions are not a data payload.** The agents SDK publishes both speakers'
transcriptions as text streams on topic `lk.transcription`, paced to the audio
(one delta stream per agent reply; one full-text stream per STT interim for the
candidate, same `lk.segment_id`). `interview.html` consumes them via
`registerTextStreamHandler` and `static/captions.js`. Two facts the page depends
on, both verified against LiveKit Cloud (2026-09): the legacy `Transcription`
packet (`RoomEvent.TranscriptionReceived`) is **not forwarded** any more, and in
direct mode both speakers' streams arrive under the **agent's** identity, so the
page routes by `lk.transcribed_track_id`, not sender. `agent_caption` is emitted
from `conversation_item_added`, i.e. after playback, which is why it can only
be the fallback. `tests/e2e/caption_probe.py` asserts all of this live.
| `question_skipped` | `stage`, `outcome`, `skipped_count` | WT2 | RESERVED |
| `agent_state` | `state`: `"listening"｜"thinking"｜"speaking"` | WT5 | RESERVED |
| `input_mode` | `mode` | WT5 | RESERVED |

---

## 4. Per-turn transcript record

`RuntimeHandles.conversation["user"]` entries, as written today:

```python
{
  "index": int,
  "text": str,
  "timestamp": float,      # time.time()
  "duration_s": float|None,# measured speaking seconds; None means NOT MEASURED
  "stage": str,
}
```

`"mode": "voice"|"text"` is **RESERVED for WT5** and must be added to both
recording paths in `attach_handlers`.

`duration_s` is `None` for typed turns and for any voice turn whose speaking
window was implausible. **None is the honest value and must survive to
`speech_analytics`.** Writing `0` there is a fabricated measurement, which is the
exact failure `fix/delivery-metrics-honest` removed; do not reintroduce it.

Agent entries are the same minus `duration_s`.

### Why user turns come from two events

`user_input_transcribed` (final) is authoritative for voice.
`conversation_item_added(role="user")` records a turn **only** when no STT final
has arrived since the last one — an empty buffer means nothing was spoken, so
the text was typed.

Neither event alone is sufficient, and the reasoning is in `attach_handlers`'
docstring. The short version: an STT event never fires for typed input, and
livekit-agents 1.3.6 only adds the user message to the chat context
`if new_message is not None and speech_handle.scheduled`, so an interrupted turn
never produces a `conversation_item_added` either.

---

## 5. `skipped_questions` — RESERVED for WT2

```python
{"stage": str, "index": int, "question": str,
 "source": "button" | "voice" | "stage_skip", "at": str}
```

Stored in a **new JSONB column** with a migration (handoff §8.4), not folded into
an existing JSON blob. `"voice"` stays in the enum although WT2 ships button-only
(§8.3), so adding voice later is not a schema change.

`collect_interview_data` is where it gets persisted; add the key there so both
finalize paths pick it up at once.

---

## 6. Delivery block — LIVE, shape owned by `speech_analytics`

Already shipped in `fix/delivery-metrics-honest`. Read
`tests/test_delivery_honesty.py` before changing it.

```python
{"pace_available": bool, "avg_words_per_minute": float|None,
 "total_speaking_duration_seconds": float|None, "longest_monologue_s": float|None,
 "filler_total": int, "filler_per_100_words": float, ...}
```

WT6 adds the typed-session case: exclude `mode == "text"` turns from pace and
report unavailability with a reason when too few voice turns remain.

---

## 7. The clock

`InterviewState._now` is a `Callable[[], datetime]` defaulting to
`datetime.now`. Every wall-clock read inside the class goes through it, so a
harness can age a stage without sleeping:

```python
fake = {'t': datetime(2026, 1, 1, 12, 0, 0)}
state = build_interview_state(config, now=lambda: fake['t'])
fake['t'] += timedelta(minutes=7)
state.time_in_current_stage()   # 420.0
```

The speaking-window capture in `attach_handlers` still reads `time.time()`
directly, because it measures audio wall-time rather than interview progress.
Tests monkeypatch `time.time`; see `tests/test_speech_window.py`.

---

## 7b. Corrections found by tracing, 2026-09-05

Two read-only passes over this code and over livekit-agents 1.3.6 turned up
things the handoff assumes that are not true. These are normative: the owning
worktree must handle them, not rediscover them.

### For WT2 (skip the question)

1. **`current_question_text()` cannot be implemented for intro or
   technical_voice as things stand.** The only writer of question text anywhere
   is `ask_question` (`interview_runtime.py`), which the model is *asked* to
   call and never forced to. Intro has no question store at all; technical_voice
   stores three questions per topic with no pointer to the current one. Decide
   explicitly: either make `ask_question` the single choke point that records
   `state.current_question`, and accept that a question asked without the tool
   is unattributable — or narrow the "every question, no exceptions" claim.
2. **`execute_skip_transition` does not advance the per-track indices.** The
   block that sets `current_question_index`, `current_problem_index`,
   `coding_stage_active` and `problem_start_times` lives only in
   `transition_stage`. A skip to `behavioral_q2` today leaves the index at 0 and
   injects Q1's text into the Q2 stage. Extract that block and call it from both
   paths **before** unifying anything on top of it.
3. **`skipped_stages` and `skipped_questions` collide.**
   `transition_to(skipped=True)` unconditionally appends to `skipped_stages`. A
   single skipped *question* that resolves to NEXT_STAGE would be recorded as a
   skipped *stage* and shown to the candidate as one.
4. **The hard gate on the intro track is time, not question count.**
   `transition_stage` refuses to leave `self_intro`/`past_experience`/
   `company_fit` before 30/45/30s regardless of any counter. "A skipped question
   still counts as asked, so skipping can never trap a candidate" is true of the
   counter and false of the gate.
5. **Nothing makes the agent ask the next question after a skip.**
   `execute_skip_transition` ends at `session.say(ack)` with no
   `generate_reply()`, so today's skips leave the agent silent until the
   candidate speaks. Name the `generate_reply()` as a required step.
6. **`track` vs `track_type`.** `state.track` is set dynamically;
   `track_type` is the declared field, and different call sites read different
   ones. **`track_type` is authoritative.** New code that guesses wrong gets a
   silently dead branch.

### For WT5 (input modes)

7. **`session.interrupt()` will RAISE here.** It calls
   `speech.interrupt(force=False)` on the current speech, which raises when the
   speech disallows interruptions — and this repo plays three non-interruptible
   speeches (cached welcome, skip ack, closing). `handle_command` swallows it
   and the candidate's message vanishes. Use `interrupt(force=True)`. Do not
   copy livekit's `_default_text_input_cb`; it assumes every speech is
   interruptible.
8. **PTT orderings are load-bearing, not stylistic.** `ptt_end` must disable
   audio *then* commit: `commit_user_turn` only flushes silence into STT to
   force the final transcript when it sees `audio_detached`. `ptt_start` must
   enable audio *last*, because `clear_user_turn` restarts the STT stream.
9. **Mid-session open-mic↔PTT is broken, not merely unverified.**
   `AgentActivity.update_options` forwards a new `turn_detection` to
   `AudioRecognition` but never updates its own `_turn_detection`, which four
   barge-in paths read. Switching to manual leaves barge-in armed; switching
   away leaves it dead. Keep it out of v1 — and implement text mode with
   `set_audio_enabled`, never by switching `turn_detection`.
10. **`agent_state` has five values, not three.** `initializing`, `idle`,
    `listening`, `thinking`, `speaking` — and `initializing` is the first one
    the UI ever receives. Widen §3 and give the aria-live pill a default branch.
11. **Commands can arrive before `session.start()`.** The `data_received`
    handler is registered before the session starts, and every session method
    raises `RuntimeError("AgentSession isn't running")` until then. Do not let
    the UI enable the composer before the first `agent_state`.
12. **The agent already registers a `lk.chat` text-stream handler** that the
    pinned client can never reach. Either pass
    `RoomInputOptions(text_enabled=False)` so there is provably one text path,
    or adopt it deliberately — two implementations of one thing is what §1.3
    was about.

---

## 8. Scenario JSON schema — RESERVED for WT1

JSON, not YAML: `pyyaml` is not a dependency and a dev tool is not a reason to
add one (handoff §1.9). `config` keys are exactly `agent_mode.CONFIG_FIELDS` and
go through `normalize_config`; `script` is the ordered step list in handoff §3.
