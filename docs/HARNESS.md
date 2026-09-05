# The text harness

Drive a real interview as pure text — no browser, no LiveKit room, no
microphone. A developer or an AI agent can play the candidate across every
track, and a test can assert on what the interview actually did.

```bash
python -m harness run  scenarios/intro_happy_path.json
python -m harness play scenarios/intro_happy_path.json
```

`run` executes a scripted scenario and checks its expectations. `play` is a
REPL: you type as the candidate, and the slash commands map onto the same
handlers the browser's data channel reaches.

Both need `OPENAI_API_KEY` (from `.env` or the environment) until the cassette
tier below exists.

## What it is

It composes the production runtime; it does not reimplement it. The same
`InterviewAgent`, the same FSM state, the same `AgentSession`, built by the same
`build_interview_state` / `build_session` / `attach_handlers` that
`agent_worker.py` calls. The only substitutions are the ones that need
hardware:

| Production | Harness |
|---|---|
| Deepgram STT | none — you type instead |
| OpenAI TTS | none — `say()` works with no audio output attached |
| Silero VAD | none |
| `RoomTransport` (data channel) | `NullTransport` (a list you assert on) |
| `datetime.now` | `FakeClock`, advanced by the scenario |

That substitution list is the whole difference. If a test here passes, it
passed against the code that ships.

## Scenarios

JSON, not YAML — `pyyaml` is not a dependency of this project and a dev tool is
not a reason to add one.

```json
{
  "name": "intro — greeting through to a stage skip",
  "candidate_name": "Ada Lovelace",
  "config": {"track": "intro", "role": "Backend Engineer", "level": "mid"},
  "script": [
    {"say": "Hi! I'm Ada, a backend engineer."},
    {"expect": {"user_turns": 1}},
    {"command": {"type": "skip_stage", "target_stage": "past_experience"}},
    {"expect": {"stage": "past_experience"}},
    {"expect": {"emitted": "stage_change"}},
    {"clock": "+300"}
  ]
}
```

`config` keys must be in `agent_mode.CONFIG_FIELDS` — a test enforces this, so
a typo cannot quietly test a default. Expectations available today: `stage`,
`tool_called`, `emitted`, `user_turns`, `agent_said`.

## What this does NOT catch

Read this before deleting anything from the e2e suite. The harness removes
exactly the parts of the system that these depend on, so it can say nothing
about them:

- **Turn-taking.** VAD, endpointing, barge-in, interruption. There is no audio,
  so there are no turns to detect — `run()` hands the model a complete
  utterance every time.
- **STT.** Transcription errors, interim vs final timing, caption latency,
  Deepgram availability.
- **TTS and the audio cache.** Whether the welcome audio exists, plays, or is
  the right voice. The harness logs a cache miss and moves on.
- **LiveKit.** Connection, tokens, the data channel actually delivering,
  reconnects, the room lifecycle.
- **Worker and dispatch lifecycle.** Subprocess spawn, `worker_manager`,
  resident-worker job handling, process exit.
- **Persistence.** Nothing is written to Neon. `interview_row()` shows you the
  row that *would* be saved.
- **Real time.** The clock is fake, so every race that depends on wall-clock
  ordering is absent by construction.
- **The frontend.** Everything in `interview.html`.

## Known gaps

- **No cassette tier.** Handoff §3 specifies a recorded-response LLM so CI can
  run scenarios with no API key. Until it exists, `pytest -q` covers the
  scenario format and the checker, not a scenario run.
- **The fallback timer is not started**, so `{"clock": "+600"}` ages a stage
  without ever forcing the timeout transition. The model may still react to the
  time it is told about, which is what the technical_voice scenario shows.
- **No `harness verdict`** subcommand yet — the recorded transcript is not run
  through `speech_analytics` and the evaluator.

## What it found on its first real run

- Typed turns reach the transcript. This is the deviation from handoff §1.4
  that had only been argued from reading livekit-agents; it is now observed.
- The **behavioral track never calls `generate_interview_questions`**. It
  improvises instead, so the framework competencies and any custom questions
  the user configured are silently not generated — `generated_questions` stays
  `[]`. The technical_voice track, through the same code path, calls it every
  time.
