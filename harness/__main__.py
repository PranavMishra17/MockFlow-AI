"""
CLI:

    python -m harness run  scenarios/intro_happy_path.json
    python -m harness play scenarios/intro_happy_path.json

`run` executes a scripted scenario and checks its expectations.
`play` drops you into a REPL where you type as the candidate; slash commands
map onto the same handlers the browser's data channel reaches.

Scenarios are JSON, not YAML: pyyaml is not a dependency of this project and a
dev tool is not a reason to add one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Import the app modules from the repo root regardless of where this is run.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.runtime import FakeClock, start_interview  # noqa: E402

logger = logging.getLogger("harness")


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    except ImportError:
        pass


def _build_llm(kind: str):
    if kind == 'openai':
        _load_env()
        if not os.getenv('OPENAI_API_KEY'):
            raise SystemExit(
                "OPENAI_API_KEY is not set. Put it in .env or the environment, "
                "or run with --llm cassette once cassettes exist."
            )
        from livekit.plugins import openai
        return openai.LLM(model='gpt-4o-mini', temperature=0.7)
    raise SystemExit(f"Unknown --llm {kind!r}. Only 'openai' is implemented so far.")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

class ExpectationFailed(AssertionError):
    pass


def _check(expect: dict, sess, step_no: int) -> list:
    """Evaluate one expect block. Returns the list of checks that passed."""
    passed = []
    for key, want in expect.items():
        if key == 'stage':
            got = sess.stage
            if got != want:
                raise ExpectationFailed(
                    f"step {step_no}: expected stage {want!r}, got {got!r}")
            passed.append(f"stage == {want}")
        elif key == 'tool_called':
            if want not in sess.tool_calls:
                raise ExpectationFailed(
                    f"step {step_no}: tool {want!r} was never called "
                    f"(called: {sorted(set(sess.tool_calls)) or 'none'})")
            passed.append(f"tool_called {want}")
        elif key == 'emitted':
            if not sess.emitted(want):
                types = sorted({e.get('type') for e in sess.transport.events})
                raise ExpectationFailed(
                    f"step {step_no}: nothing of type {want!r} was emitted "
                    f"(emitted: {types or 'none'})")
            passed.append(f"emitted {want}")
        elif key == 'user_turns':
            got = len(sess.transcript()['user'])
            if got != want:
                raise ExpectationFailed(
                    f"step {step_no}: expected {want} user turns, got {got}")
            passed.append(f"user_turns == {want}")
        elif key == 'questions_generated':
            got = len(sess.question_bank())
            if got < want:
                raise ExpectationFailed(
                    f"step {step_no}: expected at least {want} generated question(s), got {got}. "
                    f"An empty bank means the track fell back to improvising.")
            passed.append(f"questions_generated >= {want} (got {got})")
        elif key == 'question_bank_contains':
            if want.lower() not in sess.question_bank_text():
                raise ExpectationFailed(
                    f"step {step_no}: {want!r} is not in the generated question bank")
            passed.append(f"question_bank_contains {want!r}")
        elif key == 'agent_said':
            joined = ' '.join(t['text'].lower() for t in sess.transcript()['agent'])
            if want.lower() not in joined:
                raise ExpectationFailed(
                    f"step {step_no}: agent never said anything containing {want!r}")
            passed.append(f"agent_said {want!r}")
        else:
            raise ExpectationFailed(f"step {step_no}: unknown expectation {key!r}")
    return passed


async def _run_scenario(path: Path, llm_kind: str, verbose: bool) -> int:
    scenario = json.loads(path.read_text(encoding='utf-8'))
    name = scenario.get('name', path.stem)
    print(f"\n=== {name} ===")

    llm = _build_llm(llm_kind)
    sess = await start_interview(
        scenario['config'],
        llm=llm,
        candidate_name=scenario.get('candidate_name', 'Ada Lovelace'),
        clock=FakeClock(),
    )

    failures = 0
    try:
        await sess.settle()
        print(f"  start   stage={sess.stage} "
              f"startup_tools={sorted(set(sess.tool_calls)) or 'none'}")
        for i, step in enumerate(scenario.get('script', []), 1):
            try:
                if 'say' in step:
                    await sess.say(step['say'])
                    print(f"  {i:>3} say     {step['say'][:60]!r} -> stage={sess.stage}")
                    if verbose:
                        agent_turns = sess.transcript()['agent']
                        if agent_turns:
                            print(f"        agent: {agent_turns[-1]['text'][:160]}")
                elif 'command' in step:
                    handled = await sess.command(step['command'])
                    print(f"  {i:>3} cmd     {step['command'].get('type')} "
                          f"handled={handled} -> stage={sess.stage}")
                elif 'clock' in step:
                    seconds = float(str(step['clock']).lstrip('+'))
                    sess.advance(seconds)
                    print(f"  {i:>3} clock   +{seconds:.0f}s")
                elif 'expect' in step:
                    for ok in _check(step['expect'], sess, i):
                        print(f"  {i:>3} ok      {ok}")
                else:
                    raise ExpectationFailed(f"step {i}: unrecognised step {step!r}")
            except ExpectationFailed as e:
                failures += 1
                print(f"  {i:>3} FAIL    {e}")

        row = sess.interview_row()
        print(f"  done    stage={sess.stage} "
              f"turns={row['total_messages']} skipped={row['skipped_stages']}")
    finally:
        await sess.aclose()

    print(f"  {'PASS' if not failures else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# play
# ---------------------------------------------------------------------------

HELP = """
  /skip-stage <name>  skip to a stage      /state       stage + counters
  /clock +<seconds>   age the current stage /transcript  what has been recorded
  /emitted            what the UI received  /row         the row that would be saved
  /quit               end the session
"""


async def _play(path: Path, llm_kind: str) -> int:
    scenario = json.loads(path.read_text(encoding='utf-8'))
    llm = _build_llm(llm_kind)
    sess = await start_interview(
        scenario['config'],
        llm=llm,
        candidate_name=scenario.get('candidate_name', 'Ada Lovelace'),
        clock=FakeClock(),
    )

    print(f"\nPlaying {scenario.get('name', path.stem)}. Type as the candidate.")
    print(HELP)

    def show_new_agent_turns(seen: int) -> int:
        turns = sess.transcript()['agent']
        for turn in turns[seen:]:
            print(f"\nINTERVIEWER: {turn['text']}\n")
        return len(turns)

    await sess.settle()
    seen = show_new_agent_turns(0)
    try:
        while True:
            try:
                line = input(f"[{sess.stage}] you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            if line in ('/quit', '/q'):
                break
            if line == '/state':
                print(f"  stage={sess.stage} asked={sess.state.questions_per_stage} "
                      f"skipped={sess.state.skipped_stages} "
                      f"time_in_stage={sess.state.time_in_current_stage():.0f}s")
                continue
            if line == '/transcript':
                for turn in sess.transcript()['user']:
                    print(f"  [{turn['stage']}] {turn['text'][:100]}")
                continue
            if line == '/emitted':
                for event in sess.transport.events:
                    print(f"  {event}")
                continue
            if line == '/row':
                print(json.dumps(sess.interview_row(), indent=2, default=str)[:2000])
                continue
            if line.startswith('/clock'):
                sess.advance(float(line.split()[-1].lstrip('+')))
                print(f"  clock advanced; time_in_stage={sess.state.time_in_current_stage():.0f}s")
                continue
            if line.startswith('/skip-stage'):
                await sess.command({'type': 'skip_stage', 'target_stage': line.split()[-1]})
                print(f"  stage={sess.stage}")
                seen = show_new_agent_turns(seen)
                continue
            if line.startswith('/'):
                print(HELP)
                continue

            await sess.say(line)
            seen = show_new_agent_turns(seen)
    finally:
        await sess.aclose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog='harness')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_run = sub.add_parser('run', help='execute a scripted scenario')
    p_run.add_argument('scenario', type=Path)
    p_run.add_argument('--llm', default='openai')
    p_run.add_argument('-v', '--verbose', action='store_true')

    p_play = sub.add_parser('play', help='type as the candidate')
    p_play.add_argument('scenario', type=Path)
    p_play.add_argument('--llm', default='openai')

    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format='[%(name)s] %(message)s')

    if args.cmd == 'run':
        return asyncio.run(_run_scenario(args.scenario, args.llm, args.verbose))
    return asyncio.run(_play(args.scenario, args.llm))


if __name__ == '__main__':
    raise SystemExit(main())
