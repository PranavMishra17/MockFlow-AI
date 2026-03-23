# LiveKit Agents Framework - Complete Analysis

## Executive Summary

This document contains a comprehensive analysis of the LiveKit Agents repository, extracting essential patterns, configurations, and code structures needed to build a voice-based mock interview agent.

---

## 1. Repository Structure Map

### Core Framework (`livekit-agents/livekit/agents/`)

```
agents/
├── livekit-agents/livekit/agents/
│   ├── job.py                    # JobContext, job lifecycle management
│   ├── worker.py                 # AgentServer, worker registration
│   ├── voice/
│   │   ├── agent.py              # Agent, AgentTask base classes
│   │   ├── agent_session.py     # AgentSession - main runtime orchestrator
│   │   ├── events.py            # Event types and handlers
│   │   ├── speech_handle.py     # Speech control and interruptions
│   │   └── run_result.py        # Turn completion and results
│   ├── llm/
│   │   ├── chat_context.py      # ChatContext, ChatMessage
│   │   ├── tool_context.py      # FunctionTool, function_tool decorator
│   │   └── llm.py               # LLM base interface
│   ├── stt/                      # Speech-to-text interfaces
│   ├── tts/                      # Text-to-speech interfaces
│   └── vad.py                    # Voice Activity Detection
│
├── livekit-plugins/              # Plugin implementations
│   ├── livekit-plugins-openai/   # OpenAI STT, LLM, TTS
│   ├── livekit-plugins-deepgram/ # Deepgram STT
│   └── livekit-plugins-silero/   # Silero VAD
│
└── examples/
    ├── minimal_worker.py         # Simplest working example
    ├── drive-thru/agent.py       # Complex ordering agent
    └── frontdesk/frontdesk_agent.py  # Appointment booking agent
```

---

## 2. Core Concepts & Architecture

### 2.1 JobContext - Connection to LiveKit Room

**Purpose**: Manages the connection to a LiveKit room and provides room/participant access.

**Key Properties**:
- `room`: The LiveKit Room object for media I/O
- `agent`: The local participant (your agent)
- `job`: Job information (room name, participant details)
- `api`: LiveKitAPI for server operations

**Usage Pattern**:
```python
@server.rtc_session()
async def entrypoint(ctx: JobContext):
    await ctx.connect()  # Connect to LiveKit room
    logger.info(f"Connected to room: {ctx.room.name}")

    # Access room for media operations
    # ctx.room - for tracks, participants
```

### 2.2 AgentServer - Worker Registration

**Purpose**: Entry point that registers with LiveKit server and dispatches jobs.

**Initialization Pattern**:
```python
from livekit.agents import AgentServer, cli

server = AgentServer()

@server.rtc_session()
async def my_agent(ctx: JobContext):
    # Your agent logic here
    pass

if __name__ == "__main__":
    cli.run_app(server)  # Starts worker, connects to LiveKit
```

### 2.3 AgentSession - The Voice Pipeline Runtime

**Purpose**: Orchestrates the entire voice agent pipeline (STT → LLM → TTS).

**Key Responsibilities**:
- Manages audio I/O from room
- Coordinates STT, VAD, LLM, TTS components
- Handles turn detection and interruptions
- Manages conversation history (ChatContext)
- Executes function tools

**Core Parameters**:
```python
session = AgentSession(
    # Core Components
    stt=deepgram.STT(),           # Speech-to-text
    llm=openai.LLM(model="gpt-4o"), # Language model
    tts=cartesia.TTS(),           # Text-to-speech
    vad=silero.VAD.load(),        # Voice activity detection

    # Turn Detection
    turn_detection=MultilingualModel(),  # When user finishes speaking

    # Behavior
    allow_interruptions=True,     # Can user interrupt?
    min_endpointing_delay=0.5,    # Min wait after speech ends
    max_endpointing_delay=3.0,    # Max wait before forcing turn end
    max_tool_steps=3,             # Max consecutive tool calls

    # Optional
    userdata=my_custom_data,      # Per-session custom data
    tools=[my_tool1, my_tool2],   # Shared tools for all agents
)

await session.start(agent=MyAgent(), room=ctx.room)
```

### 2.4 Agent - The Conversational Logic

**Purpose**: Defines agent behavior, instructions, and tools.

**Base Class Pattern**:
```python
class MyAgent(Agent):
    def __init__(self):
        super().__init__(
            instructions="You are a helpful assistant...",
            tools=[self.my_function_tool],
        )

    @function_tool
    async def my_function_tool(self, ctx: RunContext, param: str) -> str:
        """Tool description for LLM"""
        # Access session data
        ctx.session  # AgentSession
        ctx.userdata  # Your custom data
        ctx.speech_handle  # Current speech handle

        return "result to send to LLM"

    async def on_enter(self) -> None:
        """Called when agent becomes active"""
        pass

    async def on_exit(self) -> None:
        """Called when agent is deactivated"""
        pass
```

---

## 3. Essential Code Patterns

### 3.1 Minimal Working Agent

```python
import logging
from dotenv import load_dotenv
from livekit.agents import AgentServer, AgentSession, JobContext, cli
from livekit.plugins import openai, deepgram, silero

load_dotenv()
logger = logging.getLogger("my-agent")

server = AgentServer()

@server.rtc_session()
async def entrypoint(ctx: JobContext):
    await ctx.connect()
    logger.info(f"Connected to room: {ctx.room.name}")

    session = AgentSession(
        stt=deepgram.STT(),
        llm=openai.LLM(model="gpt-4o"),
        tts=openai.TTS(),
        vad=silero.VAD.load(),
    )

    agent = Agent(
        instructions="You are a helpful voice assistant."
    )

    await session.start(agent=agent, room=ctx.room)

if __name__ == "__main__":
    cli.run_app(server)
```

### 3.2 Agent with Custom Instructions & Tools

```python
from dataclasses import dataclass
from livekit.agents import Agent, RunContext, function_tool

@dataclass
class InterviewData:
    candidate_name: str
    current_question: int
    responses: dict[int, str]

class MockInterviewAgent(Agent):
    def __init__(self):
        instructions = """
        You are an expert technical interviewer.
        Ask one question at a time and wait for the candidate's response.
        Provide constructive feedback after each answer.
        """

        super().__init__(
            instructions=instructions,
            tools=[self.record_response, self.next_question],
        )

    @function_tool
    async def record_response(
        self,
        ctx: RunContext[InterviewData],
        question_id: int,
        response: str
    ) -> str:
        """Record the candidate's response to a question."""
        ctx.userdata.responses[question_id] = response
        return f"Response recorded for question {question_id}"

    @function_tool
    async def next_question(self, ctx: RunContext[InterviewData]) -> str:
        """Move to the next interview question."""
        ctx.userdata.current_question += 1
        return f"Moving to question {ctx.userdata.current_question}"
```

### 3.3 Dynamic Prompt Updates

```python
class AdaptiveAgent(Agent):
    async def update_difficulty(self, new_level: str):
        """Update instructions dynamically during conversation"""
        new_instructions = f"""
        You are an interviewer at {new_level} difficulty level.
        Adjust your questions accordingly.
        """
        await self.update_instructions(new_instructions)

    async def on_user_turn_completed(
        self,
        turn_ctx: ChatContext,
        new_message: ChatMessage
    ):
        """Called after user speaks, before LLM responds"""
        # Modify chat context before LLM sees it
        # e.g., inject context, filter messages, etc.
        pass
```

### 3.4 Event Handling Pattern

```python
@server.rtc_session()
async def entrypoint(ctx: JobContext):
    await ctx.connect()

    session = AgentSession(...)

    # Register event handlers
    @session.on("user_input_transcribed")
    def on_transcript(event):
        logger.info(f"User said: {event.transcript}")

    @session.on("agent_state_changed")
    def on_state_change(event):
        logger.info(f"Agent state: {event.old_state} -> {event.new_state}")

    @session.on("speech_created")
    def on_speech(event):
        logger.info(f"Agent speaking: {event.speech_handle}")

    await session.start(agent=agent, room=ctx.room)
```

### 3.5 Managing Interruptions

```python
@function_tool
async def critical_operation(ctx: RunContext) -> str:
    """A function that should not be interrupted"""
    # Prevent interruptions during critical operations
    ctx.disallow_interruptions()

    # Perform operation
    result = await perform_long_task()

    # Wait for current speech to finish before returning
    await ctx.wait_for_playout()

    return result
```

### 3.6 Async Task Management with Timers

```python
class TimedInterviewAgent(Agent):
    def __init__(self):
        super().__init__(instructions="...")
        self._timeout_task = None

    async def on_enter(self):
        """Start timer when agent becomes active"""
        self._timeout_task = asyncio.create_task(self._question_timeout())

    async def on_exit(self):
        """Cleanup timer when agent exits"""
        if self._timeout_task:
            self._timeout_task.cancel()

    async def _question_timeout(self):
        """Timeout after 60 seconds if no response"""
        await asyncio.sleep(60)
        # Trigger fallback behavior
        speech = await self.session.say(
            "I haven't heard a response. Let's move on."
        )
```

### 3.7 Using RunContext in Tools

```python
@function_tool
async def schedule_callback(ctx: RunContext[UserData]) -> str:
    """Example showing RunContext usage"""
    # Access session
    session = ctx.session

    # Access custom userdata
    user_email = ctx.userdata.email

    # Access current speech handle
    speech = ctx.speech_handle

    # Check if user interrupted
    if speech.interrupted:
        return "Operation cancelled by user"

    # Prevent further interruptions
    ctx.disallow_interruptions()

    # Wait for current speech to complete
    await ctx.wait_for_playout()

    return "Callback scheduled"
```

---

## 4. Plugin Integration Patterns

### 4.1 OpenAI Plugin

```python
from livekit.plugins import openai

# STT
stt = openai.STT(model="whisper-1")

# LLM
llm = openai.LLM(
    model="gpt-4o",
    temperature=0.7,
    parallel_tool_calls=False,  # Execute tools sequentially
)

# TTS
tts = openai.TTS(
    model="tts-1",
    voice="alloy",
    speed=1.0
)
```

### 4.2 Deepgram STT

```python
from livekit.plugins import deepgram

stt = deepgram.STT(
    model="nova-3",
    language="en-US",
    smart_format=True,
    keyterms=["BigMac", "McFlurry"],  # Boost recognition
    mip_opt_out=True,  # Disable interim partials
)
```

### 4.3 Cartesia TTS

```python
from livekit.plugins import cartesia

tts = cartesia.TTS(
    voice="f786b574-daa5-4673-aa0c-cbe3e8534c02",
    speed="fast",  # or "normal", "slow"
)
```

### 4.4 Silero VAD

```python
from livekit.plugins import silero

vad = silero.VAD.load(
    min_speech_duration=0.1,
    min_silence_duration=0.5,
)
```

### 4.5 Turn Detection

```python
from livekit.plugins.turn_detector.multilingual import MultilingualModel

# Use multilingual turn detector
turn_detection = MultilingualModel()

# Or use specific mode
session = AgentSession(
    turn_detection="vad",  # Options: "vad", "stt", "realtime_llm", "manual"
    # ...
)
```

---

## 5. Configuration Requirements

### 5.1 Environment Variables

Create a `.env` file:

```bash
# LiveKit Server Connection (Required)
LIVEKIT_URL=wss://your-livekit-server.com
LIVEKIT_API_KEY=your_api_key
LIVEKIT_API_SECRET=your_api_secret

# OpenAI (if using OpenAI plugin)
OPENAI_API_KEY=sk-...

# Deepgram (if using Deepgram plugin)
DEEPGRAM_API_KEY=...

# Cartesia (if using Cartesia plugin)
CARTESIA_API_KEY=...

# Development
LOG_LEVEL=INFO
```

### 5.2 Python Version

```
Requires: Python >=3.9, <3.14
```

### 5.3 Core Dependencies

```toml
# From pyproject.toml
dependencies = [
    "livekit>=1.0.19,<2",
    "livekit-api>=1.0.7,<2",
    "livekit-agents>=1.3.6",
    "python-dotenv>=0.19.0",
]

# Plugins (install as needed)
optional-dependencies = [
    "livekit-plugins-openai>=1.3.6",
    "livekit-plugins-deepgram>=1.3.6",
    "livekit-plugins-silero>=1.3.6",
    "livekit-plugins-cartesia>=1.3.6",
]
```

### 5.4 Installation Commands

```bash
# Core framework
pip install livekit-agents

# With plugins
pip install livekit-agents[openai,deepgram,silero]

# Or specific plugins
pip install livekit-plugins-openai
pip install livekit-plugins-deepgram
pip install livekit-plugins-silero
```

---

## 6. Running the Agent

### 6.1 Development Mode

```bash
# Run with auto-reload
python agent.py dev

# Or using the CLI directly
livekit-agents dev agent.py
```

### 6.2 Production Mode

```bash
# Start worker
python agent.py start

# With custom options
python agent.py start --port 8080 --host 0.0.0.0
```

### 6.3 Testing Locally

```python
# In your code, add console mode testing
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "console":
        # Test in console mode without LiveKit server
        from livekit.agents import cli
        cli.run_app(server, devmode=True)
    else:
        cli.run_app(server)
```

---

## 7. Complete Mock Interview Agent Example

```python
"""
Mock Interview Agent - Complete Working Example
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Annotated
from dotenv import load_dotenv
from pydantic import Field

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    RunContext,
    cli,
    function_tool,
)
from livekit.plugins import openai, deepgram, silero

load_dotenv()
logger = logging.getLogger("mock-interview")

# ============= Data Models =============

@dataclass
class InterviewState:
    candidate_name: str = ""
    position: str = ""
    current_question_idx: int = 0
    responses: dict[int, str] = None
    evaluation_notes: list[str] = None

    def __post_init__(self):
        if self.responses is None:
            self.responses = {}
        if self.evaluation_notes is None:
            self.evaluation_notes = []

# ============= Agent Definition =============

class MockInterviewAgent(Agent):
    def __init__(self):
        self.questions = [
            "Tell me about yourself and your experience.",
            "What interests you about this position?",
            "Describe a challenging technical problem you solved.",
            "Where do you see yourself in 5 years?",
        ]

        instructions = f"""
        You are an expert technical interviewer conducting a mock interview.

        Interview Structure:
        - Greet the candidate warmly and introduce yourself
        - Ask questions one at a time from the provided list
        - Listen carefully to each response
        - Provide brief, constructive feedback after each answer
        - Move to the next question naturally

        Communication Style:
        - Be professional yet friendly
        - Speak clearly and at a moderate pace
        - Give the candidate time to think
        - Ask clarifying questions if needed

        Available questions: {len(self.questions)}
        Current question will be tracked automatically.
        """

        super().__init__(
            instructions=instructions,
            tools=[
                self.record_response,
                self.get_next_question,
                self.provide_feedback,
                self.end_interview,
            ],
        )

    @function_tool
    async def record_response(
        self,
        ctx: RunContext[InterviewState],
        question_index: Annotated[int, Field(description="Index of the question being answered (0-based)")],
        response_summary: Annotated[str, Field(description="Brief summary of candidate's response")],
    ) -> str:
        """Record the candidate's response to a specific question."""
        ctx.userdata.responses[question_index] = response_summary
        logger.info(f"Recorded response for question {question_index}")
        return f"Response recorded for question {question_index + 1}"

    @function_tool
    async def get_next_question(
        self,
        ctx: RunContext[InterviewState],
    ) -> str:
        """Get the next interview question to ask."""
        idx = ctx.userdata.current_question_idx

        if idx >= len(self.questions):
            return "All questions have been asked. Consider wrapping up the interview."

        question = self.questions[idx]
        ctx.userdata.current_question_idx += 1

        return f"Question {idx + 1}: {question}"

    @function_tool
    async def provide_feedback(
        self,
        ctx: RunContext[InterviewState],
        feedback: Annotated[str, Field(description="Constructive feedback on the response")],
    ) -> str:
        """Provide feedback on the candidate's answer."""
        ctx.userdata.evaluation_notes.append(feedback)
        return "Feedback recorded and can be shared with candidate"

    @function_tool
    async def end_interview(
        self,
        ctx: RunContext[InterviewState],
    ) -> str:
        """End the interview session."""
        ctx.disallow_interruptions()

        summary = f"""
        Interview Complete:
        - Candidate: {ctx.userdata.candidate_name or 'Anonymous'}
        - Position: {ctx.userdata.position or 'Not specified'}
        - Questions Answered: {len(ctx.userdata.responses)}/{len(self.questions)}
        """

        logger.info(summary)
        return "Interview session ended. Thank you for participating!"

    async def on_enter(self):
        """Called when agent becomes active"""
        logger.info("Interview agent activated")

    async def on_exit(self):
        """Called when agent is deactivated"""
        logger.info("Interview agent deactivated")

# ============= Server Setup =============

server = AgentServer()

@server.rtc_session()
async def interview_entrypoint(ctx: JobContext):
    """Main entry point for the interview agent"""
    await ctx.connect()
    logger.info(f"Connected to room: {ctx.room.name}")

    # Initialize interview state
    interview_state = InterviewState(
        position="Software Engineer"
    )

    # Create agent session
    session = AgentSession[InterviewState](
        userdata=interview_state,

        # Voice pipeline components
        stt=deepgram.STT(
            model="nova-3",
            language="en-US",
            smart_format=True,
        ),
        llm=openai.LLM(
            model="gpt-4o",
            temperature=0.7,
            parallel_tool_calls=False,
        ),
        tts=openai.TTS(
            voice="alloy",
            speed=1.0,
        ),
        vad=silero.VAD.load(),

        # Behavior settings
        allow_interruptions=True,
        min_endpointing_delay=0.8,  # Wait a bit longer for interview responses
        max_endpointing_delay=4.0,  # Give time to think
        max_tool_steps=5,  # Allow multiple tool calls per turn
    )

    # Event handlers
    @session.on("user_input_transcribed")
    def on_transcript(event):
        if event.is_final:
            logger.info(f"Candidate: {event.transcript}")

    @session.on("agent_state_changed")
    def on_state_change(event):
        logger.info(f"Agent state: {event.old_state} -> {event.new_state}")

    # Start the session
    agent = MockInterviewAgent()
    await session.start(agent=agent, room=ctx.room)

# ============= Main =============

if __name__ == "__main__":
    cli.run_app(server)
```

### Running this agent:

```bash
# Install dependencies
pip install livekit-agents[openai,deepgram,silero] python-dotenv

# Set environment variables in .env
# LIVEKIT_URL=...
# LIVEKIT_API_KEY=...
# LIVEKIT_API_SECRET=...
# OPENAI_API_KEY=...
# DEEPGRAM_API_KEY=...

# Run in development mode
python mock_interview_agent.py dev

# Run in production
python mock_interview_agent.py start
```

---

## 8. Key Patterns Summary

### ✅ DO's:
1. **Always** use `await ctx.connect()` before creating AgentSession
2. **Use** `@function_tool` decorator for LLM-callable functions
3. **Pass** `RunContext[YourDataType]` to tools for type safety
4. **Register** event handlers before calling `session.start()`
5. **Use** `ctx.disallow_interruptions()` for critical operations
6. **Load** VAD with `silero.VAD.load()` (singleton pattern)
7. **Set** `parallel_tool_calls=False` for sequential tool execution
8. **Use** `load_dotenv()` for environment configuration

### ❌ DON'Ts:
1. **Don't** call `session.start()` before `ctx.connect()`
2. **Don't** forget to make tools async
3. **Don't** block the event loop in tool functions
4. **Don't** store mutable state in Agent class (use userdata)
5. **Don't** use print() - use proper logging
6. **Don't** forget error handling in tools (raise ToolError)

---

## 9. Debugging & Troubleshooting

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or per-module
logging.getLogger("livekit").setLevel(logging.DEBUG)
```

### Common Issues

1. **"No STT/LLM/TTS found"**: Specify in AgentSession or Agent
2. **"VAD required"**: Add `vad=silero.VAD.load()` if STT doesn't support streaming
3. **Tools not being called**: Check tool descriptions, set `parallel_tool_calls=False`
4. **Connection errors**: Verify LIVEKIT_URL, API_KEY, API_SECRET

---

## 10. Next Steps

You now have everything needed to build a voice-based mock interview agent:

1. ✅ Understanding of JobContext and room connection
2. ✅ AgentServer setup and registration
3. ✅ AgentSession configuration
4. ✅ Agent class with custom logic
5. ✅ Function tools with RunContext
6. ✅ Event handling patterns
7. ✅ Plugin integration (OpenAI, Deepgram, Silero)
8. ✅ Complete working example

**Recommended Approach**:
1. Start with the minimal example
2. Add your custom Agent class with interview instructions
3. Implement function tools for interview flow
4. Add event handlers for logging/analytics
5. Test locally in dev mode
6. Deploy to production

---

## File References

- Core Job: [job.py:132-837](e:\MockFlow-AI\agents\livekit-agents\livekit\agents\job.py#L132-L837)
- Worker: [worker.py:253-463](e:\MockFlow-AI\agents\livekit-agents\livekit\agents\worker.py#L253-L463)
- Voice Agent: [agent.py:40-842](e:\MockFlow-AI\agents\livekit-agents\livekit\agents\voice\agent.py#L40-L842)
- Agent Session: [agent_session.py:135-300](e:\MockFlow-AI\agents\livekit-agents\livekit\agents\voice\agent_session.py#L135-L300)
- Events: [events.py:84-243](e:\MockFlow-AI\agents\livekit-agents\livekit\agents\voice\events.py#L84-L243)
- Examples: [drive-thru/agent.py](e:\MockFlow-AI\agents\examples\drive-thru\agent.py), [frontdesk/frontdesk_agent.py](e:\MockFlow-AI\agents\examples\frontdesk\frontdesk_agent.py)

---

**End of Analysis Document**
