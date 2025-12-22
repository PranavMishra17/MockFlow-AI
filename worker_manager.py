"""
Agent Worker Manager

Spawns and manages agent worker subprocesses for interviews.
Each interview gets a dedicated subprocess with user's API keys.

FIXED: Workers now connect directly to rooms instead of using LiveKit dispatch.
"""

import os
import subprocess
import logging
import time
import threading
import signal
from typing import Optional, Dict

logger = logging.getLogger(__name__)


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
        self.worker_script = os.path.join(os.path.dirname(__file__), 'agent_worker.py')
        self.max_workers = int(os.getenv('MAX_CONCURRENT_WORKERS', '10'))

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
        deepgram_api_key: str
    ) -> bool:
        """
        Spawn agent worker subprocess with user's API keys.
        
        The worker connects DIRECTLY to the specified room.
        No LiveKit dispatch system involved.

        Returns:
            bool: True if worker started successfully, False otherwise
        """
        try:
            self.cleanup_terminated_workers()

            if len(self.active_workers) >= self.max_workers:
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
                'PYTHONUNBUFFERED': '1'
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
        """Terminate worker subprocess for room"""
        try:
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
        logger.info(f"[WORKER] Cleaning up {len(self.active_workers)} active workers")

        for room_name in list(self.active_workers.keys()):
            self.terminate_worker(room_name)

        logger.info("[WORKER] All workers terminated")

    def get_worker_status(self, room_name: str) -> Optional[str]:
        """Get worker status for room."""
        if room_name not in self.active_workers:
            return None

        process = self.active_workers[room_name]

        if process.poll() is None:
            return 'running'
        else:
            return 'terminated'


# Global worker manager instance
worker_manager = WorkerManager()