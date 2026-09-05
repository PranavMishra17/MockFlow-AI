# Wing D — The Evaluation Moat: Feedback-Loop Redesign

> This is the most important document in the repo. The voice pipeline and the UI are table stakes; **the moat is whether our feedback is good enough that a candidate trusts it like a Bar Raiser would.** It is built on one principle and on five research passes (four in-app agents + a Claude-web deep-research report) into how top companies and high-bar startups actually decide who to hire.

Companion docs: [`EPIC_wingD_insights.md`](EPIC_wingD_insights.md) (code-level "what's dead/dormant" tactical audit), [`DEEP_RESEARCH_PROMPT.md`](deep-research-agent/DEEP_RESEARCH_PROMPT.md) (the prompt used), and the full primary-source report at [`research/feedback_moat_deep_research_2026-06.md`](research/feedback_moat_deep_research_2026-06.md). Sources are cited inline and in the Appendix.

---

## Status & handoff (read first)

**THE MOAT (most important thing in this app):** the feedback loop evaluates a candidate **from the hiring decision** — *"as a {company-type} {role} interviewer at {level}, would I advance you, and what evidence moves that call?"* — not "how did you do." This is what differentiates us; the voice pipeline and UI are table stakes. The full principle is §0; the rubrics are §3.

**Where the research lives:** this doc (synthesised), `docs/research/feedback_moat_deep_research_2026-06.md` (full primary-source report), `docs/deep-research-agent/DEEP_RESEARCH_PROMPT.md` (the prompt; re-run it for the per-cell rubric exemplars / mid-2026 refresh). A new agent should read §0–§5 here before changing the evaluator.

**Where it lives now:** everything is on `main` and **pushed to `origin/main`**. (The original `feat/wing-d-feedback` branch is superseded.)

### Done & verified (committed on the branch)
- **Phase 0** — `feedback_scoring.py` (TDD): research delivery bands + deterministic metrics injected; the hallucinated filler count is fixed. Migration `003_interview_scores.sql` + `db.py` `save_interview_scores`/`get_interview_scores`/`get_user_score_history` (queryable per-session scores).
- **Phase 1** — `feedback.html` delivery panel + coding block (surface what we already compute).
- **Phase 2** — `evaluator.py` (37 tests): the verdict engine — named signals per track×role×seniority, 7-point recommendation + level-read as a **formula over evidence-cited per-signal bands**, evidence-or-`cannot_determine`, down-level-don't-reject, strongest non-interviewer model. `POST /api/feedback/verdict` wires + persists it.
- **Phase 5** — `feedback.html` rebuilt as the **verdict reveal** (Verdict card → signals with your-own-words quotes + "to raise this" → next rep → delivery). Verified in Chromium.
- **Legacy retired** — removed `FEEDBACKSCORES`/`POSTINTERVIEWFEEDBACK`/`build_post_interview_feedback_prompt`, the `/api/feedback/scores` + `/api/feedback` endpoints, `finalize_scores`, and the old `renderScores`/`renderFeedback`. **User-turn stage tags** added in `agent_worker.py`.

### Done — Phase 3 + Phase 4 shipped (2026-06-14, committed to `main`, unpushed)
- **Phase 3 — longitudinal + dashboard + viz: DONE.** `insights.py` emits canonical-competency mapping, trends, cross-track stability (`competency_by_track`), a competency **radar vs a target-level polygon** (`TARGET_BANDS_BY_LEVEL` + `_target_polygon`, keyed off the live 5 `CANONICAL_COMPETENCIES`), lifetime stats, `best_lines`, `reco_series`, `recurring_to_raise`, and the pure `compare_verdicts`. Surfaced as: the rebuilt **feedback reveal** (single-column 4-moment progressive narrative), the rebuilt **Interview Personality** dashboard (stat band + hand-rolled SVG radar + reco sparkline + cross-track stability + best-lines reel + work-on-this-next), the **compare view** (`/compare` + select-to-compare on Past Interviews), and the **signed-in landing teaser** (3 states). Shared SVG radar in `static/radar.js` / `static/radar.css`. `GET /api/user/compare` added (UUID + ownership guards). Richer deterministic delivery stats (sentences, talk-ratio, longest monologue, top crutch word) in `speech_analytics`/`feedback_scoring`; `great_answers` in `finalize_verdict`. All graceful over old rows.
- **Phase 4 — calibration (lightweight): DONE.** `calibration.py` (pure **weighted** Cohen's κ + injected-scorer harness), `gold_set.json` (6 synthetic, band-labelled transcripts across tracks), and few-shot **anchored band exemplars** in `build_evaluator_messages`. CI tests mock the model (offline); the real κ run is `python calibration.py`. The public "calibrated" claim stays gated until the measured κ lands in 0.75–0.90 — user-facing copy remains a "today's-practice read".

### To run live
Run `migrations/003_interview_scores.sql` on Neon. Optionally set `EVALUATOR_MODEL` (defaults to `gpt-4o`; must be a strong model that supports JSON mode). Verdict uses the user's BYOK OpenAI key.

### Gotchas for the next agent
- The Playwright **smoke server caches Jinja templates** — after editing a template, hard-kill `python.exe` (use PowerShell `Stop-Process`; `pkill` misses it on Windows) and restart, or you'll verify stale HTML.
- `feedback.html` render functions are **closure-scoped** (not global) — you can't inject them via `page.evaluate`; drive the real button-click path instead, mocking `/api/feedback/verdict`.
- The verdict's overall recommendation is **recomputed in code** from per-signal bands (`finalize_verdict`) — don't trust the model's own `overall`; it only supplies `confidence` + `headline`.

### Polish backlog (after the first real end-to-end interview, 2026-06-14)

> **Update — second pass (2026-06-14), all committed to `main` (unpushed, per Pranav).** DONE this pass: merged the Part 1/Phase-3-core work onto main (server-side verdict persistence + verdict-based dashboard); **track-aware stage skipping** (fixed the production `ValueError: ... not in list` crash on technical/coding tracks + made the skip dropdown show the correct track's stages, not intro); **interview-page overlap** (stage timer + skip controls hid until the interview is live, no longer collide with the "connecting" card); **verdict badges on the Past Interviews cards**. REMAINING: competency **radar vs target polygon**, **compare view** (2+ sessions / "vs last session"), signed-in landing teaser, and **Phase 4 calibration**.

> **Update — third pass (2026-06-14), all committed to `main` (unpushed), 12 individual commits (C1–C12).** The REMAINING items above are now **DONE**, and the whole surfacing layer was rebuilt from first principles (see "Done — Phase 3 + Phase 4 shipped" above): the competency **radar vs target polygon** (hand-rolled SVG, shared `radar.js`/`radar.css`), the **compare view** (`/compare` + select-to-compare), the **signed-in landing teaser** (3 states incl. zero-session empty state), the richer **personality stats** (total sentences, total fillers + your top crutch word, **GREAT answers**, talk-ratio, longest monologue, best-lines reel), and **Phase 4 calibration** (lightweight). Each surface browser-verified via `tests/e2e/_verify_wingd.py {feedback|dashboard|compare|landing}` against the smoke server (console clean). Full pytest suite green (170+), ruff clean. **The moat is complete.** The only still-open Part-1 item is the subjective **interview-page layout** polish (timer/skip/mic placement) — deferred pending Pranav's direction + a live LiveKit room; independent of the moat.

> **Update — fourth pass (2026-06-14), production-unblock + UX craft, all committed to `main` (unpushed), 5 individual commits (E1–E5).** From a real signed-in session + screenshots, Pranav flagged that the moat surfaces were unpolished and **save was failing in production**. Fixed:
> - **E1 — the production save-failure was infra, not logic.** No `Procfile` → a single synchronous gunicorn worker was blocked for the 15–30 s verdict LLM call, so adjacent `/api/feedback/save` + `/api/user/insights` requests timed out → `503` → empty body → "Unexpected end of JSON input." Added a `Procfile` (gthread, 8 threads, 120 s timeout). **Also**: the feedback page wasn't scrollable — `styles.css` sets `html,body{overflow:hidden}` globally (for landing/interview); `feedback.css` now opts back into `overflow-y:auto`. *(Pranav must point Render's start command at the Procfile.)*
> - **E2 — feedback reading order, re-thought to the moat's "one earned read, then the breakdown."** The session **scorecard** (your *shape* radar + your *delivery* gauges) is promoted to **moment 2**, directly under the verdict hero (was buried in the trajectory fold). The redundant "Your Next Rep" slab — which duplicated the hero's gap-to-next line verbatim — is removed; its action folds into the hero's new **Practice this again** CTA. The session radar gains a **band-bar fallback** for <3 scorable signals so intro sessions never render a degenerate line.
> - **E3 — compare radar degenerate-line fix.** Two cross-track sessions can share <3 canonical competencies (two intros share only communication + domain-rigor), collapsing the overlaid radar to a vertical line. Below 3 shared axes we now render a **slope/dumbbell strip** (older + newer dot per competency on a poor→outstanding track, direction-coloured connector); the radar stays for ≥3 axes.
> - **E4 — Interview Personality UI craft (content unchanged).** Balanced stat band (the best-line tile spans two columns so rows stay even), tactile hover tiles, section-header accent ticks, gradient competency bars, calm consistent cards, centered radar.
> - **E5 — the orb balloon is now a static personality CTA.** Returning users → "Check out your personality →" (`/dashboard`); first-timers (0 sessions) → "Take an interview to unlock your personality →" (`/start`). Driven by the persona teaser's existing insights fetch (dropped the redundant `keys/status` round-trip).
>
> **Cross-cutting decision:** the left-edge colour stripe (Pranav's documented "AI slop" dislike) is now **removed everywhere** — feedback verdict hero, compare session chips, and the dashboard latest-verdict block all express tone via a soft wash + a colour-matched recommendation instead. Each surface re-verified via `tests/e2e/_verify_wingd.py` (console clean; the feedback check now also asserts verdict → scorecard → signals ordering, and the compare check exercises both the radar and dumbbell paths via a 2nd seeded intro session).

A real interview ran on Render and the verdict reveal worked. Two-part fix list from that run:

**Part 1 — interview-flow UX** (`interview.html`, `form.html`, `agent_worker.py`, api-keys)
- [x] **Live captions.** Shipped: stream interim user transcripts via LiveKit's audio-synced `RoomEvent.TranscriptionReceived` (additive + guarded; agents 1.3.6 forwards transcription by default).
- [x] **Form begin-button.** When the form auto-fills from a prior session, Begin stays disabled until a track is re-clicked — enable it on cache restore (`syncRestoredTrack`).
- [x] **API-keys can't be updated.** Was: editing one masked field left the other four as `••••` and `validateKeys()` rejected any masked value → partial update impossible. Shipped: the save path merges with the stored row — a blank/masked field keeps its saved value (`app.py`) — and the client validates only the fields the user actually changed (`static/apikeys.js`). First-time setup still requires all five.
- [ ] **Interview-page layout.** Timer + "Skip stages" placement, the mic/End-Interview buttons, and the orb/candidate panel balance need polish.

**Part 2 — feedback-loop completion** (`feedback.html`, the verdict endpoint, past-interviews, dashboard)
- [x] **Cached feedback not persisting.** Reopening a past session shows no detailed feedback (must regenerate). Fixed: the verdict endpoint now also saves the verdict to the `feedback` table server-side, so `checkCachedFeedback` always loads it.
- [x] **Show the spectrum.** A new user doesn't know where "Leaning No-Hire" sits — render the 7-point scale with the current position marked.
- [x] **Per-signal "i" info.** Each signal card gets an info affordance explaining what the band means + the scope to improve.
- [x] **Past Interviews page.** Verdict badge on each card + **select-to-compare** mode (tick 2 → `/compare`).
- [x] **Interview Personality, surfaced (Phase 3): DONE.** `insights.py` (TDD) aggregates the verdict history into canonical competencies + trends + lifetime stats + best-lines + cross-track stability + radar payload + `compare_verdicts`; `/api/user/insights` + `/api/user/compare`. The dashboard "Interview Personality" is fully rebuilt: stat band (sessions, words, sentences, GREAT answers, fillers + top crutch word, best line), hand-rolled SVG **radar vs the target-level polygon**, reco sparkline, per-competency trend rows, **cross-track trait-stability matrix**, **best-lines reel**, and a **work-on-this-next** action. Plus the **compare view** (2 sessions side by side, deltas, what-improved/what-lags) and the **signed-in landing teaser**. **Phase 4 calibration** shipped (lightweight) — see above.

---

## 0. The principle (the moat)

Today our evaluator asks: *"How did this answer go? How well did they perform, given their resume?"* That produces generic, coarse feedback that any tool can generate.

**We flip the camera.** The evaluator becomes the **interviewer + hiring committee** and asks the only question a real loop answers:

> **"As this company's interviewer for *this role* at *this level*, would I write *strong-hire / hire / no-hire* on this person — and exactly what evidence moves that call?"**

The output is not "how you did." It is **"the hire/no-hire verdict you'd get, the specific evidence that earned it, the level you actually demonstrated, and the specific thing that would flip it up a band."** The research below confirms this is exactly how the rigorous companies operate — and that the early-career decision turns on **how you got there (reasoning, structure, ownership), not whether you reached the optimal answer.** We specialize that judgment per **track × role × seniority**.

---

## 1. What the research established

### 1.1 Why structured, work-sample-style evaluation (the validity base)

The reframe isn't taste — it's the most predictive method we have. Schmidt & Hunter's foundational meta-analysis put **structured interviews at .51 vs .38 unstructured**, and **GMA + structured interview at .63** (Schmidt & Hunter 1998, *Psych. Bulletin* 124(2)). The 2022 reanalysis (Sackett, Zhang, Berry & Lievens, *J. Applied Psych.* 107(11)) revises the absolute numbers **down** (structured ≈ .42, unstructured ≈ .19) but the **ranking holds: structured beats unstructured, and work-sample signals carry the most weight.** Implication for us: dimensions must be **job-relevant and behaviorally anchored**, and **"work-sample" signals (live coding, real debugging, product/DS cases) are the highest-signal thing we measure** — weight them accordingly.

### 1.2 The convergent "evaluation machine" — our evaluator's backbone

Every serious process (Amazon Bar Raiser, Google hiring committee, Meta, Karat, Stripe) runs the **same machine**. We adopt all of it:

1. **A fixed set of named signals** per interview type — not a vibe.
2. **A small ordinal scale with pre-written exemplars per level.** Google's re:Work documents interviewers pre-defining what *"outstanding / solid / borderline / poor"* looks like per dimension. **Discrete anchored bands, never false-precision numbers.**
3. **A 7-point overall band:** *Strong No-Hire → No-Hire → Leaning No-Hire → On-the-Fence → Leaning Hire → Hire → Strong Hire*, plus a written narrative justifying the call.
4. **Level-indexed scope.** The *same* answer scores differently by level; the bar shifts along a **scope/ownership axis, not a knowledge axis** (intern "thinks with guidance" → new-grad "executes a defined task autonomously" → mid "owns ambiguity end-to-end, defends trade-offs, shows emergent leadership").
5. **Every score cites concrete evidence** — the Bar Raiser's *"what data backs that assertion?"*; Karat's *"observable actions, not intent or style."*

> **The single most valuable new insight from the report: an evaluator should DOWN-LEVEL, not reject, when technical signal is strong but scope/ownership evidence is thin.** Our verdict therefore emits a **leveling read** ("this performance clears the new-grad bar but not mid") — far more useful and accurate than a flat pass/fail.

### 1.3 What differentiates hire from no-hire (early-career)

- **Behavioral decides early-career offers.** ~25% of Amazon SDEs who pass the technical bar are cut on behavioral; candidates seldom fail for lack of technical skill. Yet they prep it least. **This is our highest-leverage feedback surface.**
- **The "I vs we" + quantified-impact test is universal.** Strong stories isolate *what I personally did*, anchor to real constraints/stakeholders/metrics, and survive a deep probe ("what did *you* do next? what was the metric exactly?"). Weak stories say "we," carry no metrics, and collapse under follow-up. Stories that don't map to a scoreable signal/principle are *unscoreable → default no-hire*.
- **Coding: trajectory over artifact.** **How a candidate debugs and responds to hints often outweighs reaching the optimal solution**; going silent while coding is a near-universal red flag. interviewing.io's own data: self-assessed communication and "interview feel" are weak predictors; demonstrated problem-handling carries the signal ("talk is cheap"). At **L3–L4 problem-solving + coding dominate; communication gates only at L5+.**
- **PM & DS/MLE: "do they reason about impact, or just produce outputs?"** PM strong-hire = user/problem before solution, metrics defined *from scratch with guardrails/counter-metrics*, signposted structure, handles conflicting-metric follow-ups; no-hire = jumps to features, vanity metrics, rambling. DS/MLE strong-hire = ties every analysis to a product/business decision, frames goal+metric before modeling, rock-solid SQL, evaluation rigor (leakage/drift/calibration); no-hire = correct number with no "so what," shaky SQL joins/cohorting (a frequent hard filter), stats without decision logic.
- **The upside that "raises the bar":** PM = a genuine point of view; DS/MLE = questioning the metric/experiment design; behavioral = self-initiated impact + authentic (un-scripted) conviction. Surface this as a distinct "what would make you a *strong* hire" layer.

### 1.4 The trustworthy-evaluator standard (LLM-as-judge) — non-negotiable

Synthesized from 2025–2026 LLM-judge research (Autorubric; "Scoring Bias in LLM-as-a-Judge" arXiv 2506.22316; "Position Bias in Rubric-Based LLM-as-a-Judge"; GoDaddy calibration; Masood's 2026 rubric/psychometric review). These are **requirements** — a feedback product that hallucinates loses trust instantly (and we have exactly that bug today, §1.6):

1. **Rubric-grounded, criterion-level scoring** with discrete anchors (`MET / PARTIAL / UNMET`, or 1–4) that **roll up by formula** to the signal band and the 7-point overall — never one holistic gestalt number. LLMs calibrate poorly on unbounded continuous scales; don't ask for 73 vs 82.
2. **An evidence quote per criterion** — the model must cite the candidate's verbatim words. Enables error localization and prevents hallucinated assessment.
3. **Compute countable metrics in code and *inject* them** — filler counts, WPM, pause durations, code-test pass/fail, query correctness. "Asking an LLM to count the ums" is a documented hallucination source.
4. **Explicit negative / anti-pattern criteria** to counter the **leniency bias** documented in LLM judges (Autorubric).
5. **Few-shot anchored exemplars** (1 example ≈ +15–20% accuracy; 2–3 ≈ +25–30%), **temperature 0**, **chain-of-thought before the score**, and an allowed **"cannot determine"** verdict when evidence is insufficient.
6. **Bias controls:** randomize option/rubric order; control verbosity, surface-fluency, self-enhancement, and position bias; prefer point-wise anchored scoring. **Judge with a different / stronger model than the interviewer model.**
7. **A human-labeled calibration set**; track judge agreement (Cohen's κ; target ~75–90%); treat ambiguous rubric items as the thing to fix (IRT lens). Only then lean on scores publicly.

### 1.5 Delivery metrics: what's credible vs gimmick (with real bands)

Only a narrow set of delivery metrics has research support. Compute these **deterministically** and coach with a target band + one technique:

- **Filler / disfluency rate:** **green ≤ ~5/min; flag ~12/min+** (Laske et al. 2024, *JABA*, DOI 10.1002/jaba.1093 — 12/min measurably hurt perceived effectiveness; 5/min did not). Base rate ≈ **1 filler per 100 words** (Bortfeld et al. 2001). **Coach toward a low *nonzero* rate, never zero** — fillers also cue listeners to upcoming complexity.
- **Speech rate (WPM):** advisory **green ≈ 130–160 for dense/technical content; flag sustained > ~190** (Griffiths 1990 — comprehension degrades at ~200 but not 150/100; ~150 wpm conversational average). **Advisory only** — Griffiths tested non-native listeners; native speakers tolerate far higher. Never punitive.
- **Pauses, conciseness, structure:** comprehension-supported; score structure/conciseness as *content*.

**Inferred / soft** (allowed only as clearly-labeled qualitative LLM judgment, never a precise score): tone, energy, "confidence."

**Forbidden — the HireVue line:** facial/affect scoring and "emotion/confidence-from-face-or-voice." HireVue's *own* chief data scientist found nonverbal data added ~**0.25%** predictive power (~4% even for highly-interactive roles); HireVue discontinued visual analysis (2020/announced 2021) and faced an FTC/EPIC complaint and 2026 FCRA scrutiny. Expert consensus: facial analysis "has never been an independently and scientifically validated predictor." **We never score face/affect and never claim to predict a hiring outcome.**

### 1.6 The live bug to fix first

`scores.filler_word_count` is currently **LLM-invented** — `speech_analytics.py` computes the real value and `app.py` even returns it in the payload, but the `FEEDBACKSCORES` prompt (`prompts.py`) never receives it. This is the §1.4.3 violation in production and is **Phase 0.**

---

## 2. Where we are vs where this goes

| | Today | Wing D target |
|---|---|---|
| Lens | "how was the performance" | "would I hire you, why/why not, and at what level" |
| Rubric | one flat `FEEDBACKSCORES` + free-text | named signals **per track × role × seniority**, anchored bands |
| Evidence | none | every criterion cites a transcript quote |
| Leveling | none | explicit down-level read on the scope/ownership axis |
| Countable metrics | computed, **not shown**, filler **hallucinated** | computed in code, injected, surfaced with research-based bands |
| Coding | `evaluation_result` stored, **never rendered** | full coding verdict, grounded in real pass/fail (Piston) |
| Richer engine | `TRACK_FEEDBACK` schema built but **dormant** | activated as the per-track verdict |
| Across sessions | none | trends + cross-track comparison + target-level benchmark |
| Model | interviewer model also judges | strongest, **non-interviewer** model; calibrated to a gold set |

---

## 3. The evaluator redesign — per track × role × seniority

### 3.0 Retire the legacy model (first-principles reset)

This **replaces**, not augments, the old feedback system. We delete from the user-facing model:
- the `FEEDBACKSCORES` **1–5 "overall_score"** and its **LLM-invented ad-hoc competencies** ("Technical Skills", etc.) — a number that maps to nothing in hiring;
- the separate free-text **narrative essay** (`build_post_interview_feedback_prompt`) that didn't reinforce the scores;
- any score **without an evidence quote**.

What we keep: the Phase 0/1 **measurement substrate** (deterministic delivery metrics, persistence, the delivery + coding panels). The verdict *is* the feedback now; the old gauge-plus-essay is gone.

### 3.1 Architecture

One **evaluator service**, parameterized and assembled from composable rubric blocks:

```
verdict = evaluate(
   track,                 # intro | behavioral | technical_voice | coding
   role,                  # swe | pm | ds_mle
   seniority,             # intern | new_grad (L3) | mid (L4–L5)
   company_archetype,     # big_tech | high_bar_startup  (shifts weighting & values)
   transcript,            # stage-interleaved
   deterministic_metrics, # WPM, fillers, pauses, attempts, pass/fail  ← computed in code
   coding_eval_result,    # objective Piston pass/fail when track == coding
)
```

- Track → signal set; role → flavor/applicability; seniority → per-signal scope exemplars; archetype → weighting (Stripe inverts coding weighting; Anthropic/OpenAI gate on authentic values).
- **Down-level, don't reject:** if technical signal is strong but scope is thin, the verdict says "clears new-grad, not mid," not "no-hire."
- Evaluator = strongest available model, **distinct from the interviewer model**. Temp 0, CoT-before-score, few-shot anchored. This is the dormant `TRACK_FEEDBACK` schema activated and extended.

### 3.2 The shared verdict contract

```jsonc
{
  "overall": {
    "recommendation": "strong_no_hire … strong_hire",   // 7-point band
    "confidence": "low | medium | high",                 // banded, not a %
    "level_read": "below_intern | intern | new_grad | mid | above_mid",  // scope/ownership axis
    "headline": "one calm sentence, hiring-manager voice"
  },
  "signals": [{
    "name": "Problem solving",
    "band": "poor | borderline | solid | outstanding",
    "criteria": [{ "check": "stated approach + complexity before coding",
                   "verdict": "met | partial | unmet",
                   "evidence": "verbatim quote" }],   // evidence REQUIRED per criterion
    "reasoning": "why this band, interviewer voice",
    "to_raise": "the specific thing that moves this up one band"
  }],
  "differentiators": ["what would make this a STRONG hire, not just a hire"],
  "delivery": {                                         // deterministic, code-filled
     "wpm": 178, "wpm_band": "130–160 (flag >190)",
     "filler_per_min": 9.1, "filler_band": "≤5 good, ~12 hurts",
     "longest_monologue_s": 95, "qualitative_note": "tone/energy — labeled inferred"
  }
}
```

Hard rules: **no quote → no criterion score**; **`delivery` is never produced by the LLM**; the model may return **`cannot_determine`** rather than guess.

### 3.3 Behavioral track (highest leverage) — Amazon-LP lens, role/archetype flavored

| Signal | What's being decided | Strong-hire evidence (quote-worthy) | No-hire | Level shift |
|---|---|---|---|---|
| Ownership | Will they own outcomes? | "I decided…, I measured…, when it broke I…" | "we" everywhere, vague role | intern owned a task → NG a feature → mid an ambiguous project |
| Evidence/metrics (STAR) | Real & quantified? | "Reduced p99 latency 38% by isolating one query" | collapses under "what did *you* do next?" | probing depth rises with level |
| Signal mapping | Maps to a scoreable principle? | clearly demonstrates the targeted LP/value | story doesn't map → unscoreable → no-hire | mid: multiple LPs per story |
| Conflict/collaboration | Authentic, low-ego? | empathy for the other side, disagree-then-commit | avoids, blames teammates, proves they were right | mid: cross-team influence |
| Authenticity | Internalized vs rehearsed? | specific, un-scripted, real stakes | "clean, complete, emotionally flat" = memorized (esp. Anthropic/Stripe gate) | constant |

### 3.4 Coding track — Google's 4 dims, our weighting from the 100K data

| Signal | Strong-hire | No-hire (even if solved) | Level shift |
|---|---|---|---|
| Problem-solving (primary) | restates problem, approach + complexity *before* coding, weighs alternatives | jumps to code, no plan, stuck without hints | intern reasons w/ guidance → NG independent → mid structures ambiguity |
| Coding (primary) | clean, idiomatic, modular, mentally compiles | syntax flailing, can't translate plan | NG functional → mid clean/maintainable/extensible |
| Testing/verification (differentiator) | tests normal + corner cases unprompted, self-corrects | declares done untested | mid discusses regression/edge risk |
| Response to hints (coachability, weighted) | integrates hint and accelerates | ignores, repeats stuck approach | constant |
| Communication (multiplier; gates L5+) | narrates trade-offs, clarifying Qs | silent coding, defensive | mid must explain *why* not *what* |

**`high_bar_startup` (Stripe/Anthropic):** invert weighting — complexity carries little weight; **clean, complete, PR-approvable working code + a testing instinct + fast orientation in unfamiliar code** dominate. Stripe's loop is practical (**Bug Squash** = debug failing tests in a large unfamiliar codebase; **Integration** = build something real). **Rewriting instead of surgically debugging is an explicit auto-fail.** "Efficiency, not speed." Anthropic: build-then-extend in a shared Python env, working code over elegance ("don't invent a spaceship if all we need is a bicycle"), **AI banned during live rounds.**

### 3.5 Technical (voice) track — role-defined

- **SWE:** CS fundamentals depth, trade-off reasoning, explains *why* (invariants, complexity) out loud, junior design reasoning.
- **PM:** *Product sense* (user/problem → segmentation → prioritized pains → v1 by impact-vs-effort) and *Analytical/execution* (**define metrics from scratch**, set guardrails/counter-metrics, reason through metric conflicts — GAME scaffold). Strong = starts from the user and drives; no-hire = solution-first, vanity metrics, no structure.
- **DS/MLE:** statistics with **decision logic** (success criteria, multiple-metric handling), ML depth **with evaluation rigor** (leakage/drift/calibration/offline→online), SQL fundamentals (window functions, correct event-data joins/cohorting), experimentation (guardrails, novelty/network effects), and **connecting every result to a ship/no-ship decision**. ML system design (mid+) = "think like a production engineer, not a researcher."

### 3.6 Intro track

Lower stakes, real signals: motivation/authenticity, communication & structure, role/company fit, baseline self-awareness. Feeds the longitudinal communication baseline (§4) more than a hire call.

### 3.7 Seniority scaling (scope/ownership axis — the level-read exemplars)

| | Intern | New-grad (L3/E3) | Mid (L4–L5/E4–E5) |
|---|---|---|---|
| Behavioral | potential / learning agility; class projects OK | early execution + self-awareness; individual/team stories | multi-person/team impact; conflict at "direction" altitude |
| Coding | correct, readable; a hint or two expected; optimal not required | clarifies reflexively, clean & optimal, talks through | candidate **leads** — invariants, edge cases, complexity unprompted |
| PM | structured with guidance | crisp framework + user empathy + metrics = the bar | a genuine point of view; drives ambiguity, cross-functional influence |
| DS/MLE | solid stats/SQL fundamentals + one strong project | connects stats→experiment, owns a metric | proposes tradeoffs unprompted; questions the metric definition; owns model lifecycle |

---

## 4. Cross-interview comparison & longitudinal model

The user explicitly wants to compare interviews (different tracks, same user, improvement/regression over time). This needs a **stable competency taxonomy that spans tracks** so scores are comparable session-to-session.

- **Canonical competencies** (each track maps its signals onto these): `communication`, `structure`, `ownership_impact`, `problem_solving`, `technical_depth`, `domain_rigor` (role-specific), `delivery` (deterministic). Same anchored scale → comparable.
- **Persist per-session, per-competency bands + the level-read + deterministic metrics** (today scores aren't stored in a queryable shape — Phase 0). Prerequisite for everything longitudinal.
- **Trend = rolling per-competency band over the last N sessions (require ≥3 before declaring a direction);** flag improving/flat/regressing with the delta.
- **Cross-track insight (uniquely ours):** normalize all tracks to one scale and chart a single competency across them — e.g. "your communication is *solid* in behavioral but drops to *borderline* in coding under time pressure" — revealing trait stability vs context-dependence.
- **Benchmark vs target:** each competency as **you vs the target-role/level band** (the §3.7 exemplars define the band) — the "would I get hired for the role I'm aiming at" view.
- **Differentiator memory:** recurring `to_raise` items across sessions become the headline "work on this next."

---

## 5. Surfacing it to users — the moment the interview ends (Phase 5)

First principle: when the interview ends the user is anxious and wants **one** thing first — *"would I have gotten it?"* So feedback is a **progressive reveal**, not a dashboard dump (Wispr lesson: *calm surface, one earned read; hide the machinery*; learning-analytics lesson: *insight without a next action fails*).

**The four moments (the rebuilt `feedback.html` flow):**

1. **Moment 1 — the Verdict card (instant, the emotional core).** *"Where you'd land in a real {archetype} {role} loop **today**: **Lean Hire** · performing at **new-grad** level — *'Strong problem-solving, but ownership stayed vague.'*"* The 7-point band + confidence + **level-read** + one hiring-manager sentence. Always paired with **the gap to the next band** so it's constructive, never a dead-end grade. It is a *today's-practice read*, never a "you will/won't be hired" claim (HireVue line).
2. **Moment 2 — the signals, with your own words (the trust-builder).** Scrollable cards: each named signal → band → **a verbatim quote from your transcript** → the one **"to raise this"** move. Citing the candidate's own words is what makes it feel like a coach who *listened*, not a generic scorer. Reveal progressively, not all at once.
3. **Moment 3 — your next rep (drives return).** The single highest-leverage fix (lowest signal / recurring gap) + a **"practice this again"** CTA that pre-fills the same track/role/level.
4. **Moment 4 — your trajectory (personal + longitudinal).** "vs your last session" delta + the saved report they can revisit. Plus the **delivery panel** (Phase 1) and **coding block** (Phase 1) fold in as supporting evidence under the verdict.

**Profile / "Interview Personality" → behavioral profile:** a **competency radar** with overlays for *current vs previous* and *vs a target-level reference polygon* ("the L4 SWE bar"); **per-competency trend lines**; cross-track comparison; recurring filler/pacing patterns; a **mastery checklist** driving one prioritized next action. Surfaced on the landing page so new users see where they're headed.

**Compare view:** pick 2+ sessions (any tracks) → side-by-side signal bands + deltas + "what improved / what still lags."

**Anti-patterns we delete:** the 1–5 overall_score and ad-hoc competencies; the disconnected narrative essay; any score without an evidence quote; emotion/face scoring; "you'll get hired" claims; a dump of charts with no next action.

---

## 6. Implementation plan (grounded in our code)

File-level wiring in [`EPIC_wingD_insights.md`](EPIC_wingD_insights.md).

- **Phase 0 — Stop lying, start persisting.** Inject `speech_analytics` values into the feedback prompt (`prompts.py`) to kill the hallucinated filler count; persist per-session per-competency bands + level-read + deterministic metrics to a queryable table (`db.py` + migration). Add user-turn stage tags (today only agent turns are tagged in `agent_worker.py`, so per-stage evidence needs interleaving otherwise).
- **Phase 1 — Surface what we already compute.** Render the delivery panel (E1) + coding block (E3) in `feedback.html`. Pure frontend + payload we already send.
- **Phase 2 — The evaluator redesign (replaces the legacy scorer, §3.0).** New `evaluator.py` producing the §3.2 verdict contract; **retire `FEEDBACKSCORES` (1–5 + ad-hoc competencies) and the standalone narrative essay.** Hiring-decision-lens prompt with criterion-level anchored scoring, **evidence-quote-before-band**, negative/anti-pattern criteria, few-shot exemplars, temp 0, role+seniority+archetype params, and the **down-level read**; route to the strongest **non-interviewer** model. Wire Piston `evaluation_result` into the coding verdict. Persist the verdict (extend `interview_scores`).
- **Phase 3 — Longitudinal & dashboard.** Canonical competency mapping, trends (≥3 sessions), cross-track compare, radar + target-polygon, "work on this next." Rebuild the Personality view; surface on landing.
- **Phase 4 — Calibration.** Human gold set; measure κ; tune to 75–90%; re-check periodically (and re-verify mid-2026 interview shifts, §7) before leaning on scores publicly.

---

## 7. Mid-2026 watch items (re-verify each product cycle)

The deep-research report is now incorporated (§§1–5). Live shifts to track, because they change what "good" looks like:

- **Meta** added a live **AI product-sense round** (prototype with an internal Llama "vibe-coding" tool, defending prompting/latency/token trade-offs) and reportedly **piloted an AI-assisted coding round** replacing one onsite coding interview.
- **Candidate AI-use bans during live rounds** (Anthropic, Meta OA monitoring) — even as companies encourage AI for *prep*. Our coaching should reflect both realities.
- **Validity numbers are contested** — use the *relative ranking* (structured > unstructured; work-sample is strong), not absolute coefficients.

A future deep-research refresh should chase any **primary, published rubric docs** (most FAANG internal rubrics are confidential; the tables above are informed reconstructions from high-quality secondary/insider sources) and the evolving AI-in-interview norms.

---

## Appendix — sources

**Validity & structure:** Google re:Work structured-interviewing guide (primary); Schmidt & Hunter 1998 *Psych. Bulletin* 124(2) (primary; .51/.63); Sackett, Zhang, Berry & Lievens 2022 *J. Applied Psych.* 107(11) (primary; revised ≈.42).

**Behavioral:** Amazon "Life at AWS — Bar Raiser" (primary); Meta signals + "Scope" (ex-Meta interviewer Austen McDonald); Google four attributes/Googleyness (Bock, *Work Rules!*); interviewing.io [Amazon LP guide](https://interviewing.io/guides/amazon-leadership-principles) & [Anthropic guide](https://www.implicator.ai/at-anthropic-the-culture-interview-is-the-top-late-stage-hiring-gate/); Pragmatic Engineer [1,000 interviews](https://newsletter.pragmaticengineer.com/p/learnings-from-conducting-1000-interviews).

**Coding:** [Google coding rubric (Exponent)](https://www.tryexponent.com/blog/google-coding-interview-rubric) + [Tech Interview Handbook](https://www.techinterviewhandbook.org/coding-interview-rubrics/); interviewing.io [100K study](https://interviewing.io/blog/does-communication-matter-in-technical-interviewing-we-looked-at-100k-interviews-to-find-out) & [600 interviews](https://interviewing.io/blog/ive-conducted-over-600-technical-interviews-on-interviewing-io-here-are-5-common-problem-areas-ive-seen); [Stripe (Exponent)](https://www.tryexponent.com/guides/stripe-software-engineer-interview); amazon.jobs SDE leveling (primary); [L5 (Codeintuition)](https://www.codeintuition.io/blogs/google-l5-coding-interview).

**PM & DS/MLE:** [Meta PM (Exponent, 2026)](https://www.tryexponent.com/guides/meta-pm-interview); [Google APM (Exponent)](https://www.tryexponent.com/guides/google-apm-interview); [Lenny on interviewing PMs](https://www.lennysnewsletter.com/p/how-to-interview-product-managers); [DS guide (Exponent)](https://www.tryexponent.com/blog/data-science-interview-guide); [ML system design (HelloInterview)](https://www.hellointerview.com/learn/ml-system-design/core-concepts/evaluation).

**Voice/communication (primary research):** Laske et al. 2024 *JABA* (DOI 10.1002/jaba.1093 — disfluency rate); Bortfeld et al. 2001 *Language and Speech* 44(2) (~1 filler/100 words); Griffiths 1990 *Language Learning* 40(3) (WPM comprehension); HireVue discontinuation — *Fortune* (Zuloaga, 0.25%/4%) & [SHRM](https://www.shrm.org/topics-tools/news/talent-acquisition/hirevue-discontinues-facial-analysis-screening); [Yoodli](https://yoodli.ai/blog/ai-speech-coaching-explained) & [Wispr Flow](https://en.wikipedia.org/wiki/Wispr_Flow) (vendor; raw counts only).

**LLM-as-judge:** Autorubric, "Scoring Bias in LLM-as-a-Judge" (arXiv 2506.22316), "Position Bias in Rubric-Based LLM-as-a-Judge", criterion-validity work (2025–2026, primary); [Evidently](https://www.evidentlyai.com/llm-guide/llm-as-a-judge), [Arize](https://arize.com/llm-as-a-judge/), [Confident AI](https://www.confident-ai.com/blog/why-llm-as-a-judge-is-the-best-llm-evaluation-method); GoDaddy calibration; Masood 2026 rubric/psychometric review.

**Dashboards:** Springer/ACM "Competency Dashboard"; Paulsen & Lindsay 2024 systematic review; Kaliisa et al. 2023 checklist; [Coursera Skills Dashboard](https://www.coursera.org/business/products/skillsdashboard); [Skillsoft benchmark](https://documentation.skillsoft.com/en_us/percipio/Content/A_Administrator/admn_dash_skill_benchmark.htm).

**Full report (in repo):** [`research/feedback_moat_deep_research_2026-06.md`](research/feedback_moat_deep_research_2026-06.md).

### Caveats
- FAANG internal rubrics are **confidential**; the §3 tables are **informed reconstructions** from high-quality insider/secondary sources, not official documents.
- Sackett 2022 **lowers** the historic validity coefficients — use the relative ranking, not absolute numbers.
- NCVS ~150 wpm is widely cited but unconfirmed at the primary source; Griffiths tested **non-native** listeners — WPM bands are **advisory**.
- HireVue's 0.25%/4% are **company-stated/journalist-reported**, not peer-reviewed — cite as HireVue's own admission.
- Vendor metric claims (Yoodli, Wispr) are largely self-reported; only filler-rate and WPM primitives have independent support, and even those are coaching signals, **not** hire/no-hire determinants.
