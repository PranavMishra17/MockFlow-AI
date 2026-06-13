"""
Xata Postgres data access layer.

Drop-in replacement for `supabase_client.SupabaseClient`. Exposes the same
method signatures and return shapes (None / [] / False on failure), so
callers can switch by changing one import line.

Connection target is the `DATABASE_URL` env var (a standard libpq
connection string — Neon, Aiven, Xata, or any other Postgres host).
"""

import logging
import os
from typing import Any, Dict, List, Optional

import psycopg
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

load_dotenv()

logger = logging.getLogger(__name__)


class DB:
    def __init__(self) -> None:
        dsn = os.getenv("DATABASE_URL") or os.getenv("XATA_DATABASE_URL")
        if not dsn:
            raise ValueError("DATABASE_URL is not set")

        self.pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )

        encryption_key = os.getenv("ENCRYPTION_KEY", "").encode()
        self.cipher = Fernet(encryption_key) if encryption_key else None

    def _encrypt(self, text: str) -> str:
        if not self.cipher:
            raise ValueError("Encryption key not configured")
        return self.cipher.encrypt(text.encode()).decode()

    def _decrypt(self, encrypted_text: str) -> str:
        if not self.cipher:
            raise ValueError("Encryption key not configured")
        return self.cipher.decrypt(encrypted_text.encode()).decode()

    # ---- Free tier (owner-funded trial interviews) ----

    def get_free_calls(self, user_id: str) -> tuple:
        """Return (used, granted) free interview counts for a user."""
        try:
            row = self._fetchone(
                "SELECT free_calls_used, free_calls_granted FROM users WHERE id = %s",
                (user_id,),
            )
            if not row:
                return (0, 0)
            return (int(row.get("free_calls_used") or 0), int(row.get("free_calls_granted") or 0))
        except Exception as e:
            logger.error(f"Error reading free calls: {e}")
            return (0, 0)

    def consume_free_call(self, user_id: str, month: str) -> bool:
        """
        Atomically claim one free interview if the user has allowance left, and
        bump the global monthly counter. Returns True if a credit was consumed.
        """
        try:
            row = self._fetchone(
                """
                UPDATE users
                SET free_calls_used = free_calls_used + 1
                WHERE id = %s AND free_calls_used < free_calls_granted
                RETURNING free_calls_used
                """,
                (user_id,),
            )
            if not row:
                return False
            self._execute(
                """
                INSERT INTO free_tier_usage (month, calls) VALUES (%s, 1)
                ON CONFLICT (month) DO UPDATE
                    SET calls = free_tier_usage.calls + 1, updated_at = NOW()
                """,
                (month,),
            )
            return True
        except Exception as e:
            logger.error(f"Error consuming free call: {e}")
            return False

    def free_calls_this_month(self, month: str) -> int:
        """Global count of free interviews served in the given 'YYYY-MM'."""
        try:
            row = self._fetchone(
                "SELECT calls FROM free_tier_usage WHERE month = %s", (month,)
            )
            return int(row["calls"]) if row else 0
        except Exception as e:
            logger.error(f"Error reading monthly free usage: {e}")
            return 0

    def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Aggregate dashboard stats for a user (counts, tracks, avg score, recency)."""
        empty = {
            "total_interviews": 0,
            "tracks": {},
            "avg_overall_score": None,
            "last_interview_date": None,
        }
        try:
            agg = self._fetchone(
                "SELECT COUNT(*) AS total, MAX(interview_date) AS last_date "
                "FROM interviews WHERE user_id = %s",
                (user_id,),
            )
            by_track = self._fetchall(
                "SELECT track, COUNT(*) AS n FROM interviews WHERE user_id = %s GROUP BY track",
                (user_id,),
            )
            rows = self._fetchall(
                "SELECT feedback_data FROM feedback WHERE user_id = %s", (user_id,)
            )
            scores = []
            for r in rows:
                fd = r.get("feedback_data") or {}
                val = fd.get("overall_score") if isinstance(fd, dict) else None
                if isinstance(val, (int, float)):
                    scores.append(val)
            last_date = agg.get("last_date") if agg else None
            return {
                "total_interviews": int(agg["total"]) if agg else 0,
                "tracks": {r["track"]: int(r["n"]) for r in by_track if r.get("track")},
                "avg_overall_score": round(sum(scores) / len(scores), 2) if scores else None,
                "last_interview_date": last_date.isoformat() if last_date else None,
            }
        except Exception as e:
            logger.error(f"Error building user stats: {e}")
            return empty

    def ping(self) -> bool:
        """Return True if the database answers a trivial query, else False."""
        try:
            with self.pool.connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except Exception as e:
            logger.error(f"Database ping failed: {e}")
            return False

    def _fetchone(self, sql: str, params: tuple) -> Optional[Dict[str, Any]]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def _fetchall(self, sql: str, params: tuple) -> List[Dict[str, Any]]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() or []

    def _execute(self, sql: str, params: tuple) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._fetchone(
                "SELECT * FROM users WHERE id = %s",
                (user_id,),
            )
        except Exception as e:
            logger.error(f"Error fetching user: {e}")
            return None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        try:
            return self._fetchone(
                "SELECT * FROM users WHERE email = %s",
                (email,),
            )
        except Exception as e:
            logger.error(f"Error fetching user by email: {e}")
            return None

    def create_user(
        self,
        email: str,
        name: str,
        google_id: str,
        picture_url: str = "",
    ) -> Optional[str]:
        try:
            row = self._fetchone(
                """
                INSERT INTO users (email, name, google_id, picture_url)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (email, name, google_id, picture_url),
            )
            return str(row["id"]) if row else None
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return None

    def save_api_keys(
        self,
        user_id: str,
        livekit_url: str,
        livekit_api_key: str,
        livekit_api_secret: str,
        openai_key: str,
        deepgram_key: str,
    ) -> bool:
        try:
            self._execute(
                """
                INSERT INTO user_api_keys (
                    user_id,
                    livekit_url_encrypted,
                    livekit_key_encrypted,
                    livekit_secret_encrypted,
                    openai_key_encrypted,
                    deepgram_key_encrypted,
                    encryption_salt
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    livekit_url_encrypted    = EXCLUDED.livekit_url_encrypted,
                    livekit_key_encrypted    = EXCLUDED.livekit_key_encrypted,
                    livekit_secret_encrypted = EXCLUDED.livekit_secret_encrypted,
                    openai_key_encrypted     = EXCLUDED.openai_key_encrypted,
                    deepgram_key_encrypted   = EXCLUDED.deepgram_key_encrypted,
                    updated_at               = NOW()
                """,
                (
                    user_id,
                    self._encrypt(livekit_url),
                    self._encrypt(livekit_api_key),
                    self._encrypt(livekit_api_secret),
                    self._encrypt(openai_key),
                    self._encrypt(deepgram_key),
                    "salt_v1",
                ),
            )
            return True
        except Exception as e:
            logger.error(f"Error saving API keys: {e}")
            return False

    def get_api_keys(self, user_id: str) -> Optional[Dict[str, str]]:
        try:
            row = self._fetchone(
                "SELECT * FROM user_api_keys WHERE user_id = %s",
                (user_id,),
            )
            if not row:
                return None
            return {
                "livekit_url": self._decrypt(row["livekit_url_encrypted"]),
                "livekit_api_key": self._decrypt(row["livekit_key_encrypted"]),
                "livekit_api_secret": self._decrypt(row["livekit_secret_encrypted"]),
                "openai_key": self._decrypt(row["openai_key_encrypted"]),
                "deepgram_key": self._decrypt(row["deepgram_key_encrypted"]),
            }
        except Exception as e:
            logger.error(f"Error fetching API keys: {e}")
            return None

    def save_interview(
        self, user_id: str, interview_data: Dict[str, Any]
    ) -> Optional[str]:
        try:
            candidate_name = (
                interview_data.get("candidate_name")
                or interview_data.get("candidate")
                or interview_data.get("candidateName")
                or "Unknown"
            )
            room_name = (
                interview_data.get("room_name")
                or interview_data.get("roomName")
                or ""
            )
            job_role = (
                interview_data.get("job_role")
                or interview_data.get("jobRole")
                or ""
            )
            experience_level = (
                interview_data.get("experience_level")
                or interview_data.get("experienceLevel")
                or ""
            )
            final_stage = (
                interview_data.get("final_stage")
                or interview_data.get("finalStage")
                or ""
            )
            ended_by = (
                interview_data.get("ended_by")
                or interview_data.get("endedBy")
                or "unknown"
            )
            skipped_stages = (
                interview_data.get("skipped_stages")
                or interview_data.get("skippedStages")
                or []
            )
            has_resume = bool(
                interview_data.get("has_resume") or interview_data.get("hasResume")
            )
            has_jd = bool(
                interview_data.get("has_jd")
                or interview_data.get("hasJobDescription")
            )

            logger.info(f"[DB] Saving interview for candidate: {candidate_name}")
            row = self._fetchone(
                """
                INSERT INTO interviews (
                    user_id, candidate_name, room_name, job_role, experience_level,
                    final_stage, ended_by, skipped_stages, has_resume, has_jd,
                    conversation, total_messages, metadata,
                    interview_date, track, track_config
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    COALESCE(%s, NOW()), %s, %s
                )
                RETURNING id
                """,
                (
                    user_id,
                    candidate_name,
                    room_name,
                    job_role,
                    experience_level,
                    final_stage,
                    ended_by,
                    skipped_stages,
                    has_resume,
                    has_jd,
                    Jsonb(interview_data.get("conversation", {})),
                    Jsonb(interview_data.get("total_messages", {})),
                    Jsonb(interview_data.get("metadata", {})),
                    interview_data.get("interview_date"),
                    interview_data.get("track", "intro"),
                    Jsonb(interview_data.get("track_config", {})),
                ),
            )
            if row:
                interview_id = str(row["id"])
                logger.info(f"[DB] Interview saved with ID: {interview_id}")
                return interview_id
            return None
        except Exception as e:
            logger.error(f"[DB] Error saving interview: {e}", exc_info=True)
            return None

    def get_user_interviews(
        self, user_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        try:
            return self._fetchall(
                """
                SELECT * FROM interviews
                WHERE user_id = %s
                ORDER BY interview_date DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
        except Exception as e:
            logger.error(f"Error fetching interviews: {e}")
            return []

    def get_interview_by_room(self, room_name: str) -> Optional[Dict[str, Any]]:
        try:
            return self._fetchone(
                "SELECT * FROM interviews WHERE room_name = %s LIMIT 1",
                (room_name,),
            )
        except Exception as e:
            logger.error(f"Error fetching interview: {e}")
            return None

    def get_interview_by_room_name(
        self, user_id: str, room_name: str
    ) -> Optional[Dict[str, Any]]:
        try:
            return self._fetchone(
                """
                SELECT * FROM interviews
                WHERE user_id = %s AND room_name = %s
                LIMIT 1
                """,
                (user_id, room_name),
            )
        except Exception as e:
            logger.error(f"Error fetching interview by room name: {e}")
            return None

    def get_interview_by_id(
        self, user_id: str, interview_id: str
    ) -> Optional[Dict[str, Any]]:
        try:
            return self._fetchone(
                """
                SELECT * FROM interviews
                WHERE id = %s AND user_id = %s
                """,
                (interview_id, user_id),
            )
        except Exception as e:
            logger.error(f"Error fetching interview by ID: {e}", exc_info=True)
            return None

    def save_feedback(
        self, user_id: str, interview_id: str, feedback_data: Dict[str, Any]
    ) -> bool:
        try:
            self._execute(
                """
                INSERT INTO feedback (user_id, interview_id, feedback_data)
                VALUES (%s, %s, %s)
                ON CONFLICT (interview_id) DO UPDATE SET
                    feedback_data = EXCLUDED.feedback_data,
                    updated_at    = NOW()
                """,
                (user_id, interview_id, Jsonb(feedback_data)),
            )
            return True
        except Exception as e:
            logger.error(f"Error saving feedback: {e}")
            return False

    def get_feedback(self, interview_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._fetchone(
                "SELECT * FROM feedback WHERE interview_id = %s",
                (interview_id,),
            )
        except Exception as e:
            logger.error(f"Error fetching feedback: {e}")
            return None

    def save_coding_submission(
        self,
        user_id: str,
        interview_id: str,
        problem_title: str,
        problem_description: str,
        language: str,
        code_submitted: str,
        attempt_number: int = 1,
        evaluation_result: Optional[Dict[str, Any]] = None,
        time_spent_seconds: Optional[int] = None,
    ) -> Optional[str]:
        try:
            logger.info(
                f"[DB] Saving coding submission for interview {interview_id}, "
                f"problem: {problem_title}, attempt {attempt_number}"
            )
            row = self._fetchone(
                """
                INSERT INTO coding_submissions (
                    user_id, interview_id, problem_title, problem_description,
                    language, code_submitted, attempt_number,
                    evaluation_result, time_spent_seconds
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    interview_id,
                    problem_title,
                    problem_description or "",
                    language,
                    code_submitted,
                    attempt_number,
                    Jsonb(evaluation_result or {}),
                    time_spent_seconds,
                ),
            )
            if row:
                submission_id = str(row["id"])
                logger.info(f"[DB] Coding submission saved: {submission_id}")
                return submission_id
            return None
        except Exception as e:
            logger.error(f"[DB] Error saving coding submission: {e}", exc_info=True)
            return None

    def get_coding_submissions(self, interview_id: str) -> List[Dict[str, Any]]:
        try:
            return self._fetchall(
                """
                SELECT * FROM coding_submissions
                WHERE interview_id = %s
                ORDER BY created_at ASC
                """,
                (interview_id,),
            )
        except Exception as e:
            logger.error(f"[DB] Error fetching coding submissions: {e}")
            return []


db_client = DB()
