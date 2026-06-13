# MockFlow-AI — Product & Engineering Audit

**Date:** June 12, 2026
**Scope:** Full audit — backend, frontend/UX, security, feature completeness, DevEx, production readiness.
**Method:** Four parallel deep-dive reviews (backend, frontend, security, DevEx) with every load-bearing claim re-verified against the working tree and git history.
**Deferred:** Live end-to-end verification of the voice interview flow (requires working LiveKit/OpenAI/Deepgram keys — to be done after key refresh).

---

## 0. Corrections to the brief (read this first)

1. **The database is Neon Postgres, not MongoDB Atlas.** `db.py` is a psycopg3 Postgres layer, `requirements.txt` pulls `psycopg[binary,pool]`, the keep-warm workflow pings Neon directly, and commit `d67a7e3` says "Swap Supabase Auth/DB for Authlib Google OAuth + Neon". There is no MongoDB driver or reference anywhere in the repo. Everything below audits the actual Neon stack. (If you *intended* to be on MongoDB, that migration never happened — but Neon is the better fit for this schema and I'd recommend staying.)
2. **Your `.env` and `.env.development` files were never committed.** `git log --all -- .env*` is empty; only `env.template` is tracked. The real keys exist only on your disk. No emergency rotation is required on account of git history. (Rotate LiveKit/keys anyway at your leisure since you said they may be stale.)
3. **ElevenLabs is not part of this codebase.** TTS is OpenAI, STT is Deepgram. If you have ElevenLabs keys, nothing here uses them.
4. **Production does not run the Flask dev server.** Render's documented start command is `gunicorn app:app --workers 1 --timeout 120` (docs/DEPLOYMENT.md:231). The `app.run(debug=True)` block at app.py:1601-1614 only executes when run directly (local dev).

---

## 1. Executive summary

MockFlow-AI is a genuinely impressive solo project: a four-track, FSM-driven voice interview agent with BYOK key management, Fernet-encrypted key storage, Monaco-based coding rounds, speech analytics, and LLM feedback generation — all on a $0/month stack. The architecture is sound (parameterized SQL everywhere, clean module boundaries, no circular imports, a sensible subprocess-per-interview worker model) and the recent Supabase→Neon migration was executed well.

What holds it back from "polished portfolio product" is not architecture — it's **finish work in three areas**:

- **Trust gaps (backend):** the `/health` endpoint still validates deleted Supabase env vars and never touches Neon; three API endpoints are unauthenticated (file upload, conversation cache read/write); CORS is wide open; `SECRET_KEY` silently falls back to a hardcoded dev string; your own real interview transcripts (PII) are committed to the repo; ~1,000 lines of dead code (`agent.py`) and stale Supabase-era docs/CI instructions contradict the actual stack.
- **First-run experience (frontend):** a new user hits the BYOK wall with no warning, waits through 10–120 s cold starts with no time expectations, and sees generic errors with no recovery path. Landing/form/interview pages break under ~768 px. No dark mode, weak accessibility, `alert()` for errors.
- **Verification (DevEx):** CI runs syntax checks only — zero tests, zero linting, zero type checking — yet every push to `main` auto-deploys to production.

**Top 5 priorities, in order:** (1) the Immediate Fixes list in §2 (~one focused day, mostly security/reliability), (2) the loading-state + onboarding work in §3 (biggest UX payoff per hour anywhere in the project), (3) the Testing/CI wing in §6 so merges become safe, (4) the UI overhaul wing (mobile, dark mode, a11y, token consolidation), (5) the Insights wing (dashboard, export) for demo wow-factor.

**Overall grades:** Engineering B− · Security C · UX/Polish C+ · DevEx/verifiability D+ · Concept/feature ambition A.

---

## 1a. Implementation status — branch `fix/immediate-hardening` (2026-06-12)

The entire §2 Immediate-Fixes list has been implemented on this branch, with a
hermetic pytest suite (23 tests) and a real CI pipeline. Verified via tests +
ruff + workflow-YAML parse; live voice-flow E2E remains deferred (stale keys).

**Done and verified:**

| §2 | Fix | How verified |
|----|-----|--------------|
| 1 | `/health` now pings Neon (`db.ping()`), no Supabase env check | tests assert 200 when DB up / 503 when down, and that the response never mentions Supabase |
| 2 | Interview/feedback PII untracked (`git rm --cached`, kept on disk); `/feedback` + lock added to `.gitignore` | `git ls-files interviews feedback` → empty |
| 3 | `SECRET_KEY` hardcoded fallback removed (prod fails fast; dev gets ephemeral random key); `SESSION_/REMEMBER_COOKIE_*` hardened (HttpOnly, SameSite=Lax, Secure in prod, 7-day remember) | config-assertion tests |
| 4 | `@require_auth` added to `/api/upload-resume`, `/api/conversation/cache` (POST), `/api/conversation/<key>` (GET); `MAX_CONTENT_LENGTH=10 MB` | anon-request tests assert blocked (401/redirect); confirmed those 3 endpoints have no server-to-server callers first |
| 5 | CORS scoped to `CORS_ORIGINS` (was wildcard) | test asserts disallowed origin not echoed |
| 6 | Security headers via `after_request` (XFO deny, nosniff, Referrer-Policy, `frame-ancestors` CSP, HSTS in prod) | header-presence test |
| 7 | Deleted dead `agent.py`, `test_supabase.py`, `supabase-backend/`; moved root migration into `migrations/` | confirmed `agent.py` imported nowhere live first |
| 8 | CI rewritten: ruff + pytest gates before deploy; stale `SUPABASE_*` reminders replaced with the real vars; post-deploy `/health` smoke | YAML parses; runs locally |
| 9 | `env.template` rewritten to the 5 vars the code reads + optional ones; dropped 11 unused | matches a grep of `os.getenv` |
| 10 | UUID validation on `/api/coding/submit`; `?limit=` capped at 100; `room_name` sanitised via `_safe_room_component` | validation tests |
| 11 | Root `MIGRATION.md` deleted; `docs/MIGRATION.md` + `SUPABASE_BACKEND_SCHEMA.md` archived as `*_HISTORY`; new `docs/ARCHITECTURE.md` = single source of truth | — |
| 12 | `runtime.txt` (`python-3.12.6`) | — |

Also added: `pyproject.toml` (ruff+pytest config), `requirements-dev.txt`, `tests/`
(security + speech-analytics + postprocess), and a one-line cleanup of a
shadowed import in `agent_worker.py` that ruff flagged.

**Deferred (need your decision / belong to a wing — NOT done here):**

- **Git history rewrite + force-push** to purge the PII from *past* commits. Untracking stops future leakage, but the transcripts still exist in history. This rewrites every commit SHA and force-pushes — destructive and yours to trigger. When ready: `git filter-repo --path interviews --path feedback --invert-paths` then `git push --force`.
- **API key rotation** — you said keys may be stale; rotating LiveKit/OpenAI/Deepgram/Google is your call (no leak from git history was found).
- **Full content CSP** (Wing B — needs screenshot verification against inline scripts + CDNs), **CSRF tokens** (Wing A — currently mitigated by SameSite=Lax + scoped CORS), **`db.py` error-semantics rework** and **migrating `agent_worker` off the `supabase_client` shim** (Wing A).

---

## 2. Immediate fixes (high priority, low friction)

All of these are < 1 hour each; the whole list is roughly one focused day. Ordered by importance.

| # | Fix | Why | Where | Effort |
|---|-----|-----|-------|--------|
| 1 | **Rewrite `/health`** — drop the `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` check; instead run `SELECT 1` through `db_client.pool` | It validates env vars for a service you no longer use and never touches the real DB. It currently only returns 200 because stale Supabase vars are presumably still set in Render; remove them and your health check + keep-warm flow goes red | app.py:1550-1581 | 15 min |
| 2 | **Purge committed PII** — `git rm` the 6 `interviews/*.json` + `feedback/*_feedback.json`, add `/feedback` to `.gitignore` (`/interviews` is listed but the files were force-added/pre-dated the rule). Then rewrite history with `git filter-repo` since this is a public portfolio repo | Real transcripts of your own interviews, name, education, employer details are in git history | `interviews/`, `feedback/`, .gitignore:195 | 30 min |
| 3 | **Remove the `SECRET_KEY` fallback** — fail at boot if unset; while there, set `SESSION_COOKIE_SECURE/HTTPONLY/SAMESITE='Lax'` and `REMEMBER_COOKIE_SECURE/HTTPONLY/SAMESITE` + 7-day duration | `'dev-secret-key-change-in-prod'` makes every session forgeable if the env var is ever missing in prod; SameSite=Lax also closes most practical CSRF on your JSON POSTs | app.py:51 | 30 min |
| 4 | **Auth + size limits on open endpoints** — add `@require_auth` to `POST /api/upload-resume`, `POST /api/conversation/cache`, `GET /api/conversation/<key>`; add `MAX_CONTENT_LENGTH = 10 MB` to Flask config | Unauthenticated file upload + unauthenticated cache read keyed by guessable MD5 = abuse and disclosure vectors | app.py:559, 654, 724 | 45 min |
| 5 | **Scope CORS** — `CORS(app)` currently allows all origins; restrict to your Render domain + localhost | Wide-open CORS on an authenticated API | app.py:55 | 10 min |
| 6 | **Add security headers** — one `@app.after_request`: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `HSTS`, and a starter CSP | Free hardening, expected of a production app | app.py (new) | 30 min |
| 7 | **Delete dead code** — `agent.py` (~1,000 lines, imported nowhere, contains bare `except:`), `test_supabase.py`, `supabase-backend/`, root `add_livekit_keys_migration.sql` (move to `migrations/` if historical) | Confuses every reader (including future-you); `agent.py` vs `agent_worker.py` is the #1 "which one is real?" trap | repo root | 30 min |
| 8 | **Fix the CI's stale instructions** — deploy.yml still tells you to set `SUPABASE_URL/SERVICE_KEY/ANON_KEY` in Render and `py_compile`s `agent.py`/`supabase_client.py` | The deploy job actively documents the wrong env vars | .github/workflows/deploy.yml:31-44, 74-77 | 15 min |
| 9 | **Rewrite `env.template`** — remove the 11 vars the code never reads (`FLASK_DEBUG`, `FLASK_PORT`, `LOG_*`, `STAGE_*`, `INACTIVITY_TIMEOUT`, `SUPABASE_*`); add the 5 it requires but doesn't document (`DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SECRET_KEY`, `ENCRYPTION_KEY`) plus optional `MAX_CONCURRENT_WORKERS` | A fresh clone following the template cannot boot the app | env.template | 30 min |
| 10 | **Small input-validation gaps** — UUID-validate `interview_id` in `POST /api/coding/submit` (the GET route already does); cap `?limit=` at 100 in `/api/user/interviews`; sanitize `name` before building `room_name` | Consistency with the validation you already do elsewhere | app.py:501, 780, 339 | 20 min |
| 11 | **Docs triage** — delete root MIGRATION.md (a Xata plan that never happened — you went to Neon), archive docs/MIGRATION.md + SUPABASE_BACKEND_SCHEMA.md as `*_HISTORY.md`, and add a short `docs/ARCHITECTURE.md` stating the *current* stack | Three documents currently describe three different databases; a portfolio reviewer reading docs/ will conclude the project is half-migrated | MIGRATION.md, docs/ | 1 hr |
| 12 | **Add `runtime.txt`** (`python-3.12`) | Pins Render's Python to what CI tests | repo root | 2 min |

Also worth knowing (no action needed): feedback/scoring/topic-extraction all run on the **user's own stored OpenAI key** (app.py:451, 1256, 1431), so LLM cost abuse is bounded per-user — a genuinely nice property of the BYOK design.

---

## 3. Easy feature wins

Mostly supported by existing architecture; each is hours, not days. Ranked by payoff-per-hour.

1. **Cold-start and progress messaging (the single biggest UX win).** Every long wait in the product is silent: form submit → token (10–120 s incl. worker spawn), interview connect (agent can take 1–2 min to join), feedback generation (10–60 s). Add staged copy ("Spinning up your interviewer — first run can take up to 2 minutes…"), an elapsed timer, a "still working" state after 30 s, and a hard timeout with a retry path. The form already has a loading sidebar and the feedback page already has phase dots — they just need honesty and timeouts. ~3–4 hrs.
2. **BYOK onboarding gate.** On `/start`, call the existing `/api/user/keys/status` and show a banner: "API keys configured ✓" or "You'll need API keys first → Set up (2 min)". When `/api/token` fails for missing keys, say *which* keys and deep-link to `/api-keys`. Eliminates the #1 first-run dead end. ~2–3 hrs.
3. **Empty states with CTAs.** Past-calls empty state should have a "Start your first interview" button, not just prose. Feedback placeholder should make the Generate button the hero. ~1 hr.
4. **Print/export feedback.** An `@media print` stylesheet plus a "Download PDF" (via browser print) and "Copy as Markdown" button on the feedback page. The feedback is the product's artifact — right now it can't leave the app. ~2 hrs.
5. **Search/sort/filter on past calls.** Client-side filter by track/role + date sort; the data's already in the payload. ~2–3 hrs.
6. **Replace `alert()` with toasts.** One small toast utility in `static/`; reuse everywhere (key save confirmation is currently invisible). ~2 hrs.
7. **Keyboard shortcuts.** `M` mute, `Esc` closes modals (currently click-only), `Enter` submits the ready modal. Show them in tooltips. ~2 hrs.
8. **Dark mode.** Color tokens are already centralized in `:root` in styles.css — this is mostly defining a dark palette + `prefers-color-scheme` + a toggle in the existing header settings. The blockers are the hardcoded `rgba()`s in modals.css/past_calls.css and the undefined `var(--surface-2)`/`var(--primary)` references in form.css (fix those anyway — they're silent bugs today). ~4–6 hrs.
9. **Skeleton loaders** on past-calls cards and the feedback scores panel instead of "Loading…" text. ~2 hrs.
10. **Meta/OG tags + per-track page titles** ("Behavioral Interview — MockFlow-AI"), plus a `meta description`. Matters a lot for a portfolio link shared on LinkedIn. ~1 hr.
11. **Shared `static/utils.js`** — `formatDate`, `escapeHtml`, `formatStage` are duplicated across feedback.html and past_calls.html; date format also lacks time, so same-day interviews are ambiguous. ~1 hr.
12. **Mini-stats on dashboard.** Interviews completed, average score, filler-word trend — all computable from data already in Neon. Doubles as the seed of Wing D. ~3–4 hrs.

---

## 4. Major feature wings

Branch-per-wing, in this order. Each wing = one branch, one PR, one merge-to-deploy.

### Wing A — Trust & Hardening (backend reliability + security)
- **Goal / impact:** App behaves like a production service: failures are distinguishable, abuse is bounded, restarts don't lose user work. Users (and portfolio reviewers reading the code) can trust it.
- **Scope:** Everything in §2 that isn't done yet, plus: CSRF tokens for JSON POSTs (custom `X-CSRF-Token` header tied to session — lighter than Flask-WTF for an API); `flask-limiter` on `/api/token` (5/hr/user) and feedback endpoints (10/min); rework `db.py` error semantics (today every method swallows exceptions and returns `None`/`[]`/`False`, so callers can't distinguish "no keys saved" from "database down" — raise a `DBError` and map it to a 503 with honest copy); thread-safety lock around `worker_manager.spawn_worker` (double-click currently spawns two workers for one room); persist the three in-memory caches (conversation, feedback, parsed-resume) to Postgres JSONB so Render restarts/cold starts don't eat user work mid-session; replace the crude "alive after 8 s = ready" worker-readiness heuristic with a sentinel (worker touches a file or logs a ready line); structured logging with a per-request ID passed into the worker env.
- **Complexity:** Medium. **Effort:** 3–4 days.
- **Key decisions for you:** (a) error envelope shape for all API responses (recommend `{success, data, error}`); (b) cache persistence target (recommend Postgres JSONB tables — you have no Redis and don't need one at 10 users/week); (c) CSRF approach (recommend the header-token pattern over Flask-WTF).
- **Risks / dependencies:** db.py error-semantics change touches every route — do it behind the test suite from Wing C, or at least convert `test_db.py` to pytest first. Cache persistence changes the worker↔app contract slightly.

### Wing B — First-Run Experience & UI Overhaul (frontend)
- **Goal / impact:** A stranger with a link gets from landing → configured keys → completed interview without confusion, on any device, in either color scheme. This is the wing that makes it *feel* like a product.
- **Scope:** §3 items 1, 2, 8 done properly; mobile responsiveness for landing/form/interview (the three pages that currently break < 768 px — feedback/past-calls/api-keys already stack acceptably); accessibility pass (modal `role="dialog"` + focus traps + Esc-close, `aria-pressed` on mute/skip, real heading hierarchy, `:focus-visible` everywhere, alt/aria-labels on SVGs, `prefers-reduced-motion`); design-token consolidation (fix undefined vars in form.css, replace hardcoded rgba/shadow/radius values, collapse ~7 button styles into primary/secondary/danger/icon, move inline styles out of api_keys.html and form.html); a guided 3-step API-keys wizard with per-provider "where to get this key" help and a masked preview (first 4 chars) after save; resolve the dashboard/api-keys page duplication (recommend: dashboard becomes the home for account + stats, api-keys stays the single keys editor); kill leftover `console.log`s or gate behind a DEBUG flag.
- **Complexity:** Medium — large surface, but all vanilla CSS/JS, no framework decisions needed.
- **Effort:** 5–6 days.
- **Key decisions:** (a) stay vanilla JS (recommended — it's a feature of the portfolio story, just extract shared utils) vs adopting a framework; (b) dark-mode default (recommend: follow system, manual override in header); (c) whether mobile *interview* is a supported scenario or politely gated ("best on desktop — coding round needs a keyboard").
- **Risks:** CSS refactors regress visual details — take before/after screenshots per page (the `verify`/Preview tooling can drive this). Accessibility changes to modals touch interview-flow JS; test the end-interview path carefully.

### Wing C — Verification & CI (the safety net)
- **Goal / impact:** Solo-dev confidence: a green check actually means "safe to deploy". Detailed plan in §6.
- **Scope:** pytest + tests/ layout, ruff + format gate, mypy (gradual), GitHub Actions pipeline with branch protection, post-deploy smoke check, pre-commit hooks, dev-requirements split.
- **Complexity:** Low-medium. **Effort:** 3–4 days for the foundation + the §6 starter test suite.
- **Key decisions:** (a) DB-test strategy — Neon branch per CI run vs a `postgres` service container in Actions (recommend the container: free, hermetic, zero quota use; you already have `migrations/001_initial_schema.sql` to bootstrap it); (b) coverage bar (recommend: 85% on pure modules, no global gate initially); (c) mypy strictness (start `--ignore-missing-imports`, strict on new files).
- **Risks:** None real. Do this wing *before or interleaved with* Wing A — hardening without tests is how regressions ship.

### Wing D — Insights & Artifacts (feature depth / demo wow-factor)
- **Goal / impact:** Turns one-off interviews into a progress narrative — the thing that makes the demo memorable and gives returning users a reason to return.
- **Scope:** Analytics dashboard (score trends across interviews, per-competency radar, filler-words/WPM over time — all derivable from `interviews.conversation` + `feedback.feedback_data` already in Neon); shareable feedback (public read-only link with an unguessable token, owner-revocable); resume library (persist parsed resume text per user — today it's re-uploaded and re-parsed every single interview, and the parse cache dies on restart); interview comparison view ("vs your last behavioral").
- **Complexity:** Medium-high (new tables: `resumes`, `share_tokens`; chart rendering; new pages).
- **Effort:** 5–7 days.
- **Key decisions:** (a) chart approach — recommend a tiny dependency-free SVG/canvas approach or Chart.js, not a framework; (b) share-link semantics (expiry? revocation?) — has privacy implications since transcripts are PII; (c) whether resume storage is opt-in (recommend yes, with a delete button — good privacy story for the portfolio).
- **Risks / dependencies:** Schema migrations (use Neon branches to rehearse); share links raise the stakes on Wing A's authorization work — **do Wing A first**.

**Suggested order: C → A → B → D** (or interleave C+A). C first because every later wing merges through its gates.

---

## 5. UI/UX audit

### Page-by-page

- **Landing (`index.html`):** Strong identity — cream palette, gradient hero, the logo ripple micro-interaction is genuinely delightful. Weaknesses: no reflow under 768 px (hero buttons overlap content); no h2 structure; decorative animations ignore `prefers-reduced-motion`; footer is a dead end; no OG/meta tags so shared links unfurl blank.
- **Form (`/start`):** The best page in the app — track-selector cards with per-track accents, conditional sections, drag-drop upload with validation, localStorage persistence (`mockflow_form_v1`) is a thoughtful touch. Weaknesses: the 10–120 s submit wait shows only a small sidebar spinner with no time expectation; no BYOK status/gate (the #1 funnel killer); track cards don't stack on mobile; STAR modal lacks focus trap; upload failure doesn't reset the file input; error path is a raw `alert()` with no link to fix the cause.
- **Interview:** Ambitious and mostly well-executed — stage-progress dots, agent visualizer with blinking eyes, candidate audio spikes, noise warning, Monaco coding panel with timer/attempts, LiveKit CDN-failure fallback UI. Weaknesses: "Connecting…" can sit for 2 minutes with zero narrative and no timeout/recovery; "Waiting for agent…" never escalates; camera-failure placeholder doesn't say *why*; coding "Evaluating…" has no timeout; the 3-column coding layout collapses badly on small screens; mute/skip controls have no ARIA state and no keyboard shortcuts; end-interview modal lacks `role="dialog"` and shows no session stats.
- **Feedback:** Good information design — circular score, competency bars, strength/focus highlights, transcript modal, cached indicator. Weaknesses: generation phases ("Contemplating…") are fake and unbounded — no timeout, no real progress; placeholder before generation undersells the main CTA; no print styles (the one page users would print); markdown rendering lacks code highlighting; 2-panel layout overflows < 600 px.
- **Past calls:** Decent cards + hover lift + a real empty state. Weaknesses: empty-state CTA missing; plain-text loading; raw error strings shown to users; no time-of-day in dates; no search/sort/filter.
- **API keys:** Good provider link-outs, free-tier cost notes, encryption explanation (note: the copy still says keys are stored "in Supabase" — update to Neon). Weaknesses: arrives with no context for first-timers; all five keys look equally mandatory with no per-provider walkthrough; after save you can't verify what's stored (full mask, no prefix); heavy inline styling; the security-info column would shine in a wizard format.
- **Error page:** Friendly but uninformative — no status code, no retry, only "Back Home".
- **Dashboard:** Orphaned — only reachable via the header account chip, and it half-duplicates api-keys. Pick a role for it (recommend: account + stats home).

### Cross-cutting

- **Design system:** Real token foundation in `styles.css` `:root` (good!), but eroding: form.css references `var(--surface-2)`, `var(--border)`, `var(--primary)` that are never defined (these resolve to nothing — i.e., live bugs); modals.css and past_calls.css hardcode rgba values; ~7 button variants and ~4 card patterns exist. Consolidate before adding dark mode.
- **Responsiveness:** feedback (1024 px), past-calls (768 px), api-keys (1200 px) have working breakpoints; landing, form, interview have none. ~60% of pages effectively desktop-only.
- **Accessibility (~40% there):** Biggest gaps in order: modal semantics + focus traps + Esc; ARIA state on toggle controls (mute, skip, track selector should be a radiogroup); heading hierarchy; `:focus-visible` styles; SVG labels; muted-text contrast (`#7A7A7A` on cream is borderline); `prefers-reduced-motion`.
- **Interaction-design principle to adopt:** *every async operation gets (a) an honest time expectation, (b) a visible elapsed/“still working” state, and (c) a timeout with a recovery action.* That single rule fixes the five worst moments in the product.

---

## 6. Testing & CI/CD plan

Current state: `test_db.py` / `test_speech_analytics.py` are ad-hoc scripts (decent ones — `test_db.py` round-trips full CRUD), pytest isn't installed, CI is `py_compile` + file-existence only, and every push to `main` auto-deploys. Goal: every merge gated by lint + types + tests, with a post-deploy smoke check.

### Test pyramid for this codebase

**Unit (fast, no I/O — target ~85% on these modules):**
- `speech_analytics.py` — filler detection, WPM math (port the existing script; pure logic, easiest win)
- `postprocess.py` — `merge_by_agent_turns`, partial-transcript interleaving (feed recorded JSON fixtures — you already have realistic transcript shapes from the old `interviews/*.json`; anonymize one as a fixture before deleting them in fix #2)
- `fsm.py` — stage-transition table per track, skip handling, max-question limits
- `tracks/` — config completeness (every track has prompts, stages, durations)
- `db.py` key-normalization — the camelCase/snake_case fallback chains in `save_interview` (then delete the fallbacks and keep the test)
- `document_processor.py` — extension/MIME validation paths, with tiny PDF/DOCX fixtures

**Integration (Flask test client, DB mocked via monkeypatched `db_client`):**
- **Auth boundary:** parametrized test that every protected route 401s anonymously, and every data route returns nothing for another user's IDs (codifies the IDOR guarantees `get_interview_by_id` already implements)
- `/api/token` with `worker_manager.spawn_worker` mocked: missing-keys path, success path, worker-fail path
- Upload endpoint: size limit, bad extension, happy path
- Error semantics: DB raise → 503 envelope (locks in Wing A's contract)

**DB integration (real Postgres):** convert `test_db.py` to pytest; in CI run against a `postgres:16` **service container** bootstrapped with `migrations/001_initial_schema.sql`. Hermetic, free, and doubles as a migration test. (Neon branching is a fine alternative for pre-prod schema rehearsal, but keep CI self-contained.)

**API contract tests:** lightweight — JSON-schema assertions (via `jsonschema`) on the responses of `/api/token`, `/api/user/interviews`, `/api/feedback/*`, `/health`, run inside the integration suite. Catches the response-shape drift that the current camelCase/snake_case mess proves already happened once.

**Frontend smoke/E2E (Playwright, small on purpose):** landing renders; `/start` renders with track cards and the form validates; protected pages redirect anonymously; past-calls shows the empty state; feedback page renders from a seeded interview. **Don't** try to E2E the live voice flow — it needs real LiveKit/Deepgram/OpenAI; keep that as a 10-minute manual pre-release checklist (documented in the repo) plus the existing `/health`.

### CI pipeline (GitHub Actions)

Rename/extend deploy.yml into:

```yaml
jobs:
  lint:    ruff check . && ruff format --check .
  types:   mypy . --ignore-missing-imports
  test:    pytest -q --cov  (with postgres:16 service for the db marker)
  e2e:     playwright smoke (PRs only, can be allowed-to-fail initially)
  deploy:  needs [lint, types, test]; main pushes only
           → after Render webhook fires, poll https://<app>/health until 200 (post-deploy smoke)
```

Plus:
- **Branch protection on `main`:** require the lint/types/test checks; no direct pushes (PRs only — yes, even solo; the PR is where CI gates you and where `/code-review` runs).
- **`requirements-dev.txt`:** `pytest`, `pytest-cov`, `ruff`, `mypy`, `jsonschema`, `playwright`, `pre-commit`.
- **`pre-commit`:** ruff + ruff-format + a secrets scanner (`gitleaks` or `detect-secrets`) — cheap insurance given the PII/key near-misses found in this audit.
- **`pyproject.toml`** to hold ruff/mypy/pytest config (and fold `runtime.txt`'s intent into documented Python 3.12).
- Keep `keep-warm.yml` exactly as is — it's well built (just remove the `|| true` on the health ping once `/health` is fixed, so a dead site actually fails the workflow and emails you).

### Deployment checks before merging

A 5-line `RELEASE_CHECKLIST.md`: CI green → schema change? run migration on Neon first (rehearse on a Neon branch) → merge → watch Actions post-deploy smoke → click through one interview manually if the change touched the voice path. Rollback = Render's "Rollback" button or `git revert` + push.

---

## 7. Suggested development workflow

Your instinct (branch per wing, not per tiny feature) is right for a solo dev. Refinements:

1. **Two lanes, not one.** *Wing branches* (`wing/hardening`, `wing/ui-overhaul`) for the big initiatives — live for days, merge when the wing's checklist is done. *Fix lane* — tiny branches (`fix/health-endpoint`) cut from `main`, PR'd and merged same-day. Don't trap a 15-minute health-check fix inside a 5-day wing branch; everything in §2 ships through the fix lane this week.
2. **PRs even when solo.** The PR is the choke point where CI runs, `/code-review` runs, and you write the one-paragraph summary that becomes your changelog. Merge with squash so `main` reads as a clean feature-level history.
3. **Rebase wing branches on `main` frequently** (the fix lane will move underneath them).
4. **`main` = production, always deployable.** With Render auto-deploy, merging *is* deploying — that's fine *after* Wing C exists; until then, do the manual smoke after each merge.
5. **Schema changes get rehearsed on a Neon branch** before running on main — this is exactly what Neon branching is for, and you already have the Neon tooling connected.
6. **Tag a release per wing** (`v1.1.0-hardening`) with 3 bullet notes. Cheap, and turns the repo history into a portfolio narrative.
7. **Parallelization:** wings are designed to be independent (C/A backend-ish, B frontend, D full-stack-after-A). If you want to run two at once, use git worktrees and keep one as the "active merge candidate". Sub-agent implementation works well per-wing: plan the wing → feed each checklist item to an implementation agent → review the diff yourself → PR. Don't parallelize A and D (D depends on A's authorization work).

---

## 8. Interview engine (FSM) & coding-track deep-dive

You asked me to actually read `fsm.py` / `agent_worker.py` / `prompts.py` / `tracks/`
and judge the interview experience as a candidate would feel it. I did. Line
references are approximate (the files are large and shift), but the behaviours
are real. This is the part of the product where the gap between "ambitious" and
"trustworthy" is widest — and the coding track is the sharpest edge.

### How an interview actually runs

All four tracks are one FSM with per-stage timers (`STAGE_TIME_LIMITS`) and
minimum-question gates (`STAGE_MIN_QUESTIONS`). The agent advances by **calling a
`transition_stage` tool itself** — i.e. the LLM decides a stage is "done" — with
hardcoded fallback timers as a backstop. Questions are **LLM-generated at session
start**, not drawn from a bank. Tracks expand into per-item stages
(`BEHAVIORAL_Q1/Q2/Q3`, `TECHNICAL_CONCEPTS_1/2/3`, `CODING_PROBLEM_1/2`) gated by
an `active_*_count`. The interview ends when the agent's closing line matches a
regex for "thank you" + "luck".

That last sentence should worry you: **closing detection is a brittle string
match.** If the model says "best of luck" → fine; "all the best" → the interview
never closes and rides the fallback timer. Replace it with a one-token LLM check
("is this a closing remark?") or, better, an explicit `end_interview` tool the
agent calls — the same pattern already used for transitions.

### Coding track — the real problems (highest priority)

This is theatre with no ground truth, and a candidate can feel it:

1. **Problems are invented by the LLM every session, unvetted.** No bank, no
   reference solution, no test cases. Two candidates get different problems
   (unfair to compare), and nothing guarantees the problem is solvable, correctly
   specified, or doable in 15 minutes. **This is the single biggest credibility
   risk in the product.**
2. **"Evaluation" is pure LLM judgment — the code is never executed.** The agent
   reads the submitted code and guesses pass/partial/fail. It can call working
   code broken and broken code working. Candidates can tell, and it undermines
   every other strength.
3. **The 15-minute timer is configured but not enforced or surfaced.** There's no
   countdown to the candidate and no "time's up → evaluate last submission" path,
   while a 4-second silence (`max_endpointing_delay=4.0`) can make the agent think
   the candidate finished mid-thought. The two timing models contradict each other.
4. **Submission feedback is invisible then abrupt.** Code goes to the agent over
   the data channel with no on-screen "Evaluating…", then the verdict arrives only
   as a spoken sentence. Attempt count ("2 of 3") is in the payload but never said
   aloud. Skipping a problem loads the next one **silently** — no "let's move on".
5. **Retries don't learn.** Resubmissions are evaluated independently; the agent
   never references the previous attempt, so the loop doesn't feel like coaching.

**Recommendation — split into quick wins vs redesign:**

- *Quick wins (days):* enforce + surface the timer (emit `time_remaining`, speak
  warnings at 60/30/10s); have the agent speak attempt count and announce skips;
  add an on-screen "Evaluating…" state; raise endpointing delay during coding.
- *Redesign (a wing of its own — call it Wing E, "Interview Integrity"):* a
  **vetted problem bank** (curated problems with reference solutions + test cases,
  selected by role/level/difficulty) and **real execution** of submissions against
  those tests in a sandbox (e.g. a constrained subprocess / Judge0-style runner),
  with the LLM judging *approach* on top of objective pass/fail. Without one of
  these two, the coding score is not defensible — so this should gate any
  "share your results" feature.

### Conceptual gaps across all tracks (what a candidate hits)

- **Skip-stage is half-wired.** `/api/skip-stage` validates and returns a "queued"
  message, and there's a `skip_stage_queue`, but it isn't reliably consumed inside
  `transition_stage` — so the button often does nothing. Either wire the queue into
  the transition logic with an ack back to the UI, or remove the button. A control
  that lies is worse than no control.
- **No "I don't know" / off-topic / "can you repeat?" handling.** The agent marches
  through scripted stages; there's no redirect or graceful-recovery path.
- **`custom_questions` (behavioral) are captured but never asked.** The user fills
  the field and the agent ignores it — a small fix with outsized trust payoff.
- **4-second endpointing cuts off thinkers** in experience/behavioral stages where
  people legitimately pause. Make the delay stage-dependent (longer when thinking
  is expected).
- **Document context is truncated mid-string** (resume/JD sliced at fixed char
  counts), so the agent can reference half-sentences. Truncate on token/word
  boundaries.
- **Feedback grounding:** competency frameworks are selected but the post-interview
  feedback doesn't consistently tie scores back to specific answers, so it can read
  generic.

### Simpler/neater (both cleaner code AND better UX)

- Collapse the `*_Q1/Q2/Q3` and `CONCEPTS_1/2/3` **stage explosion into a single
  parametrised question-loop** keyed by index — ~40% less FSM code and trivially
  extensible to N questions.
- Pull the **magic numbers** (900s problem timer, 3 attempts, 4s endpointing, char
  truncation limits) into one `InterviewConfig` dataclass — one place to tune, and
  it makes A/B-ing interview feel possible.
- The duplicated `get_transition_ack` / `get_fallback_ack` can merge.

**Net:** the conversational tracks (intro/behavioral/technical-voice) are good and
mostly need polish (endpointing, custom questions, closing detection, skip). The
**coding track needs an integrity layer before it's portfolio-defensible** — treat
that as its own wing, sequenced after Wing A (auth/authorization) since "share my
coding result" depends on both.

---

## Appendix A — Findings by severity (consolidated)

**Critical**
- C1 ✓ FIXED — `/health` now pings Neon (`db.ping()`); Supabase check removed — app.py
- C2 ◑ PARTIAL — PII untracked + gitignored; **history rewrite still pending** (deferred to you)
- C3 ✓ FIXED — CI now runs ruff + pytest (23 tests) before the deploy gate — deploy.yml

**High**
- H1 ✓ FIXED — `@require_auth` + `MAX_CONTENT_LENGTH` on the three open endpoints — app.py
- H2 ✓ FIXED — `SECRET_KEY` fallback removed; session/remember cookie flags hardened — app.py
- H3 ✓ FIXED — CORS scoped to `CORS_ORIGINS` — app.py
- H4 ✓ FIXED — security headers via `after_request` (full content CSP deferred to Wing B)
- H5 ◑ MITIGATED — SameSite=Lax + scoped CORS now; token-based CSRF still Wing A
- H6 ☐ Wing A — `db.py` swallows all exceptions → "DB down" indistinguishable from "no data"
- H7 ✓ FIXED — stale docs/CI removed; `docs/ARCHITECTURE.md` is now the single source of truth
- H8 ☐ Wing B — Onboarding: BYOK undisclosed until failure; no loading expectations on 10–120 s waits
- H9 ☐ Wing B — Mobile broken on landing/form/interview

**Medium**
- M1 In-memory caches (conversation/feedback/resume) lost on every restart/cold start
- M2 `worker_manager.spawn_worker` not thread-safe; readiness = "alive after 8 s"
- M3 No rate limiting anywhere (token minting, feedback generation)
- M4 `agent.py` dead code (~1,000 lines) + `supabase_client.py` shim + stale `supabase==2.27.0` dependency
- M5 camelCase/snake_case dual-key handling in `save_interview` — db.py:173-264
- M6 `SELECT *` pulls large JSONB `conversation` columns into list views; no pagination offset
- M7 Accessibility: modals lack roles/focus traps/Esc; no ARIA state on toggles; heading structure absent
- M8 No dark mode; undefined CSS vars in form.css silently failing
- M9 env.template documents 11 unused vars, omits 5 required ones
- M10 Inconsistent API response envelopes; `alert()` for user-facing errors

**Low**
- L1 Duplicated JS utils; console.logs in production; hardcoded URLs
- L2 No request correlation IDs; noisy INFO logging
- L3 No unique constraint on `(user_id, room_name)`; `total_messages` as JSONB
- L4 Hardcoded `"salt_v1"` column (unused by Fernet — remove)
- L5 No OG/meta tags; generic interview page title; no print styles
- L6 `.claude/settings.local.json` tracked; api-keys page copy still says "Supabase"

## Appendix B — Verified env var contract

Required: `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SECRET_KEY`, `ENCRYPTION_KEY` (app boot), plus per-user BYOK keys in DB. Worker subprocess env (set by worker_manager, not you): `LIVEKIT_URL/API_KEY/API_SECRET`, `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `INTERVIEW_ROOM_NAME`. Optional: `MAX_CONCURRENT_WORKERS` (default 10), `FLASK_ENV`. Everything else in the current env.template is read by nothing.
