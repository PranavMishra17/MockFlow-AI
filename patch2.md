# MockFlow-AI Patch 2 — Technical Coding Track

## Overview

Patch 2 wires up the Technical Coding track stubbed in Patch 1. Adds a Monaco editor split-view, LLM-generated coding problems, a code evaluator (separate LLM call), per-problem timers, retry logic, and coding-specific feedback.

---

## Architecture Decisions

| Decision | Choice |
|---|---|
| Code submission transport | HTTP POST to `/api/coding/submit` (reliable for large code payloads) |
| Problem delivery to frontend | LiveKit data channel `{"type": "coding_problem", "problem": {...}}` |
| Problem generation | LLM-generated at WARM_UP stage, stored in CodingInterviewState |
| Monaco editor | CDN via RequireJS, lazy-loaded only for coding track |
| Split layout | `.interview-main.coding-mode` CSS class enables 3-column layout |
| Timer | Pure JS countdown, auto-submits on expire |
| Retry limit | 3 attempts per problem |
| Agent during coding | Silent observer — speaks only on submission, user question, or timer expiry |
| Code evaluation | Separate `openai.chat.completions.create()` call (not voice context) |

---

## Files to Create

- `supabase-backend/patch2_migration.sql` — coding_submissions table + RLS

## Files to Modify

| File | Change |
|---|---|
| `fsm.py` | `CodingInterviewState`, `CODING_STAGE_TIME_LIMITS`, `CODING_STAGE_MIN_QUESTIONS` |
| `tracks/technical_coding.py` | Real time limits, `is_available=True` |
| `prompts.py` | `CODING_GREETING/SELF_INTRO/WARM_UP/PROBLEM_STAGE/CLOSING`, `CODE_EVALUATOR`, extend `QUESTION_GENERATION` |
| `agent_worker.py` | Coding dispatch branches, `evaluate_code_submission` tool, `skip_coding_problem` tool, `code_submitted` data handler |
| `app.py` | `/api/coding/submit` endpoint |
| `supabase_client.py` | `save_coding_submission()` |
| `templates/form.html` | Enable coding card (remove disabled/Coming Soon), add language/difficulty/count fields |
| `templates/interview.html` | Monaco editor panel, split layout, submit/skip buttons, timer, retry counter |
| `static/interview.css` | `.coding-mode` 3-column layout, editor panel styles |

---

## Ordered Task List

### Step 1 — `CodingInterviewState` + Constants (`fsm.py`)
```python
CODING_STAGE_TIME_LIMITS = {
    CodingStage.GREETING: 30,
    CodingStage.SELF_INTRO: 120,
    CodingStage.WARM_UP: 300,
    CodingStage.CODING_PROBLEM_1: 900,
    CodingStage.CODING_PROBLEM_2: 900,
    CodingStage.CLOSING: 45,
}

@dataclass
class CodingInterviewState(InterviewState):
    track_type: str = "coding"
    preferred_language: str = "python"
    active_problem_count: int = 2
    generated_problems: List[dict] = field(default_factory=list)
    current_problem_index: int = 0
    submissions: List[dict] = field(default_factory=list)
    submissions_per_problem: dict = field(default_factory=dict)
    problem_start_times: dict = field(default_factory=dict)
    coding_stage_active: bool = False
```
Methods: `get_active_stages()`, `get_next_coding_stage()`, `get_attempts_for_problem(idx)`, override `get_stage_time_limit()`, override `get_document_context()`.

### Step 2 — Enable Track Config (`tracks/technical_coding.py`)
Real time limits from CODING_STAGE_TIME_LIMITS, `is_available=True`.

### Step 3 — Coding Prompts (`prompts.py`)
- `CODING_GREETING` — brief greeting, confirm readiness
- `CODING_SELF_INTRO` — background, preferred language
- `CODING_WARM_UP` — past coding experience, confirm language
- `CODING_PROBLEM_STAGE` — reads problem aloud, goes silent; template vars: `{problem_title}`, `{problem_description}`, `{examples}`, `{constraints}`, `{time_limit_minutes}`, `{attempt_number}`, `{max_attempts}`
- `CODING_CLOSING` — wrap up
- `CODE_EVALUATOR.system` — returns structured JSON: `{correctness, approach_quality, edge_cases_handled, edge_cases_missed, time_complexity, space_complexity, code_quality_notes, suggestions, brief_verbal_feedback}`
- `QUESTION_GENERATION.coding_system` — generates `{problems: [{title, description, examples, constraints, difficulty, time_limit_minutes, hints}]}`
- Update `build_stage_instructions()`, `get_transition_ack()`, `get_fallback_ack()` for CodingStage

### Step 4 — Agent Worker Coding Branches (`agent_worker.py`)
- State init: `elif track_type == 'coding'` → instantiate `CodingInterviewState`, read `preferred_language`
- Stage transition: add coding dispatch branch
- `generate_interview_questions`: add `elif track_type == 'coding'` → generate problems, set `active_problem_count`
- `get_current_question`: add coding branch → emit `{"type": "coding_problem", ...}` to UI
- New tool `evaluate_code_submission(problem_index, code, language)` → separate OpenAI call → POST to `/api/coding/submit` → return `brief_verbal_feedback`
- New tool `skip_coding_problem()` → marks problem skipped → transitions stage
- Data channel: add `code_submitted` handler → validate attempt count ≤ 3 → call `evaluate_code_submission`
- `finalize_and_disconnect`: include `problems_generated`, `preferred_language`, `submissions` in track_config

### Step 5 — HTTP Endpoint (`app.py` + `supabase_client.py`)
`POST /api/coding/submit` → stores to `coding_submissions` table; `save_coding_submission()` in supabase_client.

### Step 6 — Database Migration (`supabase-backend/patch2_migration.sql`)
```sql
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
CREATE INDEX IF NOT EXISTS idx_coding_submissions_interview ON coding_submissions(interview_id);
ALTER TABLE coding_submissions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can view own submissions" ON coding_submissions FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Service can insert submissions" ON coding_submissions FOR INSERT WITH CHECK (auth.uid() = user_id);
```

### Step 7 — Form Page (`templates/form.html`)
- Remove disabled class/Coming Soon from coding card
- Add coding section: language dropdown (Python/JS/Java/C++/Go), problem count (1/2), difficulty (Easy/Medium/Hard)
- Pass `preferred_language`, `problem_count`, `problem_difficulty` to `/api/token`

### Step 8 — Interview Room (`templates/interview.html` + `static/interview.css`)
**HTML additions:**
- `<div class="code-editor-panel" id="codeEditorPanel">` with: problem display area, language select, problem timer, attempt counter, Monaco container `id="monacoEditorContainer"`, Submit + Skip buttons
- Monaco CDN script (lazy-loaded for coding track only)

**JS additions:**
- `initMonaco()` — RequireJS loads Monaco, creates editor instance
- `setEditorLanguage(lang)`, `getEditorCode()`, `setEditorCode(code)`
- `handleCodeSubmit()` — POST to `/api/coding/submit` + signal agent via data channel
- `startProblemTimer(seconds)` — countdown, auto-submit at 0
- `updateAttemptCounter(attempt, max)`
- Data channel: handle `coding_problem` → display problem, start timer; handle `evaluation_result` → show feedback

**CSS additions:**
```css
.interview-main.coding-mode { grid-template-columns: 1fr 2fr 1fr; }
.code-editor-panel { display: flex; flex-direction: column; gap: 0.75rem; }
.problem-display { overflow-y: auto; max-height: 200px; font-size: 0.875rem; }
.problem-timer { font-variant-numeric: tabular-nums; font-weight: 700; font-size: 1.25rem; }
@media (max-width: 1024px) { .interview-main.coding-mode { grid-template-columns: 1fr; } }
```

### Step 9 — Coding Feedback (`app.py` + `prompts.py`)
- In feedback endpoints: if track == 'coding', fetch submissions from coding_submissions, pass to LLM
- `TRACK_FEEDBACK.coding_track_specific_schema`: per-problem code quality grade, approach grade, edge cases, time management

### Step 10 — End-to-End Verification
1. Form → coding track → language/difficulty fields appear → submit → interview starts
2. Agent greets → self intro → warm up discussion → generates 2 problems at WARM_UP
3. First problem delivered via data channel → Monaco appears → timer starts 15:00
4. User writes code → Submit → evaluation returned → agent speaks `brief_verbal_feedback`
5. Retry (attempt 2/3) → evaluation again → counter updates
6. Timer expires → auto-submit → agent evaluates
7. Skip problem → transitions to CODING_PROBLEM_2 or CLOSING
8. After closing → `coding_submissions` table has rows with evaluation_result JSON
9. Feedback page → shows per-problem grades

---

## Verification Command
```python
python -c "
from fsm import CodingStage, CodingInterviewState
s = CodingInterviewState()
print(s.stage.value, [x.value for x in s.get_active_stages()])
from tracks import get_track_config
c = get_track_config('coding')
print(c.is_available, c.time_limits[CodingStage.CODING_PROBLEM_1])
"
# Expected: greeting [...] / True 900
```
