"""
Free-tier probe: proves a signed-in user with NO API keys gets their free
interviews on the owner's keys, that each one costs a credit, and that the
third is refused.

Level B (docs/TESTING_E2E.md): it runs the REAL app against the REAL database
and spawns a REAL agent_worker.py on the SYSTEM_* keys, so it needs the
repo-root .env with DATABASE_URL, ENCRYPTION_KEY, and either the five SYSTEM_*
keys or (fallback, so you can rehearse with your own) LIVEKIT_URL /
LIVEKIT_API_KEY / LIVEKIT_API_SECRET / OPENAI_API_KEY / DEEPGRAM_API_KEY.
FREE_TIER_ENABLED is forced on for the process; it does not touch your .env.

It creates a throwaway user, walks the flow the browser walks, and deletes
the user and its interviews afterwards (interviews cascade), then subtracts
what it consumed from the month's free_tier_usage counter, so the ledger is
left as it found it.

What it asserts:

  1. /api/user/keys/status for the new user: has_keys false, 2 free calls.
     This is what form.html and the dashboard render — if it is wrong, the
     landing page's "2 interviews on us" is a lie.
  2. POST /api/token succeeds with no keys on file, returns a LiveKit token
     for the SYSTEM_LIVEKIT_URL project, and the spawned agent actually talks
     (first lk.transcription chunk within 60 s of joining the room).
  3. The credit was consumed: free_calls_used 1, the month's counter +1,
     status now reports 1 remaining.
  4. The second call is also served; the third is refused with a 400 whose
     message tells the user to add keys.

    python tests/e2e/free_tier_probe.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
load_dotenv(REPO / ".env")

# Force the feature on for THIS process, and let a developer rehearse with
# their own keys when SYSTEM_* are not set. Must happen before `import app`,
# which reads these at import time.
os.environ["FREE_TIER_ENABLED"] = "true"
for sys_var, own_var in (
    ("SYSTEM_LIVEKIT_URL", "LIVEKIT_URL"),
    ("SYSTEM_LIVEKIT_API_KEY", "LIVEKIT_API_KEY"),
    ("SYSTEM_LIVEKIT_API_SECRET", "LIVEKIT_API_SECRET"),
    ("SYSTEM_OPENAI_KEY", "OPENAI_API_KEY"),
    ("SYSTEM_DEEPGRAM_KEY", "DEEPGRAM_API_KEY"),
):
    if not os.environ.get(sys_var) or os.environ[sys_var].startswith("<"):
        if os.environ.get(own_var):
            os.environ[sys_var] = os.environ[own_var]

T0 = time.time()
FAILURES: list[str] = []


def log(msg: str) -> None:
    print(f"{time.time() - T0:7.2f}s  {msg}", flush=True)


def check(cond: bool, what: str) -> None:
    log(("ok    " if cond else "FAIL  ") + what)
    if not cond:
        FAILURES.append(what)


async def wait_for_agent_speech(url: str, token: str, timeout: float = 60.0) -> float | None:
    """Join the room as the candidate; return seconds until the agent's first
    caption chunk, or None. Publishes a silent mic so RoomIO has an input."""
    from livekit import rtc

    room = rtc.Room()
    first = asyncio.get_running_loop().create_future()

    def on_stream(reader, sender):
        async def consume():
            async for chunk in reader:
                if not first.done():
                    first.set_result(time.time())
                    log(f"agent's first caption chunk: {chunk!r}")
                break
        asyncio.create_task(consume())

    room.register_text_stream_handler("lk.transcription", on_stream)
    await room.connect(url, token)
    joined = time.time()
    src = rtc.AudioSource(24000, 1)
    mic = rtc.LocalAudioTrack.create_audio_track("mic", src)
    await room.local_participant.publish_track(
        mic, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))

    async def silence():
        frame = rtc.AudioFrame.create(24000, 1, 240)
        while True:
            await src.capture_frame(frame)
            await asyncio.sleep(0.01)

    task = asyncio.create_task(silence())
    try:
        await asyncio.wait_for(first, timeout)
        return first.result() - joined
    except asyncio.TimeoutError:
        return None
    finally:
        task.cancel()
        await room.disconnect()


def main() -> int:
    import app as A
    from db import db_client
    from worker_manager import worker_manager

    missing = [v for v in ("DATABASE_URL", "ENCRYPTION_KEY") if not os.environ.get(v)]
    if missing or A._system_keys() is None:
        print(f"missing: {missing or 'a complete SYSTEM_* / own key set'} in {REPO / '.env'}", file=sys.stderr)
        return 2

    month = A._current_month()
    email = f"free-tier-probe+{uuid.uuid4().hex[:8]}@example.invalid"
    user_id = db_client.create_user(email=email, name="Free Tier Probe", google_id=f"probe-{uuid.uuid4().hex}")
    check(bool(user_id), f"created throwaway user {email}")
    if not user_id:
        return 1
    usage_before = db_client.free_calls_this_month(month)
    consumed = 0
    rooms: list[str] = []

    A.app.config["TESTING"] = True
    client = A.app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = user_id
        sess["_fresh"] = True

    try:
        # 1. What the UI is told.
        st = client.get("/api/user/keys/status").get_json()
        check(st.get("has_keys") is False, f"status: has_keys={st.get('has_keys')}")
        check(st.get("free_calls_remaining") == 2, f"status: free_calls_remaining={st.get('free_calls_remaining')} (want 2)")

        body = {"name": "Probe", "email": email, "role": "Software Engineer", "level": "mid",
                "track": "intro", "includeProfile": False}

        # 2. First free interview: served, and the agent really speaks.
        r = client.post("/api/token", json=body)
        check(r.status_code == 200, f"1st /api/token -> {r.status_code} {r.get_json() if r.status_code != 200 else ''}")
        if r.status_code == 200:
            consumed += 1
            d = r.get_json()
            rooms.append(d["room"])
            check(d.get("url") == os.environ["SYSTEM_LIVEKIT_URL"], "token is for the SYSTEM LiveKit project")
            t = asyncio.run(wait_for_agent_speech(d["url"], d["token"]))
            check(t is not None, f"agent spoke on the owner's keys ({'%.1fs after join' % t if t else 'never'})")

        # 3. The credit moved.
        used, granted = db_client.get_free_calls(user_id)
        check((used, granted) == (1, 2), f"users.free_calls_used/granted = {used}/{granted} (want 1/2)")
        check(db_client.free_calls_this_month(month) == usage_before + 1,
              f"free_tier_usage[{month}] advanced by 1")
        st = client.get("/api/user/keys/status").get_json()
        check(st.get("free_calls_remaining") == 1, f"status now: free_calls_remaining={st.get('free_calls_remaining')} (want 1)")

        # 4. Second is served; third is refused.
        r2 = client.post("/api/token", json=body)
        check(r2.status_code == 200, f"2nd /api/token -> {r2.status_code}")
        if r2.status_code == 200:
            consumed += 1
            rooms.append(r2.get_json()["room"])
        r3 = client.post("/api/token", json=body)
        j3 = r3.get_json() or {}
        check(r3.status_code == 400, f"3rd /api/token -> {r3.status_code} (want 400)")
        check("free" in (j3.get("message") or "").lower() and "keys" in (j3.get("message") or "").lower(),
              f"3rd refusal explains itself: {j3.get('message')!r}")
        st = client.get("/api/user/keys/status").get_json()
        check(st.get("free_calls_remaining") == 0, f"status now: free_calls_remaining={st.get('free_calls_remaining')} (want 0)")
    finally:
        for room in rooms:
            try:
                worker_manager.terminate_worker(room)
            except Exception as e:
                log(f"terminate_worker({room}) failed: {e}")
        # Leave the ledger as we found it.
        db_client._execute("DELETE FROM users WHERE id = %s", (user_id,))
        if consumed:
            db_client._execute(
                "UPDATE free_tier_usage SET calls = GREATEST(calls - %s, 0), updated_at = NOW() WHERE month = %s",
                (consumed, month))
        after = db_client.free_calls_this_month(month)
        log(f"cleanup: user deleted, free_tier_usage[{month}] {usage_before} -> {after}")

    print()
    if FAILURES:
        print("FAIL")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("PASS: a keyless signed-in user gets 2 interviews on the owner's keys, then is asked for their own")
    return 0


if __name__ == "__main__":
    sys.exit(main())
