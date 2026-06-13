# Deep-Research Prompt — MockFlow-AI Evaluation Moat

Copy everything in the block below into **Claude.ai (web) with Research / extended thinking turned on**. It is scoped to the decisions we've already made (roles, seniority, companies) and is written to produce a report we can turn directly into evaluator rubrics + a dashboard. When it finishes, paste the report back here and I'll synthesize it into the Wing D build doc.

---

```
ROLE & MISSION
You are a senior interview-research analyst helping build the evaluation engine for an AI interview coach (think: a top university placement cell + an Amazon Bar Raiser, as software). Your research will define HOW we judge a candidate after a mock interview. The output must be specific enough to write grading rubrics from — not generic interview advice.

THE NON-NEGOTIABLE PRINCIPLE (this is the whole point)
Flip the perspective. Do NOT research "how to give a good answer" or "how to perform well." Research what the INTERVIEWER and the HIRING COMMITTEE are actually deciding: "As this company's interviewer for this role and level, would I give this person a strong-hire / hire / no-hire — and what specifically separates the ones who get hired from the ones who don't?" Everything you return should be framed as the evaluator's hire/no-hire judgment and the DIFFERENTIATORS between candidates.

SCOPE (stay inside this)
- Roles: Software Engineer (SWE), Product Manager (PM), and Data Scientist / ML Engineer (DS/MLE).
- Seniority: early-career only — internship, new-grad / entry (e.g. L3 / E3), and mid (L4 / E4 / L5). Note where the bar shifts between these.
- Companies: Big Tech (Amazon, Google, Meta, Apple, Microsoft, Netflix) AND high-bar startups (Stripe, OpenAI, Anthropic, and similar). Note where standards differ between Big Tech and startups.
- Interview types to cover: behavioral / leadership, coding / technical screen, system or practical design (at the junior–mid level), PM product/execution, and DS/MLE technical + analytical.
- Recency: prioritize 2024–2026 sources; explicitly flag anything that may be outdated and note mid-2026 changes (e.g. AI-assisted interviewing, take-home/work-trial shifts, new rubric guidance).

SOURCE QUALITY BAR
Prioritize PRIMARY and insider material: official careers/engineering blogs, published hiring rubrics, Amazon Bar Raiser write-ups, Google hiring-committee descriptions, ex-interviewer / hiring-manager accounts, levels.fyi, interviewing.io research, structured-interview academic work (e.g. Google's re:Work, Schmidt & Hunter validity research). Treat generic SEO listicles as low trust. Cite every nontrivial claim with a URL. Where sources conflict or are anecdotal, say so and rate your confidence.

RESEARCH QUESTIONS

A. Behavioral / leadership hiring bars
   - Amazon: how Bar Raisers are trained; how Leadership Principles become evidence-based signals; what "raises the bar" vs "does not raise the bar" means in practice; the written-narrative + STAR data standard; the LP→signal mapping.
   - Google: the hiring-committee process and the four attributes (GCA, Role-Related Knowledge, Leadership, Googleyness) — the scoring scale and what evidence moves a score.
   - Meta, Apple, and high-bar startups: their behavioral signals and values-based bars.
   - For each: positive indicators that differentiate a strong hire, negative indicators / common no-hire reasons, and how the bar shifts intern → new-grad → mid.

B. Coding / technical-screen hiring bars (SWE)
   - The signal categories interviewers are trained to score (problem-solving, coding ability, communication-while-coding, testing/verification, response to hints) and any documented scoring scales.
   - What strong-hire vs borderline vs no-hire looks like behaviorally — not just "got the answer." How much "how they got there" outweighs "optimal solution."
   - Leveling: intern vs new-grad (L3) vs L4 vs L5 expectations.
   - Startups / work trials (Stripe etc.): pragmatic coding, debugging real code, code quality, working software.

C. PM hiring bars (early-career / APM)
   - The standard dimensions (product sense/design, analytical/execution, technical fluency, leadership/drive, communication/structure) and real rubrics (Google APM, Meta RPM, Amazon).
   - Differentiators of a strong early-career PM vs weak (structure, user empathy, metrics, tradeoffs) and common no-hire patterns.

D. Data Science / ML Engineer hiring bars (early-career)
   - Signal categories: statistics/probability, ML fundamentals & depth, coding/SQL, experimentation / causal inference / product analytics, ML system design, stakeholder communication.
   - What separates a strong early-career DS/MLE from one who "knows the algorithms" but can't tie work to product/impact.

E. Voice-AI & communication-coaching evaluation standards (mid-2026)
   - Wispr Flow: what it measures/optimizes and any analytics it surfaces.
   - Yoodli, Poised, Orai, Speeko and peers: which spoken-delivery metrics they judge and coach (pace/WPM bands, fillers, clarity, conciseness, confidence/tone, structure, pauses) — which are evidence-based vs gimmicks.
   - AI interview-prep (Final Round AI, interviewing.io, Karat, HireVue): how they evaluate and any validity criticism (e.g. HireVue facial analysis) so we avoid pseudoscience.

F. Designing a trustworthy AI evaluator (LLM-as-judge)
   - 2025–2026 best practices for rubric-grounded scoring, requiring EVIDENCE/quotes per score, calibration, avoiding hallucinated metrics (never ask the model for a count it can't compute — feed deterministic values), structured scoring schemas, reducing leniency/position bias, and multi-dimensional rubrics.

G. Progress, comparison & dashboards
   - How coaching/ed-tech products show improvement over time, benchmark a user against a target level/role, and surface "what to work on next."
   - Patterns for comparing multiple sessions (and different interview types for the same user): what to chart, how to define a trend, how to show a competency moving up or down.

REQUIRED OUTPUT FORMAT (make it directly usable)
1. Executive synthesis: the 8–12 deepest, non-obvious insights, each framed as the interviewer's hire/no-hire lens.
2. Rubric tables — one per (interview type × role) at early-career, with columns: Dimension | What the interviewer is deciding | Positive indicators (strong-hire) | Negative indicators (no-hire) | How the bar shifts intern→new-grad→mid | Example evidence phrases an evaluator could quote.
3. "Top differentiators" — per role, the 5–7 things that most separate hired from not-hired early-career candidates.
4. Voice/communication metrics worth adopting (and gimmicks to avoid), with evidence.
5. AI-evaluator design checklist (from F) we should implement to keep scoring trustworthy.
6. Dashboard & cross-session comparison recommendations (from G).
7. Sources appendix: grouped by section, with a 1-line credibility note and recency for each.

Be exhaustive but specific. If you cannot find primary evidence for a claim, say so rather than inventing a clean rubric. Currency is mid-2026.
```

---

*Once you paste the report back, I'll merge it with the four in-app research agents' findings into `docs/EPIC_wingD_feedback_moat.md` — the evaluator redesign (per track × role × seniority), the cross-interview comparison model, and the dashboard/insights spec.*
