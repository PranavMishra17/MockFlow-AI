# MockFlow-AI: Multi-Track Interview System — Implementation Prompt

## CONTEXT

You are working on **MockFlow-AI**, a production-deployed voice-based mock interview platform built on LiveKit Agents SDK, Flask, Supabase, and OpenAI/Deepgram. It is currently live at `mockflow-ai.onrender.com`. The codebase uses a BYOK (Bring Your Own Keys) model, per-session worker spawning via direct room connection (not LiveKit dispatch), and a Finite State Machine (FSM) for interview stage management.

You are tasked with a **major feature update**: adding multiple interview **tracks** (Behavioral, Technical Voice, Technical Coding) alongside the existing Intro track, plus supporting infrastructure (skip intro, cached welcome speech, speech analytics, feedback revamp). This is a production codebase — every change must be backwards-compatible, gracefully handle errors, and not break existing functionality.

---

## PHASE 0: UNDERSTAND THE REPO (DO THIS FIRST)

**Before writing ANY code or plan, you MUST thoroughly read and understand the existing codebase.**

### Step 0.1 — Read Skills

Before touching any file creation or editing, read all relevant skill files that apply to this project. At minimum:

- If creating or modifying frontend/HTML/CSS/JS → read `/mnt/skills/public/frontend-design/SKILL.md`
etc

**Use these skills throughout implementation. They contain hard-won best practices. Do not skip them.**

### Step 0.2 — Map the Project Structure

Run a full directory listing. Understand every file's purpose. Cross-reference with this known structure:

```
MockFlow-AI/
├── app.py                      # Flask server, OAuth, token gen, worker spawning
├── agent_worker.py             # LiveKit agent with FSM and voice pipeline
├── fsm.py                      # Finite State Machine for interview stages
├── prompts.py                  # Stage-specific instructions and feedback prompts
├── supabase_client.py          # DB client with encrypted API key storage
├── auth_helpers.py             # Google OAuth helpers
├── worker_manager.py           # Per-session worker process management
├── postprocess.py              # Transcript merging and formatting
├── conversation_cache.py       # Resume/JD text caching for sessions
├── document_processor.py       # PDF/DOCX/TXT text extraction
├── templates/                  # Jinja2 HTML templates
│   ├── index.html, form.html, interview.html, dashboard.html
│   ├── feedback.html, settings.html, error.html
├── static/                     # CSS, JS, images
├── requirements.txt
├── docs/ AGENT_DESIGN.md, DEPLOYMENT.md, LIVEKIT_ANALYSIS.md
├── docs/ VOICE_AGENT_ARCHITECTURE.md, SUPABASE_BACKEND_SCHEMA.md
└── README.md
```

### Step 0.3 — Read Every Core File

Read these files **in full** before planning anything:

1. `fsm.py` — Understand current `InterviewStage` enum, `InterviewState` dataclass, time limits, question tracking, transition logic
2. `agent_worker.py` — Understand voice pipeline setup, tool definitions (`transition_stage`, `ask_question`, `assess_response`), fallback timer, acknowledgement mechanism, session lifecycle
3. `prompts.py` — Understand how stage instructions are structured, role-specific injection, feedback generation prompts
4. `app.py` — Understand routes, token generation, worker spawning, form data flow, how metadata passes to agent
5. `worker_manager.py` — Understand subprocess spawning, environment variable passing, cleanup
6. `supabase_client.py` — Understand DB operations, encryption, table structure
7. `document_processor.py` — Understand current resume/JD parsing (NOTE: partially working, needs verification/fix)
8. `conversation_cache.py` — Understand how resume/JD text is cached per session
9. `postprocess.py` — Understand transcript processing
10. `templates/form.html` — Understand current form fields, JS, submission flow
11. `templates/interview.html` — Understand LiveKit room UI, caption display, audio visualization
12. `templates/feedback.html` — Understand current feedback rendering
13. `templates/dashboard.html` — Understand past interview listing
14. `static/styles.css` — Understand design system, color scheme, component patterns
15. All other CSS/JS files in `static/`

### Step 0.4 — Read Documentation Files

Read these for architectural context (they are in the docs/ folder):

- `AGENT_DESIGN.md` — Full system design, tool behavior, FSM logic, fallback timers
- `DEPLOYMENT.md` — Production deployment details, direct room connection, VAD tuning
- `VOICE_AGENT_ARCHITECTURE.md` — Industry best practices the project follows
- `LIVEKIT_ANALYSIS.md` — LiveKit SDK patterns used in the project
- `SUPABASE_BACKEND_SCHEMA.md` — Database schema and RLS policies

### Step 0.5 — Verify Current State

Before planning changes, verify:

- [ ] Does `document_processor.py` actually parse PDFs/DOCX correctly? Test it.
- [ ] What does the current feedback system output? Trace the full flow from interview end → feedback generation → display.
- [ ] How does the form currently pass data (candidate name, role, experience, resume, JD) to the agent worker? Trace the full data flow: form submission → token generation → worker spawn → agent receives metadata.
- [ ] What LiveKit data channels are currently in use? (Captions? Stage updates? Anything else?)
- [ ] What is the exact current `InterviewStage` enum? What are the exact stage time limits?
- [ ] How does the fallback timer currently work? Read the full implementation.

**Only after completing ALL of Phase 0 should you proceed to Phase 1.**

---

## PHASE 1: PLAN THE IMPLEMENTATION

Based on your understanding of the codebase, create a detailed implementation plan. The plan must be organized into **two patches**:

### PATCH 1 — Track Infrastructure + Behavioral + Technical Voice

Everything except the Technical Coding track. Coding track is a visible but disabled placeholder ("Coming Soon" / "Beta").

### PATCH 2 — Technical Coding Track

Monaco editor, code evaluator, timer, submissions, retries. Built on the infrastructure from Patch 1.

---

## DECIDED REQUIREMENTS (DO NOT DEVIATE)

Every decision below was explicitly made. Do not second-guess, reinterpret, or skip any of them.

### TRACK SYSTEM

- **One track per session.** User picks a track on the existing form page (dropdown or card selector). Each track is a separate interview session.
- **Tracks available:** Intro (existing, default), Behavioral, Technical Voice, Technical Coding (Patch 2 — placeholder in Patch 1)
- **Track selection UI:** Added to the existing `form.html` page. No new pages.
- **No chaining.** Each session = one track. Interview ends when that track's FSM completes.

### SKIP INTRO

- A "Skip Intro" button visible at the start of the interview (in `interview.html`)
- Clicking it **hard-skips** both `GREETING` and `SELF_INTRO` stages entirely
- Agent jumps directly to the selected track's first real stage
- The skip must update the FSM state, notify the agent, and update the frontend UI stage indicator
- Data flow: frontend sends skip signal (LiveKit data channel or participant metadata) → agent receives → FSM transitions → agent begins track's first stage
- Skipped stages should be recorded in the interview record (`skipped_stages` field already exists in DB)

### CACHED WELCOME SPEECH

- **Track-specific, no candidate name.** Each track has its own welcome audio (e.g., "Welcome to your behavioral interview. Here's how this will work...")
- **Generated on first use per track.** When a track's welcome speech is needed and no cached file exists, generate it via TTS API, save to disk. All subsequent sessions for that track use the cached file.
- **Storage:** Save as audio files in a predictable path (e.g., `static/audio/welcome_behavioral.mp3`)
- **Delivery:** Agent plays the cached audio file directly instead of generating TTS. If cache miss, generate → cache → play.
- **This replaces the first LLM + TTS call for the greeting.** The agent's first LLM-generated speech should be the first actual question, not the welcome boilerplate.

### FSM ARCHITECTURE

- **Separate enum per track.** Do NOT collapse all stages into one giant enum.
  - Existing: `InterviewStage` (GREETING, SELF_INTRO, PAST_EXPERIENCE, COMPANY_FIT, CLOSING) — keep for Intro track
  - New: `BehavioralStage` (GREETING, SELF_INTRO, BEHAVIORAL_QUESTIONS_1, BEHAVIORAL_QUESTIONS_2, ..., BEHAVIORAL_QUESTIONS_N, CLOSING)
  - New: `TechnicalVoiceStage` (GREETING, SELF_INTRO, EXPERIENCE_DISCUSSION, TECHNICAL_CONCEPTS_1, TECHNICAL_CONCEPTS_2, ..., TECHNICAL_CONCEPTS_N, CLOSING)
  - New: `CodingStage` (GREETING, SELF_INTRO, WARM_UP, CODING_PROBLEM_1, CODING_PROBLEM_2, ..., CODING_PROBLEM_N, CLOSING) — Patch 2
- **Each track has its own `InterviewState` subclass or config** with track-specific fields (e.g., `selected_framework` for Behavioral, `selected_topics` for Technical Voice, `coding_submissions` for Coding)
- **Shared base tools** (`transition_stage`, `ask_question`, `assess_response`) work across all tracks. The tool implementations should be track-aware (check current track, apply track-specific logic).
- **Shared base state** (candidate name, role, experience level, stage timing, question tracking) lives in a base class. Track-specific state extends it.
- **Fallback timer pattern** remains the same: async timeout per stage forces transition if agent stalls. Each track defines its own time limits per stage.
- **Transition acknowledgement mechanism** remains the same: queue acknowledgement → inject via tool response.

### BEHAVIORAL TRACK (~15 min total)

**Stages:** GREETING → SELF_INTRO → BEHAVIORAL_QUESTIONS → CLOSING

**Leadership Frameworks (all 4 ship in Patch 1):**

1. **Amazon** — 16 Leadership Principles (Customer Obsession, Ownership, Invent and Simplify, Are Right A Lot, Learn and Be Curious, Hire and Develop the Best, Insist on the Highest Standards, Think Big, Bias for Action, Frugality, Earn Trust, Dive Deep, Have Backbone, Deliver Results, Strive to be Earth's Best Employer, Success and Scale Bring Broad Responsibility)
2. **Google** — Googleyness, Leadership, Role-Related Knowledge, General Cognitive Ability
3. **Meta** — Move Fast, Be Bold, Focus on Impact, Be Open, Build Social Value
4. **Generic** — Leadership, Teamwork, Conflict Resolution, Problem Solving, Communication, Adaptability, Initiative, Decision Making, Time Management, Accountability, Mentorship, Innovation

**For each framework:**
- Curated question bank: 2-3 questions per principle/competency + 2-3 follow-up questions per main question(based on user story and answer)
- Questions should be high-quality, industry-standard behavioral interview questions
- Store in a structured format in `prompts.py` or a dedicated `question_banks.py` / `question_banks/` directory

**User selects framework on form page.** Dropdown: Amazon (default) / Google / Meta / Generic.

**Follow-up depth is configurable by user on form:**
- Light: 1 follow-up per question
- Deep: 2+ follow-ups
These all are soft limits, agent can ask more questions if needed.

**The agent must:**
- Ask main questions from the selected framework's bank(not all, select 2-3 main questions)
- Follow up based on depth setting, ask 1-2 follow-up questions per main question, probing for STAR elements (Situation, Task, Action, Result)
- Track which principles/competencies have been covered
- Assess response quality via `assess_response` tool (track STAR adherence)
- Transition between questions based on depth score + follow-up count + time remaining

**STAR Method Instructions:**
- Displayed as a text overlay/modal on the form page or pre-interview screen BEFORE the interview starts
- NOT spoken by the agent. The agent can reference STAR briefly if a candidate's answer lacks structure, but the detailed instructions are read by the user beforehand.
- Content: explain STAR, give an example, tips for strong answers

**Custom Questions:**
- A text field on the form page where users can type additional questions (one per line)
- These get appended to the selected framework's question bank for that session
- Agent treats them like any other question in the bank

**Resume/JD personalization:**
- If resume is uploaded, agent references specific experiences from resume when asking follow-ups
- If JD is provided, agent connects behavioral questions to JD requirements
- This uses the existing `document_processor.py` + `conversation_cache.py` flow (fix if broken)

### TECHNICAL VOICE TRACK (~15 min total)

**Stages:** GREETING → SELF_INTRO → EXPERIENCE_DISCUSSION → TECHNICAL_CONCEPTS → CLOSING

**Topic Selection (hybrid):**
- Auto-suggest topics from resume/JD if provided (extract technologies, frameworks, concepts)
- Display suggested topics as pre-checked checkboxes on form
- User can uncheck suggestions and/or add custom topics via text field
- If no resume/JD: show a default topic list based on role (e.g., Software Engineer → DSA, System Design, Databases, OS, Networking)

**Default topic pools by role category:**
- Engineer: Data Structures, Algorithms, System Design, Databases, OS, Networking, API Design, Concurrency
- Frontend: DOM, CSS Architecture, State Management, Performance, Accessibility, Browser APIs
- Backend: Distributed Systems, Caching, Message Queues, Databases, API Design, Authentication
- Data/ML: Statistics, ML Fundamentals, Data Pipelines, Feature Engineering, Model Evaluation
- DevOps: CI/CD, Containers, Orchestration, Monitoring, Infrastructure as Code, Cloud Services
- Generic: Programming Fundamentals, OOP, Design Patterns, Testing, Version Control
- Language-based: C++ fundamentals, Python, node.js, TypeScript, etc etc

- Users should ahve the freedom to pick topics from the list or add their own custom topics- 3 max topics can be selected.

**EXPERIENCE_DISCUSSION stage:**
- Agent asks about candidate's experience with selected topics
- Probes for depth: what they built, challenges faced, decisions made
- Warm-up before pure technical questions

**TECHNICAL_CONCEPTS stage:**
- Conceptual questions only (no coding): "Explain how X works", "Compare X vs Y", "When would you use X over Y", "What are the tradeoffs of X"
- Questions are generated/selected based on the chosen topics + experience level
- Agent assesses understanding depth, asks follow-ups on weak areas

**Curated question bank per topic:**
- 5-8 conceptual questions per topic, tagged by difficulty (junior/mid/senior)
- Store in structured format alongside behavioral question banks
- I still think this is not a good idea, we should not have a static question bank, we should generate questions based on the candidate's experience and the job description.

**Personalization:**
- Experience level adjusts question difficulty
- Resume technologies get priority in topic ordering
- JD requirements influence which topics get more time

### TECHNICAL CODING TRACK (Patch 2 — Placeholder in Patch 1)

**Patch 1 deliverable:** The track appears in the form dropdown but is **disabled/grayed out** with a label like "Coming Soon" or "In Beta". Selecting it shows a message. The `CodingStage` enum exists in code but is not wired to any agent logic.

**Patch 2 full spec (document now, implement later):**

**Stages:** GREETING → SELF_INTRO → WARM_UP → CODING_PROBLEM_1 → CODING_PROBLEM_2 → CLOSING

**Frontend — Interview Room Changes:**
- Split-view layout in `interview.html` when coding track is active:
  - Left panel: problem statement (text) top + voice interaction area (audio viz, captions) bottom
  - Right panel: Monaco editor + language dropdown + Submit button + retry counter + per-question timer
- Monaco Editor (loaded from CDN):
  - Languages: Python, JavaScript, Java, C++, Go — user picks from dropdown per question
  - Syntax highlighting, autocomplete, line numbers
  - No compilation/execution
- Submit button: sends editor content to agent for evaluation
- Timer: per-question, set by agent (e.g., 15 min). Visible countdown. When expired, auto-submit current code.
- Retry counter: "Attempt 1/3" — max 3 submissions per question

**Agent Behavior During Coding:**
- **Strict observer.** Agent stays silent while user is coding.
- Agent speaks only when: (a) user explicitly talks/asks something, (b) user clicks Submit, (c) timer expires
- If user thinks aloud, agent can respond reactively but does NOT proactively offer guidance
- If user asks for hints: agent gives subtle nudges only ("Think about edge cases", "What happens with empty input?") — never reveals solution or approach

**Code Evaluation:**
- **Separate LLM call**, not the voice agent's context
- Uses GPT-4o (configurable, BYOK — user's API key, multi-provider support in future)
- Dedicated evaluator prompt: receives problem statement + candidate code + language
- Returns structured JSON:
  ```json
  {
    "correctness": "pass" | "partial" | "fail",
    "approach_quality": "A" | "B" | "C" | "D" | "F",
    "edge_cases_handled": ["empty input", "single element"],
    "edge_cases_missed": ["negative numbers", "overflow"],
    "time_complexity": "O(n)",
    "space_complexity": "O(1)",
    "code_quality_notes": ["good variable naming", "missing error handling"],
    "suggestions": ["consider handling null input", "could optimize with hash map"]
  }
  ```
- Voice agent receives this JSON, interprets it, and speaks feedback **naturally** (not reading JSON fields verbatim). Example: "Your solution handles the core case well but misses a couple of edge cases — what happens if the input is empty?"
- After feedback, if retries remain and timer hasn't expired, user can modify code and resubmit
- Add a skip option for the coding questions, which will skip the coding question and move to the next question.

**Data Flow for Code Submission:**
- Frontend: user clicks Submit → sends editor content via LiveKit data channel (or HTTP POST to Flask endpoint)
- Agent worker: receives code → makes separate LLM API call with evaluator prompt → receives JSON → interprets → speaks
- Store each submission in `coding_submissions` table (Patch 2 DB migration)

**Problem Bank:**
- Curated coding problems tagged by topic and difficulty
- Each problem: title, description, examples (input/output), constraints, expected time, difficulty
- Agent selects problems based on selected topics + experience level
- Again, I still think this is not a good idea, we should generate questions based on the candidate's experience and the job description. This can be dynamic and can be tailored to the candidate's experience level and the job description. This will make the interview more personalized and relevant to the candidate.

### SPEECH ANALYTICS

**Real-time (lightweight, in-interview):**
- Count filler words ("um", "uh", "like", "you know", "basically", "actually", "so", "right")
- Track speaking pace (words per minute)
- Track pause frequency and duration
- Display as a small, non-intrusive counter/indicator in the interview UI (e.g., corner widget: "Fillers: 7 | Pace: 142 wpm") [NOT IMPORTANT, but store this data]
- Implementation: process STT transcripts on the frontend as they arrive via data channel. Pure JS, no backend needed for real-time counters.

**Post-interview (detailed, in feedback):** [IMPORTANT]
- Full analysis of transcript: filler word breakdown, pace over time, longest pauses, confidence indicators
- Store in `interviews.metadata` JSONB field
- Display in feedback page as a dedicated "Communication Analytics" section
- Implementation: process full conversation JSON in the feedback generation step (alongside the LLM feedback call)

### FEEDBACK SYSTEM REVAMP

**Current state:** Minimal — GPT-4o post-processing call with basic strengths/improvements/question-specific feedback. Needs significant upgrade.

**New feedback structure (all tracks):**

**Shared base categories (all tracks get these):**
- **Communication:** Letter grade (A+ to F) + explanation. Covers clarity, conciseness, structure, filler usage, pace.
- **Structure:** Letter grade + explanation. Covers STAR adherence (behavioral), logical flow (technical), problem decomposition (coding).
- **Speech Analytics:** Filler word count + breakdown, average pace, pause analysis. (From speech analytics data.)

**Track-specific extras:**

*Behavioral:*
- **Leadership Principle Coverage:** Which principles were covered, depth per principle, grade per principle
- **STAR Adherence:** Per-question STAR element detection (did they state Situation? Task? Action? Result?)
- **Specificity:** Grade on how concrete vs. vague their examples were

*Technical Voice:*
- **Concept Accuracy:** Grade per topic area discussed
- **Depth of Understanding:** Surface-level vs. deep understanding per topic
- **Articulation:** How well they explained technical concepts verbally

*Technical Coding (Patch 2):*
- **Code Quality:** Per-problem grade
- **Problem Solving Approach:** Grade on how they broke down the problem
- **Edge Case Handling:** What they caught vs. missed
- **Time Management:** How they used the allotted time

**Feedback generation:**
- Single LLM call (GPT-4o or same model as voice agent) with the full conversation JSON + track type + speech analytics data
- Prompt must request structured JSON output matching the above format
- Each category: letter grade (A+, A, A-, B+, B, B-, C+, C, C-, D, F) + 2-4 sentence explanation + actionable tip
- Question-specific feedback: for each main question asked, what was strong and what could improve

**Feedback display:**
- Redesign `feedback.html` to show:
  - Overall grade (weighted average across categories)
  - Per-category breakdown with letter grades prominently displayed
  - Expandable question-by-question feedback
  - Speech analytics charts (filler word trend, pace over time)
  - Track-specific sections

### DATABASE CHANGES

**Patch 1 migrations (add to existing Supabase SQL):**

```sql
-- Add track column to interviews
ALTER TABLE interviews ADD COLUMN IF NOT EXISTS track VARCHAR DEFAULT 'intro';

-- Add speech analytics to metadata (already JSONB, no schema change needed)
-- Convention: interviews.metadata.speech_analytics = {...}

-- Add track-specific config storage
ALTER TABLE interviews ADD COLUMN IF NOT EXISTS track_config JSONB DEFAULT '{}';
-- Stores: framework (behavioral), topics (technical), depth setting, custom questions, etc.
```

**Patch 2 migrations:**

```sql
-- Coding submissions table
CREATE TABLE IF NOT EXISTS coding_submissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    interview_id UUID NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    problem_title TEXT NOT NULL,
    problem_description TEXT,
    language VARCHAR NOT NULL,
    code_submitted TEXT NOT NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    evaluation_result JSONB,
    time_spent_seconds INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coding_submissions_interview
ON coding_submissions(interview_id);

ALTER TABLE coding_submissions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own submissions"
ON coding_submissions FOR SELECT
USING (auth.uid() = user_id);

CREATE POLICY "Service can insert submissions"
ON coding_submissions FOR INSERT
WITH CHECK (auth.uid() = user_id);
```

create properly documented SQL queries for all the above changes in supabase-backend/ folder. Make sure to add comments to the SQL queries explaining what each query does.

### FORM PAGE CHANGES (`form.html`)

Add to the existing form (do NOT create a new page):

1. **Track selector** — Dropdown or card-based selector at the top of the form:
   - Intro Call (default, existing behavior)
   - Behavioral Interview
   - Technical Voice Interview
   - Technical Coding Interview (disabled, "Coming Soon")

2. **Conditional fields that appear based on track selection:**

   *Behavioral:*
   - Framework dropdown: Amazon (default) / Google / Meta / Generic
   - Depth selector: Light / Medium (default) / Deep
   - Custom questions textarea (optional, one per line)

   *Technical Voice:*
   - Topic checkboxes (auto-populated from resume/JD if available, else role-based defaults)
   - Custom topics text field
   - Custom questions textarea (optional)

   *Technical Coding (Patch 1 — disabled):*
   - Grayed out message: "Technical Coding rounds are coming soon."

   *Intro:*
   - No new fields (existing form fields suffice)

3. **STAR method modal/overlay** — Appears when Behavioral track is selected. Dismissible. Contains:
   - What is STAR method
   - Example of a good STAR answer
   - Quick tips
   - "Got it" button to dismiss

4. All new form data must be passed through to the agent worker via the existing metadata flow (participant attributes / room metadata / subprocess env vars — match the existing pattern).

### INTERVIEW ROOM CHANGES (`interview.html`)

1. **Skip Intro button** — Visible during GREETING or SELF_INTRO stages. Disappears after those stages complete or are skipped. Sends signal to agent via data channel.

2. **Stage indicator** — Must reflect the current track's stages (not hardcoded to Intro track stages). Dynamic based on track type.

3. **Speech analytics widget** — Small, non-intrusive overlay showing live filler count and speaking pace. Toggleable (user can hide it). Positioned in a corner, semi-transparent.

4. **Coding track layout (Patch 2)** — Split view. Left: voice/problem. Right: Monaco editor + controls. This is a significant layout change; architect it now even if not implementing the editor in Patch 1.

### WORKER / AGENT CHANGES

**`agent_worker.py` refactoring:**
- The agent must be track-aware. It receives the track type from metadata.
- Based on track type, it loads the correct:
  - Stage enum and FSM configuration
  - Question bank / topic bank
  - Stage instructions (from `prompts.py`)
  - Tool behavior (same base tools, but track-aware branching inside)
  - Time limits per stage
  - Fallback timer configuration
- The welcome speech is cached audio, not LLM-generated. Agent plays cached file. If cache miss, generate via TTS API → save to disk → play.
- The agent's system prompt / instructions change per track and per stage (this is already the pattern — extend it).

**`fsm.py` refactoring:**
- Add new stage enums: `BehavioralStage`, `TechnicalVoiceStage`, `CodingStage`
- Each has its own time limits dict, min questions dict, and transition logic
- Base `InterviewState` retains shared fields. Create subclasses or use composition for track-specific state.
- The state machine logic (transition validation, time tracking, question counting) must work generically across all stage enums.

**`prompts.py` expansion:**
- Add stage instructions for every stage in every track
- Add question banks for all 4 leadership frameworks
- Add technical concept question banks per topic
- Add coding problem bank (Patch 2, but structure the file now)
- Add feedback generation prompts per track
- Structure: either expand `prompts.py` or split into `prompts/` package with modules per track

**`app.py` changes:**
- Form submission handler must accept new fields (track, framework, depth, topics, custom questions)
- Pass all new metadata to worker spawning
- Token generation must include track info in participant attributes
- New endpoint for cached welcome audio serving (or serve from static)

### FILE ORGANIZATION

Prefer this structure for new code (suggest improvements if justified, but maintain separation of concerns):

```
MockFlow-AI/
├── tracks/                       # NEW: Track definitions package
│   ├── __init__.py
│   ├── base.py                   # Base track config, shared stage logic
│   ├── intro.py                  # Intro track (wraps existing behavior)
│   ├── behavioral.py             # Behavioral track config, stages, question selection
│   ├── technical_voice.py        # Technical voice track config, stages, topic handling
│   └── technical_coding.py       # Coding track config (Patch 2 logic, Patch 1 placeholder)
│
├── question_banks/               # NEW: Curated question/problem banks
│   ├── __init__.py
│   ├── behavioral/
│   │   ├── amazon.py             # Amazon 16 LPs + questions
│   │   ├── google.py             # Google framework + questions
│   │   ├── meta.py               # Meta framework + questions
│   │   └── generic.py            # Generic competencies + questions
│   ├── technical/
│   │   ├── dsa.py, system_design.py, databases.py, os.py, networking.py, etc.
│   └── coding/                   # Patch 2
│       ├── problems.py           # Problem bank structure
│       └── evaluator.py          # Code evaluation LLM prompt + caller
│
├── speech_analytics.py           # NEW: Filler detection, pace calculation
├── audio_cache.py                # NEW: Welcome speech caching logic
├── fsm.py                        # MODIFIED: Add new stage enums, generalize state machine
├── prompts.py                    # MODIFIED: Expand with track-specific instructions
├── agent_worker.py               # MODIFIED: Track-aware agent logic
├── app.py                        # MODIFIED: New form fields, metadata passing
├── ... (rest unchanged)
```

---

## CODING STANDARDS (ENFORCE THESE)

1. **No hardcoding.** All track-specific values (time limits, question counts, topic lists) must be configurable constants or config structures, not magic numbers buried in logic.

2. **Graceful error handling.** Every API call, every LLM call, every DB operation, every file I/O — wrapped in try/except with comprehensive logging. Failures must not crash the interview session. Fallback behavior for every failure mode.

3. **Comprehensive logging.** Use Python `logging` module (already in use). Log at appropriate levels:
   - `DEBUG`: Detailed flow (tool calls, state transitions, timing)
   - `INFO`: Session lifecycle (connect, stage change, disconnect)
   - `WARNING`: Degraded behavior (cache miss, slow response, fallback triggered)
   - `ERROR`: Failures (API error, DB error, unexpected state)

4. **Reusable code.** No duplicated logic. Shared utilities for common patterns (question selection, time formatting, transcript processing). Track-specific behavior via polymorphism or config, not copy-paste.

5. **No test code in production files.** No `if __name__ == "__main__": test_something()` blocks. No debug prints. No commented-out test snippets.

6. **No markdown files or summaries unless explicitly asked.** Do not generate documentation files, changelogs, or summary docs as part of implementation. Focus on code.

7. **Backwards compatibility.** The existing Intro track must continue to work exactly as it does now. Users who don't select a track get the default Intro experience. Existing interviews in the database must not break.

8. **Production-safe migrations.** All DB changes must use `IF NOT EXISTS` / `IF NOT NULL` guards. Column additions must have defaults. No destructive changes to existing tables.

9. **Frontend consistency.** Match the existing design system (bold minimalist, high-contrast, WCAG AA). Read `static/styles.css` and follow established patterns. No new design systems or CSS frameworks.

10. **No emojis anywhere** — not in code, not in comments, not in UI text, not in prompts.

---

## IMPLEMENTATION PLAN FORMAT

After completing Phase 0, produce your implementation plan as follows:

### For each patch, list:

1. **Files to create** — with purpose and key contents
2. **Files to modify** — with specific sections/functions to change and what changes
3. **Database migrations** — exact SQL
4. **Dependencies** — any new pip packages needed
5. **Ordered task list** — numbered steps, with dependencies noted. Each task should be atomic and testable.

### Ordering principle:

1. Infrastructure first (FSM refactor, track configs, DB migrations)
2. Backend second (agent changes, prompts, question banks)
3. Frontend third (form changes, interview room changes, feedback page)
4. Integration last (end-to-end testing scenarios to verify manually)

### For Patch 1, the ordered feature list should be:

1. FSM refactor (new stage enums, generalized state machine)
2. Track configuration system (base + per-track configs)
3. Question banks (all 4 behavioral frameworks, technical concept banks)
4. Database migration (track column, track_config column)
5. Form page updates (track selector, conditional fields, STAR modal)
6. Audio cache system (welcome speech generation + caching)
7. Skip Intro mechanism (frontend signal + agent handling)
8. Agent worker refactoring (track-aware logic, prompt injection, tool behavior)
9. Prompts expansion (stage instructions per track per stage)
10. Speech analytics — real-time (frontend filler counter)
11. Speech analytics — post-interview (transcript analysis)
12. Feedback system revamp (new rubric structure, letter grades, track-specific sections)
13. Feedback page redesign (new layout with grades, analytics, expandable sections)
14. document_processor.py verification and fix
15. Coding track placeholder (disabled UI, enum exists, no agent logic)
16. End-to-end integration verification

### For Patch 2, the ordered feature list should be:

1. Monaco editor integration in interview.html
2. Split-view layout
3. Coding problem bank
4. Code evaluator (separate LLM call, structured JSON, evaluator prompt)
5. Coding-specific agent tools (read_editor, start_timer, evaluate_code)
6. CodingStage FSM wiring (agent logic for coding track stages)
7. Submission flow (Submit button → data channel → agent → evaluator → feedback)
8. Retry mechanism (attempt counter, max 3, timer integration)
9. Per-question timer (frontend countdown + auto-submit)
10. coding_submissions table migration
11. Coding-specific feedback integration
12. End-to-end coding track verification

---

## PROCEED

1. Complete Phase 0 (read the entire codebase).
2. Produce the implementation plan for Patch 1 and Patch 2 in the format above.
3. After the plan is reviewed and approved, copy the plan for both patches into md files in root directory as patch1.md and patch2.md , to be referenced later. Then begin implementing Patch 1 task by task.
3. Make use of subagents or feature-builder for iteartive takss, and for each task, make sure to update the plan as well.   
4. After each task, verify it works with the existing system (no regressions).
5. After all Patch 1 tasks complete, do a full integration check.
6. Then begin Patch 2.

**Do not start coding before the plan is reviewed.** Present the plan first.