# Handoff: text harness · skip-question · input modes

Pick up here. Three workstreams, designed to run in parallel git worktrees after
one shared prerequisite lands. Each section marked **PROMPT** is paste-able as an
agent's opening instruction. **§8 records decisions that are already locked —
read it before running any PROMPT; several prompts below were narrowed by it.**

Written 2026-09-05. Architecture proposal by a Fable review agent; the corrections
in §1 were verified against the code and one was reproduced empirically.

---

## 0. The goal, in one line each

1. **Text harness** — drive the real interview agent as pure text, no browser, no
   LiveKit room, no mic. So a developer *or an AI agent* can play the candidate,
   across every track/role/level/resume configuration, and test architecture
   without a frontend.
2. **Skip the question** — literally: whenever the agent asks a question, the
   candidate can skip it. **Every track, every question, no exceptions.** Build
   and test in the harness first, then wire into the live voice webapp.
3. **Input modes** — let real users choose to **type**, **push-to-talk**, or
   **open-mic** (today's behavior), to industry/accessibility standard.

---

## 1. Verified corrections — read before planning

These were found while scoping. Several contradict what the code's own comments
and docs claim. **Verify each yourself before acting**; they are cited, not
assumed.

### 1.1 `avg_words_per_minute` was a fabricated constant — ✅ FIXED ON MAIN

**Resolved 2026-09-05** by `fix/delivery-metrics-honest` (`bc1b34a`, `d106ea4`,
merged `d11801f`). `speech_analytics` now carries `pace_available`, real per-turn
`duration_s` captured in `agent_worker.py`, and `filler_per_100_words` in place of
the per-minute rate that divided by the fake duration. **WS3 no longer has to fix
this** — build on `pace_available`, do not re-derive it. The original finding is
kept below because §5 and risk #2 still depend on understanding it.

`speech_analytics.py:122-142` estimates each turn's duration as
`words / 150 * 60`, then `_calc_wpm` divides words by that duration. Algebraically
that is exactly 150 for any turn over ~2 words. Reproduced across random
transcripts of 2–40 turns:

```
  2 turns -> avg_wpm=150.0      25 turns -> avg_wpm=150.0
  5 turns -> avg_wpm=150.0      40 turns -> avg_wpm=150.0
  distinct per-turn wpm values: {150.0}
```

`_per_turn_pace` (`:150-157`) is 150.0 for every turn by the same construction,
and `longest_monologue_s` (`speech_analytics.py:52-54`) is `words/150*60` — a
rescaled word count, not a duration.

**Why this is serious:** `docs/EPIC_wingD_feedback_moat.md` makes it a
NON-NEGOTIABLE that countable delivery metrics are computed in code and injected,
precisely so nothing invents them. Here the *code* invents this one, and the
feedback UI presents it as measured. `filler_*` and `talk_ratio` are real.

This was pre-existing, not caused by any current branch — and it is now fixed
on `main` (see the banner above). What WS3 still owes is the *typed*-session case:
a session with no voice turns must report `available: false, reason: "typed"`,
never a zero.

### 1.2 `POST /api/skip-stage` does not skip anything

`app.py:1594` validates the stage name and returns `success: true`. The actual
skip is a LiveKit **data-channel** message `{"type":"skip_stage"}` handled inside
`agent_worker.py`. There is no HTTP path to a running agent — every mid-session
command goes over `publishData`. Do not add a second HTTP path for skip.

### 1.3 Two coding-skip implementations, one bypasses the FSM

The `@function_tool skip_coding_problem` (`agent_worker.py:763`) records the skip
and asks the model to transition. The data-channel handler sets the stage
**directly**, bypassing `transition_to` — so no `skipped_stages` record and no
instruction refresh. Unify these under the new skip contract.

### 1.4 Typed turns would be invisible to the transcript

User turns are captured only from the `user_input_transcribed` event. Text input
emits `conversation_item_added(role="user")` instead. Without a fix, a typed
answer never reaches the saved transcript **or the verdict**. WS1/WS3 must record
user turns from `conversation_item_added` and use `user_input_transcribed` only
for interim captions.

### 1.5 `agent_worker.py` calls `sys.exit(1)` at import time

Module-level env validation plus plugin imports mean the file cannot be imported
by a test or harness without full env. This is the single biggest blocker to WS1
and is why **WT0 exists**. Refactor it; do not paper over it with env stubs.

### 1.6 The behavioral skip dropdown can't reach Q2/Q3

`templates/interview.html` lists only `greeting, self_intro, behavioral_q1,
closing` for the behavioral track, though `can_skip_to` permits Q2/Q3.

### 1.7 Two tools bypass the session LLM

`generate_interview_questions` and `evaluate_code_submission` construct their own
OpenAI client directly. Any harness must mock them or CI will burn API keys.

### 1.8 Base-branch decision — ✅ RESOLVED, unblocked

**`agent_mode.py` is on `main`** as of `86e4fb8`, landed with both bug fixes so no
branch inherits the `" true"` divergence or the coding-track crash. It is pure and
stdlib-only, nothing imports it yet, and `preferred_language`/`problem_count` are
**already folded into `CONFIG_FIELDS`** — so WT0 no longer has to move them, only
to make `agent_worker.py` actually call `normalize_config` instead of its inline
parser. `feat/livekit-dispatch-mode` has `main` merged into it and stays separate.
**Branch every worktree from `main`.** Original note below, for context.

`agent_mode.py` — the single config parser both transports share — lives on
`feat/livekit-dispatch-mode` (commit `f9f669f`), **not on `main`**. Every
worktree below needs it. **Decide first:** merge that branch to `main`, or branch
all worktrees from it. An adversarial review of that branch is in flight; prefer
to resolve its findings before merging.

### 1.9 `pyyaml` is not a dependency

Verified: not in `requirements.txt` or `requirements-dev.txt`. Use **JSON** for
scenario files rather than adding a dependency for a dev tool.

---

## 2. WT0 — the prerequisite (must land before anything else)

**Nothing else can start.** `agent_worker.py` fuses room lifecycle, config,
state, plugins, session, command dispatch, and finalize into one ~600-line
function that cannot be imported without LiveKit env.

### PROMPT — worktree `refactor/interview-runtime`

> You are refactoring `E:\MockFlow-AI` to make the interview agent testable
> without LiveKit. **Behavior must not change** — this is a pure extraction.
>
> Read `docs/HANDOFF_harness_skip_inputmodes.md` first, especially §1.
>
> Extract from `agent_worker.py` into a new `interview_runtime.py`:
> - `InterviewAgent` (moved verbatim), except every
>   `room.local_participant.publish_data(...)` goes through `self.transport.emit(dict)`.
> - A `Transport` protocol with `RoomTransport(room)` (publishes JSON as today)
>   and `NullTransport()` (appends to a list for assertions).
> - `build_interview_state(config) -> InterviewState` — the per-track state init.
>   `agent_mode.CONFIG_FIELDS` already covers `preferred_language` and
>   `problem_count` (§1.8), so do NOT re-fold them. What is missing is the call:
>   `agent_worker.py` does not import `agent_mode` at all today and still parses
>   participant attributes inline inside `run_interview`. Replace that inline
>   parser with `agent_mode.normalize_config(...)` and keep
>   `tests/test_config_equivalence.py` green — it is the proof the swap is inert.
> - `build_session(state, agent, *, llm, stt=None, tts=None, vad=None, turn_detection=NOT_GIVEN)`.
> - `attach_handlers(...)` — the transcript/caption event closures. **Apply the
>   §1.4 fix**: record user turns from `conversation_item_added(role=="user")`;
>   use `user_input_transcribed` only for interim captions.
> - `handle_command(payload, ctx)` — replace the `on_data_received` if/elif chain
>   with a dict registry `COMMANDS = {"skip_intro":…, "skip_stage":…, …}`, one
>   small function each, so later worktrees add commands without colliding.
> - `collect_interview_data(...)` — deduplicate the two drifting copies of the
>   finalize dict.
>
> Also: move env validation out of module scope into `agent_worker.main()` so the
> module imports cleanly (§1.5). Give `InterviewState` an injectable clock
> (`_now: Callable[[], datetime]`, default `datetime.now`) so a harness can
> advance time. Move the fallback timer too, parameterised on that clock.
>
> `agent_worker.py` keeps: env validation, token/room connect, participant wait,
> then calls the new builders. The dispatch entrypoint must be untouched.
>
> **Acceptance:** the direct-mode diff is mechanical; `python -m pytest -q` and
> `ruff check .` pass; `import interview_runtime` works with NO env set; and you
> have run a real end-to-end interview per track before declaring done (this
> touches the only production path — see `docs/TESTING_E2E.md`).
>
> Commit to the worktree branch. Do not open a PR. Do NOT add Claude/AI as
> commit author or co-author.

---

## 3. WS1 — text harness

**Approach (decided):** drive the **real** `AgentSession` via livekit-agents'
own eval facility, with voice I/O swapped out — not a reimplementation.

Key facts verified in the installed `livekit-agents` 1.3.6:
- `AgentSession.run(user_input=…) -> RunResult` uses the same `generate_reply`
  path as real text input, and records every message / function-call event.
- `session.start(agent, capture_run=True)` with **no room** runs in eval mode.
- `mock_tools(AgentClass, {...})` exists — use it for the two direct-OpenAI tools (§1.7).
- `session.say()` works with **no TTS** as long as no audio output is attached —
  so the cached-welcome and skip-acknowledgement paths execute for real.
- `RunResult.expect` gives `is_function_call(name=…)`, `is_message(role=…)`, and
  an LLM-as-judge `judge(intent=…)` for wording assertions.

**Rejected:** fake STT/TTS plugins (same fidelity, more code, and would falsely
imply turn-taking is covered); a full "interview core" rewrite (the FSM, prompts
and tools are *already* transport-agnostic — only `run_interview` needs cutting);
livekit's console mode (interactive-only, not scriptable).

**Determinism, three tiers:**
1. **Hermetic CI (default, no API keys):** a cassette LLM replays recorded
   assistant turns as chunks/tool-calls. Tools execute **for real** against the
   real FSM. Assert FSM state, which tools were called with what args, emitted
   transport events, and the shape of `collect_interview_data`.
2. **Live tier** (`@pytest.mark.live`, skipped without `OPENAI_API_KEY`): real
   model, assert structure + `judge()` for wording. Expect flake; allow retries.
   **Run manually before a merge — not nightly in CI (§8.8).**
3. **Interactive `play`** — a human or an AI agent types as the candidate.

**Explicitly NOT covered** (document this so nobody retires the e2e suite): VAD /
endpointing / barge-in, STT errors and caption timing, TTS and audio cache,
LiveKit connection and token issues, worker/dispatch lifecycle, DB persistence,
real wall-clock races, and anything in `interview.html`.

### PROMPT — worktree `feat/text-harness`

> Build a text-only harness for the interview agent in `E:\MockFlow-AI`.
> Read `docs/HANDOFF_harness_skip_inputmodes.md` §1 and §3 first. Depends on
> WT0 (`interview_runtime.py`) — confirm it is merged before starting.
>
> Deliver a `harness/` package:
> - `python -m harness run scenarios/<name>.json [--llm cassette|openai] [--record out.jsonl]`
> - `python -m harness play scenarios/<name>.json` — interactive REPL; you type as
>   the candidate. Slash commands `/skip`, `/skip-stage <name>`, `/clock +120`,
>   `/state` map onto `handle_command` and the injectable clock.
> - `python -m harness verdict out.jsonl` — run the recorded transcript through
>   `speech_analytics` + `evaluator` so a developer can see the verdict a scripted
>   session produces.
>
> **Scenario format: JSON** (`pyyaml` is not a dependency — §1.9). Two sections:
> `config` (keys = `agent_mode.CONFIG_FIELDS`, passed through `normalize_config`)
> and `script`, an ordered list of steps: `{"say": "..."}`,
> `{"command": {"type": "skip_question"}}`, `{"clock": "+300"}`,
> `{"expect": {"stage": "behavioral_q2"}}`, `{"expect": {"tool_called": "transition_stage"}}`,
> `{"expect": {"emitted": "stage_change"}}`, `{"expect": {"judge": "acknowledges the skip"}}`.
>
> Use `AgentSession.run()` + `RunResult.expect` + `mock_tools` (mock the two
> direct-OpenAI tools by default — §1.7). Ship scenarios covering **every track**
> (intro, behavioral, technical_voice, technical_coding) × resume present/absent ×
> custom questions/topics present/absent.
>
> Note: the session finalizes on a closing keyword in the assistant text — your
> cassettes must include such a line or the session never ends. Assert no audio
> output is attached, or `say()` starts raising.
>
> Write `docs/HARNESS.md` including an explicit "what this does NOT catch" list
> (see §3). Keep the default path hermetic — `pytest -q` must pass with no API
> keys. Commit to the worktree branch, no PR. Do NOT add Claude/AI as commit
> author or co-author.

---

## 4. WS2 — skip the question (**universal**)

**The requirement, plainly:** whenever the agent asks a question, the candidate
can skip it. Every track. Every question. No track is exempt, and there is no
question type where the button is absent.

Per-track mapping of what "next question" resolves to (the tracks differ
structurally, so the *implementation* differs even though the *affordance* is
uniform):

| Track | Structure | Skip resolves to |
|---|---|---|
| behavioral | one generated question per stage (Q1/Q2/Q3) | advance to the next behavioral stage via `transition_to(skipped=True)` |
| technical_voice | 2–3 questions per topic stage | next question in the topic; if exhausted, next stage |
| intro (`self_intro`/`past_experience`/`company_fit`) | free-form, N per stage | ask a *different* question; no follow-ups on the skipped one |
| coding | one problem per stage | existing `skip_coding_problem`, unified through `transition_to` (§1.3) |

**FSM contract** (in `fsm.py`, on the base class so every track inherits):
```
skipped_questions: List[dict]
  # {"stage", "index", "question", "source": "button"|"voice"|"stage_skip", "at"}
def skip_current_question(self, source) -> SkipOutcome   # NEXT_IN_STAGE | NEXT_STAGE | NOTHING_TO_SKIP
def current_question_text(self) -> str | None
```
`transition_to(..., skipped=True)` also appends the in-flight question with
`source="stage_skip"`, so a stage skip and a question skip produce the same
record type. That is the unification with the existing skip-stage feature.

**Minimum-questions interaction:** a skipped question still **counts as asked**,
so skipping can never trap a candidate in a stage whose minimum becomes
unreachable — but the record marks it unanswered.

**Verdict protection (moat-critical).** A skipped question must never be scored:
1. Persist `skipped_questions` in `collect_interview_data` and the DB row —
   **a new JSONB column + migration** (§8.4), not folded into an existing blob.
2. Render it in the judge's transcript as `CANDIDATE: [SKIPPED — no answer given]`
   and pass a `<SKIPPED_QUESTIONS>` block to the evaluator.
3. Add an evaluator rule: *a skipped question is not evidence; never quote the
   skip request itself as evidence.*
4. **Deterministic backstop** in `finalize_verdict`: if every evidence quote for a
   signal is a substring of a skip utterance, force `cannot_determine`. This makes
   the rule testable without an LLM.
5. Surface "N questions skipped" beside the verdict confidence, so a
   lower-confidence read is explained rather than mysterious.

### PROMPT — worktree `feat/skip-question-core`

> Implement universal skip-the-question in `E:\MockFlow-AI`. Read
> `docs/HANDOFF_harness_skip_inputmodes.md` §1 and §4. Depends on WT0; use the
> harness (WS1) to test if it has landed, otherwise write unit tests against the
> FSM directly.
>
> **Requirement: every track, every question — no exceptions.**
>
> 1. `fsm.py`: add `skipped_questions`, `skip_current_question(source)`,
>    `current_question_text()`, and make `transition_to(skipped=True)` record the
>    in-flight question. Base class, so all tracks inherit.
> 2. `interview_runtime.py`: add ONLY `COMMANDS["skip_question"]`, and unify the
>    coding data-channel skip to go through `transition_to` (§1.3). Touch no other
>    command — other worktrees own those files' other lines.
> 3. `prompts.py`: add `SKIP_QUESTION_ACKS` (deterministic ack text per track) and
>    the tool description. After a skip: say the ack, then immediately generate the
>    next question — do not leave the model to infer what happened.
> 4. **Button only in v1 (§8.3).** The single initiation is the data-channel
>    `{"type":"skip_question"}`. Do NOT add a `skip_question` function_tool — voice
>    skip is a deliberate follow-up ticket. Still give `skip_current_question` its
>    `source` argument so voice drops in later without touching the FSM.
> 5. Emit `{"type":"question_skipped","stage","outcome","skipped_count"}`.
>
> Do NOT change the evaluator or the UI — those are separate worktrees consuming
> the `skipped_questions` contract above. Tests + ruff green. Commit to the
> worktree branch, no PR. Do NOT add Claude/AI as commit author or co-author.

**Sibling worktrees** (parallel, contract-only dependency):
- `feat/skip-question-verdict` — owns `evaluator.py` (rules + `<SKIPPED_QUESTIONS>`
  + the deterministic scrub), `app.py` transcript rendering, `db.py`/migration,
  and the feedback "N skipped" display.
- `feat/skip-question-ui` — owns the skip button + `S` key + aria in
  `templates/interview.html`. Also fix §1.6 while there.

---

## 5. WS3 — input modes (type / push-to-talk / open mic)

**Standards, not preference.** W3C's *Natural Language Interface Accessibility
User Requirements* requires a text alternative to speech and user control over
turn-taking; speech-only excludes deaf, non-verbal and speech-impaired users, and
anyone in a shared space. WCAG 2.2 that applies: **2.1.1 Keyboard** (every
function operable by keyboard), **2.2.1 / 2.2.6 Timing** (typing is slower than
speaking — stage timers need a text multiplier), **2.5.2 Pointer Cancellation**
(press-and-hold PTT is the canonical essential-down-event exception, but ship a
latched toggle too for users who cannot hold a key), **2.5.8 Target Size**, and
**4.1.3 Status Messages** (announce Listening/Thinking/Speaking via `aria-live`).
Industry pattern (ChatGPT Voice, Gemini Live, LiveKit's own starter apps): open
mic + VAD + tap-to-interrupt, **with a text composer always present**; hold-Space
is the established PTT convention.

**Per mode, server-side:**
- *Open mic* — today's config, unchanged.
- *PTT* — `turn_detection="manual"`; commands `ptt_start` (interrupt, clear turn,
  enable audio) / `ptt_end` (disable audio, commit turn) / `ptt_cancel`. The
  client also gates the mic track so no audio leaves the browser between presses.
  Latency is *better* than open-mic: release ends the turn, no endpointing wait.
- *Text* — `user_text` command → interrupt + `generate_reply(user_input=…)`, and
  disable audio input so background noise cannot trigger a turn.

**Transport:** the frontend pins `livekit-client@2.5.0`, which predates text
streams and RPC. **Use `publishData` for everything in v1**; bumping the client is
a separate ticket. Anything else fails silently at runtime.

**Delivery metrics when the candidate types — this is the moat-critical part:**
- §1.1 is **already fixed on `main`** — real per-turn `duration_s` and
  `pace_available` exist. Do not redo it. What is left: tag every turn
  `mode: "voice"|"text"` and thread that tag through.
- Compute pace/fillers/monologue over **voice turns only**.
- When a session is typed (or has too few voice turns), delivery returns
  `{"available": false, "reason": "typed"}` and the UI renders "not measured —
  typed session".
- **Never write `filler_total: 0` or `wpm: 150` for a typed session.** A zero is a
  fabricated measurement, which is precisely what the moat forbids.

### PROMPT — worktree `feat/input-modes-agent`

> Add text / push-to-talk / open-mic input modes to `E:\MockFlow-AI`. Read
> `docs/HANDOFF_harness_skip_inputmodes.md` §1 and §5. Depends on WT0.
>
> Own ONLY the agent side in `interview_runtime.py`: `COMMANDS` entries for
> `set_input_mode`, `ptt_start`/`ptt_end`/`ptt_cancel`, and `user_text`; the
> `turn_detection` parameter on `build_session`; per-turn `mode` and real
> `duration_s` tagging; and forwarding agent/user state as
> `{"type":"agent_state","state":…}` for the UI's aria-live pill.
>
> Apply §1.4 (typed turns must reach the transcript) and emit `user_caption` for
> typed turns too. Use `publishData` — the pinned `livekit-client@2.5.0` has no
> text streams or RPC.
>
> v1 scope: PTT is selected before joining. Mid-session open-mic↔PTT switching is
> OUT (it needs a live `turn_detection` change that is unverified) — text↔voice
> switching is IN. Add harness scenarios for text mode.
>
> Do not touch `speech_analytics.py`/`feedback_scoring.py` (sibling worktree) or
> the templates. Tests + ruff green. Commit to the worktree branch, no PR. Do NOT
> add Claude/AI as commit author or co-author.

**Sibling worktrees** (parallel):
- `feat/input-modes-metrics` — owns `speech_analytics.py`, `feedback_scoring.py`,
  `insights.py` and the feedback delivery panel. **Scope is now much smaller:**
  §1.1 and the historical-rows display both shipped in `fix/delivery-metrics-honest`.
  What remains is only the typed-session path — exclude `mode == "text"` turns from
  pace, and return `available: false, reason: "typed"` when a session has too few
  voice turns to measure. Read `tests/test_delivery_honesty.py` before touching
  anything; it already pins the honesty rules.
- `feat/input-modes-ui` — owns `templates/form.html` (mode picker),
  `templates/interview.html` (segmented control, composer, PTT, aria-live pill),
  and the participant attribute in `app.py`.

---

## 6. Worktree map and sequencing

```
WT0 refactor/interview-runtime      <- lands FIRST, alone
     |
     +-- WT1 feat/text-harness           harness/, scenarios/, docs/HARNESS.md
     +-- WT2 feat/skip-question-core     fsm.py, prompts.py, runtime skip cmd
     +-- WT3 feat/skip-question-verdict  evaluator.py, app.py, db.py, feedback.html
     +-- WT4 feat/skip-question-ui       interview.html (skip button)
     +-- WT5 feat/input-modes-agent      runtime input cmds, build_session
     +-- WT6 feat/input-modes-metrics    speech_analytics, feedback_scoring, insights
     +-- WT7 feat/input-modes-ui         form.html, interview.html (modes)
```

Merge order: **WT0** → WT1, WT2, WT3, WT4 (skip complete; run harness scenarios +
a live interview) → WT5, WT6, WT7 (input modes complete; live smoke in all three
modes).

**File-collision warnings.** `interview.html` is touched by WT4 and WT7 — merge
WT4 first and let WT7 rebase. `evaluator.py` is touched by WT3 and WT6 — WT3 owns
the system-prompt rules, WT6 owns the delivery-summary text. `interview_runtime.py`
is touched by WT2 and WT5 — they add *different* `COMMANDS` entries, which is why
that dispatch is a dict registry rather than an if/elif chain.

**Contracts to freeze in WT0 before fan-out:**
1. `interview_runtime` public surface and the `COMMANDS` handler signature.
2. Client→agent payloads: `skip_question`, `set_input_mode`, `ptt_start|end|cancel`, `user_text`.
3. Agent→client events: `question_skipped`, `agent_state`, `input_mode`, plus existing `stage_change`/`user_caption`.
4. Per-turn transcript record: `{index, text, timestamp, stage, mode, duration_s}`.
5. `skipped_questions` record shape and storage location.
6. Delivery block: `{available: bool, reason: str|null, ...}`.
7. Scenario JSON schema.

---

## 7. Risks, ranked

1. **Verdict scores what was never answered, or fabricates delivery.** Skips
   without the transcript marker + rule + scrub, or a typed session written with
   `filler_total: 0`, silently corrupts the moat. Gate merges on evaluator tests.
2. ~~**§1.1 fix changes historical comparability.**~~ — discharged: shipped in
   `fix/delivery-metrics-honest`, old rows read "not measured". Retained so the
   next person understands why `pace_available` exists.
3. **WT0 regressing the live flow** — it touches the only production path. Require
   a real interview per track before merge.
4. ~~**Voice-skip false positives**~~ — not a v1 risk: voice skip is deferred
   (§8.3), so there is no tool for the model to misfire on. Re-read this before
   adding the function_tool later; the negative case ("I'd skip caching there")
   needs a live-tier scenario the day it ships.
5. **Cassette drift** — prompt edits change real-LLM behavior while cassettes keep
   passing. Cassettes are regression pins, not proof of prompt quality; run the
   live tier by hand before merging any prompt change (§8.8).
6. **`livekit-client@2.5.0`** — text streams / RPC will fail silently. Stay on
   `publishData`.
7. **Coding-skip unification changes coding-track behavior** — cover with a
   scenario before changing it.

---

## 8. Decisions — RESOLVED 2026-09-05

Locked with Pranav. **Do not reopen these in a worktree** — ask him instead.

| # | Question | Resolution |
|---|---|---|
| 1 | Base branch (§1.8) | **Done — branch from `main`.** `agent_mode.py` landed at `86e4fb8` with both bug fixes; `fix/delivery-metrics-honest` landed at `d11801f`. `feat/livekit-dispatch-mode` stays a separate branch with `main` merged into it. |
| 2 | Skip budget | **Unlimited.** No cap, no per-stage counter, no nudge copy. The verdict absorbs it — signals with no evidence become `cannot_determine`, and the feedback surfaces "N questions skipped" beside confidence. A candidate who skips everything gets an honest empty verdict, not a blocked session. |
| 3 | Voice-initiated skip | **Button only in v1.** WT2 ships no `skip_question` function_tool. Keeps the false-positive class (risk #4) out of production entirely. Voice skip is a follow-up ticket, unblocked once WT1 can test the negative case. |
| 4 | `skipped_questions` storage | **New JSONB column + migration.** Folding it into an existing JSON blob makes "which questions do candidates skip?" unqueryable, and that is moat telemetry. |
| 5 | Text-mode stage timer | **1.5×** the voice timer (WCAG 2.2.1 — typing is slower than speaking). |
| 6 | Historical delivery display | **"pace not measured (older session)".** Rows written before the §1.1 fix have no real duration. Never preserve the fake 150 — that is the fabrication §1.1 exists to remove. |
| 7 | `/api/skip-stage` (§1.2) | **Delete it**, after grepping for callers. A no-op that returns `success: true` is worse than a 404 — it will be trusted by the next person who finds it. |
| 8 | Live-tier budget | **No nightly live tier.** CI stays hermetic and key-free. `@pytest.mark.live` runs by hand before a merge, on whatever key is in the local env. Revisit if cassette drift (risk #5) actually bites. |
