# MockFlow-AI Production Migration Plan

Complete phased migration to production with Supabase backend and BYOK architecture. Each phase is self-contained and can be completed independently.

## Core Principles

- Maintain existing UI theme, colors, fonts, and styling
- Reuse existing CSS classes, modals, and button effects
- **NO localStorage - Database is single source of truth**
- **NO local file storage - Render's filesystem is ephemeral**
- **On-demand agent workers - Spawn per interview, terminate on completion**
- No new features (subscriptions, payments, etc.)
- Iterative approach - each phase is complete before next begins

## Production Environment

- **Hosting**: Render.com (Free Tier - 512MB RAM, 0.1 CPU)
- **Database**: Supabase (Free Tier)
- **LiveKit**: Cloud (Free Tier - agent dispatch enabled)
- **Expected Users**: <5 concurrent

---

## Phase 1: Backend Foundation - Supabase Integration ✅ DONE

**Goal**: Set up backend infrastructure with Supabase client and database operations.

**Status**: Complete

---

## Phase 2: Authentication Foundation - Supabase Auth ✅ DONE

**Goal**: Implement Google OAuth authentication using Supabase's built-in auth.

**Status**: Complete

---

## Phase 3: Authentication UI - Login & Dashboard ✅ DONE

**Goal**: Create login page and user dashboard with existing UI theme.

**Status**: Complete

---

## Phase 4: API Key Management - BYOK Implementation ✅ DONE

**Goal**: Allow users to save and manage their API keys (LiveKit, OpenAI, Deepgram) with full BYOK model.

**Status**: Complete - All 5 API keys (LiveKit URL/Key/Secret, OpenAI, Deepgram) stored encrypted

---

## Phase 5: Database-Only Storage (Remove ALL localStorage & Local Files)

**Goal**: Eliminate localStorage fallbacks and local file writes. Database is single source of truth.

**Duration**: 1-2 days

**Dependencies**: Phase 4 complete

### Critical Changes

**REMOVE:**
- All `localStorage.setItem()` and `localStorage.getItem()` calls
- All file writes to `interviews/` folder
- All "localStorage fallback" logic

**REASON:** Render's filesystem is ephemeral - files disappear on service restart. localStorage doesn't work across devices.

---

### 5.1 Update `agent.py` - Direct Database Save (NO File Writes)

**Location**: Root directory

**DELETE** file writing logic (around lines 830-878):
```python
# DELETE THIS ENTIRE SECTION:
os.makedirs("interviews", exist_ok=True)
filepath = f"interviews/{just_filename}"
with open(filepath, 'w', encoding='utf-8') as f:
    json_module.dump(history_data, f, indent=2, ensure_ascii=False)
```

**REPLACE** `finalize_and_disconnect()` function:
```python
async def finalize_and_disconnect(ctx: JobContext, participant, conversation_history, state):
    """Save interview to database and disconnect"""
    try:
        import json as json_module
        from datetime import datetime
        
        # Extract user_id from participant attributes
        attrs = participant.attributes if hasattr(participant, 'attributes') else {}
        user_id = attrs.get('user_id')
        
        if not user_id:
            logger.error("[FINALIZE] No user_id found in participant attributes")
            await ctx.room.disconnect()
            return
        
        logger.info(f"[FINALIZE] Saving interview to database for user: {user_id}")
        
        # Build interview data
        now = datetime.now()
        interview_data = {
            'candidate_name': state.candidate_name,
            'interview_date': now.isoformat(),
            'room_name': ctx.room.name,
            'job_role': state.job_role,
            'experience_level': state.experience_level,
            'conversation': conversation_history,
            'total_messages': {
                'agent': len(conversation_history.get('agent', [])),
                'user': len(conversation_history.get('user', []))
            },
            'skipped_stages': state.skipped_stages,
            'final_stage': state.stage.value,
            'ended_by': 'natural_completion',
            'has_resume': bool(state.uploaded_resume_text),
            'has_jd': bool(state.job_description)
        }
        
        # Save to Supabase
        from supabase_client import supabase_client
        interview_id = supabase_client.save_interview(user_id, interview_data)
        
        if interview_id:
            logger.info(f"[FINALIZE] Interview saved successfully: {interview_id}")
            
            # Notify frontend of successful save
            data_payload = json_module.dumps({
                "type": "interview_saved",
                "interview_id": interview_id,
                "message": "Interview saved successfully"
            })
            await ctx.room.local_participant.publish_data(data_payload.encode('utf-8'))
            
        else:
            logger.error("[FINALIZE] Database save failed")
            
            # Notify frontend of save error
            data_payload = json_module.dumps({
                "type": "save_error",
                "message": "Failed to save interview. Please contact support."
            })
            await ctx.room.local_participant.publish_data(data_payload.encode('utf-8'))
        
        # Wait for data to send, then disconnect
        await asyncio.sleep(2.0)
        await ctx.room.disconnect()
        logger.info("[FINALIZE] Disconnected from room")
        
    except Exception as e:
        logger.error(f"[FINALIZE] Error: {e}", exc_info=True)
        
        # Attempt to notify frontend
        try:
            import json as json_module
            data_payload = json_module.dumps({
                "type": "save_error",
                "message": f"Save error: {str(e)}"
            })
            await ctx.room.local_participant.publish_data(data_payload.encode('utf-8'))
        except:
            pass
        
        # Disconnect anyway
        try:
            await ctx.room.disconnect()
        except:
            pass
```

**UPDATE** `save_transcript_on_disconnect()` (around line 916):
```python
async def save_transcript_on_disconnect():
    """Save interview transcript when room disconnects"""
    try:
        # Don't save if already finalized
        if closing_finalized.get("done"):
            logger.info("[HISTORY] Transcript already saved via finalize_and_disconnect")
            return
        
        # Check if we have any conversation to save
        if not conversation_history["agent"] and not conversation_history["user"]:
            logger.info("[HISTORY] No conversation to save")
            return
        
        # Extract user_id from participant
        if not ctx.room.remote_participants:
            logger.error("[HISTORY] No remote participants found")
            return
        
        participant = list(ctx.room.remote_participants.values())[0]
        attrs = participant.attributes if hasattr(participant, 'attributes') else {}
        user_id = attrs.get('user_id')
        
        if not user_id:
            logger.error("[HISTORY] No user_id found in participant attributes")
            return
        
        import json as json_module
        from datetime import datetime
        
        now = datetime.now()
        interview_data = {
            'candidate_name': candidate_name,
            'interview_date': now.isoformat(),
            'room_name': ctx.room.name,
            'job_role': interview_state.job_role,
            'experience_level': interview_state.experience_level,
            'conversation': conversation_history,
            'total_messages': {
                'agent': len(conversation_history['agent']),
                'user': len(conversation_history['user'])
            },
            'skipped_stages': interview_state.skipped_stages,
            'final_stage': interview_state.stage.value,
            'ended_by': 'user_disconnect'
        }
        
        # Save to database
        from supabase_client import supabase_client
        interview_id = supabase_client.save_interview(user_id, interview_data)
        
        if interview_id:
            logger.info(f"[HISTORY] Saved transcript on disconnect: {interview_id}")
            
            # Emit the interview_id to frontend
            try:
                data_payload = json_module.dumps({
                    "type": "interview_saved",
                    "interview_id": interview_id
                })
                await ctx.room.local_participant.publish_data(data_payload.encode('utf-8'))
            except Exception as e:
                logger.warning(f"[HISTORY] Failed to emit interview_id: {e}")
        else:
            logger.error("[HISTORY] Database save failed on disconnect")
        
    except Exception as e:
        logger.error(f"[HISTORY] Error saving on disconnect: {e}", exc_info=True)
```

**UPDATE** `entrypoint()` - Call finalize with correct params (around line 890):
```python
# In the finalize_and_disconnect call
await finalize_and_disconnect(ctx, participant, conversation_history, interview_state)
```

---

### 5.2 Update `templates/interview.html` - Remove localStorage, Handle Database Events

**Location**: `templates/interview.html`

**DELETE** all localStorage save calls:
- Remove: `localStorage.setItem('interview_${roomName}', ...)`
- Remove: `saveInterviewData()` function
- Remove: `uploadInterviewToDatabase()` function

**REPLACE** `onDataReceived()` handler (around line 850):
```javascript
function onDataReceived(payload, participant) {
    try {
        var data = JSON.parse(new TextDecoder().decode(payload));
        
        if (data.type === 'stage_change' && data.stage) {
            updateStage(data.stage);
        }
        
        if (data.type === 'agent_caption') {
            updateAgentCaption(data.text);
        }
        
        if (data.type === 'user_caption') {
            updateCandidateCaption(data.text);
        }
        
        if (data.type === 'interview_saved') {
            // Store interview_id for feedback navigation
            state.interviewDatabaseId = data.interview_id;
            console.log('[INTERVIEW] Saved to database:', data.interview_id);
        }
        
        if (data.type === 'save_error') {
            console.error('[INTERVIEW] Save error:', data.message);
            updateStatus('Save Error: ' + data.message, 'error');
        }
        
        if (data.type === 'interview_ending') {
            updateAgentCaption('Interview complete.');
            updateStatus('Interview Complete', 'connected');
            
            setTimeout(function() {
                showInterviewCompleteModal();
            }, 2000);
        }
        
    } catch (err) {
        console.error('[DATA] Parse error:', err);
    }
}
```

**REPLACE** `showInterviewCompleteModal()` function:
```javascript
function showInterviewCompleteModal() {
    document.getElementById('modalTitle').textContent = 'Interview Complete';
    document.getElementById('modalMessage').textContent = 'Thank you for participating! Would you like to get feedback?';
    document.getElementById('modalIcon').className = 'modal-icon success';
    document.getElementById('modalIcon').innerHTML = '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>';
    
    // Hide the confirm/cancel actions, show feedback actions
    document.getElementById('modalActions').style.display = 'none';
    document.getElementById('modalFeedbackActions').style.display = 'flex';
    
    // Set up feedback button
    var feedbackBtn = document.getElementById('getFeedbackBtn');
    feedbackBtn.onclick = function() {
        if (state.interviewDatabaseId) {
            // Redirect to feedback page with interview_id
            window.location.href = '/feedback/' + encodeURIComponent(state.interviewDatabaseId);
        } else {
            // No interview_id received - show error
            alert('Interview was not saved properly. Please check your Past Interviews page.');
            window.location.href = '/past-calls';
        }
    };
    
    // Set up return home button
    document.getElementById('returnHomeBtn').onclick = function() {
        window.location.href = '/';
    };
    
    showModal();
}
```

**DELETE** `uploadInterviewToDatabase()` function entirely

---

### 5.3 Update `templates/feedback.html` - Database-Only Load

**Location**: `templates/feedback.html`

**DELETE** all localStorage references:
- Remove: `localStorage.getItem('feedback_...')`
- Remove: `localStorage.setItem('feedback_...')`
- Remove: `localStorage.getItem('interview_...')`

**REPLACE** `loadInterview()` function (around line 180):
```javascript
function loadInterview() {
    // filename is actually interview_id from URL parameter
    fetch('/api/interview/' + encodeURIComponent(filename))
        .then(function(response) {
            if (!response.ok) throw new Error('Interview not found');
            return response.json();
        })
        .then(function(data) {
            elements.loadingState.style.display = 'none';
            
            if (data.error) {
                showError('Interview not found in database: ' + data.error);
                return;
            }

            renderInterview(data);
            checkCachedFeedback();
        })
        .catch(function(err) {
            console.error('[FEEDBACK] Load error:', err);
            elements.loadingState.style.display = 'none';
            showError('Failed to load interview. Please check your Past Interviews page.');
        });
}
```

**REPLACE** `checkCachedFeedback()` function:
```javascript
function checkCachedFeedback() {
    // Check backend for cached feedback
    fetch('/api/feedback/get/' + encodeURIComponent(filename))
        .then(function(response) {
            if (!response.ok) return null;
            return response.json();
        })
        .then(function(data) {
            if (data && data.feedback_data) {
                console.log('[FEEDBACK] Found cached feedback in database');
                
                if (data.feedback_data.scores) {
                    renderScores(data.feedback_data.scores, true);
                    feedbackState.scoresGenerated = true;
                }
                
                if (data.feedback_data.feedback) {
                    renderFeedback(data.feedback_data.feedback, true);
                    feedbackState.reportGenerated = true;
                }
                
                elements.generateSection.style.display = 'none';
            } else {
                console.log('[FEEDBACK] No cached feedback found');
            }
        })
        .catch(function(err) {
            console.log('[FEEDBACK] No cached feedback available');
        });
}
```

**REPLACE** `saveFeedbackToDatabase()` function:
```javascript
function saveFeedbackToDatabase(interviewId, feedbackData) {
    fetch('/api/feedback/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
            interview_id: interviewId,
            feedback: feedbackData
        })
    })
    .then(function(response) { return response.json(); })
    .then(function(result) {
        if (result.success) {
            console.log('[FEEDBACK] Saved to database successfully');
        } else {
            console.error('[FEEDBACK] Save failed:', result.message);
        }
    })
    .catch(function(err) {
        console.error('[FEEDBACK] Save error:', err);
    });
}
```

**UPDATE** `generateReport()` - Remove localStorage cache, only save to DB:
```javascript
function generateReport() {
    console.log('[FEEDBACK] Stage 2: Generating detailed report...');
    elements.feedbackPlaceholder.style.display = 'none';
    elements.feedbackLoading.style.display = 'flex';

    // Animate loading phases
    var phases = [
        'Reading transcript...',
        'Matching candidate info...',
        'Looking through job requirements...',
        'Contemplating insights...'
    ];
    var phaseIndex = 0;

    var phaseInterval = setInterval(function() {
        phaseIndex = (phaseIndex + 1) % phases.length;
        elements.loadingPhase.textContent = phases[phaseIndex];

        var dots = document.querySelectorAll('.phase-dot');
        dots.forEach(function(dot, i) {
            dot.classList.toggle('active', i <= phaseIndex);
        });
    }, 3000);

    fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            interview_id: filename,
            scores: feedbackState.scoresData
        })
    })
    .then(function(response) { return response.json(); })
    .then(function(data) {
        clearInterval(phaseInterval);

        if (data.error) {
            showFeedbackError(data.message || data.error);
            return;
        }

        console.log('[FEEDBACK] Report generated successfully');
        feedbackState.reportGenerated = true;

        // Save to database (no localStorage)
        saveFeedbackToDatabase(filename, {
            feedback: data.feedback,
            scores: feedbackState.scoresData
        });

        renderFeedback(data.feedback, false);
    })
    .catch(function(err) {
        clearInterval(phaseInterval);
        console.error('[FEEDBACK] Report generation error:', err);
        showFeedbackError('Failed to generate report: ' + err.message);
    });
}
```

---

### 5.4 Update `templates/past_calls.html` - Database-Only Load

**Location**: `templates/past_calls.html`

**DELETE** all localStorage functions:
- Remove: `getLocalStorageInterviews()`
- Remove: `mergeInterviews()`
- Remove: `loadFromLocalStorageOnly()`
- Remove: `loadFromDatabaseWithLocalStorageMerge()`

**REPLACE** `loadInterviews()` function (around line 240):
```javascript
function loadInterviews() {
    checkAuth().then(function(isAuthenticated) {
        if (isAuthenticated) {
            loadFromDatabase();
        } else {
            showError('Please log in to view your interviews');
        }
    }).catch(function() {
        showError('Authentication check failed. Please log in.');
    });
}

function loadFromDatabase() {
    fetch('/api/user/interviews?limit=50')
        .then(function(response) {
            if (!response.ok) throw new Error('Failed to load interviews');
            return response.json();
        })
        .then(function(dbInterviews) {
            console.log('[PAST_CALLS] Loaded ' + dbInterviews.length + ' interviews from database');
            
            elements.loadingState.style.display = 'none';

            if (dbInterviews.length === 0) {
                showEmptyState();
                return;
            }

            renderInterviews(dbInterviews);
        })
        .catch(function(err) {
            console.error('[PAST_CALLS] Database load error:', err);
            elements.loadingState.style.display = 'none';
            showError('Failed to load interviews: ' + err.message);
        });
}
```

**UPDATE** `renderInterviews()` - Use database fields:
```javascript
function renderInterviews(interviews) {
    var html = interviews.map(function(interview) {
        var date = interview.interview_date ? formatDate(interview.interview_date) : 'Unknown date';
        var messageCount = interview.total_messages || {};
        var totalMessages = (messageCount.agent || 0) + (messageCount.user || 0);
        
        // interview.id is the database ID
        var interviewId = interview.id;

        var tagsHtml = '';
        if (interview.job_role) {
            tagsHtml += '<span class="interview-tag role">' + escapeHtml(interview.job_role) + '</span>';
        }
        if (interview.experience_level) {
            tagsHtml += '<span class="interview-tag level">' + formatLevel(interview.experience_level) + '</span>';
        }

        return '<a href="/feedback/' + encodeURIComponent(interviewId) + '" class="interview-card">' +
            '<div class="card-content">' +
                '<div class="interview-name">' + escapeHtml(interview.candidate_name || 'Unknown') + '</div>' +
                '<div class="interview-date">' + date + '</div>' +
                (tagsHtml ? '<div class="interview-tags">' + tagsHtml + '</div>' : '') +
                '<div class="interview-meta">' +
                    '<span class="interview-meta-item">' +
                        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>' +
                        totalMessages + ' msgs' +
                    '</span>' +
                '</div>' +
            '</div>' +
            '<svg class="card-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">' +
                '<path d="M9 18l6-6-6-6"/>' +
            '</svg>' +
        '</a>';
    }).join('');

    elements.interviewsGrid.innerHTML = html;
}
```

---

### 5.5 Update `app.py` - Database-Only Endpoints

**Location**: `app.py`

**REPLACE** `/api/interview/<interview_id>` endpoint:
```python
@app.route('/api/interview/<interview_id>')
@require_auth
def get_interview(interview_id):
    """Get interview by ID from database"""
    try:
        user_id = get_user_id()
        
        # Validate UUID format
        import uuid
        try:
            uuid.UUID(interview_id)
        except ValueError:
            return jsonify({'error': 'Invalid interview ID format'}), 400
        
        # Load from database
        interview = supabase_client.get_interview_by_id(user_id, interview_id)
        
        if not interview:
            return jsonify({'error': 'Interview not found'}), 404
        
        logger.info(f"[API] Loaded interview {interview_id} for user {user_id}")
        
        # Format conversation for frontend
        ordered_conversation = format_conversation(interview.get('conversation', {}))
        
        # Format for frontend
        return jsonify({
            'success': True,
            'meta': {
                'candidate': interview.get('candidate_name', 'Unknown'),
                'interview_date': interview.get('interview_date'),
                'job_role': interview.get('job_role'),
                'experience_level': interview.get('experience_level'),
                'source': 'database'
            },
            'ordered_conversation': ordered_conversation
        })
        
    except Exception as e:
        logger.error(f"[API] Get interview error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


def format_conversation(conversation_dict):
    """Convert DB conversation format to ordered list for frontend"""
    try:
        agent_msgs = conversation_dict.get('agent', [])
        user_msgs = conversation_dict.get('user', [])
        
        # Merge by timestamp
        all_msgs = []
        
        for msg in agent_msgs:
            all_msgs.append({
                'role': 'agent',
                'text': msg.get('text', ''),
                'timestamp': msg.get('timestamp', 0),
                'stage': msg.get('stage', '')
            })
        
        for msg in user_msgs:
            all_msgs.append({
                'role': 'user',
                'text': msg.get('text', ''),
                'timestamp': msg.get('timestamp', 0)
            })
        
        # Sort by timestamp
        all_msgs.sort(key=lambda x: x.get('timestamp', 0))
        
        return all_msgs
        
    except Exception as e:
        logger.error(f"[FORMAT] Conversation format error: {e}", exc_info=True)
        return []
```

**DELETE** old file-based endpoints:
- Remove: `/api/interviews` (old file listing)
- Remove: `/api/interview/<filename>/summary` (old file-based summary)

**UPDATE** `/api/feedback/get/<interview_id>`:
```python
@app.route('/api/feedback/get/<interview_id>')
@require_auth
def get_feedback_by_id(interview_id):
    """Get feedback for interview from database"""
    try:
        user_id = get_user_id()
        
        # Validate UUID format
        import uuid
        try:
            uuid.UUID(interview_id)
        except ValueError:
            return jsonify({'error': 'Invalid interview ID'}), 400
        
        # Get feedback from database
        feedback = supabase_client.get_feedback(interview_id)
        
        if not feedback:
            return jsonify({}), 404
        
        # Verify user owns this interview
        if feedback.get('user_id') != user_id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        logger.info(f"[API] Feedback retrieved for interview: {interview_id}")
        return jsonify(feedback)
        
    except Exception as e:
        logger.error(f"[API] Feedback fetch error: {e}", exc_info=True)
        return jsonify({}), 500
```

---

### 5.6 Update `supabase_client.py` - Add Missing Method

**Location**: `supabase_client.py`

**ADD** new method:
```python
def get_interview_by_id(self, user_id: str, interview_id: str) -> Optional[Dict[str, Any]]:
    """Get interview by ID for specific user"""
    try:
        response = self.client.table('interviews').select('*').eq('id', interview_id).eq('user_id', user_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error fetching interview by ID: {e}", exc_info=True)
        return None
```

---

### Phase 5 Tasks Checklist

- [x] Update `agent.py` - Remove file writes, add database save with error handling
- [x] Update `agent.py` - Modify `finalize_and_disconnect()` to save to DB and emit events
- [x] Update `agent.py` - Modify `save_transcript_on_disconnect()` to save to DB
- [x] Update `templates/interview.html` - Remove localStorage, handle `interview_saved` event
- [x] Update `templates/feedback.html` - Database-only load, remove localStorage
- [x] Update `templates/past_calls.html` - Database-only load, remove localStorage merge
- [x] Update `app.py` - Add `format_conversation()` helper
- [x] Update `app.py` - Update `/api/interview/<interview_id>` to use database
- [x] Update `app.py` - Update `/api/feedback/get/<interview_id>`
- [x] Update `supabase_client.py` - Add `get_interview_by_id()` method
- [x] Test interview save to database (check agent logs)
- [x] Test feedback load from database
- [x] Test past calls list from database
- [x] Verify NO localStorage usage remains (search codebase for `localStorage`)
- [x] Verify NO file writes remain (search for `open(`, `makedirs`)
- [x] Commit changes: "Phase 5: Database-only storage, remove localStorage"

### Critical Corrections (Not in Original Plan)

During implementation, two critical issues were discovered and fixed:

**Correction 5.7: Authentication & user_id in Token Generation**
- **File**: `app.py` - `/api/token` endpoint (line 342)
- **Issue**: Token generation was not requiring authentication and was missing `user_id` in participant attributes
- **Fix**: Added `@require_auth` decorator, extracted `user_id` using `get_user_id()`, and included it in participant attributes dict
- **Impact**: Without this, agent couldn't save interviews (no user_id), causing cascade of failures

**Correction 5.8: Database Loading in Feedback Pipeline**
- **File**: `app.py` - `_load_interview_context()` function (line 972)
- **Issue**: Feedback generation was still using file-based `resequence_interview()` function with database UUIDs
- **Fix**: Rewrote function to load directly from database using `supabase_client.get_interview_by_id()`, removed file-based import
- **Impact**: Fixed feedback generation 404 errors when interviews stored as database UUIDs

**Phase 5 Complete** ✅: All storage is database-only, no localStorage or file writes

---

## Phase 6: On-Demand Agent Worker (Spawn & Terminate)

**Goal**: Agent spawns as subprocess when interview starts, terminates when complete. Uses user's API keys from participant attributes.

**Duration**: 2-3 days

**Dependencies**: Phase 5 complete

### Architecture Overview
```
User Flow:
1. User submits form → POST /api/start-interview
2. Backend:
   - Validates user has API keys
   - Spawns agent subprocess with user's decrypted keys
   - Waits for agent "ready" signal (3-5 seconds)
   - Returns room URL + token
3. User redirects to interview page → connects to LiveKit
4. Agent handles interview (isolated subprocess)
5. Interview ends:
   - Agent saves to database
   - Subprocess terminates automatically
   - Frontend redirects to feedback page
```

**Key Changes:**
- Agent receives API keys via **environment variables** (subprocess isolated)
- Agent runs per-interview, not 24/7
- Clean termination after interview ends

---

### 6.1 Create `agent_worker.py`

**Location**: Root directory

**Purpose**: Standalone agent that accepts runtime environment variables

**Implementation**:

This is a **copy of `agent.py`** with these modifications:
```python
"""
MockFlow-AI Interview Agent Worker

Standalone agent that runs as subprocess with API keys passed via environment variables.
Terminates automatically after interview ends.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# DO NOT load .env file - keys come from subprocess environment
# load_dotenv()  # REMOVE THIS LINE

from livekit.agents import (
    AgentServer,
    AgentSession,
    JobContext,
    cli,
    Agent,
    RunContext,
    function_tool,
)
from livekit.plugins import openai, deepgram, silero

from fsm import InterviewState, InterviewStage, STAGE_TIME_LIMITS, STAGE_MIN_QUESTIONS
from prompts import (
    build_stage_instructions,
    get_transition_ack,
    get_fallback_ack,
    build_role_context,
    build_personality_note,
    WELCOME,
    SKIP_STAGE,
    CLOSING_FALLBACK,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("agent-worker")

# Suppress noisy logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Verify API keys are in environment (passed by parent process)
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
DEEPGRAM_API_KEY = os.getenv('DEEPGRAM_API_KEY')
LIVEKIT_URL = os.getenv('LIVEKIT_URL')
LIVEKIT_API_KEY = os.getenv('LIVEKIT_API_KEY')
LIVEKIT_API_SECRET = os.getenv('LIVEKIT_API_SECRET')

if not all([OPENAI_API_KEY, DEEPGRAM_API_KEY, LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET]):
    logger.error("[CONFIG] Missing required API keys in environment")
    logger.error(f"[CONFIG] OpenAI: {bool(OPENAI_API_KEY)}, Deepgram: {bool(DEEPGRAM_API_KEY)}")
    logger.error(f"[CONFIG] LiveKit URL: {bool(LIVEKIT_URL)}, Key: {bool(LIVEKIT_API_KEY)}, Secret: {bool(LIVEKIT_API_SECRET)}")
    sys.exit(1)

logger.info("[CONFIG] API keys loaded from environment")
logger.info(f"[CONFIG] LiveKit URL: {LIVEKIT_URL}")

# Create agent server
server = AgentServer()

# ... REST OF AGENT.PY CODE EXACTLY THE SAME ...
# (Copy all classes, functions, decorators from agent.py)

if __name__ == "__main__":
    logger.info("[WORKER] Starting agent worker subprocess")
    cli.run_app(server)
```

**Key Differences from `agent.py`:**
1. **No `load_dotenv()`** - keys come from subprocess environment
2. **Strict validation** - exits if keys missing
3. **Different logger name** - `"agent-worker"` for easy identification

---

### 6.2 Create `worker_manager.py`

**Location**: Root directory

**Purpose**: Manages agent worker subprocesses (spawn, monitor, terminate)

**Implementation**:
```python
"""
Agent Worker Manager

Spawns and manages agent worker subprocesses for interviews.
Each interview gets a dedicated subprocess with user's API keys.
"""

import os
import subprocess
import logging
import asyncio
import time
from typing import Optional, Dict

logger = logging.getLogger(__name__)

class WorkerManager:
    def __init__(self):
        self.active_workers: Dict[str, subprocess.Popen] = {}
        self.worker_script = os.path.join(os.path.dirname(__file__), 'agent_worker.py')
        
    def spawn_worker(
        self,
        room_name: str,
        livekit_url: str,
        livekit_api_key: str,
        livekit_api_secret: str,
        openai_api_key: str,
        deepgram_api_key: str
    ) -> bool:
        """
        Spawn agent worker subprocess with user's API keys.
        
        Returns:
            bool: True if worker started successfully, False otherwise
        """
        try:
            logger.info(f"[WORKER] Spawning worker for room: {room_name}")
            
            # Build environment with user's API keys
            worker_env = os.environ.copy()
            worker_env.update({
                'LIVEKIT_URL': livekit_url,
                'LIVEKIT_API_KEY': livekit_api_key,
                'LIVEKIT_API_SECRET': livekit_api_secret,
                'OPENAI_API_KEY': openai_api_key,
                'DEEPGRAM_API_KEY': deepgram_api_key,
                'PYTHONUNBUFFERED': '1'  # Force unbuffered output
            })
            
            # Spawn subprocess
            process = subprocess.Popen(
                ['python', self.worker_script],
                env=worker_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1  # Line buffered
            )
            
            # Store process reference
            self.active_workers[room_name] = process
            
            logger.info(f"[WORKER] Worker spawned (PID: {process.pid}) for room: {room_name}")
            
            # Wait for worker to be ready (check for startup log)
            return self._wait_for_worker_ready(process, timeout=10)
            
        except Exception as e:
            logger.error(f"[WORKER] Failed to spawn worker: {e}", exc_info=True)
            return False
    
    def _wait_for_worker_ready(self, process: subprocess.Popen, timeout: int = 10) -> bool:
        """
        Wait for worker to emit ready signal.
        
        Returns:
            bool: True if worker ready within timeout, False otherwise
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check if process is still alive
            if process.poll() is not None:
                # Process died
                stdout, stderr = process.communicate()
                logger.error(f"[WORKER] Process died during startup")
                logger.error(f"[WORKER] STDOUT: {stdout}")
                logger.error(f"[WORKER] STDERR: {stderr}")
                return False
            
            # Check for ready signal in logs
            # For now, just wait 5 seconds (agent startup time)
            # In production, parse stdout for "Starting agent worker" log
            if time.time() - start_time >= 5:
                logger.info("[WORKER] Worker assumed ready after 5 seconds")
                return True
            
            time.sleep(0.5)
        
        logger.error(f"[WORKER] Worker not ready within {timeout}s timeout")
        return False
    
    def terminate_worker(self, room_name: str):
        """Terminate worker subprocess for room"""
        try:
            if room_name not in self.active_workers:
                logger.warning(f"[WORKER] No active worker for room: {room_name}")
                return
            
            process = self.active_workers[room_name]
            
            if process.poll() is None:
                # Process still running - terminate
                logger.info(f"[WORKER] Terminating worker (PID: {process.pid}) for room: {room_name}")
                process.terminate()
                
                # Wait for graceful shutdown (max 5 seconds)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"[WORKER] Worker did not terminate gracefully, forcing kill")
                    process.kill()
                    process.wait()
            
            # Remove from active workers
            del self.active_workers[room_name]
            logger.info(f"[WORKER] Worker terminated for room: {room_name}")
            
        except Exception as e:
            logger.error(f"[WORKER] Error terminating worker: {e}", exc_info=True)
    
    def cleanup_all_workers(self):
        """Terminate all active workers (called on server shutdown)"""
        logger.info(f"[WORKER] Cleaning up {len(self.active_workers)} active workers")
        
        for room_name in list(self.active_workers.keys()):
            self.terminate_worker(room_name)
        
        logger.info("[WORKER] All workers terminated")
    
    def get_worker_status(self, room_name: str) -> Optional[str]:
        """
        Get worker status for room.
        
        Returns:
            str: 'running', 'terminated', or None if not found
        """
        if room_name not in self.active_workers:
            return None
        
        process = self.active_workers[room_name]
        
        if process.poll() is None:
            return 'running'
        else:
            return 'terminated'


# Global worker manager instance
worker_manager = WorkerManager()
```

---

### 6.3 Update `app.py` - Add Worker Spawn Endpoint

**Location**: `app.py`

**ADD** import at top:
```python
from worker_manager import worker_manager
import atexit
```

**ADD** cleanup handler:
```python
# Register cleanup on server shutdown
atexit.register(worker_manager.cleanup_all_workers)
```

**REPLACE** `/api/token` endpoint:
```python
@app.route('/api/token', methods=['POST'])
@require_auth
def generate_token():
    """
    Spawn agent worker and generate LiveKit token.
    
    This endpoint:
    1. Validates user has API keys
    2. Spawns dedicated agent worker subprocess with user's keys
    3. Waits for worker ready signal
    4. Generates LiveKit token
    5. Returns token + room info
    """
    try:
        user_id = get_user_id()
        data = request.json or {}
        
        name = data.get('name', 'Anonymous')
        email = data.get('email', '')
        role = data.get('role', '')
        level = data.get('level', '')
        resume_cache_key = data.get('resumeCacheKey', '')
        job_description = data.get('jobDescription', '')
        include_profile = data.get('includeProfile', True)
        
        logger.info(f"[TOKEN] Token request from user {user_id} ({name})")
        
        # Get user's API keys from database
        keys = supabase_client.get_api_keys(user_id)
        
        if not keys:
            logger.error(f"[TOKEN] No API keys found for user: {user_id}")
            return jsonify({
                'error': 'API keys not configured',
                'message': 'Please configure your API keys in Settings before starting an interview.'
            }), 400
        
        # Validate keys are present
        required_keys = ['livekit_url', 'livekit_api_key', 'livekit_api_secret', 'openai_key', 'deepgram_key']
        missing_keys = [k for k in required_keys if not keys.get(k)]
        
        if missing_keys:
            logger.error(f"[TOKEN] Missing keys for user {user_id}: {missing_keys}")
            return jsonify({
                'error': 'Incomplete API keys',
                'message': f'Missing keys: {", ".join(missing_keys)}'
            }), 400
        
        # Create unique room name
        timestamp = int(time.time())
        room_name = f"interview-{name.lower().replace(' ', '-')}-{timestamp}"
        
        logger.info(f"[TOKEN] Spawning worker for room: {room_name}")
        
        # Spawn agent worker subprocess with user's API keys
        worker_started = worker_manager.spawn_worker(
            room_name=room_name,
            livekit_url=keys['livekit_url'],
            livekit_api_key=keys['livekit_api_key'],
            livekit_api_secret=keys['livekit_api_secret'],
            openai_api_key=keys['openai_key'],
            deepgram_api_key=keys['deepgram_key']
        )
        
        if not worker_started:
            logger.error(f"[TOKEN] Worker failed to start for room: {room_name}")
            return jsonify({
                'error': 'Worker startup failed',
                'message': 'Failed to start interview agent. Please try again.'
            }), 500
        
        logger.info(f"[TOKEN] Worker ready for room: {room_name}")
        
        # Build participant attributes (without API keys - already in worker)
        attributes = {
            'user_id': user_id,
            'role': role,
            'level': level,
            'email': email,
            'include_profile': str(include_profile).lower(),
        }
        
        # Add resume text if cached
        if resume_cache_key:
            resume_text = doc_processor.get_cached_text(resume_cache_key)
            if resume_text:
                attributes['resume_text'] = resume_text[:3000]  # Truncate to fit
                logger.info(f"[TOKEN] Attached resume text ({len(resume_text)} chars)")
        
        # Add job description if provided
        if job_description:
            attributes['job_description'] = job_description[:2000]  # Truncate
            logger.info(f"[TOKEN] Attached job description ({len(job_description)} chars)")
        
        # Create LiveKit access token using USER'S keys
        token = api.AccessToken(
            keys['livekit_api_key'],
            keys['livekit_api_secret']
        )
        
        token.with_identity(name).with_name(name).with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            )
        ).with_attributes(attributes)
        
        # Generate JWT
        jwt_token = token.to_jwt()
        
        logger.info(f"[TOKEN] Token generated successfully for room: {room_name}")
        
        return jsonify({
            'token': jwt_token,
            'url': keys['livekit_url'],  # Use user's LiveKit URL
            'room': room_name,
            'candidate': {
                'name': name,
                'email': email,
                'role': role,
                'level': level
            }
        })
        
    except Exception as e:
        logger.error(f"[TOKEN] Token generation error: {e}", exc_info=True)
        return jsonify({
            'error': 'Token generation failed',
            'message': str(e)
        }), 500
```

**ADD** worker status endpoint:
```python
@app.route('/api/worker/status/<room_name>')
@require_auth
def worker_status(room_name):
    """Check worker status for room"""
    try:
        status = worker_manager.get_worker_status(room_name)
        
        return jsonify({
            'room_name': room_name,
            'status': status or 'not_found'
        })
        
    except Exception as e:
        logger.error(f"[WORKER] Status check error: {e}")
        return jsonify({'error': str(e)}), 500
```

---

### 6.4 Update `templates/interview.html` - Handle Worker Startup Delay

**Location**: `templates/interview.html`

**UPDATE** `connectToRoom()` function to show "Waiting for agent..." status:
```javascript
async function connectToRoom() {
    updateStatus('Starting agent worker...', 'connecting');
    
    try {
        // ... existing token generation code ...
        
        var response = await fetch('/api/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(tokenData)
        });
        
        var data = await response.json();
        
        if (data.error) {
            throw new Error(data.message || data.error);
        }
        
        // Store room name
        state.roomName = data.room;
        
        updateStatus('Agent worker ready. Connecting to room...', 'connecting');
        
        // ... rest of connection code ...
        
    } catch (err) {
        console.error('[CONNECT] Error:', err);
        updateStatus('Connection failed: ' + err.message, 'error');
    }
}
```

---

### Phase 6 Tasks Checklist

- [ ] Create `agent_worker.py` - Copy from `agent.py` with environment key loading
- [ ] Create `worker_manager.py` - Subprocess management
- [ ] Update `app.py` - Import `worker_manager`, add cleanup handler
- [ ] Update `app.py` - Replace `/api/token` to spawn worker before token generation
- [ ] Update `app.py` - Add `/api/worker/status/<room_name>` endpoint
- [ ] Update `templates/interview.html` - Show "Starting agent..." status
- [ ] Test worker spawn (check logs for "Worker spawned (PID: ...)")
- [ ] Test interview flow end-to-end
- [ ] Test worker termination after interview ends
- [ ] Verify worker isolation (run 2 concurrent interviews with different keys)
- [ ] Test worker cleanup on server shutdown
- [ ] Commit changes: "Phase 6: On-demand agent workers with BYOK"

**Phase 6 Complete**: Agent spawns per interview, uses user's API keys, terminates cleanly

---

## Phase 7: Production Deployment & Testing

**Goal**: Deploy to Render, verify all functionality, optimize for free tier limits.

**Duration**: 2-3 days

**Dependencies**: Phase 6 complete

### 7.1 Render Configuration

**Create `render.yaml`**

**Location**: Root directory
```yaml
services:
  - type: web
    name: mockflow-ai
    env: python
    region: oregon
    plan: free
    buildCommand: "pip install -r requirements.txt"
    startCommand: "gunicorn app:app"
    envVars:
      - key: PYTHON_VERSION
        value: 3.11.0
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_SERVICE_KEY
        sync: false
      - key: SUPABASE_ANON_KEY
        sync: false
      - key: ENCRYPTION_KEY
        sync: false
      - key: SECRET_KEY
        sync: false
```

**Update `requirements.txt`**

Add production dependencies:
```txt
# Existing dependencies...
gunicorn==21.2.0
psycopg2-binary==2.9.9
```

---

### 7.2 Production Environment Variables

**Set in Render Dashboard:**
```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
SUPABASE_ANON_KEY=eyJ...

# Security
ENCRYPTION_KEY=<your-fernet-key>
SECRET_KEY=<your-flask-secret>

# Python
PYTHON_VERSION=3.11.0
```

**Note**: User API keys (LiveKit, OpenAI, Deepgram) are NOT in environment - they come from database.

---

### 7.3 Performance Optimizations for Free Tier

**Update `app.py` - Add Worker Limits**
```python
# At top of app.py
MAX_CONCURRENT_WORKERS = 3  # Free tier limit
```

**Update `worker_manager.py`**
```python
class WorkerManager:
    def __init__(self):
        self.active_workers: Dict[str, subprocess.Popen] = {}
        self.max_workers = int(os.getenv('MAX_CONCURRENT_WORKERS', '3'))
        
    def spawn_worker(self, ...):
        # Check worker limit
        if len(self.active_workers) >= self.max_workers:
            logger.error(f"[WORKER] Max concurrent workers ({self.max_workers}) reached")
            return False
        
        # ... rest of spawn logic ...
```

**Add Worker Timeout Cleanup**
```python
# In worker_manager.py
class WorkerManager:
    async def cleanup_stale_workers(self):
        """Terminate workers that have been running too long (60 minutes)"""
        import time
        
        MAX_WORKER_AGE = 3600  # 60 minutes
        
        for room_name, process in list(self.active_workers.items()):
            if process.poll() is not None:
                # Already terminated
                del self.active_workers[room_name]
                continue
            
            # Check process age (requires tracking start time - add to spawn_worker)
            # For now, just rely on natural termination
            pass
```

---

### 7.4 Database Indexes for Performance

**Run in Supabase SQL Editor:**
```sql
-- Index for fast user interview lookups
CREATE INDEX IF NOT EXISTS idx_interviews_user_date 
ON interviews(user_id, interview_date DESC);

-- Index for feedback lookups
CREATE INDEX IF NOT EXISTS idx_feedback_interview 
ON feedback(interview_id);

-- Index for API key lookups
CREATE INDEX IF NOT EXISTS idx_api_keys_user 
ON user_api_keys(user_id);
```

---

### 7.5 Error Monitoring & Logging

**Update `app.py` - Add Request Logging**
```python
import logging
from logging.handlers import RotatingFileHandler

# Configure logging
if not app.debug:
    # Production logging
    file_handler = RotatingFileHandler('logs/mockflow.log', maxBytes=10240, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('MockFlow-AI startup')
```

---

### 7.6 Health Check Endpoint
```python
@app.route('/health')
def health_check():
    """Health check for Render"""
    try:
        # Check database connection
        user = supabase_client.get_user('test')  # Will return None, but tests connection
        
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'active_workers': len(worker_manager.active_workers)
        }), 200
        
    except Exception as e:
        logger.error(f"[HEALTH] Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500
```

---

### 7.7 Testing Checklist

**Authentication Flow**
- [ ] Google OAuth login works
- [ ] Session persists across page reloads
- [ ] Logout clears session
- [ ] Protected routes redirect to login
- [ ] Auth status API returns correct state

**API Key Management**
- [ ] Keys save to database encrypted
- [ ] Keys load with masking
- [ ] Update keys works (INSERT vs UPDATE)
- [ ] Validation catches invalid formats
- [ ] Test keys validates formats

**Interview Flow**
- [ ] Worker spawns on "Start Interview"
- [ ] Interview page loads after worker ready
- [ ] Agent connects to room
- [ ] Voice transcription works (STT)
- [ ] Agent responds (LLM + TTS)
- [ ] Stage transitions work
- [ ] Skip stage buttons work
- [ ] Interview saves to database on completion
- [ ] No localStorage writes occur
- [ ] Worker terminates after interview

**Feedback Flow**
- [ ] Feedback page loads interview from database
- [ ] Generate scores works
- [ ] Generate report works
- [ ] Feedback saves to database
- [ ] No localStorage reads/writes

**Past Calls**
- [ ] Past calls loads from database
- [ ] Interview cards display correctly
- [ ] Clicking card opens feedback page
- [ ] No localStorage merge logic runs

**Error Handling**
- [ ] Missing API keys shows error
- [ ] Worker spawn failure shows error
- [ ] Database save failure shows error
- [ ] Invalid interview_id returns 404
- [ ] Unauthorized access returns 403

**Performance**
- [ ] Max 3 concurrent workers enforced
- [ ] Workers terminate cleanly
- [ ] No memory leaks (check logs)
- [ ] Page load times <3 seconds
- [ ] Database queries <500ms

---

### 7.8 Deployment Steps

**1. Push to GitHub**
```bash
git add .
git commit -m "Production ready: Database-only storage + on-demand workers"
git push origin main
```

**2. Create Render Service**

1. Go to Render Dashboard
2. New → Web Service
3. Connect GitHub repo
4. Select `main` branch
5. Use `render.yaml` configuration
6. Add environment variables
7. Deploy

**3. Configure Supabase**

1. Run SQL migrations (indexes, RLS policies)
2. Verify Google OAuth callback URLs
3. Test database connection from Render

**4. Verify Deployment**
```bash
# Check health endpoint
curl https://mockflow-ai.onrender.com/health

# Check logs in Render dashboard
# Look for: "MockFlow-AI startup"
# Look for: "Worker spawned (PID: ...)"
```

---

### 7.9 Post-Deployment Monitoring

**Daily Checks**
- [ ] Health endpoint returns 200
- [ ] No error spikes in logs
- [ ] Worker count stays <3
- [ ] Database queries remain fast

**Weekly Checks**
- [ ] Review Supabase usage (should stay in free tier)
- [ ] Review Render usage (512MB RAM limit)
- [ ] Check for zombie workers (should be 0)
- [ ] User feedback/bug reports

---

### Phase 7 Tasks Checklist

- [ ] Create `render.yaml` deployment config
- [ ] Update `requirements.txt` with production deps
- [ ] Add database indexes in Supabase
- [ ] Update `app.py` - Add worker limits
- [ ] Update `app.py` - Add health check endpoint
- [ ] Update `app.py` - Add production logging
- [ ] Test all flows locally before deployment
- [ ] Push to GitHub
- [ ] Deploy to Render
- [ ] Configure environment variables in Render
- [ ] Run database migrations in Supabase
- [ ] Test live site end-to-end
- [ ] Monitor logs for errors
- [ ] Verify no localStorage usage (check browser DevTools)
- [ ] Commit changes: "Phase 7: Production deployment"

**Phase 7 Complete**: Application deployed and tested in production

---

## Success Criteria

Migration is complete when:
- ✅ All 7 phases completed
- ✅ All tests passing
- ✅ No localStorage usage anywhere
- ✅ No local file writes
- ✅ Database properly configured with indexes
- ✅ BYOK working correctly (user keys isolated)
- ✅ On-demand workers spawn and terminate
- ✅ Production environment deployed to Render
- ✅ Health check endpoint returns healthy
- ✅ <5 concurrent users can use system

---

## Rollback Plan

If issues arise:

1. **Phase 7 Issues**: Revert to Phase 6 commit, run locally
2. **Database Issues**: Check Supabase logs, verify RLS policies
3. **Worker Issues**: Check Render logs for subprocess errors
4. **Critical Bugs**: Revert entire migration, use local dev mode

Always keep backups of:
- Database schema dumps
- Environment variables
- Working code commits

---

## Support & Maintenance

After deployment:

**1. Monitor:**
- Worker spawn/terminate logs
- Database query performance
- Render memory usage (should stay <400MB)
- API key usage (user's responsibility)

**2. Regular Tasks:**
- Review logs weekly
- Clean up stale database entries (optional)
- Update dependencies monthly
- Backup database weekly (Supabase auto-backup enabled)

**3. User Support:**
- Document common issues in README
- Provide email support
- Monitor GitHub issues

---

## Known Limitations

**1. Free Tier Constraints:**
- Max 3 concurrent interviews
- 512MB RAM (Render)
- 500MB database (Supabase)
- No persistent filesystem (ephemeral)

**2. Worker Startup Delay:**
- 3-5 seconds to spawn worker
- User sees "Starting agent..." message

**3. No Worker Pooling:**
- Each interview spawns fresh worker
- Slightly slower than persistent workers
- Acceptable for <5 concurrent users

---

## Migration Complete

You now have a production-ready mock interview platform with:
- ✅ Google OAuth authentication
- ✅ Encrypted BYOK API key storage
- ✅ Database-only persistence (no localStorage)
- ✅ On-demand agent workers (spawn per interview)
- ✅ Clean worker termination
- ✅ Free tier optimized deployment