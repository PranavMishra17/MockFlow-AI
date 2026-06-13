# MockFlow-AI — Architecture (current)

Single source of truth for the **current** stack. The older `MIGRATION_HISTORY.md`
and `SUPABASE_SCHEMA_HISTORY.md` files describe earlier states (Supabase, a
planned Xata move) and are kept only for history — do not follow them for setup.

## Stack

| Concern        | Technology |
|----------------|------------|
| Web app        | Flask 3 (`app.py`), served by gunicorn on Render free tier |
| Voice agent    | LiveKit Agents (`agent_worker.py`), one subprocess per interview via `worker_manager.py` |
| Database       | Neon Postgres (`db.py`, psycopg3 pool) |
| Auth           | Authlib Google OAuth + Flask-Login (`auth_helpers.py`) |
| STT / LLM / TTS | Deepgram (STT), OpenAI (LLM + TTS) — **BYOK**: each user supplies their own keys |
| Key storage    | Fernet-encrypted in Postgres (`ENCRYPTION_KEY`) |

There is **no MongoDB and no Supabase** in the running system. `supabase_client.py`
is a thin compatibility shim re-exporting `db.db_client` under the old name; the
live importer is `agent_worker.py` (migrating it off the shim is tracked work).

## Request flow

```
Browser (form)  ──POST /api/token──▶  Flask
                                      ├─ load user's encrypted keys from Neon
                                      ├─ worker_manager.spawn_worker()  ──▶ agent_worker.py subprocess
                                      └─ mint LiveKit JWT (user's keys) ──▶ returned to browser
Browser  ──join LiveKit room──▶  agent_worker (FSM-driven interview)
                                      └─ on end: save transcript to Neon
Browser (feedback) ──POST /api/feedback*──▶  Flask ──▶ OpenAI (user's key) ──▶ feedback
```

The interview state machine (`fsm.py`) is track-aware: `intro`, `behavioral`,
`technical_voice`, `technical_coding` (see `tracks/`).

## Environment variables

The app reads exactly these (see `env.template`):

- **Required:** `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SECRET_KEY`, `ENCRYPTION_KEY`
- **Optional:** `FLASK_ENV`, `CORS_ORIGINS`, `MAX_CONCURRENT_WORKERS`
- **Per-user (not env):** LiveKit / OpenAI / Deepgram keys — entered in the app, stored encrypted.
- **Worker subprocess only (injected by `worker_manager`):** `LIVEKIT_URL/API_KEY/API_SECRET`, `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `INTERVIEW_ROOM_NAME`.

## Local development

```bash
python -m venv .venv && .venv\Scripts\activate    # Windows (use source .venv/bin/activate on *nix)
pip install -r requirements-dev.txt
cp env.template .env                               # then fill in the 5 required vars
psql "$DATABASE_URL" -f migrations/001_initial_schema.sql
python app.py                                      # http://localhost:5000
```

Run the test suite and linter:

```bash
python -m pytest
python -m ruff check .
```

## Deployment (Render)

- **Start command:** `gunicorn app:app --workers 1 --timeout 120`
  (`--workers 1` is required: the BYOK model tracks agent subprocesses in one
  process's memory; multiple gunicorn workers would each see a different set.)
- **Python:** pinned via `runtime.txt` (`python-3.12.6`).
- **Health:** `GET /health` pings Neon and reports worker load.
- **Keep-warm:** `.github/workflows/keep-warm.yml` pings the app + Neon every ~14 days.
- Push to `main` runs CI (`.github/workflows/deploy.yml`: lint + tests) before Render auto-deploys.
