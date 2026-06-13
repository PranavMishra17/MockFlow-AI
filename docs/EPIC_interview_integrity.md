# Wing B — Interview Integrity (coding track)

The coding track's core weakness (audit §8): problems are **LLM-invented per session,
unvetted** (can be unsolvable/ambiguous), and "evaluation" is **LLM-only — the code is
never executed**, so there's no ground truth. This wing fixes both.

## Done (this branch — `coding/` package + tests)

- **Vetted problem bank** (`coding/problem_bank.py`): 6 curated problems across
  easy/medium/hard, keeping the exact shape the agent + frontend already consume
  (title/description/examples/constraints/difficulty/time_limit/hints) and adding
  `entrypoint`, `starter_code`, `test_cases`, and a `reference_solution`.
- **Deterministic selector** (`select_problems(difficulty|level, count, exclude)`),
  plus `difficulty_for_level` mirroring the agent's prior mapping.
- **Sandboxed test runner** (`coding/code_runner.py` + `_exec_driver.py`): runs code
  against a problem's test cases in a separate process with a wall-clock timeout;
  returns objective `passed/total` + per-case results; detects timeouts, missing
  entrypoints, and candidate exceptions.
- **Integrity tests** (`tests/test_problem_bank.py`, 22 tests): the headline test
  **executes every reference solution against its own test cases** — proving the bank
  is solvable and correctly specified. Plus runner behavior (wrong answer flagged,
  timeout, missing entrypoint, exceptions) and selector tests.

## Next (needs your decision before wiring to live candidate code)

1. **Wire the bank into the agent** (`agent_worker.py` coding stage): replace the
   LLM problem-generation call with `select_problems(level=..., count=active_problem_count)`.
   Low risk — same problem shape, drop-in. This alone removes unsolvable-problem risk.
2. **Ground evaluation with real results**: on `code_submitted`, run the candidate's
   code against the problem's `test_cases` and feed the objective pass/fail into the
   evaluator so feedback reflects what actually ran (LLM then judges *approach* on top).

### THE DECISION — how to safely execute UNTRUSTED candidate code

The current `code_runner` isolates by process + timeout only. That's safe for the
bank's own **trusted** reference solutions (CI), but NOT sufficient for arbitrary
candidate code in production (no network/filesystem restriction). Options:

| Option | What | Pros | Cons |
|--------|------|------|------|
| **A. Hosted runner (Piston)** | POST code to a free/self-hostable execution API (Piston by engineer-man, or Judge0) | Real isolation off our box; multi-language; minimal/no cost (public Piston is free, rate-limited) | External network call; dependency on a third party (self-host to remove) |
| **B. Subprocess + OS limits** | Keep `code_runner`, add `RLIMIT_CPU/AS`, drop network via namespaces/seccomp on Render's Linux | No external dep | Arbitrary code on the app instance; proper isolation (no-network, fs) is hard to get right; risky |
| **C. Hybrid grounding only** | Don't execute untrusted code; keep LLM eval but require it to reason against the vetted reference + visible test cases | No code execution risk at all | Still not true ground truth |

**Recommendation: A (Piston)** — best isolation for least risk, language-agnostic,
and the vetted bank already provides the test cases. The LLM stays, but judges
*approach/quality* on top of objective test results. Self-host Piston later if the
public instance's rate limits bite.

Until a decision is made, `code_runner` is used ONLY for the trusted bank self-test.
It is not pointed at candidate submissions.
