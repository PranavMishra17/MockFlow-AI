# MockFlow-AI Agent Design

## Overview

MockFlow-AI is a voice-driven interview agent built on LiveKit, implementing a **Finite State Machine (FSM)** to orchestrate structured interview conversations. The agent conducts multi-stage interviews with explicit state transitions, time-based fallbacks, and quality-driven progression.

---

## Core Architecture

### System Components

1. **Web Server** ([app.py](app.py))
   - Flask-based web interface
   - Candidate registration and metadata collection (name, email, role, experience level)
   - LiveKit token generation with participant attributes
   - Room name generation: `interview-{name}-{timestamp}`

2. **Interview Agent** ([agent.py](agent.py))
   - LiveKit Agents SDK integration
   - Voice interaction pipeline: Deepgram STT → GPT-4o-mini LLM → OpenAI TTS
   - FSM-driven stage management with explicit tool-based transitions
   - Real-time caption emission and UI synchronization
   - Conversation history logging to JSON files

3. **State Machine** ([fsm.py](fsm.py))
   - Enum-based stage definitions (GREETING → SELF_INTRO → PAST_EXPERIENCE → CLOSING)
   - Time tracking and progress calculation per stage
   - Question counting and minimum requirement enforcement
   - Transition acknowledgement queue mechanism

---

## Agent Flow & State Management

### Interview Stages

```
GREETING (60s, 1 min question)
    ↓ (Agent calls transition_stage tool)
SELF_INTRO (120s, 2 min questions)
    ↓ (Agent evaluates progress and calls transition_stage)
PAST_EXPERIENCE (240s, 5 min questions)
    ↓ (Agent or timeout forces transition)
CLOSING (45s, graceful goodbye)
    ↓ (Auto-disconnect after closing message)
```

**Key Design Principle**: Stage transitions are **explicit and tool-driven**—the LLM must call `transition_stage()` to progress. This prevents uncontrolled stage drift and ensures FSM integrity.

---

## Agent Tools (Function Calling)

The agent has 4 primary tools that enforce interview structure:

### 1. `transition_stage(reason: str)`
**Purpose**: Explicit stage progression with guardrails.

**Logic**:
- Checks minimum time gates (e.g., 30s for SELF_INTRO, 45s for PAST_EXPERIENCE)
- Executes FSM transition: `state.transition_to(next_stage)`
- Updates agent instructions with personalized, role-specific prompts
- Queues transition acknowledgements for graceful handoff
- Emits stage change events to frontend UI

**Acknowledgement Strategy**:
- For SELF_INTRO/PAST_EXPERIENCE: Queue acknowledgement → inject via `ask_question` tool
- For CLOSING: Return instruction to speak closing message immediately

### 2. `ask_question(question: str)`
**Purpose**: Validate questions before asking to prevent repetition.

**Logic**:
- Normalizes question text (lowercase, strip punctuation)
- Compares against `questions_asked` list using exact and substring matching
- Tracks per-stage question counts
- **Returns progress guidance** with time remaining % and question status
- **Delivers queued transition acknowledgements** when agent asks first question in new stage

**Example Response**:
```
STAGE TRANSITION - You MUST first say this to acknowledge the new stage:
"Excellent introduction, thank you John! Now let's shift gears and discuss your past work experience..."
Then ask your question.

Question approved (1/5 questions). Time remaining: 85% (204s).
Need 4 more question(s) to meet minimum. Now ask: 'Can you walk me through a project you're proud of?'
```

### 3. `assess_response(depth_score: int, key_points_covered: list[str])`
**Purpose**: Evaluate candidate response quality and guide next action.

**Logic**:
- Scores response depth (1=vague, 5=comprehensive)
- Stores key points for conversation history
- Calculates transition urgency based on:
  - Time remaining % (critical at 10%, high at 25%)
  - Minimum questions met
  - Response quality (depth ≥3 suggests readiness)
- **Returns actionable guidance**: follow-up, transition, or continue

**Recent Change**: Fixed multi-assessment bug—agent must wait for full user response before calling `assess_response`. No partial assessments mid-turn.

### 4. `record_response(response_summary: str)` *(Deprecated in favor of assess_response)*
**Purpose**: Store key points from candidate responses for final analysis.

---

## Minimum-Question Flow (Recent Enhancement)

**Previous Design**: Max question caps (3 for SELF_INTRO, 8 for PAST_EXPERIENCE).

**Current Design**: **Minimum-only** question requirements with quality-driven transitions.

### Rationale
- Max caps were arbitrary and cut off productive conversations
- Minimum requirements ensure baseline coverage
- Agent transitions when: `min_questions_met AND (time_low OR depth_sufficient)`

### Per-Stage Minimums
- GREETING: 1 (auto-transition after greeting)
- SELF_INTRO: 2 questions
- PAST_EXPERIENCE: 5 questions
- CLOSING: 1 (graceful goodbye)

**Transition Logic**:
```
IF questions >= minimum:
    IF time_remaining_pct <= 25% OR depth_score >= 4:
        → SUGGEST TRANSITION
    ELSE:
        → CONTINUE (agent's discretion)
ELSE:
    → CONTINUE (must meet minimum)
```

---

## Fallback Timer (Safety Net)

**Purpose**: Prevent interview from getting stuck if agent fails to transition.

**Implementation** (Lines 930-1160 in [agent.py](agent.py)):
- Background async task monitoring SELF_INTRO, PAST_EXPERIENCE, CLOSING stages
- Logs progress milestones: 50%, 75%, 90%, 100% of time limit
- **Forces transition** when stage exceeds time limit:
  - Calls `state.transition_to(next_stage, forced=True)`
  - Updates agent instructions
  - Queues acknowledgement
  - Attempts `session.say()` as backup (may be interrupted if user is speaking)

**CLOSING Stage Safety**:
- 60s timeout forces disconnect if closing message not delivered
- Uses content-based detection (checks for "thank you", "good luck", "best of luck", etc.)
- Waits 5s for TTS to finish, then finalizes interview

---

## Transition Acknowledgement Mechanism

**Challenge**: When transition happens mid-user-speech or during fallback, agent must acknowledge stage change gracefully.

**Solution** (Lines 249-295, 351-428 in [agent.py](agent.py)):

1. **Queue Acknowledgement**:
   ```python
   ctx.userdata.pending_acknowledgement = "Excellent introduction! Now let's discuss your experience..."
   ctx.userdata.pending_ack_stage = "past_experience"
   ctx.userdata.transition_acknowledged = False
   ```

2. **Inject via Tool Response**:
   - When agent calls `ask_question` or `assess_response` in new stage, tool response **prepends** acknowledgement
   - Example: `"STAGE TRANSITION - You MUST first say: 'Great intro!' Then ask your question."`

3. **Clear After Delivery**:
   - Set `transition_acknowledged = True` when agent asks question in new stage
   - Prevents redundant acknowledgements

**Edge Case Handling**:
- CLOSING stage: Return explicit instruction to speak closing message (no tool call expected)
- Fallback timer: Queue acknowledgement + attempt `session.say()` as backup

---

## Role-Specific Interview Adaptation

**Dynamic Instruction Injection** (Lines 544-583 in [agent.py](agent.py)):

Each stage's base instructions are **personalized** with:
- Candidate name (used naturally in conversation)
- Job role being applied for (injected via `[ROLE]` placeholder)
- Experience level (entry/junior/mid/senior/lead/staff)
- Role-specific focus areas (e.g., "system design decisions" for engineers, "team leadership" for managers)

**Example**:
```
For this Software Engineer role (mid level):
- Key focus areas: technical architecture, development process, code quality practices
- Focus on independent project ownership, technical decisions, collaboration.
- Tailor questions to probe relevant experience for this role and level.
```

**Role Keywords** (Lines 549-559):
- engineer → technical skills, problem-solving, system design
- manager → team leadership, project planning, stakeholder communication
- product → product strategy, user research, roadmap prioritization
- devops → infrastructure, CI/CD pipelines, monitoring

---

## Conversation History & Logging

**Captured Data**:
- User transcripts (from Deepgram STT)
- Agent responses (text content from LLM)
- Timestamps per message
- Stage context for each agent message
- Total message counts

**Storage** (Lines 830-878 in [agent.py](agent.py)):
```json
{
  "candidate": "John Doe",
  "interview_date": "2025-12-13T10:30:00",
  "room_name": "interview-john-doe-1734096600",
  "conversation": {
    "agent": [{"index": 0, "text": "Hi John! Welcome...", "timestamp": 1234567890, "stage": "greeting"}],
    "user": [{"index": 0, "text": "Thanks! I'm John...", "timestamp": 1234567891}]
  },
  "total_messages": {"agent": 15, "user": 14}
}
```

Saved to: `interviews/{name}_{timestamp}.json`

---

## Current Architecture Limitations (Single-Worker)

### Worker Model
**Current**: One shared agent worker ([agent.py](agent.py)) connects to LiveKit and handles **all rooms** via the `@server.rtc_session()` decorator.

**How it Works**:
- LiveKit dispatches a new `entrypoint()` coroutine per room connection
- Each session gets isolated state: `InterviewState` instance
- Worker process is **multi-session** via async concurrency

**Limitations**:
1. **Resource Contention**: Heavy load (100+ concurrent interviews) risks CPU/memory bottlenecks
2. **No Isolation**: A crash in one session's code could affect others (though async tasks are isolated)
3. **Scaling**: Horizontal scaling requires manual worker pool management

---

## Production-Ready Architecture (Recommendation)

### Per-Session Worker with BYOK (Bring Your Own Keys)

**Design**:
```
[Web Server] → [LiveKit SFU] → [Worker Pool]
    ↓ Token + Metadata         ↓ Dispatch Room
[Frontend UI]                  [Per-Session Agent Worker]
    ↓ API Keys (BYOK)              ↓ Uses Client Keys
                                [OpenAI API] [Deepgram API]
```

**Components**:

1. **Frontend Key Injection**:
   - User provides OpenAI + Deepgram API keys in UI (stored in session/local storage, never logged)
   - Keys passed as participant attributes or room metadata

2. **Worker Dispatch**:
   - LiveKit Cloud's agent dispatch or custom Kubernetes deployment
   - One ephemeral worker per room (auto-scales)
   - Worker reads keys from `participant.attributes` or room metadata

3. **Benefits**:
   - **Cost Isolation**: Each user's API usage billed to their keys
   - **Resource Isolation**: Worker crash only affects one session
   - **Elastic Scaling**: Auto-scale worker pods based on active rooms
   - **Privacy**: API keys never touch server logs

4. **Implementation**:
   - Modify [agent.py](agent.py) lines 703-720 to read keys from `ctx.room.remote_participants[0].attributes`
   - Use Kubernetes HPA (Horizontal Pod Autoscaler) to scale worker replicas
   - Set pod resource limits (e.g., 2 CPU cores, 4GB RAM per worker)

**Security Considerations**:
- Validate API keys before initializing STT/LLM/TTS
- Use short-lived workers (terminate after interview ends)
- Encrypt keys in transit (HTTPS/WSS enforced)

---

## Future Enhancements

### 1. Easy Plugin of More States (Role-Driven or Custom)

**Current**: Hardcoded 4 stages in `InterviewStage` enum.

**Enhancement**:
- Define stages via YAML/JSON config:
  ```yaml
  stages:
    - name: technical_skills
      min_questions: 3
      time_limit: 180
      instructions_template: "Ask about {role}-specific technical skills..."
      prerequisites: [self_intro]
  ```
- Load config at agent startup
- Generate FSM transitions dynamically
- Allow custom stage injection via frontend (admin UI)

**Use Cases**:
- Role-specific stages (e.g., SYSTEM_DESIGN for senior engineers, BEHAVIORAL for managers)
- Multi-round interviews (PHONE_SCREEN → TECHNICAL → BEHAVIORAL → CULTURE_FIT)

---

### 2. Document Analysis (Resume/Portfolio Tailoring)

**Goal**: Parse uploaded resume/portfolio to tailor questions.

**Approach**:
- Extract text from PDF/DOCX using `pypdf` or `python-docx`
- Store in `InterviewState.uploaded_resume_text` (lines 74-75 in [fsm.py](fsm.py))
- Inject resume summary into agent instructions:
  ```
  RESUME HIGHLIGHTS:
  - 5 years experience with React, Node.js
  - Led team of 4 engineers at TechCorp
  - Built real-time analytics dashboard (mentioned scaling to 10k concurrent users)

  INSTRUCTIONS: Ask follow-up questions about these specific experiences.
  ```

**Implementation Notes**:
- Add `/api/upload-resume` endpoint in [app.py](app.py)
- Store parsed text in LiveKit participant attributes or Redis cache (keyed by room name)
- Agent retrieves via `ctx.room.remote_participants[0].attributes['resume_text']`

**Privacy**: Ensure resume text is deleted after interview ends.

---

### 3. JD Analysis & Company Research (Web Search)

**Goal**: Understand job requirements and company context to ask relevant questions.

**Workflow**:
1. **JD Analysis**:
   - User pastes job description in registration form
   - Extract key requirements using LLM:
     ```
     Required: 3+ years Python, experience with microservices, AWS
     Preferred: Kubernetes, CI/CD pipelines
     ```
   - Store in `InterviewState.job_description` (line 75 in [fsm.py](fsm.py))

2. **Company Research** (Web Search):
   - Use SerpAPI or Tavily to fetch company info:
     - Recent news (funding rounds, product launches)
     - Tech stack (from job postings, engineering blogs)
     - Culture mentions (Glassdoor, LinkedIn)
   - Inject into agent context:
     ```
     COMPANY CONTEXT (TechCorp):
     - Series B startup, 50 employees
     - Tech stack: Python, React, Postgres, AWS
     - Recent launch: AI-powered analytics product

     INSTRUCTIONS: Connect candidate's experience to company's tech stack and product.
     ```

**Implementation**:
- Add `analyze_jd(jd_text)` helper function in [agent.py](agent.py)
- Call web search API in [app.py](app.py) token generation endpoint
- Cache results in participant attributes or Redis (TTL: 1 hour)

---

### 4. ACTUAL Feedback (Chat History Analysis)

**Goal**: Generate actionable feedback for candidates post-interview.

**What to Analyze**:
- **Response Quality**: Depth scores from `assess_response` calls
- **STAR Method Usage**: Did candidate structure answers (Situation, Task, Action, Result)?
- **Technical Depth**: Use of specific technologies, metrics, problem-solving clarity
- **Communication**: Clarity, conciseness, active listening (pauses before responding)

**Feedback Categories**:

1. **Strengths**:
   - "You provided detailed STAR-structured responses for 4 out of 5 experience questions."
   - "Strong technical depth when discussing microservices architecture and scaling challenges."

2. **Areas for Improvement**:
   - "Your responses to behavioral questions lacked specific metrics. Try quantifying impact (e.g., 'reduced latency by 40%')."
   - "Consider pausing briefly before answering to organize thoughts—this shows thoughtfulness."

3. **Question-Specific Pointers**:
   - Q: "Tell me about a challenging bug you fixed."
   - Feedback: "You described the bug well, but didn't mention the debugging process or tools used. Interviewers want to understand your problem-solving approach."

**Implementation**:
- Add `/api/feedback` endpoint in [app.py](app.py)
- Load conversation JSON, pass to GPT-4o with prompt:
  ```
  Analyze this interview transcript and provide feedback in 3 sections:
  1. Strengths (2-3 bullet points)
  2. Areas for Improvement (2-3 actionable tips)
  3. Question-Specific Feedback (for 2-3 key questions)

  Be constructive and specific. Focus on interview technique, not correctness of answers.
  ```
- Return formatted feedback as JSON:
  ```json
  {
    "strengths": ["..."],
    "improvements": ["..."],
    "question_feedback": [
      {"question": "...", "feedback": "..."}
    ]
  }
  ```

**Delivery**:
- Email to candidate (using email from registration)
- Downloadable PDF report
- In-app feedback page (requires candidate login)

---

## Key Design Choices Summary

| Decision | Rationale | Trade-offs |
|----------|-----------|------------|
| **FSM-driven stages** | Prevents unstructured rambling; enforces interview flow | Less flexible than pure LLM-driven conversation |
| **Explicit tool-based transitions** | Agent must call `transition_stage()`—no implicit stage drift | LLM must learn tool usage; requires clear instructions |
| **Minimum-only question requirements** | Allows quality-driven transitions; no arbitrary caps | Agent must evaluate depth correctly |
| **Fallback timer** | Safety net for stuck interviews | Hard time limits may cut off valuable discussions |
| **Queued acknowledgements** | Graceful stage transitions mid-user-speech | Complex state tracking (3 flags: pending, stage, acknowledged) |
| **Role-specific instructions** | Tailored questions improve relevance | Requires maintaining role keyword mappings |
| **Single-worker model (current)** | Simple deployment; async concurrency handles multiple sessions | Limited scalability; no cost/resource isolation |
| **BYOK model (recommended)** | User pays for their API usage; elastic scaling | Complex key management; requires secure key handling |

---

## File References

- **Agent Logic**: [agent.py](agent.py) (1164 lines)
  - `InterviewAgent` class (lines 159-595)
  - Tool implementations: `transition_stage`, `ask_question`, `assess_response`
  - Fallback timer: `stage_fallback_timer` (lines 930-1160)

- **State Machine**: [fsm.py](fsm.py) (319 lines)
  - `InterviewStage` enum (lines 17-22)
  - `InterviewState` dataclass (lines 42-319)
  - Time/question status helpers (lines 215-251)

- **Web Server**: [app.py](app.py) (215 lines)
  - Token generation: `/api/token` (lines 100-178)
  - Routes: `/`, `/start`, `/interview`

---

## Conclusion

MockFlow-AI implements a **structured, FSM-driven interview agent** that balances LLM flexibility with explicit stage control. The minimum-question flow with quality-driven transitions ensures productive conversations without arbitrary caps. The current single-worker architecture suits demos and small-scale deployments, but production systems should adopt **per-session workers with BYOK** for scalability and cost isolation.

Future enhancements (pluggable stages, document analysis, company research, detailed feedback) will transform this from a basic interview simulator into a **comprehensive interview preparation platform** that provides real value to candidates.

---

**Document Version**: 1.0
**Last Updated**: 2025-12-13
**Maintainer**: MockFlow-AI Team
