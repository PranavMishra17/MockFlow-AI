"""
Tests for the owner-funded free-tier interview path and the dashboard stats
endpoint. The risky logic (which keys get used, and the abuse caps) is unit
tested here against mocked db methods + env.
"""

SYS = {
    "SYSTEM_LIVEKIT_URL": "wss://sys.livekit",
    "SYSTEM_LIVEKIT_API_KEY": "lk-owner",
    "SYSTEM_LIVEKIT_API_SECRET": "ls-owner",
    "SYSTEM_OPENAI_KEY": "sk-owner",
    "SYSTEM_DEEPGRAM_KEY": "dg-owner",
}

FULL_BYOK = {
    "livekit_url": "wss://user",
    "livekit_api_key": "lk-user",
    "livekit_api_secret": "ls-user",
    "openai_key": "sk-user",
    "deepgram_key": "dg-user",
}


def _enable_free_tier(monkeypatch, app_module):
    monkeypatch.setattr(app_module, "FREE_TIER_ENABLED", True)
    for k, v in SYS.items():
        monkeypatch.setenv(k, v)


# ---------- free_tier_available ----------

def test_free_tier_off_by_default(app_module, db_client, monkeypatch):
    monkeypatch.setattr(app_module, "FREE_TIER_ENABLED", False)
    assert app_module.free_tier_available("u1") is False


def test_free_tier_available_when_enabled_and_allowance_left(app_module, db_client, monkeypatch):
    _enable_free_tier(monkeypatch, app_module)
    monkeypatch.setattr(db_client, "free_calls_this_month", lambda m: 0)
    monkeypatch.setattr(db_client, "get_free_calls", lambda uid: (0, 2))
    assert app_module.free_tier_available("u1") is True


def test_free_tier_blocked_when_allowance_used(app_module, db_client, monkeypatch):
    _enable_free_tier(monkeypatch, app_module)
    monkeypatch.setattr(db_client, "free_calls_this_month", lambda m: 0)
    monkeypatch.setattr(db_client, "get_free_calls", lambda uid: (2, 2))
    assert app_module.free_tier_available("u1") is False


def test_monthly_killswitch_disables_free_tier(app_module, db_client, monkeypatch):
    _enable_free_tier(monkeypatch, app_module)
    monkeypatch.setattr(app_module, "FREE_TIER_MONTHLY_MAX_CALLS", 100)
    monkeypatch.setattr(db_client, "free_calls_this_month", lambda m: 100)
    monkeypatch.setattr(db_client, "get_free_calls", lambda uid: (0, 2))
    assert app_module.free_tier_available("u1") is False


def test_free_tier_needs_system_keys(app_module, db_client, monkeypatch):
    # Enabled, allowance left, but no SYSTEM_* keys configured -> unavailable.
    monkeypatch.setattr(app_module, "FREE_TIER_ENABLED", True)
    for k in SYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(db_client, "free_calls_this_month", lambda m: 0)
    monkeypatch.setattr(db_client, "get_free_calls", lambda uid: (0, 2))
    assert app_module.free_tier_available("u1") is False


# ---------- resolve_interview_keys ----------

def test_resolve_prefers_complete_byok(app_module, db_client, monkeypatch):
    monkeypatch.setattr(db_client, "get_api_keys", lambda uid: FULL_BYOK)
    keys, is_free, err = app_module.resolve_interview_keys("u1")
    assert err is None and is_free is False and keys == FULL_BYOK


def test_resolve_uses_free_tier_without_byok(app_module, db_client, monkeypatch):
    monkeypatch.setattr(db_client, "get_api_keys", lambda uid: None)
    _enable_free_tier(monkeypatch, app_module)
    monkeypatch.setattr(db_client, "free_calls_this_month", lambda m: 0)
    monkeypatch.setattr(db_client, "get_free_calls", lambda uid: (0, 2))
    keys, is_free, err = app_module.resolve_interview_keys("u1")
    assert err is None and is_free is True
    assert keys["openai_key"] == "sk-owner" and keys["livekit_url"] == "wss://sys.livekit"


def test_resolve_errors_without_byok_or_free(app_module, db_client, monkeypatch):
    monkeypatch.setattr(db_client, "get_api_keys", lambda uid: None)
    monkeypatch.setattr(app_module, "FREE_TIER_ENABLED", False)
    keys, is_free, err = app_module.resolve_interview_keys("u1")
    assert keys is None and is_free is False and err is not None


# ---------- resolve_openai_key (feedback path) ----------

def test_openai_key_prefers_byok(app_module, db_client, monkeypatch):
    monkeypatch.setattr(db_client, "get_api_keys", lambda uid: {"openai_key": "sk-user"})
    assert app_module.resolve_openai_key("u1") == "sk-user"


def test_openai_key_falls_back_to_owner_when_free_tier_on(app_module, db_client, monkeypatch):
    monkeypatch.setattr(db_client, "get_api_keys", lambda uid: None)
    _enable_free_tier(monkeypatch, app_module)
    assert app_module.resolve_openai_key("u1") == "sk-owner"


def test_openai_key_none_when_no_byok_and_free_tier_off(app_module, db_client, monkeypatch):
    monkeypatch.setattr(db_client, "get_api_keys", lambda uid: None)
    monkeypatch.setattr(app_module, "FREE_TIER_ENABLED", False)
    assert app_module.resolve_openai_key("u1") is None


# ---------- endpoints ----------

def test_user_stats_endpoint(auth_client, app_module, db_client, monkeypatch):
    monkeypatch.setattr(app_module, "FREE_TIER_ENABLED", True)
    monkeypatch.setattr(
        db_client, "get_user_stats",
        lambda uid: {"total_interviews": 3, "tracks": {"intro": 3}, "avg_overall_score": 4.1},
    )
    monkeypatch.setattr(db_client, "get_free_calls", lambda uid: (1, 2))
    resp = auth_client.get("/api/user/stats")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_interviews"] == 3
    assert body["free_calls_remaining"] == 1


def test_keys_status_reports_free_calls_when_enabled(auth_client, app_module, db_client, monkeypatch):
    monkeypatch.setattr(app_module, "FREE_TIER_ENABLED", True)
    monkeypatch.setattr(db_client, "get_api_keys", lambda uid: None)
    monkeypatch.setattr(db_client, "get_free_calls", lambda uid: (1, 2))
    resp = auth_client.get("/api/user/keys/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["has_keys"] is False
    assert body["free_calls_remaining"] == 1


def test_free_calls_hidden_when_feature_disabled(auth_client, app_module, db_client, monkeypatch):
    # Feature off (default): never surface free calls, even if the row grants some.
    monkeypatch.setattr(app_module, "FREE_TIER_ENABLED", False)
    monkeypatch.setattr(db_client, "get_api_keys", lambda uid: None)
    monkeypatch.setattr(db_client, "get_free_calls", lambda uid: (0, 2))
    resp = auth_client.get("/api/user/keys/status")
    assert resp.get_json()["free_calls_remaining"] == 0
