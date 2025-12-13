# Agent Interaction Algorithm & FSM Architecture

## Overview

MockFlow-AI uses a **Finite State Machine (FSM)** with explicit state transitions, quality assessment tools, and fallback mechanisms to conduct structured voice interviews. The system balances natural conversation flow with robust safeguards to prevent loops and ensure progress.

---

## FSM Structure

### States (Interview Stages)

```
GREETING → SELF_INTRO → PAST_EXPERIENCE → CLOSING → END
```

**State Definitions:**
- **GREETING**: Agent introduces interview format, immediately transitions
- **SELF_INTRO**: Candidate introduces themselves (75 seconds max)
- **PAST_EXPERIENCE**: Deep dive into one specific project (180 seconds max)
- **CLOSING**: Thank you and positive feedback (35 seconds max)

### State Transitions

**Transition Triggers (Priority Order):**

1. **Tool-Based (Primary)**: Agent calls `transition_stage()` function tool
   - LLM decides when candidate has provided sufficient information
   - Quality gates enforced via `assess_response` tool

2. **Question Limit (Hard Stop)**:
   - SELF_INTRO: 3 questions max
   - PAST_EXPERIENCE: 5 questions max
   - `ask_question` tool rejects attempts beyond limit
   - Forces agent to call `transition_stage`

3. **Time-Based Fallback (Safety Net)**:
   - GREETING: 60 seconds
   - SELF_INTRO: 75 seconds
   - PAST_EXPERIENCE: 180 seconds
   - CLOSING: 35 seconds
   - **⚠️ CURRENT ISSUE**: Timer counts from stage start, NOT from last user activity

---

## Agent Decision Flow

### Question-Response Cycle

```
1. Agent Planning
   ↓
2. Agent calls ask_question(question)
   ↓
3. Tool validates:
   - Check: Already asked this question? → REJECT
   - Check: Stage question limit reached? → REJECT + Force transition
   - Check: Unique question? → APPROVE + Track
   ↓
4. Agent asks question to candidate
   ↓
5. Candidate responds (speech-to-text)
   ↓
6. Agent calls assess_response(depth_score, key_points)
   ↓
7. Tool evaluates response quality:
   - depth_score: 1 (vague) → 5 (comprehensive)
   - Returns guidance: "Ask follow-up" OR "Transition ready"
   ↓
8. Agent decides next action based on guidance
   ↓
   LOOP back to step 1 OR call transition_stage()
```

### Quality Gates

**SELF_INTRO Stage:**
- **Target**: depth_score >= 3 (adequate)
- **Depth 1-2**: Ask follow-ups about background/skills/goals
- **Depth 3+**: Ask ONE brief clarifying question, then transition

**PAST_EXPERIENCE Stage:**
- **Target**: depth_score >= 4 (detailed)
- **Depth 1**: Probe with STAR method (Situation, Task, Action, Result)
- **Depth 2**: Ask about role, challenges, or technical decisions
- **Depth 3**: Ask about specific implementation details
- **Depth 4+**: Ask final question about impact/results, then transition

---

## Safeguard Mechanisms

### 1. Question Tracking (Prevents Repetition)

**Implementation**: `ask_question` function tool

```python
STAGE_QUESTION_LIMITS = {
    'self_intro': 3,
    'past_experience': 5,
}

# Per-stage counter tracks questions asked
if stage_questions >= limit:
    return "Question limit reached. MUST transition now."

# Global deduplication prevents similar questions
for asked in questions_asked:
    if normalized_question == normalized_asked:
        return "Already asked this question. Ask different."
```

**Purpose**:
- Prevents infinite questioning loops
- Enforces interview pacing
- Blocks repetitive/similar questions

### 2. Response Quality Assessment

**Implementation**: `assess_response` function tool

```python
# Agent evaluates after EVERY candidate response
assess_response(
    depth_score=3,  # 1-5 scale
    key_points_covered=["EC2 instances", "latency issues", "model serving"]
)

# Returns adaptive guidance
if depth_score >= 3:
    return "Adequate. Ask brief follow-up, then transition."
else:
    return "Too vague. Ask detailed follow-up. Do NOT transition."
```

**Purpose**:
- Ensures adequate context gathering
- Prevents premature transitions
- Adapts follow-up strategy to response quality

### 3. Time-Based Fallback Timer ⚠️

**Current Implementation**: `stage_fallback_timer()` (Lines 605-705 in agent.py)

```python
STAGE_LIMITS = {
    InterviewStage.GREETING: 60,
    InterviewStage.SELF_INTRO: 75,
    InterviewStage.PAST_EXPERIENCE: 180,
    InterviewStage.CLOSING: 35,
}

# Runs every 20 seconds
while True:
    await asyncio.sleep(20)

    current_stage = state.verify_state()
    time_in_stage = state.time_in_current_stage()  # ⚠️ From stage START

    if time_in_stage > STAGE_LIMITS[current_stage]:
        # Force transition
        state.transition_to(next_stage, forced=True)
```

**Current Behavior**:
- Timer starts when stage begins
- Counts continuously regardless of user activity
- Forces transition even if user is mid-sentence

### ⚠️ CRITICAL ISSUE: Premature Transitions

**Problem**: Timer does not distinguish between:
- User actively speaking (should NOT count towards timeout)
- User silent/inactive (should count towards timeout)

**Example from Logs** (18:48 - 18:49):
```
18:48:49: Stage past_experience started
18:49:00: [71.2s elapsed] Transition to closing (timer triggered)
18:49:00-18:49:16: User STILL SPEAKING about project details
18:49:17: Interview forcibly disconnected
```

**Impact**:
- Interview ended while user was providing valuable information
- Agent interrupted active conversation
- Poor user experience

---

## PROPOSED FIX: Activity-Based Timeout

### Concept: Inactivity Timer (Not Stage Timer)

**Change Timer Logic From:**
```
Time since stage started > limit → Transition
```

**To:**
```
Time since last user speech > inactivity_limit → Transition
```

### Implementation Strategy

**Option 1: Inactivity-Only Timer**
```python
INACTIVITY_LIMITS = {
    InterviewStage.SELF_INTRO: 30,  # 30s of silence
    InterviewStage.PAST_EXPERIENCE: 45,  # 45s of silence
}

# Update last_activity_timestamp on every user speech
def on_user_speech(event):
    state.last_activity_timestamp = time.time()

# Check inactivity duration
time_since_activity = time.time() - state.last_activity_timestamp
if time_since_activity > INACTIVITY_LIMITS[current_stage]:
    # Force transition after prolonged silence
    state.transition_to(next_stage, forced=True)
```

**Option 2: Hybrid Timer (Max Stage Time + Inactivity)**
```python
STAGE_LIMITS = {
    InterviewStage.SELF_INTRO: 180,  # 3 min absolute max
    InterviewStage.PAST_EXPERIENCE: 300,  # 5 min absolute max
}

INACTIVITY_LIMITS = {
    InterviewStage.SELF_INTRO: 30,  # 30s silence
    InterviewStage.PAST_EXPERIENCE: 45,  # 45s silence
}

# Check both conditions
time_in_stage = state.time_in_current_stage()
time_since_activity = time.time() - state.last_activity_timestamp

if time_since_activity > INACTIVITY_LIMITS[stage]:
    # User has been silent too long
    force_transition(reason="User inactive")
elif time_in_stage > STAGE_LIMITS[stage]:
    # Stage running too long regardless of activity
    force_transition(reason="Maximum stage time exceeded")
```

**Option 3: Activity Extends Deadline**
```python
# Each user response extends the deadline
def on_user_speech(event):
    # Give extra time when user speaks
    state.stage_deadline = time.time() + EXTENSION_TIME[stage]

# Check if past deadline
if time.time() > state.stage_deadline:
    force_transition(reason="Stage deadline reached")
```

### Recommended: Option 2 (Hybrid)

**Rationale**:
- **Inactivity timer**: Handles stuck/abandoned interviews gracefully
- **Max stage time**: Prevents interviews from running indefinitely if user is overly verbose
- **Balanced approach**: Natural for active users, safe fallback for edge cases

**Proposed Limits**:
```python
STAGE_LIMITS = {
    InterviewStage.GREETING: 90,        # 90s max (should be quick)
    InterviewStage.SELF_INTRO: 180,     # 3 min max
    InterviewStage.PAST_EXPERIENCE: 300, # 5 min max
    InterviewStage.CLOSING: 60,         # 60s max
}

INACTIVITY_LIMITS = {
    InterviewStage.GREETING: 20,        # 20s silence
    InterviewStage.SELF_INTRO: 30,      # 30s silence
    InterviewStage.PAST_EXPERIENCE: 45, # 45s silence
    InterviewStage.CLOSING: 15,         # 15s silence
}
```
---

## CAUTION
MISSING FEATURE

"It would be better if the agent acknowledges state change, like: lets now move on to discuss your past exp" - or

"I guess now is the time to close -o ut our interview"

---

## State Tracking

### InterviewState Fields (fsm.py)

```python
@dataclass
class InterviewState:
    # Current state
    stage: InterviewStage
    stage_started_at: datetime  # ⚠️ Used for current timer

    # ✅ NEEDED: Activity tracking
    last_activity_timestamp: float  # Time of last user speech
    last_user_speech_timestamp: float  # For inactivity detection

    # Question tracking
    questions_asked: list[str]  # All questions globally
    questions_per_stage: dict[str, int]  # Per-stage counters

    # Response tracking
    experience_responses: list[str]  # Quality assessments

    # Transition tracking
    transition_count: int
    forced_transitions: int
```

### Key Timestamps

**Current**:
- `stage_started_at`: When stage began (used for timeout)

**Needed**:
- `last_user_speech_at`: Timestamp of most recent user speech event
- `last_activity_at`: Timestamp of any activity (speech or agent interaction)

---

## Role-Specific Context Injection

**Mechanism**: Form data (role, experience level) passed via LiveKit token attributes

```python
# Form submission → Token attributes
token.with_attributes({
    'role': 'Software Engineer',
    'level': 'mid',
    'email': 'candidate@example.com'
})

# Agent extracts attributes on session start
interview_state.job_role = role  # "Software Engineer"
interview_state.experience_level = level  # "mid"

# Injected into stage instructions
role_context = f"""
For this Software Engineer role (mid level):
- Focus areas: technical architecture, development process, code quality
- Focus on independent project ownership, technical decisions, collaboration
- Tailor questions to probe relevant experience for this role and level
"""
```

**Effect**: Agent asks role-appropriate questions with level-appropriate depth expectations.

---

## Summary: Decision Hierarchy

**Priority Order for Stage Transitions**:

1. **✅ Agent Decision (Tool-Based)**: Agent calls `transition_stage` after assessing quality
2. **✅ Question Limit Enforcement**: `ask_question` rejects and forces transition at limit
3. **⚠️ Time-Based Fallback**: Currently counts from stage start (**BROKEN**)
4. **❌ NOT IMPLEMENTED**: Inactivity detection (user silence timeout)

**Required Fix**:
- Add `last_user_speech_timestamp` to state
- Change fallback timer to check **inactivity duration**, not **stage duration**
- Optionally add absolute max stage time as secondary safeguard

---

## File References

**Core FSM**: [fsm.py](e:\MockFlow-AI\fsm.py)
- `InterviewState` dataclass (lines 25-161)
- State transition logic

**Agent Logic**: [agent.py](e:\MockFlow-AI\agent.py)
- Stage instructions (lines 68-147)
- `ask_question` tool (lines 280-348)
- `assess_response` tool (lines 350-433)
- `transition_stage` tool (lines 174-242)
- `stage_fallback_timer` ⚠️ (lines 605-705)

**Form Data Flow**: [app.py](e:\MockFlow-AI\app.py)
- Token generation with attributes (lines 136-154)

---

## Metrics Tracked

- Questions asked per stage
- Response quality scores (depth 1-5)
- Stage durations
- Forced vs. natural transitions
- Total conversation turns (agent vs. user)

All data saved to `interviews/{candidate}_{timestamp}.json` on completion.
