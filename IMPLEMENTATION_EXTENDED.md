# MockFlow-AI Implementation Summary

## New Features Implemented

### 1. Updated Interview Stage Flow
```
WELCOME (60s) -> SELF_INTRO (120s) -> PAST_EXPERIENCE (240s) -> COMPANY_FIT (240s) -> CLOSING (45s)
```

### 2. Document Extraction & Storage
- **Privacy-first**: Only extracted text is stored, never raw files
- Supports: PDF (PyPDF2), DOCX (python-docx), MD, TXT
- Cache uses MD5 hash keys for deduplication

### 3. Skip Stage Feature
- Candidates can skip ahead to any future stage via UI buttons
- Skip requests are queued and processed gracefully by the agent
- Skipped stages are tracked in interview history

### 4. Post-Interview Re-sequencing
- Merges candidate partial transcripts (gap <= 1.0s)
- Interleaves agent/candidate turns by timestamp
- Provides ordered conversation for review

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

### List Interviews
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
      "message_count": {"agent": 15, "user": 12}
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

### Request Feedback (Skeleton)
```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"interview_id": "john_doe_20241215_143000.json"}' \
  http://localhost:5000/api/feedback

# Response
{
  "interview_id": "john_doe_20241215_143000.json",
  "status": "queued",
  "message": "Feedback generation will be implemented in a future release.",
  "feedback_schema": {
    "strengths": ["(Coming soon)..."],
    "improvements": ["(Coming soon)..."],
    "question_feedback": [...]
  }
}
```

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
- `agent.py` - WELCOME/COMPANY_FIT instructions, skip handling via data channel
- `app.py` - New endpoints for upload, interviews, feedback, skip-stage
- `templates/form.html` - File upload, JD input, include profile toggle
- `templates/interview.html` - Skip controls (5 stages), updated progress bar

### Created
- `document_processor.py` - Text extraction and caching
- `postprocess.py` - Interview re-sequencing
- `templates/past_calls.html` - Interview history list
- `templates/feedback.html` - Transcript view and feedback placeholder
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

---

## TODO: Future Work

### Feedback Implementation
Location: `app.py` `/api/feedback` endpoint

```python
# TODO: Implement LLM-driven feedback
# 1. Load interview transcript via resequence_interview()
# 2. Build structured prompt for analysis
# 3. Call OpenAI with transcript + prompt
# 4. Parse response into feedback_schema format
# 5. Return structured feedback JSON
```

Expected response format:
```json
{
  "strengths": ["Clear communication", "Good STAR examples"],
  "improvements": ["Quantify impact more", "Elaborate on challenges"],
  "question_feedback": [
    {
      "question": "Tell me about a project...",
      "response_quality": "Good depth, missing metrics",
      "suggestions": "Include specific numbers"
    }
  ],
  "overall_score": 7.5
}
```
