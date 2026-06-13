# Wing D — The Evaluation Moat: Feedback-Loop Redesign

> This is the most important document in the repo. The voice pipeline and the UI are table stakes; **the thing that makes MockFlow defensible is whether our feedback is good enough that a candidate trusts it like a Bar Raiser would.** Everything here is built on one principle and four parallel research passes into how top companies and high-bar startups actually decide who to hire.

Companion docs: [`EPIC_wingD_insights.md`](EPIC_wingD_insights.md) (the code-level "what's dead/dormant" tactical audit) and [`DEEP_RESEARCH_PROMPT.md`](DEEP_RESEARCH_PROMPT.md) (the Claude-web deep-research prompt whose report folds into §3 rubric tables). Research sources are in the Appendix.

---

## 0. The principle (the moat)

Today our evaluator asks: *"How did this answer go? How well did they perform, given their resume?"* That produces generic, coarse feedback ("good communication, work on structure") that any tool can generate.

**We flip the camera.** The evaluator becomes the **interviewer + hiring committee** and asks the only question that matters in a real loop:

> **"As this company's interviewer for *this role* at *this level*, would I write *strong-hire / hire / no-hire* on this person — and exactly what evidence moves that call?"**

The output is no longer "how you did." It is **"here is the hire/no-hire verdict you'd get, the specific things that earned it, and the specific things that would flip a no-hire to a hire."** That reframing is the moat. It only works if it is grounded in what real interviewers are trained to look for — which is what the research below establishes — and specialized per **track × role × seniority**, because the bar genuinely differs across those.

---

## 1. What the research established

Four parallel research passes (behavioral bars, coding bars, PM + DS/MLE bars, and voice-AI/LLM-judge standards). The striking result: **the rigorous companies all run the same evaluation machine.**

### 1.1 The convergent "evaluation machine" — our evaluator's backbone

Every serious process (Amazon Bar Raiser, Google hiring committee, Meta, Karat) shares four properties. We adopt all four:

1. **A fixed set of named signals** per interview type — not a vibe. (Meta scores 8 named behavioral focus areas; Google scores 4 attributes; Google coding scores 4 dimensions.)
2. **A small ordinal scale with pre-written exemplars per level.** Google literally grades on *poor / borderline / solid / outstanding* with a written description of what each looks like per attribute. **Discrete bands, never false-precision numbers** (the LLM-judge research independently says the same: don't ask for 73 vs 82).
3. **Level-indexed scope.** The *same story or solution* scores differently by level. Meta defines each signal's bar separately for new-grad vs mid vs senior (e.g. "proactivity" = a solo task at junior → 2+ teams at staff). Amazon scales Scope, Contribution, Impact, Difficulty together.
4. **Every score must cite concrete evidence.** Amazon Bar Raisers throw out gut feeling and demand *"what data backs that assertion?"*; Google requires written notes so the committee can re-judge from evidence; Karat (2026) scores **"observable actions, not intent or style."**

> **Design takeaway:** our verdict is *named signals → ordinal band with exemplars → level-scoped → each band justified by a transcript quote.* That single sentence is the whole evaluator.

### 1.2 What differentiates hire from no-hire (cross-cutting, early-career)

- **Behavioral is where early-career offers are decided.** ~25% of Amazon SDEs who *pass* the technical bar are cut on behavioral; "candidates who didn't get offers seldom failed because they lacked technical skill." Yet candidates prep ~95% technical / ~5% behavioral. **Our biggest value-add is rigorous behavioral feedback.**
- **The universal "I vs we" + impact test.** Top answers isolate *what I personally did*, anchor to real constraints/stakeholders/timelines, and **quantify impact**. The single most-cited weak signal everywhere: no metrics, fuzzy ownership, stories that collapse under a follow-up probe.
- **Coding: trajectory over artifact.** From 100K interviews, at **L3–L4 coding & problem-solving dominate and communication is a *tiebreaker*, not a gate** (a 4-4-2 advances 96%; a 3-3-4 is 3× more likely rejected) — but communication becomes load-bearing at L5+. What tanks the signal *even on a solved problem*: jumping to code, going silent / half-thoughts, no clarifying questions, can't reason about complexity live, never tests, defensive on hints. **Handling a hint well is scored as coachability, not penalized.**
- **PM & DS/MLE: "do they reason about impact, or just produce outputs?"** PM strong-hire = segment-first, structured, metric-grounded, states tradeoffs, drives the conversation; no-hire = rambling/feature-listing, opinion without a framework, "what should I do next?" (reads as no ownership). DS/MLE strong-hire = ties stats/ML/SQL to a business decision, states assumptions, proposes tradeoffs unprompted; no-hire = "knows the algorithms" but can't connect to product, jumps to a model before defining the problem/metric.
- **The upside that "raises the bar":** PM = a genuine point of view; DS/MLE = questioning the metric/experiment design; behavioral = self-initiated impact and authentic (un-scripted) conflict handling. Worth surfacing explicitly as the "what would make you a *strong* hire, not just a hire" layer.

### 1.3 The trustworthy-evaluator standard (LLM-as-judge) — non-negotiable

The voice-AI research converged on 2025–2026 best practice. These are **requirements**, because a feedback product that hallucinates loses trust instantly (we already have this bug — see §1.4):

1. **Compute countable metrics in code and *inject* them.** Never ask the LLM to count fillers, WPM, pauses, attempts, or pass/fail. "An evaluator that doesn't receive the value isn't measuring it."
2. **Rubric with concrete anchors + examples** per dimension (the §1.1 machine).
3. **Reasoning + an evidence quote from the transcript *before* each score** (audit trail; G-Eval/CoT).
4. **Decompose holistic scores into atomic yes/no checks**, aggregate by formula — not one gestalt number.
5. **Structured JSON** per dimension: `{dimension, band, reasoning, evidence_quote}`.
6. **Discrete bands over fake-precise numbers.**
7. **Judge with a different / stronger model than the interviewer model** (avoid self-family bias). Our interview agent and our evaluator should not be the same model instance; the evaluator should be the strongest model available.
8. **Mitigate verbosity & position bias**; **calibrate to a human gold set** (200–500 labeled traces, ≥2 annotators, target 75–90% agreement / Cohen's κ ≥ 0.6) before we trust scores at scale.

### 1.4 Communication metrics: real vs gimmick (and a live bug)

Transcript-grounded, **defensible** → compute deterministically and coach with a target band + one technique (the Yoodli model: "13% fillers → aim ≤4% via deliberate pauses", "180 WPM → slow to ≤170"): **WPM/pace, filler-word rate, pause usage, conciseness, answer relevance, STAR/structure completeness.**

Inferred/soft → allowed only as **clearly-labeled qualitative** LLM judgment, never a precise score: **confidence, tone, energy.**

**Forbidden (the HireVue lesson):** facial/emotion scoring and any *"this predicts you'll be hired"* claim. HireVue's facial analysis was called pseudoscience, drew an FTC complaint, and was pulled. We coach toward the bar; we never claim to predict an outcome.

**Live bug to fix first (from the insights audit):** `scores.filler_word_count` is currently **LLM-invented** — `speech_analytics.py` computes the real value and `app.py` even returns it in the API payload, but the `FEEDBACKSCORES` prompt (`prompts.py`) never receives it, so the model makes up a number. This is exactly the §1.3.1 violation and must be fixed as Phase 0.

---

## 2. Where we are vs where this goes

| | Today | Wing D target |
|---|---|---|
| Lens | "how was the performance" | "would I hire you, and why / why not" |
| Rubric | one flat `FEEDBACKSCORES` (communication/technical/relevance/confidence) + free-text | named signals **per track × role × seniority**, ordinal bands w/ exemplars |
| Evidence | none | every band cites a transcript quote |
| Countable metrics | computed, **not shown**, and filler count **hallucinated** | computed in code, injected into the judge, surfaced with target bands |
| Coding | `evaluation_result` stored, **never rendered** | full coding verdict in the report, grounded in real pass/fail (Piston) |
| Richer engine | `TRACK_FEEDBACK` schema built but **dormant/unwired** | activated as the per-track structured verdict |
| Across sessions | none | longitudinal trends + cross-track comparison + "work on this next" |
| Model | interviewer model also judges | judge = different / strongest model, calibrated to a gold set |

(The "built but dormant / computed but unshown" items are detailed with file:line in [`EPIC_wingD_insights.md`](EPIC_wingD_insights.md).)

---

## 3. The evaluator redesign — per track × role × seniority

### 3.1 Architecture

One **evaluator service**, parameterized by `(track, role, seniority, company_archetype)`, that assembles a prompt from composable blocks:

```
verdict = evaluate(
   track,                 # intro | behavioral | technical_voice | coding
   role,                  # swe | pm | ds_mle
   seniority,             # intern | new_grad (L3) | mid (L4–L5)
   company_archetype,     # big_tech | high_bar_startup   (shifts weighting & values)
   transcript,            # stage-interleaved
   deterministic_metrics, # WPM, fillers, pauses, attempts, pass/fail  ← computed in code
   coding_eval_result,    # objective Piston pass/fail when track == coding
)
```

- **Track** chooses the signal set. **Role** chooses the flavor and which signals apply. **Seniority** chooses the per-signal scope exemplars. **Company archetype** shifts weighting (e.g. Stripe inverts coding weighting; Anthropic gates on culture).
- The evaluator is the **strongest available model**, distinct from the interviewer model (§1.3.7).
- Output is the shared **verdict contract** (§3.2). This is exactly what the **dormant `TRACK_FEEDBACK` schema** in `prompts.py` was reaching for — we activate and extend it rather than build new.

### 3.2 The shared verdict contract

```jsonc
{
  "overall": {
    "recommendation": "strong_no_hire | no_hire | lean_no_hire | on_fence | lean_hire | hire | strong_hire",
    "confidence": "low | medium | high",          // banded, per Meta — not a % 
    "headline": "one calm sentence, hiring-manager voice"
  },
  "signals": [
    {
      "name": "Problem solving",                   // from the track×role signal set
      "band": "poor | borderline | solid | outstanding",   // Google's scale
      "scope_met": "intern | new_grad | mid | above_level", // level it actually demonstrated
      "reasoning": "why this band, in the interviewer's voice",
      "evidence": ["verbatim quote from the candidate's transcript"],  // REQUIRED, ≥1
      "to_raise": "the specific thing that would move this up one band"
    }
  ],
  "differentiators": ["what would make this a STRONG hire, not just a hire"],
  "delivery": {                                    // deterministic, computed in code
     "wpm": 172, "wpm_target": "120–160",
     "filler_rate_pct": 9.1, "filler_target_pct": "≤4",
     "longest_monologue_s": 95, "notes": "qualitative tone/confidence — labeled as inferred"
  }
}
```

Two hard rules carried from the research: **`evidence` is required for every signal** (no quote → no score), and **`delivery` is never produced by the LLM** — code fills it.

### 3.3 Behavioral track (the highest-leverage one)

**Signal set** (union of Amazon LP clusters + Google Leadership/Googleyness + Meta's 8): *Ownership / drive, Impact (quantified), Dealing with ambiguity, Conflict & collaboration, Customer/user focus, Communication & structure, Growth/self-awareness.* Role only lightly flavors this (PM weights customer/structure; SWE weights ownership/ambiguity; DS/MLE weights impact/rigor); **company archetype matters more** (Amazon → LP evidence + metrics; Anthropic/OpenAI → authentic mission alignment & unscripted conviction).

| Band driver | Strong-hire evidence | No-hire evidence |
|---|---|---|
| Ownership | ~80% "I", personally uncovered/drove the problem | defaults to "we", executed assigned work only |
| Impact | quantified result + learning, story "closes the circle" | no metrics, vague outcome |
| Conflict | empathy for the other side, disagree-then-commit | avoids conflict, blames teammates, rabbit-holes proving they were right |
| Robustness | holds up under a 10–15 min "find-the-edges" probe | collapses / contradicts under follow-up |
| Authenticity | specific, un-scripted, real stakes | recites LP names, rehearsed, generic |

### 3.4 Coding track

**Signal set (Google's 4, our weighting from the 100K data):** *Problem-solving/approach (primary), Coding/implementation (primary), Testing & verification (strong differentiator), Communication (multiplier — gates only at L5+).* When `PISTON_ENABLED`, the **objective pass/fail and complexity feed the verdict** (we already store `evaluation_result`).

- **Strong-hire:** states approach + complexity *before* coding, asks clarifying questions, narrates complete thoughts, clean working code in 1–2 passes, tests & self-corrects, absorbs hints as collaboration.
- **No-hire (even if solved):** jumps to code, silent / half-thoughts, no clarifying Qs, can't reason complexity live, never tests, stuck silently, defensive on a hint.
- **`company_archetype = high_bar_startup` (Stripe):** invert — complexity carries little weight; **clean, complete, PR-approvable working code + a testing instinct + fast orientation in unfamiliar code** dominate.

### 3.5 Technical (voice) track — role-specific

This track's signal set *is* role-defined:

- **SWE:** CS fundamentals depth, trade-off reasoning, can explain *why* (invariants, complexity) out loud, junior-level design reasoning.
- **PM:** **Product sense** (segment → prioritized pain points → v1 with impact-vs-effort) and **Analytical/execution** (define the metric precisely *before* diagnosing; name guardrail/counter-metrics; a GAME-style structure). Strong = anchors on a user segment and drives; no-hire = vague segments, jumps to a solution, no framework.
- **DS/MLE:** statistics (states assumptions, Type I/II), ML fundamentals **with tradeoff reasoning** (model choice in context, bias-variance), experimentation (power, guardrails, Simpson's paradox), and **connecting every answer to product impact**; ML system design (mid+) graded as "think like a production engineer, not a researcher."

### 3.6 Intro track

Lower-stakes, but real signals: *motivation/authenticity, communication & structure, role/company fit, baseline self-awareness.* This is the warm-up; the verdict is lighter and feeds the longitudinal communication baseline (§4) more than a hire call.

### 3.7 Seniority scaling (the level-scoped exemplars)

The **same** answer scores differently by level — encode this as per-signal scope exemplars:

| | Intern | New-grad (L3) | Mid (L4–L5) |
|---|---|---|---|
| Behavioral scope | potential / learning agility; class projects OK | early execution + self-awareness; individual/team-level stories | multi-person/team impact; conflict at "direction" altitude |
| Coding | correct, readable; a hint or two expected; optimal *not* required | clarifies reflexively, clean & optimal, talks through | candidate **leads** — proactive invariants, edge cases, complexity unprompted |
| PM | structured thinking on a simple prompt | crisp framework + user empathy + metrics = the bar | a genuine point of view; drives ambiguity |
| DS/MLE | solid stats/SQL fundamentals + one strong project | connects stats→experiment, owns a metric | proposes tradeoffs unprompted; questions the metric definition |

---

## 4. Cross-interview comparison & longitudinal model

The user explicitly wants to compare interviews — different tracks, same user, improvement/regression over time. This needs a **stable competency taxonomy that spans tracks** so scores are comparable session-to-session.

- **Canonical competencies** (each interview maps its track-signals onto these): `communication`, `structure`, `ownership_impact`, `problem_solving`, `technical_depth`, `domain_rigor` (role-specific), `delivery` (deterministic speech metrics). Every session emits a score per applicable competency on the same ordinal scale → comparable.
- **Persist per-session, per-competency bands + deterministic metrics** (today scores aren't persisted in a queryable shape — Phase 0 fixes this). This is the prerequisite for everything longitudinal.
- **Trend definition:** rolling per-competency band over the last *N* sessions (min 3 for a trend); flag *improving / flat / regressing* with the delta. Compare **across tracks** ("your communication is solid in behavioral but drops in coding under time pressure") — a uniquely valuable insight only we can give because we have the same person across modes.
- **Benchmark vs target:** show each competency as **you vs the target-role/level band** (the §3.7 exemplars define the band). This is the "would I get hired for the role I'm aiming at" view.
- **Differentiator memory:** track which "to_raise" items recur across sessions → that becomes the headline "work on this next."

---

## 5. Dashboard & insights spec

Borrowing the coaching-dashboard patterns (Coursera/Skillsoft) + the Wispr lesson (*calm surface, one earned headline number; hide the machinery*):

1. **Per-session report (`feedback.html`) — rebuilt around the verdict:**
   - Top: the **hire/no-hire recommendation + confidence band + one-sentence headline** (hiring-manager voice).
   - Per-signal cards: band, the **evidence quote**, and the **"to raise this"** line. This is the moat made visible.
   - **Delivery panel** (finally rendered): WPM vs band, filler rate vs target, pauses — with one technique each. *(Insights easy-win E1.)*
   - **Coding block** (finally rendered): objective pass/fail, approach grade, complexity, edge cases caught/missed. *(Insights easy-win E3.)*
   - A clear **"strong-hire differentiators"** section (the upside layer).

2. **Profile / "Interview Personality" → behavioral profile:** per-competency **you-vs-target bars**, a **trend line per competency across sessions**, cross-track comparison, recurring filler/pacing patterns, and **one prioritized next action** derived from the largest persistent gap. Surfaced on the landing page (per the roadmap) so new users see where they're headed.

3. **Compare view:** pick 2+ sessions (any tracks) → side-by-side competency bands + deltas + "what improved / what still lags."

**Anti-patterns to avoid (from research):** a single opaque 1–100 score; any score without an evidence quote; scoring emotion/face; "you'll get hired" claims; data-only dashboards with no next-step coaching.

---

## 6. Implementation plan (grounded in our code)

Phased so trust comes first and each phase ships value. File-level wiring is in [`EPIC_wingD_insights.md`](EPIC_wingD_insights.md).

- **Phase 0 — Stop lying, start persisting (trust foundation).** Fix the hallucinated filler count by **injecting** `speech_analytics` values into the feedback prompt (`prompts.py`); persist per-session per-competency bands + deterministic metrics to a queryable table (`db.py` + a migration). *Prereq for §4.*
- **Phase 1 — Surface what we already compute.** Render the delivery panel (E1) and the coding block (E3) in `feedback.html`. Pure frontend + payload we already send; immediate visible upgrade.
- **Phase 2 — The evaluator redesign.** Activate & extend `TRACK_FEEDBACK` into the §3.2 verdict contract; rewrite the evaluator prompt to the hiring-decision lens with **evidence-quote-before-band**, role+seniority+archetype parameterization, atomic checks, discrete bands; route to the **strongest, non-interviewer model**. Wire Piston `evaluation_result` into the coding verdict.
- **Phase 3 — Longitudinal & dashboard.** Canonical competency mapping, trends, cross-track compare, you-vs-target bars, "work on this next." Rebuild the Personality view; surface on landing.
- **Phase 4 — Calibration.** Build a small human gold set; measure agreement (κ); tune until 75–90%; re-check periodically. Only then do we lean on the scores publicly.

Stage-attribution caveat (from the audit): **user transcript turns aren't stage-tagged** (only agent turns are, `agent_worker.py`), so per-stage evidence must be derived by interleaving timestamps, or we add user-turn stage tags in Phase 0.

---

## 7. What the deep-research report should still resolve

The four in-app passes nailed the *framework*. The Claude-web deep-research report ([`DEEP_RESEARCH_PROMPT.md`](DEEP_RESEARCH_PROMPT.md)) should fill the **per-cell exemplar text** for the §3 rubric tables (the literal poor/borderline/solid/outstanding descriptions per signal × role × level), confirm mid-2026 shifts (AI-assisted interviewing, take-home/work-trial trends), and surface any primary rubric docs the agents hit 403/429 on (Tech Interview Handbook, IGotAnOffer, datainterview). When that report comes back, it slots directly into §3 and §3.7.

---

## Appendix — research sources

**Behavioral / leadership:** Meta 8 focus areas + per-level scope ([interviewing.io](https://interviewing.io/blog/how-software-engineering-behavioral-interviews-are-evaluated-meta)); Amazon LP evaluation & no-hire rate ([interviewing.io](https://interviewing.io/guides/amazon-leadership-principles)); ex-Bar-Raiser memoir ([Medium](https://medium.com/geekculture/memoirs-of-an-amazon-bar-raiser-718e36241310)); ~1,000 Amazon interviews ([Pragmatic Engineer](https://newsletter.pragmaticengineer.com/p/learnings-from-conducting-1000-interviews)); Google re:Work structured interviewing ([re:Work](https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices)); Google attributes/Googleyness ([InterviewKickstart](https://interviewkickstart.com/blogs/interview-questions/google-leadership-principles-interview-questions)); Anthropic culture gate ([implicator.ai](https://www.implicator.ai/at-anthropic-the-culture-interview-is-the-top-late-stage-hiring-gate/)); OpenAI mission-first ([letsdatascience](https://letsdatascience.com/blog/how-to-land-a-job-at-openai-anthropic-or-google-deepmind)); Apple 67 competencies ([carrus.io](https://www.carrus.io/blog/the-67-competencies-that-apple-uses-to-test-you-in-the-interview)).

**Coding / technical:** communication 100K-interview study ([interviewing.io](https://interviewing.io/blog/does-communication-matter-in-technical-interviewing-we-looked-at-100k-interviews-to-find-out)); 600-interview failure modes ([interviewing.io](https://interviewing.io/blog/ive-conducted-over-600-technical-interviews-on-interviewing-io-here-are-5-common-problem-areas-ive-seen)); Google coding rubric ([Exponent](https://www.tryexponent.com/blog/google-coding-interview-rubric)) + ([Tech Interview Handbook](https://www.techinterviewhandbook.org/coding-interview-rubrics/)); L5 expectations ([Codeintuition](https://www.codeintuition.io/blogs/google-l5-coding-interview)); L3-vs-L4 ([padengayle](https://padengayle.substack.com/p/understanding-the-differences-between)); Stripe ([Exponent](https://www.tryexponent.com/guides/stripe-software-engineer-interview)); hire-scale ([Taro](https://www.jointaro.com/question/L3mJTvEGDqHsYn4GaVXM/how-are-hiring-decisions-made/)).

**PM & DS/MLE:** Meta PM rubric ([Exponent](https://www.tryexponent.com/guides/meta-pm-interview)); Google APM ([Exponent](https://www.tryexponent.com/guides/google-apm-interview)); how to interview PMs ([Lenny](https://www.lennysnewsletter.com/p/how-to-interview-product-managers)) + product-sense guide ([Lenny](https://www.lennysnewsletter.com/p/the-definitive-guide-to-mastering)); 500+ PM interviews ([Aakash Gupta](https://aakashgupta.medium.com/what-500-product-manager-interviews-reveal-about-getting-hired-f788a2338d44)); DS guide ([Exponent](https://www.tryexponent.com/blog/data-science-interview-guide)); ML system design ([Exponent](https://www.tryexponent.com/blog/machine-learning-system-design-interview-guide)) + ([HelloInterview](https://www.hellointerview.com/learn/ml-system-design/core-concepts/evaluation)).

**Voice-AI / coaching / LLM-as-judge:** Wispr Flow ([Wikipedia](https://en.wikipedia.org/wiki/Wispr_Flow)); Yoodli metrics & targets ([Yoodli](https://yoodli.ai/blog/ai-speech-coaching-explained)); coaching-app comparison ([speak.io](https://www.speakio.ai/blog/7-best-ai-speech-coaching-apps-in-2026)); HireVue pseudoscience/FTC ([SHRM](https://www.shrm.org/topics-tools/news/talent-acquisition/hirevue-discontinues-facial-analysis-screening)); Karat human+AI rubrics ([Karat](https://karat.com/resource/human-ai-technical-interview-rubrics/)); LLM-as-judge best practices ([Evidently](https://www.evidentlyai.com/llm-guide/llm-as-a-judge), [Arize](https://arize.com/llm-as-a-judge/), [Confident AI](https://www.confident-ai.com/blog/why-llm-as-a-judge-is-the-best-llm-evaluation-method), [FutureAGI](https://futureagi.com/blog/llm-as-judge-best-practices-2026)); skill dashboards ([Coursera](https://www.coursera.org/business/products/skillsdashboard), [Skillsoft](https://documentation.skillsoft.com/en_us/percipio/Content/A_Administrator/admn_dash_skill_benchmark.htm)).

*Caveats from the passes: several primary rubric pages (Tech Interview Handbook, IGotAnOffer, datainterview) returned 403/429 and were captured via search snippets + corroborating sources; intern-specific bars lean partly on secondary career sources; published vendor thresholds (Yoodli/Final Round) are directional, not authoritative.*
