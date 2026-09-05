# MockFlow-AI Deployment Guide

Deploying MockFlow-AI to **Fly.io** on a **custom domain**, always-on.

> **This guide replaced a Supabase + Render one.** The backend is **Neon
> Postgres** (psycopg3 in `db.py`) with **Authlib Google OAuth + Flask-Login** —
> there is no Supabase project, no `auth.users`, and no RLS. Auth is enforced in
> Flask (`@require_auth`), not in the database.

---

## 0. Choosing a host (read this before you pick)

The app's shape decides the host. `worker_manager.spawn_worker()` launches
`agent_worker.py` as an **OS subprocess** per interview, and that process holds a
live LiveKit session — loading Silero VAD and streaming audio — for the entire
20–40 minute interview.

| Host | Verdict | Why |
|---|---|---|
| **Fly.io** | **Recommended** | Real containers, long-lived processes, subprocess spawning, always-on via `min_machines_running`, free automatic TLS on custom domains. |
| Render | Works, but | This is what it ran on. The free tier **spins down when idle**, which is exactly the "not always working itself" problem. A paid instance fixes it and needs no code change. |
| **Cloudflare Workers / Pages** | **Cannot host this** | Workers are V8 isolates running JS/WASM — there is no CPython, no `subprocess.Popen`, and no process that stays resident for a 30-minute call. Not a config problem; the execution model is incompatible. |

**Cloudflare still has a job here** (optional): point your domain's DNS at Fly
and let Cloudflare serve as DNS + CDN for `/static`. Just don't try to *run* the
Python on it. If you do use Cloudflare's proxy, see the TLS note in §4.

### Why this app pins to one machine

`worker_manager.active_workers` is an **in-process dict**. A request that lands
on a second machine cannot see a worker running on the first, so
`/api/worker-status` and interview teardown would break. Until that state moves
out of process (Redis, or LiveKit dispatch), keep `min_machines_running = 1` and
do **not** raise `max_machines_running`. This caps concurrent interviews at one
machine's memory — which is what `MAX_CONCURRENT_WORKERS` is for.

---

## 1. Prerequisites

1. **Neon project** with the migrations in `migrations/` applied (see §2).
2. **Google Cloud OAuth** client (§3).
3. **flyctl** installed and authenticated: `fly auth login`.
4. A **domain** you control.

---

## 2. Database (Neon)

Apply the migrations in order against your Neon branch. `003` is the one that
backs the whole feedback moat — if it is missing, verdicts fail to persist.

```bash
psql "$DATABASE_URL" -f migrations/001_initial_schema.sql
psql "$DATABASE_URL" -f migrations/002_free_tier_and_stats.sql
psql "$DATABASE_URL" -f migrations/003_interview_scores.sql
```

Verify:

```bash
psql "$DATABASE_URL" -c "\dt"
```

Use the **pooled** Neon connection string as `DATABASE_URL`. Put the Fly app in
the **same region as the Neon project** (`primary_region` in `fly.toml`).

---

## 3. Google OAuth

`auth_helpers.py` builds the callback with `url_for(..., _external=True)`, and
`app.py` wraps the WSGI app in `ProxyFix`, so behind Fly's TLS proxy the app
generates `https://<your-domain>/auth/google/callback` correctly.

In Google Cloud Console → Credentials → your OAuth client, register **every**
origin you will actually use:

**Authorized redirect URIs**
- `https://<your-domain>/auth/google/callback`
- `https://<app-name>.fly.dev/auth/google/callback` *(so you can test before DNS)*
- `http://localhost:5000/auth/google/callback` *(local dev)*

**Authorized JavaScript origins**
- `https://<your-domain>`, `https://<app-name>.fly.dev`, `http://localhost:5000`

A missing entry produces Google's `Error 400: redirect_uri_mismatch`. Locally, do
**not** set `FLASK_ENV=production` — `SESSION_COOKIE_SECURE` would drop the
session cookie over plain http and OAuth's state check would fail.

---

## 4. Deploy to Fly

The repo ships a `Dockerfile` and `fly.toml`. Create the app without deploying,
so you can set secrets first:

```bash
fly launch --no-deploy --name <app-name> --region <neon-region>
```

Generate and set the secrets (these are encrypted at rest and injected as env
vars; **`ENCRYPTION_KEY` must never change** — it decrypts every stored BYOK key):

```bash
fly secrets set DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require" GOOGLE_CLIENT_ID="...apps.googleusercontent.com" GOOGLE_CLIENT_SECRET="..." SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')" ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')" CORS_ORIGINS="https://<your-domain>"
```

`FLASK_ENV=production`, `PORT`, and `MAX_CONCURRENT_WORKERS` are already in
`fly.toml`'s `[env]`. With `FLASK_ENV=production`, `app.py` **fails fast at boot**
if a required variable is missing — a crash loop here is a missing secret, so
check `fly logs` first.

Deploy:

```bash
fly deploy
```

```bash
curl -fsS https://<app-name>.fly.dev/health
```

`/health` returns `200` with `{"status":"healthy","database":"reachable"}`, or
`503` if Neon is unreachable. Fly's health check in `fly.toml` polls this, so a
DB outage marks the machine unhealthy rather than serving broken pages.

### Custom domain + TLS

```bash
fly certs add <your-domain>
```

```bash
fly certs show <your-domain>
```

That prints the exact DNS records to create. Add the `A`/`AAAA` (or `CNAME`)
records at your DNS provider, then wait for issuance (usually minutes):

```bash
fly certs check <your-domain>
```

**If your DNS is on Cloudflare:** start with the proxy **off** (grey cloud) so
Fly can complete the ACME challenge. Once the cert is issued you may turn the
orange cloud on, but set Cloudflare SSL/TLS mode to **Full (strict)** — the
default "Flexible" mode talks plain http to the origin, which combined with
`force_https` in `fly.toml` causes a redirect loop.

Finally, point `CORS_ORIGINS` at the real domain:

```bash
fly secrets set CORS_ORIGINS="https://<your-domain>"
```

### Staying always-on

`fly.toml` sets `auto_stop_machines = false` and `min_machines_running = 1`, so
one machine stays resident — no cold start. Note this means the machine bills
continuously rather than per-request; that is the trade for always-on.

Neon's free tier still **scale-to-zero**s its compute after inactivity, adding a
few seconds to the first query, so `.github/workflows/keep-warm.yml` pings it
directly on a schedule. Set two repo-level values for CI:

- secret **`FLY_API_TOKEN`** (`fly tokens create deploy -x 999999h`) — enables the
  deploy job in `deploy.yml`; without it that job skips and CI still passes.
- variable **`APP_URL`** (e.g. `https://<your-domain>`) — used by the post-deploy
  health smoke and the keep-warm canary.

---

## 5. Post-deploy verification

```bash
curl -fsS https://<your-domain>/health
```

Then in a browser: sign in with Google, save BYOK keys in Settings, run a short
interview, and confirm the verdict renders and survives a page reload (it is
persisted server-side to the `feedback` table).

Watch memory during a live interview before trusting `MAX_CONCURRENT_WORKERS`:

```bash
fly ssh console -C "free -m"
```

---

## Important Notes

### About API keys (BYOK model)

- **LiveKit**, **OpenAI**, and **Deepgram** keys are **NOT** deployment env vars.
- Each user provides their own via the Settings page; they are encrypted at rest
  with `ENCRYPTION_KEY` and passed to the worker subprocess as env vars.
- The optional owner-funded free tier is the exception: `FREE_TIER_ENABLED=true`
  plus the five `SYSTEM_*` keys (requires migration `002`). It defaults **off**.

### Security

1. Never commit `.env` — it is gitignored, and `.dockerignore` keeps it out of
   the image.
2. Never expose `ENCRYPTION_KEY`; losing or rotating it invalidates every stored
   user API key.
3. Rotate `SECRET_KEY` / `GOOGLE_CLIENT_SECRET` periodically. Rotating
   `SECRET_KEY` logs everyone out (it signs the session cookie).
4. Real interview transcripts (`interviews/`, `feedback/`) are PII — gitignored
   and excluded from the image.

### Capacity

- **Fly**: sized in `fly.toml` (`shared-cpu-2x` / 2 GB as a starting point).
- **Neon free**: 0.5 GB storage, compute scales to zero when idle.
- **Concurrent interviews**: capped by `MAX_CONCURRENT_WORKERS` (memory-bound —
  each is an onnxruntime-loaded subprocess), and by the single-machine pin above.

### Architecture Details

#### Direct Room Connection (CRITICAL)

**Why This Matters:**

The agent workers use **direct room connection** instead of LiveKit's dispatch-based system. This is a critical architectural decision that prevents deployment issues.

**How It Works:**

```
Traditional Dispatch (PROBLEMATIC):
1. Worker runs: python agent_worker.py dev
2. Registers with LiveKit Cloud as "available agent"
3. LiveKit dispatches ANY room to ANY available worker
4. Old workers from previous deploys compete with new workers
5. Result: User connects to wrong worker, interview freezes

Direct Connection (CURRENT):
1. Worker runs: python agent_worker.py (NO 'dev')
2. Generates agent token for specific room
3. Connects directly via Room.connect()
4. Handles interview, exits cleanly
5. No registration, no competition, no old workers
```

**Key Code Patterns:**

```python
# agent_worker.py - Direct connection
async def run_interview():
    # Generate agent token for specific room
    token = livekit_api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    token.with_identity("interview-agent")
    token.with_grants(livekit_api.VideoGrants(
        room_join=True,
        room=INTERVIEW_ROOM_NAME,
        can_publish=True,
        can_subscribe=True,
    ))

    # Connect directly to room
    room = Room()
    await room.connect(LIVEKIT_URL, token.to_jwt())

    # Handle interview...
    # Exit when done

# worker_manager.py - Spawn worker
subprocess.Popen(['python', 'agent_worker.py'], ...)  # No 'dev'!
```

#### Plugin HTTP Session Management

**The Problem:**

LiveKit plugins (Deepgram STT, OpenAI LLM/TTS) expect to run inside `cli.run_app()` which provides a shared `aiohttp.ClientSession`. When using direct connection, there's no session available.

**The Solution:**

```python
# Create and pass http_session to plugins that need it
http_session = aiohttp.ClientSession()

try:
    # Deepgram STT needs http_session
    stt = deepgram.STT(
        model="nova-2",
        http_session=http_session  # Required
    )

    # OpenAI plugins do NOT take http_session
    llm = openai.LLM(model="gpt-4o-mini")
    tts = openai.TTS(voice="alloy")

finally:
    await http_session.close()
```

#### Silero VAD Optimization (CPU Constraints)

**The Problem:**

On a low-CPU instance (Render's free tier gave 0.1 CPU) Silero VAD runs "inference slower than realtime", causing voice to break or hang. The `shared-cpu-2x` sizing in `fly.toml` is chosen to stay clear of this.

**The Solution:**

```python
# Optimized VAD settings for low-CPU environments
vad = silero.VAD.load(
    min_speech_duration=0.1,      # Less sensitive detection
    min_silence_duration=0.3,     # Wait longer before ending speech
    padding_duration=0.1,
    max_buffered_speech=30.0,     # Reduced buffer (from 60s)
    activation_threshold=0.5,
    sample_rate=16000,            # Standard rate
)
```

**Trade-offs:**
- Less aggressive interruption detection
- Longer silence needed to end speech
- Better performance on limited CPU
- Smoother voice experience

### Troubleshooting

**Issue: Health check fails**
- Verify `DATABASE_URL` is the correct Neon **pooled** connection string
- Check the Neon project/branch is not suspended, and that `/health` reports `database: reachable`

**Issue: OAuth fails**
- Verify Google OAuth redirect URI matches exactly
- Check `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` are set (`fly secrets list`)

**Issue: Worker spawn fails**
- Check `fly logs` for subprocess errors
- Verify the user has entered API keys in Settings
- Check memory headroom (`fly ssh console -C "free -m"`) — each worker is memory-hungry; lower `MAX_CONCURRENT_WORKERS` or raise `[[vm]] memory`

**Issue: User connects but interview freezes / no agent voice**

This is the most common issue. Caused by old workers still registered with LiveKit Cloud.

**Symptoms:**
- User joins room successfully
- Loading indicator never disappears
- No agent voice
- Logs show: `Connected to room: interview-xxx` but nothing happens
- LiveKit dashboard shows multiple agents registered

**Root Cause:**

Old workers from previous deployments are still registered with LiveKit Cloud and competing for room connections.

**Solution A: Clear LiveKit Cloud Agent Cache**

1. Go to [LiveKit Cloud Dashboard](https://cloud.livekit.io)
2. Navigate to your project
3. Go to **Agents** or **Workers** section
4. Terminate ALL registered agents (look for IDs like `AW_4YwS9uFDcCiw`)
5. Redeploy: `fly deploy`

**Solution B: Hard restart the machine**

```bash
fly apps restart <app-name>
```

This kills every lingering worker subprocess and starts a clean container. To rule out a stale image layer, rebuild without cache: `fly deploy --no-cache`.

**Solution C: Verify Direct Connection Mode**

Check your logs for:

```bash
# GOOD - Direct connection mode
[WORKER] Starting agent worker - DIRECT ROOM CONNECTION MODE
[MAIN] Connected to room: interview-xxx
[MAIN] Waiting for participant to join...

# BAD - Dispatch mode (should NOT see this)
[WORKER] Starting dispatch worker...
[AGENT] Registered with LiveKit Cloud
```

If you see dispatch mode logs, your code is using the old architecture. Verify:
- `agent_worker.py` uses `asyncio.run(run_interview())` NOT `cli.run_app(server)`
- `worker_manager.py` spawns with `['python', 'agent_worker.py']` NOT `['python', 'agent_worker.py', 'dev']`

**Issue: Voice breaks / hangs / "inference slower than realtime"**

**Cause:** Silero VAD running too aggressively on limited CPU.

**Solution:** Already optimized in latest code. If still happening:
1. Check load with `fly ssh console -C "uptime"` during an interview
2. Scale up: `fly scale vm performance-1x` (dedicated CPU)
3. Or reduce `max_buffered_speech` further in `agent_worker.py`

**Issue: RuntimeError: Attempted to use an http session outside of a job context**

**Cause:** Plugin trying to use HTTP without session.

**Solution:** Already fixed in latest code. Verify:
```python
# Deepgram gets http_session
stt = deepgram.STT(..., http_session=http_session)

# OpenAI plugins do NOT
llm = openai.LLM(...)  # No http_session parameter
```

**Issue: Database queries slow**
- Verify the migrations in `migrations/` ran (they create the indexes)
- Confirm `primary_region` in `fly.toml` matches the Neon region — a cross-region hop dominates query time
- Check the Neon console for slow queries; a scaled-to-zero compute adds a few seconds to the first query

---

## Monitoring

### Check Logs

```bash
fly logs
```

**Important Log Patterns:**
- `[WORKER] Spawning worker for room: interview-*` - Worker starting
- `[WORKER] Worker spawned (PID: *)` - Worker started successfully
- `[SESSION] Successfully connected to room: *` - Agent connected
- `[FINALIZE] Interview saved successfully: *` - Interview saved to database
- `[HEALTH] Health check passed` - System healthy

### Monitor Active Workers

Visit `/health` endpoint to see current worker count:
```bash
watch -n 5 'curl -s https://<your-domain>/health | jq'

---

## Rollback

```bash
fly releases
```

```bash
fly releases rollback <version>
```

Or revert the commit and redeploy:

```bash
git revert HEAD && git push origin main && fly deploy
```

---

## Support

- **GitHub Issues**: https://github.com/PranavMishra17/MockFlow-AI/issues
- **Fly status**: [status.flyio.net](https://status.flyio.net)
- **Neon status**: [neonstatus.com](https://neonstatus.com)

---

## Summary checklist

**Pre-deploy**
- [ ] Neon migrations `001`, `002`, `003` applied
- [ ] Google OAuth redirect URIs registered for the domain **and** `*.fly.dev`
- [ ] `SECRET_KEY` + `ENCRYPTION_KEY` generated and stored safely
- [ ] `fly launch --no-deploy` run; all six secrets set
- [ ] `primary_region` matches the Neon region

**Post-deploy**
- [ ] `fly deploy` succeeded; `fly logs` clean
- [ ] `/health` returns 200 with `database: reachable`
- [ ] `fly certs check <domain>` shows the cert issued
- [ ] `CORS_ORIGINS` points at the real domain
- [ ] Google sign-in works on the custom domain

**Interview E2E**
- [ ] Logs show `DIRECT ROOM CONNECTION MODE` (never "dispatch" / "registering with LiveKit Cloud")
- [ ] Agent audio within ~5 s; user speech transcribed
- [ ] Interview saves to Neon; verdict renders and survives a reload
- [ ] Memory headroom confirmed under a live interview (`fly ssh console -C "free -m"`)
