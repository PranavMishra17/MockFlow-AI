"""
Live-caption probe: proves captions STREAM while the agent talks, from the room.

This is a Level B check (docs/TESTING_E2E.md): it needs working LiveKit, OpenAI
and Deepgram keys in the repo-root .env, and it costs a short interview. It does
not need the web app, a browser or a microphone. It joins a fresh room as the
candidate, spawns agent_worker.py for that room exactly as worker_manager does,
and timestamps every channel a browser could build a caption from:

  AUDIO   first audible TTS frame of each burst — what the human hears
  STREAM  `lk.transcription` text-stream chunks — what interview.html renders
  DATA    agent_caption / user_caption data packets — the end-of-turn fallback
  LEGACY  rtc.Transcription segments — TranscriptionReceived in old clients

What it asserts, and why each matters:

  1. The agent's first STREAM chunk lands within 1.5 s of its first audible
     frame. Captions are word-synced by the agents SDK; if this fails, the
     caption has fallen back to something that only arrives after the turn.
  2. That first chunk precedes the `agent_caption` data packet. The data
     packet is sent from conversation_item_added, after playback — it is the
     bug this probe was written to catch (captions appearing only once the
     agent stopped talking). It is a fallback, never the live path.
  3. With --say, the candidate's STREAM chunks carry lk.transcribed_track_id
     equal to OUR mic track. interview.html routes captions by that attribute
     because in direct mode both speakers' streams arrive under the agent's
     identity (verified against LiveKit Cloud, 2026-09). If this fails, the
     candidate's words would land in the agent's caption box.

LEGACY is reported, not asserted: LiveKit Cloud stopped forwarding it, which is
exactly why the page cannot rely on it.

    python tests/e2e/caption_probe.py                 # agent greeting only, ~45 s
    python tests/e2e/caption_probe.py --say "Hi, I'm Sam and I build backends." --speak-at 40 --seconds 70
    python tests/e2e/caption_probe.py --track behavioral
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from livekit import api, rtc

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env")

T0 = time.time()
EVENTS: list[tuple[float, str, dict]] = []


def now() -> float:
    return time.time() - T0


def log(chan: str, msg: str, **fields) -> None:
    EVENTS.append((now(), chan, fields))
    print(f"{now():8.3f}s  {chan:7s} {msg}", flush=True)


def candidate_token(room_name: str, track: str) -> str:
    """Same identity shape and attributes app.py's /api/token issues."""
    return (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity("candidate-probe")
        .with_name("Probe")
        .with_attributes({
            "user_id": "probe-user", "role": "Software Engineer", "level": "mid", "email": "",
            "include_profile": "false", "track": track, "framework": "amazon", "depth": "medium",
            "custom_questions": "", "topics": "", "custom_topics": "", "is_free_call": "false",
        })
        .with_grants(api.VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True))
        .to_jwt()
    )


def synthesize(text: str) -> bytes:
    """24 kHz mono int16 PCM of `text`, via OpenAI TTS (a key is required anyway)."""
    from openai import OpenAI

    wav = OpenAI().audio.speech.create(model="tts-1", voice="onyx", response_format="wav", input=text).content
    i = wav.find(b"data")
    return wav[i + 8:]


async def run(args) -> int:
    room_name = f"caption-probe-{int(time.time())}"
    room = rtc.Room()
    audio = {"speaking": False, "quiet": 0}
    mic_sid = {"sid": None}

    @room.on("transcription_received")
    def on_legacy(segments, participant, publication):
        for s in segments:
            log("LEGACY", f"{participant.identity if participant else '?'} final={s.final} {s.text[-50:]!r}")

    @room.on("data_received")
    def on_data(pkt: rtc.DataPacket):
        try:
            d = json.loads(pkt.data.decode())
        except Exception:
            return
        t = d.get("type")
        if t in ("agent_caption", "user_caption"):
            log("DATA", f"{t} len={len(d.get('text', ''))} {d.get('text', '')[:50]!r}", type=t)

    def on_stream(reader: rtc.TextStreamReader, sender: str):
        attrs = dict(reader.info.attributes or {})
        seg = attrs.get("lk.segment_id", "?")
        track_id = attrs.get("lk.transcribed_track_id")

        async def consume():
            n = 0
            async for chunk in reader:
                n += 1
                log("STREAM", f"sender={sender} track={track_id} seg={seg} #{n} {chunk[:40]!r}",
                    sender=sender, track_id=track_id, seg=seg)
            final = dict(reader.info.attributes or {}).get("lk.transcription_final")
            log("STREAM", f"sender={sender} seg={seg} closed after {n} chunks final={final}", closed=True)

        asyncio.create_task(consume())

    room.register_text_stream_handler("lk.transcription", on_stream)

    async def watch_audio(track):
        async for ev in rtc.AudioStream(track):
            data = ev.frame.data
            n = min(200, len(data))
            energy = sum(abs(int(data[i])) for i in range(n)) / max(n, 1)
            if energy > 300:
                audio["quiet"] = 0
                if not audio["speaking"]:
                    audio["speaking"] = True
                    log("AUDIO", f"burst start (energy={energy:.0f})", start=True)
            else:
                audio["quiet"] += 1
                if audio["speaking"] and audio["quiet"] > 40:
                    audio["speaking"] = False
                    log("AUDIO", "burst end")

    @room.on("track_subscribed")
    def on_track(track, publication, participant):
        log("TRACK", f"subscribed {participant.identity} kind={track.kind}")
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            asyncio.create_task(watch_audio(track))

    await room.connect(os.environ["LIVEKIT_URL"], candidate_token(room_name, args.track))
    log("ROOM", f"connected as candidate-probe to {room_name}")

    src = rtc.AudioSource(24000, 1)
    mic = rtc.LocalAudioTrack.create_audio_track("mic", src)
    await room.local_participant.publish_track(
        mic, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    mic_sid["sid"] = mic.sid
    log("ROOM", f"published mic sid={mic.sid}")

    pcm = synthesize(args.say) if args.say else b""

    async def feed_mic():
        silence = rtc.AudioFrame.create(24000, 1, 240)
        step = 240 * 2
        pos, started = 0, False
        while True:
            if pcm and now() >= args.speak_at and pos < len(pcm):
                if not started:
                    started = True
                    log("MIC", "candidate speech start")
                chunk = pcm[pos:pos + step]
                pos += step
                chunk = chunk.ljust(step, b"\0")
                await src.capture_frame(rtc.AudioFrame(
                    data=chunk, sample_rate=24000, num_channels=1, samples_per_channel=240))
                if pos >= len(pcm):
                    log("MIC", "candidate speech end")
            else:
                await src.capture_frame(silence)
            await asyncio.sleep(0.01)

    mic_task = asyncio.create_task(feed_mic())

    env = os.environ.copy()
    env.update({"INTERVIEW_ROOM_NAME": room_name, "AGENT_MODE": "direct", "PYTHONUNBUFFERED": "1"})
    worker_log = Path(tempfile.gettempdir()) / f"{room_name}.worker.log"
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "agent_worker.py")], cwd=str(REPO), env=env,
        stdout=open(worker_log, "w", encoding="utf-8"), stderr=subprocess.STDOUT)
    log("PROBE", f"spawned agent_worker.py pid={proc.pid} (log: {worker_log})")

    try:
        await asyncio.sleep(args.seconds)
    finally:
        mic_task.cancel()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        await room.disconnect()

    return report(mic_sid["sid"], spoke=bool(pcm))


def report(mic_sid: str | None, *, spoke: bool) -> int:
    def first(pred):
        return next((t for t, _, f in EVENTS if pred(_, f)), None)

    audio_start = first(lambda c, f: c == "AUDIO" and f.get("start"))
    agent_stream = first(lambda c, f: c == "STREAM" and "seg" in f and f.get("track_id") != mic_sid)
    data_caption = first(lambda c, f: c == "DATA" and f.get("type") == "agent_caption")
    legacy = sum(1 for _, c, _ in EVENTS if c == "LEGACY")
    user_streams = [f for _, c, f in EVENTS if c == "STREAM" and "seg" in f and f.get("track_id") == mic_sid]
    user_untagged = [f for _, c, f in EVENTS if c == "STREAM" and "seg" in f and f.get("track_id") is None]

    print("\n=== caption probe report ===")
    print(f"first audible agent frame : {audio_start}")
    print(f"first agent STREAM chunk  : {agent_stream}")
    print(f"first agent_caption DATA  : {data_caption}")
    print(f"LEGACY segments           : {legacy}  (LiveKit Cloud forwards none; informational)")
    print(f"candidate STREAM chunks   : {len(user_streams)} tagged with our mic, {len(user_untagged)} untagged")

    failures = []
    if agent_stream is None:
        failures.append("no lk.transcription stream from the agent at all")
    elif audio_start is None:
        failures.append("agent audio never became audible (TTS/output problem, not a caption one)")
    elif agent_stream - audio_start > 1.5:
        failures.append(f"first caption chunk lagged first audible frame by {agent_stream - audio_start:.2f}s (>1.5s)")
    if agent_stream is not None and data_caption is not None and data_caption < agent_stream:
        failures.append("agent_caption data packet arrived BEFORE the stream — the stream is not live")
    if spoke:
        if not user_streams:
            failures.append("candidate spoke but no stream was tagged lk.transcribed_track_id=<our mic>")
        if user_untagged:
            failures.append(f"{len(user_untagged)} candidate stream(s) lacked lk.transcribed_track_id; "
                            "the page would route them to the agent caption")

    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS: captions stream while the agent speaks"
          + (", and the candidate's are tagged with their own track" if spoke else ""))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seconds", type=float, default=45, help="how long to observe (default 45)")
    p.add_argument("--track", default="intro", help="interview track attribute (default intro)")
    p.add_argument("--say", default=None, help="text the candidate speaks, synthesized with OpenAI TTS")
    p.add_argument("--speak-at", type=float, default=40, help="seconds into the run to start speaking")
    args = p.parse_args()
    missing = [k for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "OPENAI_API_KEY", "DEEPGRAM_API_KEY")
               if not os.environ.get(k)]
    if missing:
        print(f"missing in {REPO / '.env'}: {', '.join(missing)}", file=sys.stderr)
        return 2
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
