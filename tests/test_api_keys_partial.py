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


# --------------------------------------------------------------------------
# Undecryptable rows (ENCRYPTION_KEY rotated at some point in the past)
# --------------------------------------------------------------------------

def test_undecryptable_keys_log_an_actionable_message_not_an_empty_one(caplog):
    """Found in production: 3 of 4 stored key rows could not be decrypted.

    Fernet's InvalidToken carries no message, so `f"...: {e}"` produced a bare
    "Error fetching API keys:" with nothing after the colon — a real, permanent
    data problem that was effectively invisible in the logs.
    """
    import logging

    from cryptography.fernet import Fernet

    import db as db_module

    client = db_module.DB.__new__(db_module.DB)
    # A key that did NOT encrypt the stored blob.
    client.cipher = Fernet(Fernet.generate_key())
    blob = Fernet(Fernet.generate_key()).encrypt(b"wss://someones.livekit.cloud").decode()

    client._fetchone = lambda *a, **k: {
        "livekit_url_encrypted": blob,
        "livekit_key_encrypted": blob,
        "livekit_secret_encrypted": blob,
        "openai_key_encrypted": blob,
        "deepgram_key_encrypted": blob,
    }

    with caplog.at_level(logging.ERROR):
        result = client.get_api_keys("user-123")

    assert result is None, "callers must see 'no keys', prompting re-entry"
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "cannot be decrypted" in msg
    assert "user-123" in msg
    assert "re-enter" in msg.lower()
    assert not msg.rstrip().endswith(":"), "must not log an empty reason"


def test_missing_row_still_returns_none_without_logging_an_error(caplog):
    """'No keys yet' is normal and must stay silent — otherwise the real
    decryption failure above is lost in noise."""
    import logging

    import db as db_module

    client = db_module.DB.__new__(db_module.DB)
    client._fetchone = lambda *a, **k: None

    with caplog.at_level(logging.ERROR):
        assert client.get_api_keys("user-123") is None
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
