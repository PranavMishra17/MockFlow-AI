# Flow behaviour audit — September 2026

An independent, first-hand audit of how Flow (the interviewer) conducts an
interview, across all four tracks, before any behavioural change is planned.
This is a **ledger of observations with evidence**, not a fix list. Decisions
come after review.

- Runs: 20 scripted persona runs (4 tracks × 5 mocked candidates) via
  `tests/e2e/agent_audit.py`, plus one behavioral interview I conducted myself,
  turn by turn, as a mid-level ML engineer.
- Evidence: every transcript, stage change, tool call, generated question bank
  and the verdict the feedback page would show is in
  [`docs/audit/agent-2026-09/`](audit/agent-2026-09/INDEX.md). Quotes below
  cite `track/persona`.
- What this can and cannot see: it runs the production `InterviewAgent`, FSM
  and `AgentSession` through the text harness — same prompts, tools and
  model — with voice I/O removed. So it sees everything Flow *says* and
  *decides*, and nothing about barge-in, VAD, TTS pacing or STT errors.
  Latencies quoted are text-only; TTS adds to them.
- Caveats on the data: the candidates are LLM-played personas (they are more
  articulate and compliant than real people — the "buggy code" persona wrote
  correct code); the harness clock was advanced 30 s per exchange so Flow saw
  realistic time-in-stage; the first parallel batch hit OpenAI's TPM limit and
  eleven runs were redone sequentially, so a few latencies in the first nine
  include 429 retries.

## The personas

| key | who | what they test |
|---|---|---|
| `priya_senior` | 8-yr tech lead, STAR answers with numbers | does Flow go deep when depth is offered? |
| `marcus_junior` | new grad, hedging, filler words, no metrics | does Flow draw out a nervous candidate? |
| `dana_rambler` | 4 yrs, 150–250-word tangents, forgets to answer | does Flow redirect? |
| `ken_terse` | 5 yrs, 3–15 words, disengaged | does Flow adapt to low signal? |
| `sam_curveball` | 6 yrs, asks Flow to repeat, asks for feedback, pushes back, "I don't know" | does Flow handle a two-way conversation? |

---

## Ledger

Severity: **S1** breaks the interview or the user's trust · **S2** makes Flow feel like a script, not an interviewer · **S3** polish.

### Flow control

**F1 · S1 · Silent turns: Flow sometimes says nothing after the candidate speaks.**
Cause: the model loops tool calls (`assess_response` → `ask_question` → …) until the agents SDK's step cap and the turn ends with no text. The input did reach Flow — its own transcript has the user turn — it just never answered.
Evidence: my own session — after my answer to the custom question ("shipped something I'm not proud of") Flow produced no turn; worker log at that moment: `maximum number of function calls steps reached`; 9 user turns recorded vs 8 replies. `behavioral/priya_senior`: three consecutive candidate turns in `behavioral_q3` (71.8 s, 79.7 s) with no reply. Matrix logs show the cap warning 2–3× per track.
In voice this is dead air until the candidate talks again.

**F2 · S1 · The stage-transition acknowledgement lands one turn late and replaces engagement with the candidate's first answer in the new stage.**
Mechanism (`interview_runtime.py` `transition_stage` → `pending_acknowledgement` → injected into the *next* `ask_question` result as `STAGE TRANSITION - First say: "…"`): the model already speaks its own transition sentence in the turn it transitions; then the candidate answers the first question of the new stage; then the canned line ("Great, Priya Raman! Let's move into the behavioral questions.") is prepended to Flow's next reply.
Evidence: my session — a full STAR story (8 % CTR drop, root cause in six hours, drift checks added) was answered with "Great, Pranav Mishra! Let's move into the behavioral questions. Can you tell me about a time you shipped something you were not proud of?" Not one word about the story. `behavioral/dana_rambler`: her booking-flow story answered with "Great, Dana Whitfield! Let's move into the behavioral questions. Can you tell me about a time when you had to prioritize customer needs" — a new question, first story dropped. `intro/priya_senior`: "Priya Raman, please go ahead and tell me about yourself." *after* she had introduced herself and answered a project question; "Excellent introduction, thank you Priya Raman! Now let's discuss your past work experience" one turn after past_experience had already begun. Same pattern in every track.
This single mechanism explains most of "Flow ignores what I said".

**F3 · S1 · Every stage change costs a wasted exchange.**
Flow announces the stage without a question ("Now that I have a better understanding of your background, let's move into some behavioral questions."), waits, the candidate says "ready", then Flow speaks the canned ack *and* the question. Three exchanges to ask one question.
Evidence: `behavioral/priya_senior` at every stage boundary (17.0 s, 37.8 s, 56.6 s); `intro/marcus_junior` "let's move on to the past experience stage. I'm looking forward to hearing more about your experiences!" (no question).

**F4 · S1 · Flow does not transition on its own when the candidate gives little.**
With the terse candidate Flow asked four generic questions in a row in `self_intro` and never moved; the simulated user had to press skip in every stage.
Evidence: `intro/ken_terse` (smoke run): 3 stalls, 0 self-transitions; `intro/marcus_junior`: stall in `past_experience` after 11.4 s silence.
Note: the harness does not run the wall-clock fallback timer, so in production the timer would eventually force it — after 2–4 minutes of the candidate wondering why nothing is happening.

**F5 · S2 · Stages get skipped or collapsed.**
`behavioral/sam_curveball`: `behavioral_q2` → `closing`; q3 never happened. `technical_voice/sam_curveball`: all three API questions fired inside `technical_concepts_1`, then `technical_concepts_2` opened with the literal placeholder **"Good. Now let's talk about [TOPIC_2]."** and went straight to closing. `coding/marcus_junior`: closing announced with problem 2 pushed but not yet submitted.

**F6 · S2 · The greeting is non-deterministic.**
Some runs start with the scripted welcome ("Hi Priya Raman! I'm Flow…"); others skip it and open with the stage-change ack: "Now that we've completed the greeting, let's move on to the self-introduction stage." (`intro/marcus_junior`, `behavioral/sam_curveball`, `behavioral/marcus_junior`). `technical_voice/priya_senior` opened with "Welcome back, Priya!" — there was no "back".

### Conversation quality

**F7 · S1 · Follow-ups are STAR-template probes fired regardless of what was already said.**
"Can you give me more context about the situation?", "What exactly was your responsibility in that scenario?", "What was the outcome? Any metrics or concrete impact?" are asked verbatim even when the answer already contained them.
Evidence: `behavioral/priya_senior` — she gave the 30 % latency outcome in her first answer; Flow later asked "What was the outcome? Any metrics or concrete impact?" My session: "What exactly was your responsibility in that scenario?" after I had said "it was my project, I built it and I made the call." Priya's answer to "your responsibility" then gets a *second* "What was the outcome?" Three template probes in a row is an interrogation, not an interview.
The waste is doubled: the generated question bank already carries *specific* probes per question ("What tools or methods did you use to diagnose the issue?", "How did you ensure the solution was sustainable?" — `behavioral/priya_senior` bank) and Flow asked none of them; it reached for the three "Missing Situation / Task / Result" lines from `prompts.py:688`, which the prompt itself says are for elements that are *missing*.

**F8 · S1 · Flow never adapts to the candidate's signal level.**
- Rambler: 150–250-word answers, an explicit tangent that never answered the question (`dana_rambler` turn 4) — Flow neither redirected, nor asked for the outcome, nor asked for brevity, in any track.
- Terse: "Not sure. Next question?" — Flow moved to the next generic question rather than probing the one concrete thing Ken had said (the claims batch pipeline). It never asked *him* a specific, answerable question.
- Junior: "I'm not sure I remember the specific features exactly" → "Thanks for sharing that, Marcus! What did you find most challenging…" — accepted, praised, moved on.
An interviewer's job with these three candidates is different; Flow ran the same script for all of them.

**F9 · S2 · Candidate questions are ignored or deflected; one was answered with invented facts.**
- "Could you repeat the end of that question?" → Flow asked a *different* question (`behavioral/sam_curveball` 4.0 s turn). (Handled correctly in `technical_voice/sam_curveball` and in my session.)
- The persona's "Would you like to hear about…?" offers were never taken up (`behavioral/priya_senior`, four times).
- At closing, "I'm curious about the team dynamics" → "I can't provide additional information as we are wrapping up." (`behavioral/sam_curveball`)
- `behavioral/marcus_junior` closing: Flow **fabricated** an employer: "Regarding your question about the onboarding process for new grads, it typically includes a comprehensive orientation, mentorship programs, and hands-on training." There is no company. A mock interviewer should say so.

**F10 · S2 · Praise is unconditional, and it contradicts the verdict.**
"Great!", "Excellent!", "impressive", "It's clear that your proactive approach significantly improved team dynamics" — to every candidate, including the ones the verdict then rates `lean_no_hire`. `behavioral/marcus_junior` closing: "Your insights into your learning process and collaboration skills are impressive" → verdict headline: "lacks depth in ownership and impact." The candidate will read the report and feel lied to in the room. Heuristic count: 8 praise words in 12 turns (`behavioral/sam_curveball`), 8 in 17 (`technical_voice/sam_curveball`).

**F11 · S2 · The candidate's name, every turn, and often the full name.**
"Hi Ken Okafor!", "Great to have you here, Pranav Mishra!", "Thank you so much for your thoughtful responses, Priya Raman." The canned acks use `[CANDIDATE_NAME]` = full name; the model adds "Sam!" on its own: 10 uses in 12 turns (`behavioral/sam_curveball`), 11 in 13 (`behavioral/marcus_junior`). No human interviewer does this.

**F12 · S2 · Meta / stage language leaks into speech.**
"Now that we've completed the greeting, let's move on to the self-introduction stage." · "Now, I will move to the self-introduction stage." (live room probe, 2026-09-12) · "let's move on to the past experience stage" · "Feel free to explain your reasoning, and I'll assess your response afterward!" · "**Compare REST vs. GraphQL**" (markdown bold, read aloud by TTS as asterisks or swallowed). Candidates should never hear the FSM.

**F13 · S2 · Two questions in one breath.**
"Can you describe a challenging project… and the specific role you played in it? What were some obstacles you faced, and how did you overcome them?" — 3–4 such turns per run (`intro/priya_senior`, `behavioral/dana_rambler`). In voice, the candidate answers the last one.

**F14 · S3 · Closing is fragmented and sometimes absent.**
`behavioral/priya_senior`: final line "Thank you so much for your thoughtful responses, Priya Raman. Let me wrap up." — and nothing after; no goodbye, no "feedback on the platform". `coding/dana_rambler`: three separate closing fragments (the canned "That's all the problems for today, Dana Whitfield. Let me wrap up." → the grader's `brief_verbal_feedback` read out as a bare sentence → the real goodbye). `technical_voice/sam_curveball`: the goodbye loop — nine "Take care!/Talk soon!/Bye for now!" exchanges because neither side ends the call. In production `on_closing` disconnects ~5 s after a "good luck" line; the loop shows Flow has no notion of *having said goodbye*.

**F16 · S2 · Scripted promises that are false in a mock.** The intro closing says "We'll be in touch with next steps via email." (`prompts.py`, every intro run). There is no email and no next step; the truthful line is that the feedback is on the platform — which the behavioral/technical closings do say. Same family as the invented employer in F9.

**F17 · S2 · The interview can be over in four questions.** `technical_voice/marcus_junior`: one question per stage — two experience questions, arrays-vs-linked-lists, hash tables — then "That covers our technical discussion." Six candidate turns total, verdict `no_hire`. A junior who got four questions has not been interviewed; the stage-minimum logic counts questions, not signal.

**F18 · S3 · Double greeting.** `intro/sam_curveball`: the scripted welcome (which already ends "Please go ahead and introduce yourself") is immediately followed by "Great! Now that we've transitioned to the self-introduction stage, please take a moment to introduce yourself." Two invitations before the candidate has said a word. `technical_voice/marcus_junior`: "Great! Now let's talk about your hands-on experience with these topics." spoken twice, verbatim, two turns apart.

**F15 · S3 · Latency.** Text-only median 2–4 s per reply, with spikes of 7–11 s on tool-heavy turns (`intro/marcus_junior` 11.4 s and 11.6 s; my session 7.0 s on a plain intro). TTS adds ~1 s+. Voice interviews feel broken past ~3 s of silence. Tool loops (F1) are the main driver.

### Track-specific

**Intro.** The scripted welcome works when it fires (F6). Question bank is always empty (by design — no generation). Company-fit questions assume a real company ("What aspects of our company culture or mission resonate with you?") that the candidate has no information about.

**Behavioral.** The question bank *is* generated now (3 Amazon-LP questions) and custom questions are used — the harness doc's note that behavioral never generates is stale. But F2/F7 mean the generated question is asked, one template probe follows, and the stage moves on; the LP framing is never named, and no answer is ever pushed for the "Result" when missing.

**Technical voice.** Best of the four when the bank is used (`priya_senior`: coherent progression CAP → trade-offs → consistency incident → monitoring). Worst when it isn't: `sam_curveball` had all three questions of topic 1 read out in one stage with "Let's dive into some technical concepts. We'll start with another question:" repeated three times, then the `[TOPIC_2]` placeholder (F5). Flow lectured: a 105-word turn that told Sam what challenges "many teams" face instead of asking him anything.

**Coding.**
- The "I'm Ready" click is honoured in *any* stage: the greeting itself says "click the I'm Ready button to receive your first problem", the problem is pushed during `greeting`, the candidate solves it, and Flow then runs the self-intro script ("Marcus Lee, tell me about your programming background") and later **re-reads problem 1** as if new (`coding/marcus_junior`).
- One submission evaluated twice: the `code_submitted` command path and the model's own `evaluate_code_submission` tool both ran — two `evaluation_result` events, two verbal feedbacks, attempt count double-charged (`coding/ken_terse`, 3 evaluations for 2 submissions).
- Flow closes without waiting for code: `marcus_junior` — problem 2 pushed, approach discussed, "That's all the problems for today" spoken *before* the submission arrived; the submission was then evaluated into a closed interview.
- Off-track improvisation: after both problems, "Now, let's discuss your experience with system design. Can you explain a system you designed…" in a coding interview (`ken_terse`). In `dana_rambler`, `coding_problem_2` opened with "Before we dive in, let's warm up… What challenges do you anticipate while implementing Kadane's algorithm?" — the problem she had already solved.
- Grading is an LLM guess, and a soft one. `PISTON_ENABLED` is unset in production, so no submission is ever executed. Tested directly with the real `CODE_EVALUATOR` prompt: a Two Sum that returns *values* instead of indices (fails every test) → `correctness: partial, approach: C`; an off-by-one that pairs an element with itself → `partial, D` with verbal feedback that only mentions inefficiency and never names the bug. Hard-coded stub and syntax error → `fail`. Every persona submission in the matrix was graded `pass / A`.
- No retry on the evaluation call: three 429s → `_evaluate_code_async failed` → no `evaluation_result` emitted → the UI's "Evaluating…" state would never clear (`coding/marcus_junior`).

### The feedback (verdict)

Read alongside the transcripts, the verdict pipeline is the strongest part of the product — and it is undermined by what happens in the room.
- Rankings are sane and discriminating: Priya `strong_hire`/`hire`, Sam `lean_hire`/`on_fence`, Dana `lean_hire`, Marcus `lean_no_hire`, Ken `no_hire`/`on_fence`. Quotes are verbatim and apt; "to_raise" lines are concrete.
- But it grades the *transcript Flow produced*. When Flow never probed for outcome (F2/F7), the verdict says "impact metrics are less clear" (`behavioral/dana_rambler`) — a Flow failure attributed to the candidate. When Flow ran a 3-question interrogation of Ken and never asked the one specific question that would have surfaced his batch pipeline, the verdict is `no_hire`, level read `intern`, for a 5-year engineer. The report is only as good as the interview, and the interview is the weak link.
- Delivery block: `pace_available: false` in every harness run (no audio; correct and honest per the measured-or-absent rule), `talk_ratio` computed.
- The in-room praise (F10) and the written verdict disagree in tone for every below-the-bar candidate.

---

## What I could not assess here

Barge-in and interruption handling; VAD/endpointing on real pauses (a rambler's mid-sentence breaths); how F15's latencies feel with TTS; STT errors and how Flow recovers from a misheard word; whether the wall-clock fallback timer (F4) fires gracefully or mid-sentence. These need the live room; `tests/e2e/caption_probe.py` is the starting point for a voice-level audit.

## Candidate decisions for review (not yet taken)

1. Remove the canned transition acknowledgements entirely, or deliver them in the same turn as `transition_stage` (F2, F3, F11, F12).
2. Cap tool steps per turn and force a spoken fallback when the cap is hit (F1, F15).
3. Replace STAR-template probes with "probe what is missing from *this* answer" — the model already has `assess_response`; use its output (F7).
4. Give Flow explicit strategies per signal level: redirect ramblers, narrow for the terse, scaffold the junior (F8).
5. A mock interviewer should answer questions about the process honestly and refuse to invent an employer; decide how "company" questions work when there is no company (F9, intro company-fit).
6. Calibrate praise: acknowledge, don't grade, in the room; or make in-room reactions consistent with the rubric (F10).
7. Coding: gate `ready_for_problem` on stage; make submission-vs-tool evaluation one path; do not close with a problem open; decide on Piston in prod (grading honesty).
8. Voice hygiene: first name only, one question per turn, no markdown, no FSM vocabulary, a single closing utterance, no promises the product cannot keep (F11–F14, F16, F18).
9. Decide what "enough interview" means per level — a floor on substantive answers, not on questions asked (F17, F4).

---

## Round 2 — after the redesign (2026-09-12, same day)

The plan that came out of this ledger was executed the same day: a code-owned
turn loop (`interview_turn.py`, `interview_coverage.py`; `docs/RUNTIME_CONTRACT.md`
§0), a one-line greeting with the walkthrough moved to the pre-join panel, a
prompt rewrite with a linter, a sentinel closing, and the coding fixes. The
same rig, same five personas, same four tracks were run again:
[`docs/audit/agent-after-redesign/`](audit/agent-after-redesign/INDEX.md).

### The numbers (20 runs each, identical personas)

| measure | before | after |
|---|---|---|
| times the simulated user had to press Skip (F4) | 8 | **0** |
| silent turns — candidate spoke, Flow said nothing (F1) | 18 | **0** |
| Flow turns asking two questions (F13) | 29 | 3 |
| Flow turns with a praise adjective (F10) | 92 | **0** |
| Flow turns using the candidate's full name (F11) | 44 | **0** |
| Flow turns with FSM vocabulary (F12) | 27 | 2 (both false positives: the candidate's own "transition"/"stage" quoted back) |
| text-only reply latency p50 / p95 (F15) | 2.2 s / 6.0 s | 2.5 s / 2.8 s |

The p50 rose slightly because every turn now includes the structured
assessment; the p95 fell by more than half because the tool-chain spikes are
gone. In the room the assessment is primed from the interim transcript while
the candidate is still talking, so most of that 2.5 s is not on the critical
path (live probe: no timeouts logged).

### Finding by finding

| # | status | evidence |
|---|---|---|
| F1 silent turns | **fixed** | 0/20; `prepare_turn` cannot raise past StopResponse; `max_tool_steps=1`; no tools |
| F2 stale acknowledgement | **fixed** | no `pending_acknowledgement` exists; the first answer of every stage gets a specific pickup and the next question in one reply (`behavioral/priya_senior`: "You organized workshops… Tell me about a time…") |
| F3 wasted "ready?" exchange | **fixed** | transitions arrive with a question; zero "let's move into" lines |
| F4 no self-transition | **fixed** | 0 stalls; progression is code (coverage / overtime / terse streak / cap) |
| F5 skipped stages, `[TOPIC_2]` | **fixed** | every run reached closing through its stages; prompt lint fails on any unreplaced placeholder |
| F6 non-deterministic greeting | **fixed** | one fixed line per track, spoken by code; tested |
| F7 template probes | **fixed** | probes come from the bank's `follow_up_probes` or the missing STAR element; the "Missing Situation/Task/Result" lines are deleted |
| F8 no adaptation | **improved** | terse → narrow question about the one thing said (`behavioral/ken_terse`); "I don't know" → "Fair — that's better than guessing" + scaffold (`technical_voice/marcus_junior`); rambler pinning exists but the LLM persona answered its questions, so it was not exercised — needs a real rambler |
| F9 candidate questions | **fixed** | "repeat" repeats the whole spoken question; "how am I doing" and company questions get fixed honest lines; no invented employer |
| F10 unconditional praise | **fixed** | 0 praise-adjective turns in 20 runs |
| F11 full name every turn | **fixed** | 0; first name appears once, in the closing |
| F12 FSM vocabulary | **fixed** | 2 false positives only |
| F13 two questions | **improved** | 29 → 3; the remaining three are bank questions that are themselves two questions (generator prompt; see follow-ups) |
| F14 fragmented / absent closing | **fixed** | one code-spoken utterance quoting the candidate's own strongest line, ending in the sentinel; finalization keys on the sentinel only |
| F15 latency | **improved** | p95 6.0 → 2.8 s text-only |
| F16 false promises | **fixed** | "we'll be in touch via email" deleted; linter bans it |
| F17 four-question interviews | **fixed** | two-turn floor per stage; regression asserts ≥ 5 exchanges |
| F18 double greeting | **fixed** | the greeting is not generated |
| coding: Ready in any stage | **fixed** | gated: before problems → start problem 1; during → re-push; else ignored |
| coding: double evaluation | **fixed** | one path; test asserts one `evaluation_result` per submission |
| coding: closes with a problem open | **fixed** | closing only after every active problem is submitted, skipped or timed out |
| coding: grader soft | **improved** | contract violations fail and are named ("you're returning the values instead of the indices"); still LLM-only in prod, and the editor now says so |
| coding: 429 → stuck editor | **fixed** | retry with backoff, then `evaluation_error` releases the editor |

### What is still true, for the next round

- **Rhythm is regular.** Two exchanges per stage, pickup + question, every
  time. It is correct and it is a little metronomic. The opener-variety rule
  helps; a real fix is letting the move chooser occasionally spend a third
  turn on a rich answer and a single turn on a thin one — the ledger has the
  signal for it.
- **Some bank questions are two questions.** `QUESTION_GENERATION` should be
  told one question per item, and the technical generator should stop
  pairing "explain X" with "and discuss Y".
- **The assessor mis-tags occasionally** ("thanks for indulging me" read as
  another company question). The no-repeat-preface guard hides the visible
  symptom; a cheaper fix is to require the question mark before tagging.
- **Interviews are shorter** (6–12 exchanges vs 12–16), because the old
  length was padding. Whether the floors should rise for senior candidates is
  a product call; the rig makes it a one-line change to test.
- **Voice-only behaviour is still unverified by machine**: barge-in, the
  timer-forced move landing mid-sentence, TTS pacing of the closing line.
  `tests/e2e/caption_probe.py` proved the audio path runs the new loop with
  no assessment timeouts; a human run per track on prod is the remaining
  check.

### How to keep it this way

`python -m pytest -m level_b tests/e2e/test_agent_audit.py -x` runs the 20
interviews and asserts every row of the numbers table (140 checks). Run it
before merging anything that touches `prompts.py`, `interview_turn.py` or
`interview_runtime.py`. `tests/test_prompt_lint.py`, `tests/test_interview_turn.py`,
`tests/test_prepare_turn.py`, `tests/test_coding_flow.py` and
`tests/test_closing_and_forced_moves.py` run on every commit without a key.
