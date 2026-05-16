"""
Smoke test for db.py against a live Xata Postgres.

Run after Phase 6 (schema bootstrap):
    python test_db.py

Requires XATA_DATABASE_URL and ENCRYPTION_KEY in .env.
Inserts one test user + interview + feedback + coding submission, reads
them back, then cleans up by deleting the user (cascade removes the rest).
"""

import logging
import sys
import uuid
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(message)s")

from db import db_client


def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    email = f"smoketest+{suffix}@example.com"

    user_id = db_client.create_user(
        email=email,
        name="Smoke Test",
        google_id=f"google-{suffix}",
        picture_url="",
    )
    assert user_id, "create_user returned None"
    print(f"[OK] create_user -> {user_id}")

    assert db_client.get_user(user_id), "get_user returned None"
    assert db_client.get_user_by_email(email), "get_user_by_email returned None"
    print("[OK] get_user / get_user_by_email")

    assert db_client.save_api_keys(
        user_id,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="APItest",
        livekit_api_secret="secrettest",
        openai_key="sk-test",
        deepgram_key="dgtest",
    ), "save_api_keys returned False"
    keys = db_client.get_api_keys(user_id)
    assert keys and keys["openai_key"] == "sk-test", f"get_api_keys mismatch: {keys}"
    print("[OK] save_api_keys / get_api_keys (encrypt+decrypt round-trip)")

    interview_id = db_client.save_interview(
        user_id,
        {
            "candidate_name": "Test Candidate",
            "room_name": f"room-{suffix}",
            "job_role": "Software Engineer",
            "experience_level": "mid",
            "interview_date": datetime.now(timezone.utc).isoformat(),
            "conversation": {"turns": [{"role": "user", "text": "hi"}]},
            "total_messages": {"user": 1, "agent": 1},
            "metadata": {"smoke": True},
            "skipped_stages": ["welcome"],
            "final_stage": "closing",
            "ended_by": "user",
            "has_resume": False,
            "has_jd": False,
            "track": "intro",
            "track_config": {"depth": "medium"},
        },
    )
    assert interview_id, "save_interview returned None"
    print(f"[OK] save_interview -> {interview_id}")

    assert db_client.get_interview_by_id(user_id, interview_id)
    assert db_client.get_interview_by_room(f"room-{suffix}")
    assert db_client.get_interview_by_room_name(user_id, f"room-{suffix}")
    assert len(db_client.get_user_interviews(user_id)) == 1
    print("[OK] get_interview_by_id / get_interview_by_room / get_user_interviews")

    assert db_client.save_feedback(
        user_id, interview_id, {"score": 8, "notes": "good"}
    ), "save_feedback returned False"
    fb = db_client.get_feedback(interview_id)
    assert fb and fb["feedback_data"]["score"] == 8, f"feedback mismatch: {fb}"
    print("[OK] save_feedback / get_feedback (with JSONB round-trip)")

    sub_id = db_client.save_coding_submission(
        user_id=user_id,
        interview_id=interview_id,
        problem_title="Two Sum",
        problem_description="...",
        language="python",
        code_submitted="def two_sum(nums, target): ...",
        attempt_number=1,
        evaluation_result={"correctness": "passed"},
        time_spent_seconds=120,
    )
    assert sub_id, "save_coding_submission returned None"
    subs = db_client.get_coding_submissions(interview_id)
    assert len(subs) == 1, f"expected 1 submission, got {len(subs)}"
    print(f"[OK] save_coding_submission -> {sub_id}")

    with db_client.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    print("[OK] cleanup (cascade deleted interview/feedback/submission/api_keys)")

    print("\nAll db.py methods round-trip correctly against Postgres.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
