# The Evaluator's Lens: A Primary-Source Hiring-Bar Reference for an AI Interview Coach (Mid-2026)

## TL;DR
- **The single most important reframe is that early-career hires are made on "how you got there," not "did you get the optimal answer."** Across Big Tech and high-bar startups, interviewers score a small set of signals (problem-solving, communication-while-working, code/analysis quality, response to hints, evidence-backed behavioral stories) on 1–4 scales that roll up to a Strong-Hire→Strong-No-Hire band — and the differentiator between a "hire" and a "no-hire" at intern/new-grad level is almost always the reasoning process, structure, and ownership a candidate demonstrates, not raw correctness.
- **The hiring bar shifts by level along a scope axis, not a knowledge axis:** intern = "can think and learn with guidance"; new-grad/L3/E3 = "can execute a well-defined task autonomously and write functional, communicated code"; mid/L4–L5/E4–E5 = "owns ambiguous problems end-to-end, makes and defends trade-offs, and shows emergent leadership/influence." An evaluator down-levels (rather than rejects) when technical signal is strong but scope/ownership evidence is thin.
- **For the voice/communication layer, only a narrow set of delivery metrics has credible research support** — filler-word *rate* (≤~5/min is acceptable; ~12/min measurably hurts perceived effectiveness), speech *rate* (~150 wpm is average; comprehension degrades at ~200 wpm), and structured/evidence-based content scoring. **Facial-expression and "confidence/emotion-from-face" analysis is pseudoscience for hiring and must be excluded** — HireVue itself dropped it after its own chief data scientist found nonverbal data added only ~0.25% predictive power. The trustworthy evaluator is a rubric-grounded LLM-as-judge that quotes evidence per score and is fed deterministic counts rather than asked to hallucinate them.

## Key Findings

### A. The universal evaluation shape
Every credible employer in scope uses **structured interviewing**: the same questions and a shared rubric with behaviorally-anchored levels, scored independently before debrief. Google's re:Work documents this explicitly — interviewers pre-define what "outstanding, solid, borderline, and poor" answers look like, and Google states its internal studies found structured-interview scores are "highly predictive indicators of future performance scores." This matters for an AI coach because a defensible evaluation engine must mirror that structure: fixed dimensions, anchored levels, evidence per score, and an explicit overall band.

The standard overall scale across Google, Meta, Amazon, and most peers is a 7-point band: **Strong No-Hire → No-Hire → Leaning No-Hire → On-the-Fence → Leaning Hire → Hire → Strong Hire** (confirmed by interviewing.io's Google process guide, which notes a "Strong Hire" can earn an offer or buy a bonus round, while a "Strong No-Hire" can freeze a candidate out for years). Interviewers also write a structured narrative justifying the call.

### B. The validity evidence behind structured interviewing
The foundational evidence is **Schmidt & Hunter (1998, *Psychological Bulletin* 124(2), 262–274)**: structured interviews show validity of **.51** vs. **.38** for unstructured; general mental ability alone is **.51**; and "an equally weighted combination of the structured interview and a GMA measure yields a validity of **.63**" (the three highest combinations were GMA + work-sample at .63, GMA + integrity test at .65, and GMA + structured interview at .63). A 2022 reanalysis — **Sackett, Zhang, Berry & Lievens (2022, *Journal of Applied Psychology* 107(11))** — argues earlier coefficients were systematically over-corrected for range restriction and revises them downward (structured interviews to ~.42, GMA to ~.31, unstructured to ~.19), but the *relative ranking* — structured beats unstructured, work-samples are strong — holds. **Takeaway for the coach: dimensions must be job-relevant and behaviorally anchored, and "work-sample"-style signals (live coding, real debugging, product cases) carry the most predictive weight.**

### C. Behavioral / leadership bars
- **Amazon (Bar Raiser + Leadership Principles):** Per Amazon's own "Life at AWS" write-up, Bar Raisers are trained employee volunteers from outside the hiring team who have run the program for 25 years; their job is to ensure each hire "raises the average performance bar." Ex-Amazon sources describe the standard as the candidate being in the **top ~50% of current Amazonians** in the role, with **veto power** even over a unanimous panel. Evidence standard is rigorous STAR with mandatory metrics. The most common no-hire patterns (per multiple 2026 guides): "we" instead of "I," shallow stories that collapse under deep follow-up probing ("What did *you* do next? What was the metric exactly? What would you do differently?"), and stories that don't clearly map to a specific Leadership Principle — interviewers literally cannot score them, so they default to no-hire.
- **Google (Hiring Committee + four attributes):** **General Cognitive Ability** (widely reported as most weighted), **Role-Related Knowledge** (least weighted but still verified), **Leadership** (emergent — influence without formal authority), and **Googleyness** (comfort with ambiguity, intellectual humility, bias to action, low-ego collaboration). A committee of senior Googlers who never met the candidate scores all four from the written packet; weakness on any single attribute can produce a no-hire. Googleyness is the signal that filters "technically strong but team-corrosive."
- **Meta:** Behavioral signal areas plus an unofficial **"Scope"** assessment (per ex-Meta interviewer Austen McDonald) that drives leveling — being "Growing Continuously" looks very different at E3 vs. E6. The behavioral/design rounds frequently decide E4-vs-E3 or E5-vs-E4 down-leveling even when coding is strong; interviewers are trained to spot rehearsed or inflated stories and dig with "What specifically did you do to convince the team? How did you measure the impact?"
- **High-bar startups (Anthropic, Stripe, OpenAI):** Values/mission alignment is a real gate, not a formality. Per interviewing.io's Anthropic guide and Anthropic recruiters, the **values/culture round is where most candidates fail**; rehearsed answers that are "clean, complete, and emotionally flat" read as memorized rather than internalized. Stripe weaves its principles (users first, ownership, cost-efficiency) into every round and weights the behavioral/managerial round heavily (it is "not a throwaway").

### D. Coding / technical-screen bars (SWE)
The cross-company rubric reduces to four dimensions (Tech Interview Handbook synthesis, corroborated by Google's published 1–4 coding rubric and interviewing.io interviewer accounts):
1. **Communication** — clarifying questions, narrating approach and trade-offs.
2. **Problem-solving** — decomposition, strategy, complexity analysis, optimization.
3. **Technical competency / coding** — correct, clean, idiomatic implementation, language fluency.
4. **Testing/verification** — exercising normal + corner cases, self-correcting bugs.

Google's published anchors: a "4" finds an optimal, well-reasoned solution with time to discuss trade-offs and asks clarifying questions; a "2" is unorganized/arbitrary and needs heavy hinting; "4s across the board" = Strong Hire, all 1s = Strong No-Hire. interviewing.io's interviewer accounts (drawn from one author's 600+ interviews on the platform) emphasize that **how a candidate debugs and responds to hints often outweighs reaching the optimal solution** — "the ability to think through problems while debugging is just as important as writing the code in the first place" — and that going silent while coding is a near-universal red flag. interviewing.io's data work also found that *self-assessed* communication and "interview feel" are poor predictors of outcome, while question quality and demonstrated problem-handling carry the signal; notably, one early interviewing.io analysis found communication scores alone were a weak predictor ("talk is cheap") relative to actual problem-solving.

**Leveling:** Intern/new-grad (L3/E3/SDE-1) — functional, correct code on a well-defined problem with clear communication; no distributed-systems design expected (Amazon SDE-1 explicitly "no distributed systems"). L4/E4/SDE-2 — higher code-quality bar (an Amazon manager: "with an SDE-1 I just expect functional code, but the bar is higher for an SDE-2"), independent handling of more ambiguous multi-week problems, first dedicated design round (down-leveling common at E4). L5/E5 — owns a problem space end-to-end, sets technical direction, mentors; E5 is the "terminal" level most engineers settle at.

**Startups / work-trials (Stripe):** The loop is deliberately practical — a **Bug Squash** round (debug failing tests in a large unfamiliar codebase, consistently reported in 2026 as the hardest round), an **Integration** round (build something real with vanilla libraries — request dedup, JSON parsing), and design focused on real-world failure modes (idempotency, retries, 135+ currency handling). Per a Stripe recruiter prep note (relayed via a Taro discussion thread): "This interview will evaluate your ability to solve a programming exercise in a readable way… We don't use Leetcode or trivia, or ask trick questions… speed is not really a metric we measure candidates on, but efficiency is." **Rewriting instead of surgically debugging is an explicit auto-fail signal.** Stripe's published technical evaluation criteria are Problem Solving, Design, Correctness, Debugging, Programming Language Familiarity, and Tools Familiarity, plus non-technical Excitement, Velocity, and Communication "tests." Anthropic similarly uses multi-tiered practical coding (build, then extend under added constraints in a shared Python environment), values working code and clear reasoning over algorithmic elegance ("We don't invent a spaceship if all we need is a bicycle"), and **bans AI assistance during live rounds** while explicitly encouraging Claude for prep.

### E. PM bars (early-career / APM)
Standard dimensions across Google APM, Meta RPM/PM, and Amazon: **product sense/design, analytical/execution, technical fluency, leadership/drive, communication/structure.** Meta scores each interview independently on a product rubric with summary notes ("Soft no," "Suggest re-evaluate," "Strong yes"); its product framing is **"Understand, Identify, Execute,"** and Meta deliberately frames metrics around "people" (DAP/MAP) not company metrics (DAU/MAU). Google evaluates **six areas** (Product Vision, Strategic Insights, Product Analysis, Problem Space & Understanding, Execute with Judgment, Behavioral & Situational) and has the highest technical bar for PMs in FAANG, especially at junior levels where PMs are expected to "get in the weeds with engineers." In Meta's analytical/execution round, candidates must **define metrics from scratch** (the GAME framework — Goals, Actions, Metrics, Evaluation — is a common scaffold), define guardrail/counter-metrics, and reason through metric conflicts (one reported prompt: notification engagement rising while time-on-site falls). Common no-hire patterns: jumping to solutions before defining the user/problem, no structure, metrics with no guardrails, and inability to handle trade-off follow-ups.

Mid-2026 change: Meta has added a live **AI product-sense round** for its AI PM track — candidates prototype a working solution in real time using an internal **Llama "vibe-coding" tool** while defending prompting strategy, latency, and token trade-offs (and a Central Products loop adds a product-architecture challenge).

### F. Data Scientist / ML Engineer bars (early-career)
Signal categories: **statistics/probability, ML fundamentals & depth, coding/SQL, experimentation / causal inference / product analytics, ML system design, stakeholder communication.** The defining differentiator (Google, Meta, Robinhood, Reddit DS guides): **connecting analysis to a product/business decision, not just producing a correct number.** Robinhood's strongest reported signal was interviewers "pushing beyond the mechanics of SQL or experimentation to ask why this metric matters and how the result would change a product decision." Documented common no-hire patterns (Datadog/Meta DS guides): shallow problem framing (jumping to a model/query before clarifying goal and metric definitions — "reads as brittle"), weak SQL fundamentals (window functions, cohorting, correct joins on event data — "a frequent filter because it blocks day-one productivity"), "stats without decision logic" (knowing tests but not how to set success criteria or handle multiple metrics), and "modeling without evaluation rigor" (ignoring leakage, drift, calibration, offline-vs-online mismatch). Google's DS loop weights **three separate quantitative stages** (SQL/Data Modeling, Statistics/Probability, Product Sense/Metrics); candidates who over-invest in ML/coding and under-invest in stats/product are the most common rejection.

### G. Voice & communication metrics — what's credible vs. gimmick
**Credible, research-backed delivery metrics:**
- **Filler-word / disfluency rate.** **Laske et al. (2024, *Journal of Applied Behavior Analysis*, DOI 10.1002/jaba.1093)** created speeches at 0, 2, 5, and 12 disfluencies/minute and had them crowd-rated: filler sounds at **~12/min significantly hurt perceived effectiveness across most categories**, while "a low, but nonzero, rate of disfluencies (5 per minute) did not adversely affect perceived effectiveness… a rate of five or fewer disfluencies per minute may be acceptable." Base-rate context: native English speakers naturally produce "uh"/"um" **roughly once per 100 words** (**Bortfeld et al., 2001, *Language and Speech* 44(2), 123–147**). A defensible coaching target is therefore **≤5 fillers/minute, not zero** — and the comprehension literature is clear that fillers also serve listener-oriented functions (they reliably cue upcoming complexity/novelty and aid processing), so penalizing them to zero is unsupported.
- **Speech rate (WPM).** Average U.S. English conversational rate is **~150 wpm** (widely attributed to the National Center for Voice and Speech, though I could only confirm this via consistent secondary citations, not an original NCVS page). **Griffiths (1990, *Language Learning* 40(3), 311–336)** tested 100, 150, and 200 wpm and found comprehension degrades significantly at **~200 wpm** but **not** at 150 or 100 wpm. A defensible "green band" is roughly **130–160 wpm for technical/dense content**, flagging sustained >~190 wpm. Important caveat: Griffiths tested **non-native listeners**; native speakers tolerate substantially higher rates (~275–300 wpm in other work), so bands should be advisory, not punitive.
- **Pauses / structure / conciseness.** Strategic pauses aid comprehension and emphasis (well-supported in the comprehension literature); structure and conciseness are legitimately scorable as *content* signals.

**Tools (report only credible signal):**
- **Yoodli** measures filler words, pace/WPM, conciseness, "sentence starters," word choice, and provides transcript + timestamps. The filler-rate and pace metrics map to the research above and are credible *as raw counts*; its "confidence," "empathy," and webcam-based "eye contact/body language" scores have **no published validity evidence** and should be treated as gimmicks for hiring evaluation.
- **Wispr Flow** is a dictation/voice-to-text product, *not* a delivery-coaching tool — it *removes* filler words and polishes text. Its only relevant surfaced analytics are WPM and total words dictated (the "Hub" shows dictation stats; iOS unlocks WPM after 500 words). It has no credible interview-delivery evaluation metrics; **do not adopt it as an evaluator.** It also drew criticism for undisclosed background analytics/network traffic that the company later said was for "performance analytics."
- **HireVue / facial analysis** is the cautionary case. HireVue's visual analysis was **discontinued in March 2020 and publicly announced in January 2021**, after internal research that, per chief data scientist **Lindsey Zuloaga** (via *Fortune*, Jan 19, 2021), found "nonverbal data didn't provide much predictive power… in most cases, it contributed about **0.25%** to a model's predictive power… Even when trying to assess candidates for a role with a lot of customer interaction, nonverbal attributes contributed just **4%**." Independent expert **Merve Hickok (SHRM-SCP, founder of Lighthouse Career Consulting)** stated: "Facial analysis has never been an independently and scientifically validated predictor of a person's ability, capacity or success in a role." (For scale, SHRM noted HireVue's platform had hosted 19M+ video interviews for 700+ customers.) In 2026 HireVue was reportedly among AI-hiring vendors under legal scrutiny related to the Fair Credit Reporting Act. **Exclude any facial/affect/"emotion-from-voice-tone confidence" scoring entirely.**

### H. Designing a trustworthy LLM-as-judge (2025–2026 best practice)
Synthesis from 2025–2026 LLM-as-judge research (Autorubric, arXiv 2603.00077; "Evaluating Scoring Bias in LLM-as-a-Judge," arXiv 2506.22316; "Position Bias in Rubric-Based LLM-as-a-Judge," arXiv 2602.02219; GoDaddy calibration engineering; Adnan Masood's 2026 rubric/psychometric review):
- **Rubric-grounded, criterion-level scoring** beats single holistic scores. Use yes/no or discrete-anchored criteria ("MET/PARTIAL/UNMET") with explicit numeric values to decouple score from presentation order; avoid unbounded continuous scales (LLMs calibrate poorly on them — Autorubric intentionally excludes them).
- **Require evidence/quotes per score** — the model must cite the candidate's verbatim words justifying each criterion. This enables error localization ("when a model fails on a specific rubric criterion, engineers know exactly which… adjustment will address the issue") and prevents hallucinated assessment.
- **Never ask the model for a count it can't compute.** Compute filler counts, WPM, pause durations, and code-test pass/fail *deterministically* and feed them in as values. Asking an LLM to "count the ums" is a documented hallucination source.
- **Mitigate known biases:** verbosity bias, self-enhancement bias, surface-fluency bias, position bias (point-wise vs. pairwise), and **leniency bias** — Autorubric uses explicit negative criteria/penalties for anti-patterns "to counteract the leniency bias documented in LLM judges."
- **Calibrate with few-shot anchored examples** (Databricks/TDS findings cited: 1 example per score ≈ +15–20% accuracy, 2–3 ≈ +25–30%), randomize rubric/option order, require chain-of-thought before scoring, use temperature 0, and instruct the model to return "cannot determine" when evidence is insufficient.
- Emerging methods (2025–2026): psychometric/IRT treatment of the rubric *itself* (which items are too ambiguous or judge-sensitive) and calibration-based bias correction with confidence intervals.

### I. Dashboards, progress & cross-session comparison
From learning-analytics and competency-dashboard literature plus performance-review practice:
- **Competency radar/spider charts** are the standard for multi-dimensional skill snapshots and explicitly support overlaying (a) current vs. previous session and (b) candidate vs. a **target-level reference polygon** (the "expected performance level" line) — directly serving "benchmark me against the L4 PM bar."
- **Trend lines per competency over sessions**, with a defined minimum number of sessions before declaring a "trend" (avoid over-reading two points). Education-dashboard research (e.g., Springer/ACM "Competency Dashboard" work, and Paulsen & Lindsay's 2024 systematic review) stresses *actionable* insight over raw analytics and alignment with goals — the dominant reason dashboards fail to be adopted is "insufficient actionable insights or a lack of alignment with… workflows."
- **Mastery/competency checklists** show which sub-skills are "achieved" vs. "developing" — good for "what to work on next."
- **Cross-interview-type comparison:** normalize each interview type to the same anchored scale, then show a single competency (e.g., "communication") across behavioral, coding, and PM sessions to reveal whether it's a stable trait or context-dependent.

## Details: Rubric Tables (early-career)

### SWE — Coding/Technical Screen
| Dimension | What the interviewer is deciding | Positive (strong-hire) | Negative (no-hire) | Bar shift intern→new-grad→mid | Evidence phrases to quote |
|---|---|---|---|---|---|
| Problem-solving | Can they decompose and strategize, not just recall? | Restates problem, states approach + complexity before coding, considers alternatives | Jumps to code, no plan, stuck without hints | Intern: reasons with guidance. NG: independent on defined problem. Mid: structures ambiguous/under-specified problems | "Before I code, let me confirm inputs and edge cases…"; "This is O(n²); a hash map gets us O(n)." |
| Coding ability | Can they produce correct, clean, idiomatic code? | Compiles mentally, clean naming, modular | Syntax flailing, no structure, can't translate plan to code | NG: functional/correct. Mid: clean, maintainable, anticipates extension | Working solution with helper functions; correct language idioms |
| Communication-while-coding | Could I work with them? | Narrates trade-offs, asks clarifying Qs, collaborates on hints | Silent coding, defensive to hints | Bar rises: mid must explain *why*, not just *what* | "I'll pause here to walk through my logic before running." |
| Testing/verification | Do they verify their own work? | Proactively tests normal + corner cases, self-corrects | Declares done untested, misses obvious edge case | Mid expected to discuss regression/edge risk after fix | "Let me trace a null/empty input." |
| Response to hints | Coachability | Integrates hint, builds on it, accelerates | Ignores, repeats stuck approach | Constant across levels; weighted heavily | Incorporates interviewer nudge and accelerates |

### SWE — Behavioral (Amazon LP lens)
| Dimension | Deciding | Positive | Negative | Level shift | Evidence phrases |
|---|---|---|---|---|---|
| Ownership | Will they own outcomes? | "I" stories, drove to result, owned failure | "We" everywhere, vague role | Intern: owned a task. NG: owned a feature. Mid: owned an ambiguous project | "I decided…, I measured…, when it broke I…" |
| Evidence/metrics (STAR) | Are stories real and quantified? | Specific situation, metric-backed result, survives probing | Collapses under "what did *you* do next?" | Probing depth increases with level | "Reduced p99 latency 38% by isolating one query." |
| LP/value mapping | Does the story map to a scoreable signal? | Clearly demonstrates the targeted principle | Story doesn't map → unscoreable → default no-hire | Mid: multiple LPs per story | "Customer was the starting point because…" |
| Bias for action / learning | Judgment + curiosity | Acts under ambiguity, learns from failure | Waited for instruction, no reflection | Mid: drove change beyond own scope | "I shipped an MVP to test, then iterated." |

### PM — Product Sense + Execution (early-career/APM)
| Dimension | Deciding | Positive | Negative | Level shift | Evidence phrases |
|---|---|---|---|---|---|
| Product sense/design | Do they start from the user? | Defines user/problem before solution, creative + scalable MVP, user empathy | Jumps to features, no user segmentation | APM: structured with guidance. Mid: owns ambiguity, ties to strategy | "Who am I building for, and what's their core problem?" |
| Analytical/execution | Can they reason with metrics? | Defines metrics from scratch, sets guardrails/counter-metrics, handles conflicts | Picks vanity metrics, no guardrails | Mid: handles conflicting-metric scenarios | "Success = X; guardrail = Y so we don't harm Z." |
| Technical fluency | Can they work with engineers? | Correct technical intuition, sensible trade-offs | Hand-waves feasibility | Higher bar at Google even junior | "We'd cache this; the trade-off is staleness." |
| Structure/communication | Can they lead a conversation? | Clear framework, signposts, prioritizes | Rambles, no prioritization | Constant; mid expected to drive | "I'll cover users, then solutions, then metrics." |
| Leadership/drive | Will they move others? | Influence without authority, ownership | Passive, follower stories | Mid: cross-functional influence | "I aligned eng + design by…" |

### DS/MLE — Technical + Analytical (early-career)
| Dimension | Deciding | Positive | Negative | Level shift | Evidence phrases |
|---|---|---|---|---|---|
| Stats/probability | Sound inference? | Correct test choice, practical + statistical significance | Mechanical test recall, no decision logic | Mid: designs from scratch, handles multiple metrics | "I'd set success criteria and a guardrail before peeking." |
| Coding/SQL | Day-one productive? | Correct joins on event data, window functions, clean queries | Shaky joins/cohorting (frequent hard filter) | NG: correctness. Mid: efficiency + debugging | Correct ROW_NUMBER/PARTITION for latest-per-key |
| Experimentation/causal | Can they design + read an A/B test? | Defines metric, guardrails, reasons about bias/novelty | No guardrails, ignores novelty/network effects | Mid: advanced designs (holdouts, geolift) | "Counter-metric here is retention, not just CTR." |
| ML fundamentals | Depth + evaluation rigor | Discusses leakage, drift, calibration, offline→online | Algorithm name-drops, no eval rigor | Mid: owns model lifecycle | "I'd check for train/serve skew before trusting AUC." |
| Stakeholder communication / product tie | Do they connect analysis to a decision? | "This changes the ship/no-ship call because…" | Produces correct number, no 'so what' | Differentiator at every level | "The result means we should hold the launch." |

## Top Differentiators (hired vs. not-hired, early-career)

**SWE:** (1) Narrates a structured approach *before* coding; (2) debugs methodically and self-corrects rather than freezing; (3) integrates hints and accelerates (coachability); (4) tests own code unprompted; (5) writes clean, idiomatic code, not just correct; (6) for startups: surgically debugs unfamiliar code instead of rewriting; (7) behavioral: "I"-owned, metric-backed stories that survive deep probing.

**PM:** (1) Defines user and problem before any solution; (2) defines metrics from scratch *with guardrails/counter-metrics*; (3) explicit, signposted structure; (4) reasons through trade-offs and conflicting metrics under follow-up; (5) technical fluency to converse with engineers; (6) influence/ownership stories; (7) creativity + scalability balanced with user empathy.

**DS/MLE:** (1) Ties every analysis to a product/business decision; (2) frames the problem (goal, constraints, metric definitions) before modeling/querying; (3) rock-solid SQL fundamentals; (4) experimentation with guardrails and awareness of bias/novelty effects; (5) evaluation rigor (leakage, drift, calibration); (6) clear communication to non-technical stakeholders; (7) pragmatism with messy data.

## Voice/Communication Metrics Worth Adopting (and gimmicks to avoid)

**Adopt (deterministic, evidence-backed):**
- **Filler/disfluency rate per minute** — green ≤5/min, flag ~12/min+ (Laske et al. 2024; Bortfeld et al. 2001 base rate of ~1 filler/100 words). Coach toward a low nonzero rate, never zero.
- **Speech rate (WPM)** — advisory green ~130–160 for dense content, flag sustained >~190 (Griffiths 1990; NCVS ~150 avg). Advisory only (non-native-listener caveat).
- **Pause usage** and **conciseness/structure** — comprehension-supported; score structure as content.

**Avoid (no credible validity for hiring):** facial-expression/affect scoring, "confidence" or "empathy" scores inferred from tone or face, webcam eye-contact/body-language scoring, any single composite "communication IQ." HireVue's own data (≈0.25% predictive contribution; ~4% only for "highly interactive roles where a calm tone-of-voice… is valued") and expert consensus make these pseudoscience for evaluation.

## AI-Evaluator Design Checklist
1. Fixed, job-relevant dimensions with **behaviorally-anchored** 1–4 (or MET/PARTIAL/UNMET) levels per interview-type × role.
2. **Evidence quote required** for every criterion score.
3. **Deterministic metrics fed in**, never asked of the LLM (filler count, WPM, pause stats, code test pass/fail, query correctness).
4. Explicit **negative/anti-pattern criteria** to counter leniency bias.
5. **Few-shot anchored exemplars** (1–3 per score level) + temperature 0 + chain-of-thought before scoring; allow a "cannot determine" verdict.
6. **Bias controls:** randomize option/rubric order; control verbosity/surface-fluency/self-enhancement/position bias; prefer point-wise rubric scoring with anchors.
7. **Calibration set** with human labels; track judge agreement; treat ambiguous rubric items as the thing to fix (IRT lens).
8. Roll criterion scores into a transparent weighted band (Strong No-Hire→Strong Hire) with the **narrative justification** the human process produces.
9. Output a leveling read (intern/NG/mid) keyed to the **scope/ownership** axis, not just correctness.
10. Never score facial affect or infer protected characteristics; keep delivery metrics advisory and content/process metrics primary.

## Dashboard & Cross-Session Recommendations
- **Competency radar** per session with overlays: current vs. previous, and vs. a **target-level reference polygon** (e.g., "L4 SWE bar").
- **Per-competency trend lines** across sessions; require ≥3 sessions before labeling a direction a "trend."
- **Mastery checklist** of sub-skills (achieved/developing) to drive a prioritized "what to work on next."
- **Cross-interview-type view:** normalize all types to one anchored scale; chart one competency (e.g., communication) across behavioral/coding/PM to show trait stability vs. context-dependence.
- Keep dashboards **actionable** (the dominant finding in learning-analytics adoption research): each chart should map to a specific next action, not just display analytics.

## Caveats
- Many company-process specifics (loop structure, signal names, leveling) come from high-quality secondary sources (interviewing.io, Exponent, IGotAnOffer, Hello Interview, ex-interviewer accounts) and crowd data (levels.fyi); **exact internal rubrics are confidential and FAANG companies do not publish them.** Treat "representative" rubrics (e.g., the Meta PM example attributed to ex-Meta leader "Noah") as informed reconstructions, not official documents.
- The **Sackett et al. (2022) reanalysis materially lowers** the historic Schmidt & Hunter validity coefficients (structured interview ~.42 vs. .51); use the *relative ranking* of methods, not absolute numbers. (The revised figures were confirmed via a reliable secondary summary, not the primary JAP article directly.)
- The NCVS ~150 wpm figure is ubiquitously cited but I could not locate it on an original NCVS/University of Iowa page; and Griffiths (1990) tested **non-native listeners**, so treat WPM bands as advisory.
- HireVue's 0.25%/4% figures are **company-stated, journalist-reported, and not peer-reviewed** — cite them as HireVue's own admission, not independent research.
- Mid-2026 shifts are real and ongoing: Meta's AI-enabled coding round and AI product-sense (Llama vibe-coding) round; Meta's reported October 2025 AI-assisted coding pilot (and interviewing.io's report that Meta began piloting an AI-enabled coding interview replacing one onsite coding round); bans on candidate AI use during live rounds (Anthropic, Meta OA video/mic monitoring). These will keep moving; re-verify before each product cycle.
- Tool claims (Yoodli, Wispr Flow) are largely vendor-stated; only the filler-rate and WPM primitives have independent research support, and even those should be presented as coaching signals, not hire/no-hire determinants.

## Sources Appendix (grouped by section)

**A–B. Structured interviewing & validity**
- Google re:Work, "A guide to structured interviewing" — *primary/insider*, evergreen (rubric definitions: outstanding/solid/borderline/poor; calibration). High trust.
- CNBC (2017), Google senior recruiter Haynes on structured interviews being "highly predictive" — secondary reporting of insider claim. Medium-high trust, dated but evergreen practice.
- Schmidt & Hunter (1998), *Psychological Bulletin* 124(2):262–274 — *primary* meta-analysis (.51/.63). High trust; foundational but pre-2022.
- Sackett, Zhang, Berry & Lievens (2022), *Journal of Applied Psychology* 107(11) — *primary* reanalysis (revised ~.42/.31). High trust; 2022. (Revised figures via reliable secondary summary.)

**C. Behavioral / leadership**
- Amazon "Life at AWS — Bar Raiser program" (aws.amazon.com) — *primary/insider*, 25-year program description. High trust.
- IGotAnOffer, Interview Prep Guru, FastApply (2026) — secondary guides quoting ex-Amazon Bar Raisers; top-50% standard, veto power, "we vs I." Medium trust, recent.
- ResumeAdapter, FastApply, AllyNerds (2026) — Google four-attribute and committee descriptions. Medium trust; consistent across sources; the framework is attributed to Laszlo Bock (*Work Rules!*), not a live Google URL.
- bigtechcareers.com (ex-Meta interviewer Austen McDonald) — *insider account*, Meta signal areas + "Scope." Medium-high trust.
- interviewing.io Anthropic guide; Anthropic "Candidate AI Guidance" (anthropic.com) — *primary/insider*; values round as top failure point; AI-use policy. High trust, 2026.

**D. SWE coding**
- Tech Interview Handbook, "coding interview rubrics" — synthesis of FAANG rubrics (4 dimensions). Medium-high trust.
- Exponent, "Google Coding Interview Rubric" — 1–4 anchors, Strong Hire bands. Medium trust.
- interviewing.io blogs ("600+ interviews," "thousands of coding interviews," "talk is cheap") — *insider/data-driven*. High trust.
- Stripe: interviewquery.com, vervecopilot.com, nodeflair.com (273 interviews), coditioning.com; recruiter quote via Taro (jointaro.com) — secondary + insider-prep. Medium trust, 2026.
- Anthropic: Exponent, finalroundai.com, jobright.ai, linkjob.ai — secondary candidate reports. Medium trust.
- Amazon/Meta leveling: amazon.jobs (SDE-II prep, *primary*), Taro, Hello Interview (E4/E5/E6 guides), ResumeAdapter, onsites.fyi. Medium-high trust.

**E. PM**
- Product Alliance, StellarPeers, IGotAnOffer (Google APM, Meta RPM/PM, analytical thinking) — secondary prep guides; six Google areas, Meta "Understand/Identify/Execute," GAME. Medium trust.
- Exponent "Meta PM Interview Guide (2026)" — AI product-sense/Llama vibe-coding round. Medium trust, recent.

**F. DS/MLE**
- datainterview.com (Google, Meta, Datadog DS guides) — secondary, detailed no-hire patterns. Medium trust.
- interviewquery.com (Meta, Robinhood, Reddit DS guides) — secondary + candidate reports. Medium trust.

**G. Voice/communication evidence**
- Laske et al. (2024), *Journal of Applied Behavior Analysis*, DOI 10.1002/jaba.1093 — *primary* parametric disfluency study (0/2/5/12 per min). High trust.
- Bortfeld et al. (2001), *Language and Speech* 44(2):123–147 — *primary*, ~1 filler/100 words. High trust.
- Griffiths (1990), *Language Learning* 40(3):311–336 — *primary*, 100/150/200 wpm comprehension. High trust (non-native caveat).
- NCVS ~150 wpm — secondary citations only (improvepodcast, VirtualSpeech, etc.). Medium trust.
- PMC/ScienceDirect reviews on fillers aiding comprehension — *primary* literature. High trust.
- Yoodli (yoodli.ai, research.com review) — vendor + review; filler/pace credible, "confidence/empathy/eye-contact" unsubstantiated. Low-medium trust on scores.
- Wispr Flow (wisprflow.ai, docs; tldv.io, willowvoice.com, letterly.app reviews) — vendor + reviews; dictation tool, not an evaluator; privacy criticism. Low trust as evaluator.
- HireVue: *Fortune* (Jan 19, 2021, Zuloaga 0.25%/4%); SHRM (Maurer, Hickok quote; 19M interviews/700 customers); Wikipedia; staffingindustry.com. High trust for the discontinuation facts and quotes.

**H. LLM-as-judge**
- arXiv 2603.00077 (Autorubric), 2506.22316 (Scoring Bias), 2602.02219 (Position Bias), 2604.00022 (criterion validity) — *primary* 2025–2026 research. High trust.
- GoDaddy engineering blog (calibrating LLM-judge scores); Adnan Masood (Medium, Apr 2026) rubric/psychometric review; emergentmind.com; mer.vin (2025) — secondary engineering syntheses. Medium-high trust.

**I. Dashboards**
- Springer/ACM "Competency Dashboard" chapter; Paulsen & Lindsay (2024) systematic review; Kaliisa et al. (2023) checklist — *primary* learning-analytics literature. High trust.
- peoplebox.ai, performancereviewssoftware.com (spider/radar chart practice, reference-level overlays) — secondary practitioner sources. Medium trust.
- gitnexa.com, kissmetrics.io, engineerica.com (edtech dashboard practice) — secondary. Medium trust.