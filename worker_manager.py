"""
Agent Worker Manager

Gets an interview agent into a LiveKit room, by one of two transports:

  direct    (default) Spawn agent_worker.py as a dedicated subprocess carrying
            the user's API keys. The worker connects straight to the room.

  dispatch  Ask LiveKit to hand the room to a RESIDENT worker registered under
            an agent_name. No subprocess; this box stays small.

`spawn_worker()` picks between them and returns the same bool either way, so
callers do not branch on transport.

Dispatch is not always available. This app is BYOK: an interview may be funded
by the user's OWN LiveKit project, and a worker registered against the owner's
project can never receive a job for a room that lives somewhere else. When the
credentials do not match the resident worker's, we fall back to a direct spawn —
see agent_mode.can_dispatch.
"""

import os
import subprocess
import logging
import time
import threading
import signal
from typing import Optional, Dict

import agent_mode

logger = logging.getLogger(__name__)

# Owner-funded ("system") LiveKit credentials — the project a dispatch worker is
# expected to be registered with. Mirrors app._system_keys()'s LiveKit subset,
# read from env here to avoid importing app (which imports this module).
def _system_livekit_keys() -> Optional[Dict[str, str]]:
    """The resident dispatch worker's credentials — ALL FIVE, from SYSTEM_*.

    The worker reads the same vars (agent_worker resolves them via
    agent_mode.system_keys_from_env in dispatch mode), so comparing an
    interview's keys against these is a claim that can actually be true.
    Previously this returned only the LiveKit subset and compared it against a
    worker registered with unrelated LIVEKIT_* vars.
    """
    return agent_mode.system_keys_from_env(os.environ)


# Fail fast on a misconfigured AGENT_MODE: this raises at import, so the web
# process refuses to start rather than falling back to the wrong transport and
# only revealing it when the first candidate's interview fails to find an agent.
agent_mode.resolve_mode(os.environ)


def _log_subprocess_output(process: subprocess.Popen, room_name: str):
    """Read subprocess stdout/stderr and forward to parent logger"""
    try:
        for line in iter(process.stdout.readline, ''):
            if line:
                logger.info(f"[WORKER-{room_name[-8:]}] {line.rstrip()}")
    except Exception as e:
        logger.error(f"[WORKER] Error reading subprocess output: {e}")


class WorkerManager:
    def __init__(self):
        self.active_workers: Dict[str, subprocess.Popen] = {}
        # Dispatched interviews run on a resident worker, so there is no local
        # process to poll. Records are kept for status reporting only and age out
        # via DISPATCH_TTL_SECONDS — the worker ends the job without telling us.
        # room_name -> {"dispatch_id": str, "created_at": float}
        self.active_dispatches: Dict[str, Dict[str, object]] = {}
        self.worker_script = os.path.join(os.path.dirname(__file__), 'agent_worker.py')
        self.max_workers = int(os.getenv('MAX_CONCURRENT_WORKERS', '10'))

    #: A dispatched interview is abandoned from this process's bookkeeping after
    #: this long. It is only ever used for reporting — nothing is killed — but
    #: without it `active_dispatches` grows forever, since the resident worker
    #: ends the job and this process is never told.
    DISPATCH_TTL_SECONDS = 3 * 60 * 60

    def _reap_stale_dispatches(self):
        """Drop dispatch records older than any plausible interview."""
        now = time.time()
        stale = [
            room for room, rec in self.active_dispatches.items()
            if now - rec.get("created_at", now) > self.DISPATCH_TTL_SECONDS
        ]
        for room in stale:
            self.active_dispatches.pop(room, None)
        if stale:
            logger.info(f"[WORKER] Reaped {len(stale)} stale dispatch record(s)")

    def total_active_count(self) -> int:
        """Interviews currently being served, across both transports (reporting)."""
        self._reap_stale_dispatches()
        return len(self.active_workers) + len(self.active_dispatches)

    def local_capacity_used(self) -> int:
        """Interviews consuming THIS box's memory — i.e. spawned subprocesses.

        MAX_CONCURRENT_WORKERS caps local memory: each direct worker loads
        onnxruntime here. A dispatched interview runs on the resident worker and
        costs this process nothing, so counting it against the local cap made
        dispatch *reduce* the app's capacity — and because nothing ever released
        a dispatch record, the cap was reached permanently and every interview,
        on both transports, was refused until restart.
        """
        return len(self.active_workers)

    def cleanup_terminated_workers(self):
        """Remove terminated workers from active list"""
        terminated = []
        for room_name, process in list(self.active_workers.items()):
            if process.poll() is not None:
                terminated.append(room_name)
                logger.info(f"[WORKER] Worker for room {room_name} has terminated (exit code: {process.returncode})")

        for room_name in terminated:
            del self.active_workers[room_name]

        if terminated:
            logger.info(f"[WORKER] Cleaned up {len(terminated)} terminated workers")

    def spawn_worker(
        self,
        room_name: str,
        livekit_url: str,
        livekit_api_key: str,
        livekit_api_secret: str,
        openai_api_key: str,
        deepgram_api_key: str,
        interview_config: Optional[dict] = None,
    ) -> bool:
        """
        Get an interview agent into `room_name`, by whichever transport applies.

        In dispatch mode with matching credentials this creates a LiveKit agent
        dispatch; otherwise it spawns a dedicated subprocess that connects
        DIRECTLY to the room (the original behavior).

        `interview_config`, when given, rides along as dispatch job metadata.
        It is optional because the web client already publishes the same values
        as participant attributes, which the worker reads in both modes — so
        dispatch works correctly even with no config plumbing at all.

        Returns:
            bool: True if an agent is on its way to the room, False otherwise
        """
        try:
            self.cleanup_terminated_workers()

            # All five, because can_dispatch compares all five: LiveKit decides
            # whether the job can be routed, OpenAI/Deepgram decide whose account
            # the interview is billed to.
            interview_keys = {
                'livekit_url': livekit_url,
                'livekit_api_key': livekit_api_key,
                'livekit_api_secret': livekit_api_secret,
                'openai_key': openai_api_key,
                'deepgram_key': deepgram_api_key,
            }

            # Try dispatch BEFORE the local capacity gate: a dispatched interview
            # runs on the resident worker and consumes none of this box's memory,
            # so a full local cap must not block it.
            if agent_mode.dispatch_enabled(os.environ):
                if agent_mode.can_dispatch(interview_keys, _system_livekit_keys()):
                    return self._create_dispatch(room_name, interview_keys, interview_config)
                logger.info(
                    "[WORKER] Dispatch mode is on but this interview uses different "
                    "credentials (BYOK); falling back to a direct spawn."
                )

            # Gate on LOCAL capacity: the cap exists to bound this box's memory,
            # and only a spawned subprocess consumes it.
            if self.local_capacity_used() >= self.max_workers:
                logger.error(f"[WORKER] Max concurrent workers ({self.max_workers}) reached")
                return False

            logger.info(f"[WORKER] Spawning worker for room: {room_name}")

            # Build environment with user's API keys + specific room name
            worker_env = os.environ.copy()
            worker_env.update({
                'LIVEKIT_URL': livekit_url,
                'LIVEKIT_API_KEY': livekit_api_key,
                'LIVEKIT_API_SECRET': livekit_api_secret,
                'OPENAI_API_KEY': openai_api_key,
                'DEEPGRAM_API_KEY': deepgram_api_key,
                'INTERVIEW_ROOM_NAME': room_name,
                'PYTHONUNBUFFERED': '1',
                # MUST be forced. The child inherits this process's environment,
                # so in dispatch mode a BYOK fallback spawn would inherit
                # AGENT_MODE=dispatch, route __main__ to cli.run_app() with no
                # subcommand, and die instantly with "Missing command." (exit 2)
                # — breaking the one path the BYOK guard exists to provide.
                'AGENT_MODE': agent_mode.MODE_DIRECT,
            })

            # Spawn subprocess WITHOUT 'dev' command
            # Worker runs asyncio.run(run_interview()) directly
            # This means worker connects directly to room, not via LiveKit dispatch
            process = subprocess.Popen(
                ['python', self.worker_script],  # NO 'dev' command!
                env=worker_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True
            )

            self.active_workers[room_name] = process

            logger.info(f"[WORKER] Worker spawned (PID: {process.pid}) for room: {room_name}")

            # Start thread to forward subprocess logs
            log_thread = threading.Thread(
                target=_log_subprocess_output,
                args=(process, room_name),
                daemon=True
            )
            log_thread.start()

            # Wait for worker to initialize (load models, connect to room)
            return self._wait_for_worker_ready(process, timeout=30)

        except Exception as e:
            logger.error(f"[WORKER] Failed to spawn worker: {e}", exc_info=True)
            return False

    def _create_dispatch(
        self,
        room_name: str,
        keys: Dict[str, str],
        interview_config: Optional[dict] = None,
    ) -> bool:
        """Route `room_name` to the resident worker, and CONFIRM one arrived.

        `create_dispatch` succeeding only means LiveKit accepted the job — it
        succeeds even when no worker is registered under this agent_name, in
        which case the candidate waits out the join timeout with no interviewer.
        Direct mode returns True only after verifying its subprocess is alive, so
        returning True on mere acceptance made the two transports mean different
        things to every caller — including the free-tier credit, which is claimed
        the moment this returns True.

        So we poll the room for the agent participant. True here means the same
        thing it means in direct mode: an interviewer is present.
        """
        import asyncio

        from livekit import api as livekit_api

        agent = agent_mode.agent_name(os.environ)
        metadata = agent_mode.encode_job_metadata(interview_config) if interview_config else ""

        async def _dispatch_and_confirm():
            client = livekit_api.LiveKitAPI(
                url=keys['livekit_url'],
                api_key=keys['livekit_api_key'],
                api_secret=keys['livekit_api_secret'],
            )
            try:
                dispatch = await client.agent_dispatch.create_dispatch(
                    livekit_api.CreateAgentDispatchRequest(
                        agent_name=agent, room=room_name, metadata=metadata
                    )
                )
                joined = await self._await_agent_join(client, room_name)
                return dispatch, joined
            finally:
                await client.aclose()

        try:
            logger.info(f"[WORKER] Creating dispatch for room: {room_name} (agent_name={agent})")
            # Called from a Flask request thread, which has no running event loop
            # of its own, so a fresh one per dispatch is safe here.
            dispatch, joined = asyncio.run(_dispatch_and_confirm())
            dispatch_id = getattr(dispatch, 'id', '') or 'unknown'

            if not joined:
                logger.error(
                    f"[WORKER] Dispatch {dispatch_id} accepted for {room_name} but no agent "
                    f"joined within {self.DISPATCH_JOIN_TIMEOUT}s — is a worker registered "
                    f"under agent_name={agent}?"
                )
                return False

            self.active_dispatches[room_name] = {
                'dispatch_id': dispatch_id,
                'created_at': time.time(),
            }
            logger.info(f"[WORKER] Agent joined via dispatch {dispatch_id} for room: {room_name}")
            return True
        except Exception as e:
            logger.error(f"[WORKER] Failed to create dispatch for {room_name}: {e}", exc_info=True)
            return False

    #: How long to wait for the dispatched agent to actually appear in the room.
    #: Mirrors the direct path's readiness wait; the resident worker has no model
    #: loading to do, so this is generous.
    DISPATCH_JOIN_TIMEOUT = 20

    async def _await_agent_join(self, client, room_name: str) -> bool:
        """Poll the room until a non-candidate participant (the agent) appears."""
        import asyncio

        from livekit import api as livekit_api

        deadline = time.time() + self.DISPATCH_JOIN_TIMEOUT
        while time.time() < deadline:
            try:
                res = await client.room.list_participants(
                    livekit_api.ListParticipantsRequest(room=room_name)
                )
                for p in getattr(res, 'participants', []):
                    identity = getattr(p, 'identity', '') or ''
                    if identity.startswith('interview-agent') or identity.startswith('agent'):
                        return True
            except Exception as e:
                # The room may not exist until the agent or candidate joins.
                logger.debug(f"[WORKER] list_participants not ready for {room_name}: {e}")
            await asyncio.sleep(1.0)
        return False

    def _wait_for_worker_ready(self, process: subprocess.Popen, timeout: int = 30) -> bool:
        """
        Wait for worker to start and connect to room.

        The worker needs to:
        1. Load ONNX models (Silero VAD) - ~5-10 seconds
        2. Generate agent token
        3. Connect to LiveKit room
        4. Wait for participant

        Returns:
            bool: True if worker started, False if it died during startup
        """
        start_time = time.time()
        check_interval = 0.5
        
        # Initial delay for model loading
        time.sleep(3)

        while time.time() - start_time < timeout:
            # Check if process died
            exit_code = process.poll()
            if exit_code is not None:
                logger.error(f"[WORKER] Process died during startup with code: {exit_code}")
                return False

            # Worker is still running - after initial model load time, consider ready
            elapsed = time.time() - start_time
            if elapsed >= 8:
                logger.info(f"[WORKER] Worker process running after {elapsed:.1f}s, considered ready")
                return True

            time.sleep(check_interval)

        # Timeout reached but process still running - assume success
        if process.poll() is None:
            logger.info(f"[WORKER] Worker still running after {timeout}s timeout, considered ready")
            return True
            
        logger.error(f"[WORKER] Worker not ready within {timeout}s timeout")
        return False

    def terminate_worker(self, room_name: str):
        """Release the agent serving `room_name`."""
        try:
            # Dispatched jobs have no local process. The agent leaves when the
            # room empties, which the framework handles; we just stop tracking.
            if room_name in self.active_dispatches:
                dispatch_id = self.active_dispatches.pop(room_name).get('dispatch_id', 'unknown')
                logger.info(
                    f"[WORKER] Released dispatched room {room_name} "
                    f"(dispatch {dispatch_id}); resident worker ends the job itself"
                )
                return

            if room_name not in self.active_workers:
                logger.warning(f"[WORKER] No active worker for room: {room_name}")
                return

            process = self.active_workers[room_name]

            if process.poll() is None:
                logger.info(f"[WORKER] Terminating worker (PID: {process.pid}) for room: {room_name}")
                process.terminate()

                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"[WORKER] Worker did not terminate gracefully, forcing kill")
                    process.kill()
                    process.wait()

            del self.active_workers[room_name]
            logger.info(f"[WORKER] Worker terminated for room: {room_name}")

        except Exception as e:
            logger.error(f"[WORKER] Error terminating worker: {e}", exc_info=True)

    def cleanup_all_workers(self):
        """Terminate all active workers (called on server shutdown)"""
        logger.info(f"[WORKER] Cleaning up {self.total_active_count()} active interviews")

        for room_name in list(self.active_workers.keys()):
            self.terminate_worker(room_name)
        # Dispatched jobs outlive this process by design — the resident worker
        # is not ours to kill — so we only drop our tracking of them.
        for room_name in list(self.active_dispatches.keys()):
            self.terminate_worker(room_name)

        logger.info("[WORKER] All workers terminated")

    def get_worker_status(self, room_name: str) -> Optional[str]:
        """Get worker status for room."""
        if room_name in self.active_dispatches:
            # No local process to poll. The agent was confirmed present at
            # dispatch time, so report running until the room is released or the
            # record ages out.
            return 'running'

        if room_name not in self.active_workers:
            return None

        process = self.active_workers[room_name]

        if process.poll() is None:
            return 'running'
        else:
            return 'terminated'


# Global worker manager instance
worker_manager = WorkerManager()