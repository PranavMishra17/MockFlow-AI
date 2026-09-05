# Agent transport: direct connection vs LiveKit dispatch

How the AI interviewer gets into a LiveKit room. There are two transports; the
interview itself is identical in both.

Selected by `AGENT_MODE` (`direct` — the default — or `dispatch`).

---

## The two transports

### `direct` (default, unchanged behavior)

```
POST /api/token
  -> worker_manager.spawn_worker()
  -> subprocess.Popen(["python", "agent_worker.py"])       # per interview
  -> agent_worker mints its own token, room.connect(LIVEKIT_URL)
  -> config read from the participant's LiveKit *attributes*
```

Self-contained: no agent registration, no LiveKit-side routing. The cost is that
every concurrent interview is a Silero/onnxruntime-loaded process on the web box,
and the set of live workers is an **in-process dict**, which is why the app
cannot run more than one machine.

### `dispatch` (LiveKit-native)

```
POST /api/token
  -> worker_manager.spawn_worker()
  -> AgentDispatchService.create_dispatch(room, agent_name, metadata)
  -> LiveKit routes the job to a RESIDENT worker
  -> agent_worker.dispatch_entrypoint(ctx); ctx.room already connected
  -> config read from job *metadata*, falling back to participant attributes
```

The resident worker is a separate process you run yourself:

```bash
AGENT_MODE=dispatch python agent_worker.py start
```

The web process no longer spawns anything for these interviews, so its memory
stops scaling with concurrency and the agents can be scaled independently.

`WorkerOptions(agent_name=...)` means **explicit** dispatch: LiveKit routes only
jobs created for that name, never every room in the project. That matters because
the same project also hosts rooms the app drives directly.

---

## The constraint that governs everything: BYOK

**A dispatch worker registers with exactly one LiveKit project.**

But this app is bring-your-own-keys. `resolve_interview_keys()` hands an
interview either the user's own LiveKit credentials or the owner's `SYSTEM_*`
ones. A worker registered against the owner's project **cannot** receive a job
for a room that lives inside some user's project — that room is not visible to
it. The dispatch API call would succeed and the candidate would sit staring at a
"connecting" card until the join timeout.

So `worker_manager` guards every dispatch with `agent_mode.can_dispatch()`, which
compares the interview's LiveKit URL + key + secret against the resident worker's.
When they differ, it **falls back to a direct spawn**.

| Interview funded by | Transport in `AGENT_MODE=dispatch` |
|---|---|
| Owner `SYSTEM_*` keys (free tier) | dispatch → resident worker |
| User's own BYOK LiveKit keys | **direct spawn** (fallback) |

**Consequence:** dispatch mode does not remove the need for the web box to spawn
subprocesses, and does not by itself unlock horizontal scaling. It only removes
that load for system-key interviews. Fully removing it requires either dropping
BYOK for LiveKit specifically, or running a worker per user project (which is
strictly worse than the current direct spawn).

This is a property of BYOK, not a defect in the implementation.

---

## Why the webapp behaves the same

The two transports deliver interview config by different means — participant
attributes (strings) in direct mode, JSON job metadata in dispatch mode. If those
parsed differently, interviews would subtly diverge.

They cannot, because both funnel through the single parser
`agent_mode.normalize_config()`. Its defaults and list-splitting rules are
transcribed from the inline parser that previously lived in
`run_interview()`, and the transcription was verified differentially against the
original across **10,242 attribute combinations with zero mismatches** (plus the
no-attributes case). `tests/test_agent_mode.py` pins the same contract, including
a direct assertion that attributes and metadata yield an identical config.

Because the web client already publishes config as participant attributes in both
modes, dispatch works **with no config plumbing at all** — metadata is an optional
enhancement that wins field-by-field where present.

---

## What changed in `agent_worker.py`

`run_interview()` gained three optional parameters and kept its body:

| | direct (`room=None`) | dispatch (`room` supplied) |
|---|---|---|
| Room | mints a token, `room.connect()` | `ctx.room`, already connected |
| HTTP session | creates + closes its own | owned by the job context |
| Config | participant attributes | job metadata, attributes as fallback |
| On finish | `sys.exit(0)` | **returns** — the worker is resident |

The last row is the one that bites: a resident worker that called `sys.exit(0)`
would take the whole agent pool down after a single interview. Same for closing
the framework's HTTP session or disconnecting its room — all three are now gated
on `owns_room` / `owns_http_session`.

---

## Operating it

Run the resident worker alongside the web process:

```bash
AGENT_MODE=dispatch python agent_worker.py start
```

Both processes need `AGENT_MODE=dispatch` — the web process to create dispatches
instead of spawning, the worker to register instead of connecting to one room.
A misspelled `AGENT_MODE` raises at import, so the process refuses to start
rather than silently serving traffic on the other transport.

### Verifying

- Worker log on start: `Starting agent worker - DISPATCH MODE (agent_name=...)`
- Web log per interview: `Dispatch created (id: ...) for room: ...`
- A BYOK interview instead logs: `falling back to a direct spawn`
- `/health` counts both transports (`worker_manager.total_active_count()`)

### If the candidate never hears an agent

`create_dispatch` succeeding only means LiveKit accepted the job. If **no** worker
is registered under that `agent_name`, the job is queued and nothing joins. Check
that the resident worker is running, that its `AGENT_NAME` matches the web
process's, and that both point at the same LiveKit project.

---

## Status

Implemented and unit-tested; **not yet exercised against a live LiveKit
project.** The dispatch path's LiveKit calls are stubbed in tests, so
`create_dispatch` wiring, job routing, and the resident worker's job lifecycle
still need a real end-to-end run before this is trusted in production.
