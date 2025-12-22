"""
Agent Worker Manager

Spawns and manages agent worker subprocesses for interviews.
Each interview gets a dedicated subprocess with user's API keys.
"""

import os
import subprocess
import logging
import time
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class WorkerManager:
    def __init__(self):
        self.active_workers: Dict[str, subprocess.Popen] = {}
        self.worker_script = os.path.join(os.path.dirname(__file__), 'agent_worker.py')
        self.max_workers = int(os.getenv('MAX_CONCURRENT_WORKERS', '3'))

    def cleanup_terminated_workers(self):
        """Remove terminated workers from active list"""
        terminated = []
        for room_name, process in list(self.active_workers.items()):
            if process.poll() is not None:
                terminated.append(room_name)
                logger.info(f"[WORKER] Worker for room {room_name} has terminated, cleaning up")

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

        Returns:
            bool: True if worker started successfully, False otherwise
        """
        try:
            # Clean up any terminated workers first
            self.cleanup_terminated_workers()

            # Check worker limit
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
                'INTERVIEW_ROOM_NAME': room_name,  # Pass specific room to join
                'PYTHONUNBUFFERED': '1'
            })

            # Spawn subprocess with 'dev' command to connect to specific room
            # Don't pipe stdout/stderr so we can see agent logs in real-time
            process = subprocess.Popen(
                ['python', self.worker_script, 'dev'],
                env=worker_env
            )

            # Store process reference
            self.active_workers[room_name] = process

            logger.info(f"[WORKER] Worker spawned (PID: {process.pid}) for room: {room_name}")

            # Wait for worker to be ready (agent loads ONNX models and initializes)
            return self._wait_for_worker_ready(process, timeout=20)

        except Exception as e:
            logger.error(f"[WORKER] Failed to spawn worker: {e}", exc_info=True)
            return False

    def _wait_for_worker_ready(self, process: subprocess.Popen, timeout: int = 20) -> bool:
        """
        Wait for worker to start and initialize.

        The worker subprocess needs to:
        1. Load ONNX models (Silero VAD) - ~5-10 seconds
        2. Initialize LiveKit FFI - ~2-5 seconds
        3. Connect to LiveKit server

        This typically takes 10-15 seconds on cold start.

        Returns:
            bool: True if worker started successfully, False otherwise
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Check if process is still alive
            if process.poll() is not None:
                # Process died during startup
                logger.error(f"[WORKER] Process died during startup with code: {process.returncode}")
                return False

            # Wait for agent to initialize (10-15 seconds is typical on cold start)
            if time.time() - start_time >= 10:
                logger.info("[WORKER] Worker process started, agent should be ready soon")
                return True

            time.sleep(0.5)

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
                # Process still running - terminate
                logger.info(f"[WORKER] Terminating worker (PID: {process.pid}) for room: {room_name}")
                process.terminate()

                # Wait for graceful shutdown (max 5 seconds)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"[WORKER] Worker did not terminate gracefully, forcing kill")
                    process.kill()
                    process.wait()

            # Remove from active workers
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
        """
        Get worker status for room.

        Returns:
            str: 'running', 'terminated', or None if not found
        """
        if room_name not in self.active_workers:
            return None

        process = self.active_workers[room_name]

        if process.poll() is None:
            return 'running'
        else:
            return 'terminated'


# Global worker manager instance
worker_manager = WorkerManager()
