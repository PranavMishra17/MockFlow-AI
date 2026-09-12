"""
Agent behaviour audit: run Flow against mocked candidates on every track,
then run the real verdict pipeline on what was said, and write it all down.

This is an OBSERVATION tool, not a test. It composes the text harness (the
production InterviewAgent / FSM / AgentSession with voice I/O removed), plays
a set of candidate personas against it with an LLM writing the candidate's
lines, and records: every turn with the stage it happened in and how long
Flow took to answer, every stage change and tool call, the generated question
bank, the interview row that would be saved, and the hiring verdict the
feedback page would show. Heuristic flags are appended so the reader has
somewhere to start, but the point is the transcripts.

Level B (docs/TESTING_E2E.md): needs OPENAI_API_KEY. One run is one short
interview's worth of tokens; the full matrix (4 tracks x 5 personas) is ~20.

    python tests/e2e/agent_audit.py                       # full matrix
    python tests/e2e/agent_audit.py --track behavioral    # one track
    python tests/e2e/agent_audit.py --persona ken_terse   # one persona
    python tests/e2e/agent_audit.py --out docs/audit/agent-2026-09

Output: <out>/<track>__<persona>.md (human) and .json (machine), plus
<out>/INDEX.md summarising every run. The ledger of judgements is written by
a human (or an AI reading the .md files), not by this script.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")
logging.basicConfig(level=logging.WARNING)
logging.getLogger("interview-runtime").setLevel(logging.WARNING)

CANDIDATE_MODEL = "gpt-4o-mini"
MAX_TURNS = 16
STALL_TURNS = 6   # candidate turns in one stage before we do what a real user does: press skip
SECONDS_PER_EXCHANGE = 30  # the harness clock is fake; age it so Flow sees realistic time-in-stage

# ---------------------------------------------------------------------------
# Personas: the mocked user profiles
# ---------------------------------------------------------------------------

@dataclass
class Persona:
    key: str
    name: str
    role: str
    level: str
    bio: str
    style: str
    # turn index -> an instruction that overrides the style for that one turn.
    moves: dict = field(default_factory=dict)
    code_quality: str = "correct"   # correct | buggy | partial
    config_extra: dict = field(default_factory=dict)


PERSONAS: dict[str, Persona] = {
    "priya_senior": Persona(
        key="priya_senior", name="Priya Raman", role="Senior Backend Engineer", level="senior",
        bio=("8 years in backend engineering. Currently tech lead for a payments platform at a fintech "
             "(Go, Postgres, Kafka, AWS). Led a migration from a monolith to services that cut p99 latency "
             "40%. Mentors two juniors. Previously at a logistics startup that got acquired."),
        style=("Confident and structured. Answers behavioural questions in STAR form without being asked. "
               "Uses concrete numbers. 60-120 words per answer. Asks one sharp clarifying question if a "
               "question is vague. Never rambles."),
        moves={5: "End your answer with a genuine question back to the interviewer about the team or role."},
        config_extra={"topics": "distributed systems,databases,caching"},
    ),
    "marcus_junior": Persona(
        key="marcus_junior", name="Marcus Lee", role="Software Engineer", level="junior",
        bio=("New grad, CS degree, one 10-week internship at a small startup building a React dashboard. "
             "Two class projects: a Flask todo app and a group project on a chess engine in Python. "
             "No production experience. Knows Python and some JavaScript."),
        style=("Nervous and hedging. Uses filler ('um', 'like', 'I guess', 'sort of'). 25-60 words. Generic "
               "answers with no metrics, sometimes repeats the question back. Occasionally honest about not "
               "knowing something. Speaks like a transcript of speech, not written prose."),
        moves={2: "Say you didn't quite understand the question and ask them to rephrase it.",
               6: "Admit you have never done this and ask if you can talk about a class project instead."},
        code_quality="buggy",
        config_extra={"topics": "data structures,REST APIs"},
    ),
    "dana_rambler": Persona(
        key="dana_rambler", name="Dana Whitfield", role="Full Stack Engineer", level="mid",
        bio=("4 years. Started as a product analyst, moved into engineering. Works on a healthcare "
             "scheduling app (TypeScript, React, Node, Postgres). Proud of a redesign of the booking flow. "
             "Has strong opinions about process and tends to tell the whole backstory."),
        style=("Warm, talkative, tangential. 150-250 words per answer. Starts with context and backstory, "
               "drifts to a related anecdote, often never states the outcome unless pushed. Says 'so, "
               "basically' and 'long story short' (and then it isn't short)."),
        moves={4: "Go on a tangent about a completely different project and forget to answer the question."},
        code_quality="partial",
        config_extra={"topics": "frontend performance,APIs"},
    ),
    "ken_terse": Persona(
        key="ken_terse", name="Ken Okafor", role="Software Engineer", level="mid",
        bio=("5 years. Backend, Java and Spring, at a large insurance company. Competent but disengaged; "
             "doing this interview because his manager suggested it. Has real experience (built a claims "
             "batch pipeline) but does not volunteer it."),
        style=("Terse and low-energy. 3-15 words. 'Yeah.' 'Not really.' 'It was fine.' Only gives detail "
               "when asked a direct, specific follow-up, and even then briefly. Never asks questions."),
        moves={3: "Answer with just: 'Not sure. Next question?'",
               7: "Give one detailed, specific answer for once - 80 words with a real number in it."},
        code_quality="correct",
        config_extra={"topics": "concurrency,databases"},
    ),
    "sam_curveball": Persona(
        key="sam_curveball", name="Sam Ortiz", role="Backend Engineer", level="mid",
        bio=("6 years. Python/Django and some Rust, at two mid-size SaaS companies. Solid engineer who "
             "treats the interview as a two-way conversation and probes how the interviewer handles "
             "the unexpected."),
        style=("Direct and a little playful. 40-100 words. Competent answers, but tests the interviewer: "
               "asks what they meant, asks for feedback, pushes back when a question is generic."),
        moves={1: "Before answering, ask the interviewer to repeat the question because you missed the end of it.",
               3: "Ask the interviewer for feedback on your previous answer before continuing.",
               5: "Say 'sorry, my dog is barking, one second' and then answer normally.",
               6: "Push back: say the question is generic and ask for a more specific one.",
               8: "Say honestly that you don't know, and ask what a strong answer would look like."},
        code_quality="correct",
        config_extra={"topics": "APIs,security"},
    ),
}

TRACK_CONFIG = {
    "intro": {},
    "behavioral": {"framework": "amazon", "depth": "medium"},
    "technical_voice": {},   # topics come from the persona
    "coding": {"preferred_language": "python", "problem_count": "2"},
}

# ---------------------------------------------------------------------------
# The simulated candidate
# ---------------------------------------------------------------------------

def _client():
    from openai import OpenAI
    return OpenAI()


def candidate_reply(client, persona: Persona, track: str, history: list[dict], turn: int) -> str:
    move = persona.moves.get(turn)
    system = (
        f"You are {persona.name}, a candidate in a mock {track.replace('_', ' ')} interview for a "
        f"{persona.role} role. This is a VOICE interview: reply as spoken words only, no markdown, no "
        f"lists, no stage directions.\n\nBackground: {persona.bio}\n\nHow you talk: {persona.style}\n\n"
        "Stay in character. Answer what the interviewer actually asked. Never break the fourth wall or "
        "mention being simulated."
        + (f"\n\nFOR THIS TURN ONLY: {move}" if move else "")
    )
    msgs = [{"role": "system", "content": system}]
    for h in history[-12:]:
        msgs.append({"role": "assistant" if h["who"] == "candidate" else "user", "content": h["text"]})
    r = client.chat.completions.create(model=CANDIDATE_MODEL, messages=msgs, temperature=0.9, max_tokens=400)
    return (r.choices[0].message.content or "").strip()


def candidate_code(client, persona: Persona, problem: dict) -> str:
    quality = {
        "correct": "Write a correct, idiomatic solution.",
        "buggy": "Write a plausible attempt that has one real bug (an off-by-one or a missed edge case). Do not comment on the bug.",
        "partial": "Write a solution that handles the main case but ignores one of the stated constraints.",
    }[persona.code_quality]
    prompt = (f"{quality}\nLanguage: Python. Return ONLY the code, no fences, no prose.\n\nProblem:\n"
              f"{problem.get('title', '')}\n{problem.get('description', '')}\n"
              f"Function signature / starter code, if any:\n{problem.get('starter_code', '') or problem.get('function_signature', '')}")
    r = client.chat.completions.create(model=CANDIDATE_MODEL, messages=[{"role": "user", "content": prompt}],
                                       temperature=0.4, max_tokens=700)
    code = (r.choices[0].message.content or "").strip()
    return re.sub(r"^```[a-z]*\n|\n```$", "", code)


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def next_stage_after(sess, current: str) -> str | None:
    order = [s.value for s in sess.state.get_active_stages()]
    if current in order and order.index(current) + 1 < len(order):
        return order[order.index(current) + 1]
    return None


async def run_one(track: str, persona: Persona, out_dir: Path, client) -> dict:
    from livekit.plugins import openai as lk_openai
    from harness import start_interview

    config = {"track": track, "role": persona.role, "level": persona.level, "user_id": "audit-user",
              **TRACK_CONFIG[track], **persona.config_extra}
    if track != "technical_voice":
        config.pop("topics", None)

    llm = lk_openai.LLM(model="gpt-4o-mini", temperature=0.7)
    t_start = time.time()
    sess = await start_interview(config, llm=llm, candidate_name=persona.name)
    await sess.settle()

    history: list[dict] = []      # {who, text, stage, t, latency}
    seen_agent = 0
    seen_events = 0
    stage_turns: dict[str, int] = {}
    stalls: list[str] = []
    solved_problems: set[int] = set()
    notes: list[str] = []

    def drain_agent(latency=None):
        nonlocal seen_agent
        agent = sess.handles.conversation["agent"]
        for m in agent[seen_agent:]:
            history.append({"who": "flow", "text": m["text"], "stage": m.get("stage"), "t": round(time.time() - t_start, 1),
                            "latency": latency})
            latency = None
        seen_agent = len(agent)

    def drain_events():
        nonlocal seen_events
        evs = sess.transport.events[seen_events:]
        seen_events = len(sess.transport.events)
        return evs

    drain_agent()
    drain_events()

    async def handle_coding_events(evs):
        for e in evs:
            if e.get("type") == "coding_problem" and e.get("problem"):
                idx = e.get("problem_index", 0)
                if idx in solved_problems:
                    continue
                solved_problems.add(idx)
                prob = e["problem"]
                history.append({"who": "system", "text": f"[coding_problem pushed: {prob.get('title')}]", "stage": sess.stage,
                                "t": round(time.time() - t_start, 1)})
                code = candidate_code(client, persona, prob)
                think = candidate_reply(client, persona, track, history + [
                    {"who": "flow", "text": f"Here is your problem: {prob.get('title')}. {prob.get('description', '')[:400]} Talk me through your approach."}], 99)
                t0 = time.time()
                await sess.say(think)
                history.append({"who": "candidate", "text": think, "stage": sess.stage, "t": round(t0 - t_start, 1)})
                drain_agent(round(time.time() - t0, 1))
                await sess.command({"type": "code_submitted", "code": code, "language": "python", "problem_index": idx})
                history.append({"who": "system", "text": f"[code_submitted problem {idx}, {len(code.splitlines())} lines]\n{code}",
                                "stage": sess.stage, "t": round(time.time() - t_start, 1)})
                for _ in range(60):   # wait for evaluation_result
                    await asyncio.sleep(0.5)
                    if any(x.get("type") == "evaluation_result" and x.get("problem_index", idx) == idx
                           for x in sess.transport.events[seen_events:]):
                        break
                await sess.settle(timeout=20)
                drain_agent()
                for x in drain_events():
                    if x.get("type") == "evaluation_result":
                        ev = x.get("evaluation") or {}
                        history.append({"who": "system", "text": "[evaluation_result] " + json.dumps(ev)[:600],
                                        "stage": sess.stage, "t": round(time.time() - t_start, 1)})

    if track == "coding":
        await sess.command({"type": "ready_for_problem"})
        await sess.settle(timeout=20)
        drain_agent()
        await handle_coding_events(drain_events())

    for turn in range(MAX_TURNS):
        stage = sess.stage
        if stage == "closing" and any("luck" in h["text"].lower() for h in history[-2:] if h["who"] == "flow"):
            notes.append(f"closing delivered by Flow at turn {turn}")
            break
        reply = candidate_reply(client, persona, track, history, turn)
        t0 = time.time()
        try:
            await sess.say(reply)
        except Exception as e:
            notes.append(f"turn {turn}: say() raised {type(e).__name__}: {e}")
            break
        latency = round(time.time() - t0, 1)
        sess.advance(SECONDS_PER_EXCHANGE)
        history.append({"who": "candidate", "text": reply, "stage": stage, "t": round(t0 - t_start, 1)})
        drain_agent(latency)
        evs = drain_events()
        for e in evs:
            if e.get("type") == "stage_change":
                history.append({"who": "system", "text": f"[stage_change -> {e.get('stage')}]", "stage": e.get("stage"),
                                "t": round(time.time() - t_start, 1)})
        if track == "coding":
            await handle_coding_events(evs)
            if sess.stage.startswith("coding_problem") and not solved_problems:
                await sess.command({"type": "ready_for_problem"})
                await sess.settle(timeout=20)
                drain_agent()
                await handle_coding_events(drain_events())

        stage_turns[sess.stage] = stage_turns.get(sess.stage, 0) + 1
        if stage_turns[sess.stage] >= STALL_TURNS and sess.stage != "closing":
            nxt = next_stage_after(sess, sess.stage)
            if nxt:
                stalls.append(f"turn {turn}: {STALL_TURNS} candidate turns in '{sess.stage}' with no transition; skipped to '{nxt}'")
                history.append({"who": "system", "text": f"[user pressed skip -> {nxt}]", "stage": nxt, "t": round(time.time() - t_start, 1)})
                await sess.command({"type": "skip_stage", "target_stage": nxt})
                await sess.settle(timeout=20)
                drain_agent()
                drain_events()
                stage_turns[sess.stage] = 0

    row = sess.interview_row()
    bank = sess.question_bank()
    tool_calls = list(sess.tool_calls)
    await sess.aclose()

    verdict = None
    try:
        verdict = run_verdict(client, row, track, persona)
    except Exception as e:
        notes.append(f"verdict failed: {type(e).__name__}: {e}")

    result = {
        "track": track, "persona": persona.key, "config": config, "duration_s": round(time.time() - t_start, 1),
        "history": history, "stages_visited": [h["stage"] for h in history if h["who"] == "system" and "stage_change" in h["text"]],
        "final_stage": row.get("stage") or row.get("final_stage"), "tool_calls": tool_calls,
        "question_bank": bank, "stalls": stalls, "notes": notes, "verdict": verdict,
        "flags": heuristic_flags(history, persona),
    }
    write_run(out_dir, result)
    return result


def run_verdict(client, row: dict, track: str, persona: Persona) -> dict:
    """Exactly what /api/feedback/verdict does, minus the database."""
    from evaluator import (build_evaluator_messages, build_rubric, finalize_verdict, infer_archetype,
                           infer_role, infer_seniority, pick_evaluator_model)
    from feedback_scoring import build_speech_summary
    from postprocess import merge_by_agent_turns
    from speech_analytics import analyze_transcript

    conv = row.get("conversation") or {}
    merged = merge_by_agent_turns(conv.get("agent", []), conv.get("user", []))
    lines = []
    for t in merged:
        who = "INTERVIEWER" if t["role"] == "agent" else "CANDIDATE"
        st = f" [{t['stage']}]" if t.get("stage") else ""
        lines.append(f"{who}{st}: {t['text']}")
    transcript = "\n\n".join(lines)
    role = infer_role(row.get("job_role"))
    seniority = infer_seniority(row.get("experience_level"))
    archetype = infer_archetype(row.get("job_role"))
    speech = analyze_transcript(conv)
    rubric = build_rubric(track, role, seniority, archetype)
    messages = build_evaluator_messages(
        rubric, candidate_profile=f"Name: {persona.name}\nExperience Level: {persona.level}",
        job_summary=f"Role: {persona.role}", transcript=transcript, speech_summary=build_speech_summary(speech))
    resp = client.chat.completions.create(model=pick_evaluator_model(), messages=messages, temperature=0,
                                          response_format={"type": "json_object"}, max_tokens=2200)
    raw = json.loads(resp.choices[0].message.content)
    v = finalize_verdict(raw, speech, weights=rubric.get("weighting"))
    v["context"] = {"track": track, "role": role, "seniority": seniority, "archetype": archetype}
    return v


# ---------------------------------------------------------------------------
# Heuristic flags: a starting point for the reader, not a judgement
# ---------------------------------------------------------------------------

SYCOPHANCY = re.compile(r"\b(great|awesome|fantastic|excellent|wonderful|amazing|impressive|love that|perfect)\b", re.I)
META = re.compile(r"\b(stage|transition|tool|prompt|as an ai|language model|self-introduction stage|move to the)\b", re.I)


def heuristic_flags(history: list[dict], persona: Persona) -> list[str]:
    flags = []
    flow = [h for h in history if h["who"] == "flow"]
    cand = [h for h in history if h["who"] == "candidate"]
    if not flow:
        return ["Flow never spoke"]
    long_turns = [h for h in flow if len(h["text"].split()) > 90]
    if long_turns:
        flags.append(f"{len(long_turns)}/{len(flow)} Flow turns over 90 words (voice: too long) — longest {max(len(h['text'].split()) for h in flow)} words")
    multi_q = [h for h in flow if h["text"].count("?") >= 2]
    if len(multi_q) >= 2:
        flags.append(f"{len(multi_q)} Flow turns ask 2+ questions at once")
    syc = sum(len(SYCOPHANCY.findall(h["text"])) for h in flow)
    if syc >= max(3, len(flow) // 2):
        flags.append(f"{syc} praise words across {len(flow)} Flow turns (sycophancy)")
    first = persona.name.split()[0]
    names = sum(h["text"].count(first) for h in flow)
    if names > len(flow) * 0.6:
        flags.append(f"uses the candidate's first name {names} times in {len(flow)} turns")
    meta = [h["text"][:80] for h in flow if META.search(h["text"])]
    if meta:
        flags.append(f"possible meta/stage leakage in {len(meta)} turns, e.g. {meta[0]!r}")
    lat = [h["latency"] for h in flow if h.get("latency")]
    if lat:
        flags.append(f"reply latency: median {sorted(lat)[len(lat)//2]}s, max {max(lat)}s (text-only; TTS adds more)")
    # Candidate asked a question; did the next Flow turn engage with it?
    unanswered = 0
    for i, h in enumerate(history):
        if h["who"] == "candidate" and h["text"].rstrip().endswith("?"):
            nxt = next((x for x in history[i + 1:] if x["who"] == "flow"), None)
            if nxt and "?" in nxt["text"] and len(nxt["text"].split()) < 25:
                unanswered += 1
    if unanswered:
        flags.append(f"{unanswered} candidate question(s) answered with an immediate counter-question")
    openers = [h["text"].split(",")[0].split("!")[0].strip().lower() for h in flow]
    dup = {o for o in openers if openers.count(o) >= 3 and len(o) > 3}
    if dup:
        flags.append(f"repeated openers: {sorted(dup)}")
    return flags


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_run(out_dir: Path, r: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"{r['track']}__{r['persona']}"
    base.with_suffix(".json").write_text(json.dumps(r, indent=2, default=str), encoding="utf-8")
    md = [f"# {r['track']} — {r['persona']}", "",
          f"config: `{json.dumps(r['config'])}`  ", f"duration: {r['duration_s']}s · final stage: `{r['final_stage']}` · "
          f"tool calls: {r['tool_calls']}", ""]
    if r["question_bank"]:
        md += ["## Generated question bank", ""] + [f"- {json.dumps(q, default=str)[:300]}" for q in r["question_bank"]] + [""]
    else:
        md += ["## Generated question bank", "", "_(empty)_", ""]
    md += ["## Transcript", ""]
    for h in r["history"]:
        tag = {"flow": "**FLOW**", "candidate": f"**{r['persona'].split('_')[0].upper()}**", "system": "_system_"}[h["who"]]
        lat = f" _({h['latency']}s)_" if h.get("latency") else ""
        md.append(f"`{h['t']:>6}s` `{h.get('stage')}` {tag}{lat}: {h['text']}")
        md.append("")
    md += ["## Stalls (user had to press skip)", ""] + ([f"- {s}" for s in r["stalls"]] or ["- none"]) + [""]
    md += ["## Heuristic flags", ""] + ([f"- {f}" for f in r["flags"]] or ["- none"]) + [""]
    md += ["## Notes", ""] + ([f"- {n}" for n in r["notes"]] or ["- none"]) + [""]
    v = r.get("verdict")
    md += ["## Verdict (what the feedback page would show)", ""]
    if v:
        ov = v.get("overall") or {}
        md.append(f"**recommendation:** {ov.get('recommendation')} · **level read:** {ov.get('level_read')} · "
                  f"**confidence:** {ov.get('confidence')}  ")
        md.append(f"**headline:** {ov.get('headline') or ''}")
        md.append("")
        for s_ in v.get("signals", []):
            md.append(f"- **{s_.get('name')}** → {s_.get('band')} (scope {s_.get('scope_met')}): {str(s_.get('reasoning') or '')[:260]}")
            for q in (s_.get("evidence") or [])[:2]:
                md.append(f"  > {str(q)[:200]}")
            if s_.get("to_raise"):
                md.append(f"  _to raise:_ {str(s_['to_raise'])[:200]}")
        if v.get("differentiators"):
            md.append("")
            md.append("**differentiators:** " + "; ".join(str(d) for d in v["differentiators"])[:500])
        if v.get("gap_to_next"):
            md.append(f"**gap to next:** {json.dumps(v['gap_to_next'], default=str)[:400]}")
        if v.get("delivery"):
            md.append(f"**delivery:** {json.dumps(v['delivery'], default=str)[:400]}")
    else:
        md.append("_(verdict failed — see notes)_")
    base.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")


def write_index(out_dir: Path, results: list[dict]) -> None:
    rows = ["# Agent audit runs", "", "| track | persona | turns | final stage | stalls | recommendation | flags |", "|---|---|---|---|---|---|---|"]
    for r in results:
        turns = sum(1 for h in r["history"] if h["who"] == "candidate")
        rec = ((r.get("verdict") or {}).get("overall") or {}).get("recommendation", "—")
        rows.append(f"| {r['track']} | {r['persona']} | {turns} | {r['final_stage']} | {len(r['stalls'])} | {rec} | "
                    f"{len(r['flags'])} — [{r['track']}__{r['persona']}.md]({r['track']}__{r['persona']}.md) |")
    (out_dir / "INDEX.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


async def main_async(args) -> int:
    client = _client()
    tracks = [args.track] if args.track else list(TRACK_CONFIG)
    personas = [PERSONAS[args.persona]] if args.persona else list(PERSONAS.values())
    out = Path(args.out)
    results = []
    for track in tracks:
        for p in personas:
            print(f"=== {track} / {p.key}", flush=True)
            try:
                r = await run_one(track, p, out, client)
                print(f"    {sum(1 for h in r['history'] if h['who']=='candidate')} turns, final {r['final_stage']}, "
                      f"stalls {len(r['stalls'])}, verdict {((r.get('verdict') or {}).get('overall') or {}).get('recommendation')}", flush=True)
                results.append(r)
            except Exception as e:
                print(f"    RUN FAILED: {type(e).__name__}: {e}", flush=True)
                results.append({"track": track, "persona": p.key, "history": [], "final_stage": f"CRASH {type(e).__name__}",
                                "stalls": [], "flags": [str(e)], "verdict": None})
    # Merge with any earlier runs already in the folder so partial matrices still index.
    existing = {}
    for j in out.glob("*__*.json"):
        try:
            d = json.loads(j.read_text(encoding="utf-8"))
            existing[(d["track"], d["persona"])] = d
        except Exception:
            pass
    for r in results:
        existing[(r["track"], r["persona"])] = r
    write_index(out, sorted(existing.values(), key=lambda d: (d["track"], d["persona"])))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--track", choices=list(TRACK_CONFIG))
    p.add_argument("--persona", choices=list(PERSONAS))
    p.add_argument("--out", default=str(REPO / "docs" / "audit" / "agent-2026-09"))
    args = p.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY missing", file=sys.stderr)
        return 2
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
