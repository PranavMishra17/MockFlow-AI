# MockFlow-AI Multi-Track Interview System — Patch 1 Implementation Plan

## Context

MockFlow-AI currently supports one interview track (Intro). This plan adds Behavioral and Technical Voice tracks with per-question FSM stages, skip intro, pre-committed welcome audio, post-interview speech analytics, and a revamped feedback page. Technical Coding track is a disabled placeholder. Every change must be backwards-compatible — existing Intro track interviews must continue to work unchanged.

## Clarified Decisions

| Decision | Choice |
|---|---|
| Question banks | Fully dynamic — LLM generates questions at session start (no static bank files) |
| Behavioral FSM | Per-question stages: BEHAVIORAL_Q1, Q2, Q3 (max 3, skip unused) |
| Technical Voice FSM | Per-topic stages: TECHNICAL_CONCEPTS_1, 2, 3 (max 3 topics) |
| Welcome audio | Pre-generate 4 files once, commit to `static/audio/` |
| Speech analytics | Post-interview only (feedback page), no real-time widget |
| Stage naming | New enums use GREETING; existing Intro keeps WELCOME unchanged |

---

## Architecture

### Track System (`tracks/`)

```
tracks/
  __init__.py          # get_track_config(track_type) factory
  base.py              # TrackConfig dataclass
  intro.py             # Wraps existing InterviewStage behavior
  behavioral.py        # BehavioralStage config
  technical_voice.py   # TechnicalVoiceStage config
  technical_coding.py  # Placeholder, no agent logic
```

**`TrackConfig` dataclass** (`tracks/base.py`):
```python
@dataclass
class TrackConfig:
    track_type: str                           # 'intro'|'behavioral'|'technical_voice'|'coding'
    stage_enum: type                          # The Enum class for this track
    stage_sequence: list                      # Ordered list of stage enum members
    time_limits: dict                         # stage -> seconds
    min_questions: dict                       # stage -> int
    welcome_audio_file: str                   # e.g. 'static/audio/welcome_behavioral.mp3'
    first_real_stage: Any                     # Stage after skip-intro jumps to here
```

### FSM Changes (`fsm.py`)

**New enums** (added, existing `InterviewStage` untouched):

```python
class BehavioralStage(Enum):
    GREETING = "greeting"
    SELF_INTRO = "self_intro"
    BEHAVIORAL_Q1 = "behavioral_q1"
    BEHAVIORAL_Q2 = "behavioral_q2"
    BEHAVIORAL_Q3 = "behavioral_q3"   # skipped if only 2 questions
    CLOSING = "closing"

class TechnicalVoiceStage(Enum):
    GREETING = "greeting"
    SELF_INTRO = "self_intro"
    EXPERIENCE_DISCUSSION = "experience_discussion"
    TECHNICAL_CONCEPTS_1 = "technical_concepts_1"
    TECHNICAL_CONCEPTS_2 = "technical_concepts_2"   # skipped if <2 topics
    TECHNICAL_CONCEPTS_3 = "technical_concepts_3"   # skipped if <3 topics
    CLOSING = "closing"

class CodingStage(Enum):             # Patch 2 logic, Patch 1 enum only
    GREETING = "greeting"
    SELF_INTRO = "self_intro"
    WARM_UP = "warm_up"
    CODING_PROBLEM_1 = "coding_problem_1"
    CODING_PROBLEM_2 = "coding_problem_2"
    CLOSING = "closing"
```

**New state subclasses**:

```python
@dataclass
class BehavioralInterviewState(InterviewState):
    framework: str = "amazon"           # amazon|google|meta|generic
    depth_setting: str = "medium"       # light|medium|deep
    custom_questions: list = field(default_factory=list)
    generated_questions: list = field(default_factory=list)  # LLM-generated at start
    active_question_count: int = 2      # How many Q stages are active (2 or 3)
    current_question_index: int = 0     # Which question we're on
    question_assessments: list = field(default_factory=list) # Per-question results

@dataclass
class TechnicalVoiceInterviewState(InterviewState):
    selected_topics: list = field(default_factory=list)    # e.g. ['React', 'System Design']
    custom_topics: list = field(default_factory=list)
    active_topic_count: int = 1
    topic_assessments: list = field(default_factory=list)
```

**Generalized `get_next_stage()`**: Takes `active_stages: list` parameter (set from track config + runtime count). Skips inactive stages. Existing Intro track passes full `[WELCOME, SELF_INTRO, PAST_EXPERIENCE, COMPANY_FIT, CLOSING]`.

**Time limits for new stages**:
```python
BEHAVIORAL_STAGE_TIME_LIMITS = {
    BehavioralStage.GREETING: 30,
    BehavioralStage.SELF_INTRO: 120,
    BehavioralStage.BEHAVIORAL_Q1: 300,   # 5 min per question
    BehavioralStage.BEHAVIORAL_Q2: 300,
    BehavioralStage.BEHAVIORAL_Q3: 300,
    BehavioralStage.CLOSING: 45,
}

TECHNICAL_VOICE_STAGE_TIME_LIMITS = {
    TechnicalVoiceStage.GREETING: 30,
    TechnicalVoiceStage.SELF_INTRO: 120,
    TechnicalVoiceStage.EXPERIENCE_DISCUSSION: 180,
    TechnicalVoiceStage.TECHNICAL_CONCEPTS_1: 240,
    TechnicalVoiceStage.TECHNICAL_CONCEPTS_2: 240,
    TechnicalVoiceStage.TECHNICAL_CONCEPTS_3: 240,
    TechnicalVoiceStage.CLOSING: 45,
}
```

### Agent Worker (`agent_worker.py`)

**Track-aware session init**:
1. Read `track` attribute from participant metadata (default: `'intro'`)
2. Read track-specific attributes: `framework`, `depth`, `topics`, `custom_questions`
3. Call `get_track_config(track)` → `TrackConfig`
4. Instantiate correct state subclass
5. Set `active_stages` list based on config + runtime count (e.g. 2 questions → skip Q3)

**New tool: `generate_interview_questions`** (called once during GREETING):
- Separate LLM call (not in voice context) to generate questions
- Input: framework/topics + candidate resume + JD + role + depth
- Returns structured JSON: `{questions: [{main_question, competency, follow_up_probes}]}`
- Stores in `state.generated_questions`
- Sets `state.active_question_count` → determines which Q stages are active

**New tool: `get_current_question`** (called when entering a Q stage):
- Returns the question text for the current stage index from `state.generated_questions`
- Agent reads this and asks it as the main question for the stage

**Welcome audio playback**:
- `audio_cache.play_welcome_audio(track_type, session)`
- Reads pre-committed mp3 file → plays via `session.say()` (with audio bytes)
- Falls back to LLM TTS generation if file missing (logs WARNING)

**Skip intro handling** (existing `data_received` handler extended):
- Skip signal: `{"type": "skip_intro"}`
- Jumps to `track_config.first_real_stage`
- Records skipped stages in `state.skipped_stages`

**Fallback timer**: Generalized to work with any stage enum via `TrackConfig.time_limits`

### Prompts (`prompts.py`)

**New classes** (following existing pattern):

```python
class BEHAVIORAL_GREETING: ...
class BEHAVIORAL_SELF_INTRO: ...
class BEHAVIORAL_QUESTION_STAGE:   # Used for Q1/Q2/Q3
    conversation = """You are conducting behavioral question {question_index} of {total}.
    The question for this stage is: {question_text}
    Ask it naturally. Probe for STAR elements (Situation, Task, Action, Result).
    Follow-up depth: {depth_setting} (light=1 follow-up, medium=2, deep=3+).
    [DOCUMENT_CONTEXT]
    ...
    """
class BEHAVIORAL_CLOSING: ...
class TECHNICAL_VOICE_GREETING: ...
class TECHNICAL_VOICE_SELF_INTRO: ...
class TECHNICAL_VOICE_EXPERIENCE_DISCUSSION: ...
class TECHNICAL_VOICE_CONCEPTS_STAGE:   # Used for CONCEPTS_1/2/3
    conversation = """Assess {topic_name} concepts. Experience level: {level}.
    Ask conceptual questions: explain, compare, tradeoffs, when-to-use.
    [DOCUMENT_CONTEXT]
    """
class TECHNICAL_VOICE_CLOSING: ...
```

**Question generation prompt**:
```python
class QUESTION_GENERATION:
    behavioral_system = """Generate {count} behavioral interview questions for a {framework} framework interview.
    Role: {role}, Level: {level}.
    Resume context: {resume_snippet}
    JD context: {jd_snippet}
    Custom questions to include: {custom_questions}
    Return JSON: {"questions": [{"main_question": "...", "competency": "...", "follow_up_probes": ["...", "..."]}]}
    """
    technical_system = """Generate conceptual questions for topic: {topic}.
    Role: {role}, Level: {level}.
    Resume context: {resume_snippet}
    Return JSON: {"questions": ["...", "...", "..."]}
    """
```

**Feedback prompt revamp**:
```python
class TRACK_FEEDBACK:
    system = """Generate structured feedback as JSON with letter grades (A+ to F).
    Track type: {track_type}
    Return JSON matching this schema: { overall_grade, communication, structure,
    speech_analytics, track_specific: {...}, question_feedback: [...] }
    """
```

### Form (`templates/form.html`)

**Track selector**: Card-based selector at top of form (4 cards):
- Intro Call (default, green border)
- Behavioral Interview
- Technical Voice Interview
- Technical Coding (grayed out, "Coming Soon" badge)

**Conditional sections** (shown/hidden via JS on track change):

*Behavioral section*:
- Framework dropdown: Amazon / Google / Meta / Generic
- Depth: Light / Medium (default) / Deep (radio buttons)
- Custom questions textarea (optional)
- STAR method info modal trigger button

*Technical Voice section*:
- Topic checkboxes (populated via `/api/extract-topics` if resume exists, else role-based defaults)
- Custom topic input
- Auto-suggest button (calls backend to extract topics from resume)

*Coding section* (shown as disabled):
- Message: "Technical Coding rounds are coming soon."

**STAR modal**: Appears when Behavioral selected. Contains STAR explanation + example + tips. Dismissible.

**New form data passed to `/api/token`**:
```json
{
  "track": "behavioral",
  "framework": "amazon",
  "depth": "medium",
  "custom_questions": "...",
  "topics": ["React", "System Design"],
  "custom_topics": []
}
```

**New `/api/extract-topics` endpoint** (app.py):
- Input: `cache_key`, `role`
- Makes LLM call on resume text to extract technologies
- Returns: `{topics: ["React", "TypeScript", ...]}`

### Token / app.py Changes

New participant attributes added to LiveKit token:
```python
attrs.update({
    'track': form_data.get('track', 'intro'),
    'framework': form_data.get('framework', 'amazon'),
    'depth': form_data.get('depth', 'medium'),
    'custom_questions': form_data.get('custom_questions', ''),
    'topics': ','.join(form_data.get('topics', [])),
    'custom_topics': ','.join(form_data.get('custom_topics', [])),
})
```

Save interview with new fields:
```python
interview_data['track'] = state.track_type
interview_data['track_config'] = {
    'framework': ..., 'depth': ..., 'topics': ..., 'generated_questions': ...
}
```

### Interview Room (`templates/interview.html`)

**Skip Intro button**: Visible only during GREETING/SELF_INTRO stages. Sends `{"type": "skip_intro"}` via LiveKit data channel.

**Dynamic stage indicator**: JS reads `track` URL param, renders correct stage dots:
- intro: 5 dots (Welcome → Intro → Experience → Fit → Closing)
- behavioral: 4 dots (Welcome → Intro → Questions → Closing)
- technical_voice: 5 dots (Welcome → Intro → Experience → Concepts → Closing)

### Speech Analytics (`speech_analytics.py`)

```python
FILLER_WORDS = ['um', 'uh', 'like', 'you know', 'basically', 'actually', 'so', 'right']

def analyze_transcript(conversation: dict) -> dict:
    """Returns speech analytics from user messages only."""
    # Returns:
    # {
    #   filler_total: int,
    #   filler_breakdown: {word: count},
    #   avg_words_per_minute: float,
    #   total_speaking_duration_seconds: float,
    #   word_count: int,
    #   per_turn_pace: [{turn_index, wpm}],
    # }
```

Called in `app.py` feedback endpoints. Result stored in `interviews.metadata.speech_analytics`.

### Feedback Revamp

**New feedback JSON schema** (from LLM):
```json
{
  "overall_grade": "B+",
  "communication": {"grade": "A-", "explanation": "...", "tip": "..."},
  "structure": {"grade": "B", "explanation": "...", "tip": "..."},
  "speech_analytics_summary": {"filler_grade": "C+", "pace_grade": "B", "notes": "..."},
  "track_specific": {
    "behavioral": {
      "star_adherence": {"grade": "B+", "per_question": [...]},
      "leadership_coverage": {"covered": [...], "missed": [...]},
      "specificity": {"grade": "B", "explanation": "..."}
    }
  },
  "question_feedback": [
    {"question": "...", "strength": "...", "improvement": "...", "grade": "B"}
  ]
}
```

**`feedback.html` redesign**: Grade cards grid, per-category breakdown, expandable Q&A accordion, communication analytics section.

### Database Migration (`supabase-backend/patch1_migration.sql`)

```sql
-- Add track support to interviews table
ALTER TABLE interviews ADD COLUMN IF NOT EXISTS track VARCHAR DEFAULT 'intro';
ALTER TABLE interviews ADD COLUMN IF NOT EXISTS track_config JSONB DEFAULT '{}';
```

---

## Critical Files

| File | Change Type | What Changes |
|---|---|---|
| `fsm.py` | Modify | Add 3 new enums, 2 state subclasses, generalize get_next_stage() |
| `agent_worker.py` | Modify | Track-aware init, new tools, welcome audio, generalized fallback timer |
| `prompts.py` | Modify | Add all new stage instructions + generation prompts + feedback prompts |
| `app.py` | Modify | New form fields, `/api/extract-topics`, pass new attrs to token, speech analytics in feedback |
| `templates/form.html` | Modify | Track cards, conditional sections, STAR modal, topic checkboxes |
| `templates/interview.html` | Modify | Skip button, dynamic stage indicator |
| `templates/feedback.html` | Modify | Full redesign with grade cards + analytics |
| `supabase_client.py` | Modify | Pass `track` + `track_config` when saving |
| `tracks/` (new) | Create | 6 files — TrackConfig + per-track configs |
| `speech_analytics.py` (new) | Create | Filler detection, pace calc |
| `audio_cache.py` (new) | Create | Welcome audio playback |
| `static/audio/*.mp3` (new) | Create | 4 pre-generated welcome audio files |
| `supabase-backend/patch1_migration.sql` (new) | Create | DB migration |

---

## Ordered Task List (Patch 1)

### Step 1 — FSM Refactor (`fsm.py`)
- Add `BehavioralStage`, `TechnicalVoiceStage`, `CodingStage` enums
- Add `BehavioralInterviewState`, `TechnicalVoiceInterviewState` dataclasses
- Add `BEHAVIORAL_STAGE_TIME_LIMITS`, `TECHNICAL_VOICE_STAGE_TIME_LIMITS` dicts
- Generalize `get_next_stage()` to accept `active_stages` list
- Existing Intro track: zero changes to `InterviewStage` enum or methods
- **Verify**: Import the file, all enums instantiate correctly, `get_next_stage()` skips inactive stages

### Step 2 — Track Configuration System (`tracks/`)
- Create `tracks/base.py`: `TrackConfig` dataclass + `get_track_config()` factory
- Create `tracks/intro.py`: wraps existing behavior as TrackConfig
- Create `tracks/behavioral.py`: BehavioralStage config with time limits
- Create `tracks/technical_voice.py`: TechnicalVoiceStage config
- Create `tracks/technical_coding.py`: placeholder, no agent logic
- Create `tracks/__init__.py`: exports `get_track_config`
- **Verify**: `get_track_config('intro')` returns config matching existing behavior

### Step 3 — Database Migration (`supabase-backend/patch1_migration.sql`)
- Write SQL with `IF NOT EXISTS` guards
- Add comments explaining each change
- **No breaking changes** to existing columns
- **Verify**: SQL is valid and idempotent

### Step 4 — Form Page Updates (`templates/form.html`, `static/form.css` if needed)
- Add track selector cards above form fields
- Add conditional Behavioral section (framework, depth, custom questions)
- Add conditional Technical Voice section (topic checkboxes, custom topics)
- Add coding placeholder section
- Add STAR method modal (HTML + JS)
- Add JS: track change → show/hide correct section
- Add JS: topic auto-suggest (calls `/api/extract-topics` if resume cached)
- Follow existing CSS patterns (`.form-input`, `.btn-primary`, etc.)
- **Verify**: All 4 tracks selectable, conditional fields show/hide correctly, STAR modal dismissible

### Step 5 — Token / Metadata Updates (`app.py`)
- Accept new form fields in `/api/token` handler
- Add new participant attributes to token
- Add `/api/extract-topics` endpoint
- Save `track` + `track_config` fields in `save_interview` call flow
- **Verify**: Token attributes include `track`, `framework`, `depth`, `topics` as expected

### Step 6 — Audio Cache (`audio_cache.py` + `static/audio/`)
- Create `audio_cache.py` with `play_welcome_audio(track_type, session)` function
- Pre-generate 4 welcome audio files using OpenAI TTS (requires dev OpenAI key)
  - `welcome_intro.mp3`: "Welcome to your mock interview. I'm Alex, your AI interviewer..."
  - `welcome_behavioral.mp3`: "Welcome to your behavioral interview. I'll be asking questions about your past experiences..."
  - `welcome_technical_voice.mp3`: "Welcome to your technical interview. We'll explore your knowledge of the selected topics..."
  - `welcome_coding.mp3`: placeholder (not used in Patch 1)
- Files committed to `static/audio/`
- Fallback: if file missing, generate via TTS in-session (log WARNING)
- **Verify**: `audio_cache.py` loads mp3 bytes without error

### Step 7 — Agent Worker Refactoring (`agent_worker.py`)
- Read `track` + all track-specific attributes from participant metadata
- Instantiate correct state class via track type
- Load correct `TrackConfig`
- Set `active_stages` list (skip unused Q/concept stages)
- Add `generate_interview_questions` tool (separate LLM call)
- Add `get_current_question` tool (reads from `state.generated_questions`)
- Welcome audio playback at session start
- Skip intro: handle `{"type": "skip_intro"}` → jump to `track_config.first_real_stage`
- Generalize fallback timer to use `track_config.time_limits`
- Backwards compat: if `track == 'intro'`, behavior identical to current
- **Verify**: Intro track works unchanged; Behavioral track loads correct state

### Step 8 — Prompts Expansion (`prompts.py`)
- Add `BEHAVIORAL_GREETING`, `BEHAVIORAL_SELF_INTRO`, `BEHAVIORAL_QUESTION_STAGE`, `BEHAVIORAL_CLOSING` classes
- Add `TECHNICAL_VOICE_GREETING`, `TECHNICAL_VOICE_SELF_INTRO`, `TECHNICAL_VOICE_EXPERIENCE_DISCUSSION`, `TECHNICAL_VOICE_CONCEPTS_STAGE`, `TECHNICAL_VOICE_CLOSING` classes
- Add `QUESTION_GENERATION` class (behavioral + technical voice generation prompts)
- Add `TRACK_FEEDBACK` class (structured JSON feedback prompt per track)
- Update `build_stage_instructions()` to handle new stage types
- Update `get_transition_ack()` + `get_fallback_ack()` for new stages
- **Verify**: `build_stage_instructions(BehavioralStage.BEHAVIORAL_Q1, state)` returns non-empty string

### Step 9 — Skip Intro Mechanism (`interview.html` + `agent_worker.py`)
- Add "Skip Intro" button to `interview.html` (visible only during GREETING/SELF_INTRO)
- Button sends `{"type": "skip_intro"}` via LiveKit data channel
- Button disappears after those stages pass
- Agent handler (already partially exists) routes to `track_config.first_real_stage`
- Updates skipped_stages in state
- **Verify**: Button appears/disappears at correct stages; FSM skips correctly

### Step 10 — Dynamic Stage Indicator (`interview.html`)
- Read `track` from URL param
- JS constructs stage dots array based on track
- Existing stage update data channel event (`stage_change`) still updates active dot
- **Verify**: Correct dots shown for each track; active dot advances correctly

### Step 11 — Speech Analytics (`speech_analytics.py`)
- `analyze_transcript(conversation: dict) -> dict`
- Processes user messages only (not agent)
- Calculates: filler counts, total WPM, per-turn pace
- Unit-testable (pure function, no side effects)
- Called in `app.py` feedback generation endpoint
- Result passed to LLM as part of feedback prompt context
- **Verify**: Returns correct filler count for sample transcript

### Step 12 — Supabase Client Updates (`supabase_client.py`)
- Update `save_interview()` to include `track` + `track_config` columns
- Existing interviews (track=NULL) unaffected by DB default
- **Verify**: Save + retrieve roundtrip with track field

### Step 13 — Feedback System Revamp (`app.py` + `prompts.py` + `feedback.html`)
- `app.py`: In feedback generation endpoints, call `speech_analytics.analyze_transcript()`
- `app.py`: Pass analytics + track type to LLM prompt
- `prompts.py`: New `TRACK_FEEDBACK` prompt requests structured JSON with letter grades
- `feedback.html`: Redesign layout — overall grade (large), per-category grade cards, track-specific section, speech analytics section, expandable Q&A accordion
- Match existing CSS design system (no new frameworks, no emojis)
- **Verify**: Feedback page renders with grades for a behavioral interview

### Step 14 — Document Processor Verification (`document_processor.py`)
- Test PDF extraction with a sample resume
- Test DOCX extraction
- Fix any encoding or parsing errors found
- **Verify**: Both PDF and DOCX return meaningful extracted text

### Step 15 — Coding Track Placeholder
- Form: coding card grayed out with "Coming Soon" badge (already handled in Step 4)
- `CodingStage` enum exists (already added in Step 1)
- `tracks/technical_coding.py` returns placeholder config (Step 2)
- No agent logic wired to coding track
- **Verify**: Selecting coding track on form shows correct message; submitting form is disabled for coding track

### Step 16 — End-to-End Integration Verification
- Intro track: Start interview, complete all stages → verify unchanged behavior
- Behavioral track: Submit form (Amazon, Medium depth) → verify agent loads, generates questions, runs Q stages
- Technical Voice track: Submit form (2 topics) → verify agent loads, runs concept stages
- Feedback page: Verify new layout renders for both behavioral and technical voice interviews
- Skip intro: Verify button works for both new tracks
- DB: Verify `track` + `track_config` columns saved correctly

---

## Patch 2 (Document Now, Implement Later)

Patch 2 scope: Monaco editor, coding problem bank (LLM-generated), code evaluator, split-view layout, retry mechanism, per-question timer, `coding_submissions` DB table.

Not implementing in Patch 1. Placeholder only (disabled UI + CodingStage enum).

---

## New Dependencies

None required. All features use existing libraries (openai, livekit-agents, supabase-py, PyPDF2, python-docx).

Audio generation for welcome files requires a one-time dev script (not a runtime dependency).

---

## Verification

End-to-end test scenarios to run after implementation:

1. **Intro track regression**: Submit form with no track selected → interview behaves exactly as before
2. **Behavioral track**: Select Behavioral + Amazon + Medium → interview runs GREETING → SELF_INTRO → Q1 → Q2 → (Q3 if deep) → CLOSING
3. **Skip intro**: Click "Skip Intro" during GREETING → FSM jumps to BEHAVIORAL_Q1 (or TECHNICAL_CONCEPTS_1)
4. **Technical Voice**: Select 2 topics → interview runs GREETING → SELF_INTRO → EXPERIENCE → CONCEPTS_1 → CONCEPTS_2 → CLOSING
5. **Feedback**: Generate feedback for behavioral interview → page shows grade cards, STAR section, speech analytics
6. **Coding placeholder**: Coding card shown as disabled on form; selecting it shows "Coming Soon" message
7. **DB migration**: Run SQL on dev Supabase → `track` + `track_config` columns exist with defaults; existing rows unaffected
