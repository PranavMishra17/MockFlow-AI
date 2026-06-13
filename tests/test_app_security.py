"""
Tests for the immediate security/reliability hardening fixes.

Covers: health check (DB ping, not Supabase env), auth on previously-open
endpoints, request-size + cookie config, input validation, and the room-name
sanitiser helper.
"""


# ---------- /health ----------

def test_health_ok_when_db_reachable(client, db_client, monkeypatch):
    monkeypatch.setattr(db_client, "ping", lambda: True, raising=False)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "healthy"
    # The check must reflect the real database, not leftover Supabase config.
    assert "supabase" not in resp.get_data(as_text=True).lower()


def test_health_unhealthy_when_db_unreachable(client, db_client, monkeypatch):
    monkeypatch.setattr(db_client, "ping", lambda: False, raising=False)
    resp = client.get("/health")
    assert resp.status_code == 503
    assert "supabase" not in resp.get_data(as_text=True).lower()


# ---------- auth required on previously-open endpoints ----------

BLOCKED = (401, 302)  # 401 for JSON clients, redirect for browser navigations


def test_upload_resume_requires_auth(client):
    resp = client.post(
        "/api/upload-resume",
        headers={"Accept": "application/json"},
        data={"document_type": "resume"},
    )
    assert resp.status_code in BLOCKED


def test_conversation_cache_post_requires_auth(client):
    resp = client.post(
        "/api/conversation/cache",
        headers={"Accept": "application/json"},
        json={"conversation": {"agent": [], "user": []}},
    )
    assert resp.status_code in BLOCKED


def test_conversation_cache_get_requires_auth(client):
    resp = client.get(
        "/api/conversation/some-key",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code in BLOCKED


# ---------- request-size + cookie hardening (config) ----------

def test_max_content_length_is_capped(app_module):
    assert app_module.app.config["MAX_CONTENT_LENGTH"] == 10 * 1024 * 1024


def test_session_cookies_hardened(app_module):
    cfg = app_module.app.config
    assert cfg["SESSION_COOKIE_HTTPONLY"] is True
    assert cfg["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert cfg["REMEMBER_COOKIE_SAMESITE"] == "Lax"


def test_secret_key_is_not_the_hardcoded_default(app_module):
    assert app_module.app.secret_key != "dev-secret-key-change-in-prod"


# ---------- security headers ----------

def test_security_headers_present(client):
    resp = client.get("/api/auth/status")
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Referrer-Policy" in resp.headers


# ---------- CORS scoped (not wildcard) ----------

def test_cors_is_not_wildcard(client):
    resp = client.get(
        "/api/auth/status",
        headers={"Origin": "https://evil.example.com"},
    )
    assert resp.headers.get("Access-Control-Allow-Origin") != "*"


# ---------- input validation ----------

def test_coding_submit_rejects_non_uuid_interview_id(auth_client, db_client, monkeypatch):
    called = {"saved": False}

    def _spy(*a, **k):
        called["saved"] = True
        return "sid"

    monkeypatch.setattr(db_client, "save_coding_submission", _spy)
    resp = auth_client.post(
        "/api/coding/submit",
        json={"interview_id": "not-a-uuid", "code_submitted": "print(1)"},
    )
    assert resp.status_code == 400
    assert called["saved"] is False  # validation happens before the DB write


def test_user_interviews_limit_is_capped(auth_client, db_client, monkeypatch):
    captured = {}

    def _capture(user_id, limit):
        captured["limit"] = limit
        return []

    monkeypatch.setattr(db_client, "get_user_interviews", _capture)
    auth_client.get("/api/user/interviews?limit=99999")
    assert captured["limit"] <= 100


# ---------- room-name sanitiser ----------

def test_safe_room_component_strips_unsafe_chars(app_module):
    fn = app_module._safe_room_component
    assert fn("Jane Doe") == "jane-doe"
    assert fn("a/b<script>") == "abscript"
    assert fn("  ") == "candidate"
    assert all(c.islower() or c.isdigit() or c == "-" for c in fn("Aö9 #x"))
