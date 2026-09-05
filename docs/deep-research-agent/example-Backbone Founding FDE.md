# === INTERVIEW PREP — DEEP RESEARCH BRIEF · Backbone / Founding Engineer (Forward Deployed) / Technical Round 2 ===
# Compiled from the general template with: M1 (ownership/founding-eng), M10 (high-bar-startup archetype),
# + two round-specific extensions baked in: FDE-business-problems and AI-assisted-coding.

────────────────────────────────────
VARIABLES (locked from candidate input)
────────────────────────────────────
- COMPANY: Backbone  ·  URL: https://www.backbonesystems.ai
- COMPANY_TYPE: high-bar early-stage startup (a16z / Lightspeed / Hanabi backed)
- ROLE: Founding Engineer, Forward Deployed
- ROLE_FAMILY: swe (full-stack, backend bias) + forward-deployed-engineer (FDE) flavor
- SENIORITY: early-to-mid IC (1–4 yrs) BUT with founding-engineer ownership expectations
- ROUND: Technical Interview — 1 hour, split 50% non-coding fundamentals / 50% AI-assisted coding. NO leetcode.
- INTERVIEWER: CEO Manan Shah and/or eng team (Manan: BS/MS Math & CS, Stanford; led ML infra at Kumo AI — GNNs for DoorDash/Reddit/Coinbase)
- ALREADY_CLEARED: founder's call
- ROUNDS_REMAINING: after this → an on-site ~half/full day solving a real problem together, then offer decision
- DOMAIN: US healthcare payments — prior authorization, claims, denials, appeals, payer⇄provider adjudication; clinical AI; revenue-cycle automation
- LOCATION / PREP_TIME / MY_BACKGROUND: <candidate fills — paste resume highlights + how many days you have - 7 days>

────────────────────────────────────
PRIMARY SOURCE — treat as ground truth (do not contradict; build on it)
────────────────────────────────────
Manan (the interviewer), describing this exact round, verbatim:
"the next steps will look like a one hour technical interview where 50% of it is non coding, 50% of it is AI assisted coding. There's no leetcode. The former is just fundamentals around doing work with interesting business problems, and the latter is for us to see how you leverage the latest techniques today —[Claude Code], whatever, all these different variants — to both design and scale the system that you built. [Then] a half day where we would spend time together solving a particular problem, get a feel for how we communicate and interact together, and then based on that we would choose to extend an offer."

what the role requires:
"
Core Responsibility: End-to-end ownership of whatever problems the company faces to accelerate growth

What Success Looks Like [05:13 - 06:12]: The role is amorphous—not a fixed set of tasks. Instead, it involves working with the team to solve and distribute diverse engineering demands. Examples of what a day might entail:

Fix product UI issues for customers
Scale core backend systems to support increased throughput
Dedicate resources to solve specific customer problems to maintain relationships and drive revenue
Key Responsibilities

Own the full product surface area from customer conversations to product decisions
Handle both front-end and back-end work
Make improvements to core machine learning systems
Close the engineering, product, and design loop to accelerate with design partners
"

JD essentials: close the loop from customer pain to shipped software — observe the workflow, understand clinical/operational context, build it, deploy it, make sure it works. Sit with providers/payers/ops. Debug live issues across charts, claims, payer portals, EHR/PM systems, policy rules, ops queues. Strong full-stack w/ backend bias + clear evidence of shipping real software. Strong communication + product judgment. High ownership + urgency: shortest path from customer pain to working software in messy, real-world environments. Healthcare experience helpful, not required.

────────────────────────────────────
# RESEARCHER ROLE
────────────────────────────────────
### Act as a founding engineer + hiring manager who has personally run forward-deployed-engineer loops at a16z-backed AI startups in regulated, messy domains. Do NOT give generic "SWE interview tips." Reconstruct, as precisely as evidence allows, what Backbone's 1-hour technical round (per Manan's quote above) will actually test for a Founding Engineer (Forward Deployed), and prepare me to clear its bar — then set me up for the on-site that follows. Judge from the founder's hire/no-hire decision ("do I want this person in front of a customer AND shipping fast?"), not "how to perform."

────────────────────────────────────
TASK
────────────────────────────────────
§0  CONFIRM THE COMPANY. Lock to backbonesystems.ai (clinical AI for healthcare payments) — distinguish it from unrelated "Backbone" companies (gaming controllers, infra/networking, etc.). One-line confirmation + what they actually sell.

§1  COMPANY & THESIS DEEP DIVE. The $350B admin-waste thesis; the product (clinical-AI layer + "intelligent financial rails" for instant payer⇄provider payments; automating prior auth / claims / denials / appeals). Who the customers are (payers vs providers vs both) and what an FDE touches day-to-day. Stage, funding (a16z/Lightspeed/Hanabi), team size, founder Manan Shah's background and what he likely values technically (ML infra, systems, GNNs). Pull recent signals (≤18 mo): site, LinkedIn (founder + early eng posts), press, a16z portfolio notes. Cite; flag low-confidence inferences. Backbone-specific interview intel will be THIN — say so and fall back to closest comparables (Palantir/OpenAI/Anthropic FDE loops, a16z founding-eng loops).

§2  ROLE DECODE — Forward Deployed Engineer. What "FDE" means (Palantir lineage → now common at AI startups), and specifically what THIS JD describes: customer-facing engineer who closes pain→shipped-software in messy real-world systems. Map each JD bullet to the concrete competency it's probing. Make explicit how "founding engineer" raises the ownership/urgency/taste bar even at 1–4 yrs.

§3  DOMAIN PRIMER — US healthcare payments (the literacy the "business problems" half assumes). Teach me the lifecycle crisply: eligibility → prior authorization → claim submission (837/EDI) → adjudication → remittance (835) → denial (CARC/RARC codes) → appeal → payment. Key entities & systems: payers, providers, clearinghouses, EHR/PM systems (Epic, athenahealth), payer portals, medical necessity, CPT/ICD codes, policy/coverage rules, prior-auth bottlenecks. Where the friction and the automation opportunities are. Keep it practical — enough to reason about building software for it, not a textbook.

§4  ROUND DECODE + QUESTION BANK. Break down BOTH halves of the hour:

   PART A — Non-coding fundamentals / "interesting business problems."
   Predict the format (likely a grounded system/product-design discussion in their domain, not abstract). Give the implicit rubric (ownership, product judgment, full-stack/backend systems thinking, communication, ambiguity→implementation). Then 6–10 likely business-problem prompts with STRONG-ANSWER SCAFFOLDS, e.g.: "How would you automate prior authorization for a provider group?" / "A payer denies X% of claims for reason Y — how do you build something to catch it pre-submission?" / "How would you model the messy data flowing between an EHR and a payer portal?" For each: the winning structure (clarify the real workflow → find the highest-leverage automation → data/integration model → reliability + human-in-the-loop + safety → success metric → iterate) and the weak answer to avoid (jumping to tech, ignoring the messy real world, no safety/PHI awareness).

   PART B — AI-assisted coding ("design and scale the system you built").
   Decode exactly what Manan wants to SEE: how I leverage agentic tools (Claude Code / Cursor / Copilot) to design and then SCALE a system. Produce a concrete, winning live workflow: spec-first → small reviewable diffs → run/verify every change → narrate intent & trade-offs → know when the agent is wrong and correct it (don't blindly accept) → show taste. Define what "scale" means here (concurrency, data volume, failure handling, idempotency/retries/audit trails for payments, observability, edge cases in healthcare data, PHI/HIPAA safety). Advise me to come with a real system I've built that I can extend live, and how to pick it. List the anti-signals (over-trusting the agent, no verification, no architecture, can't explain the generated code).

§5  THE HIRING BAR (most important). strong-hire / hire / no-hire for a FOUNDING FDE at a high-bar a16z startup. Use the JD's own criteria as the rubric: shipped real software (backend bias) · communication + product judgment · high ownership + urgency · shortest path from pain → working software in messy environments · curiosity/rigor/taste. For each: the evidence that makes Manan write "advance," and the tell of someone who's a good engineer but NOT forward-deployable (can't talk to customers, freezes in ambiguity, gold-plates instead of shipping). Frame as the founder's decision.

§6  GAME PLAN for the 1-hour split. How to open each half, think aloud, structure a business-problem answer under time, run the AI-coding half cleanly, and what to do when I don't know the domain detail. How this round sets up the half-day on-site (what they're really testing there: how we communicate and build together) and how to leave them wanting that day.

§7  PREP PLAN, time-boxed to {{PREP_TIME}}, highest-probability gaps first: (1) domain primer reps, (2) 2–3 healthcare-payments system-design dry runs, (3) rehearse the AI-assisted build-&-scale workflow on a real project end-to-end, (4) 3–4 ownership/shipping stories with backend depth, (5) FDE customer-communication framing. Concrete drills, not "review system design."

§8  SMART QUESTIONS to ask Andrew Tierno / the team that signal founding-FDE thinking (about their hardest current workflow, what breaks in production today, how they decide what to build, the pilot→close→expand motion).

§9  RED FLAGS / failure modes that sink FDE candidates here + how to avoid each (treating it as pure SWE, no domain curiosity, no safety mindset in a regulated space, can't translate customer pain, AI-coding without judgment).

────────────────────────────────────
OUTPUT RULES
────────────────────────────────────
- Lead with a 5-line TL;DR: the 3–4 things this round most tests + the single biggest thing to nail.
- Cite inline; tag each major claim [Backbone-specific] vs [role-general/FDE] vs [domain] + a confidence level.
- Prefer primary/recent sources (Backbone site, founder LinkedIn, a16z, FDE write-ups from Palantir/OpenAI/Anthropic, healthcare-RCM primers, ≤2 yrs where possible).
- Specific, falsifiable, no filler. Backbone interview evidence is thin → say so and reason from the JD + Manan's quote + closest comparables.
- Treat Manan's quote and the JD as ground truth; everything else is inference you must label.
- one new md file for ROUND 2 - backbone.ai 