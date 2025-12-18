# MockFlow-AI Implementation Summary

## New Features Implemented

### 1. Updated Interview Stage Flow
```
WELCOME (60s) -> SELF_INTRO (120s) -> PAST_EXPERIENCE (240s) -> COMPANY_FIT (240s) -> CLOSING (45s)
```

The WELCOME stage now properly speaks a greeting before transitioning to SELF_INTRO. The agent is instructed to speak the full greeting out loud before calling `transition_stage`.

### 2. Document Extraction & Storage
- **Privacy-first**: Only extracted text is stored, never raw files
- Supports: PDF (PyPDF2), DOCX (python-docx), MD, TXT
- Cache uses MD5 hash keys for deduplication

### 3. Skip Stage Feature
- Candidates can skip ahead to any future stage via UI buttons
- Skip requests are queued and processed gracefully by the agent
- Skipped stages are tracked in interview history

### 4. Post-Interview Re-sequencing (Enhanced)
- **Smart merging**: Groups ALL user messages between agent turns as one response
- Uses 5-second gap threshold for natural speech pauses
- `merge_by_agent_turns()` function produces cleaner conversation flow
- Interleaves agent/candidate turns by timestamp

### 5. AI-Powered Feedback Generation
- Chain-of-thought analysis using GPT-4o-mini
- Uses prompts from `POSTINTERVIEWFEEDBACK` class in `prompts.py`
- Analyzes candidate profile, job requirements, and conversation flow
- Generates structured feedback with strengths, improvements, and practice plan

### 6. Enhanced Feedback UI
- **Scrollable feedback content** (max-height: 70vh)
- **Animated loading phases** with 5 rotating messages:
  - "Gathering candidate profile..."
  - "Reviewing job requirements..."
  - "Processing conversation flow..."
  - "Evaluating response quality..."
  - "Synthesizing insights..."
- Phase indicator dots with completion states
- Error handling with retry and "View All Interviews" options

### 7. Get Feedback Button (Interview End Modal)
- Prominent golden button with shimmer animation and pulsing glow
- Appears in modal after interview ends (natural or user-initiated)
- Links directly to feedback page with auto-generate enabled

### 8. Improved Past-Calls Page
- **Job role tag** (purple) - shows position applied for
- **Experience level tag** (green) - entry/junior/mid/senior/lead/staff
- **"Ended Early" tag** (amber) - for user-disconnected interviews
- **Stages covered pills** - shows which interview stages were completed
- **Resume indicator** - when resume was attached to interview

### 9. Transcript Saving on Manual End
- Transcripts now save when user clicks "End Interview"
- Agent emits actual filename to frontend for accurate navigation
- Includes additional metadata: job_role, experience_level, final_stage, ended_by

---

## New API Endpoints

### Document Upload
```bash
# Upload resume/portfolio
curl -X POST \
  -F "file=@resume.pdf" \
  -F "document_type=resume" \
  -F "include_profile=true" \
  http://localhost:5000/api/upload-resume

# Response
{
  "success": true,
  "cache_key": "abc123...",
  "text_preview": "John Doe - Software Engineer...",
  "char_count": 2500,
  "document_type": "resume"
}
```

### List Interviews (Enhanced)
```bash
curl http://localhost:5000/api/interviews

# Response
{
  "success": true,
  "interviews": [
    {
      "filename": "john_doe_20241215_143000.json",
      "candidate": "John Doe",
      "interview_date": "2024-12-15T14:30:00",
      "job_role": "Software Engineer",
      "experience_level": "mid",
      "final_stage": "closing",
      "ended_by": "natural_completion",
      "stages_covered": ["welcome", "self_intro", "past_experience", "company_fit", "closing"],
      "message_count": {"agent": 15, "user": 12},
      "file_size": 8542,
      "has_resume": true,
      "has_jd": false
    }
  ],
  "count": 1
}
```

### Get Re-sequenced Interview
```bash
curl http://localhost:5000/api/interview/john_doe_20241215_143000.json

# Response
{
  "success": true,
  "ordered_conversation": [
    {"role": "agent", "text": "Hi John...", "timestamp": 1734..., "stage": "welcome"},
    {"role": "candidate", "text": "Thank you...", "timestamp": 1734...}
  ],
  "meta": {
    "candidate": "John Doe",
    "total_turns": 27
  }
}
```

### Get Interview Summary
```bash
curl http://localhost:5000/api/interview/john_doe_20241215_143000.json/summary

# Response
{
  "success": true,
  "candidate": "John Doe",
  "duration_seconds": 542,
  "stages_covered": ["welcome", "self_intro", "past_experience", "company_fit", "closing"]
}
```

### Generate Feedback (Implemented)
```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"interview_id": "john_doe_20241215_143000.json"}' \
  http://localhost:5000/api/feedback

# Response
{
  "success": true,
  "interview_id": "john_doe_20241215_143000.json",
  "feedback": "## 1. Overall Summary\n\nThe candidate demonstrated...\n\n## 2. Key Strengths\n\n- **Clear communication**...\n\n## 3. Areas to Improve\n\n- ...",
  "meta": {
    "candidate": "John Doe",
    "interview_date": "2024-12-15T14:30:00",
    "total_turns": 15,
    "model": "gpt-4o-mini"
  }
}
```

The feedback API uses chain-of-thought analysis with prompts from `POSTINTERVIEWFEEDBACK` class:
- Analyzes candidate profile and job requirements
- Evaluates response quality and structure (STAR method usage)
- Generates actionable improvement suggestions
- Provides a 1-2 week practice plan with specific exercises

### Skip Stage Request
```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"room_name": "interview-john-1734...", "target_stage": "company_fit"}' \
  http://localhost:5000/api/skip-stage

# Response
{
  "success": true,
  "target_stage": "company_fit",
  "message": "Skip to company_fit queued. The agent will transition shortly."
}
```

---

## New Pages

| Route | Description |
|-------|-------------|
| `/past-calls` | Lists saved interviews with view/feedback buttons |
| `/feedback/<filename>` | Shows transcript and feedback placeholder |

---

## Files Modified/Created

### Modified
- `fsm.py` - New stage flow, skip queue, document context fields
- `agent.py` - WELCOME/COMPANY_FIT instructions, skip handling, transcript saving on disconnect, filename emission
- `app.py` - New endpoints for upload, interviews, feedback (implemented), skip-stage
- `prompts.py` - Updated WELCOME greeting prompt, added POSTINTERVIEWFEEDBACK class
- `templates/form.html` - File upload, JD input, include profile toggle
- `templates/interview.html` - Skip controls, Get Feedback button in end modal, filename tracking
- `templates/past_calls.html` - Rich metadata display (role, level, stages, resume indicator)
- `templates/feedback.html` - Animated loading phases, scrollable feedback, error handling
- `static/interview.css` - Golden feedback button styles with shimmer/glow animations
- `static/feedback.css` - Loading phases, phase dots, scrollable content
- `static/past_calls.css` - Tags, stage pills, metadata styling
- `postprocess.py` - Enhanced merging with `merge_by_agent_turns()`, rich metadata

### Created
- `document_processor.py` - Text extraction and caching
- `postprocess.py` - Interview re-sequencing with smart merging
- `templates/past_calls.html` - Interview history list with rich metadata
- `templates/feedback.html` - Transcript view with AI feedback generation
- `requirements.txt` - Added PyPDF2, python-docx

---

## Running Locally

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Start Services
```bash
# Terminal 1: Agent
python agent.py dev

# Terminal 2: Web Server
python app.py
```

### Access
- Web UI: http://localhost:5000
- Start interview: http://localhost:5000/start
- Past interviews: http://localhost:5000/past-calls

---

## Architecture Notes

### Skip Stage Flow
1. User clicks skip button in UI
2. Frontend sends `{type: 'skip_stage', target_stage: '...'}` via LiveKit data channel
3. Agent receives message, queues skip in `InterviewState.skip_stage_queue`
4. On next transition check, agent processes skip queue
5. Agent transitions with `skipped=True`, records skipped stages
6. UI updates skip button states based on current stage

### Document Context Injection
1. User uploads resume on form page
2. Server extracts text, caches with MD5 key
3. Cache key passed to interview page via URL params
4. Token generation attaches text to participant attributes
5. Agent reads from attributes, populates `InterviewState`
6. Stage instructions inject `[DOCUMENT_CONTEXT]` placeholder
7. `_get_stage_instructions()` replaces with actual context

### Transcript Saving & Filename Sync
1. Interview ends (natural completion or user disconnect)
2. Agent saves transcript with timestamped filename
3. Agent emits `{type: 'interview_ending', filename: '...'}` or `{type: 'transcript_saved', filename: '...'}`
4. Frontend stores filename in `state.interviewFilename`
5. "Get Feedback" button uses actual filename for navigation
6. Fallback: If filename not received, redirect to past-calls page

### Feedback Generation Flow
1. User clicks "Get Feedback" or navigates to `/feedback/<filename>?request_feedback=1`
2. Frontend shows animated loading phases (5 phases, 4s each)
3. API loads transcript via `resequence_interview()` (merges user turns)
4. API builds prompt with candidate profile, job summary, and transcript
5. OpenAI GPT-4o-mini generates chain-of-thought feedback
6. Frontend renders markdown feedback with section headers, lists, and emphasis

### Post-Interview Transcript Merging
1. Raw transcript has many partial user messages (from STT chunking)
2. `merge_by_agent_turns()` groups all user messages between agent turns
3. Produces clean alternating agent/candidate conversation
4. Each merged turn shows original partial count for debugging

---

## Completed: Feedback Implementation

The feedback system is now fully implemented in `app.py` `/api/feedback` endpoint:

```python
# Implementation flow:
# 1. Load interview transcript via resequence_interview()
# 2. Format transcript with INTERVIEWER/CANDIDATE labels and stage tags
# 3. Build prompt using POSTINTERVIEWFEEDBACK class from prompts.py
# 4. Call OpenAI GPT-4o-mini with chain-of-thought analysis
# 5. Return markdown-formatted feedback
```

Feedback includes:
- **Overall summary** (3-5 sentences)
- **Key strengths** with examples from the interview
- **Areas to improve** with actionable tips
- **Answer structure feedback** (STAR method evaluation)
- **Practice plan** (1-2 weeks of exercises)

---

## TODO: Future Work

### Structured Feedback Parsing
Currently feedback is returned as markdown text. Future enhancement:
- Parse markdown into structured JSON sections
- Enable per-section display and highlighting
- Add numerical scoring for each competency

### Feedback Caching
- Cache generated feedback to avoid re-generation
- Store in interviews directory alongside transcript
- Load cached feedback on feedback page if available

### Email Delivery
- Send feedback report to candidate email
- Generate PDF version for download
- Include interview audio/video recording link (if enabled)
