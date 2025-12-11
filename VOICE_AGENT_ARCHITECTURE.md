# Streaming Voice Agent Architecture: Deep Dives & Best Practices

> Focus: Interview bot (self-intro → past-experience stages) with Python/Flask. Design for fundamentally sound extensibility.

---

## 1. REAL-TIME VOICE PIPELINE ARCHITECTURE

### Core Pipeline: STT → LLM → TTS Over WebRTC
```
User Speech (WebRTC Audio) 
  → VAD (Voice Activity Detection) 
  → Streaming STT (Deepgram) 
  → Partial Transcripts (buffered) 
  → LLM (GPT-4o-mini, streaming) 
  → Token streamer 
  → Streaming TTS (OpenAI) 
  → Audio chunks 
  → Back to User
```

**Key Insight:** Success is **concurrent execution + streaming**, not sequential processing.

- **STT latency:** 100-300ms for streaming partials (not waiting for full transcript)
- **LLM latency:** 100-500ms TTFT (Time-to-First-Token) when using streaming + smaller models
- **TTS latency:** 75-300ms depending on provider; OpenAI TTS-1 is ~200ms

**End-to-end target:** Keep round-trip under 300-400ms for natural feel. Humans respond in ~200ms on average.

### Streaming Overlaps (NOT Turn-Based)
Modern agents do NOT:
1. Wait for user to finish speaking
2. THEN call STT
3. THEN call LLM
4. THEN call TTS

Instead:
- **Start LLM as soon as** you have partial transcript (e.g., after 500ms of streaming partial from Deepgram)
- **Start TTS as soon as** first token arrives from LLM (before LLM finishes)
- **Listen AND speak simultaneously** (full-duplex), detecting user interruption via VAD

**Implementation pattern:**
```python
async def pipeline_loop():
    stt_buffer = []
    llm_generator = None
    
    while session_active:
        # Pull partial transcripts continuously
        partial = await stt.get_partial()  # Non-blocking, ~100ms chunks
        stt_buffer.append(partial)
        
        # LLM doesn't wait for "end of user utterance"
        # Start LLM planning when you have enough context (~200-500ms)
        if len(stt_buffer) >= MIN_TOKENS_TO_START_LLM and not llm_generator:
            text = "".join(stt_buffer)
            llm_generator = llm.stream(text)  # Starts immediately
        
        # Pull from LLM token-by-token, feed to TTS
        if llm_generator:
            try:
                token = next(llm_generator)  # Non-blocking iterator
                await tts.stream_token(token)  # TTS consumes tokens as they come
            except StopIteration:
                llm_generator = None
        
        # Detect user interruption (high-priority)
        if vad.user_speech_detected():
            stop_tts_immediately()
            llm_generator = None
            stt_buffer = []  # Reset for next turn
```

---

## 2. TURN-TAKING & INTERRUPTION HANDLING

### Voice Activity Detection (VAD): The Silent Killer of Bad UX
VAD is **not optional**—it's your entire turn-taking system.

**Two VAD modes to understand:**

| Mode | Behavior | Best For |
|------|----------|----------|
| **Server VAD (silence-based)** | Detects pause (default 0.5s), triggers end-of-turn | Noisy environments; forgiving timing |
| **Semantic VAD** | LLM-based: "did user complete thought?" | Clean audio; needs ~200ms extra latency |

**LiveKit defaults (good baseline):**
```python
turndetection = MultilingualModel()
# OR explicitly:
session.turn_detection = "vad"
session.min_endpointing_delay = 0.5  # Min silence before ending turn
session.max_endpointing_delay = 3.0  # Force end after 3s silence
session.allow_interruptions = True
```

**Critical VAD tuning for interviews:**
- **min_endpointing_delay = 0.4-0.5s** (user pauses to think before answering)
- If too short (~0.2s): False end-of-turn (user is still thinking)
- If too long (~1.5s): Feels unresponsive
- **Test with real interview audio** (nervous pauses, heavy accents)

### Handling Interruptions (Barge-In)
Real-world: **User interrupts agent's response.** Must handle gracefully.

**What happens behind the scenes:**
1. User starts speaking (VAD detects speech onset)
2. TTS pauses immediately (don't block the user)
3. Buffer audio being played is discarded
4. LLM generation is halted (rollback to last commit point)
5. Clear previous intent from chat history—user's new input takes priority

**Implementation pattern:**
```python
# In LiveKit AgentSession
session.allow_interruptions = True
session.min_interruption_duration = 0.5  # Don't cut off on every noise spike
session.discard_audio_if_uninterruptible = True  # Drop audio while agent speaks

# In Agent class
async def on_interrupt(self, event):
    """Called when user starts speaking during agent output."""
    logger.info(f"Interrupted! Clearing TTS buffer.")
    # Agent automatically truncates conversation history to 
    # what user heard BEFORE interruption began
    # (LiveKit handles this internally)
    pass
```

**Gotcha:** False interruption detection due to background noise (TV, traffic).
- **Solution:** Use background voice cancellation (BVC) upstream
- Reduces false positives by 3.5x (per Krisp research)
- For production: integrate Krisp or similar, pre-process audio before VAD

---

## 3. STATE MANAGEMENT FOR MULTI-STAGE INTERVIEWS

### Finite State Machine (FSM) Pattern: The Backbone
For interview flows (self-intro → past-experience), use explicit state tracking.

**Why FSM vs. "just LLM everything":**
- LLMs hallucinate state transitions (will keep asking same question)
- Interview logic is deterministic: Q1 → Q2 → Q3 (not ambiguous)
- Clear audit trail for debugging

**Minimal FSM for your 2-stage interview:**
```python
from enum import Enum
from dataclasses import dataclass

class InterviewStage(Enum):
    GREETING = "greeting"
    SELF_INTRO = "self_intro"          # Stage 1
    PAST_EXPERIENCE = "past_experience"  # Stage 2
    CLOSING = "closing"

@dataclass
class InterviewState:
    stage: InterviewStage
    candidate_name: str = ""
    self_intro_received: bool = False
    experience_responses: list[str] = None
    current_question_idx: int = 0
    timestamp_stage_started: float = None
    
    def __post_init__(self):
        if self.experience_responses is None:
            self.experience_responses = []

# In Agent class
class InterviewAgent(Agent):
    def __init__(self):
        super().__init__(instructions="...")
        self.fsm_states = {
            InterviewStage.GREETING: self.handle_greeting,
            InterviewStage.SELF_INTRO: self.handle_self_intro,
            InterviewStage.PAST_EXPERIENCE: self.handle_past_experience,
            InterviewStage.CLOSING: self.handle_closing,
        }
    
    async def handle_next_state(self, ctx: RunContext[InterviewState]):
        """Explicit state machine transition logic."""
        current = ctx.userdata.stage
        handler = self.fsm_states.get(current)
        
        if handler:
            await handler(ctx)
        else:
            logger.error(f"Unknown stage: {current}")
```

### Detecting Stage Completion (The Hard Part)
**Problem:** LLM says "thanks for sharing, let's move to the next stage" but user hasn't answered yet.

**Solution:** Use function tools + explicit confirmations, NOT LLM-driven transitions.

```python
class InterviewAgent(Agent):
    @functiontool
    async def confirm_stage_complete(
        self, 
        ctx: RunContext[InterviewState],
        quality: Annotated[int, Field(description="1-5 quality rating")]
    ) -> str:
        """LLM explicitly calls this when ready to move stages."""
        if quality < 2:
            return "Please encourage more detail."
        
        # Manual state transition
        if ctx.userdata.stage == InterviewStage.SELF_INTRO:
            ctx.userdata.stage = InterviewStage.PAST_EXPERIENCE
            ctx.userdata.timestamp_stage_started = time.time()
            return "Moving to past experience questions."
        
        return "Stage transition complete."
```

**Why explicit tools?** Because LLMs are unreliable state machines—they need guardrails.

---

## 4. TIME-BASED FALLBACK MECHANISM (Critical for Robustness)

### Problem: What If LLM Never Calls `confirm_stage_complete`?
Agent hangs in same stage, asking same question infinitely. User gets frustrated.

### Solution: Async Timeout Fallback
```python
class InterviewAgent(Agent):
    STAGE_TIMEOUT = 60  # Force transition after 60s
    
    async def on_enter(self):
        """Called when agent becomes active (stage just started)."""
        self.stage_timer = asyncio.create_task(self.stage_timeout_handler())
    
    async def on_exit(self):
        """Called when agent is deactivated."""
        if self.stage_timer:
            self.stage_timer.cancel()
    
    async def stage_timeout_handler(self):
        """Fallback: Force stage progression if LLM gets stuck."""
        try:
            await asyncio.sleep(self.STAGE_TIMEOUT)
            
            # At this point: LLM should have progressed stages
            # If not, force progression
            session = getattr(self, '_session', None)
            if session:
                userdata = session.userdata
                logger.warning(
                    f"Stage timeout! Forcing transition from {userdata.stage}"
                )
                
                if userdata.stage == InterviewStage.SELF_INTRO:
                    userdata.stage = InterviewStage.PAST_EXPERIENCE
                    await session.say(
                        "I didn't quite catch all that. Let's move on to "
                        "your past experience with similar projects."
                    )
                elif userdata.stage == InterviewStage.PAST_EXPERIENCE:
                    userdata.stage = InterviewStage.CLOSING
                    await session.say("Thank you. Let's wrap up.")
        
        except asyncio.CancelledError:
            pass  # Stage completed normally, timer cancelled
```

**Key metrics to monitor:**
- How often fallback triggers → LLM prompt needs refinement
- Stage time distribution → Interview pacing feedback

---

## 5. LATENCY OPTIMIZATION TACTICS

### Latency Budget Allocation (For ~300ms Round-Trip)
```
STT partial receipt     : 100-150ms  (Deepgram streaming partial)
LLM TTFT               : 100-200ms  (GPT-4o-mini with streaming)
TTS first bytes        : 50-100ms   (OpenAI TTS-1 via streaming)
Network jitter buffer  : 50-100ms   (WebRTC NetEQ)
───────────────────────────────────
Total                  : 300-550ms
```

### Concrete Optimization Points

**1. STT: Streaming Partials**
```python
stt = deepgram.STT(
    model="nova-3",
    language="en-US",
    smart_format=True,
    endpointing=200,  # ms, emit partial after 200ms silence
    # NO: don't wait for final transcript
)

# Get partials immediately
async for partial_transcript in stt.stream():
    if partial_transcript.is_final:
        # Official end of utterance
        pass
    else:
        # Interim partial (100-200ms latency)
        await llm.ingest_partial(partial_transcript.text)
```

**2. LLM: Streaming Output + Context Window**
```python
llm = openai.LLM(
    model="gpt-4o-mini",  # Smaller, faster than gpt-4o
    temperature=0.7,
    max_tokens=150,       # Cap responses (interview answers should be < 30s)
    stream=True,          # Stream tokens, don't wait for full response
)

# In agent instructions, keep context tight:
instructions = """
You are interviewing a candidate. Ask one question at a time.
After the candidate responds, ask a follow-up or move to the next stage.
Keep responses to 1-2 sentences max (30 seconds spoken time).
"""
```

**3. TTS: Parallel Streaming**
```python
tts = openai.TTS(
    model="tts-1",    # Faster than tts-1-hd
    voice="alloy",    # Neutral, natural
    speed=1.0,        # Don't over-speed; sounds robotic
)

# Feed tokens immediately as LLM generates
async for chunk in llm_generator:
    audio_stream = tts.synthesize(chunk)
    await session.play(audio_stream)  # Don't wait for full synthesis
```

**4. Network: Jitter Buffer & Audio Frame Size**
LiveKit handles WebRTC internally, but understand:
- **20ms frame size** is standard for good networks
- **60-120ms** for degraded networks (tradeoff: more latency, better recovery)
- **NetEQ buffer** automatically adapts; no tuning needed, but monitor for over-buffering

Monitor:
```python
session.on_participant_connected(lambda p: 
    logger.info(f"Participant stats: {p.audio_stats}")
)
```

---

## 6. DOCUMENT CONTEXT INJECTION (For Future RAG)

### Architecture Decision: Pre-Session vs. Runtime Processing

| Approach | Latency | Flexibility | Cost |
|----------|---------|-------------|------|
| **Pre-session embed** | Zero runtime cost | Hard to update | Low |
| **Runtime retrieval (RAG)** | +100-200ms per query | Easy to adapt | Medium |
| **Hybrid (cache + refresh)** | +50ms (cached) | Best | Medium |

### Best Practice: Hybrid Approach for Interview Agent

```python
# Phase 1: Pre-session (before interview starts)
async def prepare_interview_context(job_description_pdf: str, resume_pdf: str):
    """
    Called when candidate submits form but BEFORE interview starts.
    Embeddings ready in memory when agent boots.
    """
    job_context = extract_text_from_pdf(job_description_pdf)
    resume_context = extract_text_from_pdf(resume_pdf)
    
    # Embed for later retrieval
    job_embeddings = await embed_model.embed(job_context)
    resume_embeddings = await embed_model.embed(resume_context)
    
    # Store in memory (not in LLM context; too long)
    session_cache[session_id] = {
        "job": job_context,
        "resume": resume_context,
        "job_embeddings": job_embeddings,
        "resume_embeddings": resume_embeddings,
    }

# Phase 2: Runtime (during interview)
class InterviewAgent(Agent):
    @functiontool
    async def generate_follow_up_question(
        self, 
        ctx: RunContext[InterviewState], 
        last_answer: str
    ) -> str:
        """LLM can call this to get context-aware follow-ups."""
        
        # Lightweight RAG: retrieve relevant job context
        cache = session_cache[ctx.session.room.name]
        
        # Simple semantic matching (no extra latency for small docs)
        relevant_job_skills = retrieve_relevant_context(
            last_answer,
            cache["job"],
            top_k=2  # Only top 2 matches
        )
        
        # Inject into LLM prompt dynamically
        augmented_prompt = f"""
        Candidate said: "{last_answer}"
        
        Relevant job requirements: {relevant_job_skills}
        
        Ask a follow-up question that probes deeper on these skills.
        """
        
        follow_up = await self.llm.generate(augmented_prompt)
        return follow_up
```

### Why NOT Full RAG During Interview?
- **Latency adds up:** Embedding user answer (10-50ms) + retrieval (50-100ms) = 100-150ms extra per turn
- **Not needed for interviews:** Job description is small; can fit in system prompt
- **Better approach:** Embed documents once at session start, reference cached embeddings only

### Injection Pattern (Keep It Simple)
```python
# Good: Inject relevant job skills into system prompt at start
system_prompt = f"""
You are interviewing for: {job_title}
Key skills needed: {top_job_skills}

Ask about their experience with these technologies and responsibilities.
"""

# Bad: Re-embed and re-retrieve on every LLM call
# (adds unnecessary latency, doesn't improve accuracy for interviews)
```

---

## 7. PRODUCTION FAILURE MODES & RECOVERY

### Failure Mode: STT Never Detects End-of-User-Utterance
**Symptom:** Agent waits forever for user to finish; timeout eventually triggers.

**Root causes:**
- VAD tuned too long
- User has heavy accent; speech not detected
- Network packet loss (partial audio)

**Mitigation:**
```python
session.min_endpointing_delay = 0.5
session.max_endpointing_delay = 3.0  # Force end after 3s, no exceptions

# Log it
session.on_speech_committed(lambda event:
    logger.info(f"User turn took {event.duration}s, "
                f"forced={event.forced_by_timeout}")
)
```

### Failure Mode: LLM Returns Malformed JSON or Gets Stuck
**Symptom:** Agent stops responding mid-conversation.

**Root cause:** LLM confused by interview context, returns invalid tool call.

**Mitigation:**
```python
# Wrap tool calls with try-catch
@functiontool
async def record_response(self, ctx, response: str) -> str:
    try:
        if not response or len(response) > 5000:
            raise ValueError("Invalid response format")
        
        ctx.userdata.responses.append(response)
        return "Response recorded."
    except Exception as e:
        logger.error(f"Tool error: {e}")
        # Fallback: don't crash; ask user to repeat
        return "I didn't catch that. Could you repeat?"

# Also: set timeout on LLM calls
llm = openai.LLM(
    model="gpt-4o-mini",
    timeout=10,  # 10s max per response
)
```

### Failure Mode: Network Audio Dropout
**Symptom:** Audio stream freezes; user hears silence.

**Root cause:** WebRTC jitter buffer ran out of packets (network congestion).

**LiveKit handles internally**, but monitor:
```python
# Listen for network stats
async def monitor_network_health():
    while session_active:
        stats = await session.get_network_stats()
        
        if stats.packet_loss_rate > 0.05:  # 5% loss
            logger.warning(f"High packet loss: {stats.packet_loss_rate}")
            # Could adjust bitrate, increase buffer, etc.
        
        if stats.rtt_ms > 500:
            logger.warning(f"High latency: {stats.rtt_ms}ms")
        
        await asyncio.sleep(5)
```

### Failure Mode: TTS Provider Timeout / Rate Limit
**Symptom:** Agent gets stuck during response generation (no audio output).

**Mitigation:**
```python
tts = openai.TTS(model="tts-1", timeout=5)  # 5s per call

# Also: implement exponential backoff
async def resilient_tts(text: str, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await tts.synthesize(text)
        except TimeoutError:
            wait_time = 2 ** attempt  # 1s, 2s, 4s
            logger.warning(f"TTS timeout, retrying in {wait_time}s")
            await asyncio.sleep(wait_time)
    
    # Fallback: use pre-recorded apology
    return load_fallback_audio("sorry_experiencing_issues.wav")
```

### Failure Mode: Agent Keeps Asking Same Question (LLM State Loss)
**Symptom:** Loop detected: agent asks "Tell me about yourself" 3 times.

**Root cause:** LLM lost context or system prompt not enforced.

**Prevention (FSM-based):**
```python
# NOT: rely on LLM to remember "I asked this already"
# Instead: explicit question tracking

class InterviewState:
    questions_asked: list[str] = None

@functiontool
async def ask_next_question(self, ctx, ...) -> str:
    # Only ask questions from predefined list
    questions = [
        "Tell me about yourself.",
        "What's your experience with [skill]?",
        "Describe a challenging project.",
    ]
    
    idx = ctx.userdata.current_question_idx
    if idx >= len(questions):
        # No more questions; transition stage
        ctx.userdata.stage = InterviewStage.CLOSING
        return "Let's wrap up."
    
    question = questions[idx]
    ctx.userdata.current_question_idx += 1
    return question
```

---

## 8. STATE PERSISTENCE & ERROR RECOVERY

### Session State: In-Memory (For Now) vs. Database
For your sample project: **In-memory is fine.**

For production:
```python
# Snapshot state periodically
import json
import asyncio

async def checkpoint_state(userdata: InterviewState):
    """Save state to DB every 30 seconds."""
    while True:
        await asyncio.sleep(30)
        
        state_json = json.dumps({
            "stage": userdata.stage.value,
            "candidate_name": userdata.candidate_name,
            "responses": userdata.responses,
            "timestamp": time.time(),
        })
        
        # Save to DB (PostgreSQL, DynamoDB, etc.)
        await db.save_checkpoint(session_id, state_json)
```

### Recovery on Connection Drop
```python
# On agent reconnect
async def entry_point(ctx: JobContext):
    await ctx.connect()
    
    # Check if session exists
    checkpoint = await db.get_checkpoint(ctx.room.name)
    if checkpoint:
        # Restore state
        userdata = InterviewState(**json.loads(checkpoint))
        logger.info(f"Resumed interview at stage: {userdata.stage}")
    else:
        userdata = InterviewState()
    
    session = AgentSession(userdata=userdata)
    agent = InterviewAgent()
    await session.start(agent, room=ctx.room)
```

---

## 9. TESTING & VALIDATION

### Unit Test: State Transitions
```python
async def test_stage_transition():
    state = InterviewState(stage=InterviewStage.SELF_INTRO)
    
    # Simulate LLM confirmation
    state.stage = InterviewStage.PAST_EXPERIENCE
    
    assert state.stage == InterviewStage.PAST_EXPERIENCE
```

### Integration Test: Full Interview Flow
```python
async def test_full_interview_flow():
    # Mock LiveKit session
    mock_session = AsyncMock()
    mock_room = AsyncMock()
    
    # Run agent
    agent = InterviewAgent()
    ctx = RunContext(session=mock_session, userdata=InterviewState())
    
    # Simulate user turns
    await agent.on_message("Hi, I'm John")
    await agent.on_message("5 years in Python")
    
    # Assert state progression
    assert ctx.userdata.stage == InterviewStage.PAST_EXPERIENCE
    assert len(ctx.userdata.responses) == 2
```

### Latency Test: Measure End-to-End
```python
import time

async def measure_pipeline_latency():
    start = time.perf_counter()
    
    # Record "now"
    user_speech_received = time.perf_counter()
    stt_partial = await stt.get_partial()  # ~100ms
    llm_token = await llm.stream()  # ~200ms
    tts_audio = await tts.synthesize()  # ~150ms
    end = time.perf_counter()
    
    latency_ms = (end - start) * 1000
    logger.info(f"E2E latency: {latency_ms:.0f}ms")
    
    assert latency_ms < 400, "Latency budget exceeded"
```

---

## 10. FLASK APP INTEGRATION CHECKLIST

### Minimal Flask Setup
```python
# app.py
from flask import Flask, render_template, request, jsonify
from agent import InterviewAgent, interview_entry_point
from livekit.agents import cli

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/interview/start', methods=['POST'])
def start_interview():
    data = request.json
    candidate_name = data.get('name')
    job_role = data.get('role')
    
    # Generate LiveKit token
    token = generate_token(candidate_name, room_name=f"interview_{candidate_name}")
    
    return jsonify({
        'token': token,
        'room': f"interview_{candidate_name}",
        'server_url': LIVEKIT_URL,
    })

@app.route('/api/interview/end', methods=['POST'])
def end_interview():
    # Cleanup, save results
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    # Start agent worker in background
    from threading import Thread
    agent_thread = Thread(target=lambda: cli.run_app(
        entry_point=interview_entry_point
    ), daemon=True)
    agent_thread.start()
    
    app.run(debug=True, port=5000)
```

### Critical Flask ↔ LiveKit Bridge
- **Session ID mapping:** Flask `session` ↔ LiveKit `room_name`
- **Token generation:** Use LiveKit API to create participant tokens
- **Result persistence:** Store interview results (responses, feedback) in DB after session ends

---

## 11. SUMMARY: ARCHITECTURE DECISIONS FOR YOUR PROJECT

| Decision | Choice | Why |
|----------|--------|-----|
| **State Management** | FSM (explicit stages) | Prevents infinite loops; clear audit trail |
| **Interruption Handling** | LiveKit built-in (allow_interruptions=True) | Automatic, handles complexities |
| **Fallback Transitions** | Async timeout timer | Guarantees progress if LLM stalls |
| **Latency Optimization** | Streaming STT/LLM/TTS + caching | Achievable <400ms E2E |
| **Document Context** | Pre-session embedding + lightweight retrieval | Future-proof without runtime latency |
| **Error Recovery** | Try-catch around tools + fallback responses | Graceful degradation |
| **Testing** | Integration tests for state, unit tests for tools | Catches multi-stage flow bugs |

---

## Final Gotchas to Avoid

1. **Don't wait for "final" transcript from STT.** Use partials.
2. **Don't let LLM drive state transitions.** Use explicit tools + FSM.
3. **Don't inject huge PDFs into every LLM prompt.** Pre-embed, cache, retrieve sparingly.
4. **Don't ignore VAD tuning.** Test with real interview audio (accents, pauses, background noise).
5. **Don't rely on single timeout mechanism.** Layer: VAD endpointing + LLM timeout + stage timeout.
6. **Don't forget to log latency metrics.** You'll need them to debug "feels slow" complaints.
7. **Don't use production TTS models in dev.** Cost adds up fast; use mocking or cheaper models initially.

---

**End of recommendations.**
