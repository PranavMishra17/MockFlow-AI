# MockFlow-AI Testing Guide

## Quick Start Testing

### Prerequisites Check

1. **Environment Variables**:
   ```bash
   # Verify .env file exists and contains required keys
   cat .env | grep -E "LIVEKIT_URL|LIVEKIT_API_KEY|OPENAI_API_KEY|DEEPGRAM_API_KEY"
   ```

2. **Dependencies Installed**:
   ```bash
   pip list | grep -E "livekit|Flask|openai|deepgram"
   ```

### Testing Steps

#### Step 1: Test Agent Startup

**Terminal 1 - Start Agent in Dev Mode:**
```bash
python agent.py dev
```

**Expected Output:**
```
[INFO] [MAIN] Starting MockFlow-AI Interview Agent
[INFO] [SESSION] Connected to room: ...
```

**Common Issues:**
- `ModuleNotFoundError`: Run `pip install -r requirements.txt`
- `Connection Error`: Verify LiveKit credentials in `.env`
- `API Key Error`: Check OpenAI and Deepgram keys

#### Step 2: Test Flask Web Server

**Terminal 2 - Start Flask:**
```bash
python app.py
```

**Expected Output:**
```
[INFO] [MAIN] Starting Flask web server
[INFO] [MAIN] Access the application at http://localhost:5000
* Running on http://0.0.0.0:5000
```

**Test Health Endpoint:**
```bash
curl http://localhost:5000/api/health
```

**Expected Response:**
```json
{
  "status": "healthy",
  "service": "MockFlow-AI",
  "livekit_configured": true
}
```

#### Step 3: Test Web UI

1. **Open Browser**: Navigate to `http://localhost:5000`

2. **Landing Page**:
   - Verify page loads with banner
   - Check "Start Mock Interview" button is visible
   - Click button to proceed to form

3. **Registration Form**:
   - Fill in:
     - Name: "Test Candidate"
     - Email: "test@example.com"
     - Role: "Software Engineer"
     - Level: "Mid Level"
   - Click "Start Interview"

4. **Interview Room**:
   - Should redirect to interview page
   - Check for "Connecting..." status
   - Verify audio permissions requested
   - Wait for "Connected" status

#### Step 4: Test Voice Interaction

1. **Microphone Test**:
   - Ensure microphone is enabled in browser
   - Speak: "Hello, can you hear me?"
   - Wait for agent response

2. **Stage 1 - Self Introduction**:
   - Agent should greet you
   - Introduce yourself: "Hi, I'm [Name]. I'm a software engineer with 3 years of experience..."
   - Agent should ask 1-2 follow-up questions
   - Answer naturally

3. **Stage Transition**:
   - After 2-3 minutes, agent should transition to Stage 2
   - Check stage indicator updates
   - Timer should reset

4. **Stage 2 - Past Experience**:
   - Agent should reference your introduction
   - Discuss a project: "I worked on a web application that..."
   - Answer follow-up questions

5. **Closing**:
   - After discussion, agent should wrap up
   - Thank you message
   - Click "End Interview" or wait for auto-disconnect

#### Step 5: Verify Logs

**Check Agent Logs:**
```bash
# Look for successful state transitions
grep "Stage transition" logs/*.log

# Look for any errors
grep "ERROR" logs/*.log
```

**Expected Log Patterns:**
```
[AGENT] Stage transition: greeting -> self_intro (reason: ...)
[AGENT] Stage transition: self_intro -> past_experience (reason: ...)
[FALLBACK] Stage: self_intro, Time: 45s / 360s
```

### Test Scenarios

#### Scenario 1: Normal Flow
- Complete full interview (8-10 minutes)
- Verify smooth transitions
- No forced transitions

#### Scenario 2: Fallback Mechanism
- Start interview
- Stay silent in Stage 1 for 6+ minutes
- Verify forced transition occurs
- Check logs for `FORCING stage transition`

#### Scenario 3: Interruption Handling
- Start interview
- Interrupt agent while speaking
- Verify agent stops and listens
- Continue conversation naturally

#### Scenario 4: Connection Recovery
- Start interview
- Disconnect network briefly
- Verify reconnection or error handling
- Check logs for connection status

### Performance Checks

#### Latency Monitoring
Watch logs for timing information:
```bash
grep -E "latency|duration" logs/*.log
```

**Target Metrics:**
- STT latency: < 300ms
- LLM response: < 500ms
- TTS synthesis: < 200ms
- Total round-trip: < 400ms

#### State Verification
Monitor state verification checkpoints:
```bash
grep "State verification" logs/*.log
```

**Expected:** Checkpoint every 30 seconds

### Troubleshooting

#### Issue: No Audio Output
**Check:**
1. Browser audio permissions granted
2. Agent is connected to room
3. TTS provider API key is valid
4. Check browser console for WebRTC errors

**Debug:**
```javascript
// In browser console
console.log(room.participants)
console.log(room.localParticipant.audioTracks)
```

#### Issue: Agent Not Responding
**Check:**
1. Agent process is running (`ps aux | grep agent.py`)
2. No errors in agent logs
3. LLM API key is valid
4. Internet connection stable

**Debug:**
```bash
# Restart agent with debug logging
export LOG_LEVEL=DEBUG
python agent.py dev
```

#### Issue: Stage Not Transitioning
**Check:**
1. Minimum time requirement met
2. LLM calling transition_stage tool
3. Fallback timer functioning

**Debug:**
```bash
# Watch for transition attempts
tail -f logs/*.log | grep -E "transition|fallback"
```

### Manual Testing Checklist

- [ ] Agent starts without errors
- [ ] Flask server starts without errors
- [ ] Landing page loads correctly
- [ ] Registration form accepts input
- [ ] Token generation succeeds
- [ ] Interview room connects to LiveKit
- [ ] Audio input detected (microphone)
- [ ] Audio output works (speaker)
- [ ] Stage 1 conversation flows naturally
- [ ] Stage 1 → Stage 2 transition occurs
- [ ] Stage 2 conversation continues
- [ ] Closing stage completes
- [ ] Interview can be ended manually
- [ ] Logs show no critical errors
- [ ] State verification checkpoints occur
- [ ] Fallback timer works if needed
- [ ] UI is readable (high contrast)
- [ ] Responsive design works on mobile

### Automated Testing (Future)

**Unit Tests:**
```bash
# Future: Add pytest tests
pytest tests/test_fsm.py
pytest tests/test_agent.py
```

**Integration Tests:**
```bash
# Future: Add integration tests
pytest tests/test_integration.py
```

## Success Criteria

✅ **All Systems Go** if:
1. Agent connects to LiveKit successfully
2. Web UI loads and is navigable
3. Token generation works
4. Voice pipeline functions (STT → LLM → TTS)
5. Stage transitions occur (manual or automatic)
6. Interview completes without crashes
7. Logs show expected progression
8. No critical errors in logs

---

## Testing Tips

1. **Use headphones** to prevent audio feedback
2. **Quiet environment** for better STT accuracy
3. **Clear speech** helps transcription
4. **Wait for pauses** for natural turn-taking
5. **Check logs** frequently during testing
6. **Document issues** with timestamps and log excerpts

---

## Reporting Issues

When reporting issues, include:
1. **Steps to reproduce**
2. **Expected behavior**
3. **Actual behavior**
4. **Relevant log excerpts**
5. **Browser/system information**
6. **Timestamp of occurrence**

---

**Happy Testing!**
