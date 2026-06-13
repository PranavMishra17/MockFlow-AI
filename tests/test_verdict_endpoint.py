"""
Integration test for POST /api/feedback/verdict — proves the wiring:
the endpoint builds the rubric, calls the (mocked) judge model, and the
deterministic spine recomputes the verdict (evidence-less signal dropped,
recommendation rolled up from bands, delivery injected).
"""

import json


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


def test_verdict_endpoint_requires_interview_id(auth_client):
    resp = auth_client.post("/api/feedback/verdict", json={})
    assert resp.status_code == 400
