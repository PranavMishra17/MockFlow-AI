# EPIC — Wing D: The Feedback Loop ("Insights")

**Status:** Research / planning (no production code in this doc)
**Author:** Senior product + ML review
**Date:** 2026-06-13
**Scope:** Make the post-interview feedback loop genuinely valuable — capture more of what
we already have, compute richer signal, and surface it in ways that change candidate behavior.

---

## 1. Current state — what we CAPTURE vs. what we SURFACE

### 1.1 What we capture (data that exists today)

| Signal | Where captured | Stored where | Surfaced? |
|---|---|---|---|
| Full transcript (agent + user turns) | `agent_worker.py:1266` (user), `:1282` (agent) | `interviews.conversation` JSONB | Yes (transcript modal) |
| Agent turn **stage tag** + **timestamp** | `agent_worker.py:1285-1286` | `conversation.agent[].stage`, `.timestamp` | Partly (stage badges) |
| User turn **timestamp** (NO stage tag) | `agent_worker.py:1266-1270` | `conversation.user[].timestamp` | No |
| Filler words (count + per-word breakdown) | `speech_analytics.py:70` `_count_fillers` | computed at feedback time, returned in API but **not persisted** | **No** (returned by API, never rendered) |
| WPM (avg + per-turn pace, first 20 turns) | `speech_analytics.py:107`, `:113` | computed at feedback time, returned in API but **not persisted** | **No** |
| Word count, speaking duration | `speech_analytics.py:39-47` | same | **No** |
| Track + per-interview question set / competencies | `interviews.track`, `interviews.track_config` JSONB (`db.py:359-360`) | DB | No |
| Skipped stages, final stage, ended_by | `interviews` columns (`db.py:304-318`) | DB | No |
| has_resume / has_jd | `interviews` columns | DB | No |
| **Coding submissions**: code, language, attempt #, time_spent_seconds | `db.py:459` `save_coding_submission` | `coding_submissions` table | **No** |
| **Coding evaluation_result**: correctness, approach_quality (A–F), edge_cases_handled/missed, time/space complexity, code_quality_notes, suggestions | `agent_worker.py:684`, `prompts.py:1410` `CODE_EVALUATOR` | `coding_submissions.evaluation_result` JSONB | **No** (returned in `/api/feedback/scores` payload as `coding_submissions`, never rendered) |
| Competency scores (3–5, 1–5 scale) | LLM via `FEEDBACKSCORES` (`prompts.py:513`) | `feedback.feedback_data.scores` JSONB | Yes (bars + top/focus) |
| Narrative markdown feedback | LLM via `POSTINTERVIEWFEEDBACK` (`prompts.py:342`) | `feedback.feedback_data.feedback` | Yes (right panel) |

### 1.2 What we surface

- **`templates/feedback.html`** renders only: overall score gauge, per-competency bars + quick-take, top strength / focus area, and the markdown narrative (`renderScores` `:467`, `renderFeedback` `:579`). It **never reads `speech_analytics` or `coding_submissions`** even though both are in the API response (`app.py:1459-1460`, `:1614-1615`).
- **Dashboard widget** (`static/dashboard.js:99` `buildPersonalitySummary`, `:126` `renderStatsContent`) shows: total interviews, strongest track persona, avg overall score /5, last-active recency, per-track counts, free calls left. Backed by `db.py:112` `get_user_stats` and `/api/user/stats` (`app.py:258`).

### 1.3 The two big structural problems

1. **A richer feedback schema already exists but is NOT wired up.** `prompts.py:1169` `TRACK_FEEDBACK` defines per-track structured JSON with `question_feedback[]`, STAR `per_question` breakdown, `covered/missed_competencies`, `concept_accuracy[]`, and coding `code_quality`/`edge_case_handling`/`time_management`. The live endpoints (`/api/feedback/scores`, `/api/feedback`) ignore it and use the flat `FEEDBACKSCORES` + free-text `POSTINTERVIEWFEEDBACK` instead. Significant analysis surface is built but dormant.

2. **Speech analytics are computed but thrown away.** `analyze_transcript` runs on every feedback request (`app.py:1377`, `:1521`) and is even passed into the *narrative* prompt — but the deterministic numbers are never shown as their own UI block, never persisted, and never trended. Worse, `FEEDBACKSCORES.user_template` (`prompts.py:565`) does **not** receive `speech_analytics`, yet the scores prompt asks the LLM for `filler_word_count` — so the count in `scores` is **hallucinated** (sample: `scores.filler_word_count = 20` from the LLM vs. the real deterministic value from `speech_analytics`). This is a correctness bug, not just a gap.

---

## 2. Honest critique

- **Per-competency scores have no evidence in the structured layer.** The bars show "Communication Clarity 2/5" with a one-line quick-take, but the *quote* that justifies it lives only inside the prose narrative, not attached to the score. Users can't click a score to see why.
- **No per-question / per-stage breakdown.** We tag every agent turn with `stage` and timestamp, so we can attribute every user answer to the question that preceded it — but nothing does. There is no "Question 2: you scored B, here's the moment you lost points."
- **Filler/WPM captured but not coached.** The single most concrete, defensible, longitudinal signal we have (deterministic, no LLM) is invisible. No "you said 'basically' 7 times," no pace gauge, no per-turn sparkline.
- **Coding pass/fail is fully divorced from feedback.** We store correctness, approach grade, complexity, and missed edge cases per attempt, and the agent already spoke a verbal one-liner — but the report page shows none of it. A coding-track user gets generic communication feedback and zero code analysis.
- **No longitudinal trend.** `get_user_stats` averages all feedback scores into one number. There is no "your clarity went 2 → 3 → 4 over three sessions," no trend line, no "best/worst session," no streak. Repeat usage (the core retention loop) is unrewarded.
- **No target-role / level calibration.** We store `job_role` and `experience_level` and even `has_jd`, but feedback never says "for a senior role, this answer would need X." Scores float free of any bar.
- **No "top 3 things to fix next time."** `top_improvement` is a single sentence; there's no prioritized, carry-forward action list that seeds the next interview.
- **Feedback generation is best-effort and not idempotent.** It's triggered client-side on page view, cached in a process-local dict (`app.py:1231` `_feedback_cache`, lost on restart) plus DB. No regeneration, no versioning, no model record beyond a hard-coded `gpt-4o-mini` string.

---

## 3. Wing D feature plan

Effort key: **S** ≈ <1 day, **M** ≈ 2–4 days, **L** ≈ 1–2 weeks. Layer key: **FE** (frontend only),
**Prompt** (prompt/LLM-call only), **Schema/Agent** (needs DB columns or capture changes).

### 3.1 Easy wins (mostly using data we already have)

| # | Feature | Value prop | User-facing change | Data needed (have?) | Effort | Layer |
|---|---|---|---|---|---|---|
| E1 | **Speech Analytics panel** | Show the deterministic signal we already compute and currently discard | New card on `feedback.html`: total fillers, top-3 filler words with counts, avg WPM with a "too slow / good / too fast" band, and a per-turn pace sparkline | `speech_analytics` already returned by `/api/feedback/scores` (`app.py:1459`); fully captured | **S** | FE |
| E2 | **Fix hallucinated filler count + persist real analytics** | Scores show a made-up filler number today; replace with the real one and stop recomputing every view | `filler_word_count` becomes correct; analytics persist with the feedback record | Pass `speech_analytics_json` into `FEEDBACKSCORES.user_template` (`prompts.py:565`); store `speech_analytics` inside `feedback_data` on save (`app.py:1026`) | **S** | Prompt + Schema(JSON) |
| E3 | **Coding report block** | Coding-track users currently get zero code feedback despite full capture | Render per-problem cards: correctness badge, approach grade, complexity, edge cases caught/missed, suggestions, time spent, attempt history | `coding_submissions` already returned by the API (`app.py:1460`); `evaluation_result` fully captured | **S/M** | FE |
| E4 | **Evidence-linked competency scores** | Make each score defensible by attaching the candidate's own words | Click/expand a competency bar to reveal a supporting quote + one micro-fix | Switch the scores call to a small structured schema that returns `evidence_quote` per competency (the narrative already quotes; just structure it) | **M** | Prompt + FE |
| E5 | **Top 3 fixes ("Next time, focus on…")** | Turn a wall of prose into 3 prioritized, carry-forward actions | Pinned checklist at top of report; same 3 items pre-seed the next interview's intro | Derivable from existing narrative/scores; add a `priority_fixes[]` field to the scores schema | **S** | Prompt + FE |
| E6 | **Per-stage answer breakdown** | "Where in the interview did I do well/poorly" using stage tags we already store | Timeline strip: each stage with a grade + one-line note; click to jump to that part of the transcript | Agent turns carry `stage`+`timestamp` (`agent_worker.py:1285`); interleave user turns by timestamp to attribute answers — cheap to derive, no new capture | **M** | Prompt + FE |

### 3.2 Bigger bets

| # | Feature | Value prop | User-facing change | Data needed (have?) | Effort | Layer |
|---|---|---|---|---|---|---|
| B1 | **Activate `TRACK_FEEDBACK` structured feedback** | A whole richer schema (`question_feedback`, STAR `per_question`, covered/missed competencies, coding `edge_case_handling`) is already written but dormant | Track-specific report sections: behavioral STAR matrix, technical concept-accuracy table, coding quality breakdown | Wire `prompts.py:1169` `TRACK_FEEDBACK` into a new generation path; feed transcript + `speech_analytics` + `coding_submissions` (all captured) | **L** | Prompt + Schema + FE |
| B2 | **Longitudinal trends across sessions** | Reward the repeat-usage retention loop; show improvement over time | Dashboard trend lines: overall + per-competency over last N sessions; "clarity 2→3→4", best/worst session, filler-rate trend | Persist scores + speech analytics per interview (E2); extend `db.py:112` `get_user_stats` to return time series | **M/L** | Schema + Agent(none) + FE |
| B3 | **Target-role / level calibration** | Anchor scores to the role and level the user is actually targeting | "For a senior AI Engineer, this is below bar / at bar / above bar" per competency; gap callouts | `job_role`, `experience_level`, `has_jd` already stored (`db.py:299`, `:322`); feed JD summary into the rubric | **M** | Prompt + FE |
| B4 | **STAR / structure scoring with per-question matrix (behavioral)** | Behavioral candidates need to see exactly which STAR element they dropped | Per-question S/T/A/R checkmarks + "missing quantified Result" notes | `behavioral_track_specific_schema` already defines `per_question` (`prompts.py:1215`); needs B1 + question text from `track_config` | **M** | Prompt + FE (depends on B1) |
| B5 | **Coding execution / test-case results** | Today correctness is an LLM opinion, not a real run; actually executing tests would make code feedback trustworthy | "7/10 test cases passed" with failing-case diffs instead of "looks partial" | NEW capture: a sandboxed runner + stored test cases per problem; `coding_submissions.evaluation_result` can hold real results | **L** | Schema + Agent + infra |
| B6 | **"Interview Personality" v2 (real profile, not a sentence)** | Current widget is a single concatenated string; make it a genuine skills profile | Radar chart of avg competencies, strengths/recurring-weakness tags, filler/pace trend, session streak | Builds on B2 persisted per-session scores | **M** | FE (depends on B2) |
| B7 | **Answer rewrite as a saved, reusable artifact** | The narrative already produces a before/after rewrite (`prompts.py:458`); make it first-class and trackable | "My rewrites" library; mark a fix as practiced; resurface in next session | Extract the rewrite into a structured field; new lightweight `practice_items` storage | **M** | Prompt + Schema + FE |
| B8 | **Regeneration + model/version metadata** | Feedback is a one-shot, process-cached, single-model artifact today | "Regenerate" button; record model + prompt version + timestamp on each feedback row | Add `model`, `version`, `generated_at` to `feedback_data`; the in-process `_feedback_cache` (`app.py:1231`) should be retired in favor of DB | **S/M** | Schema + FE |

---

## 4. The 3 highest-leverage easy wins

1. **E1 — Speech Analytics panel.** Zero new capture, zero new LLM cost: the data is already in the
   API response and just isn't rendered. Deterministic, defensible, and the single most concrete
   coaching signal we own (filler counts, WPM band, per-turn pace).

2. **E3 — Coding report block.** Coding-track users currently receive *no* code feedback at all
   despite us storing correctness, approach grade, complexity, edge cases, and suggestions per
   attempt. Rendering `coding_submissions` (already returned at `app.py:1460`) closes an embarrassing
   gap for an entire track with frontend-only work.

3. **E2 — Fix the hallucinated filler count + persist analytics.** This corrects a real bug (the
   scores' `filler_word_count` is LLM-invented because `FEEDBACKSCORES.user_template` never receives
   the speech data) and persisting analytics is the prerequisite that unlocks every longitudinal
   feature (B2, B6).

---

## 5. Deep-dive notes

### 5.1 Richer per-competency feedback WITH evidence
The narrative prompt (`POSTINTERVIEWFEEDBACK`, `prompts.py:342`) already demands quoted evidence and
micro-techniques, and the sample output (`feedback/pranav_mishra_20251217_171529_feedback.json`)
shows good quotes embedded in prose. The gap is purely structural: the *scores* layer
(`FEEDBACKSCORES`) returns name/score/quick_take with no quote, so the UI can't bind evidence to a
bar. Recommended fix (E4): have the scores call return `{name, score, evidence_quote,
micro_fix}` per competency, then make each competency bar expandable. This is a prompt + FE change;
no schema or agent work.

### 5.2 Longitudinal / trend insights
Everything needed already exists per interview (`feedback.feedback_data.scores`, plus speech
analytics once E2 persists them). `get_user_stats` (`db.py:112`) currently collapses all scores into
one average. Extend it to return an ordered time series keyed by `interview_date`, then drive a trend
line and per-competency deltas (B2) and a real personality profile (B6). The retention story —
"come back and watch your clarity climb" — is the strongest product argument in this epic and is
unlocked by one schema-light change (persist scores you already generate).

### 5.3 Tying coding execution into the report
Two tiers:
- **Now (E3):** surface the LLM evaluation we already store (`coding_submissions.evaluation_result`:
  correctness, approach_quality, edge cases, complexity, suggestions, attempt history, time_spent).
  Frontend-only.
- **Later (B5):** replace LLM-judged correctness with a real sandboxed execution against stored test
  cases, so "7/10 tests passed" is fact, not opinion. This is the only feature in the epic that needs
  new infra (a runner) and new capture (test cases per generated problem).

### 5.4 Grounding caveats
This plan references only fields/files that exist today. Two things to keep honest:
- User turns are **not** stage-tagged (`agent_worker.py:1266`); per-stage attribution (E6) must be
  *derived* by interleaving user/agent timestamps, not read from a column.
- The `TRACK_FEEDBACK` schema (B1/B4) is written but unused — activating it is real work, not a
  config flip, because the generation path, persistence shape, and UI are all built around the flat
  `FEEDBACKSCORES`/`POSTINTERVIEWFEEDBACK` output today.
