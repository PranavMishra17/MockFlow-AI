"""
Authentication helpers — Authlib (Google OAuth) + Flask-Login.

Replaces the previous Supabase Auth integration. Exports the same names
the rest of the app already imports (`require_auth`, `get_current_user`,
`get_user_id`, `is_authenticated`) and matches the call-site shape — e.g.
`get_current_user().user.email` keeps working because we return a small
shim that mirrors Supabase's user object.

Wire-up in app.py:
    from auth_helpers import init_auth, register_auth_routes
    init_auth(app)
    register_auth_routes(app)
"""

import logging
import os
from functools import wraps
from typing import Optional

from authlib.integrations.flask_client import OAuth
from flask import jsonify, redirect, request, session, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_user,
    logout_user,
)

logger = logging.getLogger(__name__)

login_manager = LoginManager()
oauth = OAuth()

GOOGLE_DISCOVERY_URL = (
    "https://accounts.google.com/.well-known/openid-configuration"
)


class _UserMetadataShim(dict):
    """Mirrors Supabase's user.user_metadata.get('full_name'/'avatar_url')."""


class _UserInner:
    """Inner '.user' attribute on the shim, matching Supabase's response shape."""

    def __init__(self, row: dict) -> None:
        self.id = str(row["id"])
        self.email = row.get("email", "")
        self.user_metadata = _UserMetadataShim(
            full_name=row.get("name", ""),
            avatar_url=row.get("picture_url", ""),
        )


class AuthUser(UserMixin):
    """Flask-Login user. Wraps a row from the `users` table."""

    def __init__(self, row: dict) -> None:
        self._row = dict(row)
        self.id = str(row["id"])
        self.email = row.get("email", "")
        self.name = row.get("name", "")
        self.picture_url = row.get("picture_url", "")
        # Backwards-compat: existing call sites do `user.user.id` etc.
        self.user = _UserInner(row)

    def get_id(self) -> str:
        return self.id


def init_auth(app) -> None:
    """Initialize LoginManager + Authlib OAuth client. Call once at app startup."""
    secret = os.getenv("SECRET_KEY") or os.getenv("FLASK_SECRET_KEY")
    if secret and not app.secret_key:
        app.secret_key = secret

    login_manager.init_app(app)
    login_manager.login_view = "login"  # endpoint name of /auth/login

    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_CLOUD_CLIENT_SECRET"),
        server_metadata_url=GOOGLE_DISCOVERY_URL,
        client_kwargs={"scope": "openid email profile"},
    )

    @login_manager.user_loader
    def load_user(user_id: str) -> Optional[AuthUser]:
        from db import db_client
        row = db_client.get_user(user_id)
        return AuthUser(row) if row else None

    @login_manager.unauthorized_handler
    def _unauthorized():
        # JSON for XHR/fetch, redirect for browser navigations.
        if request.is_json or request.accept_mimetypes.best == "application/json":
            return jsonify({"error": "Authentication required"}), 401
        return redirect(url_for("login"))


def register_auth_routes(app) -> None:
    """Register /auth/login, /auth/google/callback, /auth/logout, /api/auth/status."""

    @app.route("/auth/login")
    def login():
        redirect_uri = url_for("auth_google_callback", _external=True)
        logger.info(f"[AUTH] Starting Google OAuth, callback={redirect_uri}")
        return oauth.google.authorize_redirect(redirect_uri)

    @app.route("/auth/google/callback")
    def auth_google_callback():
        from db import db_client
        try:
            token = oauth.google.authorize_access_token()
        except Exception as e:
            logger.error(f"[AUTH] OAuth callback failed: {e}", exc_info=True)
            return "Authentication failed", 401

        userinfo = token.get("userinfo") or {}
        email = userinfo.get("email")
        if not email:
            logger.error("[AUTH] Google returned no email claim")
            return "Authentication failed: no email", 401

        google_id = userinfo.get("sub", "")
        name = userinfo.get("name", "")
        picture = userinfo.get("picture", "")

        row = db_client.get_user_by_email(email)
        if not row:
            user_id = db_client.create_user(
                email=email,
                name=name,
                google_id=google_id,
                picture_url=picture,
            )
            if not user_id:
                logger.error(f"[AUTH] Failed to create user for {email}")
                return "Authentication failed: could not create user", 500
            row = db_client.get_user(user_id)

        if not row:
            return "Authentication failed: user not found after create", 500

        login_user(AuthUser(row), remember=True)
        logger.info(f"[AUTH] User logged in: {email} ({row['id']})")
        return redirect(url_for("dashboard"))

    @app.route("/auth/logout")
    def logout():
        # Drop any legacy keys from the Supabase era BEFORE logout_user(),
        # because logout_user() writes a "clear remember cookie" marker into
        # the session and session.clear() afterwards would wipe that marker,
        # leaving the remember cookie alive -> user gets re-logged-in on
        # the next request via the user_loader.
        for stale in ("access_token", "refresh_token"):
            session.pop(stale, None)
        logout_user()
        logger.info("[AUTH] User logged out")
        resp = redirect(url_for("index"))
        # Belt and suspenders: explicitly expire the remember cookie on the
        # response in case the session-based clear marker doesn't trigger
        # (e.g., behind certain proxies that strip cookies).
        resp.delete_cookie("remember_token")
        return resp

    @app.route("/api/auth/status")
    def auth_status():
        if not current_user.is_authenticated:
            return jsonify({"authenticated": False})
        return jsonify({
            "authenticated": True,
            "user": {
                "id": current_user.id,
                "email": current_user.email,
                "name": current_user.name,
                "avatar": current_user.picture_url,
            },
        })


def get_current_user() -> Optional[AuthUser]:
    """Return the AuthUser shim (with `.user.id`/`.user.email`) or None."""
    if not current_user.is_authenticated:
        return None
    return current_user


def get_user_id() -> Optional[str]:
    if not current_user.is_authenticated:
        return None
    return current_user.id


def is_authenticated() -> bool:
    return bool(current_user.is_authenticated)


def require_auth(f):
    """Decorator: require an authenticated user; JSON 401 or redirect to /auth/login."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            if request.is_json or request.accept_mimetypes.best == "application/json":
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper
