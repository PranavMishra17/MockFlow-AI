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

# Synthetic Wing D verdict + history so the reveal, personality, radar and
# compare surfaces render with realistic data (no DB, no OpenAI).
_VERDICT = {
    "overall": {"recommendation": "lean_hire", "confidence": "medium", "level_read": "new_grad",
                "headline": "Strong problem-solving and clear structure, but ownership stayed at the team level."},
    "context": {"track": "behavioral", "role": "swe", "seniority": "mid", "archetype": "big_tech"},
    "signals": [
        {"name": "Problem-solving", "band": "outstanding", "scope_met": "mid",
         "reasoning": "Decomposed the ambiguous prompt before diving in and weighed two approaches out loud.",
         "evidence": ["I'd first clarify the constraints, then compare a hash-map approach against sorting"], "to_raise": ""},
        {"name": "Communication & structure", "band": "solid", "scope_met": "new_grad",
         "reasoning": "Signposted the answer and kept it concise.",
         "evidence": ["Let me walk through this in three parts: the problem, my approach, and the trade-offs"],
         "to_raise": "Land the headline result first, then the detail."},
        {"name": "Ownership", "band": "borderline", "scope_met": "new_grad",
         "reasoning": "Defaulted to 'we' and the personal contribution stayed fuzzy under follow-up.",
         "evidence": ["We shipped the migration and it went well"],
         "to_raise": "Say 'I decided / I measured', and name the metric you personally moved."},
        {"name": "Impact & metrics", "band": "solid", "scope_met": "new_grad",
         "reasoning": "Quantified one result credibly.",
         "evidence": ["That cut the p99 latency by about 30 percent"],
         "to_raise": "Tie each story to a number and the decision it changed."},
        {"name": "Authenticity", "band": "cannot_determine", "scope_met": "new_grad",
         "reasoning": "Not enough unscripted detail to judge.", "evidence": [], "to_raise": ""},
    ],
    "differentiators": ["A genuine point of view on the trade-off, not just the textbook answer."],
    "delivery": {"wpm": 168, "wpm_band": "brisk", "wpm_target": "130-160",
                 "filler_total": 14, "filler_per_min": 7.2, "filler_band": "moderate", "filler_target": "<=5/min",
                 "word_count": 1180, "sentence_count": 86,
                 "filler_breakdown": {"like": 9, "basically": 3, "um": 2},
                 "top_crutch_word": {"word": "like", "count": 9},
                 "talk_ratio": 0.63, "longest_monologue_s": 48.0},
    "gap_to_next": {"signal": "Ownership", "from_band": "borderline", "to_band": "solid",
                    "move": "Say 'I decided / I measured', and name the metric you personally moved."},
    "great_answers": 1,
}


def _hist(iid, track, created, reco, level, signals, delivery, great=0):
    return {"interview_id": iid, "track": track, "created_at": created,
            "scores": {"verdict": {"overall": {"recommendation": reco, "level_read": level},
                                   "context": {"seniority": "mid", "role": "swe", "archetype": "big_tech"},
                                   "signals": signals, "delivery": delivery, "great_answers": great,
                                   "gap_to_next": {"signal": signals[-1]["name"], "move": "tighten this signal"}}}}


ID_A = "00000000-0000-0000-0000-0000000000a1"  # behavioral, latest
ID_B = "00000000-0000-0000-0000-0000000000b2"  # coding
ID_C = "00000000-0000-0000-0000-0000000000c3"  # intro, oldest

_HISTORY = [
    _hist(ID_C, "intro", "2026-05-20T10:00:00", "on_fence", "new_grad",
          [{"name": "Communication & structure", "band": "borderline", "evidence": ["uh I guess my background is"]},
           {"name": "Motivation & authenticity", "band": "solid", "evidence": ["I've wanted to work on infra since my first internship"]}],
          {"word_count": 600, "sentence_count": 40, "filler_total": 18,
           "filler_breakdown": {"like": 12, "um": 6}, "talk_ratio": 0.55, "longest_monologue_s": 30}),
    _hist(ID_B, "coding", "2026-06-02T10:00:00", "lean_hire", "new_grad",
          [{"name": "Problem-solving", "band": "solid", "evidence": ["I'd start by clarifying the inputs and the expected output"]},
           {"name": "Coding", "band": "solid", "evidence": ["a clean recursion with a memo table to avoid recomputation"]},
           {"name": "Communication & structure", "band": "solid", "evidence": ["narrating the trade-offs as I go"]}],
          {"word_count": 900, "sentence_count": 62, "filler_total": 10,
           "filler_breakdown": {"like": 6, "basically": 4}, "talk_ratio": 0.60, "longest_monologue_s": 40}),
    {"interview_id": ID_A, "track": "behavioral", "created_at": "2026-06-10T14:30:00",
     "scores": {"verdict": _VERDICT}},
]

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
    {"id": ID_A, "candidate_name": "Demo Candidate", "job_role": "Backend Engineer",
     "experience_level": "mid", "track": "behavioral", "interview_date": "2026-06-10T14:30:00",
     "room_name": "interview-demo-1", "final_stage": "closing", "total_messages": {"agent": 12, "user": 14}},
    {"id": ID_B, "candidate_name": "Demo Candidate", "job_role": "ML Engineer",
     "experience_level": "mid", "track": "coding", "interview_date": "2026-06-02T09:05:00",
     "room_name": "interview-demo-2", "final_stage": "coding_problem_1", "total_messages": {"agent": 8, "user": 9}},
    {"id": ID_C, "candidate_name": "Demo Candidate", "job_role": "Frontend Engineer",
     "experience_level": "junior", "track": "intro", "interview_date": "2026-05-20T18:40:00",
     "room_name": "interview-demo-3", "final_stage": "closing", "total_messages": {"agent": 10, "user": 11}},
]
db.get_feedback = lambda iid: {"user_id": "demo-user-1", "interview_id": iid, "feedback_data": {"verdict": _VERDICT}}
db.get_user_score_history = lambda uid, limit=50: _HISTORY
db.save_feedback = lambda uid, iid, data: True
db.save_interview_scores = lambda **k: True
db.get_coding_submissions = lambda iid: []
db.get_interview_by_id = lambda uid, iid: {
    "id": iid, "user_id": uid, "candidate_name": "Demo Candidate", "job_role": "Backend Engineer",
    "experience_level": "mid", "track": "behavioral", "interview_date": "2026-06-10T14:30:00",
    "conversation": {"agent": [{"text": "Tell me about a hard project.", "stage": "behavioral_q1"}],
                     "user": [{"text": "Sure, so basically we built a migration tool.", "stage": "behavioral_q1"}]},
}


@A.app.route("/__testlogin")
def __testlogin():
    login_user(AuthUser(DEMO))
    return redirect("/dashboard")


if __name__ == "__main__":
    A.app.run(port=5099, debug=False, use_reloader=False)
