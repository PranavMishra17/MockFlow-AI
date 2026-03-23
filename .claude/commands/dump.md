# /dump

Dump a full progress snapshot for session handoff. Writes a new file to `.claude/progress/` so the next agent session can resume with full context via `@.claude/progress/dumpN.md`.

## Instructions

1. Determine the next dump number by checking `.claude/progress/` — if `dump1.md`, `dump2.md` exist, write `dump3.md`. Create the folder if it doesn't exist. Start at `dump1.md` if empty.
2. Gather context by reviewing:
   - Any `tasks/todo.md` or similar task tracking files
   - Recent conversation history from this session
   - Current git status (`git status --short` and `git log --oneline -10`)
   - Any open error messages, failing tests, or blocked tasks from this session
3. Write the file at `.claude/progress/dumpN.md` using the format below.
4. After writing, print: "Dump complete — run `/clear` then start new session with: `@.claude/progress/dumpN.md`"

## Output File Format

```
# Session Dump — dumpN
Generated: <timestamp>
Project: <project name from CLAUDE.md or directory name>

---

## What Was Done This Session
- <Specific completed task with outcome>
- <Specific completed task with outcome>

## Current State
<One paragraph describing where the project is right now — what works, what doesn't>

## Active To-Do List
- [ ] <Task> — <why it's needed, any blockers>
- [ ] <Task> — <why it's needed, any blockers>
- [x] <Completed task> — done

## Remaining Work
<Ordered list of what still needs to happen to reach the goal, with rough priority>

1. <Next immediate task — most critical>
2. <Second task>
3. <Third task>

## Known Issues / Blockers
- <Issue or error that was encountered and its status>
- <Anything that caused confusion or needs investigation>

## Key Decisions Made
- <Decision> — <rationale>
- <Decision> — <rationale>

## Files Recently Modified
<output of git status --short or manual list if no git>

## Context for Next Agent
<Any assumptions, implicit knowledge, or gotchas the next agent needs to know that aren't obvious from the code>

## Last 10 Git Commits
<output of git log --oneline -10>
```

## Rules
- Be specific — "fixed bug in auth module" not "made some fixes"
- Include exact file paths where relevant
- If a task is blocked, say WHY and what information is needed to unblock it
- The "Context for Next Agent" section is the most important — write what you wish you had known at session start
