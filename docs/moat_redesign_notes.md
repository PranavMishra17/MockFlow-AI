# Moat Redesign — "THE DOSSIER" (June 2026)

> Fresh-eyes redesign of the three moat surfaces (feedback verdict, Interview
> Personality, compare) so a new user screenshots and shares them. Hard rules
> kept: no data-contract changes, no interview-page changes, no left-edge color
> stripes, brand tokens from `styles.css`, tests + ruff green, consoles clean.

## The direction (one bold thing)

**The hiring desk keeps a dossier on you.** Every surface reads like a sealed
verdict a hiring committee assembled — editorial, deliberate, a little
broadcast-stat-card, a little case file. The reveal is the *moment the folder is
opened*: a stamped verdict lands, then the evidence writes itself in.

The through-line motif is the brand **orb** — concentric "signal rings" — pushed
everywhere as a radial language: the verdict sits inside a faint ring-field, the
stat band is a player card with a ring sigil, the radar draws from the center
out like a sonar ping. Atmosphere over flat fills: warm cream + grain + soft
ring-mesh, not white boxes on white.

**The one memorable thing:** the **VERDICT STAMP** — the recommendation lands
like an ink stamp inside a concentric ring target, with a "case sealed" eyebrow
and a kicker line. It is the screenshot.

## Palette deltas (additive — all derived from existing tokens)

- Keep the warm cream system (`--bg-cream/-warm/-soft`, `--accent-green*`).
- Add **paper depth**: a global ring-mesh + grain wash behind report stages
  (`--dossier-mesh`, a stacked radial-gradient using accent-green/cyan at very
  low alpha) so backgrounds have atmosphere, never flat `--bg-card`.
- **Ink** = `--text-primary` used as a confident near-black for stamps/kickers.
- Tone stays semantic: green = advance, amber `#E0A100` = on-fence, terracotta
  `#E07A3F` = below-bar. No purple-on-white gradients.

## Type

- **Display:** `Fraunces` (Google Fonts, opsz 9..144, wght 400..900, soft
  slant). Warm, high-contrast editorial serif — authoritative, characterful,
  the opposite of generic Inter. Used ONLY for the big verdict word, the stat
  "player name", section kickers, and headline pull-quotes.
- **Body / data:** keep `Inter` (already loaded) for everything readable +
  tabular numerics. Display is the spice, Inter is the substance.
- New util classes: `.font-display` (Fraunces), heavy tracking-tight on the
  verdict word.

## Motifs / components

- **Ring sigil** (`.ring-sigil`) — a tiny concentric-ring SVG echoing the orb;
  marks the dossier eyebrow on each surface.
- **Verdict stamp** — the reco word in Fraunces inside a radial ring target +
  the 7-point spectrum re-skinned as a "calibrated dial".
- **Player card stat band** — the dashboard stat band becomes one wide trading
  card (Fraunces name, ring sigil, sessions count as the "number"), with the
  countable stats as inset chips. Tactile, screenshot-ready.
- **Evidence cards** — signals restyled as case-file evidence: a band "verdict
  chip", a quoted exhibit in the candidate's own words, monospace exhibit label.
- **Sonar radar** — center-out draw-in + interactivity (below).

## Interactive radar (shared `radar.js` / `radar.css`, API back-compat)

- `build({axes,size,previous,showTarget,compact})` unchanged + additive opts
  `interactive` (default true for non-compact) and `level`.
- Hover/tap an axis → highlights that spoke, shows a tooltip with the
  competency's band + the gap to the target ("Ownership · Borderline · 1 below
  the bar"). Keyboard-focusable hotspots.
- First reveal: a center-out "sonar" draw-in (scale + sweep), reduced-motion
  collapses to a static polygon. Hover lifts the vertex dots.

## "John Doe" live examples (T5 — front-end mock data only)

Brand-new users see the moat before doing anything, each clearly ribboned
**"EXAMPLE — this is what yours will look like"**:
- **Personality** — full sample player-card + radar + best-line on the dashboard
  zero-session empty state.
- **Feedback** — a mini sample hiring-verdict dossier on the feedback empty/error
  state and as a standalone preview.
- **Compare** — a sample two-session compare card on `/compare` when a user has
  < 2 sessions (no ids).
- Mock data lives in `static/john_doe.js` (one shared `window.MockFlowExamples`
  object: a verdict, a 2-session history, an insights blob). No backend.

## What changed per surface (as built — all verified in Chromium, console clean)

- **radar.js / radar.css** — `build()` now emits a soft sonar field + per-axis
  focusable hotspots whose tooltip shows the band + the gap to the target,
  plus vertex dots; a center-out "sonar" draw-in on first reveal; new
  `MockFlowRadar.sigil()` ring sigil. API back-compat (compact/landing radars
  opt out of interactivity). Reduced-motion safe.
- **feedback.html / feedback.css** — page is now a **candidate dossier**: header
  kicker "Candidate dossier / The Hiring Verdict" (Fraunces); the verdict hero
  is a sealed call — a concentric **ring-target stamp** (grade glyph, drop
  animation) beside the recommendation in big Fraunces, a re-skinned
  **calibrated dial** spectrum, a Fraunces pull-quote headline, a dark "TIP THE
  CALL" gap tag; signals became **evidence cards** ("Exhibit 01" mono labels,
  band verdict chips, "what you said" Fraunces quotes); ring-mesh + grain paper
  stage behind it all. IA + data contract + every verify selector preserved.
- **dashboard.js / dashboard.css** — the stat band is now a **candidate /
  trading card**: a banner (ring sigil + latest verdict as the Fraunces "name"
  + a "Signature" strength badge + ghosted ring field) over the countable stats
  as inset chips; section heads carry a ring-bullet; best-lines + verdict in
  Fraunces. All `.pp-stat` / radar / stability / best-line / next selectors kept.
- **compare.html** — Fraunces + the sample compare card on the no-ids path
  (real-id compare unchanged, inherits the sonar radar).
- **john_doe.js (new) + examples.css (new)** — shared `window.MockFlowExamples`
  with a sample verdict / insights / compare blob and three renderers
  (mini dossier, sample personality, sample compare), each badged with an
  **"Example — this is what yours will look like"** ribbon. Wired into: dashboard
  zero-session empty state (personality), feedback not-found/error state (mini
  dossier), `/compare` with no ids (compare). Front-end only — no backend.
- **index.html** — untouched in this pass (its signed-out sample persona already
  reads as an illustrative sample; the John-Doe examples cover the new surfaces).
</content>
</invoke>
