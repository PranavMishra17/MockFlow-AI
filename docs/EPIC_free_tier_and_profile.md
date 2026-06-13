# Epic — Free Tier, Profile/Personality & Polish

Branch: `feat/free-tier-and-profile` (off `fix/immediate-hardening`).
Source: `docs/PRODUCT_AUDIT_2026-06.md` §3 (easy wins) + owner requests (free trial, Wispr-Flow-style profile).

## Decisions (locked)

- **Free tier:** build now, behind a flag; live E2E once owner keys are wired in (owner's keys may be stale).
- **Cap:** 2 interviews per verified email + a global monthly $ kill-switch.
- **Cost:** ~$0.07–0.10 / interview marginal (voice dominates; LiveKit ~free under its 5,000 min/mo tier). 2 free calls ≈ $0.15–0.20 / user. 200 free users/mo ≈ $30–40. Cost is not the risk — abuse is, hence the email cap + monthly ceiling.

## Workstream 1 — Free Tier (backend DONE this branch)

Implemented and unit-tested (`tests/test_free_tier.py`, 13 tests):

- `migrations/002_free_tier_and_stats.sql` — `users.free_calls_used/granted`, `free_tier_usage(month, calls)`.
- `db.py` — `get_free_calls`, `consume_free_call` (atomic, guards `used < granted`, bumps monthly counter), `free_calls_this_month`, `get_user_stats`.
- `app.py` — `FREE_TIER_ENABLED` + `FREE_TIER_MONTHLY_MAX_CALLS` config; `_system_keys()`, `free_tier_available()`, `resolve_interview_keys()` (BYOK first, else owner free tier), `resolve_openai_key()` (owner-key feedback for free users). `/api/token` consumes a credit only on successful worker spawn and tags the room `is_free_call`. `/api/user/stats` endpoint; `/api/user/keys/status` now reports `free_calls_remaining`.

**Remaining (needs working owner keys):** set `FREE_TIER_ENABLED=true` + `SYSTEM_*` env vars on Render, run migration 002 on Neon, then live E2E one free interview + feedback. Frontend surfaces the "X free interviews left" badge and lets keyless users start (Workstream 3).

**Design notes:** credit decrements at successful spawn (abandoned setups don't burn one; an abandoned *started* call does — acceptable and anti-abuse). Email uniqueness on `users` bounds farming. Kill-switch pauses free tier once the month's count hits the ceiling.

## Workstream 2 — Profile / "Interview Personality"

Today the dashboard shows only name + API-key status. Data already available: interview count + tracks (`interviews`), avg score (`feedback.feedback_data.overall_score`), speech analytics (`speech_analytics.py`: signature filler, WPM/pace), recency/streak. `/api/user/stats` now serves counts, tracks, avg score, last date, and free-calls balance.

Widget set: total interviews, average score, by-track breakdown, free-calls-remaining badge, and (where feedback data exists) strongest/focus competency + a pace label. Built by a dedicated frontend agent on `dashboard.html`/`dashboard.js` (+ its own `dashboard.css`) consuming `/api/user/stats`.

## Workstream 3 — Onboarding + 12 polish wins

Mapped to disjoint files for parallel agents (audit §3). Shared-file hotspots (`app.py`, `db.py`, `styles.css`, `header.js`, `modal.js`) are owned by the foundation pass; page agents own their template + page CSS/JS only.

## Rollout (parallel sub-agents, Fable/Opus — never Haiku)

- **Wave 0 (done):** backend free-tier + stats foundation.
- **Wave 1 (parallel, disjoint files):** dashboard personality (`dashboard.*`), past-calls search/sort/empty/skeleton (`past_calls.*`), feedback print/export + meta (`feedback.*`). Each adds its own page meta tags + small local helpers.
- **Wave 2 (shared files, sequenced):** dark-mode tokens + toggle (`styles.css`, `header.js`), toast util (`modal.js`), onboarding BYOK gate + cold-start messaging (`form.html`, `interview.html`, consuming `/api/user/keys/status`), keyboard shortcuts (`interview.html`), shared `utils.js` dedupe.

Each wave: verify `pytest` + `ruff` green, manual sanity, commit. PRs merge to main behind CI gates.
