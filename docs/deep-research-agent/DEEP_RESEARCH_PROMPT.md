# === INTERVIEW PREP — DEEP RESEARCH BRIEF · GENERAL TEMPLATE v1 ===
# One prompt for any role / level / company / round.
# Fill §A. Turn ON the §D modules whose guard is true (rules in §E). Everything else is always-on.

────────────────────────────────────
§A. VARIABLES   (user-inputted; any blank → "infer it & flag confidence", never silently assume)
────────────────────────────────────
- COMPANY:
- COMPANY_URL / LINKEDIN:        ← pins disambiguation; if blank, researcher disambiguates
- COMPANY_TYPE:                  ← big_tech | startup | consulting | enterprise | agency | unknown
- ROLE:
- ROLE_FAMILY:                   ← swe | pm | data_ds_mle | business_analyst | design | gtm | other
- SENIORITY:                     ← intern | new_grad | mid | senior | lead | staff_plus | manager
- YEARS_EXPERIENCE:
- ROUND:                         ← recruiter | technical_skill | coding | system_design | behavioral | case | take_home | hiring_manager | values_bar_raiser | panel_onsite
- ROUND_FORMAT:                  ← live | take_home | panel | async   (blank → infer)
- DURATION:
- INTERVIEWER:                   ← title if known (peer | hiring_manager | bar_raiser | exec)
- ALREADY_CLEARED:               ← e.g. recruiter screen, + any others
- ROUNDS_REMAINING:              ← known, else "infer the likely loop"
- DOMAIN / PRODUCT:              ← blank → infer from company research
- LOCATION / REGION:             ← interview norms differ
- PREP_TIME_AVAILABLE:
- JOB_DESCRIPTION: <paste, or "none">
- MY_BACKGROUND: <3–4 lines: resume / strongest relevant experience>

────────────────────────────────────
§B. RESEARCHER ROLE
────────────────────────────────────
Act as a senior hiring manager + interview coach who has personally run {{ROLE}} loops at {{COMPANY_TYPE}} companies like {{COMPANY}}. Do NOT give generic "{{ROLE}} interview tips." Reconstruct, as precisely as evidence allows, what THIS specific {{DURATION}} {{ROUND}} round for a {{SENIORITY}} {{ROLE}} at {{COMPANY}} will actually test — and prepare me to clear ITS hiring bar. Judge from the interviewer's hire/no-hire decision, not from "how to perform."

────────────────────────────────────
§C. ALWAYS-ON TASK SECTIONS
────────────────────────────────────
§0 DISAMBIGUATE COMPANY. If COMPANY_URL given, lock to it. Else identify the most likely employer (product co. vs staffing/consulting vs client site), state your assumption + what would change it; if truly ambiguous, prep the 2 most likely and label sections.
§1 COMPANY SNAPSHOT. What COMPANY does, business model, domain, size, the systems/data this role touches, tech/BI stack. Recent signals (≤24 mo): Glassdoor/Blind/Reddit interview reports, levels.fyi, LinkedIn, news. Cite; flag low-confidence inferences.
§2 ROLE DECODE. What {{ROLE}} at {{SENIORITY}} is actually accountable for here; map JOB_DESCRIPTION → the concrete competencies they'll probe.
§3 ROUND DECODE. Anatomy of a {{DURATION}} {{ROUND}}: likely format(s), what each is really assessing, the implicit rubric. [apply DURATION rule E4]
§4 QUESTION BANK — ranked by probability. FIRST derive 4–7 skill categories THIS exact role+round tests (don't reuse a generic list — seed per ROLE_FAMILY, E5). THEN 20–30 ranked questions, each with a STRONG-ANSWER SCAFFOLD (the framework of a winning answer, not a script) + the common weak answer to avoid.
§5 THE HIRING BAR (most important). strong-hire / hire / no-hire for THIS round at {{SENIORITY}}: the evidence that makes an interviewer write "advance," and the tell of someone operating one level below. Frame as the interviewer's decision with specific behaviors. [if SENIORITY ≥ senior: add an operating-altitude read and "down-level, don't reject" when skill is strong but scope is thin]
§6 GAME PLAN for the {{DURATION}} window: how to open, think aloud, structure under time pressure, and what to do when you don't know.
§7 PREP PLAN, time-boxed to {{PREP_TIME_AVAILABLE}}, highest-probability gaps (from §3–§4) first. Concrete drills, not "review X."
§8 SMART QUESTIONS to ask the interviewer, calibrated to {{SENIORITY}}.
§9 RED FLAGS / failure modes that sink candidates in this round + how to avoid each.

────────────────────────────────────
§D. CONDITIONAL MODULES   (include ONLY those whose ACTIVATE-WHEN is true)
────────────────────────────────────
[M1 leadership-signal]   WHEN SENIORITY ∈ {senior, lead, staff_plus, manager}: assess ownership of ambiguity, cross-stakeholder influence, mentoring, pushing back on a bad spec/requirement; in §5 grade SCOPE, not just correctness.
[M2 people-leadership]   WHEN SENIORITY = manager: add team / delivery / conflict / hiring questions; de-emphasize hands-on tool drills.
[M3 potential-lens]      WHEN SENIORITY ∈ {intern, new_grad}: soften the ownership bar → learning agility + fundamentals; question bank skews fundamentals; §5 grades trajectory & coachability.
[M4 coding-round]        WHEN ROUND = coding: add DS&A, complexity, test/verify, talk-aloud; trajectory-over-artifact; going silent = red flag.
[M5 system-design]       WHEN ROUND = system_design (or panel_onsite & SENIORITY ≥ senior): scoping, requirements→constraints, tradeoffs, scale, failure modes.
[M6 behavioral-values]   WHEN ROUND ∈ {behavioral, values_bar_raiser}: STAR, "I vs we", quantified impact, authenticity; map to the company's actual values/LPs.
[M7 case-study]          WHEN ROUND = case: structured framework, hypothesis, drive to a recommendation, handle conflicting data.
[M8 take-home]           WHEN ROUND_FORMAT = take_home OR ROUND = take_home: scope discipline, completeness, README + tradeoff write-up, what reviewers actually grade.
[M9 recruiter-screen]    WHEN ROUND = recruiter: motivation, comp/logistics, basic fit, "tell me about yourself," what gets you cut at this stage.
[M10 company-archetype]  WHEN COMPANY_TYPE known: shift §5 — big_tech = structured/leveled/bar-raiser; startup = practical/build-real/scrappy; consulting = client-case + communication; enterprise = process + domain depth.
[M11 region-norms]       WHEN LOCATION given & non-default: note interview-norm differences.

────────────────────────────────────
§E. STAGING / ASSEMBLY RULES   (how modules turn on — this block is the engine spec)
────────────────────────────────────
E1 SENIORITY  → M3 (intern/new_grad) | none (mid) | M1 (senior/lead/staff_plus) | M1+M2 (manager)
E2 ROUND      → M4 coding | M5 system_design | M6 behavioral/values | M7 case | M8 take_home | M9 recruiter | (technical_skill / hiring_manager → core only)
E3 COMPANY    → COMPANY_TYPE known ⇒ M10 ; LOCATION non-default ⇒ M11
E4 DURATION   → ≤30 min: "tests 2–4 things fast, not deep — name them" · 45–75: "1–2 areas, deeper" · ≥90 / onsite: "breadth + stamina, multi-competency"
E5 ROLE_FAMILY→ selects §4 seed categories:
     swe={DS&A, system design, language/runtime depth, debugging, testing}
     pm={product sense, analytical/metrics, execution, strategy, behavioral}
     data_ds_mle={SQL, stats/experimentation, ML depth + evaluation, modeling/ML-sys-design, business framing}
     business_analyst={requirements/elicitation, SQL/data, process modeling, BI/viz, documentation, stakeholder cases}
     design={portfolio critique, app/whiteboard challenge, craft, process}
     gtm={domain, metrics/funnel, role-play, channel strategy}
E6 BLANKS     → researcher infers explicitly + flags confidence (never silently assumes)

────────────────────────────────────
§F. OUTPUT RULES
────────────────────────────────────
- Lead with a 5-line TL;DR: the 3–4 things this round most tests + the single biggest thing to nail.
- Cite inline; tag each major claim [company-specific] vs [role-general] + a confidence level.
- Prefer primary/recent sources (company site, Blind, Glassdoor, levels.fyi, LinkedIn, ≤2 yrs).
- Specific & falsifiable, no filler. Thin evidence on COMPANY → say so and fall back to the role-general bar.
- Honor only the §D modules activated by §E; ignore inactive ones.