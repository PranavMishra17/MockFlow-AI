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
) -> AgentSession: ...

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

Everything goes over `publishData`. The frontend pins `livekit-client@2.5.0`,
which predates text streams and RPC; those fail **silently** at runtime.

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
| `user_caption` / `agent_caption` | `text` | WT0 | LIVE |
| `coding_problem` | `problem`, `problem_index`, `attempt_number`, `max_attempts`, `time_limit_minutes` | WT0 | LIVE |
| `evaluation_result` | `evaluation`, `attempt`, `max_attempts`, `problem_index`, `objective_tests?` | WT0 | LIVE |
| `max_attempts_reached` | `problem_index` | WT0 | LIVE |
| `interview_saved` | `interview_id`, `message?` | WT0 | LIVE |
| `interview_ending` / `save_error` | `message` | WT0 | LIVE |
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

## 8. Scenario JSON schema — RESERVED for WT1

JSON, not YAML: `pyyaml` is not a dependency and a dev tool is not a reason to
add one (handoff §1.9). `config` keys are exactly `agent_mode.CONFIG_FIELDS` and
go through `normalize_config`; `script` is the ordered step list in handoff §3.
