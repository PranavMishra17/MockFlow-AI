"""
Integration test for POST /api/feedback/verdict — proves the wiring:
the endpoint builds the rubric, calls the (mocked) judge model, and the
deterministic spine recomputes the verdict (evidence-less signal dropped,
recommendation rolled up from bands, delivery injected).
"""

import json

import pytest


_RAW_VERDICT = json.dumps({
    "overall": {"confidence": "medium", "headline": "Solid problem-solving, ownership stayed vague"},
    "signals": [
        {"name": "Problem-solving", "reasoning": "clarified inputs first", "band": "solid",
         "scope_met": "new_grad", "evidence": ["I'd clarify the inputs first"], "to_raise": "state complexity upfront"},
        {"name": "Coding", "reasoning": "claimed but no quote", "band": "outstanding",
         "scope_met": "mid", "evidence": [], "to_raise": "cleaner names"},
    ],
    "differentiators": ["a genuine point of view"],
})

_CREATE_KWARGS = {}


class _FakeOpenAI:
    def __init__(self, **kwargs):
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        _CREATE_KWARGS.update(kwargs)
        msg = type("M", (), {"content": _RAW_VERDICT})
        choice = type("C", (), {"message": msg})
        return type("R", (), {"choices": [choice]})


def test_verdict_endpoint_wires_evaluator(auth_client, app_module, db_client, monkeypatch):
    import openai

    ctx = (
        "CANDIDATE: I'd clarify the inputs first",      # interview_chat
        "Name: Test",                                    # candidate_profile
        "Role: Software Engineer",                       # job_summary
        {"candidate": "Test", "track": "coding",         # meta
         "job_role": "Software Engineer", "experience_level": "New Grad"},
        [{"role": "user", "text": "I'd clarify the inputs first"}],  # conversation
        {"user": [{"text": "I'd clarify the inputs first like you know", "timestamp": 0.0}]},  # raw
        None,                                            # error
    )
    monkeypatch.setattr(app_module, "_load_interview_context", lambda iid: ctx)
    monkeypatch.setattr(app_module, "resolve_openai_key", lambda uid: "sk-test")
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    saved = {}
    monkeypatch.setattr(db_client, "save_interview_scores",
                        lambda **k: saved.update(k) or True)
    monkeypatch.setattr(db_client, "get_coding_submissions", lambda iid: [])

    resp = auth_client.post("/api/feedback/verdict",
                            json={"interview_id": "00000000-0000-0000-0000-000000000abc"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["success"] is True

    verdict = body["verdict"]
    # evidence-less "Coding" signal must be downgraded to cannot_determine
    coding = [s for s in verdict["signals"] if s["name"] == "Coding"][0]
    assert coding["band"] == "cannot_determine"
    # only the evidence-backed "solid" signal counts -> lean_hire (not the LLM's gestalt)
    assert verdict["overall"]["recommendation"] == "lean_hire"
    # deterministic delivery block injected from code
    assert "delivery" in verdict and "wpm_band" in verdict["delivery"]
    # constructive next step + context attached
    assert verdict["gap_to_next"] is not None
    assert verdict["context"]["role"] == "swe"
    # judge ran deterministically
    assert _CREATE_KWARGS.get("temperature") == 0
    # and we persisted a row
    assert saved.get("track") == "coding"


_BEHAVIORAL_RAW_VERDICT = json.dumps({
    "overall": {"confidence": "medium", "headline": "Owns the story, thin on metrics"},
    "signals": [
        {"name": "Ownership", "reasoning": "first-person throughout", "band": "solid",
         "scope_met": "new_grad", "evidence": ["I decided to rewrite the pipeline"], "to_raise": "name the metric moved"},
        {"name": "Impact & metrics", "reasoning": "claimed impact, no quote", "band": "outstanding",
         "scope_met": "mid", "evidence": [], "to_raise": "quantify the result"},
    ],
    "differentiators": ["genuine ownership language"],
})


@pytest.mark.parametrize("track,raw_verdict,role_signal", [
    ("behavioral", _BEHAVIORAL_RAW_VERDICT, "Ownership"),
    ("technical_voice", _RAW_VERDICT.replace("Coding", "Technical depth").replace("Problem-solving", "Technical depth"), "Technical depth"),
    ("intro", _RAW_VERDICT.replace("Coding", "Self-awareness").replace("Problem-solving", "Motivation & authenticity"), "Motivation & authenticity"),
])
def test_verdict_endpoint_wires_non_coding_tracks(auth_client, app_module, db_client, monkeypatch, track, raw_verdict, role_signal):
    """The evaluator pipeline (build_rubric -> judge -> finalize_verdict) must
    work end-to-end for every track, not just coding (the only track the
    original integration test covered). Also proves the coding-only
    get_coding_submissions branch is skipped cleanly for non-coding tracks."""
    import openai

    class _FakeOpenAINonCoding:
        def __init__(self, **kwargs):
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **kwargs):
            msg = type("M", (), {"content": raw_verdict})
            choice = type("C", (), {"message": msg})
            return type("R", (), {"choices": [choice]})

    ctx = (
        "CANDIDATE: I decided to rewrite the pipeline",
        "Name: Test", "Role: Software Engineer",
        {"candidate": "Test", "track": track,
         "job_role": "Software Engineer", "experience_level": "New Grad"},
        [{"role": "user", "text": "I decided to rewrite the pipeline"}],
        {"user": [{"text": "I decided to rewrite the pipeline", "timestamp": 0.0}]},
        None,
    )
    monkeypatch.setattr(app_module, "_load_interview_context", lambda iid: ctx)
    monkeypatch.setattr(app_module, "resolve_openai_key", lambda uid: "sk-test")
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAINonCoding)
    saved = {}
    monkeypatch.setattr(db_client, "save_interview_scores", lambda **k: saved.update(k) or True)
    # get_coding_submissions must NOT be called for non-coding tracks; make it
    # raise so the test fails loudly if that branch is ever mistakenly entered.
    monkeypatch.setattr(db_client, "get_coding_submissions",
                        lambda iid: (_ for _ in ()).throw(AssertionError("should not be called for non-coding tracks")))

    resp = auth_client.post("/api/feedback/verdict",
                            json={"interview_id": "00000000-0000-0000-0000-000000000abd"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    verdict = resp.get_json()["verdict"]
    assert verdict["context"]["track"] == track
    named = {s["name"] for s in verdict["signals"]}
    assert role_signal in named
    assert saved.get("track") == track


def test_verdict_persists_feedback_even_if_scores_fail(auth_client, app_module, db_client, monkeypatch):
    """The recurring bug: save_interview_scores threw (table missing) and took
    save_feedback down with it, so the verdict persisted to NEITHER table and
    reopening regenerated. Feedback must save independently."""
    import openai

    ctx = (
        "CANDIDATE: I'd clarify the inputs first",
        "Name: Test", "Role: Software Engineer",
        {"candidate": "Test", "track": "coding", "job_role": "Software Engineer", "experience_level": "New Grad"},
        [{"role": "user", "text": "I'd clarify the inputs first"}],
        {"user": [{"text": "I'd clarify the inputs first", "timestamp": 0.0}]},
        None,
    )
    monkeypatch.setattr(app_module, "_load_interview_context", lambda iid: ctx)
    monkeypatch.setattr(app_module, "resolve_openai_key", lambda uid: "sk-test")
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    monkeypatch.setattr(db_client, "get_coding_submissions", lambda iid: [])

    def _boom(**k):
        raise RuntimeError("relation \"interview_scores\" does not exist")
    monkeypatch.setattr(db_client, "save_interview_scores", _boom)

    saved_fb = {}
    monkeypatch.setattr(db_client, "save_feedback",
                        lambda uid, iid, data: saved_fb.update({"iid": iid, "data": data}) or True)

    resp = auth_client.post("/api/feedback/verdict",
                            json={"interview_id": "00000000-0000-0000-0000-000000000abc"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    # the verdict reached the feedback table despite the scores-table failure
    assert saved_fb.get("iid") == "00000000-0000-0000-0000-000000000abc"
    assert "verdict" in saved_fb.get("data", {})


def test_verdict_endpoint_requires_interview_id(auth_client):
    resp = auth_client.post("/api/feedback/verdict", json={})
    assert resp.status_code == 400


# ---- GET /api/feedback/get/<id> ownership (the recurring reopen-403 bug) ----

def test_get_feedback_owner_match_with_uuid_typed_user_id(auth_client, db_client, monkeypatch):
    """psycopg returns the feedback.user_id UUID column as a uuid.UUID object,
    but the session user id is a str. The ownership check must normalize both
    sides — otherwise it ALWAYS 403s, the cache always misses, and the verdict
    is regenerated on every reopen (raised 3-4 times)."""
    import uuid as _uuid

    iid = "00000000-0000-0000-0000-0000000000fb"
    me = "00000000-0000-0000-0000-000000000001"  # the auth_client user id
    monkeypatch.setattr(db_client, "get_feedback", lambda i: {
        "interview_id": _uuid.UUID(iid),
        "user_id": _uuid.UUID(me),  # UUID object, exactly as psycopg3 returns it
        "feedback_data": {"verdict": {"overall": {"recommendation": "lean_hire"}}},
    })
    resp = auth_client.get(f"/api/feedback/get/{iid}")
    assert resp.status_code == 200, resp.get_data(as_text=True)


def test_get_feedback_rejects_other_users_row(auth_client, db_client, monkeypatch):
    """A genuinely different owner must still 403 (no ownership leak)."""
    import uuid as _uuid

    iid = "00000000-0000-0000-0000-0000000000fc"
    other = "00000000-0000-0000-0000-0000000000ff"
    monkeypatch.setattr(db_client, "get_feedback", lambda i: {
        "interview_id": _uuid.UUID(iid),
        "user_id": _uuid.UUID(other),
        "feedback_data": {"verdict": {}},
    })
    resp = auth_client.get(f"/api/feedback/get/{iid}")
    assert resp.status_code == 403


# ---- GET /api/user/compare (Wing D C6) ----

_A = "00000000-0000-0000-0000-00000000000a"
_B = "00000000-0000-0000-0000-00000000000b"
_C = "00000000-0000-0000-0000-00000000000c"


def _hist_row(iid, reco, track, band):
    return {"interview_id": iid, "track": track, "created_at": "2026-06-01T10:00:00",
            "scores": {"verdict": {"overall": {"recommendation": reco, "level_read": "new_grad"},
                                   "signals": [{"name": "Problem-solving", "band": band, "evidence": ["q"]}]}}}


def test_compare_endpoint_returns_aligned_verdicts(auth_client, db_client, monkeypatch):
    hist = [_hist_row(_A, "on_fence", "behavioral", "borderline"),
            _hist_row(_B, "hire", "coding", "outstanding")]
    monkeypatch.setattr(db_client, "get_user_score_history", lambda uid, limit=50: hist)
    monkeypatch.setattr(db_client, "get_user_feedback_history", lambda uid, limit=50: [])
    resp = auth_client.get(f"/api/user/compare?ids={_A},{_B}")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert len(body["sessions"]) == 2
    comp = {c["key"]: c for c in body["competencies"]}
    assert comp["problem_solving"]["delta"] == 2  # borderline -> outstanding


def test_compare_endpoint_rejects_unowned_id(auth_client, db_client, monkeypatch):
    monkeypatch.setattr(db_client, "get_user_score_history",
                        lambda uid, limit=50: [_hist_row(_A, "hire", "coding", "solid")])
    monkeypatch.setattr(db_client, "get_user_feedback_history", lambda uid, limit=50: [])
    resp = auth_client.get(f"/api/user/compare?ids={_A},{_C}")  # _C not owned
    assert resp.status_code == 404


def test_compare_endpoint_rejects_bad_uuid(auth_client, db_client, monkeypatch):
    monkeypatch.setattr(db_client, "get_user_score_history", lambda uid: [])
    resp = auth_client.get("/api/user/compare?ids=not-a-uuid,also-bad")
    assert resp.status_code == 400


def test_compare_endpoint_requires_at_least_two(auth_client, db_client, monkeypatch):
    monkeypatch.setattr(db_client, "get_user_score_history", lambda uid: [])
    resp = auth_client.get(f"/api/user/compare?ids={_A}")
    assert resp.status_code == 400
