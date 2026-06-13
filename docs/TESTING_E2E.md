# End-to-End Testing Guide

How to stand up MockFlow-AI locally and exercise a **complete** interview — from Google sign-in, through a live voice (and coding) session, to the scored feedback report. This is the manual counterpart to the automated `pytest` + Playwright smoke suite.

There are two levels of "end-to-end":

| Level | What it proves | Needs working voice keys? |
|---|---|---|
| **A. App E2E** | Sign-in, DB, forms, dashboard, feedback rendering, exports | No |
| **B. Full interview E2E** | A real spoken interview: STT → LLM → TTS over LiveKit, live coding, transcript + feedback generation | **Yes** — LiveKit + OpenAI + Deepgram |

Do **A** first (cheap, no paid keys). Do **B** once you have working BYOK keys.

---

## 1. Prerequisites

### 1.1 Tooling
- **Python 3.12** (pinned in `runtime.txt`)
- `pip install -r requirements-dev.txt` (dev set includes pytest, ruff, Playwright)
- A modern Chromium/Chrome/Edge browser that can grant **microphone** access (required for the voice pipeline)

### 1.2 A Neon Postgres database
- Create a project at [neon.tech](https://neon.tech) and grab the **pooled** connection string → this is `DATABASE_URL`.
- Run the schema migrations:
  ```bash
  psql "$DATABASE_URL" -f migrations/001_initial_schema.sql
  psql "$DATABASE_URL" -f migrations/002_free_tier_and_stats.sql
  ```
  (`add_livekit_keys_migration.sql` is an older historical migration already folded into `001`; you don't need to run it on a fresh DB.)

### 1.3 A Google OAuth client — **register the local callback**
This is the single most common reason local sign-in fails after the Supabase → Google OAuth migration. In **Google Cloud Console → APIs & Services → Credentials → your OAuth 2.0 Client ID**:

- **Authorized redirect URIs** → add exactly:
  ```
  http://localhost:5000/auth/google/callback
  ```
- **Authorized JavaScript origins** → add:
  ```
  http://localhost:5000
  ```
- If you open the app at `127.0.0.1:5000` instead of `localhost`, add those two `127.0.0.1` variants too — Google treats them as different origins.
- Save and wait ~1 minute to propagate.

> Symptom if this is missing: Google shows **"Error 400: redirect_uri_mismatch"** and never returns to the app.

### 1.4 Environment file
```bash
cp env.template .env
```
Fill the **five required** vars:

| Var | Where from |
|---|---|
| `DATABASE_URL` | Neon pooled connection string |
| `GOOGLE_CLIENT_ID` | Google OAuth client |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client (the app also accepts `GOOGLE_CLOUD_CLIENT_SECRET`) |
| `SECRET_KEY` | any long random string (`python -c "import secrets;print(secrets.token_hex(32))"`) |
| `ENCRYPTION_KEY` | a Fernet key (`python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`) |

Leave `FLASK_ENV` unset (or `development`) for local — `production` turns on **Secure** cookies, which the browser drops over plain `http://localhost`, so sign-in won't stick.

### 1.5 BYOK voice keys — needed only for Level B
MockFlow is **Bring-Your-Own-Keys**: these are **not** in `.env`; you add them in the UI after signing in. For a full interview you need working:
- **LiveKit** — URL + API key + API secret → [cloud.livekit.io](https://cloud.livekit.io)
- **OpenAI** — API key (LLM + TTS) → [platform.openai.com](https://platform.openai.com)
- **Deepgram** — API key (STT) → [console.deepgram.com](https://console.deepgram.com)

> If your old keys are stale, Level-B tests will fail at "begin interview" or with silent audio. Refresh them first.

---

## 2. Start the app

```bash
python app.py          # serves http://localhost:5000 (Flask dev server, single process)
```

Sanity checks before touching the browser:
```bash
curl -s http://localhost:5000/health          # pings Neon + reports worker load
curl -s http://localhost:5000/api/auth/status # {"authenticated": false} when logged out
```

---

## 3. Level A — App E2E (no paid keys)

Walk this in the browser:

1. **Sign in** — landing page → *Log In* → Google → you land on `/dashboard`.
   - ✅ `/api/auth/status` now returns your profile; header shows your account.
   - ✅ A `users` row exists in Neon (first login creates it).
2. **Settings / API keys** — open `/api-keys`.
   - ✅ Page loads; copy still says **Neon**, not Supabase (known minor copy cleanup pending).
   - Add your BYOK keys; click **Validate** (`/api/user/keys/validate`) — should report which keys are valid.
3. **Start form** — `/start`.
   - ✅ Name + role **cache** to `localStorage` (`mockflow_form_v1`): type them, reload, they persist.
   - ✅ Track cards: selecting one lights it up and greys the others; no focus-outline pop-up.
   - ✅ Resume upload shows the green success state + filename + a toast.
4. **Dashboard / past calls / feedback render** — confirm the "Interview Personality" widget, past-calls list, and a feedback report page (`/feedback/<id>`) all render (use seed/existing data if you have none yet).
5. **Sign out** — `/auth/logout` → you're logged out and stay logged out on refresh (remember-cookie cleared).

**Automated Level-A coverage** — run these any time:
```bash
python -m pytest                      # unit + integration suite (hermetic; stubs the DB pool)
python -m ruff check .                # lint
python tests/e2e/smoke_server.py &    # synthetic server (stubs DB) on :5099
python tests/e2e/run_smoke.py         # Playwright: every page in Chromium, console-error + screenshot
```

---

## 4. Level B — Full interview E2E (needs working voice keys)

1. Sign in, add **valid** LiveKit + OpenAI + Deepgram keys in Settings, Validate them.
2. `/start` → pick **Intro** (simplest path), fill name/role, **Begin Interview**.
   - Backend: `POST /api/token` loads your encrypted keys, `worker_manager` spawns an `agent_worker.py` subprocess, and mints a LiveKit JWT.
   - ✅ Watch the server log for the worker spawn; the cold-start panel should resolve to "Agent ready".
3. **Grant microphone** access when the browser asks. Join the room.
   - ✅ The orb animates; the interviewer **greets you out loud** (TTS).
   - ✅ Speak — your words are transcribed (Deepgram STT) and the agent asks adaptive follow-ups (OpenAI LLM).
   - ✅ FSM advances through stages; the skip control moves you forward.
4. **Coding track** (separate run): pick **Coding**.
   - ✅ Monaco editor loads with a problem from the vetted bank.
   - ✅ (Optional) set `PISTON_ENABLED=true` to have submissions actually executed — feedback is then grounded in real pass/fail rather than an LLM guess.
5. **End the interview.**
   - ✅ Transcript is persisted to Neon (`/api/interview/save`).
   - ✅ Feedback is generated (`/api/feedback/save` → OpenAI with your key) and the report renders at `/feedback/<id>` with scores + speech analytics.
   - ✅ **Export to PDF** and **Copy as Markdown** both work.

### What commonly breaks in Level B
- **No audio / silent agent** → bad OpenAI TTS key, or browser mic permission denied.
- **"Begin" hangs / worker won't spawn** → invalid LiveKit creds, or `MAX_CONCURRENT_WORKERS` reached.
- **Cold start** → first request after idle is slow; the progress panel covers this.
- **Single worker** → the app runs **one** process on purpose (agent subprocesses live in its memory). Don't run multiple gunicorn workers locally.

---

## 5. Optional — exercise the free tier

Off by default. To test the owner-funded trial path without BYOK keys:
1. Set `FREE_TIER_ENABLED=true` and all five `SYSTEM_*` keys (your own LiveKit/OpenAI/Deepgram) in `.env`.
2. Restart. A new email should get its bounded free interviews; the dashboard badge shows remaining slots; the monthly ceiling (`FREE_TIER_MONTHLY_MAX_CALLS`) is the kill-switch.
3. ✅ Confirm a 3rd interview on the same email falls back to "bring your own keys".

---

## 6. Quick reference — green-path checklist

- [ ] Neon DB created, migrations `001` + `002` run
- [ ] Google OAuth client has `http://localhost:5000/auth/google/callback` registered
- [ ] `.env` has the 5 required vars; `FLASK_ENV` not `production`
- [ ] `pip install -r requirements-dev.txt`
- [ ] `python app.py` → `/health` OK, sign-in lands on `/dashboard`
- [ ] (Level B) valid LiveKit + OpenAI + Deepgram keys added & validated in Settings
- [ ] Full interview runs, ends, saves transcript, renders scored feedback, exports
- [ ] `pytest` + `ruff` green; Playwright smoke clean
