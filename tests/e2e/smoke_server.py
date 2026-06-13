"""
Prod-safe smoke server for browser testing.

Boots the real Flask app but:
  - stubs the psycopg connection pool (no real DB connection),
  - replaces db_client methods with synthetic data,
  - adds a /__testlogin route that logs in a demo user (no Google OAuth).

Run:  python tests/e2e/smoke_server.py   (serves on :5099)
This never touches the production database. For local/manual UI testing only.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Force non-secure cookies so the session works over plain http in a browser.
os.environ["FLASK_ENV"] = "development"
os.environ.setdefault("SECRET_KEY", "smoke-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://smoke:smoke@localhost/smoke")
os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("GOOGLE_CLIENT_ID", "smoke")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "smoke")

# Stub the pool BEFORE importing app/db so no socket is opened.
import psycopg_pool  # noqa: E402

psycopg_pool.ConnectionPool = MagicMock(name="StubPool")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import app as A  # noqa: E402
from flask import redirect  # noqa: E402
from flask_login import login_user  # noqa: E402
from auth_helpers import AuthUser  # noqa: E402

DEMO = {"id": "demo-user-1", "email": "demo@mockflow.ai", "name": "Demo Candidate", "picture_url": ""}

db = A.supabase_client
db.get_user = lambda uid: DEMO
db.get_api_keys = lambda uid: None  # exercise the "free interviews, no keys" onboarding path
db.get_free_calls = lambda uid: (1, 2)
db.ping = lambda: True
db.get_user_stats = lambda uid: {
    "total_interviews": 7,
    "tracks": {"intro": 3, "behavioral": 2, "technical_voice": 1, "technical_coding": 1},
    "avg_overall_score": 4.1,
    "last_interview_date": "2026-06-10T14:30:00",
}
db.get_user_interviews = lambda uid, limit=50: [
    {"id": "iv1", "candidate_name": "Demo Candidate", "job_role": "Backend Engineer",
     "experience_level": "mid", "track": "behavioral", "interview_date": "2026-06-10T14:30:00",
     "room_name": "interview-demo-1", "final_stage": "closing", "total_messages": {"agent": 12, "user": 14}},
    {"id": "iv2", "candidate_name": "Demo Candidate", "job_role": "ML Engineer",
     "experience_level": "senior", "track": "technical_coding", "interview_date": "2026-06-08T09:05:00",
     "room_name": "interview-demo-2", "final_stage": "coding_problem_1", "total_messages": {"agent": 8, "user": 9}},
    {"id": "iv3", "candidate_name": "Demo Candidate", "job_role": "Frontend Engineer",
     "experience_level": "junior", "track": "intro", "interview_date": "2026-06-08T18:40:00",
     "room_name": "interview-demo-3", "final_stage": "closing", "total_messages": {"agent": 10, "user": 11}},
]
db.get_feedback = lambda iid: {"user_id": "demo-user-1", "interview_id": iid, "feedback_data": {"overall_score": 4.1}}
db.get_interview_by_id = lambda uid, iid: {
    "id": iid, "user_id": uid, "candidate_name": "Demo Candidate", "job_role": "Backend Engineer",
    "experience_level": "mid", "track": "behavioral", "interview_date": "2026-06-10T14:30:00",
    "conversation": {"agent": [], "user": []},
}


@A.app.route("/__testlogin")
def __testlogin():
    login_user(AuthUser(DEMO))
    return redirect("/dashboard")


if __name__ == "__main__":
    A.app.run(port=5099, debug=False, use_reloader=False)
