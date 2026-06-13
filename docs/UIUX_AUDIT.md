# MockFlow-AI — UI/UX Audit (per page + per button)

Date: 2026-06-13. Grounded in live Chromium screenshots (light + dark) + code.
"Fix now" items are being addressed in the landing/header redesign branch; the
rest are tracked for follow-up.

## Cross-cutting (fix now)

- **Theme defaults to system, should default to LIGHT.** `header.js applyStoredTheme`
  leaves `data-theme` unset when there's no saved choice, so system-dark users get
  dark. Default to light; dark only on explicit toggle. **[fixing]**
- **Header is cluttered:** five separate icon buttons (info, GitHub, sponsor, theme,
  settings). GitHub/Sponsor/About all already live inside the "About developer"
  modal — collapse info+GitHub+sponsor into a single **About** control. Leaves a clean
  Home · About · Theme · Settings bar, constant across pages. **[fixing]**
- **Dark-mode button text contrast fails** on the landing primary buttons ("Start
  Interview" / "Past Sessions") and auth buttons — near-invisible dark-on-dark. Audit
  every button variant for AA contrast in dark. **[fixing]**
- **Landing animations feel cluttered/unfocused** — needs a more intentional hero +
  staggered load, reduced-motion aware. **[fixing]**
- `free_calls_remaining` is reported even when the free tier is OFF, so the dashboard
  could promise free interviews that don't work. Gate it on `FREE_TIER_ENABLED`. **[fixing, backend]**

## Landing (`index.html`)

- Hero wordmark "MockFlow.ai", tagline, 2×2 feature cards, "POWERED BY" badges, and
  two large game-style buttons (Start Interview / Past Sessions) on the right.
- **Buttons:** Start Interview (primary) — good prominence in light; **unreadable in
  dark**. Past Sessions (secondary) — same. Log In / Sign Up (top-left) — fine in
  light, check dark.
- **Issues:** right-rail buttons feel disconnected from the hero; feature cards are
  tight; footer line is an orphan; decorative animation draws the eye away from the CTA.
- **Fix:** redesign hero so the primary CTA is unmistakable; tie the two actions into
  the hero flow; refine entry animation; ensure dark contrast.

## Form / `/start` (`form.html`)

- Clean two-column: fields + track cards (Intro/Behavioral/Technical/Coding) left,
  Begin Interview + demo notice right. The free-interview onboarding banner shows on top. Good.
- **Buttons:** Begin Interview (primary) — clear. Track cards — good selected state.
- **Minor:** track cards don't stack < 500px; STAR modal lacks focus trap; the
  "Begin" button's loading→timeout states are good (wave 2). Low priority.

## Interview (`interview.html`)

- Agent visualizer, candidate panel, controls (mute/end), Monaco for coding, skip
  controls, connection status + cold-start messaging (wave 2). Keyboard shortcuts M/Esc/Enter.
- **Buttons:** Mute (aria-pressed ✓), End Interview (danger), Skip (per stage), coding
  Submit/Skip. **Issue:** 3-column coding layout doesn't stack on small screens; End-
  interview modal could show session stats. Medium priority.

## Feedback (`feedback.html`)

- Scores, competency bars, strengths/focus, transcript modal, Download-PDF + Copy-as-
  Markdown (wave 1), print stylesheet. Strong.
- **Buttons:** Generate (hero when empty), Download PDF, Copy Markdown, View Transcript.
  **Minor:** code blocks not syntax-highlighted; placeholder could be bolder. Low priority.

## Past Calls (`past_calls.html`)

- Search + track filter + sort, date-with-time, dark cards, skeleton loaders, empty +
  no-results states with CTAs. Polished (wave 1).
- **Buttons:** Start an interview (empty CTA), Clear filters, Retry, sort toggle. Good.

## Dashboard (`dashboard.html`)

- Full-width "Account Settings" + "Interview Personality" (stats, by-track, free badge),
  account card, API-keys status, Manage Keys, Log Out. Polished (post-fix).
- **Buttons:** Manage Keys, Log Out, Start your first interview (empty). **Issue:** free
  badge shows even when free tier is off — gating (above). Low-medium.

## API Keys (`api_keys.html`)

- Provider sections + links, security info, Test/Save. **Issues:** copy still says keys
  stored "in Supabase" (now Neon); no per-provider "where to get this key" walkthrough;
  no first-4-char masked preview after save. Medium — a guided wizard is a future win.

## Error (`error.html`)

- Friendly but uninformative — no status code, no retry, only "Back Home". Low priority;
  add a retry + status context later.

## Priority order

1. (now) light default + header declutter (About box) + dark contrast + landing overhaul + free-badge gating.
2. (next) api-keys copy fix + guided key setup; interview mobile layout; error page context.
3. (later) feedback code highlighting; STAR/transcript modal focus traps.
