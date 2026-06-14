"""
POST /api/user/keys supports PARTIAL updates: a blank or masked field keeps its
existing saved value, so a user can change one key without re-entering the rest.
"""


def test_partial_update_keeps_existing_for_masked_fields(auth_client, db_client, monkeypatch):
    existing = {
        "livekit_url": "wss://old.livekit.cloud",
        "livekit_api_key": "OLDKEY123",
        "livekit_api_secret": "OLDSECRET0123456789",
        "openai_key": "sk-oldoldoldold",
        "deepgram_key": "OLDDEEPGRAM0123456789",
    }
    saved = {}
    monkeypatch.setattr(db_client, "get_api_keys", lambda uid: dict(existing))
    monkeypatch.setattr(db_client, "save_api_keys",
                        lambda uid, lu, lk, ls, ok, dk: saved.update(
                            livekit_url=lu, livekit_api_key=lk, livekit_api_secret=ls,
                            openai_key=ok, deepgram_key=dk) or True)

    # Only the OpenAI key is changed; the rest are sent masked (the UI placeholder).
    resp = auth_client.post("/api/user/keys", json={
        "livekit_url": "••••••••",
        "livekit_api_key": "••••••••",
        "livekit_api_secret": "••••••••",
        "openai_key": "sk-brandnewkey999",
        "deepgram_key": "",
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["success"] is True
    # changed field updated, others preserved from existing
    assert saved["openai_key"] == "sk-brandnewkey999"
    assert saved["livekit_url"] == existing["livekit_url"]
    assert saved["deepgram_key"] == existing["deepgram_key"]


def test_first_time_setup_requires_all_keys(auth_client, db_client, monkeypatch):
    monkeypatch.setattr(db_client, "get_api_keys", lambda uid: None)  # no existing keys
    monkeypatch.setattr(db_client, "save_api_keys", lambda *a: True)

    resp = auth_client.post("/api/user/keys", json={
        "livekit_url": "wss://x.livekit.cloud",
        "openai_key": "sk-only",
        # missing the other three
    })
    assert resp.status_code == 400
    body = resp.get_json()
    assert "missing" in body
    assert "deepgram_key" in body["missing"]
