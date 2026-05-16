# MockFlow-AI — Supabase → Xata + Authlib Migration Plan

**Goal:** $0/mo, never-pausing stack. Keep Render free for the app; replace Supabase (paused after 7 days idle) with Xata free Postgres + Authlib Google OAuth.

**Final stack**
- App host: Render free (unchanged — 2-min cold start accepted)
- Database: Xata free (Postgres-compatible, 15 GB, no pause, no CC)
- Auth: Authlib + Flask-Login (Google OAuth, sessions in Flask cookie)
- LiveKit: unchanged (BYOK)

---

## Prerequisites — YOUR work before Phase 1

These are the manual steps Claude cannot do for you. Do them in order; takes ~30 minutes total.

### 1. Create a Xata account and database (~10 min)

1. Sign up at https://xata.io with GitHub or Google. **No credit card required.**
2. Create a new workspace (any name).
3. Create a new database:
   - Name: `mockflow-ai`
   - Region: pick closest to your Render region (Render's default is Oregon → choose `us-east-1` or `us-west-2`)
   - Postgres-compatible: **YES** (this is the default in 2025+ — confirm the toggle says "Postgres" not "Xata SDK only")
4. Under **Settings → Connect with Postgres**, copy the connection string. It looks like:
   ```
   postgresql://<workspace>:<api_key>@<region>.sql.xata.sh/mockflow-ai:main?sslmode=require
   ```
5. Save this somewhere safe — you'll paste it into Render env vars later.

### 2. Update Google OAuth redirect URIs (~5 min)

You already have a Google Cloud OAuth client (it's currently pointing at Supabase's callback). Add a new redirect URI for your own callback so we can drop Supabase Auth.

1. Go to https://console.cloud.google.com → APIs & Services → Credentials
2. Open your existing OAuth 2.0 Client ID for MockFlow-AI
3. Under **Authorized redirect URIs**, ADD:
   - `https://mockflow-ai.onrender.com/auth/google/callback`
   - `http://localhost:5000/auth/google/callback` (for local dev)
4. Keep the Supabase callback for now (we'll remove it after migration is verified).
5. Copy your `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` — you already have these but make sure they're handy.

### 3. Export current Supabase data (~10 min)

So we can re-import into Xata.

1. Go to https://supabase.com → your MockFlow-AI project → SQL Editor
2. Run this query and save the output as `supabase_export.json` somewhere safe:
   ```sql
   SELECT 'users' AS t, row_to_json(u.*) AS r FROM auth.users u
   UNION ALL
   SELECT 'user_api_keys', row_to_json(k.*) FROM user_api_keys k
   UNION ALL
   SELECT 'interviews', row_to_json(i.*) FROM interviews i
   UNION ALL
   SELECT 'feedback', row_to_json(f.*) FROM feedback f
   UNION ALL
   SELECT 'coding_submissions', row_to_json(c.*) FROM coding_submissions c;
   ```
   Use the **Download as JSON** button.
3. Also keep your existing `ENCRYPTION_KEY` value safe — without it, all stored user API keys become unrecoverable ciphertext.

### 4. Decide: keep existing user IDs, or fresh users? (1 min)

Supabase Auth issues UUIDs from `auth.users`. Authlib doesn't have that table — we'll create a `users` table in Xata.

Two options:
- **A. Fresh start (recommended for a demo project):** existing users re-login with Google, get new UUIDs, lose old interview history. Simplest migration.
- **B. Preserve user IDs:** import `auth.users` rows into the new `users` table keeping the same UUIDs, match new Google logins by email. More work, preserves history.

**Tell me A or B before Phase 3.** If unsure, pick A.

---

## What Claude (me) will do — phased plan

Each phase is independently committable. Anything that fails verification rolls back without breaking the live site (Supabase stays connected until Phase 4).

### Phase 0 — Already done ✅
- Form fields persist in localStorage (`templates/form.html`, commit `478d307`)

### Phase 1 — Add new dependencies (5 min, low risk)
- Add to `requirements.txt`: `psycopg[binary]>=3.2`, `authlib>=1.3`, `flask-login>=0.6`
- Add a `.env.example` block for new vars: `XATA_DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `FLASK_SECRET_KEY`, `ENCRYPTION_KEY` (the last two already exist)
- Verification: `pip install -r requirements.txt` succeeds locally

### Phase 2 — Create `db.py` (psycopg replacement for supabase_client.py) (~3 hrs)
- New file `db.py` exposing the same method signatures as `SupabaseClient`: `get_user`, `get_user_by_email`, `create_user`, `save_api_keys`, `get_api_keys`, `create_interview`, `update_interview`, `get_interviews_by_user`, `save_feedback`, `get_feedback`, `save_coding_submission`, etc.
- Use `psycopg.connect(XATA_DATABASE_URL)` with a small connection pool
- Keep the Fernet encryption helpers exactly as-is (the cipher is at the app layer, not the DB layer — ciphertext just rides in TEXT columns)
- **Do not touch `supabase_client.py` yet** — both files coexist during this phase
- Verification: a `test_db.py` script that round-trips one user, one interview, one feedback row against a live Xata DB

### Phase 3 — Replace `auth_helpers.py` with Authlib (~2 hrs)
- Rewrite `auth_helpers.py` to use Authlib's Google OAuth + Flask-Login
- Replace `supabase.auth.get_user(access_token)` with `current_user` from Flask-Login
- Two new routes in `app.py`: `/auth/google/login` and `/auth/google/callback`
- User row created in Xata's `users` table on first login (lookup by email)
- Verification: local OAuth flow → land on dashboard → `session` has Flask-Login user

### Phase 4 — Cut over `app.py` (~30 min, REVERSIBLE)
- Swap `from supabase_client import SupabaseClient` → `from db import DB`
- Single-line import switch; all method names stay identical thanks to Phase 2
- Delete `supabase_client.py` only after a week of stable Xata operation
- Verification: full end-to-end on local — login, save API keys, run an interview, generate feedback, view past interviews

### Phase 5 — Render deployment (~10 min)
- Update Render env vars: add `XATA_DATABASE_URL`, remove `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_ANON_KEY` after one week of stability
- Add `https://mockflow-ai.onrender.com/auth/google/callback` to Google OAuth redirect URIs (already in prerequisites)
- Trigger a deploy
- Verification: `/health` returns 200, OAuth login works in prod, one full interview completes

### Phase 6 — Schema bootstrap on Xata (5 min)
- Run the existing `docs/DEPLOYMENT.md` SQL migrations on Xata (they're standard Postgres — no rewrites needed)
- Plus a new `users` table (Authlib-managed, replaces `auth.users`):
  ```sql
  CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    picture_url TEXT,
    google_id TEXT UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  ```
- Change all `REFERENCES auth.users(id)` to `REFERENCES users(id)` in the migration files
- Drop the RLS policies (we enforce `WHERE user_id = %s` in app code instead — `db.py` handles this)
- Verification: `\dt` on the Xata SQL console shows all 5 tables

### Phase 7 — Data re-import (~15 min, only if you picked option B in prereq #4)
- Python script that reads `supabase_export.json` and writes rows into Xata via `db.py`
- Skip if you picked option A (fresh start)

---

## Total time estimate

- Your prerequisites: **30 min**
- Claude's Phase 1: 5 min
- Claude's Phase 2: 3 hrs
- Claude's Phase 3: 2 hrs
- Claude's Phase 4: 30 min
- Claude's Phase 5: 10 min
- Claude's Phase 6: 5 min
- Claude's Phase 7: 15 min (optional)

**~6 hrs of Claude work, 30 min of your work.** Realistically this spills into a second chat session — Phase 2 alone is heavy. Phases 1, 6, the prereqs are great to do today; Phase 2-4 might want a fresh session.

---

## What Claude cannot do for you

- Sign up for Xata (browser flow, requires your email)
- Click through Google Cloud Console UI to add redirect URIs
- Set Render env vars (you have to paste into Render dashboard)
- Trigger a Render deploy (you click "Manual Deploy")
- Decide option A vs B in prereq #4

## What Claude CAN do (and Supabase MCP note)

You have a Supabase MCP connected — that lets me query/migrate the Supabase side **if you give me read access**. It doesn't help with the Xata side (there's no Xata MCP yet). Concretely:

- If you'd like, share your Supabase project ref and I can run the data export query for you via the MCP, saving prereq step 3.
- I can also use it to verify the schema before we migrate, so the new `db.py` matches reality.

If you want that, paste the Supabase project ref (the part before `.supabase.co` in your URL). Otherwise the manual SQL Editor export works just as well.

---

## Rollback plan

Phases 1-3 are additive — they don't touch the running site. If something fails in Phase 4 (cutover), revert that one commit and you're back on Supabase. Phase 5 is the only "Render env vars change" — keep the old Supabase env vars in Render until a week of Xata stability.
