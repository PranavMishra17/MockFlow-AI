"""
Shared pytest fixtures.

The Flask app and data layer construct a live psycopg connection pool at import
time. To exercise the HTTP layer without a database we:
  1. seed dummy env vars so module-level config validation passes, and
  2. replace psycopg_pool.ConnectionPool with a stub BEFORE `db`/`app` import,
     so `DB()` never opens a real socket.

Per-test behavior is controlled by monkeypatching methods on the single shared
`db.db_client` instance (app and auth both import the same object).
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 1. Seed env so app.py's required-var validation passes (non-production mode).
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SECRET_KEY", "unit-test-secret-key")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("FLASK_ENV", "testing")

# 2. Stub the connection pool before db/app import it.
import psycopg_pool  # noqa: E402

psycopg_pool.ConnectionPool = MagicMock(name="StubConnectionPool")


@pytest.fixture
def app_module():
    import app as app_module

    app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    return app_module


@pytest.fixture
def client(app_module):
    return app_module.app.test_client()


@pytest.fixture
def db_client():
    import db

    return db.db_client


@pytest.fixture
def auth_client(client, db_client, monkeypatch):
    """A test client with an authenticated session (Flask-Login)."""
    fake_row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "email": "tester@example.com",
        "name": "Test User",
        "picture_url": "",
    }
    monkeypatch.setattr(db_client, "get_user", lambda uid: fake_row)
    with client.session_transaction() as sess:
        sess["_user_id"] = fake_row["id"]
        sess["_fresh"] = True
    return client
